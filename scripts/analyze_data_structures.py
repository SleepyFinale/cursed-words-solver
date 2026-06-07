#!/usr/bin/env python3
"""Run data-structure optimization analysis from the organization reference plan.

Profiles chess-heavy and sticker-heavy fixtures, reports cache hit rates,
Board.flat access counts, and per-solve vs per-candidate recomputation notes.

Examples (from repo root):

  python scripts/analyze_data_structures.py
  python scripts/analyze_data_structures.py --budget 12
  python scripts/analyze_data_structures.py --json
"""

from __future__ import annotations

import argparse
import cProfile
import json
import pstats
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cursed_words_solver.config import GAME_WORDLIST_PATH, ensure_wordlist
from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.encounter_board import effective_board_for_loadout
from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.search import WordSearcher

CHESS_FIXTURES = [
    ROOT / "tests" / "fixtures" / "mismatches" / "20260525_172555.json",
    ROOT / "tests" / "fixtures" / "boards" / "20260529_styrofoams_king_check.json",
]
STICKER_FIXTURES = [
    ROOT / "tests" / "fixtures" / "boards" / "20260527_hayley_abacus.json",
    ROOT / "tests" / "fixtures" / "mismatches" / "20260526_231923.json",
]

PRECOMPUTE_AUDIT = [
    {
        "item": "build_solve_context(loadout)",
        "when": "per_solve",
        "where": "search.py find_best_words, search_parallel workers",
        "note": "Precomputes stamp_search_flags, hourglass, shield blue, compound percents once",
    },
    {
        "item": "ScoringPipeline._compute_state",
        "when": "per_candidate",
        "where": "rules/pipeline.py via score_total_only",
        "note": "Full wiki-order pipeline: tile init, pin, stickers L-R, stamps, boss",
    },
    {
        "item": "build_scoring_item_sequence",
        "when": "per_candidate",
        "where": "rules/pipeline.py _compute_state",
        "note": "Rebuilds grid-path + item order for every scored word",
    },
    {
        "item": "board_fingerprint(board)",
        "when": "per_chess_attack_lookup",
        "where": "rules/chess_tiles.py is_square_attacked cache key",
        "note": "Once per solve on chess boards; skipped when no chess pieces",
    },
    {
        "item": "loadout_mult_rules + build_mult_neighbor_hints",
        "when": "per_solve",
        "where": "search.py find_best_words start",
        "note": "Already precomputed once per F8",
    },
    {
        "item": "effective_board_for_loadout",
        "when": "per_solve",
        "where": "search.py find_best_words start",
        "note": "Scatter/grid simulation skipped when board_from_melmod",
    },
    {
        "item": "stickers.json catalog",
        "when": "per_process",
        "where": "lru_cache in boss_effects, stamp_behaviors, mult_search",
        "note": "Loaded once per Python process",
    },
    {
        "item": "rank_score_for_word + optimistic_mult_factor",
        "when": "per_candidate_miss",
        "where": "search.py _rank_score_for_candidate",
        "note": "Extra work after score_total_only on cache miss",
    },
]


@dataclass
class AnalysisRow:
    label: str
    category: str
    wall_sec: float
    score_pct: float
    score_calls: int
    dfs_expansions: int
    sticker_count: int
    score_cache_hit_pct: float
    dict_path_cache_hit_pct: float
    chess_attack_cache_hit_pct: float
    board_flat_calls: int
    board_flat_cum_sec: float
    trie_steps: int
    trie_prunes: int
    trie_fast_accepts: int
    dfs_bb_prunes: int
    dfs_bb_calls: int
    best_word: str
    best_score: float
    dominant_phase: str


def _hit_pct(hits: int, misses: int) -> float:
    total = hits + misses
    return 100.0 * hits / total if total else 0.0


def _load_fixture(path: Path) -> tuple:
    from tests.regression.test_scoring_mismatches import _run_state_for_replay

    data = json.loads(path.read_text(encoding="utf-8"))
    if "run_state_snapshot" in data:
        run_state = _run_state_for_replay(data)
    elif isinstance(data.get("board"), dict):
        run_state = data
    else:
        run_state = data.get("run_state") or data
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    if board is None:
        raise ValueError(f"No board in {path}")
    pipeline = ScoringPipeline()
    board = effective_board_for_loadout(board, loadout, pipeline.rules)
    return board, loadout


def _profile_board_flat(board, loadout, *, dictionary, wordlist_path, budget) -> float:
    """Return cumulative seconds in Board.flat via cProfile."""
    searcher = WordSearcher(
        dictionary=dictionary,
        min_len=1,
        max_len=25,
        time_budget=budget,
        wordlist_path=wordlist_path,
        search_workers=1,
    )
    profiler = cProfile.Profile()
    profiler.enable()
    searcher.find_best_words(board, loadout, top_n=1)
    profiler.disable()
    stats = pstats.Stats(profiler)
    flat_sec = 0.0
    for func, (_, _, _, cumtime, _) in stats.stats.items():
        if func[2] == "flat" and "models.py" in func[0].replace("\\", "/"):
            flat_sec += cumtime
    return flat_sec


def _run_one(
    label: str,
    category: str,
    board,
    loadout,
    *,
    dictionary: WordDictionary,
    wordlist_path: Path,
    budget: float,
    profile_flat: bool,
) -> AnalysisRow:
    searcher = WordSearcher(
        dictionary=dictionary,
        min_len=1,
        max_len=25,
        time_budget=budget,
        wordlist_path=wordlist_path,
        search_workers=1,
    )
    t0 = time.perf_counter()
    results = searcher.find_best_words(board, loadout, top_n=3)
    elapsed = time.perf_counter() - t0
    timing = searcher.last_search_timing
    if timing is None:
        raise RuntimeError("SearchTiming missing")

    total_score = timing.score_sec + timing.final_score_sec
    score_pct = 100.0 * total_score / elapsed if elapsed > 0 else 0.0
    explore_pct = 100.0 * max(0.0, elapsed - total_score) / elapsed if elapsed else 0.0
    dominant = "scoring" if score_pct >= explore_pct else "dfs_exploration"

    flat_sec = 0.0
    if profile_flat:
        flat_sec = _profile_board_flat(
            board,
            loadout,
            dictionary=dictionary,
            wordlist_path=wordlist_path,
            budget=budget,
        )

    sticker_count = len(loadout.stickers) + len(loadout.stamps)
    return AnalysisRow(
        label=label,
        category=category,
        wall_sec=elapsed,
        score_pct=score_pct,
        score_calls=timing.score_calls,
        dfs_expansions=timing.dfs_expansions,
        sticker_count=sticker_count,
        score_cache_hit_pct=_hit_pct(
            timing.score_cache_hits, timing.score_cache_misses
        ),
        dict_path_cache_hit_pct=_hit_pct(
            timing.dict_path_cache_hits, timing.dict_path_cache_misses
        ),
        chess_attack_cache_hit_pct=_hit_pct(
            timing.chess_attack_cache_hits, timing.chess_attack_cache_misses
        ),
        board_flat_calls=timing.board_flat_calls,
        board_flat_cum_sec=flat_sec,
        trie_steps=timing.trie_steps,
        trie_prunes=timing.trie_prunes,
        trie_fast_accepts=timing.trie_fast_accepts,
        dfs_bb_prunes=timing.dfs_bb_prunes,
        dfs_bb_calls=timing.dfs_bb_calls,
        best_word=results[0].word if results else "",
        best_score=results[0].score if results else 0.0,
        dominant_phase=dominant,
    )


def _print_report(rows: list[AnalysisRow]) -> None:
    print("=" * 72)
    print("1. HOT-PATH PROFILE (scoring vs DFS)")
    print("=" * 72)
    print(
        f"{'fixture':<32} {'cat':<8} {'wall':>6} {'score%':>7} "
        f"{'calls':>7} {'expand':>8} {'dominant':>12}"
    )
    print("-" * 72)
    for r in rows:
        print(
            f"{r.label:<32} {r.category:<8} {r.wall_sec:6.2f}s {r.score_pct:6.1f}% "
            f"{r.score_calls:7d} {r.dfs_expansions:8d} {r.dominant_phase:>12}"
        )

    print()
    print("=" * 72)
    print("2. CACHE HIT RATES")
    print("=" * 72)
    print(
        f"{'fixture':<32} {'score%':>7} {'dict%':>7} {'chess%':>7} "
        f"{'flat_calls':>10} {'flat_sec':>8}"
    )
    print("-" * 72)
    for r in rows:
        print(
            f"{r.label:<32} {r.score_cache_hit_pct:6.1f}% "
            f"{r.dict_path_cache_hit_pct:6.1f}% {r.chess_attack_cache_hit_pct:6.1f}% "
            f"{r.board_flat_calls:10d} {r.board_flat_cum_sec:7.3f}s"
        )

    print()
    print("=" * 72)
    print("2b. TRIE PREFIX PRUNING")
    print("=" * 72)
    print(
        f"{'fixture':<32} {'steps':>10} {'prunes':>10} {'fast_acc':>10} "
        f"{'bb_prune':>10} {'expand':>10}"
    )
    print("-" * 72)
    for r in rows:
        print(
            f"{r.label:<32} {r.trie_steps:10d} {r.trie_prunes:10d} "
            f"{r.trie_fast_accepts:10d} {r.dfs_bb_prunes:10d} "
            f"{r.dfs_expansions:10d}"
        )

    print()
    print("=" * 72)
    print("3. PER-SOLVE VS PER-CANDIDATE RECOMPUTATIONS")
    print("=" * 72)
    for entry in PRECOMPUTE_AUDIT:
        print(f"  [{entry['when']}] {entry['item']}")
        print(f"    {entry['where']}")
        print(f"    {entry['note']}")
        print()

    chess_rows = [r for r in rows if r.category == "chess"]
    sticker_rows = [r for r in rows if r.category == "sticker"]
    avg_chess_score = (
        sum(r.score_pct for r in chess_rows) / len(chess_rows) if chess_rows else 0
    )
    avg_sticker_score = (
        sum(r.score_pct for r in sticker_rows) / len(sticker_rows)
        if sticker_rows
        else 0
    )
    avg_flat_pct = []
    for r in rows:
        if r.wall_sec > 0 and r.board_flat_cum_sec > 0:
            avg_flat_pct.append(100.0 * r.board_flat_cum_sec / r.wall_sec)
    flat_share = sum(avg_flat_pct) / len(avg_flat_pct) if avg_flat_pct else 0.0

    print("=" * 72)
    print("4. SUMMARY & RECOMMENDATIONS")
    print("=" * 72)
    print(f"  Chess-heavy avg score time:    {avg_chess_score:.1f}% of wall")
    print(f"  Sticker-heavy avg score time: {avg_sticker_score:.1f}% of wall")
    print(f"  Board.flat cProfile share:     ~{flat_share:.2f}% of wall (avg)")
    print()
    if avg_sticker_score >= 55:
        print("  -> Sticker-heavy boards: scoring dominates; optimize pipeline precompute")
    elif avg_chess_score < 40:
        print("  -> Chess-heavy boards: DFS dominates; chess cache + neighbor gen matter")
    else:
        print("  -> Mixed profile: tune per board type")
    if flat_share < 1.0:
        print("  -> Board.flat allocation is negligible vs scoring/DFS; skip caching flat")
    else:
        print("  -> Board.flat has measurable cost; consider cached flat list per solve")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--budget", type=float, default=12.0)
    parser.add_argument("--wordlist", type=Path, default=None)
    parser.add_argument(
        "--skip-flat-profile",
        action="store_true",
        help="Skip second cProfile pass for Board.flat (faster)",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    wl = args.wordlist or (
        GAME_WORDLIST_PATH if GAME_WORDLIST_PATH.exists() else ensure_wordlist()
    )
    dictionary = WordDictionary(wl)
    rows: list[AnalysisRow] = []

    cases = (
        [(p, "chess") for p in CHESS_FIXTURES if p.exists()]
        + [(p, "sticker") for p in STICKER_FIXTURES if p.exists()]
    )
    if not cases:
        raise SystemExit("No analysis fixtures found")

    for path, category in cases:
        print(f"Analyzing {path.name} ({category})...", file=sys.stderr)
        board, loadout = _load_fixture(path)
        row = _run_one(
            path.stem,
            category,
            board,
            loadout,
            dictionary=dictionary,
            wordlist_path=wl,
            budget=args.budget,
            profile_flat=not args.skip_flat_profile,
        )
        rows.append(row)

    if args.json:
        print(
            json.dumps(
                {
                    "rows": [asdict(r) for r in rows],
                    "precompute_audit": PRECOMPUTE_AUDIT,
                },
                indent=2,
            )
        )
    else:
        _print_report(rows)


if __name__ == "__main__":
    main()
