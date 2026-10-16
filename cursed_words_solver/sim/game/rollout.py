"""Rollout policy improvement: judge run decisions by playing them out.

For a candidate action, clone the game, apply it, then let a fast base policy
(``AdvicePolicy``) play to a horizon (end of the current stage's boss by default)
several times. The score of an action is its survival rate, then encounters cleared,
then money — a one-step policy-improvement over the base policy. Sampled futures use
common random numbers across candidates, so differences come from the action.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from cursed_words_solver.sim.game.agent import Action, Candidates, apply, clone, legal_actions
from cursed_words_solver.sim.game.core import Rng
from cursed_words_solver.sim.game.features import progress
from cursed_words_solver.sim.game.player import Node
from cursed_words_solver.sim.game.policy import AdvicePolicy, Policy, PowerConfig

if TYPE_CHECKING:  # pragma: no cover
    from cursed_words_solver.sim.game.run import Game


@dataclass
class RolloutConfig:
    samples: int = 3
    horizon_stages: int = 2  # play until this many stage bosses are beaten (or the run ends)
    money_weight: float = 0.002  # per $ left at the horizon (tie-break only)
    max_candidates: int = 5
    search_budget: float = 0.4  # word-search deadline inside rollouts


def _horizon_reached(g: "Game", stage0: int, horizon: int) -> bool:
    if g.phase == "done":
        return True
    run = g.player.run
    return run.stage >= stage0 + horizon and run.node in (Node.SHOP_ZERO, Node.ENCOUNTER_FIRST)


def rollout(game: "Game", action: Action | None, base: Policy, *, seed: str, horizon: int,
            max_steps: int = 2000) -> tuple[float, float, int]:
    """(survived, progress, money) after applying ``action`` then playing ``base``."""
    g = clone(game)
    g.rng = Rng(f"rollout|{seed}")
    if g.shop is not None:
        g.shop.rng = g.rng
    if g.encounter is not None:
        g.encounter.rng = g.rng
    stage0 = g.player.run.stage
    if hasattr(base, "_leave"):
        base._leave()  # fresh per-shop bookkeeping for this sampled future
    if action is not None:
        apply(g, action)
    steps = 0
    strength = 0.0
    while not _horizon_reached(g, stage0, horizon) and steps < max_steps:
        steps += 1
        a = base.act(g)
        target = g.encounter.total_target if (a.kind == "submit" and g.encounter is not None) else 0
        res = apply(g, a)
        if target > 0 and res is not None and hasattr(res, "score"):
            strength += max(0, res.score) / target  # points per word, in units of the target
    survived = 0.0 if g.won is False else 1.0
    return survived, strength + progress(g), g.player.money


class RolloutPolicy(Policy):
    """Advice policy whose shop / boss / pin choices are re-ranked by rollouts."""

    def __init__(self, cands: Candidates, cfg: RolloutConfig | None = None, seed: int = 0) -> None:
        self.cfg = cfg or RolloutConfig()
        self.fast = cands.with_budget(self.cfg.search_budget)
        self.base = AdvicePolicy(self.fast, PowerConfig(probe_seeds=1, probe_grids=2), seed=seed)
        self.play = AdvicePolicy(cands, PowerConfig(probe_seeds=1, probe_grids=2), seed=seed)
        self.seed = seed
        self._decision = 0

    def candidates(self, game: "Game") -> list[Action]:
        ph = game.phase
        acts = legal_actions(game)
        if ph == "boss_draft":
            return [a for a in acts if a.kind == "boss"]
        if ph == "pin_reward":
            return [a for a in acts if a.kind == "pin"]
        if ph != "shop":
            return []
        suggested = self.play._advice_shop(game)
        buys = [a for a in acts if a.kind in ("buy", "hippo") and a.args[0] != "tile"]
        out = [suggested]
        # Prefer upgrades of owned stickers, then the rest, up to max_candidates.
        owned = {i.game_class for i in game.player.stickers_list(for_comparison=True)}

        def key(a: Action) -> int:
            stock = game.shop.stickers if a.args[0] == "sticker" else game.shop.stamps
            o = stock[a.args[1]]
            return 0 if (o is not None and o.item.game_class in owned) else 1

        for a in sorted(buys, key=key):
            if a not in out:
                out.append(a)
            if len(out) >= self.cfg.max_candidates:
                break
        leave = Action("leave")
        if leave not in out:
            out.append(leave)
        return out

    def score(self, game: "Game", action: Action) -> tuple[float, float, float]:
        tot = [0.0, 0.0, 0.0]
        for s in range(self.cfg.samples):
            sv, pr, money = rollout(game, action, self.base, seed=f"{self.seed}|{self._decision}|{s}",
                                    horizon=self.cfg.horizon_stages)
            tot[0] += sv
            tot[1] += pr
            tot[2] += money
        n = float(self.cfg.samples)
        return (tot[0] / n, tot[1] / n + self.cfg.money_weight * tot[2] / n, 0.0)

    def act(self, game: "Game") -> Action:
        ph = game.phase
        if ph == "encounter":
            return self.play.act(game)
        cands = self.candidates(game)
        if len(cands) <= 1:
            return cands[0] if cands else self.play.act(game)
        self._decision += 1
        best, best_a = (-math.inf,), cands[0]
        for a in cands:
            sc = self.score(game, a)
            if sc > best:
                best, best_a = sc, a
        if ph == "shop":
            # keep the base policy's per-shop bookkeeping consistent
            if best_a.kind == "leave":
                self.play._leave()
        return best_a
