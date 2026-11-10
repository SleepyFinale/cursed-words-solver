"""Expert iteration: the look-ahead (rl.search) plays training seeds with the latest PPO
weights and saves every searched decision with the look-ahead's pick. PPO distils these
(``--distill-dir``), so the network learns what the search finds and the next search
starts from a stronger policy.

    python -m cursed_words_solver.rl.exit --dir ~/.cursed_words_solver/rl/exit --policy ~/.cursed_words_solver/rl/ppo1/weights.pt

Resumable: ``state.json`` counts started runs; a run in flight at a kill is replayed with a
new seed. ``STOP`` file in the dir = finish nothing more and exit. Output: ``shards/*.npz``
(env.pack steps + ``chosen`` = look-ahead pick, ``margin``, ``changed``) and ``runs.jsonl``.
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
SEARCH = {"top": 2, "sims": 2, "horizon": 1.0}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=str(store.RL_HOME / "exit"))
    ap.add_argument("--policy", default=str(store.RL_HOME / "ppo1" / "weights.pt"))
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--runs", type=int, default=10**9)
    ap.add_argument("--search", default=json.dumps(SEARCH), help="JSON SearchConfig")
    ap.add_argument("--quest-share", type=float, default=0.1)
    ap.add_argument("--crown-weights", default="1,1,1,1,1,1,1,1,1")
    args = ap.parse_args(argv)
    out = Path(args.dir).expanduser()
    (out / "shards").mkdir(parents=True, exist_ok=True)
    st_path = out / "state.json"
    state = json.loads(st_path.read_text()) if st_path.is_file() else {"started": 0, "saved": 0}
    search = json.loads(args.search)
    policy = str(Path(args.policy).expanduser())

    from cursed_words_solver.rl.play import init_worker, play
    from cursed_words_solver.rl.ppo import sample_job
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
        j = sample_job(rng, n, args.quest_share, [float(x) for x in args.crown_weights.split(",")])
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
                        "changed": np.asarray(tr["search_changed"], np.bool_)})
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
                    rows = [r for r in store.read_jsonl(out / "runs.jsonl")[-200:] if not r.get("error")]
                    win = np.mean([bool(r["won"]) for r in rows]) if rows else float("nan")
                    print(f"[exit] {state['saved']} shards, {done / (time.time() - t0) * 3600:.0f} runs/h, "
                          f"recent win {win:.3f}", flush=True)
                submit()
    finally:
        pool.terminate()


if __name__ == "__main__":
    main()
