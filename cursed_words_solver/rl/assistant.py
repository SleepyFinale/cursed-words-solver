"""Run assistant: the trained policy's advice for the live game state.

    python -m cursed_words_solver.rl.assistant                 # ~/.cursed_words_solver/run_state.json
    python -m cursed_words_solver.rl.assistant --file some_journal_or_round_log.json

For every decision type it ranks what a player can do, with the policy's probability and
the value head's estimates (expected final outcome, P(win), P(beat Michael)):

- encounter: which of the top words to play (not always the highest), grid reroll, skip,
  rack-tile placements, discards, reorders / sells;
- shop: a step plan (sell / buy / freeze / reorder ...) played forward on a copy until the
  policy would leave or restock (restock = press F8 again on the new stock);
- boss draft: each option's P(win) after picking it, with the cursed preference rule
  (prefer the cursed boss while still on Michael's route unless it is clearly riskier);
- pin reward, Michael's drafts: options ranked.

Frozen items and the stage plan (encounters, targets, boss options) are shown on every screen.
Only what the player can see is used: hidden state is resampled (``agent.determinize``).
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from cursed_words_solver.rl import store
from cursed_words_solver.rl.env import CWEnv, pack, potential
from cursed_words_solver.sim.game.agent import Action, apply, clone, determinize

CURSED_MARGIN = 0.05   # take the cursed boss unless its P(win) is this much lower
_MODEL_CACHE: dict[str, tuple[float, Any]] = {}


def policy_path() -> Path | None:
    """The policy the assistant uses: ``rl/assistant_policy.pt`` if present, else the newest
    PPO champion, else the behaviour-cloned policy."""
    pinned = store.RL_HOME / "assistant_policy.pt"
    if pinned.is_file():
        return pinned
    found = sorted(store.RL_HOME.glob("ppo*/champion.pt"), key=lambda p: p.stat().st_mtime)
    if found:
        return found[-1]
    bc = store.RL_HOME / "bc" / "best.pt"
    return bc if bc.is_file() else None


def _load(path: Path):
    from cursed_words_solver.rl.model import load_policy

    mt = path.stat().st_mtime
    hit = _MODEL_CACHE.get(str(path))
    if hit is None or hit[0] != mt:
        m, _ = load_policy(path)
        _MODEL_CACHE[str(path)] = (mt, m)
        hit = _MODEL_CACHE[str(path)]
    return hit[1]


@dataclass
class Option:
    action: Action
    prob: float
    p_win: float | None = None
    exp_outcome: float | None = None
    note: str = ""


@dataclass
class Advice:
    phase: str
    options: list[Option] = field(default_factory=list)
    plan: list[str] = field(default_factory=list)       # shop step plan
    pick: Option | None = None
    p_win: float = 0.0
    p_michael: float = 0.0
    exp_outcome: float = 0.0
    context: list[str] = field(default_factory=list)    # stage plan, frozen items, warnings

    def text(self, top: int = 6) -> str:
        lines = [f"[{self.phase}]  P(win run) {self.p_win:.0%}  P(beat Michael) {self.p_michael:.0%}  "
                 f"expected outcome {self.exp_outcome:.1f}"]
        lines += [f"  {c}" for c in self.context]
        if self.plan:
            lines.append("  Plan:")
            lines += [f"    {i + 1}. {s}" for i, s in enumerate(self.plan)]
        if self.pick is not None:
            lines.append(f"  -> {label(self.pick.action)}{('  ' + self.pick.note) if self.pick.note else ''}")
        for o in self.options[:top]:
            bits = [f"{o.prob:5.1%}"]
            if o.p_win is not None:
                bits.append(f"P(win) {o.p_win:.0%}")
            if o.note:
                bits.append(o.note)
            lines.append(f"     {label(o.action):44s} {'  '.join(bits)}")
        return "\n".join(lines)

    def html(self, top: int = 6) -> str:
        import html as H

        rows = [f"<b>AI ({H.escape(self.phase)})</b> &nbsp; win {self.p_win:.0%} &middot; Michael {self.p_michael:.0%}"]
        rows += [f"<span style='color:#9ab'>{H.escape(c)}</span>" for c in self.context]
        if self.plan:
            rows.append("<b>Plan:</b> " + " &rarr; ".join(H.escape(s) for s in self.plan))
        if self.pick is not None:
            rows.append(f"<b style='color:#7f7'>&#9654; {H.escape(label(self.pick.action))}</b> {H.escape(self.pick.note)}")
        for o in self.options[:top]:
            extra = f" &middot; win {o.p_win:.0%}" if o.p_win is not None else ""
            rows.append(f"{o.prob:.0%} &nbsp; {H.escape(label(o.action))}{extra} {H.escape(o.note)}")
        return "<br>".join(rows)


def label(a: Action) -> str:
    return a.label or f"{a.kind} {a.args}"


def _evaluate(actor, env: CWEnv):
    st = env.current()
    pk = pack(st)
    probs, v, aux = actor.evaluate(pk)
    return st, probs, v, aux


def _value_after(actor, game, action: Action, cands, key: str) -> tuple[float, float, float] | None:
    """(P(win), P(Michael), expected outcome) after taking ``action`` (hidden state resampled)."""
    from cursed_words_solver.rl.env import CWEnv

    g = determinize(clone(game), key)
    try:
        apply(g, action)
    except Exception:
        return None
    if g.phase == "done":
        from cursed_words_solver.sim.game.features import outcome

        return float(bool(g.won)), float(g.end_reason == "michael"), outcome(g)
    env = CWEnv(cands)
    st = env.attach(g)
    probs, v, aux = actor.evaluate(pack(st))
    return float(aux[0]), float(aux[1]), potential(g) + 8.0 * v


def _context(game) -> list[str]:
    from cursed_words_solver.sim.game.player import Node

    p = game.player
    run = p.run
    out = []
    try:
        st = max(1, run.stage)
        tg = [run.encounter_target(st, n, p) for n in (Node.ENCOUNTER_FIRST, Node.ENCOUNTER_SECOND, Node.BOSS)]
        bosses = ""
        if 0 < run.stage <= len(run.boss_drafts):
            opts = run.boss_drafts[run.stage - 1].options
            bosses = " / ".join(f"{b.game_class}{' (cursed)' if b.cursed else ''}" for b in opts)
        out.append(f"Stage {st} [{run.node.name.lower()}]: targets {tg[0]} -> shop -> {tg[1]} -> shop -> boss {tg[2]}"
                   + (f"  [{bosses}]" if bosses else ""))
    except Exception:
        pass
    frozen = [o for o in list(p.frozen_stickers) + list(p.frozen_stamps) if o is not None]
    if frozen:
        out.append("Frozen: " + ", ".join(f"{o.item.game_class} (${getattr(o, 'cost', '?')})" for o in frozen))
    if run.ascension >= 1:
        if not p.has_faced_uncursed_boss:
            out.append(f"Michael route: {len(run.cursed_bosses_defeated)}/5 cursed bosses beaten")
        else:
            out.append("Michael route lost (an uncursed boss was fought)")
    return out


def advise_game(game, *, cands=None, model_path: Path | None = None, plan_steps: int = 12,
                search: bool = True) -> Advice:
    from cursed_words_solver.rl.model import Actor
    from cursed_words_solver.sim.game.agent import Candidates

    cands = cands or Candidates(time_budget=2.0)
    path = model_path or policy_path()
    if path is None:
        raise FileNotFoundError("no trained policy yet (rl/bc/best.pt or rl/ppo*/champion.pt)")
    actor = Actor(_load(Path(path)), greedy=True)
    env = CWEnv(cands)
    env.attach(game)
    st, probs, v, aux = _evaluate(actor, env)
    ph = game.phase
    if ph == "encounter" and game.encounter is not None and game.encounter.michael_draft is not None:
        ph = "michael_draft"
    adv = Advice(phase=ph, p_win=float(aux[0]), p_michael=float(aux[1]), exp_outcome=potential(game) + 8.0 * v,
                 context=_context(game))
    order = np.argsort(-probs)
    adv.options = [Option(st.cands[i].action, float(probs[i])) for i in order]
    if not adv.options:
        return adv
    adv.pick = adv.options[0]
    if ph == "boss_draft":
        _boss_rule(adv, actor, game, cands)
    elif ph in ("pin_reward", "michael_draft"):
        for o in adv.options:
            if o.action.kind not in ("pin", "michael_pick"):
                continue
            r = _value_after(actor, game, o.action, _fast(cands), "assist|after")
            if r is not None:
                o.p_win, _, o.exp_outcome = r
    elif ph in ("shop", "encounter"):
        if ph == "encounter":
            _encounter_notes(adv, game)
        if search:
            try:
                _look_ahead(adv, actor, env, st, probs, cands)
            except Exception as exc:  # advisory: keep the plain policy pick
                adv.context.append(f"look-ahead failed: {type(exc).__name__}: {exc}")
        if ph == "shop":
            adv.plan = _shop_plan(actor, game, cands, plan_steps, first=adv.pick.action if adv.pick else None)
    return adv


# fresh-seed paired evals of champion u225 (2026-11-11, 125 runs each, vs plain 40.0% wins):
#   top 3 / 4 futures / horizon 2: 46.4% (t=1.86), ~5-36 s per shop call;  top 2 / 2 / 1: 41.6% (t=0.44), ~1-5 s
SEARCH_DEEP = {"top": 3, "sims": 4, "horizon": 2.0}
SEARCH_FAST = {"top": 2, "sims": 2, "horizon": 1.0}
# noise-aware: Gumbel-top-3, 4 shared futures each, +8 for the best two, override the policy only at paired t >= 1
SEARCH_HALVING = {"mode": "halving", "k": 3, "sims0": 4, "sims1": 4, "switch_t": 1.0, "horizon": 2.0}
# CWS_AI_SEARCH=fast picks the quick look-ahead, =halving the noise-aware one (default: deep;
# the app shows the plain advice first either way)
SEARCH_DEFAULT = dict({"fast": SEARCH_FAST, "halving": SEARCH_HALVING}.get(os.environ.get("CWS_AI_SEARCH", "").lower(),
                                                                         SEARCH_DEEP))


def _look_ahead(adv: Advice, actor, env, st, probs, cands) -> None:
    """Close shop / grid calls: play the top candidates forward on resampled futures (rl.search)."""
    from cursed_words_solver.rl.search import SearchConfig, Searcher, wants_search

    cfg = SearchConfig(**SEARCH_DEFAULT)
    if not wants_search(env, st, probs, cfg):
        return
    sub = CWEnv(_fast(cands))
    sub.attach(env.game)
    sr = Searcher(actor, cfg)
    info = None
    if cfg.mode == "halving":
        if len(sr.candidates(probs, "assist|search")) < 2:
            return   # nothing to compare: the policy pick stands
        info = sr.halving(sub, st, probs, "assist|search")
        sc = info["scores"]
    else:
        sc = sr.scores(sub, st, probs, "assist|search")
    if not sc:
        return
    by_action = {id(st.cands[i].action): i for i in sc}
    for o in adv.options:
        i = by_action.get(id(o.action))
        if i is None:
            continue
        v = sc[i]
        o.exp_outcome = v
        if info is not None:
            se = info["se"].get(i, 0.0)
            if i == info["policy"]:
                extra = f" n={info['n'][i]}"
            else:
                extra = f" ±{se:.2f} vs policy pick (t={info['t'][i]:.1f}) n={info['n'][i]}"
            o.note = (o.note + f" look-ahead {v:.1f}{extra}").strip()
        else:
            o.note = (o.note + f" look-ahead {v:.1f}").strip()
    best = info["pick"] if info is not None else max(sc, key=lambda i: (sc[i], probs[i]))
    pick = next(o for o in adv.options if o.action is st.cands[best].action)
    if pick is not adv.pick:
        pick.note = (pick.note + " (look-ahead overrides the policy)").strip()
        adv.pick = pick


def _fast(cands):
    """Deterministic quick search for after-state evaluation (the advice's own words use ``cands``)."""
    try:
        return cands.with_effort(0.05, cheap_floor=True)
    except Exception:
        return cands


def _boss_rule(adv: Advice, actor, game, cands) -> None:
    p = game.player
    route = p.run.ascension >= 1 and not p.has_faced_uncursed_boss
    opts = game.boss_options()
    for o in adv.options:
        if o.action.kind != "boss":
            continue
        r = _value_after(actor, game, o.action, _fast(cands), "assist|boss")
        if r is not None:
            o.p_win, _, o.exp_outcome = r
        b = opts[o.action.args[0]]
        o.note = "cursed" if b.cursed else ""
    bosses = [o for o in adv.options if o.action.kind == "boss" and o.p_win is not None]
    if not bosses:
        return
    best = max(bosses, key=lambda o: o.p_win)
    cursed = [o for o in bosses if o.note == "cursed"]
    pick = best
    if cursed:
        c = max(cursed, key=lambda o: o.p_win)
        if route and c.p_win >= best.p_win - CURSED_MARGIN:
            pick = c
            if c is not best:
                c.note = f"cursed: kept on Michael's route (only {best.p_win - c.p_win:.0%} riskier)"
        elif not route and p.unpacked_of("BlessingOfTheFairies") and c.p_win >= best.p_win - CURSED_MARGIN / 2:
            pick = c
            c.note = "cursed: fairy for Blessing of the Fairies"
    adv.pick = pick


def _shop_plan(actor, game, cands, steps: int, first: Action | None = None) -> list[str]:
    """Greedy policy plan for this shop; starts with ``first`` (the advice's pick, which the
    look-ahead may have changed) so the plan and the pick agree."""
    g = determinize(clone(game), "assist|shop")
    env = CWEnv(_fast(cands))
    env.attach(g)
    out = []
    for n in range(steps):
        st, probs, v, aux = _evaluate(actor, env)
        if not st.cands:
            break
        a = st.cands[int(np.argmax(probs))].action
        if n == 0 and first is not None:
            a = next((c.action for c in st.cands if label(c.action) == label(first)), a)
        out.append(label(a))
        if a.kind in ("leave", "reroll_shop"):
            if a.kind == "reroll_shop":
                out.append("(press F8 again after restocking)")
            break
        env.step(a)
        if g.phase != "shop":
            break
    return out


def placement_note(game, action: Action) -> str:
    """'place c at row 1 col 2, ...' for a submit that needs rack tiles placed first
    (rows counted from the top, columns from the left, both 1-based)."""
    if action.kind != "submit" or len(action.args) < 3 or not action.args[2]:
        return ""
    enc = game.encounter
    height = enc.grid.height if enc is not None and enc.grid is not None else 5
    bits = []
    for ri, x, y in action.args[2]:
        rack = game.player.consumables
        face = rack[ri].srep() if 0 <= ri < len(rack) and rack[ri] is not None else "?"
        bits.append(f"{face or '?'} at row {height - y} col {x + 1}")
    return "first place " + ", ".join(bits)


def _encounter_notes(adv: Advice, game) -> None:
    enc = game.encounter
    for o in adv.options:
        pn = placement_note(game, o.action)
        if pn and pn not in o.note:
            o.note = (pn + "; " + o.note).strip("; ")
    top = adv.pick.action if adv.pick else None
    if top is None:
        return
    pn = placement_note(game, top)
    if pn and pn not in adv.pick.note:
        adv.pick.note = (pn + "; " + adv.pick.note).strip("; ")
    words = [o for o in adv.options if o.action.kind == "submit"]
    if top.kind == "submit" and words and words[0].action is not top:
        pass
    if top.kind == "submit":
        best = max((int(o.action.label.rsplit("(", 1)[-1].rstrip(")")) for o in words if "(" in o.action.label), default=0)
        mine = int(top.label.rsplit("(", 1)[-1].rstrip(")")) if "(" in top.label else best
        if mine < best:
            adv.pick.note = (f"lower than the best ({best}) on purpose: better for the build / money "
                             + adv.pick.note).strip()
    elif top.kind == "reroll_grid":
        adv.pick.note = ("reroll this grid " + adv.pick.note).strip()
    if enc is not None:
        adv.context.append(f"Grid {max(1, enc.total_grids - enc.remaining_grids)}/{enc.total_grids}, "
                           f"{enc.remaining_target} still needed, rerolls {enc.rerolls}")


def advise(run_state: dict[str, Any], **kw) -> Advice:
    from cursed_words_solver.sim.game.advise import load_game

    return advise_game(load_game(run_state), **kw)


ASSISTANT_DECISIONS = ("boss_draft", "pin_reward", "michael_draft")
_APP_CANDS = None
_APP_CANDS_SEARCH = None


def decision_of(run_state: dict[str, Any] | None) -> str:
    """melmod 1.5 ``extras.decision``; older exports: from the node type."""
    if not isinstance(run_state, dict):
        return "none"
    extras = run_state.get("extras") if isinstance(run_state.get("extras"), dict) else {}
    d = str(extras.get("decision") or "").strip()
    if d:
        return d
    node = str(((run_state.get("game_state") or {}).get("run") or {}).get("node_type") or extras.get("run_node_type") or "")
    return {"BossDraft": "boss_draft", "BossReward": "pin_reward"}.get(node, "none")


def available() -> bool:
    try:
        import torch  # noqa: F401
    except Exception:
        return False
    return policy_path() is not None


def app_advice(run_state: dict[str, Any], *, budget: float = 1.5, search: bool = False) -> Advice | None:
    """Advice for the solver app; None when no policy / no game_state (never raises).
    ``search``: add the look-ahead on close shop / grid calls (10-30 s, so the app shows the
    plain advice first and re-emits)."""
    global _APP_CANDS, _APP_CANDS_SEARCH
    if not available() or not isinstance(run_state, dict) or "game_state" not in run_state:
        return None
    try:
        from cursed_words_solver.sim.game.agent import Candidates

        # the look-ahead runs on its own app thread: give it its own engine instance
        if search:
            if _APP_CANDS_SEARCH is None:
                _APP_CANDS_SEARCH = Candidates(time_budget=budget)
            return advise(run_state, cands=_APP_CANDS_SEARCH, search=True)
        if _APP_CANDS is None:
            _APP_CANDS = Candidates(time_budget=budget)
        return advise(run_state, cands=_APP_CANDS, search=False)
    except Exception as exc:  # advisory only
        print(f"  AI assistant unavailable: {type(exc).__name__}: {exc}", flush=True)
        return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="AI run assistant for the live game state")
    ap.add_argument("--file", default=str(Path.home() / ".cursed_words_solver" / "run_state.json"))
    ap.add_argument("--policy", default="")
    args = ap.parse_args(argv)
    data = json.loads(Path(args.file).read_text(encoding="utf-8"))
    adv = advise(data, model_path=Path(args.policy).expanduser() if args.policy else None)
    print(adv.text())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
