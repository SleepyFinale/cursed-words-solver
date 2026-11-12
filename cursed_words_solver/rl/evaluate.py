"""Evaluate a policy on a fixed seed set; results are cached per run (resumable) and
compared paired (same character / crown / quest / seed) against another arm.

    python -m cursed_words_solver.rl.evaluate run --arm bc1 --policy ~/.cursed_words_solver/rl/bc/best.pt
    python -m cursed_words_solver.rl.evaluate run --arm teacher --policy teacher
    python -m cursed_words_solver.rl.evaluate compare bc1 teacher

Seed sets: ``main`` = 11 characters Ã— crowns 0-7 Ã— ``--per`` seeds (block 40,000,000) plus
26 quests Ã— ``--per-quest``. ``fresh<K>`` = a different block for confirmation.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from typing import Any

from cursed_words_solver.rl import store
from cursed_words_solver.rl.teacher import CHARS

EVAL_HOME = store.RL_HOME / "eval"


# playable crowns: GameStatics.HighestCrownAvailable = 7. AscensionLevel 8 (HarderBosses: every boss
# at the next floor's strength) exists in code only, so no run is ever played or scored there.
CROWNS = range(8)


def eval_jobs(per: int = 3, per_quest: int = 1, block: int = 0, crowns=CROWNS) -> list[dict[str, Any]]:
    from cursed_words_solver.sim.game.challenges import QUESTS

    base = 40_000_000 + 1_000_000 * block
    out = []
    for ci, ch in enumerate(CHARS):
        for cr in crowns:
            for i in range(per):
                out.append({"character": ch, "crown": cr, "quest": None, "seed": base + 10_000 * ci + 100 * cr + i})
    for qi, q in enumerate(sorted(QUESTS)):
        for i in range(per_quest):
            ch = CHARS[(qi + i) % len(CHARS)]
            out.append({"character": ch, "crown": 0, "quest": q, "seed": base + 500_000 + 100 * qi + i})
    return out


def key(r: dict) -> tuple:
    return (r["character"], r["crown"], r.get("quest") or "", r["seed"])


def run_arm(arm: str, policy: str, jobs: list[dict], workers: int = 7, *, greedy: bool = True, search=None,
            out_dir: Path = EVAL_HOME, pool=None, verbose: bool = True) -> list[dict]:
    path = Path(out_dir) / f"{arm}.jsonl"
    done = {key(r): r for r in store.read_jsonl(path) if not r.get("error")}
    todo = [j for j in jobs if key(j) not in done]
    if todo:
        from cursed_words_solver.rl.play import init_worker, play
        from cursed_words_solver.sim.game.agent import spawn_pool

        own = pool is None
        pool = pool or spawn_pool(workers, init_worker, ())
        t0 = time.time()
        try:
            for n, r in enumerate(pool.imap_unordered(play, [{**j, "policy": policy, "greedy": greedy, "search": search} for j in todo]), 1):
                r.pop("traj", None)
                store.append_jsonl(path, r)
                if not r.get("error"):
                    done[key(r)] = r
                elif verbose:
                    print("ERROR", r["error"], r.get("trace", "")[-300:], flush=True)
                if verbose and n % 25 == 0:
                    print(f"[{arm}] {n}/{len(todo)} {n / (time.time() - t0) * 3600:.0f} runs/h", flush=True)
        finally:
            if own:
                pool.terminate()
    return [done[key(j)] for j in jobs if key(j) in done]


def summarize(rows: list[dict]) -> dict:
    n = len(rows)
    if not n:
        return {"n": 0}
    wins = sum(bool(r["won"]) for r in rows)
    mich = sum(r.get("reason") == "michael" for r in rows)
    out = sum(r["outcome"] for r in rows) / n
    return {"n": n, "wins": wins, "win_rate": round(wins / n, 4), "michael_wins": mich, "outcome": round(out, 3)}


def paired(a: list[dict], b: list[dict]) -> dict:
    bk = {key(r): r for r in b}
    pairs = [(r, bk[key(r)]) for r in a if key(r) in bk]
    if not pairs:
        return {"n": 0}
    d = [x["outcome"] - y["outcome"] for x, y in pairs]
    n = len(d)
    mean = sum(d) / n
    sd = math.sqrt(sum((v - mean) ** 2 for v in d) / max(1, n - 1))
    only_a = sum(bool(x["won"]) and not bool(y["won"]) for x, y in pairs)
    only_b = sum(bool(y["won"]) and not bool(x["won"]) for x, y in pairs)
    wa = sum(bool(x["won"]) for x, _ in pairs)
    wb = sum(bool(y["won"]) for _, y in pairs)
    disc = only_a + only_b
    # win-rate difference with McNemar-style SE
    se_w = math.sqrt(max(1, disc)) / n
    return {"n": n, "wins_a": wa, "wins_b": wb, "win_diff": round((wa - wb) / n, 4),
            "win_diff_lb90": round((wa - wb) / n - 1.645 * se_w, 4), "only_a": only_a, "only_b": only_b,
            "win_z": round((only_a - only_b) / math.sqrt(disc), 2) if disc else 0.0,
            "outcome_diff": round(mean, 3), "t": round(mean / (sd / math.sqrt(n)) if sd > 0 else 0.0, 2)}


# PPO gate: block 1, 4 seeds per character x crown + 2 per quest = 404 runs. eval_jobs seeds are
# prefix-stable in per / per_quest, so the earlier 202-run gate (2 / 1) rows are reused.
GATE_PER, GATE_PER_QUEST = 4, 2


def gate_jobs(per: int = GATE_PER, per_quest: int = GATE_PER_QUEST) -> list[dict[str, Any]]:
    return eval_jobs(per=per, per_quest=per_quest, block=1)


def promote_ok(cmp: dict, min_z: float = 1.0) -> bool:
    """Candidate beats the champion paired: more wins and more outcome, and at least one of the
    two differences is >= ``min_z`` standard errors (outcome t, or win z = win_diff / (sqrt(disc) / n))."""
    if not cmp.get("n"):
        return False
    return cmp["win_diff"] > 0 and cmp["outcome_diff"] > 0 and max(cmp["t"], cmp.get("win_z", 0.0)) >= min_z


def table(rows: list[dict], by: str) -> dict:
    groups: dict = {}
    for r in rows:
        k = (r.get("quest") or "-") if by == "quest" else r[by]
        groups.setdefault(k, []).append(r)
    return {k: summarize(v) for k, v in sorted(groups.items(), key=lambda kv: str(kv[0]))}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--arm", required=True)
    r.add_argument("--policy", required=True, help="'teacher' or a policy .pt file")
    r.add_argument("--per", type=int, default=3)
    r.add_argument("--per-quest", type=int, default=1)
    r.add_argument("--block", type=int, default=0)
    r.add_argument("--workers", type=int, default=7)
    r.add_argument("--sample", action="store_true", help="sample actions instead of greedy")
    r.add_argument("--search", default="", help="decision-time look-ahead: JSON SearchConfig, e.g. '{}' or '{\"sims\": 2}'")
    c = sub.add_parser("compare")
    c.add_argument("a")
    c.add_argument("b")
    s = sub.add_parser("show")
    s.add_argument("arm")
    args = ap.parse_args(argv)
    EVAL_HOME.mkdir(parents=True, exist_ok=True)
    if args.cmd == "run":
        pol = args.policy if args.policy == "teacher" else str(Path(args.policy).expanduser())
        rows = run_arm(args.arm, pol, eval_jobs(args.per, args.per_quest, args.block), args.workers, greedy=not args.sample, search=json.loads(args.search) if args.search else None)
        print(summarize(rows))
    elif args.cmd == "compare":
        a = store.read_jsonl(EVAL_HOME / f"{args.a}.jsonl")
        b = store.read_jsonl(EVAL_HOME / f"{args.b}.jsonl")
        a = [x for x in a if not x.get("error") and x["crown"] in CROWNS]
        b = [x for x in b if not x.get("error") and x["crown"] in CROWNS]
        print("A", summarize(a), "\nB", summarize(b), "\npaired", paired(a, b))
    else:
        rows = [x for x in store.read_jsonl(EVAL_HOME / f"{args.arm}.jsonl")
                if not x.get("error") and x["crown"] in CROWNS]
        print(summarize(rows))
        for by in ("crown", "character", "quest"):
            print(by, table(rows, by))


if __name__ == "__main__":
    main()
