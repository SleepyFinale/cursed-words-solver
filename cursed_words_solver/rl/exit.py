"""Expert iteration: the look-ahead (rl.search) plays training seeds with the latest PPO
weights and saves every searched decision with the look-ahead's pick. PPO distils these
(``--distill-dir``), so the network learns what the search finds and the next search
starts from a stronger policy.

    python -m cursed_words_solver.rl.exit --dir ~/.cursed_words_solver/rl/exit --policy ~/.cursed_words_solver/rl/ppo1/weights.pt

Resumable: ``state.json`` counts started runs; a run in flight at a kill is replayed with a
new seed. ``STOP`` file in the dir = finish nothing more and exit. Output: ``shards/*.npz``
(env.pack steps + ``chosen`` = look-ahead pick, ``margin``, ``changed``, ``obs_version``) and
``runs.jsonl``. With a halving search (``--search '{"mode": "halving"}'``) shards also hold
soft targets ``q_idx`` / ``q_val`` / ``q_n`` / ``q_se`` (see ``soft_targets``; PPO ``--distill-soft``).
Jobs follow PPO's curriculum (``--curriculum``, ppo1/curriculum.json, re-read as it changes): the same character / quest weights, so the labels cover the slices PPO is weak on.
Build targets: ``--targets-mix`` (as rl.ppo; default: the ``targets_mix`` PPO writes to its
curriculum.json, none = FREE) gives runs a target build, which the shards' obs carry
(``obs_version`` 3). A second collector runs beside a second PPO with its own ``--dir`` (exit2).
"""

from __future__ import annotations

import argparse
import json
import random
import time
from collections import deque
from pathlib import Path

import numpy as np

from cursed_words_solver.rl import store

EXIT_SEED0 = 60_000_000
SEARCH = {"top": 3, "sims": 4, "horizon": 2.0}   # deep look-ahead: +6.4% wins on fresh seeds (2026-11-11)


def soft_targets(tr: dict) -> dict[str, np.ndarray]:
    """Halving-mode search (``"mode": "halving"``): per-decision soft targets, (decisions, k)
    arrays ``q_idx`` (searched candidate indices, -1 = pad), ``q_val`` (mean Q), ``q_n``
    (futures) and ``q_se`` (paired SE vs the policy argmax). Empty for top-k search, and only
    when every decision of the run has a row (so rows line up with ``chosen``)."""
    rows = tr.get("search_q_idx")
    if not rows or len(rows) != len(tr.get("search_steps") or []):
        return {}
    w = max(len(r) for r in rows)

    def pad(xs, fill, dt):
        return np.stack([np.pad(np.asarray(x, dt), (0, w - len(x)), constant_values=fill) for x in xs]).astype(dt)

    return {"q_idx": pad(rows, -1, np.int16), "q_val": pad(tr["search_q_val"], 0, np.float32),
            "q_n": pad(tr["search_q_n"], 0, np.int16), "q_se": pad(tr["search_q_se"], 0, np.float32)}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=str(store.RL_HOME / "exit"))
    ap.add_argument("--policy", default=str(store.RL_HOME / "ppo1" / "weights.pt"))
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--runs", type=int, default=10**9)
    ap.add_argument("--search", default=json.dumps(SEARCH), help="JSON SearchConfig")
    ap.add_argument("--quest-share", type=float, default=0.25)
    ap.add_argument("--crown-weights", default="1,1,1,1,1,1,1,1")   # crowns 0-7
    ap.add_argument("--curriculum", default="", help="PPO curriculum.json (default: next to --policy; '-' = off)")
    ap.add_argument("--targets-mix", default="", metavar="P_FREE,P_THEME,P_ANY",
                    help="build targets of non-quest runs (rl.ppo); default: PPO's curriculum.json targets_mix, else FREE")
    args = ap.parse_args(argv)
    out = Path(args.dir).expanduser()
    (out / "shards").mkdir(parents=True, exist_ok=True)
    st_path = out / "state.json"
    state = json.loads(st_path.read_text()) if st_path.is_file() else {"started": 0, "saved": 0}
    search = json.loads(args.search)
    policy = str(Path(args.policy).expanduser())
    curr_path = None if args.curriculum == "-" else Path(args.curriculum or Path(policy).parent / "curriculum.json").expanduser()
    curr = {"mtime": None, "char": None, "quest": None, "mix": None}

    def weights() -> tuple[dict | None, dict | None]:
        """Character / quest weights from PPO's curriculum.json (cached by mtime; missing = uniform)."""
        try:
            mt = curr_path.stat().st_mtime if curr_path is not None else None
            if mt is not None and mt != curr["mtime"]:
                c = json.loads(curr_path.read_text())
                on = c.get("enabled", True)
                mix = c.get("targets_mix")
                curr.update(mtime=mt, char=c.get("char") if on else None, quest=c.get("quest") if on else None,
                            mix=tuple(float(x) for x in mix) if mix else None)
        except (OSError, ValueError):
            pass   # being replaced: keep the last weights
        return curr["char"], curr["quest"]

    from cursed_words_solver.rl.obs import OBS_VERSION
    from cursed_words_solver.rl.play import init_worker, play
    from cursed_words_solver.rl.ppo import parse_mix, sample_job

    own_mix = parse_mix(args.targets_mix)
    from cursed_words_solver.sim.game.agent import spawn_pool

    # a fresh pipeline starts this before PPO has written its first weights
    while not Path(policy).is_file():
        if store.stop_requested(out):
            return
        time.sleep(2)
    pool = spawn_pool(args.workers, init_worker, ())
    in_flight: deque = deque()

    def submit() -> None:
        if store.stop_requested(out) or state["started"] >= args.runs:
            return
        n = state["started"]
        rng = random.Random(n * 104729 + 7)
        cw, qw = weights()
        j = sample_job(rng, n, args.quest_share, [float(x) for x in args.crown_weights.split(",")], cw, qw,
                       own_mix or curr["mix"])
        j["seed"] = EXIT_SEED0 + n
        state["started"] += 1
        store.atomic_write_json(st_path, state)
        in_flight.append(pool.apply_async(play, ({**j, "policy": policy, "greedy": True, "search": search,
                                                   "record_search": True},)))

    try:
        for _ in range(args.workers * 2):
            submit()
        t0, done = time.time(), 0
        while in_flight:
            ready = [a for a in in_flight if a.ready()]
            if not ready:
                time.sleep(0.2)
                continue
            for a in ready:
                in_flight.remove(a)
                res = a.get()
                tr = res.pop("traj", {}) or {}
                if not res.get("error") and tr.get("search_steps"):
                    data = store.pack_episode(tr["search_steps"], {
                        "chosen": np.asarray(tr["search_pick"], np.int16),
                        "margin": np.asarray(tr["search_margin"], np.float32),
                        "changed": np.asarray(tr["search_changed"], np.bool_),
                        "obs_version": np.asarray([OBS_VERSION], np.int16), **soft_targets(tr)})
                    store.atomic_write_bytes(out / "shards" / f"{res['seed']}.npz", data)
                    state["saved"] += 1
                    store.atomic_write_json(st_path, state)
                elif res.get("error"):
                    print("ERROR", res["error"], res.get("trace", "")[-300:], flush=True)
                    time.sleep(5)   # don't spin through seeds on a persistent failure
                res["n_search"] = len(tr.get("search_steps") or [])
                store.append_jsonl(out / "runs.jsonl", res)
                done += 1
                if done % 10 == 0:
                    rows = [r for r in store.read_jsonl(out / "runs.jsonl")[-200:] if not r.get("error") and r.get("crown", 0) <= 7]
                    win = np.mean([bool(r["won"]) for r in rows]) if rows else float("nan")
                    print(f"[exit] {state['saved']} shards, {done / (time.time() - t0) * 3600:.0f} runs/h, "
                          f"recent win {win:.3f}", flush=True)
                submit()
    finally:
        pool.terminate()


if __name__ == "__main__":
    main()
