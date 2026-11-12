"""The whole training pipeline as one resumable command.

    python -m cursed_words_solver.rl.pipeline            # start or resume
    python -m cursed_words_solver.rl.pipeline --status   # where it is
    (create ~/.cursed_words_solver/rl/STOP to pause; delete it and rerun to resume)

Stages (each skipped when its output is complete; each stage is itself resumable):

1. ``teacher``  — behaviour-cloning data from the current best AI (``--teacher-runs``)
2. ``bc``       — behaviour cloning on the GPU (``--bc-epochs``)
3. ``baseline`` — the teacher on the PPO gate seeds (reference for every gate); only the gate
                  jobs missing from ppo1/eval/teacher.jsonl are played (e.g. after the gate grew)
4. ``ppo``      — self-improvement, forever (or ``--ppo-updates``); champion in rl/ppo1/champion.pt,
                  with the rl.exit look-ahead collector beside it (``--exit-workers``)

Gate = ``evaluate.gate_jobs(--gate-per, --gate-per-quest)``: 4 x 11 characters x 8 crowns + 2 x 26
quests = 404 runs (the old 202-run gate, per 2 / 1, is its prefix, so cached rows are reused).

Stages run as child processes; output goes to ``rl/pipeline.log`` and each stage's dir.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from cursed_words_solver.rl import store

HOME = store.RL_HOME


def _run(args: list[str], log: Path) -> int:
    with open(log, "a", encoding="utf-8") as f:
        f.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} {' '.join(args)}\n")
        f.flush()
        p = subprocess.Popen([sys.executable, "-u", "-m", *args], stdout=f, stderr=subprocess.STDOUT,
                             cwd=str(Path(__file__).resolve().parents[2]))
        try:
            while p.poll() is None:
                if (HOME / "STOP").exists():
                    # forward the pause to the stage (each stage checks its own STOP file)
                    for d in ("teacher", "bc", "ppo1", "exit"):
                        (HOME / d).mkdir(parents=True, exist_ok=True)
                        (HOME / d / "STOP").touch()
                time.sleep(2)
        except KeyboardInterrupt:
            p.terminate()
            raise
        return p.returncode


def _exit_status() -> dict:
    p = HOME / "exit" / "state.json"
    if not p.is_file():
        return {}
    rows = [r for r in store.read_jsonl(HOME / "exit" / "runs.jsonl")[-200:]
            if not r.get("error") and r.get("crown", 0) <= 7]
    st = json.loads(p.read_text())
    if rows:
        st["recent_win"] = round(sum(bool(r["won"]) for r in rows) / len(rows), 3)
        st["recent_n"] = len(rows)
    return st


def status(args) -> dict:
    t = HOME / "teacher" / "shards"
    shards = len(list(t.glob("*.npz"))) if t.is_dir() else 0
    bc_hist = store.read_jsonl(HOME / "bc" / "history.jsonl")
    base = [r for r in store.read_jsonl(HOME / "ppo1" / "eval" / "teacher.jsonl") if not r.get("error")]
    ppo_hist = store.read_jsonl(HOME / "ppo1" / "history.jsonl")
    gates = store.read_jsonl(HOME / "ppo1" / "gates.jsonl")
    from cursed_words_solver.rl.evaluate import gate_jobs, key, summarize

    gate_keys = {key(j) for j in gate_jobs(args.gate_per, args.gate_per_quest)}
    n_gate = len(gate_keys)
    gs = gates[-1] if gates else None
    # the gate row is written before a promotion, so the newer champion wins when it promoted
    cu = (gs["update"] if gs.get("promoted") else gs["champion_update"]) if gs else 0
    champ = [r for r in store.read_jsonl(HOME / "ppo1" / "eval" / f"champion_u{cu}.jsonl")
             if not r.get("error") and key(r) in gate_keys] if gs else []
    curr = HOME / "ppo1" / "curriculum.json"
    curr = json.loads(curr.read_text()) if curr.is_file() else {}
    base = [r for r in base if key(r) in gate_keys]
    out = {"teacher_shards": f"{shards}/{args.teacher_runs}",
           "bc_epochs": f"{len(bc_hist)}/{args.bc_epochs}",
           "bc_last": {k: v for k, v in (bc_hist[-1] if bc_hist else {}).items() if k.startswith("val_") and k != "val_by_kind"},
           "baseline": f"{len(base)}/{n_gate} {summarize(base) if base else ''}",
           "ppo_updates": len(ppo_hist),
           "ppo_last": {k: ppo_hist[-1].get(k) for k in ("update", "episodes", "recent_win", "recent_outcome", "eps_per_h",
                                                          "kl_coef", "kl_ref_src", "ent", "ent_coef", "distill_n",
                                                          "distill_changed", "approx_kl")} if ppo_hist else {},
           "gate_size": n_gate,
           "champion_gate_rows": f"{len(champ)}/{n_gate}" if gs else None,
           "last_gate": gates[-1] if gates else None,
           "curriculum": {k: curr.get(k) for k in ("update", "char", "quest", "n_char", "n_quest")} if curr else None,
           "exit": _exit_status(),
           "paused": (HOME / "STOP").exists()}
    return out


def _single_instance():
    """OS lock on rl/pipeline.lock for this process's lifetime (released when it dies), so a
    restart cannot run beside a pipeline still draining its stages and clear their STOP files."""
    f = open(HOME / "pipeline.lock", "a+")
    try:
        if os.name == "nt":
            import msvcrt

            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return None
    return f


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--teacher-runs", type=int, default=1500)
    ap.add_argument("--bc-epochs", type=int, default=30)
    ap.add_argument("--workers", type=int, default=7)
    ap.add_argument("--gate-per", type=int, default=4, help="PPO gate seeds per character x crown")
    ap.add_argument("--gate-per-quest", type=int, default=2, help="PPO gate seeds per quest")
    ap.add_argument("--eval-per", dest="gate_per", type=int, help=argparse.SUPPRESS)   # old name of --gate-per
    ap.add_argument("--ppo-updates", type=int, default=100000)
    ap.add_argument("--exit-workers", type=int, default=3, help="look-ahead collector workers beside PPO (0 = off)")
    # training effort goes where runs are still lost (training wins 50% at crown 0 incl. quests, 13% at 7);
    # crowns 0-7 only: 7 is the top playable crown
    ap.add_argument("--crown-weights", default="0.4,0.6,0.8,1,1.2,1.4,1.6,2.0")
    ap.add_argument("--quest-share", type=float, default=0.25)
    ap.add_argument("--episodes", type=int, default=112, help="PPO episodes per update")
    ap.add_argument("--distill-coef", type=float, default=0.15)
    ap.add_argument("--distill-same-w", type=float, default=0.1)
    ap.add_argument("--distill-cap", type=int, default=20000)
    ap.add_argument("--ent-target", type=float, default=0.2)
    ap.add_argument("--kl-ref", choices=("champion", "init"), default="champion")
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args(argv)
    HOME.mkdir(parents=True, exist_ok=True)
    if args.status:
        print(json.dumps(status(args), indent=1, default=str))
        return 0
    log = HOME / "pipeline.log"
    lock = _single_instance()
    if lock is None:
        print("another pipeline is still running (or still shutting down after STOP); try again when it exits",
              flush=True)
        return 1
    for d in ("teacher", "bc", "ppo1", "exit"):
        (HOME / d / "STOP").unlink(missing_ok=True)
    (HOME / "command.txt").write_text(f"python -m cursed_words_solver.rl.pipeline {' '.join(argv or sys.argv[1:])}\n")
    W = str(args.workers)
    shards = HOME / "teacher" / "shards"
    if not shards.is_dir() or len(list(shards.glob("*.npz"))) < args.teacher_runs:
        _run(["cursed_words_solver.rl.teacher", "--dir", str(HOME / "teacher"), "--runs", str(args.teacher_runs), "--workers", W], log)
    if (HOME / "STOP").exists():
        return 0
    if len(store.read_jsonl(HOME / "bc" / "history.jsonl")) < args.bc_epochs:
        _run(["cursed_words_solver.rl.bc", "--data", str(HOME / "teacher"), "--dir", str(HOME / "bc"), "--epochs", str(args.bc_epochs)], log)
    if (HOME / "STOP").exists():
        return 0
    # teacher baseline on the PPO gate seeds (same seed set the gate uses)
    from cursed_words_solver.rl.evaluate import gate_jobs, key

    have = {key(r) for r in store.read_jsonl(HOME / "ppo1" / "eval" / "teacher.jsonl") if not r.get("error")}
    if any(key(j) not in have for j in gate_jobs(args.gate_per, args.gate_per_quest)):
        code = ("from cursed_words_solver.rl.evaluate import gate_jobs, run_arm; from pathlib import Path; "
                f"run_arm('teacher', 'teacher', gate_jobs({args.gate_per}, {args.gate_per_quest}), {args.workers}, "
                f"out_dir=Path(r'{HOME / 'ppo1' / 'eval'}'))")
        with open(log, "a", encoding="utf-8") as f:
            f.write("\n=== teacher baseline\n")
        subprocess.call([sys.executable, "-u", "-c", code], stdout=open(log, "a"), stderr=subprocess.STDOUT,
                        cwd=str(Path(__file__).resolve().parents[2]))
    if (HOME / "STOP").exists():
        return 0
    # expert iteration beside PPO: the look-ahead plays with the latest weights, PPO distils its picks
    exit_proc = None
    if args.exit_workers > 0:
        (HOME / "ppo1").mkdir(parents=True, exist_ok=True)
        ex_log = open(HOME / "exit.log", "a", encoding="utf-8")
        exit_proc = subprocess.Popen(
            [sys.executable, "-u", "-m", "cursed_words_solver.rl.exit", "--dir", str(HOME / "exit"),
             "--policy", str(HOME / "ppo1" / "weights.pt"), "--workers", str(args.exit_workers),
             "--crown-weights", args.crown_weights, "--quest-share", str(args.quest_share),
             "--curriculum", str(HOME / "ppo1" / "curriculum.json")],
            stdout=ex_log, stderr=subprocess.STDOUT, cwd=str(Path(__file__).resolve().parents[2]))
    ppo_w = str(max(1, args.workers - args.exit_workers + 1)) if args.exit_workers else W
    try:
        _run(["cursed_words_solver.rl.ppo", "--dir", str(HOME / "ppo1"), "--init", str(HOME / "bc" / "best.pt"),
              "--workers", ppo_w, "--updates", str(args.ppo_updates),
              "--gate-per", str(args.gate_per), "--gate-per-quest", str(args.gate_per_quest),
              "--crown-weights", args.crown_weights, "--quest-share", str(args.quest_share),
              "--episodes", str(args.episodes), "--ent-target", str(args.ent_target), "--kl-ref", args.kl_ref,
              "--distill-coef", str(args.distill_coef), "--distill-same-w", str(args.distill_same_w),
              "--distill-cap", str(args.distill_cap),
              *(["--distill-dir", str(HOME / "exit")] if args.exit_workers else [])], log)
    finally:
        if exit_proc is not None:
            (HOME / "exit").mkdir(parents=True, exist_ok=True)
            (HOME / "exit" / "STOP").touch()
            try:
                exit_proc.wait(timeout=600)
            except subprocess.TimeoutExpired:
                exit_proc.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
