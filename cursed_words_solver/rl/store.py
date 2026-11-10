"""Crash-safe files for long jobs: atomic writes, per-episode shards, a STOP file.

Pause / resume rule for every job in ``cursed_words_solver.rl``: rerunning the same command
continues where it stopped. Episodes are written one shard per episode (a kill loses at most
the episodes in flight), checkpoints are written atomically (tmp + fsync + ``os.replace``,
retried on Windows sharing violations), and a ``STOP`` file in the job dir ends the job at
the next safe point.
"""

from __future__ import annotations

import io
import json
import os
import time
from pathlib import Path
from typing import Any, Iterable

import numpy as np

RL_HOME = Path.home() / ".cursed_words_solver" / "rl"

# per-decision arrays and how they are concatenated in a shard
FIXED = ("glob",)                                  # (N, G)
TOKENS = ("tok_type", "tok_cls", "tok_feat")       # concatenated over decisions, offsets tok_off
ACTIONS = ("act_type", "act_ref1", "act_ref2", "act_feat")  # offsets act_off
F16 = ("glob", "tok_feat", "act_feat")


def atomic_write_bytes(path: Path, data: bytes, retries: int = 20) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp{os.getpid()}")
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    for i in range(retries):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:  # reader / antivirus holds the target on Windows
            time.sleep(0.05 * (i + 1))
    os.replace(tmp, path)


def atomic_write_json(path: Path, obj: Any) -> None:
    atomic_write_bytes(path, json.dumps(obj, indent=1, sort_keys=True).encode())


def append_jsonl(path: Path, row: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
        f.flush()
        os.fsync(f.fileno())


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    p = Path(path)
    if p.is_file():
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # a line cut short by a kill
    return rows


def stop_requested(job_dir: Path) -> bool:
    return (Path(job_dir) / "STOP").exists()


def pack_episode(steps: Iterable[dict[str, np.ndarray]], extra: dict[str, np.ndarray]) -> bytes:
    """Concatenate per-decision dicts (``env.pack`` + per-step scalars in ``extra``)."""
    steps = list(steps)
    out: dict[str, np.ndarray] = {}
    out["glob"] = np.stack([s["glob"] for s in steps]).astype(np.float16)
    tl = [len(s["tok_type"]) for s in steps]
    al = [len(s["act_type"]) for s in steps]
    out["tok_off"] = np.concatenate([[0], np.cumsum(tl)]).astype(np.int64)
    out["act_off"] = np.concatenate([[0], np.cumsum(al)]).astype(np.int64)
    F = steps[0]["tok_feat"].shape[1] if steps else 0
    for k in TOKENS:
        parts = [s[k] for s in steps]
        if k == "tok_feat":
            parts = [p if len(p) else np.zeros((0, F), np.float32) for p in parts]
        arr = np.concatenate(parts) if parts else np.zeros(0)
        out[k] = arr.astype(np.float16) if k in F16 else arr.astype(np.int16)
    for k in ACTIONS:
        arr = np.concatenate([s[k] for s in steps])
        out[k] = arr.astype(np.float16) if k in F16 else arr.astype(np.int16)
    for k, v in extra.items():
        out[k] = np.asarray(v)
    buf = io.BytesIO()
    np.savez_compressed(buf, **out)
    return buf.getvalue()


def load_episode(path: Path) -> dict[str, np.ndarray]:
    with np.load(path) as z:
        return {k: z[k] for k in z.files}


def unpack_step(ep: dict[str, np.ndarray], i: int) -> dict[str, np.ndarray]:
    t0, t1 = ep["tok_off"][i], ep["tok_off"][i + 1]
    a0, a1 = ep["act_off"][i], ep["act_off"][i + 1]
    return {"glob": ep["glob"][i].astype(np.float32),
            "tok_type": ep["tok_type"][t0:t1].astype(np.int64), "tok_cls": ep["tok_cls"][t0:t1].astype(np.int64),
            "tok_feat": ep["tok_feat"][t0:t1].astype(np.float32),
            "act_type": ep["act_type"][a0:a1].astype(np.int64), "act_ref1": ep["act_ref1"][a0:a1].astype(np.int64),
            "act_ref2": ep["act_ref2"][a0:a1].astype(np.int64), "act_feat": ep["act_feat"][a0:a1].astype(np.float32)}


def code_fingerprint() -> str:
    """Hash of the rl + sim game sources (a job warns when the code changed under it)."""
    import hashlib

    h = hashlib.sha1()
    root = Path(__file__).resolve().parent
    for d in (root, root.parent / "sim" / "game"):
        for f in sorted(d.glob("*.py")):
            h.update(f.name.encode())
            h.update(f.read_bytes())
    return h.hexdigest()[:10]
