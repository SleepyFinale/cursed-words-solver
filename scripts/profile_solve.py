#!/usr/bin/env python3
"""Profile WordSearcher on a chess-heavy mismatch fixture (cProfile breakdown)."""

from __future__ import annotations

import argparse
import cProfile
import json
import pstats
import sys
import time
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cursed_words_solver.config import GAME_WORDLIST_PATH, ensure_wordlist
from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
from cursed_words_solver.search import WordSearcher

DEFAULT_FIXTURE = (
    ROOT / "tests" / "fixtures" / "mismatches" / "20260525_172555.json"
)

_PROFILE_BUCKETS = (
    ("dfs_collect", "search.py", "_collect_words"),
    ("chess_neighbors", "chess_tiles.py", "chess_neighbors"),
    ("chess_attacked", "chess_tiles.py", "is_square_attacked"),
    ("score_total_only", "pipeline.py", "score_total_only"),
    ("compute_state", "pipeline.py", "_compute_state"),
    ("prefix_ok", "search.py", "prefix_ok"),
)


def _load_case(fixture: Path) -> tuple:
    from tests.regression.test_scoring_mismatches import _run_state_for_replay

    data = json.loads(fixture.read_text(encoding="utf-8"))
    run_state = _run_state_for_replay(data)
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    if board is None:
        raise SystemExit(f"No board in fixture: {fixture}")
    return board, loadout


def _bucket_stats(stats: pstats.Stats) -> dict[str, float]:
    totals: dict[str, float] = {name: 0.0 for name, _, _ in _PROFILE_BUCKETS}
    totals["other"] = 0.0
    for func, (_, _, _, cumtime, _) in stats.stats.items():
        filename = func[0].replace("\\", "/")
        matched = False
        for name, file_part, func_name in _PROFILE_BUCKETS:
            if file_part in filename and func[2] == func_name:
                totals[name] += cumtime
                matched = True
                break
        if not matched and "cursed_words_solver" in filename:
            totals["other"] += cumtime
    return totals


def run_profile(
    fixture: Path,
    *,
    budget: float,
    wordlist: Path | None,
    workers: int | str,
) -> None:
    board, loadout = _load_case(fixture)
    wl = wordlist or (
        GAME_WORDLIST_PATH if GAME_WORDLIST_PATH.exists() else ensure_wordlist()
    )
    dictionary = WordDictionary(wl)
    from cursed_words_solver.search_parallel import resolve_search_workers

    searcher = WordSearcher(
        dictionary=dictionary,
        min_len=1,
        max_len=max(1, sum(board.active)),
        time_budget=budget,
        wordlist_path=wl,
        search_workers=resolve_search_workers(workers),
    )

    profiler = cProfile.Profile()
    t0 = time.perf_counter()
    profiler.enable()
    results = searcher.find_best_words(board, loadout, top_n=3)
    profiler.disable()
    elapsed = time.perf_counter() - t0

    stream = StringIO()
    stats = pstats.Stats(profiler, stream=stream)
    stats.sort_stats(pstats.SortKey.CUMULATIVE)
    stats.print_stats(40)

    buckets = _bucket_stats(stats)
    total_cum = sum(buckets.values()) or 1.0

    print(f"\nSolve wall time: {elapsed:.2f}s  candidates: {len(results)}")
    if results:
        print(f"Best: {results[0].word!r} score={results[0].score}")
    print("\nTime share (cumulative in solver package):")
    for name, _, _ in _PROFILE_BUCKETS:
        sec = buckets[name]
        pct = 100.0 * sec / total_cum
        print(f"  {name:20s} {sec:8.2f}s  ({pct:5.1f}%)")
    print(f"  {'other':20s} {buckets['other']:8.2f}s")
    print("\nTop 40 cumulative functions:")
    print(stream.getvalue())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "fixture",
        nargs="?",
        type=Path,
        default=DEFAULT_FIXTURE,
        help="Mismatch JSON with run_state_snapshot",
    )
    parser.add_argument(
        "--budget",
        type=float,
        default=8.0,
        help="search_time_budget_sec for this run",
    )
    parser.add_argument("--wordlist", type=Path, default=None)
    parser.add_argument(
        "--workers",
        default="1",
        help='search_workers: 1, 2-16, or "auto"',
    )
    args = parser.parse_args()
    if not args.fixture.exists():
        raise SystemExit(f"Fixture not found: {args.fixture}")
    run_profile(
        args.fixture,
        budget=args.budget,
        wordlist=args.wordlist,
        workers=args.workers,
    )


if __name__ == "__main__":
    main()
