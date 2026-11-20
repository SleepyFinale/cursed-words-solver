"""PPO self-improvement: CPU actor processes play runs with the current policy (sampled),
the GPU learner updates it. Every ``--eval-every`` updates the greedy policy plays the gate seed
set (``evaluate.gate_jobs``, 404 runs); it becomes the champion when it beats the current champion
paired (``evaluate.promote_ok``: more wins and more outcome, one of them >= 1 SE).

Loss: PPO clip + value + adaptive entropy bonus (coefficient moved in log space each update so
the mean policy entropy stays near ``--ent-target``) + KL anchor + look-ahead distillation.
Anchor: KL(policy || ref) with ref = ``--kl-ref`` (champion.pt, reloaded on every promotion, or
the BC init.pt); coefficient ``--kl-coef`` * 0.5 ** (update / ``--kl-halflife``).
Curriculum: characters and quests are sampled inversely to their recent training win rate
(``curriculum_weights``), written to ``curriculum.json`` each update for the rl.exit collector.

Build targets (``rl/targets.py``): ``--targets-mix p_free,p_theme,p_any`` gives each non-quest
training run a target build (FREE / one of the character's THEMES / any plan; default 1,0,0 =
always FREE, the unconditioned run), drawn from its own RNG so the character / crown / quest /
seed draws are unchanged; ``--shaping`` adds that much potential per owned on-target item.
``--pivot p,lo,hi`` (default off) makes share p of non-quest runs PIVOT runs: they start FREE
and, from a stage drawn in lo..hi, take the build their owned items lean to at each shop entry
(``targets.pivot_update``, ``play.PivotTracker``); stats in ``train_pivot`` / ``train_by_target``.
``--gate-targets`` adds ``evaluate.themed_gate_jobs`` (144 themed runs) to the gate; promotion
is decided over all gate rows, paired by key (target included). ``--compare-dir`` (e.g. ppo1)
logs ``vs_ppo1`` on the FREE gate rows against that dir's champion eval rows.

Michael bonus (``--michael-bonus b``, default 8 = the game's ``MICHAEL_BONUS``): training only.
A Michael win is worth 16 + b in the episode return / value targets (``episode_items`` moves the
last reward by b - the bonus the env applied). Eval / episode rows keep the true outcome (16 / 24);
the gate compares wins and ``evaluate.row_outcome(r, b)`` (``paired(..., michael_bonus=b)``), so
promotion follows what training values. b is saved in the checkpoint, curriculum.json and
command.txt: a resume without the flag keeps it (an explicit flag wins; old runs = 8).

Value / representation fixes (2026-11-18, all default off): ``--aux-coef`` (BCE of the aux head
on the run's won / Michael flags), ``--lam-build`` (GAE lambda of the build decisions' advantages:
shop / skip / pin / boss_draft / michael_pick steps), ``--vf-lam`` (lambda of the value target),
``--vf-epochs`` (value(+aux)-only passes after the policy epochs, KL(snapshot || policy) on the
logits * ``--vf-kl-coef``). Every update logs ``epochs_run`` and the explained variance of the
value targets (``ev*``: by the actors' values; ``ev_fit*``: by the learner's in the last pass;
``_shop`` / ``_word`` = shop / encounter steps) in history.jsonl.

Pause / resume: rerun the same command (``command.txt``). State is checkpointed after every
update (model, optimiser, counters, RNG); episodes in flight at a kill are simply replayed
with new seeds. ``STOP`` file in the dir = checkpoint and exit.

    python -m cursed_words_solver.rl.ppo --dir ~/.cursed_words_solver/rl/ppo1 --init ~/.cursed_words_solver/rl/bc/best.pt
"""

from __future__ import annotations

import argparse
import io
import json
import math
import random
import shutil
import time
from collections import Counter, deque
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn.functional as F

from cursed_words_solver.rl import store
from cursed_words_solver.rl.bc import VALUE_SCALE
from cursed_words_solver.rl.evaluate import GATE_PER, GATE_PER_QUEST, MICHAEL_BONUS
from cursed_words_solver.rl.obs import OBS_VERSION
from cursed_words_solver.rl.model import (Policy, ModelConfig, collate, load_policy, save_policy,
                                          upgrade_checkpoint, upgrade_optimizer_state)
from cursed_words_solver.rl.teacher import CHARS

TRAIN_SEED0 = 50_000_000
LEGACY_OBS_VERSION = 1      # rl.exit shards without an ``obs_version`` array were written at this version
CURR_WINDOW = 3000          # recent non-quest training episodes behind the character weights
CURR_QUEST_WINDOW = 1500    # recent quest episodes behind the quest weights (~60 per quest)
CURR_PRIOR = 10             # pseudo-episodes at the mean win rate (few-sample slices stay near 1)


def target_rng(n: int) -> random.Random:
    """The build-target draw of job ``n``: its own stream, so the job's other draws don't move."""
    return random.Random(f"target|{n}")


def pivot_rng(n: int) -> random.Random:
    """The pivot draw of job ``n`` (``sample_job(pivot=...)``): its own stream."""
    return random.Random(n * 7919 + 31)


def parse_pivot(text: str | None) -> tuple[float, int, int] | None:
    """``"p,lo,hi"`` -> (p_pivot, lo, hi); None / "" / p <= 0 -> None (no pivot runs)."""
    if not text:
        return None
    parts = str(text).split(",")
    if len(parts) != 3:
        raise ValueError(f"pivot needs p,lo,hi, got {text!r}")
    p, lo, hi = float(parts[0]), int(parts[1]), int(parts[2])
    if not 0 <= p <= 1 or lo < 1 or hi < lo:
        raise ValueError(f"pivot needs 0<=p<=1 and 1<=lo<=hi, got {text!r}")
    return (p, lo, hi) if p > 0 else None


def parse_mix(text: str | None) -> tuple[float, float, float] | None:
    """``"p_free,p_theme,p_any"`` -> tuple; None / "" -> None (no targets)."""
    if not text:
        return None
    mix = tuple(float(x) for x in str(text).split(","))
    if len(mix) != 3 or min(mix) < 0 or sum(mix) <= 0:
        raise ValueError(f"targets mix needs 3 non-negative shares, got {text!r}")
    return mix   # type: ignore[return-value]


def sample_job(rng: random.Random, n: int, quest_share: float, crown_weights: list[float],
               char_w: dict[str, float] | None = None, quest_w: dict[str, float] | None = None,
               targets_mix: tuple[float, float, float] | None = None, shaping: float = 0.0,
               target_w: dict[str, dict[str, float]] | None = None,
               pivot: tuple[float, int, int] | None = None) -> dict[str, Any]:
    """Training job; ``char_w`` / ``quest_w`` (curriculum) weight the draws, None = uniform (old draws).
    ``targets_mix`` (p_free, p_theme, p_any): the run's build target (``targets.sample_target``
    with ``target_rng(n)``; quest runs stay FREE: their quest fixes the plan); None = FREE.
    ``target_w`` {character: {plan: weight}} (target curriculum) weights the plan draw.
    ``pivot`` (p_pivot, lo, hi): a non-quest run is a PIVOT run with probability p_pivot (target
    FREE, ``pivot_stage`` uniform in lo..hi; drawn from ``pivot_rng(n)``, so with pivot None every
    draw is as before); the rest take the ``targets_mix`` path."""
    from cursed_words_solver.rl.targets import FREE, sample_target
    from cursed_words_solver.sim.game.challenges import QUESTS

    if char_w:
        ch = rng.choices(CHARS, weights=[char_w.get(c, 1.0) for c in CHARS])[0]
    else:
        ch = CHARS[rng.randrange(len(CHARS))]
    if rng.random() < quest_share:
        qs = sorted(QUESTS)
        q = rng.choices(qs, weights=[quest_w.get(x, 1.0) for x in qs])[0] if quest_w else qs[rng.randrange(len(qs))]
        return {"character": ch, "crown": 0, "quest": q, "seed": TRAIN_SEED0 + n, "target": FREE, "shaping": shaping}
    cr = rng.choices(range(len(crown_weights)), weights=crown_weights)[0]
    if pivot is not None and pivot[0] > 0:
        pr = pivot_rng(n)
        if pr.random() < pivot[0]:
            return {"character": ch, "crown": cr, "quest": None, "seed": TRAIN_SEED0 + n, "target": FREE,
                    "shaping": shaping, "pivot_stage": pr.randint(int(pivot[1]), int(pivot[2]))}
    t = (sample_target(target_rng(n), ch, targets_mix, (target_w or {}).get(ch))
         if targets_mix and targets_mix[0] < sum(targets_mix) else FREE)
    return {"character": ch, "crown": cr, "quest": None, "seed": TRAIN_SEED0 + n, "target": t, "shaping": shaping}


def by_target(rows) -> dict[str, dict]:
    """Rolling training stats per build target ("free" for FREE): n, win rate, mean on-plan items."""
    from cursed_words_solver.rl.targets import file_tag

    g: dict[str, list[dict]] = {}
    for r in rows:
        t = file_tag(r.get("target") or "")
        if r.get("pivot_stage"):   # pivot runs: the "pivot" bucket and "pivot-<final target>", never a plain plan
            g.setdefault("pivot", []).append(r)
            t = "pivot-" + t
        g.setdefault(t, []).append(r)
    return {t: {"n": len(v), "win": round(sum(bool(r["won"]) for r in v) / len(v), 4),
                "on_plan": round(sum(r.get("on_plan", 0) for r in v) / len(v), 2)} for t, v in sorted(g.items())}


def by_pivot(rows) -> dict:
    """Rolling training stats of pivot runs: n, win rate, mean target switches, share that
    ended on a build, per pivot stage."""
    rs = [r for r in rows if r.get("pivot_stage")]
    if not rs:
        return {"n": 0}
    out = {"n": len(rs), "win": round(sum(bool(r["won"]) for r in rs) / len(rs), 4),
           "switches": round(sum(r.get("pivot_switches", len(r.get("targets_seen") or ())) for r in rs) / len(rs), 2),
           "committed": round(sum(bool(r.get("target")) for r in rs) / len(rs), 4),
           "final": {k: v for k, v in sorted(Counter(r.get("target") or "" for r in rs).items())}}
    for s in sorted({int(r["pivot_stage"]) for r in rs}):
        v = [r for r in rs if int(r["pivot_stage"]) == s]
        out[f"stage{s}"] = {"n": len(v), "win": round(sum(bool(r["won"]) for r in v) / len(v), 4)}
    return out


def curriculum_weights(rows, keys, lo: float = 0.5, hi: float = 2.0) -> tuple[dict[str, float], dict[str, float]]:
    """``rows`` = (key, won) pairs -> (weight, smoothed win rate) per key.
    w = clamp((mean_win + 0.1) / (win + 0.1), lo, hi); win is shrunk toward the mean by CURR_PRIOR."""
    rows = list(rows)
    if not rows:
        return {k: 1.0 for k in keys}, {}
    mean = sum(bool(w) for _, w in rows) / len(rows)
    n: dict[str, int] = {}
    wins: dict[str, int] = {}
    for k, w in rows:
        n[k] = n.get(k, 0) + 1
        wins[k] = wins.get(k, 0) + bool(w)
    wt, wr = {}, {}
    for k in keys:
        r = (wins.get(k, 0) + CURR_PRIOR * mean) / (n.get(k, 0) + CURR_PRIOR)
        wr[k] = round(r, 4)
        wt[k] = round(min(hi, max(lo, (mean + 0.1) / (r + 0.1))), 4)
    return wt, wr


CURR_TARGET_WINDOW = 12_000  # (character, target, won) rows for the target curriculum
TARGET_W_LO, TARGET_W_HI = 0.15, 1.5


def target_weights(rows) -> dict[str, dict[str, float]]:
    """Target curriculum (2026-11-13): {character: {plan: weight}}; weight =
    clamp((r_t + 0.05) / (r_free + 0.05), TARGET_W_LO, TARGET_W_HI), r_t shrunk toward half the
    character's FREE win rate with CURR_PRIOR pseudo-runs. Targets doing about as well as
    FREE get sampled most; hopeless ones keep a floor so they are still explored."""
    from cursed_words_solver.rl.targets import SAMPLE_PLANS

    tally: dict[tuple[str, str], list[int]] = {}
    for ch, t, won in rows:
        s = tally.setdefault((ch, t), [0, 0])
        s[0] += int(won)
        s[1] += 1
    out: dict[str, dict[str, float]] = {}
    for ch in CHARS:
        fw, fn = tally.get((ch, ""), [0, 0])
        r_free = fw / fn if fn else 0.4
        prior = 0.5 * r_free
        ws = {}
        for p in SAMPLE_PLANS:
            w, n = tally.get((ch, p), [0, 0])
            r = (w + CURR_PRIOR * prior) / (n + CURR_PRIOR)
            ws[p] = round(min(TARGET_W_HI, max(TARGET_W_LO, (r + 0.05) / (r_free + 0.05))), 4)
        out[ch] = ws
    return out


class Curriculum:
    """Rolling (character, won) / (quest, won) tallies of training episodes; saved in the checkpoint."""

    def __init__(self, char_rows=(), quest_rows=(), target_rows=()) -> None:
        self.chars: deque = deque((tuple(r) for r in char_rows), maxlen=CURR_WINDOW)
        self.quests: deque = deque((tuple(r) for r in quest_rows), maxlen=CURR_QUEST_WINDOW)
        self.targets: deque = deque((tuple(r) for r in target_rows), maxlen=CURR_TARGET_WINDOW)

    @classmethod
    def from_episodes(cls, path: Path) -> "Curriculum":
        c = cls()
        for r in store.read_jsonl(path):
            c.add(r)
        return c

    def add(self, r: dict) -> None:
        if r.get("error") or r.get("crown", 0) > 7:
            return
        if r.get("quest"):
            self.quests.append((r["quest"], int(bool(r["won"]))))
        else:
            self.chars.append((r["character"], int(bool(r["won"]))))
            if r.get("pivot_stage"):
                # pivot runs stay out of the target tally: a committed one already survived to its pivot
                # stage (biased up vs fixed-from-start runs), an uncommitted one is not a FREE baseline run
                return
            self.targets.append((r["character"], r.get("target") or "", int(bool(r["won"]))))

    def state(self) -> dict:
        return {"chars": [list(x) for x in self.chars], "quests": [list(x) for x in self.quests],
                "targets": [list(x) for x in self.targets]}

    def weights(self) -> dict:
        from cursed_words_solver.sim.game.challenges import QUESTS

        cw, cr = curriculum_weights(self.chars, CHARS)
        qw, qr = curriculum_weights(self.quests, sorted(QUESTS))
        return {"char": cw, "quest": qw, "char_win": cr, "quest_win": qr,
                "n_char": len(self.chars), "n_quest": len(self.quests),
                "target": target_weights(self.targets), "n_target": len(self.targets)}


def adapt_ent_coef(coef: float, ent: float, target: float, lr: float, lo: float = 1e-4, hi: float = 0.2) -> float:
    """Log-space step toward the entropy target: entropy below target -> larger bonus."""
    if target <= 0 or not math.isfinite(ent):
        return coef
    step = lr * max(-1.0, min(1.0, (target - ent) / target))
    return float(min(hi, max(lo, coef * math.exp(step))))


def gae(rew: np.ndarray, val: np.ndarray, lam, gamma: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    """GAE advantages and lambda-returns. ``lam`` is a float or a per-step array (len(rew)):
    step t's advantage is sum_k (gamma * lam[t]) ** k * delta[t + k], i.e. each decision uses its
    OWN lambda over the whole remaining horizon (a step's advantage does not depend on the other
    steps' lambdas; a constant array == the float)."""
    if np.ndim(lam):
        lam_t = np.asarray(lam, np.float64).reshape(-1)
        if len(lam_t) != len(rew):
            raise ValueError(f"per-step lambda has {len(lam_t)} entries for {len(rew)} steps")
        adv = np.zeros(len(rew), np.float32)
        for lv in np.unique(lam_t):
            m = lam_t == lv
            adv[m] = gae(rew, val, float(lv), gamma)[0][m]
        return adv, adv + val
    n = len(rew)
    adv = np.zeros(n, np.float32)
    last = 0.0
    for t in range(n - 1, -1, -1):
        nv = val[t + 1] if t + 1 < n else 0.0
        delta = rew[t] + gamma * nv - val[t]
        last = delta + gamma * lam * last
        adv[t] = last
    return adv, adv + val


# build decisions (``--lam-build``): steps in these phases, or whose chosen action is of these kinds
BUILD_PHASES = frozenset({"shop", "boss_draft", "pin_reward", "michael_pick"})
BUILD_KINDS = frozenset({"skip", "pin", "boss", "michael_pick"})
_SHOP_KINDS = frozenset({"buy", "hippo", "freeze", "reroll_shop", "leave", "sell_buy"})
_WORD_KINDS = frozenset({"submit", "skip", "reroll_grid", "place", "finale"})


def step_phase(st: dict, phase: str | None = None) -> str:
    """The decision's phase: the recorded one (play.py traj ``phase``), else inferred from the
    candidate action kinds ('shop', 'boss_draft', 'pin_reward', 'michael_pick', 'encounter';
    '' when only anytime actions are on offer)."""
    if phase:
        return str(phase)
    from cursed_words_solver.rl.actions import ACTION_TYPES

    kinds = {ACTION_TYPES[int(k)] for k in np.asarray(st["act_type"]).reshape(-1) if 0 <= int(k) < len(ACTION_TYPES)}
    if kinds & _SHOP_KINDS:
        return "shop"
    if "michael_pick" in kinds:
        return "michael_pick"
    if "boss" in kinds:
        return "boss_draft"
    if "pin" in kinds:
        return "pin_reward"
    if kinds & _WORD_KINDS:
        return "encounter"
    return ""


def is_build_step(st: dict, chosen: int, phase: str | None = None) -> bool:
    """A shop / skip / pin / boss_draft / michael_pick decision (``--lam-build`` steps)."""
    from cursed_words_solver.rl.actions import ACTION_TYPES

    if step_phase(st, phase) in BUILD_PHASES:
        return True
    at = np.asarray(st["act_type"]).reshape(-1)
    k = int(at[chosen]) if 0 <= int(chosen) < len(at) else -1
    return 0 <= k < len(ACTION_TYPES) and ACTION_TYPES[k] in BUILD_KINDS


def explained_variance(pred, target) -> float:
    """1 - Var(target - pred) / Var(target); nan with < 2 points or a constant target."""
    y = np.asarray(target, np.float64)
    p = np.asarray(pred, np.float64)
    if len(y) < 2:
        return float("nan")
    vy = float(y.var())
    return float(1.0 - (y - p).var() / vy) if vy > 1e-12 else float("nan")


class DistillBuffer:
    """Look-ahead picks from ``rl.exit`` shards (expert iteration), newest ``cap`` decisions by shard
    mtime. Weight 1 where the look-ahead changed the policy's pick, ``same_w`` where it agreed;
    labels with margin 0 (one candidate scored, or a tie) carry nothing and are dropped. Shards
    whose obs version or feature widths differ from the model's are skipped."""

    def __init__(self, root: Path, cap: int = 20_000, same_w: float = 0.1,
                 widths: tuple[int, int, int] | None = None, version: int = OBS_VERSION) -> None:
        self.dir = Path(root) / "shards"
        self.cap = cap
        self.same_w = same_w
        self.widths = widths      # (global, token, action) feature widths; None = current obs / actions
        self.version = version
        self.seen: set[str] = set()
        self.items: deque = deque(maxlen=cap)
        self.n_skipped = 0        # shards dropped for format

    def _widths(self) -> tuple[int, int, int]:
        if self.widths is None:
            from cursed_words_solver.rl.actions import n_action_features
            from cursed_words_solver.rl.obs import n_global_features, n_token_features

            self.widths = (n_global_features(), n_token_features(), n_action_features())
        return self.widths

    def format_ok(self, ep: dict) -> bool:
        v = ep.get("obs_version")
        v = int(np.asarray(v).reshape(-1)[0]) if v is not None else LEGACY_OBS_VERSION
        G, Ft, Fa = self._widths()
        if v != self.version:
            # older shards (v1: pre-2026-11-11 labels; v2: before target builds) are kept:
            # collate / forward zero-pad their narrower columns, i.e. they read as "new features
            # unknown" (for v3 target columns: FREE)
            from cursed_words_solver.rl.obs import LEGACY_GLOBAL, LEGACY_TOKEN

            if self.version != OBS_VERSION or not LEGACY_OBS_VERSION <= v < OBS_VERSION \
                    or v - LEGACY_OBS_VERSION >= min(len(LEGACY_GLOBAL), len(LEGACY_TOKEN)):
                return False
            from cursed_words_solver.rl.actions import LEGACY_ACTION_BY_OBS

            G, Ft = LEGACY_GLOBAL[v - LEGACY_OBS_VERSION], LEGACY_TOKEN[v - LEGACY_OBS_VERSION]
            # obs v4 widened the action features (38 -> 54): an old shard has its version's width
            # (the current one is accepted too; collate / forward zero-pad the narrower columns)
            fa_ok = {Fa, LEGACY_ACTION_BY_OBS.get(v, Fa)}
        else:
            fa_ok = {Fa}
        g, tf, af = ep.get("glob"), ep.get("tok_feat"), ep.get("act_feat")
        if g is None or af is None or g.ndim != 2 or g.shape[1] != G or af.ndim != 2 or af.shape[1] not in fa_ok:
            return False
        return tf is not None and ((tf.ndim == 2 and tf.shape[1] == Ft) or tf.size == 0)

    def _items(self, ep: dict) -> list[dict]:
        margin = ep.get("margin")
        changed = ep.get("changed")
        q_idx, q_val = ep.get("q_idx"), ep.get("q_val")   # halving search soft targets (rl.exit.soft_targets)
        if q_idx is None or q_val is None or q_idx.ndim != 2 or len(q_idx) != len(ep["chosen"]) or q_val.shape != q_idx.shape:
            q_idx = q_val = None
        out = []
        for i in range(len(ep["chosen"])):
            if margin is not None and float(margin[i]) == 0.0:
                continue
            w = 1.0 if changed is not None and bool(changed[i]) else self.same_w
            if w <= 0:
                continue
            st = store.unpack_step(ep, i)
            if len(st["act_type"]) <= 1:
                continue
            it = {**st, "chosen": int(ep["chosen"][i]), "w": float(w)}
            if q_idx is not None:
                ok = (q_idx[i] >= 0) & (q_idx[i] < len(st["act_type"]))
                if ok.sum() >= 2:
                    it["q_idx"] = q_idx[i][ok].astype(np.int64)
                    it["q_val"] = q_val[i][ok].astype(np.float32)
            out.append(it)
        return out

    def refresh(self) -> int:
        if not self.dir.is_dir():
            return 0
        # runs.jsonl maps shard seed -> crown; crown 8 is not playable (old collector runs)
        skip = {f"{r['seed']}.npz" for r in store.read_jsonl(self.dir.parent / "runs.jsonl")
                if r.get("crown", 0) > 7}
        mt = {}
        for f in self.dir.glob("*.npz"):
            if f.name not in self.seen:
                try:
                    mt[f] = f.stat().st_mtime
                except OSError:
                    pass
        got: list[list[dict]] = []
        total = 0
        for f in sorted(mt, key=lambda p: (mt[p], p.name), reverse=True):   # newest first, stop at the cap
            if f.name in skip or total >= self.cap:
                self.seen.add(f.name)
                continue
            try:
                ep = store.load_episode(f)
            except Exception:
                continue   # being written
            self.seen.add(f.name)
            if not self.format_ok(ep):
                self.n_skipped += 1
                continue
            its = self._items(ep)
            got.append(its)
            total += len(its)
        for its in reversed(got):   # oldest first, so the deque drops the oldest
            self.items.extend(its)
        return total

    @property
    def n_changed(self) -> int:
        return sum(it["w"] >= 1.0 for it in self.items)

    def sample(self, n: int) -> list[dict]:
        k = len(self.items)
        return [self.items[i] for i in np.random.randint(0, k, size=min(n, k))] if k else []


def soft_distill_targets(items: list[dict], width: int, temp: float, mix: float) -> np.ndarray:
    """Distillation targets (len(items), width). An item with search Q values (``q_idx`` /
    ``q_val``, halving search) gets ``(1 - mix) * onehot(chosen) + mix * softmax(Q / temp)``
    over its searched candidates; others get ``onehot(chosen)`` (= the hard CE). As
    ``temp -> 0`` the soft part tends to onehot(argmax Q), i.e. the hard label whenever the
    pick is the best mean (the halving switch rule can keep the policy argmax instead)."""
    tgt = np.zeros((len(items), width), np.float64)
    for r, it in enumerate(items):
        tgt[r, it["chosen"]] = 1.0
        qi, qv = it.get("q_idx"), it.get("q_val")
        if qi is None or qv is None or len(qi) < 2 or temp <= 0 or mix <= 0:
            continue
        z = np.asarray(qv, np.float64) / temp
        z = np.exp(z - z.max())
        tgt[r] *= 1.0 - mix
        np.add.at(tgt[r], np.asarray(qi, np.int64), mix * z / z.sum())
    return tgt.astype(np.float32)


def distill_loss(logits: torch.Tensor, items: list[dict], temp: float = 0.0, mix: float = 0.5) -> torch.Tensor:
    """Weighted distillation loss over the label items (weights ``w``). ``temp <= 0``: hard
    cross-entropy on ``chosen`` (the default); ``temp > 0``: soft targets (``soft_distill_targets``)."""
    device = logits.device
    dw = torch.tensor([it.get("w", 1.0) for it in items], device=device)
    if temp <= 0:
        dch = torch.tensor([it["chosen"] for it in items], device=device)
        ce = F.cross_entropy(logits, dch, reduction="none")
    else:
        tgt = torch.from_numpy(soft_distill_targets(items, logits.shape[1], temp, mix)).to(device)
        ce = -(tgt * F.log_softmax(logits, -1)).sum(-1)
    return (dw * ce).sum() / dw.sum().clamp_min(1e-9)


def aux_loss(out: dict, items: list[dict], device) -> torch.Tensor:
    """BCE of the aux head (win, Michael-win logits) against the items' run flags."""
    y = torch.tensor([[float(it.get("won", 0.0)), float(it.get("michael", 0.0))] for it in items],
                     device=device, dtype=out["aux"].dtype)
    return F.binary_cross_entropy_with_logits(out["aux"], y)


def _ev_stats(batch: list[dict], pred_key: str, prefix: str, pred=None) -> dict[str, float]:
    """Explained variance of ``ret`` by ``pred`` (or each item's ``pred_key``): overall, shop
    steps, word (encounter) steps. Keys ``{prefix}``, ``{prefix}_shop``, ``{prefix}_word``; nan
    groups are left out."""
    if pred is None:
        if not batch or any(pred_key not in it for it in batch):
            return {}
        pred = [it[pred_key] for it in batch]
    pred = np.asarray(pred, np.float64)
    ret = np.asarray([it["ret"] for it in batch], np.float64)
    ph = [step_phase(it, it.get("phase")) for it in batch]
    out = {}
    for name, m in ((prefix, np.ones(len(batch), bool)),
                    (prefix + "_shop", np.asarray([p == "shop" for p in ph], bool)),
                    (prefix + "_word", np.asarray([p == "encounter" for p in ph], bool))):
        ev = explained_variance(pred[m], ret[m]) if m.any() else float("nan")
        if math.isfinite(ev):
            out[name] = round(ev, 4)
    return out


def _masked_kl(p_logp: torch.Tensor, q_logp: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    """mean over rows of KL(p || q) on the legal actions (log-probs; mask 1 = legal)."""
    return (p_logp.exp() * (p_logp - q_logp).masked_fill(mask == 0, 0)).sum(-1).mean()


def ppo_update(model: Policy, ref: Policy | None, opt, batch: list[dict], args, device,
               distill: DistillBuffer | None = None) -> dict:
    """PPO epochs (early stop at ``target_kl``), then ``vf_epochs`` value(+aux)-only passes.
    Optional args (missing = off): ``aux_coef`` (BCE of the aux head on the run's won / michael
    flags, in the policy epochs and the value passes), ``vf_epochs`` / ``vf_kl_coef`` (default 1.0:
    KL(snapshot || model) on the logits, snapshot = the model after the policy epochs).
    Returns the mean losses plus ``epochs_run`` (policy epochs started), ``ev`` / ``ev_shop`` /
    ``ev_word`` (explained variance of the targets by the actors' values, ``vpred``) and
    ``ev_fit*`` (by the learner's values in the last pass over the batch)."""
    model.train()
    idx = np.arange(len(batch))
    stats: dict[str, list[float]] = {}
    beta = args.kl_coef
    aux_coef = float(getattr(args, "aux_coef", 0.0) or 0.0)
    vf_epochs = int(getattr(args, "vf_epochs", 0) or 0)
    epochs_run = 0
    fit_pred = np.zeros(len(batch), np.float64)
    for _ in range(args.epochs):
        epochs_run += 1
        np.random.shuffle(idx)
        ep_kl: list[float] = []
        for s in range(0, len(idx), args.mb):
            items = [batch[i] for i in idx[s:s + args.mb]]
            b = collate(items, device)
            chosen = torch.tensor([it["chosen"] for it in items], device=device)
            old_logp = torch.tensor([it["logp"] for it in items], device=device)
            adv = torch.tensor([it["adv"] for it in items], device=device)
            ret = torch.tensor([it["ret"] for it in items], device=device)
            out = model(b)
            # the actors sample from softmax(logits / T); learn that same distribution
            logp_all = F.log_softmax(out["logits"] / args.temperature, -1)
            logp = logp_all.gather(1, chosen.unsqueeze(1)).squeeze(1)
            ratio = torch.exp(logp - old_logp)
            pg = -torch.min(ratio * adv, ratio.clamp(1 - args.clip, 1 + args.clip) * adv).mean()
            vloss = F.smooth_l1_loss(out["value"], ret / VALUE_SCALE)
            p = logp_all.exp() * b["act_mask"]
            ent = -(p * logp_all.masked_fill(b["act_mask"] == 0, 0)).sum(-1).mean()
            loss = pg + args.vf_coef * vloss - args.ent_coef * ent
            fit_pred[idx[s:s + args.mb]] = out["value"].detach().double().cpu().numpy() * VALUE_SCALE
            if aux_coef > 0:
                aux = aux_loss(out, items, device)
                loss = loss + aux_coef * aux
                stats.setdefault("aux", []).append(aux.item())
            kl_ref = torch.zeros((), device=device)
            if ref is not None and beta > 0:
                with torch.no_grad():
                    rl = F.log_softmax(ref(b)["logits"] / args.temperature, -1)
                kl_ref = (p * (logp_all - rl).masked_fill(b["act_mask"] == 0, 0)).sum(-1).mean()
                loss = loss + beta * kl_ref
            dist = torch.zeros((), device=device)
            if distill is not None and args.distill_coef > 0:
                ditems = distill.sample(args.distill_mb)
                if ditems:
                    db = collate(ditems, device)
                    soft_t = float(getattr(args, "distill_soft", 0.0) or 0.0)
                    if soft_t > 0:
                        dist = distill_loss(model(db)["logits"], ditems, soft_t, float(getattr(args, "distill_soft_mix", 0.5)))
                    else:
                        dch = torch.tensor([it["chosen"] for it in ditems], device=device)
                        dw = torch.tensor([it.get("w", 1.0) for it in ditems], device=device)
                        ce = F.cross_entropy(model(db)["logits"], dch, reduction="none")
                        dist = (dw * ce).sum() / dw.sum().clamp_min(1e-9)
                    loss = loss + args.distill_coef * dist
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), args.max_grad)
            opt.step()
            with torch.no_grad():
                # KL(old || new) of the PPO ratio alone (k3 estimator, >= 0), before this step
                lr_ = logp - old_logp
                approx_kl = (torch.exp(lr_) - 1 - lr_).mean().item()
                ep_kl.append(approx_kl)
                clipfrac = ((ratio - 1).abs() > args.clip).float().mean().item()
            for k, v in (("pg", pg.item()), ("v", vloss.item()), ("ent", ent.item()), ("kl_ref", kl_ref.item()), ("distill", dist.item()),
                         ("approx_kl", approx_kl), ("clipfrac", clipfrac)):
                stats.setdefault(k, []).append(v)
        if ep_kl and np.mean(ep_kl) > args.target_kl:   # this epoch moved the policy enough
            break
    if vf_epochs > 0 and batch:
        import copy

        kl_c = float(getattr(args, "vf_kl_coef", 1.0))
        snap = copy.deepcopy(model)
        snap.eval()
        for p_ in snap.parameters():
            p_.requires_grad_(False)
        # the shared optimiser's first moments still hold the policy epochs' gradients: left in,
        # they would keep pushing the policy along the PPO direction for ~1/(1-beta1) value steps
        # (past the target_kl early stop) before the KL term pulls back. Zero them for the value
        # passes and restore the optimiser state afterwards (the next update's policy epochs see
        # the momentum as if the value passes had not run).
        opt_saved = copy.deepcopy(opt.state_dict())
        for st_ in opt.state.values():
            if "exp_avg" in st_:
                st_["exp_avg"].zero_()
            if "momentum_buffer" in st_ and st_["momentum_buffer"] is not None:
                st_["momentum_buffer"].zero_()
        for _ in range(vf_epochs):
            np.random.shuffle(idx)
            for s in range(0, len(idx), args.mb):
                items = [batch[i] for i in idx[s:s + args.mb]]
                b = collate(items, device)
                ret = torch.tensor([it["ret"] for it in items], device=device)
                out = model(b)
                vloss = F.smooth_l1_loss(out["value"], ret / VALUE_SCALE)
                with torch.no_grad():
                    snap_lp = F.log_softmax(snap(b)["logits"] / args.temperature, -1)
                kl = _masked_kl(snap_lp, F.log_softmax(out["logits"] / args.temperature, -1), b["act_mask"])
                loss = args.vf_coef * vloss + kl_c * kl
                if aux_coef > 0:
                    aux = aux_loss(out, items, device)
                    loss = loss + aux_coef * aux
                    stats.setdefault("vf_aux", []).append(aux.item())
                fit_pred[idx[s:s + args.mb]] = out["value"].detach().double().cpu().numpy() * VALUE_SCALE
                opt.zero_grad(set_to_none=True)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), args.max_grad)
                opt.step()
                stats.setdefault("vf_v", []).append(vloss.item())
                stats.setdefault("vf_kl", []).append(kl.item())
        opt.load_state_dict(opt_saved)
    res ={k: round(float(np.mean(v)), 4) for k, v in stats.items()}
    res["epochs_run"] = epochs_run
    if vf_epochs > 0:
        res["vf_epochs_run"] = vf_epochs
    if batch:
        res.update(_ev_stats(batch, "vpred", "ev"))
        res.update(_ev_stats(batch, "", "ev_fit", pred=fit_pred))
    return res


def michael_reward_delta(res: dict, michael_bonus: float = MICHAEL_BONUS) -> float:
    """What to add to the last reward of an episode so a Michael win is worth 16 + ``michael_bonus``:
    0 unless the run beat Michael; the env's rewards carry ``res["michael_bonus"]`` (CWEnv reports a
    non-default one there), else the game's MICHAEL_BONUS."""
    if not (res.get("won") and res.get("reason") == "michael"):
        return 0.0
    applied = float(res.get("michael_bonus", MICHAEL_BONUS))
    return float(michael_bonus) - applied


def resolve_michael_bonus(flag: float | None, ck_state: dict | None, out: Path) -> float:
    """--michael-bonus when given; else the value the run was saved with (checkpoint, then
    curriculum.json); else MICHAEL_BONUS (runs from before the flag)."""
    if flag is not None:
        return float(flag)
    if ck_state and ck_state.get("michael_bonus") is not None:
        return float(ck_state["michael_bonus"])
    try:
        c = json.loads((Path(out) / "curriculum.json").read_text())
    except (OSError, ValueError):
        c = None
    if isinstance(c, dict) and c.get("michael_bonus") is not None:
        return float(c["michael_bonus"])
    return MICHAEL_BONUS


def command_argv(argv, flag: float | None, michael_bonus: float) -> list[str]:
    """command.txt's arguments: ``argv``, plus ``--michael-bonus`` (the resolved value) when it was not
    given, so rerunning command.txt keeps the run's bonus."""
    out = list(argv)
    if flag is None:
        out += ["--michael-bonus", f"{float(michael_bonus):g}"]
    return out


def _per_step(tr: dict, key: str, n: int, fill):
    """traj list ``key`` when it has one entry per step, else ``fill`` per step (old trajs)."""
    v = tr.get(key)
    return list(v) if v is not None and len(v) == n else [fill] * n


def episode_items(res: dict, lam: float, michael_bonus: float = MICHAEL_BONUS, lam_build: float | None = None,
                  vf_lam: float | None = None) -> list[dict]:
    """PPO items of one recorded run. ``lam_build`` (None = ``lam``): GAE lambda of the build
    decisions' advantages (``is_build_step``); ``vf_lam`` (None = ``lam``): constant lambda of the
    value target ``ret``. With both None (or == lam) the items' adv / ret are the plain-GAE ones.
    Items also carry ``stage`` / ``phase`` (play.py traj; None / '' when not recorded), ``build``,
    ``vpred`` (the actor's value, outcome units, unshaped) and the run's ``won`` / ``michael``."""
    tr = res["traj"]
    if not tr["steps"]:
        return []
    rew = np.asarray(tr["reward"], np.float32)
    if len(rew):
        rew[-1] += michael_reward_delta(res, michael_bonus)
    val = np.asarray(tr["value"], np.float32) * VALUE_SCALE
    # build-target shaping: the value head predicts the UNSHAPED return-to-go (what search /
    # assistant add to the plain potential); the shaped one is that minus the step's shaping
    # bonus (shaping * on-target items), so GAE runs on shaped values and the target adds it back
    bonus = np.asarray(tr.get("bonus") if tr.get("bonus") is not None else (), np.float32).reshape(-1)
    if len(bonus) != len(rew):
        bonus = np.zeros(len(rew), np.float32)
    n = len(tr["steps"])
    stages = _per_step(tr, "stage", n, None)
    phases = _per_step(tr, "phase", n, "")
    phases = [step_phase(st, ph) for st, ph in zip(tr["steps"], phases)]
    build = [is_build_step(st, int(tr["chosen"][i]), phases[i]) for i, st in enumerate(tr["steps"])]
    if (lam_build is None or lam_build == lam) and (vf_lam is None or vf_lam == lam):
        adv, ret = gae(rew, val - bonus, lam)
    else:
        lb = lam if lam_build is None else float(lam_build)
        adv, _ = gae(rew, val - bonus, np.where(np.asarray(build, bool), lb, lam).astype(np.float64))
        _, ret = gae(rew, val - bonus, lam if vf_lam is None else float(vf_lam))
    ret = ret + bonus
    won = float(bool(res.get("won")))
    michael = float(bool(res.get("won")) and (res.get("reason") == "michael" or bool(res.get("michael"))))
    items = []
    for i, st in enumerate(tr["steps"]):
        if len(st["act_type"]) <= 1:
            continue  # forced move: no gradient
        items.append({**st, "chosen": tr["chosen"][i], "logp": tr["logp"][i], "adv": float(adv[i]), "ret": float(ret[i]),
                      "vpred": float(val[i]), "stage": stages[i], "phase": phases[i], "build": bool(build[i]),
                      "won": won, "michael": michael})
    return items


def save_ckpt(path: Path, model, opt, state: dict) -> None:
    buf = io.BytesIO()
    torch.save({"config": model.cfg.__dict__, "state": model.state_dict(), "opt": opt.state_dict(), **state,
                "py_rng": random.getstate(), "np_rng": np.random.get_state(), "torch_rng": torch.get_rng_state()}, buf)
    store.atomic_write_bytes(path, buf.getvalue())


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=str(store.RL_HOME / "ppo1"))
    ap.add_argument("--init", default=str(store.RL_HOME / "bc" / "best.pt"))
    ap.add_argument("--workers", type=int, default=7)
    ap.add_argument("--updates", type=int, default=100000, help="total updates (absolute)")
    ap.add_argument("--episodes", type=int, default=112, help="episodes per update")
    ap.add_argument("--lr", type=float, default=5e-5)
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--mb", type=int, default=512)
    ap.add_argument("--clip", type=float, default=0.15)
    ap.add_argument("--lam", type=float, default=0.95)
    ap.add_argument("--vf-coef", type=float, default=0.5)
    ap.add_argument("--ent-coef", type=float, default=0.003, help="starting entropy coefficient (adapted after)")
    ap.add_argument("--ent-target", type=float, default=0.2, help="mean policy entropy (nats) to hold; 0 = fixed coef")
    ap.add_argument("--ent-lr", type=float, default=0.3, help="max log-space change of the entropy coef per update")
    ap.add_argument("--kl-ref", choices=("champion", "init"), default="champion",
                    help="anchor policy: champion.pt (reloaded on promotion) or the BC init.pt")
    ap.add_argument("--kl-coef", type=float, default=0.1,
                    help="anchor coefficient base: kl_coef * 0.5 ** (update / kl_halflife)")
    ap.add_argument("--kl-halflife", type=float, default=300.0, help="updates for the anchor to halve")
    ap.add_argument("--target-kl", type=float, default=0.03, help="stop the epochs once one moves the PPO ratio this far")
    ap.add_argument("--max-grad", type=float, default=0.5)
    ap.add_argument("--quest-share", type=float, default=0.25)
    ap.add_argument("--no-curriculum", action="store_true", help="uniform characters / quests")
    ap.add_argument("--eval-every", type=int, default=25)
    ap.add_argument("--gate-per", type=int, default=GATE_PER, help="gate seeds per character x crown")
    ap.add_argument("--gate-per-quest", type=int, default=GATE_PER_QUEST, help="gate seeds per quest")
    ap.add_argument("--eval-per", type=int, default=None, help=argparse.SUPPRESS)   # old name of --gate-per
    ap.add_argument("--temperature", type=float, default=1.0)
    ap.add_argument("--distill-dir", default="", help="rl.exit dir: also learn the look-ahead's picks")
    ap.add_argument("--distill-coef", type=float, default=0.15)
    ap.add_argument("--distill-mb", type=int, default=128)
    ap.add_argument("--distill-same-w", type=float, default=0.1, help="weight of labels where the look-ahead agreed")
    ap.add_argument("--distill-cap", type=int, default=20000, help="newest look-ahead decisions kept")
    ap.add_argument("--distill-soft", type=float, default=0.0, metavar="TEMP",
                    help="> 0: labels with search Q values (halving search shards) are learned as "
                         "(1 - mix) * onehot(pick) + mix * softmax(Q / TEMP) over the searched candidates "
                         "(Q in outcome points); 0 = hard cross-entropy on the pick")
    ap.add_argument("--distill-soft-mix", type=float, default=0.5, help="share of softmax(Q / TEMP) in the soft target")
    ap.add_argument("--crown-weights", default="1,1,1,1,1,1,1,1",
                    help="sampling weight of crowns 0-7 for training runs (comma list; 7 = top playable)")
    ap.add_argument("--targets-mix", default="1,0,0", metavar="P_FREE,P_THEME,P_ANY",
                    help="build target of non-quest training runs: FREE / a character theme / any plan "
                         "(1,0,0 = always FREE, the unconditioned training)")
    ap.add_argument("--shaping", type=float, default=0.0, help="potential per owned on-target item (targeted runs)")
    ap.add_argument("--target-curriculum", action="store_true",
                    help="weight each character's target draws by recent win rate vs FREE (target_weights)")
    ap.add_argument("--pivot", default="", metavar="P,LO,HI",
                    help="share P of non-quest runs are PIVOT runs: start FREE, from a stage in LO..HI re-read the "
                         "build the owned items lean to at each shop entry (targets.pivot_update); default off")
    ap.add_argument("--gate-targets", action="store_true", help="add the themed gate block (evaluate.themed_gate_jobs)")
    ap.add_argument("--compare-dir", default="", help="another PPO dir (e.g. ppo1): log vs its champion on FREE gate rows")
    ap.add_argument("--michael-bonus", type=float, default=None,
                    help=f"training value of beating Michael on top of a win (16); returns / value targets and the "
                         f"gate's outcome use it, eval rows keep the game's {MICHAEL_BONUS:g}. Default: what the run "
                         f"was saved with, else {MICHAEL_BONUS:g}")
    ap.add_argument("--aux-coef", type=float, default=0.0,
                    help="weight of the aux head's BCE on the run's (won, Michael win) in the PPO loss; 0 = off")
    ap.add_argument("--lam-build", type=float, default=None,
                    help="GAE lambda of the advantages at build decisions (shop / skip / pin / boss_draft / "
                         "michael_pick steps); default = --lam")
    ap.add_argument("--vf-lam", type=float, default=None, help="GAE lambda of the value target; default = --lam")
    ap.add_argument("--vf-epochs", type=int, default=0,
                    help="value(+aux)-only passes after the policy epochs, with KL(snapshot || policy) on the "
                         "logits (--vf-kl-coef) so the policy stays put; 0 = off")
    ap.add_argument("--vf-kl-coef", type=float, default=1.0, help="KL-to-snapshot coefficient of the --vf-epochs passes")
    args = ap.parse_args(argv)
    targets_mix = parse_mix(args.targets_mix)
    pivot = parse_pivot(args.pivot)
    if targets_mix and targets_mix[0] >= sum(targets_mix):
        targets_mix = None   # all FREE: the old jobs
    if args.eval_per is not None:
        args.gate_per = args.eval_per
    out = Path(args.dir).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    ck_path = out / "ckpt.pt"
    if ck_path.is_file():
        ck = upgrade_checkpoint(torch.load(ck_path, map_location="cpu", weights_only=False))   # old obs widths -> zero-padded
        model = Policy(ModelConfig(**ck["config"])).to(device)
        model.load_state_dict(ck["state"])
        opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=0.0)
        opt.load_state_dict(upgrade_optimizer_state(ck["opt"], model))   # v1 widths -> current
        state = {k: ck[k] for k in ("update", "episodes_started", "episodes_done", "champion_update", "init")}
        state["pending_gate"] = ck.get("pending_gate", 0)
        state["ent_coef"] = float(ck.get("ent_coef", args.ent_coef))
        state["michael_bonus"] = resolve_michael_bonus(args.michael_bonus, ck, out)
        if "curriculum" in ck:
            state["curriculum"] = ck["curriculum"]
        random.setstate(ck["py_rng"])
        np.random.set_state(ck["np_rng"])
        torch.set_rng_state(ck["torch_rng"])
        print(f"resumed at update {state['update']}", flush=True)
    else:
        init = str(Path(args.init).expanduser())
        model, _ = load_policy(init, device=str(device))
        opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=0.0)
        state = {"update": 0, "episodes_started": 0, "episodes_done": 0, "champion_update": 0, "init": init,
                 "pending_gate": 0, "ent_coef": args.ent_coef,
                 "michael_bonus": resolve_michael_bonus(args.michael_bonus, None, out)}
        shutil.copyfile(init, out / "init.pt")
        shutil.copyfile(init, out / "champion.pt")
        random.seed(1)
        np.random.seed(1)
    mb = float(state["michael_bonus"])
    if mb != MICHAEL_BONUS:
        print(f"michael bonus {mb:g} (training returns / gate outcome; eval rows keep {MICHAEL_BONUS:g})", flush=True)
    cmd_argv = command_argv(argv if argv is not None else __import__("sys").argv[1:], args.michael_bonus, mb)
    (out / "command.txt").write_text("python -m cursed_words_solver.rl.ppo " + " ".join(cmd_argv) + "\n")
    # rolling win tallies (from episodes.jsonl the first time a checkpoint lacks them)
    if "curriculum" in state:
        curr = Curriculum(state["curriculum"]["chars"], state["curriculum"]["quests"],
                          state["curriculum"].get("targets", ()))
        if not curr.targets:  # checkpoints from before the target curriculum: rebuild its tallies
            curr.targets.extend(Curriculum.from_episodes(out / "episodes.jsonl").targets)
    else:
        curr = Curriculum.from_episodes(out / "episodes.jsonl")
    weights = out / "weights.pt"
    save_policy(model, weights, {"update": state["update"]})
    distill = None
    if args.distill_dir:
        c = model.cfg
        distill = DistillBuffer(Path(args.distill_dir).expanduser(), cap=args.distill_cap, same_w=args.distill_same_w,
                                widths=(c.n_global, c.n_tok_feat, c.n_act_feat))
    from cursed_words_solver.rl.evaluate import (champion_eval_path, gate_jobs as make_gate_jobs, paired, promote_ok,
                                                 row_outcome, run_arm, summarize, themed_gate_jobs)
    from cursed_words_solver.rl.play import init_worker, play
    from cursed_words_solver.sim.game.agent import spawn_pool

    pool = spawn_pool(args.workers, init_worker, ())
    gate_jobs = make_gate_jobs(args.gate_per, args.gate_per_quest)
    if args.gate_targets:
        gate_jobs = gate_jobs + themed_gate_jobs()
    eval_dir = out / "eval"
    # finish a promotion a crash interrupted (state is saved before the files are copied)
    cu = state["champion_update"]
    if cu and (out / f"cand_u{cu}.pt").is_file():
        shutil.copyfile(out / f"cand_u{cu}.pt", out / "champion.pt")
        if (eval_dir / f"u{cu}.jsonl").is_file():
            shutil.copyfile(eval_dir / f"u{cu}.jsonl", eval_dir / f"champion_u{cu}.jsonl")
        (out / f"cand_u{cu}.pt").unlink(missing_ok=True)
    ref = None

    def load_ref() -> None:
        nonlocal ref
        if args.kl_coef <= 0:
            return
        ref, _ = load_policy(out / ("champion.pt" if args.kl_ref == "champion" else "init.pt"), device=str(device))
        for p in ref.parameters():
            p.requires_grad_(False)

    load_ref()

    def champion_rows() -> list[dict]:
        """The champion on every gate job (run_arm plays only the missing ones, e.g. after the gate grew)."""
        return run_arm(f"champion_u{state['champion_update']}", str(out / "champion.pt"), gate_jobs,
                       out_dir=eval_dir, pool=pool, verbose=False)

    if state["update"] == 0 or not (eval_dir / f"champion_u{state['champion_update']}.jsonl").is_file():
        print("evaluating the starting champion on the gate set...", flush=True)
        champion_rows()
    rng = random.Random(state["episodes_started"] * 7919 + 13)
    crown_w = [float(x) for x in args.crown_weights.split(",")]
    assert len(crown_w) == 8, "--crown-weights needs 8 values (crowns 0-7)"
    cw = {"char": None, "quest": None, "target": None}
    in_flight: deque = deque()
    recent: deque = deque(maxlen=500)

    def set_curriculum() -> dict:
        w = curr.weights()
        if not args.no_curriculum:
            cw["char"], cw["quest"] = w["char"], w["quest"]
        if args.target_curriculum:
            cw["target"] = w["target"]
        store.atomic_write_json(out / "curriculum.json", {
            "update": state["update"], "enabled": not args.no_curriculum, "quest_share": args.quest_share,
            "crown_weights": crown_w, "targets_mix": list(targets_mix) if targets_mix else None,
            "target_curriculum": bool(args.target_curriculum), **({"pivot": list(pivot)} if pivot else {}),
            "michael_bonus": mb, **w})
        return w

    set_curriculum()

    def submit() -> None:
        j = sample_job(rng, state["episodes_started"], args.quest_share, crown_w, cw["char"], cw["quest"],
                       targets_mix, args.shaping, cw["target"], pivot)
        state["episodes_started"] += 1
        in_flight.append(pool.apply_async(play, ({**j, "policy": str(weights), "record": True,
                                                   "temperature": args.temperature, "michael_bonus": mb},)))

    def ckpt() -> None:
        save_ckpt(ck_path, model, opt, {**state, "curriculum": curr.state()})

    def gate(u: int) -> None:
        """Paired eval of candidate cand_u{u}.pt vs the champion; resumable (run_arm appends)."""
        arm = f"u{u}"
        cand = out / f"cand_{arm}.pt"
        champ = [r for r in champion_rows() if not r.get("error")]
        rows = run_arm(arm, str(cand), gate_jobs, out_dir=eval_dir, pool=pool, verbose=False)
        cmp = paired(rows, champ, michael_bonus=mb)   # outcome with the training Michael bonus
        promote = promote_ok(cmp)
        teacher = [r for r in store.read_jsonl(eval_dir / "teacher.jsonl") if not r.get("error")]
        grow = {"update": u, "eval": summarize(rows, mb), "vs_champion": cmp, "promoted": promote,
                "rule": "win_diff>0 & outcome_diff>0 & max(t, win_z)>=1"
                        + (f" (outcome: Michael win = 16+{mb:g})" if mb != MICHAEL_BONUS else ""),
                "gate_n": len(gate_jobs),
                "champion_update": state["champion_update"],
                "vs_teacher": paired(rows, teacher) if teacher else None}
        if args.gate_targets:
            free = [r for r in rows if not r.get("target")]
            themed = [r for r in rows if r.get("target")]
            grow["eval_free"], grow["eval_themed"] = summarize(free, mb), summarize(themed, mb)
            grow["vs_champion_free"] = paired(free, champ, michael_bonus=mb)
            grow["vs_champion_themed"] = paired(themed, champ, michael_bonus=mb)
            p1 = eval_dir / "ppo1_champion.jsonl"   # pipeline baseline2: the ppo1 champion on this gate
            if p1.is_file():
                grow["vs_ppo1_all"] = paired(rows, [r for r in store.read_jsonl(p1) if not r.get("error")])
        if args.compare_dir:
            cp = champion_eval_path(Path(args.compare_dir).expanduser())
            if cp is not None:
                other = [r for r in store.read_jsonl(cp) if not r.get("error")]
                grow["vs_ppo1"] = paired([r for r in rows if not r.get("target")], other)
                grow["vs_ppo1_src"] = str(cp)
        if mb != MICHAEL_BONUS:
            grow["michael_bonus"] = mb
        print("GATE", grow, flush=True)
        store.append_jsonl(out / "gates.jsonl", grow)
        state["pending_gate"] = 0
        if promote:
            state["champion_update"] = u
            ckpt()   # commit the decision, then move files
            shutil.copyfile(eval_dir / f"{arm}.jsonl", eval_dir / f"champion_u{u}.jsonl")
            shutil.copyfile(cand, out / "champion.pt")
            if args.kl_ref == "champion":
                load_ref()
        else:
            ckpt()
        cand.unlink(missing_ok=True)

    if state.get("pending_gate"):
        u = state["pending_gate"]
        if (out / f"cand_u{u}.pt").is_file():
            print(f"finishing the interrupted gate of update {u}", flush=True)
            gate(u)
        else:
            state["pending_gate"] = 0

    for _ in range(args.workers * 2):
        submit()
    buf_items: list[dict] = []
    buf_eps: list[dict] = []
    t_last = time.time()
    try:
        while state["update"] < args.updates:
            # collect
            while len(buf_eps) < args.episodes:
                ready = [a for a in in_flight if a.ready()]
                if not ready:
                    time.sleep(0.05)
                    continue
                for a in ready:
                    in_flight.remove(a)
                    res = a.get()
                    submit()
                    if res.get("error"):
                        print("episode error:", res["error"], res.get("trace", "")[-400:], flush=True)
                        continue
                    buf_items.extend(episode_items(res, args.lam, mb, lam_build=args.lam_build, vf_lam=args.vf_lam))
                    res.pop("traj", None)
                    buf_eps.append(res)
                    recent.append(res)
                    state["episodes_done"] += 1
            # learn
            args.kl_coef_now = args.kl_coef * 0.5 ** (state["update"] / max(1e-9, args.kl_halflife))
            ent_coef = state["ent_coef"]
            a2 = argparse.Namespace(**{**vars(args), "kl_coef": args.kl_coef_now, "ent_coef": ent_coef})
            if buf_items:
                advs = np.asarray([it["adv"] for it in buf_items], np.float32)
                mu, sd = float(advs.mean()), float(advs.std() + 1e-6)
                for it in buf_items:
                    it["adv"] = (it["adv"] - mu) / sd
                if distill is not None:
                    distill.refresh()
                st = ppo_update(model, ref, opt, buf_items, a2, device, distill)
                if distill is not None:
                    st["distill_n"] = len(distill.items)
                    st["distill_changed"] = distill.n_changed
                if args.ent_target > 0 and "ent" in st:
                    state["ent_coef"] = adapt_ent_coef(ent_coef, st["ent"], args.ent_target, args.ent_lr)
            else:
                st = {}
            state["update"] += 1
            save_policy(model, weights, {"update": state["update"]})
            for r in buf_eps:
                curr.add(r)
            w = set_curriculum()
            dt = time.time() - t_last
            t_last = time.time()
            row = {"update": state["update"], "episodes": state["episodes_done"], "steps": len(buf_items),
                   "secs": round(dt, 1), "eps_per_h": round(len(buf_eps) / max(1e-9, dt) * 3600),
                   **{f"train_{k}": v for k, v in summarize(buf_eps, mb).items()},
                   "recent_win": round(float(np.mean([bool(r["won"]) for r in recent])), 4),
                   "recent_outcome": round(float(np.mean([r["outcome"] for r in recent])), 3),
                   **({"recent_train_outcome": round(float(np.mean([row_outcome(r, mb) for r in recent])), 3),
                       "michael_bonus": mb} if mb != MICHAEL_BONUS else {}),
                   "kl_coef": round(args.kl_coef_now, 4), "kl_ref_src": args.kl_ref,
                   "ent_coef": round(ent_coef, 5), "ent_coef_next": round(state["ent_coef"], 5),
                   "curr_char_w": {k: v for k, v in w["char"].items() if v != 1.0}, **st}
            fix = {k: v for k, v in (("aux_coef", args.aux_coef), ("lam_build", args.lam_build), ("vf_lam", args.vf_lam),
                                     ("vf_epochs", args.vf_epochs)) if v}
            if fix:
                row["ppofix"] = fix
            if targets_mix or pivot:
                row["train_by_target"] = by_target(recent)
            if pivot:
                row["train_pivot"] = by_pivot(recent)
            print(row, flush=True)
            due = state["update"] % args.eval_every == 0
            if due:
                shutil.copyfile(weights, out / f"cand_u{state['update']}.pt")
                state["pending_gate"] = state["update"]
            ckpt()
            # logs after the checkpoint: a crash can drop a row, never duplicate one
            store.append_jsonl(out / "history.jsonl", row)
            for r in buf_eps:
                store.append_jsonl(out / "episodes.jsonl", r)
            buf_items, buf_eps = [], []
            if due:
                gate(state["update"])
            if store.stop_requested(out):
                print("STOP file found: checkpointed, exiting", flush=True)
                break
    finally:
        pool.terminate()


if __name__ == "__main__":
    main()
