"""``CWEnv``: one human decision per step over a simulated run.

Reward is the increase of a potential Φ (encounters cleared + share of the current
encounter's target reached), so the episode return telescopes to the run's ``outcome``
(win 16, Michael win 24; a loss scores how far it got). Dense, and it doesn't change which
policy is optimal.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

from cursed_words_solver.rl.actions import ANYTIME, CandidateBuilder, Cand, Limits
from cursed_words_solver.rl.obs import Obs, observe
from cursed_words_solver.sim.game.agent import Action, apply
from cursed_words_solver.sim.game.features import outcome, progress

if TYPE_CHECKING:  # pragma: no cover
    from cursed_words_solver.sim.game.agent import Candidates
    from cursed_words_solver.sim.game.run import Game

MAX_STEPS = 1500


def potential(game: "Game") -> float:
    if game.phase == "done":
        return outcome(game)
    base = progress(game)
    enc = game.encounter
    if enc is not None and enc.total_target > 0 and enc.michael_draft is None:
        base += max(0.0, min(1.0, 1.0 - enc.remaining_target / enc.total_target))
    return base


@dataclass
class Step:
    obs: Obs
    cands: list[Cand]


def pack(step: Step) -> dict[str, np.ndarray]:
    """Arrays for the model: refs resolved to token indices (-1 = none)."""
    o, cs = step.obs, step.cands
    A = len(cs)
    from cursed_words_solver.rl.actions import n_action_features

    feat = np.zeros((A, n_action_features()), dtype=np.float32)
    atype = np.zeros(A, dtype=np.int64)
    r1 = np.full(A, -1, dtype=np.int64)
    r2 = np.full(A, -1, dtype=np.int64)
    for i, c in enumerate(cs):
        feat[i] = c.feat
        atype[i] = c.atype
        if c.ref1 is not None:
            r1[i] = o.refs.get(c.ref1, -1)
        if c.ref2 is not None:
            r2[i] = o.refs.get(c.ref2, -1)
    return {"glob": o.glob, "tok_type": o.tok_type, "tok_cls": o.tok_cls, "tok_feat": o.tok_feat,
            "act_type": atype, "act_ref1": r1, "act_ref2": r2, "act_feat": feat}


class CWEnv:
    def __init__(self, cands: "Candidates", limits: Limits | None = None) -> None:
        self.builder = CandidateBuilder(cands, limits)
        self.game: "Game | None" = None
        self.point_anytime = 0
        self.shop_actions = 0
        self.steps = 0
        self._shop_id = None
        self.phi = 0.0

    def reset(self, *, character: str, crown: int, seed: int, quest: str | None = None, wordlist=None) -> Step:
        from cursed_words_solver.sim.game.run import Game, RunConfig

        self.game = Game(RunConfig(character=character, ascension=crown, challenge=quest, seed=seed,
                                   wordlist=wordlist or self.builder.cands.wordlist))
        return self.attach(self.game)

    def attach(self, game: "Game") -> Step:
        """Start from an existing game (live advice, imported captures)."""
        self.game = game
        self.point_anytime = 0
        self.shop_actions = 0
        self.steps = 0
        self._shop_id = id(game.shop) if game.shop is not None else None
        self.phi = potential(game)
        return self.current()

    def current(self) -> Step:
        g = self.game
        key = f"after|{g.player.run.stage}|{g.player.run.node}|{self.steps}"
        cs = self.builder.build(g, point_anytime=self.point_anytime, shop_actions=self.shop_actions, key=key)
        words = self.builder.last_words if g.phase == "encounter" else []
        best = words[0].score if words else 0.0
        second = words[1].score if len(words) > 1 else 0.0
        o = observe(g, best=best, second=second, n_words=len(words), phase_steps=self.point_anytime,
                    shop_actions=self.shop_actions)
        self.builder.last_words = []
        return Step(o, cs)

    @property
    def done(self) -> bool:
        return self.game is None or self.game.phase == "done" or self.steps >= MAX_STEPS

    def step(self, action: Action) -> tuple[float, bool]:
        g = self.game
        ok = apply(g, action)
        self.steps += 1
        if action.kind in ANYTIME:
            self.point_anytime += 1
        else:
            self.point_anytime = 0
        if g.shop is not None and g.phase == "shop":
            if id(g.shop) != self._shop_id:
                self._shop_id = id(g.shop)
                self.shop_actions = 0
            elif action.kind != "leave":
                self.shop_actions += 1
        else:
            self._shop_id = None
            self.shop_actions = 0
        phi = potential(g)
        r = phi - self.phi
        self.phi = phi
        done = self.done
        if done and g.phase != "done":
            r += 0.0  # step cap: episode cut, return is progress so far
        _ = ok
        return r, done

    def result(self) -> dict[str, Any]:
        g = self.game
        return {"won": bool(g.won), "reason": g.end_reason, "outcome": round(outcome(g), 4),
                "stage": g.player.run.stage, "steps": self.steps,
                "michael": g.end_reason == "michael", "cursed": len(g.player.run.cursed_bosses_defeated)}
