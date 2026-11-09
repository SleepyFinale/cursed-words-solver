"""Whole-run build plans against the plain rules player (S2): every character plays every plan on
the same seeds and crowns, each run committed to its plan from the first shop.

Runs are played in shuffled order and appended to ``runs.jsonl``, so an early report is balanced and
an interrupted test resumes. ``--start`` / ``--n`` pick the seeds per character: raise them to add
seeds for the plans worth a closer look (rules-player runs are shared). The many gains this reports
come from one set of seeds, so confirm the best on fresh ones (``--start`` past those used) first.

``--arm name=Plan:key=value,...`` adds a plan with other ``PowerConfig`` settings, played on the same
seeds, e.g. ``--arm g1=Curse:build_plan_commit=1``. ``--versus`` reports against another arm than rules.

usage: python -m cursed_words_solver.sim.game.plantest --out DIR --n 16 --workers 8 [--plans Cards,Curse] [--arm ...]
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


def parse_arm(spec: str) -> tuple[str, dict[str, Any]]:
    """``name=Plan:key=value,...`` -> (name, ``PowerConfig`` overrides)."""
    name, _, rest = spec.partition("=")
    plan, _, settings = rest.partition(":")
    if not name or not plan:
        raise ValueError(f"bad arm {spec!r}: expected name=Plan:key=value,...")
    cfg: dict[str, Any] = {"build_plan": plan, "build_plan_chars": {}}
    for kv in filter(None, settings.split(",")):
        key, _, value = kv.partition("=")
        cfg[key] = json.loads(value)
    return name, cfg


def plan_cfg(plan: str) -> dict[str, Any]:
    """``PowerConfig`` overrides that play ``plan`` for every character (``BASE``: no plan)."""
    return {"build_plan": ""} if plan == BASE else {"build_plan": plan, "build_plan_chars": {}}


def make_jobs(plans: list[str], characters: list[str], start: int, n: int, boss_risk: str = "",
              arms: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """One run per plan × character × seed; crowns cycle, so each plan and character sees them evenly."""
    arms = arms or {}
    jobs = []
    for c, character in enumerate(characters):
        for i in range(start, start + n):
            for plan in plans:
                jobs.append({"plan": plan, "character": character, "crown": CROWNS[i % len(CROWNS)],
                             "seed": SEED_BASE + 10_000 * c + i, "boss_risk": boss_risk,
                             "cfg": arms.get(plan) or plan_cfg(plan)})
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


def gains(runs: dict[tuple[str, int], dict[str, Any]], plan: str, keep=lambda r: True, base: str = BASE) -> dict[str, Any] | None:
    """Plan − base on the seeds both finished: paired gain and t, and each side's wins."""
    import numpy as np

    pairs = [(r, runs[base, seed]) for (p, seed), r in runs.items() if p == plan and (base, seed) in runs and keep(r)]
    if len(pairs) < 2:
        return None
    d = np.array([r["outcome"] - b["outcome"] for r, b in pairs])
    se = float(d.std(ddof=1) / np.sqrt(len(d)))
    return {"n": len(d), "gain": float(d.mean()), "se": se, "t": float(d.mean() / se) if se > 0 else 0.0,
            "wins": sum(r["won"] for r, _ in pairs), "base_wins": sum(b["won"] for _, b in pairs),
            "only_plan": sum(r["won"] and not b["won"] for r, b in pairs),
            "only_base": sum(b["won"] and not r["won"] for r, b in pairs),
            "michael": sum(r["outcome"] >= 24 for r, _ in pairs), "base_michael": sum(b["outcome"] >= 24 for _, b in pairs),
            "early": sum(not r["won"] and r["stage"] <= 2 for r, _ in pairs),
            "base_early": sum(not b["won"] and b["stage"] <= 2 for _, b in pairs)}


def versus(runs: dict[tuple[str, int], dict[str, Any]], base: str) -> list[str]:
    """Every arm against ``base``, wins first, with the wins bound and per-character changes."""
    from cursed_words_solver.sim.game.bench import rate_change

    rows = []
    for plan in sorted({p for p, _ in runs} - {base}):
        g = gains(runs, plan, base=base)
        if g:
            pairs = [(runs[base, seed]["won"], r["won"]) for (p, seed), r in runs.items() if p == plan and (base, seed) in runs]
            rows.append((plan, g, rate_change([a for a, _ in pairs], [b for _, b in pairs])))
    rows.sort(key=lambda t: -t[2]["change"])
    out = [f"Against {base}: wins, change in points (one-sided 95% lower bound), won only by each side, Michael wins, dead by stage 2, outcome.",
           f"{'arm':12s} {'runs':>5s} {'wins':>9s} {'change':>7s} {'lower':>6s} {'only':>8s} {'Michael':>9s} {'early':>9s} {'outcome':>8s} {'t':>6s}"]
    for plan, g, w in rows:
        out.append(f"{plan:12s} {g['n']:5d} {g['wins']:4d}/{g['base_wins']:<4d} {100 * w['change']:+7.1f} {100 * w['lower']:+6.1f}"
                   f" {g['only_plan']:3d}/{g['only_base']:<4d} {g['michael']:4d}/{g['base_michael']:<4d} {g['early']:4d}/{g['base_early']:<4d}"
                   f" {g['gain']:+8.2f} {g['t']:+6.2f}")
    out.append("Wins per character, arm/base:")
    for character in sorted({r["character"] for r in runs.values()}):
        cols = []
        for plan, _, _ in rows:
            c = gains(runs, plan, lambda r, c=character: r["character"] == c, base=base)
            if c:
                cols.append(f"{plan} {c['wins']}/{c['base_wins']}")
        out.append(f"  {character:15s} " + "  ".join(cols))
    return out


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
    ap.add_argument("--plans", default="", help="comma-separated (default: all but Colourless, or none with --arm)")
    ap.add_argument("--arm", action="append", default=[], help="name=Plan:key=value,... (repeatable)")
    ap.add_argument("--versus", default="", help="also report every arm against this one")
    ap.add_argument("--start", type=int, default=0, help="first seed per character")
    ap.add_argument("--n", type=int, default=16, help="seeds per character")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--report", action="store_true", help="only print the results so far")
    args = ap.parse_args()
    path = args.out / "runs.jsonl"
    if not args.report:
        arms = dict(parse_arm(a) for a in args.arm)
        plans = args.plans.split(",") if args.plans else ([] if arms else sorted(BUILD_PLANS))
        unknown = (set(plans) | {c["build_plan"] for c in arms.values()}) - set(BUILD_PLANS)
        if unknown:
            ap.error(f"unknown plans {sorted(unknown)}; known: {sorted(BUILD_PLANS)}")
        risk = str(RISK) if RISK.is_file() else ""
        play(make_jobs([BASE, *plans, *arms], list(CHARS), args.start, args.n, risk, arms), path, args.workers)
    runs = load_runs(path)
    print("\n".join(report(runs)), flush=True)
    if args.versus:
        print("\n".join(versus(runs, args.versus)), flush=True)
    if not args.report:
        print("done", flush=True)


if __name__ == "__main__":  # spawn-safe: workers import this file
    main()
