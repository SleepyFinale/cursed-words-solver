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
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

from cursed_words_solver.rl import store
from cursed_words_solver.rl.env import CWEnv, pack, potential
from cursed_words_solver.sim.game.agent import Action, apply, clone, determinize

CURSED_MARGIN = 0.05   # take the cursed boss unless its P(win) is this much lower
# CWS_AI_CURSED_MARGIN=0 turns the cursed-boss preference (CURSED_MARGIN) off for A/B tests: the
# boss pick is then the look-ahead's (search on) or the best after-state P(win) (search off).
# Default "1" = on (the old behaviour).
CURSED_MARGIN_ENV = "CWS_AI_CURSED_MARGIN"
_MODEL_CACHE: dict[str, tuple[float, Any]] = {}
_WARNED_FALLBACK: set[str] = set()


def cursed_margin_on() -> bool:
    return os.environ.get(CURSED_MARGIN_ENV, "1").strip().lower() not in ("0", "off", "false", "no")


def _warn_fallback(path: Path) -> None:
    """Once per path: no pinned assistant policy, so the newest champion by mtime is used."""
    if str(path) in _WARNED_FALLBACK:
        return
    _WARNED_FALLBACK.add(str(path))
    import sys

    try:   # (a windowed app may have no usable stderr: never let the warning break policy_path)
        print(f"  AI assistant: no {store.RL_HOME / 'assistant_policy.pt'}; falling back to the newest "
              f"champion by mtime ({path})", file=sys.stderr, flush=True)
    except Exception:
        pass


def policy_path() -> Path | None:
    """The policy the assistant uses: ``rl/assistant_policy.pt`` if present, else the newest
    PPO champion, else the behaviour-cloned policy."""
    pinned = store.RL_HOME / "assistant_policy.pt"
    if pinned.is_file():
        return pinned
    found = sorted(store.RL_HOME.glob("ppo*/champion.pt"), key=lambda p: p.stat().st_mtime)
    if found:
        _warn_fallback(found[-1])
        return found[-1]
    bc = store.RL_HOME / "bc" / "best.pt"
    return bc if bc.is_file() else None


def _model_entry(path: Path) -> tuple[Any, bool]:
    """(policy, trained with target-build inputs) for a checkpoint, cached by mtime. ``Policy``
    widens old configs on load, so "conditioned" is read from the SAVED config."""
    import torch

    from cursed_words_solver.rl.model import ModelConfig, Policy, conditioned

    mt = path.stat().st_mtime
    hit = _MODEL_CACHE.get(str(path))
    if hit is None or hit[0] != mt:
        ck = torch.load(path, map_location="cpu", weights_only=False)
        m = Policy(ModelConfig(**ck["config"]))
        m.load_state_dict(ck["state"])
        m.eval()
        _MODEL_CACHE[str(path)] = (mt, m, conditioned(ck["config"], ck["state"]))
        hit = _MODEL_CACHE[str(path)]
    return hit[1], hit[2]


def _load(path: Path):
    return _model_entry(path)[0]


# --- target build (build-conditioned policies) ------------------------------------------------
# The live game is rebuilt from the export on every call, so the run's target is chosen once
# and persisted in RL_HOME/assistant_run_target.json until a new run is detected.
TARGET_ENV = "CWS_AI_TARGET"   # a plan ("Cards", "Red+Blue"), "free", "pivot" / "pivot:S", or "auto" (default: the table)
# Pivot mode ("pivot:S", from the env or a target_table.json band): the run starts FREE and,
# from stage S, at each shop entry the plan becomes the build the owned items lean to
# (``targets.pivot_update``, as the PPO pivot runs); the current plan persists with the run.


def _target_table_path() -> Path:
    return store.RL_HOME / "target_table.json"


def _run_target_path() -> Path:
    return store.RL_HOME / "assistant_run_target.json"


def _env_target() -> str | None:
    """CWS_AI_TARGET: None = auto (not set / "auto" / invalid), else the target ("" = FREE) or a
    pivot mode "pivot:S" ("pivot" = "pivot:2")."""
    from cursed_words_solver.rl.targets import FREE, canonical, parse_pivot_label, pivot_label

    raw = os.environ.get(TARGET_ENV, "").strip()
    if not raw or raw.lower() == "auto":
        return None
    if raw.lower() in ("free", "none"):
        return FREE
    ps = parse_pivot_label(raw)
    if ps is not None:
        return pivot_label(ps)
    try:
        return canonical(raw.replace("-", "+"))
    except ValueError:
        print(f"  {TARGET_ENV}={raw!r} is not a build plan; using auto", flush=True)
        return None


def _crown_matches(key: str, crown: int) -> bool:
    from cursed_words_solver.rl.targets import crown_matches

    return crown_matches(key, crown)


def _table_target(character: str, crown: int) -> str:
    """RL_HOME/target_table.json: {"version": 1, "table": {character: {"0-3": t, "4-7": t}}};
    t may be a plan, "free" / "", or a pivot mode "pivot:S" (``targets.table_target``; any
    error -> FREE)."""
    from cursed_words_solver.rl.targets import FREE, table_target

    try:
        return table_target(json.loads(_target_table_path().read_text(encoding="utf-8")), character, crown)
    except Exception:
        return FREE


def choose_target(character: str, crown: int) -> str:
    """The target build (or pivot mode "pivot:S") for a new run: CWS_AI_TARGET, else the target
    table, else FREE."""
    t = _env_target()
    return t if t is not None else _table_target(character, crown)


def _progress(game) -> tuple[int, float]:
    """(stage, node rank) in play order: the Meg shop (node 9) comes between the boss draft (6)
    and the boss fight (7), so it ranks 6.5."""
    from cursed_words_solver.sim.game.player import Node

    run = game.player.run
    node = run.node
    return int(run.stage), (6.5 if node == Node.MEG_SHOP else int(node))


def run_target(game) -> str:
    """The live run's target build (``run_target_info``)."""
    return run_target_info(game)[0]


def _pivot_step(game, st: dict) -> bool:
    """Pivot mode: at the first call of a new shop visit re-read the plan into ``st``
    (target / last_shop / since_stage / first_stage / switches). True if ``st`` changed."""
    from cursed_words_solver.rl.targets import pivot_update

    if getattr(game, "phase", None) != "shop":
        return False
    k = [int(game.player.run.stage), int(game.player.run.node)]
    if st.get("last_shop") == k:
        return False
    st["last_shop"] = k
    cur = str(st.get("target") or "")
    t = pivot_update(game, int(st["pivot_stage"]), cur)
    if t != cur:
        st["target"] = t
        st["since_stage"] = k[0]
        st["switches"] = int(st.get("switches", 0)) + 1
        if t and st.get("first_stage") is None:
            st["first_stage"] = k[0]
    return True


def _pivot_info(st: dict) -> dict:
    return {"pivot_stage": int(st["pivot_stage"]), "since_stage": st.get("since_stage"),
            "first_stage": st.get("first_stage"), "switches": int(st.get("switches", 0))}


def run_target_info(game, mode: str | None = None) -> tuple[str, dict | None]:
    """The live run's target build and, in pivot mode, the pivot state ({pivot_stage,
    since_stage, first_stage, switches}; else None). An explicit CWS_AI_TARGET plan always
    wins; otherwise the choice persisted for this run, or a new choice when a new run is
    detected (character / crown / mode changed, or progress went backwards). ``mode``: force a
    choice ("pivot:S" / a plan) as if it came from CWS_AI_TARGET. Pivot runs persist the
    current plan and re-read it at shop entries from their stage. Never raises."""
    import time

    from cursed_words_solver.rl.targets import FREE, canonical, parse_pivot_label

    env_t = mode if mode is not None else _env_target()
    if env_t is not None and parse_pivot_label(env_t) is None:
        return env_t, None
    try:
        if getattr(game.player.run, "challenge", None) is not None:
            return FREE, None   # quest runs: the quest fixes the plan; PPO trains them FREE only
        character, crown = game.player.character, int(game.player.run.ascension)
        prog = _progress(game)
    except Exception:
        return FREE, None
    path = _run_target_path()
    try:
        st = json.loads(path.read_text(encoding="utf-8"))
        same = (st.get("character") == character and int(st.get("crown")) == crown
                and tuple(float(x) for x in st.get("progress", (0, 0))) <= prog
                and (env_t is None or st.get("mode") == env_t))
        if same:
            changed = tuple(float(x) for x in st.get("progress")) != prog
            st["progress"] = list(prog)
            pivot = None
            if parse_pivot_label(st.get("mode") or "") is not None:
                changed = _pivot_step(game, st) or changed
                pivot = _pivot_info(st)
            t = canonical(str(st.get("target") or ""))
            if changed:
                _write_json(path, st)
            return t, pivot
    except Exception:
        pass
    choice = env_t if env_t is not None else choose_target(character, crown)
    st = {"character": character, "crown": crown, "target": choice, "progress": list(prog),
          "started": time.strftime("%Y-%m-%dT%H:%M:%S")}
    pivot = None
    ps = parse_pivot_label(choice) if choice else None
    if ps is not None:
        st.update(mode=choice, target=FREE, pivot_stage=ps, last_shop=None, since_stage=None, first_stage=None,
                  switches=0)
        _pivot_step(game, st)
        pivot = _pivot_info(st)
    _write_json(path, st)
    return str(st["target"]), pivot


def _write_json(path: Path, data: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        import threading

        tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        pass


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
    target: str | None = None    # the run's target build ("" = Free); None: the policy takes no target
    character: str = ""          # in-game character name (for the target line)
    pivot: dict | None = None    # pivot mode state (run_target_info); None: a fixed target
    on_plan: int = 0             # owned items on the target build (pivot line)

    def target_line(self) -> str:
        """"Target build: Cards" ("" when the policy is not build-conditioned)."""
        if self.target is None:
            return ""
        from cursed_words_solver.rl.targets import display as tdisplay

        who = f" for {self.character}" if self.character else ""
        if self.pivot:
            if not self.target:
                return f"Plan{who}: Free (pivot from stage {self.pivot['pivot_stage']})"
            name = tdisplay(self.target)
            at = self.pivot.get("since_stage") or self.pivot.get("first_stage")
            return (f"Plan{who}: {name} (pivoted at stage {at} - you own {self.on_plan} {name} "
                    f"item{'s' if self.on_plan != 1 else ''})")
        return f"Target build{who}: {tdisplay(self.target)}" + ("  (AI chooses)" if not self.target else "")

    def as_dict(self, top: int = 6) -> dict[str, Any]:
        """JSON-able summary for the app."""
        from cursed_words_solver.rl.targets import display as tdisplay

        return {"phase": self.phase, "p_win": self.p_win, "p_michael": self.p_michael,
                "exp_outcome": self.exp_outcome, "context": list(self.context), "plan": list(self.plan),
                "target": self.target, "target_display": tdisplay(self.target) if self.target is not None else None,
                "pivot": dict(self.pivot) if self.pivot else None, "target_line": self.target_line(),
                "pick": label(self.pick.action) if self.pick is not None else None,
                "pick_note": self.pick.note if self.pick is not None else "",
                "options": [{"label": label(o.action), "prob": o.prob, "p_win": o.p_win,
                             "exp_outcome": o.exp_outcome, "note": o.note} for o in self.options[:top]]}

    def text(self, top: int = 6) -> str:
        lines = [f"[{self.phase}]  P(win run) {self.p_win:.0%}  P(beat Michael) {self.p_michael:.0%}  "
                 f"expected outcome {self.exp_outcome:.1f}"]
        if self.target is not None:
            lines.append(f"  {self.target_line()}")
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
        if self.target is not None:
            rows.append(f"<b style='color:#fc6'>{H.escape(self.target_line())}</b>")
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
    return display(a.label or f"{a.kind} {a.args}")


_FIXED_NAMES = {"Pinata": "Piñata"}   # the export's name is mis-encoded ("Pi¤ata")


@lru_cache(maxsize=1)
def _display_pattern():
    """Item class -> in-game name, where they differ (26 differ beyond spacing, some swapped: the class
    ``EruptingVolcano`` is Disco Ball, ``PiggyBank`` is Coin Purse, ``MirrorBall`` is Banana)."""
    import re

    from cursed_words_solver.sim.game.items import catalog_rows

    names = {}
    for cls, row in catalog_rows().items():
        name = _FIXED_NAMES.get(cls) or row.get("name") or cls
        if name != cls:   # "JackOLantern" -> "Jack-o'-Lantern" as well as the swapped ones
            names[cls] = name
    if not names:
        return None, names
    return re.compile(r"\b(" + "|".join(sorted(map(re.escape, names), key=len, reverse=True)) + r")\b"), names


def display(text: str) -> str:
    """``text`` with item class names replaced by the names the game shows."""
    pat, names = _display_pattern()
    return pat.sub(lambda m: names[m.group(1)], text) if pat else text


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
        out.append("Frozen: " + display(", ".join(f"{o.item.game_class} (${getattr(o, 'cost', '?')})" for o in frozen)))
    if run.ascension >= 1:
        if not p.has_faced_uncursed_boss:
            out.append(f"Michael route: {len(run.cursed_bosses_defeated)}/5 cursed bosses beaten")
        else:
            out.append("Michael route lost (an uncursed boss was fought)")
    return out


def advise_game(game, *, cands=None, model_path: Path | None = None, plan_steps: int = 12,
                search: bool = True, target: str | None = None, boss_rule: int | None = None,
                arrange: bool | None = None) -> Advice:
    """``target``: the run's target build ("pivot:S" = pivot mode); None = ``run_target_info``
    (env / persisted / table) when the policy was trained with targets, else FREE. It is set on ``game`` before any env is
    attached, so every sub-env (look-ahead, after-states, shop plan) sees it via clones.
    ``boss_rule``: crown threshold of the uncursed-boss rule (``rules``; 0 = off; None =
    env CWS_AI_BOSS_RULE, default off); it overrides the boss-draft pick shown.
    ``arrange``: auto-arrange (``rules.best_arrangement``; None = env CWS_AI_ARRANGE, default
    ON, 0 turns it off): in an encounter / shop, when dragging Human Boy's hands (or Overhand / Underhand)
    scores more, the advice opens with "rearrange: move X to ... slot N" steps and every word /
    action is evaluated under the arranged order (on a copy: ``game`` is not changed)."""
    from cursed_words_solver.rl.model import Actor
    from cursed_words_solver.rl.targets import FREE, canonical, on_plan_count, parse_pivot_label, set_target
    from cursed_words_solver.sim.game.agent import Candidates

    cands = cands or Candidates(time_budget=2.0)
    path = model_path or policy_path()
    if path is None:
        raise FileNotFoundError("no trained policy yet (rl/bc/best.pt or rl/ppo*/champion.pt)")
    model, cond = _model_entry(Path(path))
    actor = Actor(model, greedy=True)
    pivot = None
    if not cond:
        tgt = FREE
    elif target is not None and parse_pivot_label(target) is not None:
        tgt, pivot = run_target_info(game, mode=f"pivot:{parse_pivot_label(target)}")
    elif target is not None:
        tgt = canonical(target) if target else FREE
    else:
        tgt, pivot = run_target_info(game)
    set_target(game, tgt)
    from cursed_words_solver.rl.rules import (ARRANGE_GRID, describe_drags, env_arrange_mode, grid_arrangement,
                                              has_positional, parse_arrange_mode)

    mode = env_arrange_mode() if arrange is None else parse_arrange_mode(arrange)
    arr = bool(mode and game.phase in ("shop", "encounter") and has_positional(game.player))
    grid_mode = arr and mode == ARRANGE_GRID
    shown = game
    if arr:
        game = clone(game)   # the drags are advice: evaluate on a copy
    env = CWEnv(cands, arrange=mode if arr else False)
    env.attach(game)
    if arr and game.phase == "shop":
        # probe-encounter order (encounters arrange in env.current()); grid mode: the order for the
        # first grid of the next encounter (grid-build effects), re-arranged for scoring once it exists
        env.auto_arrange()
    st, probs, v, aux = _evaluate(actor, env)
    steps = [display(s) for s in describe_drags(shown, env.arrange_log)] if arr and env.arrange_log else []
    if grid_mode and game.phase == "shop":
        steps = []   # grid mode: the drags go into the shop plan right before "leave" (after its buys)
    ph = game.phase
    if ph == "encounter" and game.encounter is not None and game.encounter.michael_draft is not None:
        ph = "michael_draft"
    adv = Advice(phase=ph, p_win=float(aux[0]), p_michael=float(aux[1]), exp_outcome=potential(game) + 8.0 * v,
                 context=_context(game), target=tgt if cond else None,
                 character=str(getattr(game.player, "character_name", "") or ""),
                 pivot=pivot if cond else None, on_plan=on_plan_count(game, tgt) if cond else 0)
    if steps:
        adv.context[:0] = steps   # first: the human drags these before anything else
    order = np.argsort(-probs)
    adv.options = [Option(st.cands[i].action, float(probs[i])) for i in order]
    if not adv.options:
        return adv
    adv.pick = adv.options[0]
    # search on: the pick is the eval's Searcher decision (play.py: Searcher.choose with the run's
    # pivot stage), keyed per decision; after-state P(win) values stay for display only
    skey = decision_key(game, ph)
    pstage = int(pivot["pivot_stage"]) if pivot and cond else 0
    if ph == "boss_draft":
        _boss_rule(adv, actor, game, cands)
        if search and not cursed_margin_on():
            ruled = adv.pick
            adv.pick = adv.options[0]   # the Searcher's pick (the policy argmax unless the look-ahead overrides)
            try:
                _look_ahead(adv, actor, env, st, probs, cands, key=skey, pivot_stage=pstage, set_values=False)
            except Exception as exc:  # advisory: keep the after-state pick
                adv.pick = ruled
                adv.context.append(f"look-ahead failed: {type(exc).__name__}: {exc}")
        _deploy_boss_rule(adv, game, boss_rule)
    elif ph in ("pin_reward", "michael_draft"):
        for o in adv.options:
            if o.action.kind not in ("pin", "michael_pick"):
                continue
            r = _value_after(actor, game, o.action, _fast(cands), "assist|after")
            if r is not None:
                o.p_win, _, o.exp_outcome = r
        if search:
            try:
                _look_ahead(adv, actor, env, st, probs, cands, key=skey, pivot_stage=pstage, set_values=False)
            except Exception as exc:  # advisory: keep the plain policy pick
                adv.context.append(f"look-ahead failed: {type(exc).__name__}: {exc}")
    elif ph in ("shop", "encounter"):
        if ph == "encounter":
            _encounter_notes(adv, game)
        if search:
            try:
                _look_ahead(adv, actor, env, st, probs, cands, key=skey, pivot_stage=pstage)
            except Exception as exc:  # advisory: keep the plain policy pick
                adv.context.append(f"look-ahead failed: {type(exc).__name__}: {exc}")
        if ph == "shop":
            adv.plan = _shop_plan(actor, shown if grid_mode else game, cands, plan_steps,
                                  first=adv.pick.action if adv.pick else None, grid=grid_mode)
        elif grid_mode and adv.pick is not None and adv.pick.action.kind in ("reroll_grid", "skip"):
            # a reroll / skip builds a grid: the hands are set for its grid-build effects, never for
            # scoring (rules.grid_arrangement, from the player's real order)
            via = "skip" if adv.pick.action.kind == "skip" else "reroll"
            verb = "skipping" if via == "skip" else "rerolling"
            del adv.context[:len(steps)]   # the scoring drags do not apply before a reroll / skip
            drags = grid_arrangement(clone(shown), cands, via=via)
            if drags:
                adv.context[:0] = ([f"before {verb}, {display(s)}" for s in describe_drags(shown, drags)]
                                   + [f"(then {via}; once the new grid appears, ask again for the scoring order)"])
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


def decision_key(game, phase: str | None = None) -> str:
    """Search key of the live decision: 'assist|' + blake2b(character, crown, stage, node, phase,
    gold, sorted owned item classes, rerolls of the current grid; in an encounter its grid number
    and target left, in a shop its stock count), all human-visible, so every decision gets its own
    determinized futures (the same state always gets the same ones)."""
    import hashlib

    try:
        p = game.player
        run = p.run
        enc = getattr(game, "encounter", None)
        items = sorted(str(it.game_class) for it in list(p.stickers) + list(p.stamps) if it is not None)
        parts = [str(p.character), int(run.ascension), int(run.stage), int(run.node),
                 str(phase if phase is not None else game.phase), int(p.money), items,
                 int(getattr(enc, "_grid_rerolls", 0) or 0) if enc is not None else 0]
        # visible progress inside one node (grid number, target left, shop restocks), so the
        # decisions of one encounter / shop do not all share one key (only appended when set)
        more = []
        if enc is not None:
            more += [int(enc.grids_generated), int(getattr(enc, "remaining_target", 0) or 0),
                     int(getattr(enc, "rerolls", 0) or 0)]
        shop = getattr(game, "shop", None)
        if shop is not None:
            more.append(int(getattr(shop, "_stocks", 0) or 0))
        if more:
            parts.append(more)
    except Exception:
        return "assist|search"
    h = hashlib.blake2b(json.dumps(parts).encode(), digest_size=8).hexdigest()
    return f"assist|{h}"


def _look_ahead(adv: Advice, actor, env, st, probs, cands, key: str = "assist|search", pivot_stage: int = 0,
                set_values: bool = True) -> None:
    """Play the top candidates forward on resampled futures (rl.search) and pick as
    ``Searcher.choose`` does with ``probs`` = the policy's (same gate, candidates, key and rule).
    ``pivot_stage`` > 0: rollouts re-read pivot targets (play.py's ``searcher.pivot_stage``).
    ``set_values`` False (drafts): keep the after-state values; the look-ahead goes in the notes."""
    from cursed_words_solver.rl.search import SearchConfig, Searcher, wants_search

    cfg = SearchConfig(**SEARCH_DEFAULT)
    if not wants_search(env, st, probs, cfg):
        return
    sr = Searcher(actor, cfg)
    sr.pivot_stage = int(pivot_stage or 0)
    if len(sr.candidates(probs, key)) < 2:
        return   # nothing to compare: the policy pick stands (Searcher.choose: "single")
    # rollouts arrange like the eval Searcher (play.py: _sub_env passes env.arrange on); off = unchanged
    sub = CWEnv(_fast(cands), arrange=getattr(env, "arrange", False))
    sub.attach(env.game)
    info = None
    if cfg.mode == "halving":
        info = sr.halving(sub, st, probs, key)
        sc = info["scores"]
    else:
        sc = sr.scores(sub, st, probs, key)
    if not sc:
        return
    by_action = {id(st.cands[i].action): i for i in sc}
    for o in adv.options:
        i = by_action.get(id(o.action))
        if i is None:
            continue
        v = sc[i]
        if set_values:
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
    if pick.action is not st.cands[int(np.argmax(probs))].action:
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
    if cursed and cursed_margin_on():
        c = max(cursed, key=lambda o: o.p_win)
        if route and c.p_win >= best.p_win - CURSED_MARGIN:
            pick = c
            if c is not best:
                c.note = f"cursed: kept on Michael's route (only {best.p_win - c.p_win:.0%} riskier)"
        elif not route and p.unpacked_of("BlessingOfTheFairies") and c.p_win >= best.p_win - CURSED_MARGIN / 2:
            pick = c
            c.note = "cursed: fairy for Blessing of the Fairies"
    adv.pick = pick


def _deploy_boss_rule(adv: Advice, game, boss_rule: int | None) -> None:
    """The deployment boss rule (``rules.uncursed_boss_override``) on the advice's pick."""
    from cursed_words_solver.rl.rules import env_boss_rule, parse_boss_rule, uncursed_boss_override

    n = env_boss_rule() if boss_rule is None else parse_boss_rule(boss_rule)
    if not n or adv.pick is None:
        return
    try:
        alt = uncursed_boss_override(game, adv.pick.action, [o.action for o in adv.options], n)
    except Exception:
        return
    if alt is None:
        return
    o = next(o for o in adv.options if o.action is alt)
    o.note = (o.note + f" uncursed: boss rule (crown >= {n}) overrides "
              f"{label(adv.pick.action)}").strip()
    adv.pick = o
    adv.context.append(f"Boss rule: at crown {n}+ take an uncursed boss over a cursed one")


def _shop_plan(actor, game, cands, steps: int, first: Action | None = None, grid: bool = False) -> list[str]:
    """Greedy policy plan for this shop; starts with ``first`` (the advice's pick, which the
    look-ahead may have changed) so the plan and the pick agree. ``grid`` (arrange mode "grid"):
    before "leave", the drags that set the hands for the next encounter's first grid
    (``rules.grid_arrangement`` on the inventory after the planned buys / sells; falls back to the
    score-mode shop order as ``CWEnv.auto_arrange`` does)."""
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
        if grid and a.kind == "leave":
            from cursed_words_solver.rl.rules import best_arrangement, describe_drags, grid_arrangement

            drags = grid_arrangement(clone(g), cands) or best_arrangement(clone(g), None, cands=cands)
            if drags:
                out.extend(display(s) for s in describe_drags(g, drags))
                out.append("(that order is for building the first grid: once it appears, ask again for the scoring order)")
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


# The policy was trained before the DLC (new pins, stickers, stamps, quests, glyphs and
# movement it has never seen), so its advice is off until it is retrained on the
# updated simulator. CWS_AI_ASSISTANT=1 turns it back on.
DISABLED_REASON = "disabled: the AI was trained before the DLC (set CWS_AI_ASSISTANT=1 to force it on)"


def unavailable_reason() -> str | None:
    """Why the assistant can't run in this interpreter (None when it can)."""
    import os

    if os.environ.get("CWS_AI_ASSISTANT", "").strip() != "1":
        return DISABLED_REASON
    try:
        import torch  # noqa: F401
    except Exception as exc:
        import sys
        return (f"torch not importable in {sys.executable} ({type(exc).__name__}: {exc}); "
                f"install it into this environment")
    if policy_path() is None:
        return "no trained policy yet (train one: python -m cursed_words_solver.rl.bc)"
    return None


def available() -> bool:
    return unavailable_reason() is None


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
    ap.add_argument("--target", default=None, help="target build (\"Cards\", \"Red+Blue\", \"free\", \"pivot:2\"); "
                    "default: CWS_AI_TARGET / this run's persisted choice / rl/target_table.json")
    args = ap.parse_args(argv)
    data = json.loads(Path(args.file).read_text(encoding="utf-8"))
    tgt = None if args.target is None else ("" if args.target.lower() == "free" else
                                            args.target if args.target.lower().startswith("pivot") else
                                            args.target.replace("-", "+"))
    adv = advise(data, model_path=Path(args.policy).expanduser() if args.policy else None, target=tgt)
    print(adv.text())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
