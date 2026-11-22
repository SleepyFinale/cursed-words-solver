"""Decision-time look-ahead on top of the learned policy (plan stage C).

At a high-impact decision (boss / pin / Michael draft, close shop calls, grid reroll or
skip) the policy's top few candidates are each played forward on several *determinized*
clones (hidden state resampled: ``agent.determinize``, same keys for every candidate =
common random numbers) with the greedy policy for a short horizon, then scored as
``Φ(end) + value(end)``, i.e. an estimate of the run's final outcome. Everything else is
the plain policy, so a run costs a few times a greedy run rather than the teacher's 100x.

Two modes (``SearchConfig.mode``):

* ``"topk"`` (default): the ``top`` most probable candidates past ``min_prob``, ``sims``
  futures each, pick the best mean.
* ``"halving"`` (opt-in, noise-aware): ``k`` candidates by Gumbel-top-k on the policy
  logits (deterministic draw keyed on the decision key; the argmax is always in), all
  rolled out on the same determinized futures (paired differences). Round 1: ``sims0``
  each; round 2: ``sims1`` more for the argmax and the best challenger. The policy argmax is kept
  unless the best challenger's paired mean difference vs the argmax is > 0 with
  t >= ``switch_t``, so close calls inside the noise do not flip the policy's pick.
* ``"race"`` (opt-in, exit3 labels; ``Searcher.race``): the top ``k`` candidates by policy
  probability (deterministic), ``race_n0`` paired futures each (key ``{key}|{s}`` shared by every
  candidate); after each round a candidate whose paired t vs the current leader is below
  ``race_drop_t`` is dropped, the survivors get ``race_step`` more futures, up to ``race_n_max`` or
  until the top two are separated (|t| >= ``race_stop_t``). Rollouts run to the end of the next
  stage's boss (``race_horizon`` 0: progress ``3 * stage + 6``) with ``race_max_steps`` steps. The
  leader is the pick only when ``confident`` (|t(top 2)| >= ``race_stop_t`` or one survivor).

Only information a human has is used: the clones are resampled before any rollout.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from cursed_words_solver.rl.env import CWEnv, Step, pack, potential
from cursed_words_solver.rl.ppo import VALUE_SCALE
from cursed_words_solver.sim.game.agent import clone, determinize
from cursed_words_solver.sim.game.features import MICHAEL_BONUS, progress

if TYPE_CHECKING:  # pragma: no cover
    from cursed_words_solver.rl.model import Actor


@dataclass
class SearchConfig:
    top: int = 3            # candidates searched (by policy probability)
    sims: int = 4           # determinized futures per candidate
    horizon: float = 2.0    # rollout until progress grows by this many nodes (or the run ends)
    min_prob: float = 0.04  # don't search candidates the policy all but rules out
    margin: float = 0.35    # shop/encounter: search only when top-2 probabilities are this close
    max_steps: int = 120    # per rollout (kept: not shown that the horizon always stops a rollout first)
    # stage gates (0 = off, the default: behaviour unchanged)
    max_stage: int = 0          # > 0: never search margin-gated shop / encounter calls at stage > max_stage
                                # (boss / pin / Michael drafts are still searched)
    shop_margin_stage: int = 0  # > 0: shop calls at stage <= N skip the margin test (margin treated as 1.0)
    # "halving" mode (mode="topk" ignores these)
    mode: str = "topk"      # "topk" | "halving"
    k: int = 3              # Gumbel-top-k candidates
    sims0: int = 4          # round 1: futures per candidate
    sims1: int = 4          # round 2: extra futures for the argmax and the round-1 challenger
    switch_t: float = 1.0   # paired t vs the policy argmax needed to override it
    # "race" mode (exit3; other modes ignore these): top-k candidates (k above) raced on paired futures
    race_n0: int = 8            # futures per candidate in round 1
    race_step: int = 4          # extra futures per surviving candidate per round
    race_n_max: int = 32        # futures cap per candidate
    race_drop_t: float = -2.5   # drop a candidate whose paired t vs the leader is below this
    race_switch_t: float = 2.5  # a leader that is not the policy pick must also beat it by this paired t
                                # (review 2026-11-21: -2 / no switch bar gave ~10% confident switches on ties)
    race_stop_t: float = 2.5    # stop (confident) once |t| of the runner-up vs the leader reaches this
    race_horizon: float = 0.0   # > 0: rollout nodes; 0 = through the next stage's boss (progress 3 * stage + 6)
    race_max_steps: int = 400   # per rollout in race mode (max_steps stays for the other modes)
    # value of a Michael win over a plain win in a finished rollout (env.potential): the game's
    # MICHAEL_BONUS by default; set it to the bonus PPO trains with (rl.ppo --michael-bonus) so
    # the look-ahead's labels value the Michael route as training does
    michael_bonus: float = MICHAEL_BONUS


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
    stage = _stage(g)
    if cfg.max_stage > 0 and g.phase in ("shop", "encounter") and stage > cfg.max_stage:
        return False
    margin = cfg.margin
    if cfg.shop_margin_stage > 0 and g.phase == "shop" and stage <= cfg.shop_margin_stage:
        margin = 1.0
    order = np.argsort(-probs)
    a, b = st.cands[order[0]], st.cands[order[1]]
    if probs[order[0]] - probs[order[1]] > margin:
        return False
    return a.action.kind in CLOSE_KINDS or b.action.kind in CLOSE_KINDS


def _stage(game) -> int:
    try:
        return int(game.player.run.stage)
    except Exception:
        return 0


def _sub_env(env: CWEnv, game) -> CWEnv:
    e = CWEnv(env.builder.cands, env.builder.lim, arrange=getattr(env, "arrange", False))
    e.attach(game)
    e.point_anytime = env.point_anytime
    e.shop_actions = env.shop_actions
    e._shop_id = id(game.shop) if game.shop is not None else None
    return e


def rollout_value(env: CWEnv, cand_action, actor: "Actor", key: str, cfg: SearchConfig,
                  pivot_stage: int = 0) -> float:
    """``pivot_stage`` > 0 (a pivot run): the rollout re-reads the target at each new shop visit
    like the real run (play.PivotTracker; the shop the real run is in was already read)."""
    g = determinize(clone(env.game), key)
    e = _sub_env(env, g)
    pv = None
    if pivot_stage > 0:
        from cursed_words_solver.rl.play import PivotTracker

        pv = PivotTracker(pivot_stage, e)
        if g.phase == "shop":
            pv.last_shop = (int(g.player.run.stage), int(g.player.run.node))
    p0 = progress(g)
    e.step(cand_action)
    n = 0
    while not e.done and n < cfg.max_steps and progress(e.game) < p0 + cfg.horizon:
        if pv is not None:
            pv.observe()
        st = e.current()
        if not st.cands:
            break
        i, _, _ = actor.choose(pack(st))
        e.step(st.cands[i].action)
        n += 1
    mb = float(cfg.michael_bonus)
    if e.game.phase == "done":
        return float(potential(e.game, michael_bonus=mb))
    st = e.current()
    if not st.cands:
        return float(potential(e.game, michael_bonus=mb))
    _, v, _ = actor.evaluate(pack(st))
    return float(potential(e.game, michael_bonus=mb)) + v * VALUE_SCALE


def race_horizon(game, cfg: SearchConfig) -> float:
    """Race-mode rollout horizon in progress nodes: ``race_horizon`` if > 0, else through the end of
    the next stage's boss, ``3 * stage + 6 - progress`` (as the deep-label driver; >= 1)."""
    if cfg.race_horizon > 0:
        return float(cfg.race_horizon)
    return max(1.0, 3.0 * _stage(game) + 6.0 - float(progress(game)))


def race_candidates(probs: np.ndarray, k: int, min_prob: float) -> list[int]:
    """Top ``k`` by probability among those >= ``min_prob`` (the argmax first, always in; ties:
    lower index). Deterministic: no key."""
    best = int(np.argmax(probs))
    order = sorted(range(len(probs)), key=lambda i: (-float(probs[i]), i))
    rest = [int(i) for i in order if i != best and probs[i] >= min_prob]
    return [best] + rest[: max(0, int(k) - 1)]


def _key_seed(key: str) -> int:
    return int.from_bytes(hashlib.blake2b(key.encode(), digest_size=8).digest(), "little")


def gumbel_candidates(probs: np.ndarray, key: str, k: int, min_prob: float) -> list[int]:
    """Gumbel-top-``k`` over ``log probs`` among candidates with probability >= ``min_prob``
    (the argmax always qualifies and is always returned first). The Gumbel draw is seeded by
    ``key``, so the same decision gets the same set. Fewer than 2 eligible -> just the argmax."""
    probs = np.asarray(probs, np.float64)
    best = int(np.argmax(probs))
    elig = [i for i in range(len(probs)) if probs[i] >= min_prob or i == best]
    if len(elig) < 2 or k < 2:
        return [best]
    g = np.random.default_rng(_key_seed(f"{key}|gumbel")).gumbel(size=len(probs))
    score = np.log(np.maximum(probs, 1e-30)) + g
    rest = sorted((i for i in elig if i != best), key=lambda i: -score[i])
    return [best] + [int(i) for i in rest[: k - 1]]


def paired_stats(a: list[float], b: list[float]) -> tuple[float, float, float, int]:
    """Paired difference ``a - b`` over their common prefix (same futures): mean, SE, t, n.
    SE 0 with mean > 0 gives t = inf; fewer than 2 pairs gives SE nan and t 0."""
    n = min(len(a), len(b))
    if n == 0:
        return 0.0, float("nan"), 0.0, 0
    d = np.asarray(a[:n], np.float64) - np.asarray(b[:n], np.float64)
    mean = float(d.mean())
    if n < 2:
        return mean, float("nan"), 0.0, n
    se = float(d.std(ddof=1) / math.sqrt(n))
    if se > 0:
        t = mean / se
    else:
        t = math.inf if mean > 0 else (-math.inf if mean < 0 else 0.0)
    return mean, se, float(t), n


class Searcher:
    """``choose(env, st, packed)`` -> candidate index; ``stats`` counts searched nodes."""

    def __init__(self, actor: "Actor", cfg: SearchConfig | None = None) -> None:
        self.actor = actor
        self.cfg = cfg or SearchConfig()
        self.stats = {"nodes": 0, "searched": 0, "changed": 0, "single": 0, "rollouts": 0}
        self.last: dict | None = None   # the last choose(): {"scores", "pick", "policy", "margin", ...} when it searched
        self.pivot_stage = 0   # > 0: rollouts re-read pivot targets at shop entries (rollout_value)

    def candidates(self, probs: np.ndarray, key: str = "") -> list[int]:
        """topk: top ``cfg.top`` by policy probability that pass ``min_prob`` (the argmax always does).
        halving: Gumbel-top-``cfg.k`` keyed on the decision ``key`` (argmax first)."""
        cfg = self.cfg
        if cfg.mode == "halving":
            return gumbel_candidates(probs, key, cfg.k, cfg.min_prob)
        if cfg.mode == "race":
            return race_candidates(probs, cfg.k, cfg.min_prob)
        return [int(i) for i in np.argsort(-probs)[: cfg.top] if probs[i] >= cfg.min_prob or i == np.argmax(probs)]

    def _roll(self, env, st, i: int, key: str, s: int, cfg: SearchConfig | None = None) -> float:
        self.stats["rollouts"] = self.stats.get("rollouts", 0) + 1
        extra = (self.pivot_stage,) if self.pivot_stage else ()   # pivot off: the old 5-argument call
        return rollout_value(env, st.cands[i].action, self.actor, f"{key}|{s}", cfg or self.cfg, *extra)

    def race(self, env: CWEnv, st: Step, probs: np.ndarray, key: str) -> dict:
        """Race the top ``k`` candidates on paired futures (module doc). Future ``s`` of every
        candidate uses determinize key ``{key}|{s}`` (common random numbers). Returns ``cands``
        (argmax first), ``vals`` (rollout values per candidate, future s at index s), ``q`` / ``n``,
        ``diff`` / ``se`` / ``t`` (paired vs the final leader; the leader's 0), ``alive`` (survivors),
        ``leader`` (best mean survivor; ties: higher probability), ``runner_up`` (best other survivor,
        None if none), ``t2`` (its t vs the leader; 0 without one), ``confident``, ``pick`` (leader if
        confident, else the policy argmax), ``policy``, ``diff_pol`` / ``t_pol`` (leader vs the argmax),
        ``margin`` (leader - runner-up mean), ``scores`` (= q), ``horizon``, ``rounds``."""
        import dataclasses

        cfg = self.cfg
        H = race_horizon(env.game, cfg)
        rcfg = dataclasses.replace(cfg, horizon=H, max_steps=int(cfg.race_max_steps))
        cands = race_candidates(probs, cfg.k, cfg.min_prob)
        policy = int(cands[0])
        vals: dict[int, list[float]] = {i: [] for i in cands}

        def mean_key(i: int):
            return (float(np.mean(vals[i])), float(probs[i]), -i)

        alive = list(cands)
        n_cur = max(1, min(int(cfg.race_n0), int(cfg.race_n_max)))
        rounds = 0
        while True:
            rounds += 1
            for i in alive:
                for s in range(len(vals[i]), n_cur):
                    vals[i].append(self._roll(env, st, i, key, s, rcfg))
            if len(alive) < 2:
                break
            ld = max(alive, key=mean_key)
            tv = {i: paired_stats(vals[i], vals[ld])[2] for i in alive if i != ld}
            alive = [i for i in alive if i == ld or tv[i] >= cfg.race_drop_t]
            if len(alive) < 2:
                break
            ru = max((i for i in alive if i != ld), key=mean_key)
            if abs(tv[ru]) >= cfg.race_stop_t or n_cur >= cfg.race_n_max:
                break
            n_cur = min(n_cur + max(1, int(cfg.race_step)), int(cfg.race_n_max))
        ld = max(alive, key=mean_key)
        q = {i: float(np.mean(v)) for i, v in vals.items()}
        n = {i: len(v) for i, v in vals.items()}
        diff, se, t = {ld: 0.0}, {ld: 0.0}, {ld: 0.0}
        for i in cands:
            if i != ld:
                diff[i], se[i], t[i], _ = paired_stats(vals[i], vals[ld])
        others = [i for i in alive if i != ld]
        ru = max(others, key=mean_key) if others else None
        t2 = float(t[ru]) if ru is not None else 0.0
        confident = ru is None or abs(t2) >= cfg.race_stop_t
        diff_pol, t_pol = (0.0, 0.0) if ld == policy else tuple(paired_stats(vals[ld], vals[policy])[i] for i in (0, 2))
        if ld != policy:
            # a switch label must beat the policy pick itself (finite t: a constant tiny gap gives inf)
            beats = (math.isfinite(t_pol) and t_pol >= cfg.race_switch_t) or (math.isinf(t_pol) and diff_pol > 0.5)
            confident = bool(confident and beats)
        rest = [q[i] for i in (others or [i for i in cands if i != ld])]
        margin = q[ld] - max(rest) if rest else 0.0
        return {"cands": list(cands), "vals": {i: list(v) for i, v in vals.items()}, "q": q, "scores": q, "n": n,
                "diff": diff, "se": se, "t": t, "alive": alive, "leader": ld, "runner_up": ru, "t2": t2,
                "confident": bool(confident), "pick": ld if confident else policy, "policy": policy,
                "diff_pol": float(diff_pol), "t_pol": float(t_pol), "margin": float(margin), "horizon": H,
                "rounds": rounds}

    def scores(self, env: CWEnv, st: Step, probs: np.ndarray, key: str) -> dict[int, float]:
        """Mean rollout value per candidate (halving mode: the round-robin means of ``halving``)."""
        if self.cfg.mode == "halving":
            return dict(self.halving(env, st, probs, key)["scores"])
        cfg = self.cfg
        out = {}
        for i in self.candidates(probs, key):
            vals = [self._roll(env, st, i, key, s) for s in range(cfg.sims)]
            out[i] = float(np.mean(vals))
        return out

    def halving(self, env: CWEnv, st: Step, probs: np.ndarray, key: str) -> dict:
        """Sequential halving with common random numbers. Future ``s`` of every candidate uses the
        determinize key ``{key}|{s}``, so candidate values are paired by future. Returns
        ``scores`` (mean Q), ``q`` / ``n`` / ``se`` / ``t`` per candidate (``se`` / ``t``: paired
        vs the policy argmax over their common futures; the argmax has se 0, t 0), ``cands``
        (searched order, argmax first), ``pick``, ``policy``, ``margin``, ``challenger``."""
        cfg = self.cfg
        cands = self.candidates(probs, key)
        best = cands[0]
        vals: dict[int, list[float]] = {i: [self._roll(env, st, i, key, s) for s in range(cfg.sims0)] for i in cands}
        others = [i for i in cands if i != best]
        # challenger = best non-argmax after round 1; round 2 extends exactly the pair the switch
        # rule compares (argmax vs challenger), so the override is decided on all shared futures
        mean = {i: float(np.mean(v)) for i, v in vals.items()}
        ch = max(others, key=lambda i: (mean[i], probs[i])) if others else None
        if cfg.sims1 > 0 and ch is not None:
            for i in (best, ch):
                vals[i].extend(self._roll(env, st, i, key, s) for s in range(cfg.sims0, cfg.sims0 + cfg.sims1))
        q = {i: float(np.mean(v)) for i, v in vals.items()}
        n = {i: len(v) for i, v in vals.items()}
        se, t = {best: 0.0}, {best: 0.0}
        diff = {best: 0.0}
        for i in cands:
            if i != best:
                diff[i], se[i], t[i], _ = paired_stats(vals[i], vals[best])
        pick = best
        if ch is not None and diff[ch] > 0 and t[ch] >= cfg.switch_t:
            pick = ch
        srt = sorted(q.values(), reverse=True)
        return {"scores": q, "q": q, "n": n, "se": se, "t": t, "cands": list(cands), "pick": pick, "policy": best,
                "challenger": ch, "margin": srt[0] - srt[1] if len(srt) > 1 else 0.0}

    def choose(self, env: CWEnv, st: Step, packed, key: str) -> int:
        self.stats["nodes"] += 1
        self.last = None
        probs, _, _ = self.actor.evaluate(packed)
        best = int(np.argmax(probs))
        if not wants_search(env, st, probs, self.cfg):
            return best
        if len(self.candidates(probs, key)) < 2:
            # nothing to compare: same pick as the policy, no rollouts, no distillation label
            self.stats["single"] = self.stats.get("single", 0) + 1
            return best
        self.stats["searched"] += 1
        if self.cfg.mode == "race":
            info = self.race(env, st, probs, key)
            pick = int(info["pick"])
            if pick != best:
                self.stats["changed"] += 1
            self.last = info
            return pick
        if self.cfg.mode == "halving":
            info = self.halving(env, st, probs, key)
            pick = int(info["pick"])
            if pick != best:
                self.stats["changed"] += 1
            self.last = info
            return pick
        sc = self.scores(env, st, probs, key)
        pick = max(sc, key=lambda i: (sc[i], probs[i]))
        if pick != best:
            self.stats["changed"] += 1
        vals = sorted(sc.values(), reverse=True)
        self.last = {"scores": sc, "pick": pick, "policy": best, "margin": vals[0] - vals[1] if len(vals) > 1 else 0.0}
        return pick
