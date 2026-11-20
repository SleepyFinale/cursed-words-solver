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
4. ``ppo2``      — PPO from bc2/best.pt with targets (``--pivot 0.5,2,4 --targets-mix 0.3,0.1,0.1
                   --shaping 0.15 --target-curriculum --gate-targets --compare-dir ppo1``: 50% pivot
                   runs, 30% FREE, 10% theme, 10% any plan, on a fresh ppo2; a ppo2 that already has a
                   curriculum.json resumes with the mix / pivot it ran with unless the flags are given),
                   with an exit2 look-ahead collector (pivot share inherited from ppo2/curriculum.json).
                   ``--michael-bonus`` (default 2; rl.ppo --michael-bonus) is the training value of a Michael
                   win on top of a run win (the game's 8 made ppo2 chase the cursed route and die at
                   stage 5); eval rows keep the true outcome, the gate compares with it.
                   exit2 has its own job settings (2026-11-14): ``--exit-search`` (sims 2: as good as 4 at
                   1/3 the cost), ``--exit-crown-weights`` (crowns 5-7 heavy), ``--exit-quest-share`` 0.1,
                   ``--exit-targets-mix`` 1,0,0 (all FREE; '' = ppo2's mix), ``--exit-pivot`` ('' = ppo2's)

``--v3`` (2026-11-20): a fresh ``rl/ppo3`` forked from the ppo2 champion (ppo2 plateaued: champion u425,
no promotion through u669). Needs ``rl/ppo2/champion.pt``; nothing under ppo2 is written (STOP is
forwarded to / cleared in ppo3 and exit2 only). Stages (``--dry-run`` prints the plan):

1. ``seed3`` — copies only: ppo2/champion.pt -> ppo3/ppo2_champion.pt (frozen; the rl.ppo ``--init``);
               the ppo2 champion's gate rows (``evaluate.champion_eval_path(ppo2)``, e.g.
               eval/champion_u425.jsonl) -> ppo3/eval/champion_u0.jsonl, the name a fresh rl.ppo looks
               up (it starts at champion_update 0 and ``run_arm`` plays only rows missing by
               ``cache_key``), so the first gate does not replay the 548 champion games; copied only when
               the frozen policy's update stamp equals that champion's update. Gate eval is greedy with
               no search, but the policy's after-state features play determinized clones
               (``actions._after``), so the 2026-11-20 keyed futures (``core.KeyedRng``) replay a few rows
               differently (1 of 162 sampled: same result, other step count); ``--v3-replay-champion``
               re-plays the champion with the current code instead (548 runs, ~20 min). Also
               ppo2/eval/ppo1_champion.jsonl (the gate's vs_ppo1_all rows) and ppo3/v3_inherit.json
               (ppo2's annealed KL-anchor and adapted entropy coefficients at the fork, ``v3_inherit``).
2. ``ppo3``  — ``v2_ppo_args`` for dir ppo3 (crowns, quests, targets mix / pivot from ppo2's
               curriculum.json, ``--compare-dir ppo1``, ``--michael-bonus``, gate sizes, distill from
               exit2) plus the value / aux fixes ``--v3-aux-coef`` (0.2), ``--v3-vf-lam`` (1.0, Monte
               Carlo value target), ``--v3-vf-epochs`` (2), ``--v3-lam-build`` (off) and the inherited
               ``--kl-coef`` / ``--ent-coef`` (``--v3-kl-coef`` / ``--v3-ent-coef`` override); the exit2
               collector beside it follows ppo3/weights.pt and ppo3/curriculum.json, still writing exit2.
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
    if getattr(args, "v3", False) or (HOME / "ppo3").is_dir():
        out["v3"] = v3_status(args)
    return out


# ------------------------------------------------------------------ v2: build-conditioned

def _n_shards(d: Path) -> int:
    return len(list((d / "shards").glob("*.npz"))) if (d / "shards").is_dir() else 0


def v2_gate_jobs(args) -> list[dict]:
    from cursed_words_solver.rl.evaluate import gate_jobs, themed_gate_jobs

    return gate_jobs(args.gate_per, args.gate_per_quest) + themed_gate_jobs()


V2_TARGETS_MIX, V2_PIVOT = "0.3,0.1,0.1", "0.5,2,4"   # a fresh ppo2: 50% pivot, 30% FREE, 10% theme, 10% any
V2_MICHAEL_BONUS = 2.0   # ppo2 training value of beating Michael (game: 8); win rate first (2026-11-14)
# exit2 (look-ahead labels) job settings, separate from ppo2's: the FREE crown 5-7 slice is where the
# search helps most (+5.7 points with sims 2, about sims 4's gain at 1/3 the cost)
EXIT2_SEARCH = '{"sims": 2}'
EXIT2_CROWN_WEIGHTS = "0.2,0.2,0.3,0.5,1.0,2.0,2.5,1.5"
EXIT2_QUEST_SHARE = 0.1
EXIT2_TARGETS_MIX = "1,0,0"


def _curriculum_target_args(runs: tuple[str, ...]) -> tuple[str, str] | None:
    """(mix, pivot) of the first of ``runs`` (rl dir names) with a curriculum.json, else None."""
    for run in runs:
        try:
            c = json.loads((HOME / run / "curriculum.json").read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(c, dict):
            continue
        mix = ",".join(f"{float(x):g}" for x in c["targets_mix"]) if c.get("targets_mix") else ""
        pivot = ",".join(f"{x:g}" if isinstance(x, float) else str(x) for x in c["pivot"]) if c.get("pivot") else ""
        return mix, pivot
    return None


def v2_target_args(args, runs: tuple[str, ...] = ("ppo2",)) -> tuple[str, str]:
    """(targets_mix, pivot) for ppo2 / exit2. Explicit flags win. Unset: a ppo2 that already has a
    curriculum.json resumes with the mix / pivot it was running (a run started before pivot targets keeps
    its old mix and no pivot); a fresh ppo2 gets V2_TARGETS_MIX / V2_PIVOT. ``runs``: the dirs whose
    curriculum.json is read, first found wins (v3: ppo3, then ppo2)."""
    mix, pivot = getattr(args, "targets_mix", None), getattr(args, "pivot", None)
    if mix is None or pivot is None:
        old_mix, old_pivot = _curriculum_target_args(runs) or (V2_TARGETS_MIX, V2_PIVOT)
        mix = old_mix if mix is None else mix
        pivot = old_pivot if pivot is None else pivot
    return mix, pivot


def v2_ppo_args(args, run: str = "ppo2", init: Path | None = None,
                target_runs: tuple[str, ...] = ("ppo2",)) -> list[str]:
    """rl.ppo for ppo2 (``run`` / ``init`` / ``target_runs``: the v3 fork reuses it for ppo3)."""
    mix, pivot = v2_target_args(args, target_runs)
    ppo_w = str(max(1, args.workers - args.exit_workers + 1)) if args.exit_workers else str(args.workers)
    init = HOME / "bc2" / "best.pt" if init is None else init
    return ["cursed_words_solver.rl.ppo", "--dir", str(HOME / run), "--init", str(init),
            "--workers", ppo_w, "--updates", str(args.ppo_updates),
            "--gate-per", str(args.gate_per), "--gate-per-quest", str(args.gate_per_quest),
            "--crown-weights", args.crown_weights, "--quest-share", str(args.quest_share),
            "--episodes", str(args.episodes), "--ent-target", str(args.ent_target), "--kl-ref", "champion",
            "--distill-coef", str(args.distill_coef), "--distill-same-w", str(args.distill_same_w),
            "--distill-cap", str(args.distill_cap),
            *(["--targets-mix", mix] if mix else []), *(["--pivot", pivot] if pivot else []), "--shaping", str(args.shaping), "--target-curriculum", "--gate-targets",
            "--compare-dir", str(HOME / "ppo1"),
            "--michael-bonus", f"{float(getattr(args, 'michael_bonus', V2_MICHAEL_BONUS)):g}",
            *(["--distill-dir", str(HOME / "exit2")] if args.exit_workers else [])]


def v2_exit_args(args, run: str = "ppo2", target_runs: tuple[str, ...] = ("ppo2",)) -> list[str]:
    """rl.exit for exit2: its own search / crown weights / quest share / targets mix (``--exit-*``);
    an empty ``--exit-targets-mix`` / ``--exit-pivot`` falls back to ppo2's (``v2_target_args`` mix; the
    collector reads the pivot from ppo2/curriculum.json). ``run``: the PPO dir it follows (policy
    weights.pt, curriculum.json; v3: ppo3)."""
    mix = getattr(args, "exit_targets_mix", EXIT2_TARGETS_MIX)
    if not mix:
        mix = v2_target_args(args, target_runs)[0]
    pivot = getattr(args, "exit_pivot", "") or ""
    return ["cursed_words_solver.rl.exit", "--dir", str(HOME / "exit2"),
            "--policy", str(HOME / run / "weights.pt"), "--workers", str(args.exit_workers),
            "--search", getattr(args, "exit_search", EXIT2_SEARCH),
            "--crown-weights", getattr(args, "exit_crown_weights", EXIT2_CROWN_WEIGHTS),
            "--quest-share", str(getattr(args, "exit_quest_share", EXIT2_QUEST_SHARE)),
            "--curriculum", str(HOME / run / "curriculum.json"),
            *(["--targets-mix", mix] if mix else []), *(["--pivot", pivot] if pivot else [])]


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
                                                       "recent_train_outcome", "train_by_target")} if hist else {}
    try:
        c = json.loads((HOME / "ppo2" / "curriculum.json").read_text())
    except (OSError, ValueError):
        c = {}
    # what ppo2 is training with (None: a ppo2 from before the flag, i.e. the game's 8)
    out["ppo2_michael_bonus"] = c.get("michael_bonus") if isinstance(c, dict) else None
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
        _run_with_exit(st["cmd"], st.get("exit"), "ppo2", "exit2", log, V1_DIRS + V2_DIRS)
    return 0


def _run_with_exit(cmd: list[str], exit_cmd: list[str] | None, run: str, exit_name: str, log: Path,
                   dirs: tuple[str, ...]) -> None:
    """The PPO stage ``cmd`` (STOP forwarded to ``dirs``) with the rl.exit collector ``exit_cmd``
    beside it (log rl/<exit_name>.log); the collector is stopped when PPO exits."""
    exit_proc = None
    if exit_cmd:
        (HOME / run).mkdir(parents=True, exist_ok=True)
        ex_log = open(HOME / f"{exit_name}.log", "a", encoding="utf-8")
        exit_proc = subprocess.Popen([sys.executable, "-u", "-m", *exit_cmd], stdout=ex_log,
                                     stderr=subprocess.STDOUT, cwd=str(Path(__file__).resolve().parents[2]))
    try:
        _run(cmd, log, dirs)
    finally:
        if exit_proc is not None:
            (HOME / exit_name).mkdir(parents=True, exist_ok=True)
            (HOME / exit_name / "STOP").touch()
            try:
                exit_proc.wait(timeout=600)
            except subprocess.TimeoutExpired:
                exit_proc.terminate()


# ------------------------------------------------------------------ v3: ppo2 champion + value fixes

V3_DIRS = ("ppo3", "exit2")   # the dirs a v3 run writes (STOP forwarding / clearing); ppo2 is only read
V3_AUX_COEF = 0.2      # rl.ppo --aux-coef: BCE on (won, Michael win); the aux head was never trained in PPO
V3_VF_LAM = 1.0        # rl.ppo --vf-lam: Monte Carlo value target (explained more stage-3 variance offline)
V3_VF_EPOCHS = 2       # rl.ppo --vf-epochs: value(+aux)-only passes, policy held by KL to the snapshot
V3_LAM_BUILD = None    # rl.ppo --lam-build: off
V3_INIT = "ppo2_champion.pt"        # frozen copy of ppo2/champion.pt inside ppo3: the init, and the
                                    # weights the seeded champion_u0 rows were played with
V3_INHERIT = "v3_inherit.json"      # ppo2's KL / entropy coefficients at the fork (written once)


def _policy_update(path: Path) -> int | None:
    """The ``update`` save_policy stamped into a policy file (a promoted champion.pt keeps its
    candidate's), else None."""
    try:
        import torch

        ck = torch.load(path, map_location="cpu", weights_only=False)
        u = (ck.get("extra") or {}).get("update")
        return None if u is None else int(u)
    except Exception:   # noqa: BLE001 - unreadable / foreign file: no stamp
        return None


def v3_seed_plan() -> dict:
    """Read-only: where ppo3's starting-champion gate rows come from. rl.ppo starts a fresh dir at
    champion_update 0 and caches the init's gate rows as eval/champion_u0.jsonl (``run_arm`` plays only
    the jobs missing by ``evaluate.cache_key``); the ppo2 champion's rows are
    ``evaluate.champion_eval_path(ppo2)`` = eval/champion_u{cu}.jsonl. They are reused only when the
    policy stamp of the init (ppo3/ppo2_champion.pt, else ppo2/champion.pt) is that cu."""
    from cursed_words_solver.rl.evaluate import champion_eval_path

    frozen = HOME / "ppo3" / V3_INIT
    pol = frozen if frozen.is_file() else HOME / "ppo2" / "champion.pt"
    src = champion_eval_path(HOME / "ppo2") if (HOME / "ppo2").is_dir() else None
    cu = None
    if src is not None:
        try:
            cu = int(src.stem[len("champion_u"):])
        except ValueError:
            cu = None
    stamp = _policy_update(pol) if pol.is_file() else None
    ok = src is not None and cu is not None and stamp == cu
    why = ("" if ok else "no ppo2 champion eval rows" if src is None else
           f"init stamp {stamp} != champion rows u{cu}")
    return {"policy": str(pol), "stamp": stamp, "src": str(src) if src else None, "champion_update": cu,
            "ok": ok, "why": why, "dst": str(HOME / "ppo3" / "eval" / "champion_u0.jsonl")}


def v3_inherit(args) -> dict:
    """ppo2's annealed KL-anchor coefficient and adapted entropy coefficient at the fork (its last
    history row), so ppo3 continues with ppo2's effective settings instead of rl.ppo's update-0 ones
    (kl 0.1 halving every 300 updates from update 0, ent 0.003). Frozen in ppo3/v3_inherit.json by the
    seeding so a resume passes the same flags; ``--v3-kl-coef`` / ``--v3-ent-coef`` win."""
    p = HOME / "ppo3" / V3_INHERIT
    try:
        got = json.loads(p.read_text())
    except (OSError, ValueError):
        got = None
    if not isinstance(got, dict):
        hist = store.read_jsonl(HOME / "ppo2" / "history.jsonl")
        last = hist[-1] if hist else {}
        got = {"kl_coef": last.get("kl_coef"), "ent_coef": last.get("ent_coef_next", last.get("ent_coef")),
               "ppo2_update": last.get("update")}
    out = dict(got)
    if getattr(args, "v3_kl_coef", None) is not None:
        out["kl_coef"] = args.v3_kl_coef
    if getattr(args, "v3_ent_coef", None) is not None:
        out["ent_coef"] = args.v3_ent_coef
    return out


def v3_ppo_args(args) -> list[str]:
    """ppo3 = ppo2's rl.ppo settings (``v2_ppo_args``: crowns, quests, targets mix / pivot as ppo2's
    curriculum has them, compare ppo1, Michael bonus, exit2 distillation) from the frozen ppo2 champion,
    plus the value / aux fixes and ppo2's KL / entropy coefficients (``v3_inherit``)."""
    cmd = v2_ppo_args(args, run="ppo3", init=HOME / "ppo3" / V3_INIT, target_runs=("ppo3", "ppo2"))
    inh = v3_inherit(args)
    lam_build = getattr(args, "v3_lam_build", V3_LAM_BUILD)
    cmd += ["--aux-coef", f"{float(getattr(args, 'v3_aux_coef', V3_AUX_COEF)):g}",
            "--vf-lam", f"{float(getattr(args, 'v3_vf_lam', V3_VF_LAM)):g}",
            "--vf-epochs", str(int(getattr(args, "v3_vf_epochs", V3_VF_EPOCHS))),
            *(["--lam-build", f"{float(lam_build):g}"] if lam_build is not None else []),
            *(["--kl-coef", f"{float(inh['kl_coef']):g}"] if inh.get("kl_coef") is not None else []),
            *(["--ent-coef", f"{float(inh['ent_coef']):g}"] if inh.get("ent_coef") is not None else [])]
    return cmd


def v3_exit_args(args) -> list[str]:
    """exit2 (same dir: its shards are ppo3's distillation data) following ppo3's weights / curriculum."""
    return v2_exit_args(args, run="ppo3", target_runs=("ppo3", "ppo2"))


def _v3_started() -> bool:
    return (HOME / "ppo3" / "ckpt.pt").is_file()


def v3_stages(args) -> list[dict]:
    """The v3 plan: ``seed3`` (``seed_ppo3``; done once ppo3 started or its champion rows are complete),
    then ``ppo3`` with exit2 beside it."""
    from cursed_words_solver.rl.evaluate import cache_key

    have = {cache_key(r) for r in store.read_jsonl(HOME / "ppo3" / "eval" / "champion_u0.jsonl") if not r.get("error")}
    rows_ok = getattr(args, "v3_replay_champion", False) or all(cache_key(j) in have for j in v2_gate_jobs(args))
    seeded = _v3_started() or ((HOME / "ppo3" / V3_INIT).is_file() and (HOME / "ppo3" / V3_INHERIT).is_file()
                               and rows_ok)
    return [
        {"name": "seed3", "done": seeded, "cmd": None},
        {"name": "ppo3", "done": len(store.read_jsonl(HOME / "ppo3" / "history.jsonl")) >= args.ppo_updates,
         "cmd": v3_ppo_args(args), "exit": v3_exit_args(args) if args.exit_workers > 0 else None},
    ]


def _copy_rows(src: Path, dst: Path) -> int:
    """Append ``src``'s non-error rows missing from ``dst`` (by ``evaluate.cache_key``); ``src`` is only read."""
    from cursed_words_solver.rl.evaluate import cache_key

    have = {cache_key(r) for r in store.read_jsonl(dst) if not r.get("error")}
    n = 0
    for r in store.read_jsonl(src):
        if not r.get("error") and cache_key(r) not in have:
            store.append_jsonl(dst, r)
            have.add(cache_key(r))
            n += 1
    return n


def seed_ppo3(args) -> dict:
    """Prepare a fresh ppo3 from ppo2 (copies only; nothing under ppo2 is written):

    - ppo3/ppo2_champion.pt: frozen copy of ppo2/champion.pt (the rl.ppo --init; rl.ppo copies it to
      init.pt / champion.pt itself);
    - ppo3/eval/champion_u0.jsonl: the ppo2 champion's gate rows (``v3_seed_plan``), so the starting
      champion is not re-played (a fresh rl.ppo champion is update 0);
    - ppo3/eval/ppo1_champion.jsonl (+ teacher.jsonl if ppo2 has one): the gate's vs_ppo1_all rows,
      and ppo3/ppo1_champion.pt (the frozen ppo1 champion) beside them;
    - ppo3/v3_inherit.json: ``v3_inherit`` frozen.

    A started ppo3 (ckpt.pt) is left alone. Returns what was done."""
    import shutil

    if _v3_started():
        return {"skipped": "ppo3 already started"}
    done: dict = {}
    ev = HOME / "ppo3" / "eval"
    ev.mkdir(parents=True, exist_ok=True)
    frozen = HOME / "ppo3" / V3_INIT
    if not frozen.is_file():
        tmp = frozen.with_name(frozen.name + ".tmp")
        shutil.copyfile(HOME / "ppo2" / "champion.pt", tmp)
        os.replace(tmp, frozen)
        done["init"] = str(frozen)
    plan = v3_seed_plan()
    done["plan"] = plan
    if getattr(args, "v3_replay_champion", False):
        done["champion_rows"] = "replay"   # rl.ppo plays the starting champion on the gate itself
    elif plan["ok"]:
        done["champion_rows"] = _copy_rows(Path(plan["src"]), ev / "champion_u0.jsonl")
    for name in ("ppo1_champion.jsonl", "teacher.jsonl"):
        if (HOME / "ppo2" / "eval" / name).is_file():
            done[name] = _copy_rows(HOME / "ppo2" / "eval" / name, ev / name)
    if (HOME / "ppo2" / "ppo1_champion.pt").is_file() and not (HOME / "ppo3" / "ppo1_champion.pt").is_file():
        shutil.copyfile(HOME / "ppo2" / "ppo1_champion.pt", HOME / "ppo3" / "ppo1_champion.pt")
    if not (HOME / "ppo3" / V3_INHERIT).is_file():
        inh = v3_inherit(argparse.Namespace())
        store.atomic_write_json(HOME / "ppo3" / V3_INHERIT, inh)
        done["inherit"] = inh
    return done


def v3_status(args) -> dict:
    from cursed_words_solver.rl.evaluate import cache_key, champion_eval_path, summarize

    out = {st["name"]: "done" if st["done"] else "todo" for st in v3_stages(args)}
    hist = store.read_jsonl(HOME / "ppo3" / "history.jsonl")
    out["ppo3_last"] = {k: hist[-1].get(k) for k in ("update", "episodes", "recent_win", "recent_outcome",
                                                       "recent_train_outcome", "kl_coef", "ent_coef", "ppofix",
                                                       "epochs_run")} if hist else {}
    gates = store.read_jsonl(HOME / "ppo3" / "gates.jsonl")
    out["ppo3_gates"] = len(gates)
    out["ppo3_last_gate"] = gates[-1] if gates else None
    out["ppo3_promotions"] = [g["update"] for g in gates if g.get("promoted")]
    cp = champion_eval_path(HOME / "ppo3") if (HOME / "ppo3").is_dir() else None
    keys = {cache_key(j) for j in v2_gate_jobs(args)}
    rows = [r for r in store.read_jsonl(cp) if not r.get("error") and cache_key(r) in keys] if cp else []
    out["ppo3_champion"] = {"rows": str(cp) if cp else None, "n": f"{len(rows)}/{len(keys)}",
                            **({"eval": summarize(rows)} if rows else {})}
    out["seed"] = v3_seed_plan()
    try:
        out["inherit"] = json.loads((HOME / "ppo3" / V3_INHERIT).read_text())
    except (OSError, ValueError):
        out["inherit"] = None
    out["exit2"] = _exit_status("exit2")
    out["paused"] = (HOME / "STOP").exists()
    return out


def run_v3(args, log: Path) -> int:
    if not (HOME / "ppo2" / "champion.pt").is_file():
        print("--v3 needs a ppo2 champion (rl/ppo2/champion.pt)", flush=True)
        return 1
    for st in v3_stages(args):
        if (HOME / "STOP").exists():
            return 0
        if st["name"] == "seed3":
            info = seed_ppo3(args)
            with open(log, "a", encoding="utf-8") as f:
                f.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} v3 seed {json.dumps(info, default=str)}\n")
            continue
        if st["done"]:
            continue
        # rebuilt after seeding: the inherited coefficients come back from ppo3/v3_inherit.json
        _run_with_exit(v3_ppo_args(args), v3_exit_args(args) if args.exit_workers > 0 else None,
                       "ppo3", "exit2", log, V3_DIRS)
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
    ap.add_argument("--targets-mix", default=None,
                    help="ppo2 / exit2 build-target mix of the non-pivot runs (p_free,p_theme,p_any; normalised); "
                         "default: what ppo2/curriculum.json ran with when resuming, else " + V2_TARGETS_MIX)
    ap.add_argument("--pivot", default=None,
                    help="ppo2 pivot runs p,lo,hi (rl.ppo --pivot; '' = off); default: what ppo2/curriculum.json "
                         "ran with when resuming (none = off), else " + V2_PIVOT)
    ap.add_argument("--shaping", type=float, default=0.15, help="ppo2 potential per owned on-target item")
    ap.add_argument("--michael-bonus", type=float, default=V2_MICHAEL_BONUS,
                    help="ppo2 training value of beating Michael on top of a run win (rl.ppo --michael-bonus; "
                         "the game's is 8; eval rows keep the true outcome)")
    ap.add_argument("--exit-search", default=EXIT2_SEARCH, help="exit2 look-ahead SearchConfig JSON (rl.exit --search)")
    ap.add_argument("--exit-crown-weights", default=EXIT2_CROWN_WEIGHTS, help="exit2 crown 0-7 weights (rl.exit --crown-weights)")
    ap.add_argument("--exit-quest-share", type=float, default=EXIT2_QUEST_SHARE, help="exit2 quest share (rl.exit --quest-share)")
    ap.add_argument("--exit-targets-mix", default=EXIT2_TARGETS_MIX,
                    help="exit2 build-target mix of its non-pivot runs (rl.exit --targets-mix; 1,0,0 = all FREE; "
                         "'' = ppo2's mix; pivot runs follow --exit-pivot)")
    ap.add_argument("--exit-pivot", default="off", help="exit2 pivot runs (rl.exit --pivot; 'off' = none; '' = ppo2's)")
    ap.add_argument("--v3", action="store_true",
                    help="ppo3: rl.ppo with ppo2's settings from the ppo2 champion + value / aux fixes, exit2 beside it")
    ap.add_argument("--v3-aux-coef", type=float, default=V3_AUX_COEF, help="ppo3 rl.ppo --aux-coef")
    ap.add_argument("--v3-vf-lam", type=float, default=V3_VF_LAM, help="ppo3 rl.ppo --vf-lam")
    ap.add_argument("--v3-vf-epochs", type=int, default=V3_VF_EPOCHS, help="ppo3 rl.ppo --vf-epochs")
    ap.add_argument("--v3-lam-build", type=float, default=V3_LAM_BUILD, help="ppo3 rl.ppo --lam-build (default off)")
    ap.add_argument("--v3-kl-coef", type=float, default=None,
                    help="ppo3 rl.ppo --kl-coef; default: ppo2's annealed coefficient at the fork (ppo3/v3_inherit.json)")
    ap.add_argument("--v3-ent-coef", type=float, default=None,
                    help="ppo3 starting rl.ppo --ent-coef; default: ppo2's adapted coefficient at the fork")
    ap.add_argument("--v3-replay-champion", action="store_true",
                    help="ppo3: do not copy ppo2's champion gate rows; rl.ppo re-plays the starting champion "
                         "(548 runs) with the current code (the copied rows predate the keyed futures)")
    ap.add_argument("--dry-run", action="store_true", help="--v2 / --v3: print the stage plan and exit")
    args = ap.parse_args(argv)
    if args.v2 and args.v3:
        ap.error("--v2 and --v3 are separate runs; pick one")
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
    if args.v3 and args.dry_run:
        if not (HOME / "ppo2" / "champion.pt").is_file():
            print("--v3 needs a ppo2 champion (rl/ppo2/champion.pt)", flush=True)
            return 1
        plan = v3_seed_plan()
        seed = ("replay (--v3-replay-champion): the champion is re-played" if args.v3_replay_champion else
                "ok" if plan["ok"] else "NOT seeded (" + plan["why"] + "): the champion is re-played")
        print(f"seed      {seed}"
              f"  {plan['src']} (policy stamp u{plan['stamp']}) -> {plan['dst']}")
        print(f"inherit   {json.dumps(v3_inherit(args))}")
        for st in v3_stages(args):
            print(f"{st['name']:10s} {'done' if st['done'] else 'todo'}  {' '.join(st['cmd'] or ['(copy from ppo2)'])}")
            if st.get("exit"):
                print(f"{'':10s} beside: {' '.join(st['exit'])}")
        return 0
    log = HOME / "pipeline.log"
    lock = _single_instance()
    if lock is None:
        print("another pipeline is still running (or still shutting down after STOP); try again when it exits",
              flush=True)
        return 1
    # --v3 clears only its own dirs: ppo2's (paused) run is never touched
    for d in V3_DIRS if args.v3 else V1_DIRS + (V2_DIRS if args.v2 else ()):
        (HOME / d / "STOP").unlink(missing_ok=True)
    (HOME / "command.txt").write_text(f"python -m cursed_words_solver.rl.pipeline {' '.join(argv or sys.argv[1:])}\n")
    if args.v3:
        return run_v3(args, log)
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
