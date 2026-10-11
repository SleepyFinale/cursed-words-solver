#!/usr/bin/env python3
"""Search quality on real boards: re-solve captured rounds and compare.

For each capture the pre-submit board is searched again with the current
engine (same budget / workers as the app) and the best score is compared with
the score of the word actually played and with the F8 suggestion at the time.

  python scripts/search_benchmark.py --latest 20               # newest 20 round logs
  python scripts/search_benchmark.py --since 20261010 --budget 30 --workers 8
  python scripts/search_benchmark.py tests/fixtures/captures/*.json

A row is a MISS when the played word scored more than the search found (the
search should have found it); --fail-on-miss exits non-zero for CI-style use.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main(argv: list[str] | None = None) -> int:
    from cursed_words_solver.config import GAME_WORDLIST_PATH, ROUND_LOG_DIR, ensure_wordlist
    from cursed_words_solver.dictionary import WordDictionary
    from cursed_words_solver.search import WordSearcher
    from cursed_words_solver.search_parallel import resolve_search_workers, shutdown_search_pool, warmup_search_pool
    from cursed_words_solver.sim.replay import prepare_replay

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="*", type=Path)
    parser.add_argument("--latest", type=int, default=0, help="newest N round logs")
    parser.add_argument("--since", help="round logs named YYYYMMDD... on or after this")
    parser.add_argument("--budget", type=float, default=20.0, help="search seconds per board")
    parser.add_argument("--workers", default="auto", help='worker processes ("auto" like the app, 1 = serial)')
    parser.add_argument("--fail-on-miss", action="store_true")
    args = parser.parse_args(argv)

    files = list(args.files)
    if args.latest or args.since:
        logs = sorted(p for p in ROUND_LOG_DIR.glob("2*.json"))
        if args.since:
            logs = [p for p in logs if p.name[:8] >= args.since]
        if args.latest:
            logs = logs[-args.latest :]
        files += logs
    if not files:
        parser.error("give capture files, --latest N or --since DATE")

    wordlist = GAME_WORDLIST_PATH if GAME_WORDLIST_PATH.exists() else ensure_wordlist()
    dictionary = WordDictionary(wordlist)
    workers = resolve_search_workers(args.workers)
    if workers > 1:
        warmup_search_pool(wordlist, workers)
    searcher = WordSearcher(dictionary=dictionary, min_len=1, max_len=25, time_budget=args.budget,
                            search_workers=workers, wordlist_path=wordlist)
    misses = better = equal = skipped = 0
    print(f"{'capture':<34} {'played':>22} {'F8 then':>10} {'search now':>24} {'s':>5}")
    try:
        for path in files:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                skipped += 1
                continue
            prep, _err = prepare_replay(data)
            if prep is None or prep.expected is None:
                skipped += 1
                continue
            played = prep.expected
            word = str((data.get("actual") or {}).get("word") or "")[:14]
            f8 = (data.get("solver") or {}).get("predicted_score")
            t0 = time.perf_counter()
            results = searcher.find_best_words(prep.board, prep.loadout, top_n=1)
            took = time.perf_counter() - t0
            best = int(results[0].score) if results else None
            best_word = results[0].word[:14] if results else "-"
            if prep.two_wrongs or best is None:
                verdict = ""
            elif best < played:
                verdict, misses = "MISS", misses + 1
            elif best > played:
                verdict, better = "better", better + 1
            else:
                verdict, equal = "same", equal + 1
            print(f"{path.name[:34]:<34} {word:>14} {played:>7} {str(f8 if f8 is not None else '-'):>10} "
                  f"{best_word:>14} {str(best):>9} {took:5.1f} {verdict}")
    finally:
        shutdown_search_pool()
    print(f"\n{better} better than played, {equal} same, {misses} MISS, {skipped} skipped")
    return 1 if (args.fail_on_miss and misses) else 0


if __name__ == "__main__":
    raise SystemExit(main())
