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

``--v2``: build-conditioned training on top of a finished ppo1 (``rl/targets.py``); the v1 stages
are not run. Stages (skipped when complete; ``--dry-run`` prints the plan):

1. ``teacher2``  — themed teacher data (``teacher --themed --dir teacher2 --runs --teacher2-runs``)
2. ``bc2``       — BC on it from the ppo1 champion, KL-anchored to it (``bc --init/--anchor``)
3. ``baseline2`` — the ppo1 champion (frozen copy ppo2/ppo1_champion.pt) on the ppo2 gate incl. the
                   themed block, as ppo2/eval/ppo1_champion.jsonl; FREE rows are copied from
                   ppo1's champion eval cache when keys match
4. ``ppo2``      — PPO from bc2/best.pt with targets (``--targets-mix 0.3,0.4,0.3 --shaping 0.15
                   --gate-targets --compare-dir ppo1``), with an exit2 look-ahead collector
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
V1_DIRS = ("teacher", "bc", "ppo1", "exit")
V2_DIRS = ("teacher2", "bc2", "ppo2", "exit2")


def _run(args: list[str], log: Path, dirs: tuple[str, ...] = V1_DIRS) -> int:
    with open(log, "a", encoding="utf-8") as f:
        f.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} {' '.join(args)}\n")
        f.flush()
        p = subprocess.Popen([sys.executable, "-u", "-m", *args], stdout=f, stderr=subprocess.STDOUT,
                             cwd=str(Path(__file__).resolve().parents[2]))
        try:
            while p.poll() is None:
                if (HOME / "STOP").exists():
                    # forward the pause to the stage (each stage checks its own STOP file)
                    for d in dirs:
                        (HOME / d).mkdir(parents=True, exist_ok=True)
                        (HOME / d / "STOP").touch()
                time.sleep(2)
        except KeyboardInterrupt:
            p.terminate()
            raise
        return p.returncode


def _exit_status(name: str = "exit") -> dict:
    p = HOME / name / "state.json"
    if not p.is_file():
        return {}
    rows = [r for r in store.read_jsonl(HOME / name / "runs.jsonl")[-200:]
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
    if getattr(args, "v2", False) or any((HOME / d).is_dir() for d in V2_DIRS):
        out["v2"] = v2_status(args)
    return out


# ------------------------------------------------------------------ v2: build-conditioned

def _n_shards(d: Path) -> int:
    return len(list((d / "shards").glob("*.npz"))) if (d / "shards").is_dir() else 0


def v2_gate_jobs(args) -> list[dict]:
    from cursed_words_solver.rl.evaluate import gate_jobs, themed_gate_jobs

    return gate_jobs(args.gate_per, args.gate_per_quest) + themed_gate_jobs()


def v2_ppo_args(args) -> list[str]:
    ppo_w = str(max(1, args.workers - args.exit_workers + 1)) if args.exit_workers else str(args.workers)
    return ["cursed_words_solver.rl.ppo", "--dir", str(HOME / "ppo2"), "--init", str(HOME / "bc2" / "best.pt"),
            "--workers", ppo_w, "--updates", str(args.ppo_updates),
            "--gate-per", str(args.gate_per), "--gate-per-quest", str(args.gate_per_quest),
            "--crown-weights", args.crown_weights, "--quest-share", str(args.quest_share),
            "--episodes", str(args.episodes), "--ent-target", str(args.ent_target), "--kl-ref", "champion",
            "--distill-coef", str(args.distill_coef), "--distill-same-w", str(args.distill_same_w),
            "--distill-cap", str(args.distill_cap),
            "--targets-mix", args.targets_mix, "--shaping", str(args.shaping), "--gate-targets",
            "--compare-dir", str(HOME / "ppo1"),
            *(["--distill-dir", str(HOME / "exit2")] if args.exit_workers else [])]


def v2_exit_args(args) -> list[str]:
    return ["cursed_words_solver.rl.exit", "--dir", str(HOME / "exit2"),
            "--policy", str(HOME / "ppo2" / "weights.pt"), "--workers", str(args.exit_workers),
            "--crown-weights", args.crown_weights, "--quest-share", str(args.quest_share),
            "--curriculum", str(HOME / "ppo2" / "curriculum.json"), "--targets-mix", args.targets_mix]


def v2_stages(args) -> list[dict]:
    """The v2 stage plan: name, done (output complete -> skipped), module args of the stage."""
    from cursed_words_solver.rl.evaluate import key

    have = {key(r) for r in store.read_jsonl(HOME / "ppo2" / "eval" / "ppo1_champion.jsonl") if not r.get("error")}
    return [
        {"name": "teacher2", "done": _n_shards(HOME / "teacher2") >= args.teacher2_runs,
         "cmd": ["cursed_words_solver.rl.teacher", "--themed", "--dir", str(HOME / "teacher2"),
                 "--runs", str(args.teacher2_runs), "--workers", str(args.workers)]},
        {"name": "bc2", "done": len(store.read_jsonl(HOME / "bc2" / "history.jsonl")) >= args.bc2_epochs,
         "cmd": ["cursed_words_solver.rl.bc", "--data", str(HOME / "teacher2"), "--dir", str(HOME / "bc2"),
                 "--init", str(HOME / "ppo1" / "champion.pt"), "--anchor", str(HOME / "ppo1" / "champion.pt"),
                 "--anchor-coef", str(getattr(args, "bc2_anchor_coef", 5.0)), "--lr", str(getattr(args, "bc2_lr", 1e-4)),
                 "--epochs", str(args.bc2_epochs)]},
        {"name": "baseline2", "done": all(key(j) in have for j in v2_gate_jobs(args)), "cmd": None},
        {"name": "ppo2", "done": len(store.read_jsonl(HOME / "ppo2" / "history.jsonl")) >= args.ppo_updates,
         "cmd": v2_ppo_args(args), "exit": v2_exit_args(args) if args.exit_workers > 0 else None},
    ]


def seed_baseline2() -> int:
    """Copy the ppo1 champion's FREE gate rows (ppo1/eval/champion_u*.jsonl; greedy and the same
    weights, so the same runs) into ppo2/eval/ppo1_champion.jsonl where that lacks them; and freeze
    the ppo1 champion as ppo2/ppo1_champion.pt. Returns rows copied."""
    import shutil

    from cursed_words_solver.rl.evaluate import champion_eval_path, key

    (HOME / "ppo2" / "eval").mkdir(parents=True, exist_ok=True)
    frozen = HOME / "ppo2" / "ppo1_champion.pt"
    if not frozen.is_file():
        shutil.copyfile(HOME / "ppo1" / "champion.pt", frozen)
    src = champion_eval_path(HOME / "ppo1")
    if src is None:
        return 0
    dst = HOME / "ppo2" / "eval" / "ppo1_champion.jsonl"
    have = {key(r) for r in store.read_jsonl(dst) if not r.get("error")}
    n = 0
    for r in store.read_jsonl(src):
        if not r.get("error") and not r.get("target") and key(r) not in have:
            store.append_jsonl(dst, r)
            have.add(key(r))
            n += 1
    return n


def v2_status(args) -> dict:
    out = {}
    for st in v2_stages(args):
        out[st["name"]] = "done" if st["done"] else "todo"
    out["teacher2_shards"] = f"{_n_shards(HOME / 'teacher2')}/{args.teacher2_runs}"
    out["bc2_epochs"] = f"{len(store.read_jsonl(HOME / 'bc2' / 'history.jsonl'))}/{args.bc2_epochs}"
    hist = store.read_jsonl(HOME / "ppo2" / "history.jsonl")
    out["ppo2_last"] = {k: hist[-1].get(k) for k in ("update", "episodes", "recent_win", "recent_outcome",
                                                       "train_by_target")} if hist else {}
    gates = store.read_jsonl(HOME / "ppo2" / "gates.jsonl")
    out["ppo2_last_gate"] = gates[-1] if gates else None
    out["exit2"] = _exit_status("exit2")
    return out


def run_v2(args, log: Path) -> int:
    if not (HOME / "ppo1" / "champion.pt").is_file():
        print("--v2 needs a ppo1 champion (rl/ppo1/champion.pt)", flush=True)
        return 1
    for st in v2_stages(args):
        if (HOME / "STOP").exists():
            return 0
        if st["done"]:
            continue
        if st["name"] == "baseline2":
            seed_baseline2()
            code = ("from cursed_words_solver.rl.evaluate import gate_jobs, run_arm, themed_gate_jobs; "
                    "from pathlib import Path; "
                    f"run_arm('ppo1_champion', r'{HOME / 'ppo2' / 'ppo1_champion.pt'}', "
                    f"gate_jobs({args.gate_per}, {args.gate_per_quest}) + themed_gate_jobs(), {args.workers}, "
                    f"out_dir=Path(r'{HOME / 'ppo2' / 'eval'}'))")
            with open(log, "a", encoding="utf-8") as f:
                f.write("\n=== ppo1 champion baseline on the ppo2 gate\n")
                f.flush()
                subprocess.call([sys.executable, "-u", "-c", code], stdout=f, stderr=subprocess.STDOUT,
                                cwd=str(Path(__file__).resolve().parents[2]))
            continue
        if st["name"] != "ppo2":
            _run(st["cmd"], log, V1_DIRS + V2_DIRS)
            continue
        exit_proc = None
        if st.get("exit"):
            (HOME / "ppo2").mkdir(parents=True, exist_ok=True)
            ex_log = open(HOME / "exit2.log", "a", encoding="utf-8")
            exit_proc = subprocess.Popen([sys.executable, "-u", "-m", *st["exit"]], stdout=ex_log,
                                         stderr=subprocess.STDOUT, cwd=str(Path(__file__).resolve().parents[2]))
        try:
            _run(st["cmd"], log, V1_DIRS + V2_DIRS)
        finally:
            if exit_proc is not None:
                (HOME / "exit2").mkdir(parents=True, exist_ok=True)
                (HOME / "exit2" / "STOP").touch()
                try:
                    exit_proc.wait(timeout=600)
                except subprocess.TimeoutExpired:
                    exit_proc.terminate()
    return 0


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
    ap.add_argument("--v2", action="store_true", help="build-conditioned stages: teacher2, bc2, baseline2, ppo2 + exit2")
    ap.add_argument("--teacher2-runs", type=int, default=2400)
    ap.add_argument("--bc2-epochs", type=int, default=12)
    # a smoke run drifted FREE play far from the ppo1 champion at coef 1 (anchor KL 0 -> 1.7 in 4 steps):
    # the champion's CE on themed teacher picks is ~17 nats; watch val_anchor_kl (stop if > ~0.1)
    ap.add_argument("--bc2-anchor-coef", type=float, default=5.0, help="bc2 KL anchor to the ppo1 champion (FREE play)")
    ap.add_argument("--bc2-lr", type=float, default=1e-4)
    ap.add_argument("--targets-mix", default="0.3,0.4,0.3", help="ppo2 / exit2 build-target mix (p_free,p_theme,p_any)")
    ap.add_argument("--shaping", type=float, default=0.15, help="ppo2 potential per owned on-target item")
    ap.add_argument("--dry-run", action="store_true", help="--v2: print the stage plan and exit")
    args = ap.parse_args(argv)
    HOME.mkdir(parents=True, exist_ok=True)
    if args.status:
        print(json.dumps(status(args), indent=1, default=str))
        return 0
    if args.v2 and args.dry_run:
        for st in v2_stages(args):
            print(f"{st['name']:10s} {'done' if st['done'] else 'todo'}  {' '.join(st['cmd'] or ['(run_arm)'])}")
            if st.get("exit"):
                print(f"{'':10s} beside: {' '.join(st['exit'])}")
        return 0
    log = HOME / "pipeline.log"
    lock = _single_instance()
    if lock is None:
        print("another pipeline is still running (or still shutting down after STOP); try again when it exits",
              flush=True)
        return 1
    for d in V1_DIRS + (V2_DIRS if args.v2 else ()):
        (HOME / d / "STOP").unlink(missing_ok=True)
    (HOME / "command.txt").write_text(f"python -m cursed_words_solver.rl.pipeline {' '.join(argv or sys.argv[1:])}\n")
    if args.v2:
        return run_v2(args, log)
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
