"""Behaviour-cloning data: the current best AI (rules + build plan + champion override)
plays runs; every decision is stored as (observation, candidates, teacher's pick, reward).

Resumable: one shard per run in ``<dir>/shards``; rerunning the command skips finished runs.
``STOP`` file in the dir = stop soon (runs in flight are redone on the next start).

    python -m cursed_words_solver.rl.teacher --dir ~/.cursed_words_solver/rl/teacher --runs 4000 --workers 7
"""

from __future__ import annotations

import argparse
import os
import random
import time
import traceback
from pathlib import Path
from typing import Any

import numpy as np

from cursed_words_solver.rl import store

CHARS = ("BonesTheDog", "HayleyBayles", "NathaServo", "NinaNix", "Octacles", "PrismaticBean", "SamGambit",
         "SandySaguaro", "SockHead", "Spike", "WetDennis")
FIRST_SEED = 30_000_000


def jobs(n: int, quest_share: float = 0.1, crowns: tuple[int, ...] = tuple(range(9))) -> list[dict[str, Any]]:
    """Deterministic job list (prefix-stable: more runs = same first ones)."""
    from cursed_words_solver.sim.game.challenges import QUESTS

    quests = sorted(QUESTS)
    out = []
    for i in range(n):
        r = random.Random(FIRST_SEED + i)
        ch = CHARS[i % len(CHARS)]
        if r.random() < quest_share:
            q, cr = quests[r.randrange(len(quests))], 0
        else:
            q, cr = None, crowns[(i // len(CHARS)) % len(crowns)]
        out.append({"i": i, "character": ch, "crown": cr, "quest": q, "seed": FIRST_SEED + i})
    return out


def shard_name(j: dict) -> str:
    return f"{j['i']:06d}_{j['character']}_c{j['crown']}_{j['quest'] or 'none'}_{j['seed']}.npz"


_CANDS = None
_TEACHER_MODEL = None


def _init_worker(effort: float, cheap: bool) -> None:
    global _CANDS, _TEACHER_MODEL
    os.environ.setdefault("PYTHONHASHSEED", "0")
    from cursed_words_solver.sim.game.agent import Candidates

    _CANDS = Candidates(effort=effort, cheap_floor=cheap)
    try:
        from cursed_words_solver.sim.game.advise import champion_path
        from cursed_words_solver.sim.game.learn import load_model

        p = champion_path()
        _TEACHER_MODEL = load_model(p) if p else None
    except Exception:
        _TEACHER_MODEL = None


def teacher_policy(cands, seed: int):
    from cursed_words_solver.sim.game.bossrisk import DEFAULT_PATH
    from cursed_words_solver.sim.game.expert import NetPolicy

    return NetPolicy(cands, _TEACHER_MODEL, seed=seed, boss_risk=str(DEFAULT_PATH) if DEFAULT_PATH.is_file() else "")


def play_teacher(j: dict, out_dir: str) -> dict:
    from cursed_words_solver.rl.actions import cand_for, same_action
    from cursed_words_solver.rl.env import CWEnv, pack

    t0 = time.time()
    path = Path(out_dir) / "shards" / shard_name(j)
    env = CWEnv(_CANDS)
    try:
        env.reset(character=j["character"], crown=j["crown"], seed=j["seed"], quest=j["quest"])
        pol = teacher_policy(_CANDS, j["seed"])
        steps, chosen, rewards, phases, added = [], [], [], [], 0
        g = env.game
        while not env.done:
            a = pol.act(g)
            st = env.current()
            idx = next((i for i, c in enumerate(st.cands) if same_action(c.action, a)), -1)
            if idx < 0:
                c = cand_for(env.builder, g, a)
                if c is not None:
                    st.cands.append(c)
                    idx = len(st.cands) - 1
                    added += 1
            ph = g.phase
            r, _ = env.step(a)
            if idx < 0:  # an action outside the vocabulary (e.g. Twinkle Toes swap): play it, don't record
                if rewards:
                    rewards[-1] += r
                continue
            steps.append(pack(st))
            chosen.append(idx)
            rewards.append(r)
            phases.append(ph)
        res = env.result()
        if steps:
            extra = {"chosen": np.asarray(chosen, np.int16), "reward": np.asarray(rewards, np.float32),
                     "outcome": np.float32(res["outcome"]), "won": np.int8(res["won"]),
                     "michael": np.int8(res["michael"])}
            store.atomic_write_bytes(path, store.pack_episode(steps, extra))
        return {**j, **res, "decisions": len(steps), "added": added, "secs": round(time.time() - t0, 1), "error": ""}
    except Exception as exc:
        return {**j, "error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc()[-1500:],
                "secs": round(time.time() - t0, 1)}


def _job(args):
    j, out_dir = args
    return play_teacher(j, out_dir)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=str(store.RL_HOME / "teacher"))
    ap.add_argument("--runs", type=int, default=4000, help="total runs wanted (absolute, not 'more')")
    ap.add_argument("--workers", type=int, default=7)
    ap.add_argument("--effort", type=float, default=0.05)
    ap.add_argument("--quest-share", type=float, default=0.1)
    args = ap.parse_args(argv)
    out = Path(args.dir).expanduser()
    (out / "shards").mkdir(parents=True, exist_ok=True)
    store.atomic_write_json(out / "config.json", {"runs": args.runs, "effort": args.effort, "quest_share": args.quest_share,
                                                  "code": store.code_fingerprint()})
    (out / "command.txt").write_text(
        f"python -m cursed_words_solver.rl.teacher --dir {out} --runs {args.runs} --workers {args.workers}\n")
    done = {p.name for p in (out / "shards").glob("*.npz")}
    failed = {r["i"] for r in store.read_jsonl(out / "runs.jsonl") if r.get("error")}
    todo = [j for j in jobs(args.runs, args.quest_share) if shard_name(j) not in done and j["i"] not in failed]
    print(f"{len(done)} done, {len(todo)} to go", flush=True)
    if not todo:
        return
    from cursed_words_solver.sim.game.agent import spawn_pool

    pool = spawn_pool(args.workers, _init_worker, (args.effort, True))
    t0, n = time.time(), 0
    try:
        for r in pool.imap_unordered(_job, [(j, str(out)) for j in todo]):
            store.append_jsonl(out / "runs.jsonl", r)
            n += 1
            if n % 10 == 0 or r.get("error"):
                rate = n / max(1e-9, time.time() - t0) * 3600
                print(f"{n}/{len(todo)} {rate:.0f} runs/h last={r.get('character')} c{r.get('crown')} "
                      f"won={r.get('won')} out={r.get('outcome')} err={r.get('error', '')[:80]}", flush=True)
            if store.stop_requested(out):
                print("STOP file found: stopping", flush=True)
                break
    finally:
        pool.terminate()


if __name__ == "__main__":
    main()
