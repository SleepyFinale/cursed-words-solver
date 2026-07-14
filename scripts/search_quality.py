#!/usr/bin/env python3
"""Search quality harness: budgeted vs long-run score gap (miss_gap).

Reports how often the normal-budget solver misses a higher-scoring path that a
longer budget (or alternate engine) finds. No persistent/learned state — report only.

Examples (from repo root):

  python scripts/search_quality.py
  python scripts/search_quality.py --budget 12 --long-budget 60
  python scripts/search_quality.py --engine beam --ab
  python scripts/search_quality.py tests/fixtures/mismatches/20260525_172555.json
  python scripts/search_quality.py --latest 6 --budget 15
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.models import CurseType, TileColor
from cursed_words_solver.search import WordSearcher

from scripts.search_profile_common import (
    ROOT as _ROOT,
    collect_fixture_paths,
    default_budget_from_config,
    load_fixture_auto,
    resolve_wordlist,
)

HARD_DEFAULT_FIXTURES = [
    _ROOT / "tests" / "fixtures" / "mismatches" / "20260525_172555.json",  # chess
    _ROOT / "tests" / "fixtures" / "mismatches" / "20260526_231923.json",  # hanafuda
    _ROOT / "tests" / "fixtures" / "mismatches" / "20260607_131029.json",  # number
    _ROOT / "tests" / "fixtures" / "mismatches" / "ayms_board_snapshot.json",
]


@dataclass
class QualityRow:
    label: str
    engine_a: str
    budget_a: float
    score_a: float
    word_a: str
    wall_a: float
    engine_b: str
    budget_b: float
    score_b: float
    word_b: str
    wall_b: float
    miss_gap: float
    items_on_a: int
    items_on_b: int
    chess_start_a: bool
    chess_start_b: bool
    wildcards_on_a: int
    wildcards_on_b: int


def _path_geometry(board, path: list[int]) -> dict:
    items = 0
    wildcards = 0
    chess_start = False
    if not path:
        return {
            "items": 0,
            "wildcards": 0,
            "chess_start": False,
        }
    for i, idx in enumerate(path):
        tile = board.get_by_index(idx)
        if tile.curse == CurseType.ITEM:
            items += 1
        if tile.curse == CurseType.WILDCARD or (
            tile.color == TileColor.WHITE and tile.curse == CurseType.LETTER
        ):
            wildcards += 1
        if i == 0 and str(tile.curse.value).startswith("chess"):
            chess_start = True
    return {
        "items": items,
        "wildcards": wildcards,
        "chess_start": chess_start,
    }


def _run_search(
    searcher: WordSearcher,
    board,
    loadout,
    *,
    budget: float,
    engine: str,
) -> tuple[float, str, list[int], float]:
    searcher.time_budget = budget
    searcher.use_beam_search = engine == "beam"
    t0 = time.perf_counter()
    results = searcher.find_best_words(board, loadout=loadout, top_n=1)
    wall = time.perf_counter() - t0
    if not results:
        return 0.0, "", [], wall
    best = results[0]
    return float(best.score), best.word, list(best.path), wall


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path, help="Fixture JSON paths")
    parser.add_argument("--latest", type=int, default=0, help="Newest N mismatches")
    parser.add_argument(
        "--budget",
        type=float,
        default=None,
        help="Normal budget seconds (default: config or 12)",
    )
    parser.add_argument(
        "--long-budget",
        type=float,
        default=None,
        help="Long / oracle budget (default: 4x budget, min 48)",
    )
    parser.add_argument(
        "--use-config-budget",
        action="store_true",
        help="Use config search_time_budget_sec as --budget",
    )
    parser.add_argument(
        "--engine",
        choices=("dfs", "beam"),
        default="dfs",
        help="Engine for budgeted pass A (default dfs)",
    )
    parser.add_argument(
        "--long-engine",
        choices=("dfs", "beam", "same"),
        default="same",
        help="Engine for long pass B (default: same as --engine)",
    )
    parser.add_argument(
        "--ab",
        action="store_true",
        help="A/B equal-budget: engine A vs the other engine (miss_gap = B-A)",
    )
    parser.add_argument("--wordlist", type=Path, default=None)
    args = parser.parse_args()

    budget = args.budget
    if budget is None:
        budget = (
            default_budget_from_config(12.0)
            if args.use_config_budget
            else 12.0
        )
    long_budget = args.long_budget
    if long_budget is None:
        long_budget = max(48.0, budget * 4.0)

    engine_a = args.engine
    if args.ab:
        engine_b = "beam" if engine_a == "dfs" else "dfs"
        budget_b = budget
    else:
        engine_b = engine_a if args.long_engine == "same" else args.long_engine
        budget_b = long_budget

    mismatches = _ROOT / "tests" / "fixtures" / "mismatches"
    paths = collect_fixture_paths(
        paths=list(args.paths),
        count=args.latest,
        mismatches_dir=mismatches,
        default_fixtures=HARD_DEFAULT_FIXTURES,
    )
    if not paths:
        print("No fixtures found.", file=sys.stderr)
        return 1

    wordlist = resolve_wordlist(args.wordlist)
    dictionary = WordDictionary(wordlist)
    searcher = WordSearcher(
        dictionary=dictionary,
        time_budget=budget,
        wordlist_path=wordlist,
        search_workers=1,
    )

    rows: list[QualityRow] = []
    print(
        f"{'label':<28} {'engA':<5} {'scA':>8} {'engB':<5} {'scB':>8} "
        f"{'gap':>8} {'wA':>6} {'wB':>6}"
    )
    print("-" * 90)

    for path in paths:
        try:
            board, loadout, label = load_fixture_auto(path)
        except Exception as exc:  # noqa: BLE001 — harness should continue
            print(f"{path.name:<28} ERROR {exc}", file=sys.stderr)
            continue

        score_a, word_a, path_a, wall_a = _run_search(
            searcher, board, loadout, budget=budget, engine=engine_a
        )
        score_b, word_b, path_b, wall_b = _run_search(
            searcher, board, loadout, budget=budget_b, engine=engine_b
        )
        geo_a = _path_geometry(board, path_a)
        geo_b = _path_geometry(board, path_b)
        gap = score_b - score_a
        row = QualityRow(
            label=label[:28],
            engine_a=engine_a,
            budget_a=budget,
            score_a=score_a,
            word_a=word_a,
            wall_a=wall_a,
            engine_b=engine_b,
            budget_b=budget_b,
            score_b=score_b,
            word_b=word_b,
            wall_b=wall_b,
            miss_gap=gap,
            items_on_a=geo_a["items"],
            items_on_b=geo_b["items"],
            chess_start_a=geo_a["chess_start"],
            chess_start_b=geo_b["chess_start"],
            wildcards_on_a=geo_a["wildcards"],
            wildcards_on_b=geo_b["wildcards"],
        )
        rows.append(row)
        print(
            f"{row.label:<28} {row.engine_a:<5} {row.score_a:8.1f} "
            f"{row.engine_b:<5} {row.score_b:8.1f} {row.miss_gap:8.1f} "
            f"{wall_a:6.1f} {wall_b:6.1f}"
        )
        if gap > 0.5:
            print(
                f"  miss: {word_a!r} -> {word_b!r}  "
                f"items {geo_a['items']}->{geo_b['items']}  "
                f"chess_start {geo_a['chess_start']}->{geo_b['chess_start']}  "
                f"wild {geo_a['wildcards']}->{geo_b['wildcards']}"
            )

    if not rows:
        return 1

    gaps = [r.miss_gap for r in rows]
    positive = sum(1 for g in gaps if g > 0.5)
    print("-" * 90)
    print(
        f"fixtures={len(rows)}  miss_count={positive}  "
        f"mean_gap={sum(gaps)/len(gaps):.1f}  "
        f"max_gap={max(gaps):.1f}  "
        f"A={engine_a}@{budget:g}s  B={engine_b}@{budget_b:g}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
