"""Behaviour cloning on teacher shards (GPU when available). Resumable: rerun the command.

Loss = cross-entropy on the teacher's pick + value (return still to come, Huber) +
auxiliary P(win) / P(Michael win). Runs with ``i % 10 == 0`` are held out for validation.
New shards written by a running teacher job are picked up at every epoch.

    python -m cursed_words_solver.rl.bc --data ~/.cursed_words_solver/rl/teacher --dir ~/.cursed_words_solver/rl/bc

Build-conditioned fine-tune: several ``--data`` dirs (comma list or repeated), ``--init`` a
checkpoint to start from (only when ``<dir>/last.pt`` does not exist; fresh AdamW at ``--lr``),
and an ``--anchor`` policy with ``--anchor-coef``: every batch is also fed with its target columns
zeroed (a FREE copy) and ``anchor_coef * KL(anchor(free) || student(free))`` is added, so FREE play
stays the anchor's while themed shards teach the targets.

    python -m cursed_words_solver.rl.bc --data ~/.cursed_words_solver/rl/teacher,~/.cursed_words_solver/rl/teacher_themed \\
        --dir ~/.cursed_words_solver/rl/bc_cond --init ~/.cursed_words_solver/rl/ppo1/champion.pt \\
        --anchor ~/.cursed_words_solver/rl/ppo1/champion.pt --anchor-coef 1.0 --lr 1e-4 --epochs 10
"""

from __future__ import annotations

import argparse
import math
import random
import threading
import queue
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

from cursed_words_solver.rl import store
from cursed_words_solver.rl.model import (Policy, collate, default_config, load_policy, save_policy, ModelConfig,
                                          upgrade_checkpoint, upgrade_optimizer_state)


def run_index(path: Path) -> int:
    return int(path.name.split("_", 1)[0])


def data_dirs(values) -> list[Path]:
    """``--data`` values (each may be a comma list) -> directories, in order, without repeats."""
    if isinstance(values, (str, Path)):
        values = [values]
    out: list[Path] = []
    for v in values:
        for part in str(v).split(","):
            part = part.strip()
            if part:
                p = Path(part).expanduser()
                if p not in out:
                    out.append(p)
    return out


def _episode_target(ep: dict) -> str:
    from cursed_words_solver.rl.teacher import shard_target

    return shard_target(ep)


class Dataset:
    """Episodes kept compressed-ish (float16 arrays) in memory; steps unpacked per batch.
    Several data dirs mix; episodes are keyed by their full path."""

    def __init__(self, data_dir) -> None:
        self.dirs = [d / "shards" for d in data_dirs(data_dir)]
        self.dir = self.dirs[0] if self.dirs else None
        self.eps: dict[str, dict] = {}
        self.train: list[tuple[str, int]] = []
        self.val: list[tuple[str, int]] = []

    def refresh(self) -> int:
        added = 0
        for d in self.dirs:
            for p in sorted(d.glob("*.npz")):
                if "_c8_" in p.name:   # crown 8 is not playable (old teacher runs)
                    continue
                key = str(p)
                if key in self.eps:
                    continue
                try:
                    ep = store.load_episode(p)
                except Exception:
                    continue  # being written
                rew = ep["reward"].astype(np.float64)
                ep["rtg"] = np.cumsum(rew[::-1])[::-1].astype(np.float32)
                ep["themed"] = np.int8(bool(_episode_target(ep)))
                self.eps[key] = ep
                target = self.val if run_index(p) % 10 == 0 else self.train
                n_act = np.diff(ep["act_off"])
                for i in range(len(ep["chosen"])):
                    if n_act[i] > 1 or target is self.val:
                        target.append((key, i))
                added += 1
        return added

    def item(self, key: tuple[str, int]) -> dict:
        name, i = key
        ep = self.eps[name]
        s = store.unpack_step(ep, i)
        s["chosen"] = int(ep["chosen"][i])
        s["rtg"] = float(ep["rtg"][i])
        s["won"] = float(ep["won"])
        s["michael"] = float(ep["michael"])
        s["themed"] = float(ep.get("themed", 0))
        return s


def make_batch(ds: Dataset, keys, device):
    items = [ds.item(k) for k in keys]
    b = collate(items, device)
    b["chosen"] = torch.tensor([it["chosen"] for it in items], device=device)
    b["rtg"] = torch.tensor([it["rtg"] for it in items], device=device)
    b["won"] = torch.tensor([it["won"] for it in items], device=device)
    b["michael"] = torch.tensor([it["michael"] for it in items], device=device)
    b["n_act"] = torch.tensor([len(it["act_type"]) for it in items], device=device)
    b["themed"] = torch.tensor([it.get("themed", 0.0) for it in items], device=device)
    return b


VALUE_SCALE = 8.0


def target_columns() -> tuple[list[int], list[int]]:
    """Indices of the target-build columns (global ``target_set`` / ``target:*``, token ``pc:*``)."""
    from cursed_words_solver.rl.obs import global_columns, token_columns

    g = [i for n, i in global_columns().items() if n == "target_set" or n.startswith("target:")]
    t = [i for n, i in token_columns().items() if n.startswith("pc:")]
    return g, t


def free_copy(b: dict) -> dict:
    """The batch with its target columns zeroed (the same states seen as FREE). Columns past a
    batch's width (older shards) are already absent / zero."""
    g, t = target_columns()
    out = dict(b)
    glob = b["glob"].clone()
    gi = [i for i in g if i < glob.shape[-1]]
    if gi:
        glob[..., gi] = 0
    tok = b["tok_feat"].clone()
    ti = [i for i in t if i < tok.shape[-1]]
    if ti:
        tok[..., ti] = 0
    out["glob"], out["tok_feat"] = glob, tok
    return out


def masked_kl(p_logits: torch.Tensor, q_logits: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    """Mean over the batch of KL(p || q) over the legal (``mask``) actions, temperature 1."""
    legal = mask > 0
    lp = torch.log_softmax(p_logits.masked_fill(~legal, -1e9), -1)
    lq = torch.log_softmax(q_logits.masked_fill(~legal, -1e9), -1)
    kl = torch.where(legal, lp.exp() * (lp - lq), torch.zeros_like(lp)).sum(-1)
    return kl.mean()


def anchor_kl(model: Policy, anchor: Policy, b: dict) -> torch.Tensor:
    """KL(anchor(free) || student(free)) on the FREE copy of ``b`` (anchor frozen)."""
    fb = free_copy(b)
    with torch.no_grad():
        a_logits = anchor(fb)["logits"]
    return masked_kl(a_logits, model(fb)["logits"], b["act_mask"])


def losses(model: Policy, b: dict, *, w_value: float = 0.5, w_aux: float = 0.2, anchor: Policy | None = None,
           anchor_coef: float = 0.0) -> tuple[torch.Tensor, dict]:
    out = model(b)
    ce = F.cross_entropy(out["logits"], b["chosen"])
    v = F.smooth_l1_loss(out["value"], b["rtg"] / VALUE_SCALE)
    aux = F.binary_cross_entropy_with_logits(out["aux"], torch.stack([b["won"], b["michael"]], -1))
    acc = (out["logits"].argmax(-1) == b["chosen"]).float().mean()
    loss = ce + w_value * v + w_aux * aux
    st = {"ce": ce.item(), "v": v.item(), "aux": aux.item(), "acc": acc.item()}
    if anchor is not None and anchor_coef > 0:
        kl = anchor_kl(model, anchor, b)
        loss = loss + anchor_coef * kl
        st["anchor_kl"] = kl.item()
    return loss, st


def prefetch(ds: Dataset, keys: list, bs: int, device, depth: int = 4):
    q: queue.Queue = queue.Queue(depth)

    def work():
        for i in range(0, len(keys), bs):
            q.put(make_batch(ds, keys[i:i + bs], device))
        q.put(None)

    th = threading.Thread(target=work, daemon=True)
    th.start()
    while True:
        b = q.get()
        if b is None:
            return
        yield b


@torch.no_grad()
def validate(model: Policy, ds: Dataset, device, bs: int = 1024, limit: int = 40000,
             anchor: Policy | None = None) -> dict:
    model.eval()
    keys = ds.val[:limit]
    tot: dict[str, float] = {}
    n = 0
    by_kind: dict[int, list[float]] = {}
    # multi-action decisions split by FREE / themed episode: [sum ce, sum right, count]
    by_target = {"free": [0.0, 0.0, 0], "themed": [0.0, 0.0, 0]}
    for b in prefetch(ds, keys, bs, device):
        out = model(b)
        multi = b["n_act"] > 1
        pred = out["logits"].argmax(-1)
        right = (pred == b["chosen"]).float()
        ce = F.cross_entropy(out["logits"], b["chosen"], reduction="none")
        k = len(b["chosen"])
        for name, val in (("ce", (ce * multi).sum() / multi.sum().clamp(min=1)), ("acc", (right * multi).sum() / multi.sum().clamp(min=1)),
                          ("v_mae", (out["value"] * VALUE_SCALE - b["rtg"]).abs().mean())):
            tot[name] = tot.get(name, 0.0) + float(val) * k
        if anchor is not None:
            tot["anchor_kl"] = tot.get("anchor_kl", 0.0) + float(anchor_kl(model, anchor, b)) * k
        chosen_type = torch.gather(b["act_type"], 1, b["chosen"].unsqueeze(1)).squeeze(1)
        for t, r, m in zip(chosen_type.tolist(), right.tolist(), multi.tolist()):
            if m:
                by_kind.setdefault(t, []).append(r)
        for name, sel in (("free", multi & (b["themed"] == 0)), ("themed", multi & (b["themed"] > 0))):
            acc_ = by_target[name]
            acc_[0] += float((ce * sel).sum())
            acc_[1] += float((right * sel).sum())
            acc_[2] += int(sel.sum())
        n += k
    model.train()
    from cursed_words_solver.rl.actions import ACTION_TYPES

    res = {k: v / max(1, n) for k, v in tot.items()}
    res["by_kind"] = {ACTION_TYPES[t]: (round(float(np.mean(v)), 3), len(v)) for t, v in sorted(by_kind.items())}
    for name, (s_ce, s_right, c) in by_target.items():
        if c:
            res[f"ce_{name}"] = s_ce / c
            res[f"acc_{name}"] = s_right / c
    return res


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", action="append", default=None,
                    help="teacher dir(s): comma list and/or repeat the flag (default <rl home>/teacher)")
    ap.add_argument("--dir", default=str(store.RL_HOME / "bc"))
    ap.add_argument("--epochs", type=int, default=30, help="total epochs (absolute)")
    ap.add_argument("--steps", type=int, default=1500, help="batches per epoch")
    ap.add_argument("--bs", type=int, default=512)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--d", type=int, default=128)
    ap.add_argument("--layers", type=int, default=3)
    ap.add_argument("--init", default="", help="start from this policy checkpoint (fine-tune; only without last.pt)")
    ap.add_argument("--anchor", default="", help="frozen policy whose FREE behaviour to keep (e.g. ppo1/champion.pt)")
    ap.add_argument("--anchor-coef", type=float, default=0.0, help="weight of KL(anchor(free) || student(free))")
    args = ap.parse_args(argv)
    data = data_dirs(args.data or [str(store.RL_HOME / "teacher")])
    out = Path(args.dir).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    (out / "command.txt").write_text(
        f"python -m cursed_words_solver.rl.bc --data {','.join(str(d) for d in data)} --dir {out} --epochs {args.epochs}"
        f" --steps {args.steps} --bs {args.bs} --lr {args.lr}"
        + (f" --init {args.init}" if args.init else "")
        + (f" --anchor {args.anchor} --anchor-coef {args.anchor_coef}" if args.anchor else "") + "\n")
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    ds = Dataset(data)
    anchor = None
    if args.anchor and args.anchor_coef > 0:
        anchor, _ = load_policy(Path(args.anchor).expanduser(), device=str(device))
        anchor.eval()
        for prm in anchor.parameters():
            prm.requires_grad_(False)
    ck_path = out / "last.pt"
    if ck_path.is_file():
        ck = upgrade_checkpoint(torch.load(ck_path, map_location="cpu", weights_only=False))   # older widths -> current
        model = Policy(ModelConfig(**ck["config"])).to(device)
        model.load_state_dict(ck["state"])
        opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
        opt.load_state_dict(upgrade_optimizer_state(ck["opt"], model))
        epoch, best = ck["epoch"], ck.get("best", math.inf)
        start_step, best_val_n = ck.get("step", 0), ck.get("best_val_n", -1)
        random.setstate(ck["py_rng"])
        torch.set_rng_state(ck["torch_rng"])
        print(f"resumed at epoch {epoch}", flush=True)
    else:
        if args.init:
            model, _ = load_policy(Path(args.init).expanduser(), device=str(device))   # widened to current obs
            model.train()
            print(f"initialised from {args.init}", flush=True)
        else:
            cfg = default_config()
            cfg.d, cfg.layers = args.d, args.layers
            model = Policy(cfg).to(device)
        opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
        epoch, best = 0, math.inf
        start_step, best_val_n = 0, -1
        random.seed(0)
    print(f"params {sum(p.numel() for p in model.parameters())/1e6:.2f}M on {device}", flush=True)
    total = args.epochs * args.steps
    sched = lambda step: args.lr * (0.1 + 0.9 * 0.5 * (1 + math.cos(math.pi * min(1.0, step / max(1, total)))))
    while epoch < args.epochs:
        added = ds.refresh()
        if not ds.train:
            print("no data yet; waiting", flush=True)
            time.sleep(60)
            continue
        t0 = time.time()
        keys = [random.choice(ds.train) for _ in range((args.steps - start_step) * args.bs)]
        stats: dict[str, float] = {}
        model.train()
        done_steps = start_step
        for s, b in enumerate(prefetch(ds, keys, args.bs, device), start=start_step):
            for gparam in opt.param_groups:
                gparam["lr"] = sched(epoch * args.steps + s)
            loss, st = losses(model, b, anchor=anchor, anchor_coef=args.anchor_coef)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            done_steps = s + 1
            for k, v in st.items():
                stats[k] = stats.get(k, 0.0) * 0.98 + v * 0.02 if k in stats else v
            if store.stop_requested(out):
                break
        if done_steps < args.steps:
            # paused mid-epoch: keep the epoch open and resume from this step
            start_step = done_steps
        else:
            start_step = 0
            val = validate(model, ds, device, anchor=anchor)
            epoch += 1
            row = {"epoch": epoch, "episodes": len(ds.eps), "train_steps": len(ds.train), "added": added,
                   "secs": round(time.time() - t0, 1), **{f"train_{k}": round(v, 4) for k, v in stats.items()},
                   **{f"val_{k}": (round(v, 4) if isinstance(v, float) else v) for k, v in val.items()}}
            print(row, flush=True)
            store.append_jsonl(out / "history.jsonl", row)
            val_n = min(len(ds.val), 40000)
            if val_n != best_val_n:   # the validation set grew: old best CE is not comparable
                best, best_val_n = math.inf, val_n
            if val["ce"] < best:
                best = val["ce"]
                save_policy(model, out / "best.pt", {"epoch": epoch, "val": {k: v for k, v in val.items() if k != "by_kind"}})
            save_policy(model, out / "policy.pt", {"epoch": epoch})
        buf = {"config": model.cfg.__dict__, "state": model.state_dict(), "opt": opt.state_dict(), "epoch": epoch,
               "best": best, "best_val_n": best_val_n, "step": start_step,
               "py_rng": random.getstate(), "torch_rng": torch.get_rng_state()}
        import io

        bio = io.BytesIO()
        torch.save(buf, bio)
        store.atomic_write_bytes(ck_path, bio.getvalue())
        if store.stop_requested(out):
            print("STOP file found", flush=True)
            break


if __name__ == "__main__":
    main()
