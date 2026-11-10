"""The whole training pipeline as one resumable command.

    python -m cursed_words_solver.rl.pipeline            # start or resume
    python -m cursed_words_solver.rl.pipeline --status   # where it is
    (create ~/.cursed_words_solver/rl/STOP to pause; delete it and rerun to resume)

Stages (each skipped when its output is complete; each stage is itself resumable):

1. ``teacher``  — behaviour-cloning data from the current best AI (``--teacher-runs``)
2. ``bc``       — behaviour cloning on the GPU (``--bc-epochs``)
3. ``baseline`` — the teacher on the PPO gate seeds (reference for every gate)
4. ``ppo``      — self-improvement, forever (or ``--ppo-updates``); champion in rl/ppo1/champion.pt

Stages run as child processes; output goes to ``rl/pipeline.log`` and each stage's dir.
"""

from __future__ import annotations

import argparse
import json
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
    rows = [r for r in store.read_jsonl(HOME / "exit" / "runs.jsonl")[-200:] if not r.get("error")]
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
    from cursed_words_solver.rl.evaluate import eval_jobs, summarize

    n_gate = len(eval_jobs(per=args.eval_per, per_quest=1, block=1))
    out = {"teacher_shards": f"{shards}/{args.teacher_runs}",
           "bc_epochs": f"{len(bc_hist)}/{args.bc_epochs}",
           "bc_last": {k: v for k, v in (bc_hist[-1] if bc_hist else {}).items() if k.startswith("val_") and k != "val_by_kind"},
           "baseline": f"{len(base)}/{n_gate} {summarize(base) if base else ''}",
           "ppo_updates": len(ppo_hist),
           "ppo_last": {k: ppo_hist[-1].get(k) for k in ("update", "episodes", "recent_win", "recent_outcome", "eps_per_h", "kl_coef")} if ppo_hist else {},
           "last_gate": gates[-1] if gates else None,
           "exit": _exit_status(),
           "paused": (HOME / "STOP").exists()}
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--teacher-runs", type=int, default=1500)
    ap.add_argument("--bc-epochs", type=int, default=30)
    ap.add_argument("--workers", type=int, default=7)
    ap.add_argument("--eval-per", type=int, default=2)
    ap.add_argument("--ppo-updates", type=int, default=100000)
    ap.add_argument("--exit-workers", type=int, default=3, help="look-ahead collector workers beside PPO (0 = off)")
    # training effort goes where runs are still lost (champion u175 wins 82% at crown 0, 14% at 7-8)
    ap.add_argument("--crown-weights", default="0.4,0.6,0.8,1,1.2,1.4,1.5,1.6,1.6")
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args(argv)
    HOME.mkdir(parents=True, exist_ok=True)
    if args.status:
        print(json.dumps(status(args), indent=1, default=str))
        return 0
    log = HOME / "pipeline.log"
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
    from cursed_words_solver.rl.evaluate import eval_jobs

    gate = eval_jobs(per=args.eval_per, per_quest=1, block=1)
    base = [r for r in store.read_jsonl(HOME / "ppo1" / "eval" / "teacher.jsonl") if not r.get("error")]
    if len(base) < len(gate):
        code = ("from cursed_words_solver.rl.evaluate import eval_jobs, run_arm; from pathlib import Path; "
                f"run_arm('teacher', 'teacher', eval_jobs(per={args.eval_per}, per_quest=1, block=1), {args.workers}, "
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
             "--crown-weights", args.crown_weights],
            stdout=ex_log, stderr=subprocess.STDOUT, cwd=str(Path(__file__).resolve().parents[2]))
    ppo_w = str(max(1, args.workers - args.exit_workers + 1)) if args.exit_workers else W
    try:
        _run(["cursed_words_solver.rl.ppo", "--dir", str(HOME / "ppo1"), "--init", str(HOME / "bc" / "best.pt"),
              "--workers", ppo_w, "--updates", str(args.ppo_updates), "--eval-per", str(args.eval_per),
              "--crown-weights", args.crown_weights,
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
