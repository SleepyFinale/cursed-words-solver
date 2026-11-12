"""Behaviour cloning on teacher shards (GPU when available). Resumable: rerun the command.

Loss = cross-entropy on the teacher's pick + value (return still to come, Huber) +
auxiliary P(win) / P(Michael win). Runs with ``i % 10 == 0`` are held out for validation.
New shards written by a running teacher job are picked up at every epoch.

    python -m cursed_words_solver.rl.bc --data ~/.cursed_words_solver/rl/teacher --dir ~/.cursed_words_solver/rl/bc
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
                                          upgrade_optimizer_state)


def run_index(path: Path) -> int:
    return int(path.name.split("_", 1)[0])


class Dataset:
    """Episodes kept compressed-ish (float16 arrays) in memory; steps unpacked per batch."""

    def __init__(self, data_dir: Path) -> None:
        self.dir = Path(data_dir) / "shards"
        self.eps: dict[str, dict] = {}
        self.train: list[tuple[str, int]] = []
        self.val: list[tuple[str, int]] = []

    def refresh(self) -> int:
        added = 0
        for p in sorted(self.dir.glob("*.npz")):
            if "_c8_" in p.name:   # crown 8 is not playable (old teacher runs)
                continue
            if p.name in self.eps:
                continue
            try:
                ep = store.load_episode(p)
            except Exception:
                continue  # being written
            rew = ep["reward"].astype(np.float64)
            ep["rtg"] = np.cumsum(rew[::-1])[::-1].astype(np.float32)
            self.eps[p.name] = ep
            target = self.val if run_index(p) % 10 == 0 else self.train
            n_act = np.diff(ep["act_off"])
            for i in range(len(ep["chosen"])):
                if n_act[i] > 1 or target is self.val:
                    target.append((p.name, i))
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
        return s


def make_batch(ds: Dataset, keys, device):
    items = [ds.item(k) for k in keys]
    b = collate(items, device)
    b["chosen"] = torch.tensor([it["chosen"] for it in items], device=device)
    b["rtg"] = torch.tensor([it["rtg"] for it in items], device=device)
    b["won"] = torch.tensor([it["won"] for it in items], device=device)
    b["michael"] = torch.tensor([it["michael"] for it in items], device=device)
    b["n_act"] = torch.tensor([len(it["act_type"]) for it in items], device=device)
    return b


VALUE_SCALE = 8.0


def losses(model: Policy, b: dict, *, w_value: float = 0.5, w_aux: float = 0.2) -> tuple[torch.Tensor, dict]:
    out = model(b)
    ce = F.cross_entropy(out["logits"], b["chosen"])
    v = F.smooth_l1_loss(out["value"], b["rtg"] / VALUE_SCALE)
    aux = F.binary_cross_entropy_with_logits(out["aux"], torch.stack([b["won"], b["michael"]], -1))
    acc = (out["logits"].argmax(-1) == b["chosen"]).float().mean()
    return ce + w_value * v + w_aux * aux, {"ce": ce.item(), "v": v.item(), "aux": aux.item(), "acc": acc.item()}


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
def validate(model: Policy, ds: Dataset, device, bs: int = 1024, limit: int = 40000) -> dict:
    model.eval()
    keys = ds.val[:limit]
    tot: dict[str, float] = {}
    n = 0
    by_kind: dict[int, list[float]] = {}
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
        chosen_type = torch.gather(b["act_type"], 1, b["chosen"].unsqueeze(1)).squeeze(1)
        for t, r, m in zip(chosen_type.tolist(), right.tolist(), multi.tolist()):
            if m:
                by_kind.setdefault(t, []).append(r)
        n += k
    model.train()
    from cursed_words_solver.rl.actions import ACTION_TYPES

    res = {k: v / max(1, n) for k, v in tot.items()}
    res["by_kind"] = {ACTION_TYPES[t]: (round(float(np.mean(v)), 3), len(v)) for t, v in sorted(by_kind.items())}
    return res


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=str(store.RL_HOME / "teacher"))
    ap.add_argument("--dir", default=str(store.RL_HOME / "bc"))
    ap.add_argument("--epochs", type=int, default=30, help="total epochs (absolute)")
    ap.add_argument("--steps", type=int, default=1500, help="batches per epoch")
    ap.add_argument("--bs", type=int, default=512)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--d", type=int, default=128)
    ap.add_argument("--layers", type=int, default=3)
    args = ap.parse_args(argv)
    out = Path(args.dir).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    (out / "command.txt").write_text(f"python -m cursed_words_solver.rl.bc --data {args.data} --dir {out} --epochs {args.epochs}\n")
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    ds = Dataset(Path(args.data).expanduser())
    ck_path = out / "last.pt"
    if ck_path.is_file():
        ck = torch.load(ck_path, map_location="cpu", weights_only=False)
        model = Policy(ModelConfig(**ck["config"])).to(device)
        model.load_state_dict(ck["state"])
        opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
        opt.load_state_dict(upgrade_optimizer_state(ck["opt"], model))   # v1 widths -> current
        epoch, best = ck["epoch"], ck.get("best", math.inf)
        start_step, best_val_n = ck.get("step", 0), ck.get("best_val_n", -1)
        random.setstate(ck["py_rng"])
        torch.set_rng_state(ck["torch_rng"])
        print(f"resumed at epoch {epoch}", flush=True)
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
            loss, st = losses(model, b)
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
            val = validate(model, ds, device)
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
