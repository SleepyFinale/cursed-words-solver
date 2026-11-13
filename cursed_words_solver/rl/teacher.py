"""Behaviour-cloning data: the current best AI (rules + build plan + champion override)
plays runs; every decision is stored as (observation, candidates, teacher's pick, reward).

Resumable: one shard per run in ``<dir>/shards``; rerunning the command skips finished runs.
``STOP`` file in the dir = stop soon (runs in flight are redone on the next start).

    python -m cursed_words_solver.rl.teacher --dir ~/.cursed_words_solver/rl/teacher --runs 4000 --workers 7

Themed mode (build-conditioned RL): ``--themed`` (alias ``--targets``) writes to a NEW directory
(default ``~/.cursed_words_solver/rl/teacher_themed``). Each job gets a target build sampled with
``targets.sample_target`` (``--mix`` = free,theme,any shares; default 0,0.5,0.5) and the teacher is
the rules player on that plan (``targets.teacher_plan``: a quest plan overrides it). The EFFECTIVE
plan is the episode's target: it goes into the observations (``target:*`` / ``pc:*`` columns),
into the shard name (``..._<plan with + as ->.npz``, "free" for FREE) and the shard's ``target``.
Seeds start at ``FIRST_SEED2``; crowns 0-7 only.

    python -m cursed_words_solver.rl.teacher --themed --runs 4000 --workers 7

Shard fields (both modes): per-step ``chosen`` / ``reward``; per-episode ``outcome`` / ``won`` /
``michael`` / ``obs_version`` (int16). Themed shards also carry ``target`` and ``target_req``
(effective and sampled target) as 0-d ``np.bytes_`` strings in canonical "A+B" form, "" for
FREE; read them with ``shard_target(ep)``.
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
FIRST_SEED2 = 31_000_000          # themed (target-build) jobs
THEMED_CROWNS = tuple(range(8))   # crowns 0-7 (8 is not playable)
THEMED_MIX = (0.0, 0.5, 0.5)      # targets.sample_target shares: free, character theme, any plan


def jobs(n: int, quest_share: float = 0.1, crowns: tuple[int, ...] | None = None, *, themed: bool = False,
         mix: tuple[float, float, float] = THEMED_MIX) -> list[dict[str, Any]]:
    """Deterministic job list (prefix-stable: more runs = same first ones). The default keeps
    crowns 0-8 only so job i still names the shard on disk; bc.py skips the crown-8 shards.

    ``themed``: seeds from ``FIRST_SEED2``, crowns 0-7, and a target per job drawn from the same
    per-job rng AFTER the quest / crown draws (``target_req``: sampled; ``target``: the plan the
    teacher actually plays, ``targets.teacher_plan``)."""
    from cursed_words_solver.rl import targets
    from cursed_words_solver.sim.game.challenges import QUESTS

    if crowns is None:
        crowns = THEMED_CROWNS if themed else tuple(range(9))
    first = FIRST_SEED2 if themed else FIRST_SEED
    quests = sorted(QUESTS)
    out = []
    for i in range(n):
        r = random.Random(first + i)
        ch = CHARS[i % len(CHARS)]
        if r.random() < quest_share:
            q, cr = quests[r.randrange(len(quests))], 0
        else:
            q, cr = None, crowns[(i // len(CHARS)) % len(crowns)]
        j: dict[str, Any] = {"i": i, "character": ch, "crown": cr, "quest": q, "seed": first + i}
        if themed:
            req = targets.sample_target(r, ch, mix=mix)
            j["target_req"] = req
            j["target"] = targets.teacher_plan(req, ch, q)
        out.append(j)
    return out


def shard_name(j: dict) -> str:
    base = f"{j['i']:06d}_{j['character']}_c{j['crown']}_{j['quest'] or 'none'}_{j['seed']}"
    if "target" in j:   # themed job
        from cursed_words_solver.rl.targets import file_tag

        base += f"_{file_tag(j['target'])}"
    return base + ".npz"


def shard_target(ep: dict) -> str:
    """The target build stored in a loaded shard ("" = FREE, also for pre-target shards)."""
    t = ep.get("target")
    if t is None:
        return ""
    v = np.asarray(t).item()
    return v.decode() if isinstance(v, bytes) else str(v)


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


def teacher_policy(cands, seed: int, build_plan: str | None = None, build_plan_chars: dict | None = None):
    """The teacher. ``build_plan`` None = today's default plans; a string (themed jobs: the
    effective target, "" = plain rules player) with ``build_plan_chars={}`` plays that plan."""
    from cursed_words_solver.sim.game.bossrisk import DEFAULT_PATH
    from cursed_words_solver.sim.game.expert import NetPolicy

    return NetPolicy(cands, _TEACHER_MODEL, seed=seed, boss_risk=str(DEFAULT_PATH) if DEFAULT_PATH.is_file() else "",
                     build_plan=build_plan, build_plan_chars=build_plan_chars)


def job_policy(cands, j: dict):
    """Teacher policy for a job: themed jobs (``target`` key) play their effective target."""
    if "target" in j:
        return teacher_policy(cands, j["seed"], build_plan=j["target"] or "", build_plan_chars={})
    return teacher_policy(cands, j["seed"])


def play_teacher(j: dict, out_dir: str) -> dict:
    from cursed_words_solver.rl.actions import cand_for, same_action
    from cursed_words_solver.rl.env import CWEnv, pack
    from cursed_words_solver.rl.obs import OBS_VERSION

    t0 = time.time()
    path = Path(out_dir) / "shards" / shard_name(j)
    env = CWEnv(_CANDS)
    try:
        env.reset(character=j["character"], crown=j["crown"], seed=j["seed"], quest=j["quest"],
                  target=j.get("target", ""))
        pol = job_policy(_CANDS, j)
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
                     "michael": np.int8(res["michael"]), "obs_version": np.int16(OBS_VERSION)}
            if "target" in j:
                extra["target"] = np.bytes_(j["target"].encode())
                extra["target_req"] = np.bytes_(j.get("target_req", "").encode())
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
    ap.add_argument("--dir", default=None, help="default: <rl home>/teacher, or teacher_themed with --themed")
    ap.add_argument("--runs", type=int, default=4000, help="total runs wanted (absolute, not 'more')")
    ap.add_argument("--workers", type=int, default=7)
    ap.add_argument("--effort", type=float, default=0.05)
    ap.add_argument("--quest-share", type=float, default=0.1)
    ap.add_argument("--themed", "--targets", dest="themed", action="store_true",
                    help="target-build jobs (new seeds, crowns 0-7, a target per run) in a new directory")
    ap.add_argument("--mix", default=",".join(str(x) for x in THEMED_MIX),
                    help="themed target shares free,theme,any (default %(default)s)")
    args = ap.parse_args(argv)
    mix = tuple(float(x) for x in args.mix.split(","))
    if len(mix) != 3:
        ap.error("--mix needs three numbers: free,theme,any")
    out = Path(args.dir or str(store.RL_HOME / ("teacher_themed" if args.themed else "teacher"))).expanduser()
    (out / "shards").mkdir(parents=True, exist_ok=True)
    conf = {"runs": args.runs, "effort": args.effort, "quest_share": args.quest_share,
            "code": store.code_fingerprint(), "mode": "themed" if args.themed else "plain"}
    if args.themed:
        from cursed_words_solver.rl.obs import OBS_VERSION

        conf.update(mix=list(mix), first_seed=FIRST_SEED2, crowns=list(THEMED_CROWNS), obs_version=OBS_VERSION)
    store.atomic_write_json(out / "config.json", conf)
    (out / "command.txt").write_text(
        f"python -m cursed_words_solver.rl.teacher --dir {out} --runs {args.runs} --workers {args.workers}"
        + (f" --themed --mix {args.mix} --quest-share {args.quest_share}" if args.themed else "") + "\n")
    done = {p.name for p in (out / "shards").glob("*.npz")}
    failed = {r["i"] for r in store.read_jsonl(out / "runs.jsonl") if r.get("error")}
    all_jobs = jobs(args.runs, args.quest_share, themed=True, mix=mix) if args.themed else jobs(args.runs, args.quest_share)
    todo = [j for j in all_jobs if shard_name(j) not in done and j["i"] not in failed]
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
