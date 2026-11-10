"""Decision-time look-ahead on top of the learned policy (plan stage C).

At a high-impact decision (boss / pin / Michael draft, close shop calls, grid reroll or
skip) the policy's top few candidates are each played forward on several *determinized*
clones (hidden state resampled: ``agent.determinize``, same keys for every candidate =
common random numbers) with the greedy policy for a short horizon, then scored as
``Φ(end) + value(end)``, i.e. an estimate of the run's final outcome. Everything else is
the plain policy, so a run costs a few times a greedy run rather than the teacher's 100x.

Only information a human has is used: the clones are resampled before any rollout.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from cursed_words_solver.rl.env import CWEnv, Step, pack, potential
from cursed_words_solver.rl.ppo import VALUE_SCALE
from cursed_words_solver.sim.game.agent import clone, determinize
from cursed_words_solver.sim.game.features import progress

if TYPE_CHECKING:  # pragma: no cover
    from cursed_words_solver.rl.model import Actor


@dataclass
class SearchConfig:
    top: int = 3            # candidates searched (by policy probability)
    sims: int = 4           # determinized futures per candidate
    horizon: float = 2.0    # rollout until progress grows by this many nodes (or the run ends)
    min_prob: float = 0.04  # don't search candidates the policy all but rules out
    margin: float = 0.35    # shop/encounter: search only when top-2 probabilities are this close
    max_steps: int = 120    # per rollout


ALWAYS = ("boss_draft", "pin_reward")
CLOSE_KINDS = frozenset({"buy", "leave", "reroll_shop", "sell_buy", "hippo", "freeze", "reroll_grid", "skip", "sell"})


def wants_search(env: CWEnv, st: Step, probs: np.ndarray, cfg: SearchConfig) -> bool:
    if len(st.cands) < 2:
        return False
    g = env.game
    if g.phase in ALWAYS:
        return True
    if g.phase == "encounter" and g.encounter is not None and g.encounter.michael_draft is not None:
        return True
    order = np.argsort(-probs)
    a, b = st.cands[order[0]], st.cands[order[1]]
    if probs[order[0]] - probs[order[1]] > cfg.margin:
        return False
    return a.action.kind in CLOSE_KINDS or b.action.kind in CLOSE_KINDS


def _sub_env(env: CWEnv, game) -> CWEnv:
    e = CWEnv(env.builder.cands, env.builder.lim)
    e.attach(game)
    e.point_anytime = env.point_anytime
    e.shop_actions = env.shop_actions
    e._shop_id = id(game.shop) if game.shop is not None else None
    return e


def rollout_value(env: CWEnv, cand_action, actor: "Actor", key: str, cfg: SearchConfig) -> float:
    g = determinize(clone(env.game), key)
    e = _sub_env(env, g)
    p0 = progress(g)
    e.step(cand_action)
    n = 0
    while not e.done and n < cfg.max_steps and progress(e.game) < p0 + cfg.horizon:
        st = e.current()
        if not st.cands:
            break
        i, _, _ = actor.choose(pack(st))
        e.step(st.cands[i].action)
        n += 1
    if e.game.phase == "done":
        return float(potential(e.game))
    st = e.current()
    if not st.cands:
        return float(potential(e.game))
    _, v, _ = actor.evaluate(pack(st))
    return float(potential(e.game)) + v * VALUE_SCALE


class Searcher:
    """``choose(env, st, packed)`` -> candidate index; ``stats`` counts searched nodes."""

    def __init__(self, actor: "Actor", cfg: SearchConfig | None = None) -> None:
        self.actor = actor
        self.cfg = cfg or SearchConfig()
        self.stats = {"nodes": 0, "searched": 0, "changed": 0}
        self.last: dict | None = None   # the last choose(): {"scores", "pick", "policy"} when it searched

    def scores(self, env: CWEnv, st: Step, probs: np.ndarray, key: str) -> dict[int, float]:
        cfg = self.cfg
        order = [int(i) for i in np.argsort(-probs)[: cfg.top] if probs[i] >= cfg.min_prob or i == np.argmax(probs)]
        out = {}
        for i in order:
            vals = [rollout_value(env, st.cands[i].action, self.actor, f"{key}|{s}", cfg) for s in range(cfg.sims)]
            out[i] = float(np.mean(vals))
        return out

    def choose(self, env: CWEnv, st: Step, packed, key: str) -> int:
        self.stats["nodes"] += 1
        self.last = None
        probs, _, _ = self.actor.evaluate(packed)
        best = int(np.argmax(probs))
        if not wants_search(env, st, probs, self.cfg):
            return best
        self.stats["searched"] += 1
        sc = self.scores(env, st, probs, key)
        pick = max(sc, key=lambda i: (sc[i], probs[i]))
        if pick != best:
            self.stats["changed"] += 1
        vals = sorted(sc.values(), reverse=True)
        self.last = {"scores": sc, "pick": pick, "policy": best, "margin": vals[0] - vals[1] if len(vals) > 1 else 0.0}
        return pick
