"""Live advice: rebuild the current game from melmod's ``run_state.json`` and rank actions.

    python -m cursed_words_solver.sim.game.advise            # reads ~/.cursed_words_solver/run_state.json
    python -m cursed_words_solver.sim.game.advise --file some_round_log.json

- **Encounter**: the top engine words, a grid reroll and the best rack-tile placement are
  played out to the end of the encounter (``FastAdvicePolicy.plan_scores``): chance of
  clearing first, then money, item levels gained and rack tiles kept.
- **Shop / boss draft / pin reward**: every option is played out several times with the
  Advice policy to the end of the next two stage bosses (``rollout.py``) and ranked by
  survival, then points-per-word vs targets (``--mode power`` for the older probe ranking).
  An instant "AI pick" (tuned policy + boss-risk table + the learning loop's champion
  model) is printed first; ``--mode quick`` prints only that.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cursed_words_solver.sim.game.agent import Action, Candidates, apply, clone, legal_actions, spawn_pool
from cursed_words_solver.sim.game.player import Node
from cursed_words_solver.sim.game.policy import PowerConfig, PowerPolicy


@dataclass
class Advice:
    action: Action
    p_clear: float | None = None
    exp_money: float | None = None
    value: float | None = None
    note: str = ""


def load_game(run_state: dict[str, Any], *, seed: int = 0):
    """``Game`` positioned where the live game is (encounter / shop / draft / reward)."""
    from cursed_words_solver.sim.game.importer import game_from_game_state
    from cursed_words_solver.sim.game.shop import Shop

    gs = run_state.get("game_state") if "game_state" in run_state else run_state
    if isinstance(run_state.get("capture"), dict):
        gs = run_state["capture"].get("pre_submit")
    if not isinstance(gs, dict):
        raise ValueError("no game_state in run_state (melmod 1.4+ required)")
    g = game_from_game_state(gs, seed=seed)
    node = g.player.run.node
    if node in (Node.SHOP_ZERO, Node.SHOP_ONE, Node.SHOP_TWO, Node.MEG_SHOP) or "grid" not in gs:
        g.encounter = None
        shop = run_state.get("shop")
        if isinstance(shop, dict) and node in (Node.SHOP_ZERO, Node.SHOP_ONE, Node.SHOP_TWO, Node.MEG_SHOP):
            g.shop = Shop.from_snapshot(g.player, g.rng, shop)
    return g


def advise_encounter(game, cands: Candidates, *, top_n: int = 6, samples: int = 6) -> list[Advice]:
    """Top words, a grid reroll and the best rack-tile placement, ranked by the encounter
    planner (``FastAdvicePolicy.plan_scores``): P(clear) first, then money, item levels
    gained and rack tiles kept when the encounter ends."""
    from cursed_words_solver.sim.game.policy import FastAdvicePolicy, tuned_config

    enc = game.encounter
    if enc.michael_draft is not None or enc.finale or enc.awaiting_forced_sell:
        return [Advice(a) for a in legal_actions(game, cands, top_n=top_n)]
    pol = FastAdvicePolicy(cands, tuned_config(plan_words=top_n))
    out = []
    for value, p_clear, a in pol.plan_scores(game, samples=samples):
        out.append(Advice(a, p_clear=p_clear, value=value,
                          note="value = $ + item levels + rack tiles at encounter end"))
    return out


def advise_power(game, cands: Candidates, kinds: tuple[str, ...]) -> list[Advice]:
    pol = PowerPolicy(cands, PowerConfig())
    base = pol.power(game)
    out: list[Advice] = []
    money = game.player.money
    for a in legal_actions(game, cands):
        if a.kind not in kinds:
            continue
        g = clone(game)
        try:
            apply(g, a)
        except Exception as exc:  # pragma: no cover - surfaced in the listing
            out.append(Advice(a, note=f"error: {exc}"))
            continue
        if a.kind in ("leave", "boss", "pin") and g.phase == "encounter":
            v = pol.power(game) if a.kind == "leave" else pol.power(g)
        else:
            v = pol.power(g)
        spent = money - g.player.money
        rel = (v - base) / max(1.0, base)
        out.append(Advice(a, value=rel - pol.cfg.money_weight * spent,
                          note=f"power {v:.0f} vs {base:.0f}, spend ${spent}"))
    out.sort(key=lambda adv: adv.value if adv.value is not None else -1e9, reverse=True)
    return out


_POOL_CANDS: Candidates | None = None


def _pool_init(wordlist: str | None) -> None:
    global _POOL_CANDS
    _POOL_CANDS = Candidates(Path(wordlist) if wordlist else None, time_budget=2.0)


def _pool_score(job: tuple) -> tuple[float, float, float]:
    from cursed_words_solver.sim.game.rollout import RolloutConfig, RolloutPolicy

    game, action, samples = job
    pol = RolloutPolicy(_POOL_CANDS, RolloutConfig(samples=samples))
    return pol.score(game, action)


def advise_rollout(game, cands: Candidates, kinds: tuple[str, ...], *, samples: int = 6,
                   workers: int = 0) -> list[Advice]:
    """Rank options by playing each out (Advice base policy, two stage bosses ahead)."""
    acts = [a for a in legal_actions(game, cands) if a.kind in kinds]
    if workers > 1 and len(acts) > 1:
        with spawn_pool(min(workers, len(acts)), initializer=_pool_init,
                                          initargs=(str(cands.wordlist) if cands.wordlist else None,)) as pool:
            scores = pool.map(_pool_score, [(game, a, samples) for a in acts])
    else:
        from cursed_words_solver.sim.game.rollout import RolloutConfig, RolloutPolicy

        pol = RolloutPolicy(cands, RolloutConfig(samples=samples))
        scores = [pol.score(game, a) for a in acts]
    out = [Advice(a, p_clear=sc[0], value=sc[1], note="survive 2 bosses / strength") for a, sc in zip(acts, scores)]
    out.sort(key=lambda adv: (adv.p_clear or 0, adv.value or 0), reverse=True)
    return out


def _keyed_job(job: tuple) -> float:
    """Outcome of one keyed full-run play-out (worker side of ``advise_keyed``)."""
    from cursed_words_solver.sim.game import expert as E

    game, action, seed = job
    roll = E.NetPolicy(E._CANDS.with_effort(E.ROLL_EFFORT, cheap_floor=True), E._MODEL, seed=1,
                       boss_risk=_risk_path())
    roll.cfg.placement_targets = E.ROLL_TARGETS
    return E.play_out(game, action, roll, seed, keyed=True)


def _risk_path() -> str:
    from cursed_words_solver.sim.game.bossrisk import DEFAULT_PATH

    return str(DEFAULT_PATH) if DEFAULT_PATH.is_file() else ""


def advise_keyed(game, cands: Candidates, *, samples: int = 8, workers: int = 8) -> list[Advice]:
    """Shop / boss / pin / Michael options, each played to the end of the run ``samples``
    times with keyed randomness (every option sees the same grids and shops wherever the
    branches meet), ranked by mean outcome (encounters cleared; a win = 16). ``value`` is
    the paired gain over the base suggestion, with its standard error in the note."""
    import numpy as np

    from cursed_words_solver.sim.game import expert as E
    from cursed_words_solver.sim.game.agent import spawn_pool

    pol = E.NetPolicy(cands, None, boss_risk=_risk_path())
    options = pol.candidates(game)
    if not options:
        return []
    jobs = [(game, a, f"advise|{k}") for a in options for k in range(samples)]
    if workers > 1:
        with spawn_pool(min(workers, len(jobs)), E._init, (str(cands.wordlist) if cands.wordlist else None, None)) as pool:
            ys = pool.map(_keyed_job, jobs)
    else:
        E._init(str(cands.wordlist) if cands.wordlist else None, None)
        ys = [_keyed_job(j) for j in jobs]
    Y = np.array(ys, float).reshape(len(options), samples)
    out = []
    for i, a in enumerate(options):
        d = Y[i] - Y[0]
        se = float(d.std(ddof=1) / np.sqrt(samples)) if samples > 1 else 0.0
        tag = "base suggestion" if i == 0 else f"{d.mean():+.2f} ± {se:.2f} vs base"
        out.append(Advice(a, value=float(Y[i].mean()), p_clear=float(np.mean(Y[i] >= 16)),
                          note=f"win {np.mean(Y[i] >= 16):.0%}; {tag}"))
    out.sort(key=lambda adv: adv.value, reverse=True)
    return out


def champion_path() -> Path | None:
    """Most recently promoted learning-loop model (``sim_models/*/champion.npz``)."""
    found = sorted((Path.home() / ".cursed_words_solver" / "sim_models").glob("*/champion.npz"),
                   key=lambda f: f.stat().st_mtime)
    return found[-1] if found else None


def quick_pick(game, cands: Candidates, model: Path | None = None) -> Action:
    """Instant recommendation for a shop / boss / pin / Michael decision: the tuned policy
    (Advice + boss-risk table) with the learning loop's champion model on top."""
    from cursed_words_solver.sim.game.bossrisk import DEFAULT_PATH
    from cursed_words_solver.sim.game.expert import NetPolicy
    from cursed_words_solver.sim.game.learn import load_model

    model = model or champion_path()
    pol = NetPolicy(cands, load_model(model) if model else None,
                    boss_risk=str(DEFAULT_PATH) if DEFAULT_PATH.is_file() else "")
    return pol.act(game)


def advise(run_state: dict[str, Any], cands: Candidates | None = None, *, mode: str = "keyed",
           workers: int = 0) -> tuple[str, list[Advice]]:
    """Ranked options for the live decision. ``mode``: ``keyed`` (each option played to the
    end of the run with keyed randomness, ~30 s on 8 workers), ``rollout`` (older two-stage
    rollouts), ``power`` (probe ranking) or ``quick`` (the AI pick only, instant)."""
    cands = cands or Candidates(time_budget=5.0)
    g = load_game(run_state)
    if g.encounter is not None:
        return "encounter", advise_encounter(g, cands)
    if mode == "quick":
        phase = "shop" if g.shop is not None else g.player.run.node.name.lower()
        return phase, [Advice(quick_pick(g, cands), note="AI pick (tuned policy + champion model)")]

    def rank(kinds):
        if mode == "power":
            return advise_power(g, cands, kinds)
        if mode == "keyed":
            return advise_keyed(g, cands, workers=max(1, workers))
        return advise_rollout(g, cands, kinds, workers=workers)

    if g.shop is not None:
        return "shop", rank(("buy", "sell", "hippo", "reroll_shop", "leave"))
    node = g.player.run.node
    if node == Node.BOSS_DRAFT:
        from cursed_words_solver.sim.game.bossrisk import BossRisk

        ranked = rank(("boss",))
        risk = BossRisk.load()
        if risk.counts:
            opts = g.boss_options()
            for adv in ranked:
                b = opts[adv.action.args[0]]
                adv.note = f"{adv.note}; ends {risk.risk(b, g.player.run.ascension, g.player.character):.0%} of simulated runs".lstrip("; ")
        return "boss_draft", ranked
    if node == Node.BOSS_REWARD:
        return "pin_reward", rank(("pin",))
    return node.name.lower(), []


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="rank actions for the live game state")
    ap.add_argument("--file", default=str(Path.home() / ".cursed_words_solver" / "run_state.json"))
    ap.add_argument("--mode", default="keyed", choices=("keyed", "rollout", "power", "quick"))
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args(argv)
    data = json.loads(Path(args.file).read_text(encoding="utf-8"))
    phase, ranked = advise(data, mode=args.mode, workers=args.workers)
    print(f"phase: {phase}")
    if phase != "encounter" and args.mode != "quick" and ranked:
        try:
            pick = quick_pick(load_game(data), Candidates(time_budget=5.0))
            print(f"AI pick (instant): {pick.label or pick.kind} {pick.args if not pick.label else ''}")
        except Exception as exc:  # pragma: no cover - advisory only
            print(f"AI pick unavailable: {exc}")
    for i, adv in enumerate(ranked):
        bits = []
        keyed = adv.note.startswith("win ")
        if adv.p_clear is not None and not keyed:
            bits.append(f"P(survive) {adv.p_clear:.0%}" if adv.note.startswith("survive") else f"P(clear) {adv.p_clear:.0%}")
        if adv.exp_money is not None:
            bits.append(f"money ${adv.exp_money:.0f}")
        if adv.value is not None:
            bits.append(f"encounters {adv.value:.2f}" if keyed else f"value {adv.value:+.3f}")
        if adv.note:
            bits.append(adv.note)
        print(f"{'->' if i == 0 else '  '} {adv.action.label or adv.action.kind:40s} {'  '.join(bits)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
