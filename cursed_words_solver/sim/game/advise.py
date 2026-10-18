"""Live advice: rebuild the current game from melmod's ``run_state.json`` and rank actions.

    python -m cursed_words_solver.sim.game.advise            # reads ~/.cursed_words_solver/run_state.json
    python -m cursed_words_solver.sim.game.advise --file some_round_log.json

- **Encounter**: the top engine words, a grid reroll and the best rack-tile placement are
  played out to the end of the encounter (``FastAdvicePolicy.plan_scores``): chance of
  clearing first, then money, item levels gained and rack tiles kept.
- **Shop / boss draft / pin reward**: every option is played out several times with the
  Advice policy to the end of the next two stage bosses (``rollout.py``) and ranked by
  survival, then points-per-word vs targets (``--mode power`` for the older probe ranking).
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


def advise(run_state: dict[str, Any], cands: Candidates | None = None, *, mode: str = "rollout",
           workers: int = 0) -> tuple[str, list[Advice]]:
    cands = cands or Candidates(time_budget=5.0)
    g = load_game(run_state)
    if g.encounter is not None:
        return "encounter", advise_encounter(g, cands)

    def rank(kinds):
        if mode == "power":
            return advise_power(g, cands, kinds)
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
                adv.note = f"{adv.note}; ends {risk.risk(b):.0%} of simulated runs".lstrip("; ")
        return "boss_draft", ranked
    if node == Node.BOSS_REWARD:
        return "pin_reward", rank(("pin",))
    return node.name.lower(), []


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="rank actions for the live game state")
    ap.add_argument("--file", default=str(Path.home() / ".cursed_words_solver" / "run_state.json"))
    ap.add_argument("--mode", default="rollout", choices=("rollout", "power"))
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args(argv)
    data = json.loads(Path(args.file).read_text(encoding="utf-8"))
    phase, ranked = advise(data, mode=args.mode, workers=args.workers)
    print(f"phase: {phase}")
    for i, adv in enumerate(ranked):
        bits = []
        if adv.p_clear is not None:
            bits.append(f"P(survive) {adv.p_clear:.0%}" if adv.note.startswith("survive") else f"P(clear) {adv.p_clear:.0%}")
        if adv.exp_money is not None:
            bits.append(f"money ${adv.exp_money:.0f}")
        if adv.value is not None:
            bits.append(f"value {adv.value:+.3f}")
        if adv.note:
            bits.append(adv.note)
        print(f"{'->' if i == 0 else '  '} {adv.action.label or adv.action.kind:40s} {'  '.join(bits)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
