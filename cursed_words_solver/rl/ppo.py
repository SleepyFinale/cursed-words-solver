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
``--gate-targets`` adds ``evaluate.themed_gate_jobs`` (144 themed runs) to the gate; promotion
is decided over all gate rows, paired by key (target included). ``--compare-dir`` (e.g. ppo1)
logs ``vs_ppo1`` on the FREE gate rows against that dir's champion eval rows.

Pause / resume: rerun the same command (``command.txt``). State is checkpointed after every
update (model, optimiser, counters, RNG); episodes in flight at a kill are simply replayed
with new seeds. ``STOP`` file in the dir = checkpoint and exit.

    python -m cursed_words_solver.rl.ppo --dir ~/.cursed_words_solver/rl/ppo1 --init ~/.cursed_words_solver/rl/bc/best.pt
"""

from __future__ import annotations

import argparse
import io
import math
import random
import shutil
import time
from collections import deque
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn.functional as F

from cursed_words_solver.rl import store
from cursed_words_solver.rl.bc import VALUE_SCALE
from cursed_words_solver.rl.evaluate import GATE_PER, GATE_PER_QUEST
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
               targets_mix: tuple[float, float, float] | None = None, shaping: float = 0.0) -> dict[str, Any]:
    """Training job; ``char_w`` / ``quest_w`` (curriculum) weight the draws, None = uniform (old draws).
    ``targets_mix`` (p_free, p_theme, p_any): the run's build target (``targets.sample_target``
    with ``target_rng(n)``; quest runs stay FREE: their quest fixes the plan); None = FREE."""
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
    t = sample_target(target_rng(n), ch, targets_mix) if targets_mix and targets_mix[0] < sum(targets_mix) else FREE
    return {"character": ch, "crown": cr, "quest": None, "seed": TRAIN_SEED0 + n, "target": t, "shaping": shaping}


def by_target(rows) -> dict[str, dict]:
    """Rolling training stats per build target ("free" for FREE): n, win rate, mean on-plan items."""
    from cursed_words_solver.rl.targets import file_tag

    g: dict[str, list[dict]] = {}
    for r in rows:
        g.setdefault(file_tag(r.get("target") or ""), []).append(r)
    return {t: {"n": len(v), "win": round(sum(bool(r["won"]) for r in v) / len(v), 4),
                "on_plan": round(sum(r.get("on_plan", 0) for r in v) / len(v), 2)} for t, v in sorted(g.items())}


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


class Curriculum:
    """Rolling (character, won) / (quest, won) tallies of training episodes; saved in the checkpoint."""

    def __init__(self, char_rows=(), quest_rows=()) -> None:
        self.chars: deque = deque((tuple(r) for r in char_rows), maxlen=CURR_WINDOW)
        self.quests: deque = deque((tuple(r) for r in quest_rows), maxlen=CURR_QUEST_WINDOW)

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

    def state(self) -> dict:
        return {"chars": [list(x) for x in self.chars], "quests": [list(x) for x in self.quests]}

    def weights(self) -> dict:
        from cursed_words_solver.sim.game.challenges import QUESTS

        cw, cr = curriculum_weights(self.chars, CHARS)
        qw, qr = curriculum_weights(self.quests, sorted(QUESTS))
        return {"char": cw, "quest": qw, "char_win": cr, "quest_win": qr,
                "n_char": len(self.chars), "n_quest": len(self.quests)}


def adapt_ent_coef(coef: float, ent: float, target: float, lr: float, lo: float = 1e-4, hi: float = 0.2) -> float:
    """Log-space step toward the entropy target: entropy below target -> larger bonus."""
    if target <= 0 or not math.isfinite(ent):
        return coef
    step = lr * max(-1.0, min(1.0, (target - ent) / target))
    return float(min(hi, max(lo, coef * math.exp(step))))


def gae(rew: np.ndarray, val: np.ndarray, lam: float, gamma: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    n = len(rew)
    adv = np.zeros(n, np.float32)
    last = 0.0
    for t in range(n - 1, -1, -1):
        nv = val[t + 1] if t + 1 < n else 0.0
        delta = rew[t] + gamma * nv - val[t]
        last = delta + gamma * lam * last
        adv[t] = last
    return adv, adv + val


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
            G, Ft = LEGACY_GLOBAL[v - LEGACY_OBS_VERSION], LEGACY_TOKEN[v - LEGACY_OBS_VERSION]
        g, tf, af = ep.get("glob"), ep.get("tok_feat"), ep.get("act_feat")
        if g is None or af is None or g.ndim != 2 or g.shape[1] != G or af.ndim != 2 or af.shape[1] != Fa:
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


def ppo_update(model: Policy, ref: Policy | None, opt, batch: list[dict], args, device,
               distill: DistillBuffer | None = None) -> dict:
    model.train()
    idx = np.arange(len(batch))
    stats: dict[str, list[float]] = {}
    beta = args.kl_coef
    for _ in range(args.epochs):
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
    return {k: round(float(np.mean(v)), 4) for k, v in stats.items()}


def episode_items(res: dict, lam: float) -> list[dict]:
    tr = res["traj"]
    if not tr["steps"]:
        return []
    rew = np.asarray(tr["reward"], np.float32)
    val = np.asarray(tr["value"], np.float32) * VALUE_SCALE
    # build-target shaping: the value head predicts the UNSHAPED return-to-go (what search /
    # assistant add to the plain potential); the shaped one is that minus the step's shaping
    # bonus (shaping * on-target items), so GAE runs on shaped values and the target adds it back
    bonus = np.asarray(tr.get("bonus") if tr.get("bonus") is not None else (), np.float32).reshape(-1)
    if len(bonus) != len(rew):
        bonus = np.zeros(len(rew), np.float32)
    adv, ret = gae(rew, val - bonus, lam)
    ret = ret + bonus
    items = []
    for i, st in enumerate(tr["steps"]):
        if len(st["act_type"]) <= 1:
            continue  # forced move: no gradient
        items.append({**st, "chosen": tr["chosen"][i], "logp": tr["logp"][i], "adv": float(adv[i]), "ret": float(ret[i])})
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
    ap.add_argument("--gate-targets", action="store_true", help="add the themed gate block (evaluate.themed_gate_jobs)")
    ap.add_argument("--compare-dir", default="", help="another PPO dir (e.g. ppo1): log vs its champion on FREE gate rows")
    args = ap.parse_args(argv)
    targets_mix = parse_mix(args.targets_mix)
    if targets_mix and targets_mix[0] >= sum(targets_mix):
        targets_mix = None   # all FREE: the old jobs
    if args.eval_per is not None:
        args.gate_per = args.eval_per
    out = Path(args.dir).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    (out / "command.txt").write_text("python -m cursed_words_solver.rl.ppo " + " ".join(argv or __import__("sys").argv[1:]) + "\n")
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
                 "pending_gate": 0, "ent_coef": args.ent_coef}
        shutil.copyfile(init, out / "init.pt")
        shutil.copyfile(init, out / "champion.pt")
        random.seed(1)
        np.random.seed(1)
    # rolling win tallies (from episodes.jsonl the first time a checkpoint lacks them)
    if "curriculum" in state:
        curr = Curriculum(state["curriculum"]["chars"], state["curriculum"]["quests"])
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
                                                 run_arm, summarize, themed_gate_jobs)
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
    cw = {"char": None, "quest": None}
    in_flight: deque = deque()
    recent: deque = deque(maxlen=500)

    def set_curriculum() -> dict:
        w = curr.weights()
        if not args.no_curriculum:
            cw["char"], cw["quest"] = w["char"], w["quest"]
        store.atomic_write_json(out / "curriculum.json", {
            "update": state["update"], "enabled": not args.no_curriculum, "quest_share": args.quest_share,
            "crown_weights": crown_w, "targets_mix": list(targets_mix) if targets_mix else None, **w})
        return w

    set_curriculum()

    def submit() -> None:
        j = sample_job(rng, state["episodes_started"], args.quest_share, crown_w, cw["char"], cw["quest"],
                       targets_mix, args.shaping)
        state["episodes_started"] += 1
        in_flight.append(pool.apply_async(play, ({**j, "policy": str(weights), "record": True,
                                                   "temperature": args.temperature},)))

    def ckpt() -> None:
        save_ckpt(ck_path, model, opt, {**state, "curriculum": curr.state()})

    def gate(u: int) -> None:
        """Paired eval of candidate cand_u{u}.pt vs the champion; resumable (run_arm appends)."""
        arm = f"u{u}"
        cand = out / f"cand_{arm}.pt"
        champ = [r for r in champion_rows() if not r.get("error")]
        rows = run_arm(arm, str(cand), gate_jobs, out_dir=eval_dir, pool=pool, verbose=False)
        cmp = paired(rows, champ)
        promote = promote_ok(cmp)
        teacher = [r for r in store.read_jsonl(eval_dir / "teacher.jsonl") if not r.get("error")]
        grow = {"update": u, "eval": summarize(rows), "vs_champion": cmp, "promoted": promote,
                "rule": "win_diff>0 & outcome_diff>0 & max(t, win_z)>=1", "gate_n": len(gate_jobs),
                "champion_update": state["champion_update"],
                "vs_teacher": paired(rows, teacher) if teacher else None}
        if args.gate_targets:
            free = [r for r in rows if not r.get("target")]
            themed = [r for r in rows if r.get("target")]
            grow["eval_free"], grow["eval_themed"] = summarize(free), summarize(themed)
            grow["vs_champion_free"], grow["vs_champion_themed"] = paired(free, champ), paired(themed, champ)
            p1 = eval_dir / "ppo1_champion.jsonl"   # pipeline baseline2: the ppo1 champion on this gate
            if p1.is_file():
                grow["vs_ppo1_all"] = paired(rows, [r for r in store.read_jsonl(p1) if not r.get("error")])
        if args.compare_dir:
            cp = champion_eval_path(Path(args.compare_dir).expanduser())
            if cp is not None:
                other = [r for r in store.read_jsonl(cp) if not r.get("error")]
                grow["vs_ppo1"] = paired([r for r in rows if not r.get("target")], other)
                grow["vs_ppo1_src"] = str(cp)
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
                    buf_items.extend(episode_items(res, args.lam))
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
                   **{f"train_{k}": v for k, v in summarize(buf_eps).items()},
                   "recent_win": round(float(np.mean([bool(r["won"]) for r in recent])), 4),
                   "recent_outcome": round(float(np.mean([r["outcome"] for r in recent])), 3),
                   "kl_coef": round(args.kl_coef_now, 4), "kl_ref_src": args.kl_ref,
                   "ent_coef": round(ent_coef, 5), "ent_coef_next": round(state["ent_coef"], 5),
                   "curr_char_w": {k: v for k, v in w["char"].items() if v != 1.0}, **st}
            if targets_mix:
                row["train_by_target"] = by_target(recent)
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
