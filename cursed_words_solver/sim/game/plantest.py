"""Whole-run build plans against the plain rules player (S2): every character plays every plan on
the same seeds and crowns, each run committed to its plan from the first shop.

Runs are played in shuffled order and appended to ``runs.jsonl``, so an early report is balanced and
an interrupted test resumes. ``--start`` / ``--n`` pick the seeds per character: raise them to add
seeds for the plans worth a closer look (rules-player runs are shared). The many gains this reports
come from one set of seeds, so confirm the best on fresh ones (``--start`` past those used) first.

usage: python -m cursed_words_solver.sim.game.plantest --out DIR --n 16 --workers 8 [--plans Cards,Curse]
       python -m cursed_words_solver.sim.game.plantest --out DIR --report
"""
from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Any

BASE = "rules"
CROWNS = tuple(range(8))
SEED_BASE = 779_000_000
BANDS = ((0, 2), (3, 5), (6, 7))


def make_jobs(plans: list[str], characters: list[str], start: int, n: int, boss_risk: str = "") -> list[dict[str, Any]]:
    """One run per plan × character × seed; crowns cycle, so each plan and character sees them evenly."""
    jobs = []
    for c, character in enumerate(characters):
        for i in range(start, start + n):
            for plan in plans:
                jobs.append({"plan": plan, "character": character, "crown": CROWNS[i % len(CROWNS)],
                             "seed": SEED_BASE + 10_000 * c + i, "boss_risk": boss_risk,
                             "cfg": {} if plan == BASE else {"build_plan": plan}})
    return jobs


def _run(job: dict[str, Any]) -> dict[str, Any]:
    from cursed_words_solver.sim.game.expert import _eval_job

    return {"plan": job["plan"], **_eval_job(job)}


def load_runs(path: Path) -> dict[tuple[str, int], dict[str, Any]]:
    runs = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue  # a line cut short by a restart
            runs[r["plan"], r["seed"]] = r
    return runs


def play(jobs: list[dict[str, Any]], path: Path, workers: int) -> None:
    from cursed_words_solver.sim.game.agent import spawn_pool
    from cursed_words_solver.sim.game.expert import EFFORT, _init

    done = load_runs(path)
    todo = [j for j in jobs if (j["plan"], j["seed"]) not in done]
    random.Random(0).shuffle(todo)
    print(f"{len(jobs) - len(todo)} of {len(jobs)} runs done", flush=True)
    if not todo:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with spawn_pool(workers, _init, (None, None, EFFORT, False)) as pool:
        for k, r in enumerate(pool.imap_unordered(_run, todo), 1):
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(r) + "\n")
            if r["error"]:
                print(f"seed {r['seed']} plan {r['plan']} crashed: {r['error']}", flush=True)
            if k % 100 == 0:
                print(f"{k} of {len(todo)} new runs", flush=True)


def gains(runs: dict[tuple[str, int], dict[str, Any]], plan: str, keep=lambda r: True) -> dict[str, Any] | None:
    """Plan − rules on the seeds both finished: paired gain and t, and each side's wins."""
    import numpy as np

    pairs = [(r, runs[BASE, seed]) for (p, seed), r in runs.items() if p == plan and (BASE, seed) in runs and keep(r)]
    if len(pairs) < 2:
        return None
    d = np.array([r["outcome"] - b["outcome"] for r, b in pairs])
    se = float(d.std(ddof=1) / np.sqrt(len(d)))
    return {"n": len(d), "gain": float(d.mean()), "se": se, "t": float(d.mean() / se) if se > 0 else 0.0,
            "wins": sum(r["won"] for r, _ in pairs), "base_wins": sum(b["won"] for _, b in pairs)}


def report(runs: dict[tuple[str, int], dict[str, Any]]) -> list[str]:
    plans = sorted({p for p, _ in runs} - {BASE})
    rows = [(plan, gains(runs, plan)) for plan in plans]
    rows = sorted(((p, g) for p, g in rows if g), key=lambda t: -t[1]["gain"])
    out = [f"{len(runs)} runs, {sum(bool(r['error']) for r in runs.values())} crashed. Gain per run over the rules player:",
           f"{'plan':15s} {'runs':>5s} {'gain':>6s} {'t':>6s} {'wins':>9s}   " + "   ".join(f"crowns {a}-{b}" for a, b in BANDS)]
    for plan, g in rows:
        bands = [gains(runs, plan, lambda r, a=a, b=b: a <= r["crown"] <= b) for a, b in BANDS]
        cols = "   ".join(f"{x['gain']:+9.2f}" if x else " " * 9 for x in bands)
        out.append(f"{plan:15s} {g['n']:5d} {g['gain']:+6.2f} {g['t']:+6.2f} {g['wins']:4d}/{g['base_wins']:<4d}   {cols}")
    by_char: dict[str, list[tuple[float, float, str, int]]] = defaultdict(list)
    for character in sorted({r["character"] for r in runs.values()}):
        for plan, _ in rows:
            g = gains(runs, plan, lambda r, c=character: r["character"] == c)
            if g:
                by_char[character].append((g["gain"], g["t"], plan, g["n"]))
    out.append("Best plans per character (noisy, and the best of many: only a lead to confirm):")
    for character, v in by_char.items():
        best = sorted(v, reverse=True)[:3]
        out.append(f"  {character:15s} " + "  ".join(f"{p} {x:+.2f} (t {t:+.1f}, n {n})" for x, t, p, n in best))
    return out


def main() -> None:
    from cursed_words_solver.sim.game.bench import CHARS
    from cursed_words_solver.sim.game.bossrisk import DEFAULT_PATH as RISK
    from cursed_words_solver.sim.game.policy import BUILD_PLANS

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--plans", default="", help="comma-separated (default: all but Colourless)")
    ap.add_argument("--start", type=int, default=0, help="first seed per character")
    ap.add_argument("--n", type=int, default=16, help="seeds per character")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--report", action="store_true", help="only print the results so far")
    args = ap.parse_args()
    path = args.out / "runs.jsonl"
    if not args.report:
        plans = args.plans.split(",") if args.plans else sorted(BUILD_PLANS)
        unknown = set(plans) - set(BUILD_PLANS)
        if unknown:
            ap.error(f"unknown plans {sorted(unknown)}; known: {sorted(BUILD_PLANS)}")
        risk = str(RISK) if RISK.is_file() else ""
        play(make_jobs([BASE, *plans], list(CHARS), args.start, args.n, risk), path, args.workers)
    print("\n".join(report(load_runs(path))), flush=True)
    if not args.report:
        print("done", flush=True)


if __name__ == "__main__":  # spawn-safe: workers import this file
    main()
