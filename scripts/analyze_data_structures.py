#!/usr/bin/env python3
"""Run data-structure optimization analysis from the organization reference plan.

Profiles representative fixtures by category, reports full SearchTiming counters,
per-solve context build metrics, cache hit rates, and optimization gating.

Examples (from repo root):

  python scripts/analyze_data_structures.py
  python scripts/analyze_data_structures.py --budget 12
  python scripts/analyze_data_structures.py --json
  python scripts/analyze_data_structures.py --write-doc
  python scripts/analyze_data_structures.py --latest 4 --category chess
  python scripts/analyze_data_structures.py --profile-flat
"""

from __future__ import annotations

import argparse
import cProfile
import json
import pstats
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cursed_words_solver.board_scoring_context import build_board_scoring_context
from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.encounter_board import effective_board_for_loadout
from cursed_words_solver.fast_rank import (
    loadout_allows_dfs_bb,
    loadout_allows_fast_rank,
    loadout_allows_tier2_screen,
    loadout_allows_tier2_two_phase,
)
from cursed_words_solver.graph_bitboard import build_board_graph_context
from cursed_words_solver.models import Loadout
from cursed_words_solver.mult_search import loadout_mult_rules
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.scoring_conditions import is_number_like_tile
from cursed_words_solver.search import SearchTiming, WordSearcher, _active_indices
from cursed_words_solver.solve_context import build_solve_context, hanafuda_sticker_level

from scripts.search_profile_common import (
    ROOT as _ROOT,
    collect_fixture_paths,
    collect_round_log_paths,
    default_budget_from_config,
    hit_pct,
    load_fixture_auto,
    resolve_wordlist,
)

DEFAULT_FIXTURES_BY_CATEGORY: dict[str, list[Path]] = {
    "chess": [
        _ROOT / "tests" / "fixtures" / "mismatches" / "20260525_172555.json",
        _ROOT / "tests" / "fixtures" / "boards" / "20260529_styrofoams_king_check.json",
    ],
    "sticker": [
        _ROOT / "tests" / "fixtures" / "boards" / "20260527_hayley_abacus.json",
        _ROOT / "tests" / "fixtures" / "mismatches" / "20260526_231923.json",
    ],
    "hanafuda": [
        _ROOT / "tests" / "fixtures" / "mismatches" / "20260526_231158.json",
    ],
    "number": [
        _ROOT / "tests" / "fixtures" / "mismatches" / "20260607_131029.json",
    ],
    "boss": [
        _ROOT / "tests" / "fixtures" / "mismatches" / "20260524_235240.json",
    ],
}

PRECOMPUTE_AUDIT = [
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
        "item": "build_solve_context(loadout)",
        "when": "per_solve",
        "where": "search.py find_best_words, search_parallel workers",
        "note": "Precomputes stamp flags, hourglass, shield blue, boss rules, inventory_refs, sticker/stamp slot order, grid_tile_multiply_first",
    },
    {
        "item": "build_board_graph_context(board)",
        "when": "per_solve",
        "where": "search.py find_best_words, search_parallel workers",
        "note": "Precomputes hanafuda_suit_mask, grid_base_score, coloured_tile_count, chess masks",
    },
    {
        "item": "build_board_scoring_context(...)",
        "when": "per_solve",
        "where": "search.py find_best_words, search_parallel workers",
        "note": "Cell target bitmasks, static sticker/stamp specs, use_split_pipeline",
    },
    {
        "item": "ScoringPipeline._compute_state",
        "when": "per_candidate",
        "where": "rules/pipeline.py via score_total_only",
        "note": "Full wiki-order pipeline (receives cached SolveContext + BoardGraphContext + BoardScoringContext)",
    },
    {
        "item": "path_grid_item_refs",
        "when": "per_path_cached",
        "where": "WordSearcher._grid_refs_cache per solve",
        "note": "Grid scatter refs cached per path; hourglass reversal applied in _compute_state",
    },
    {
        "item": "build_scoring_item_sequence",
        "when": "per_solve / tests",
        "where": "mult_search loadout_mult_rules",
        "note": "Inventory from SolveContext; grid refs from per-path cache; not _compute_state hot path",
    },
    {
        "item": "Tier-2 two-phase scoring",
        "when": "per_candidate",
        "where": "search.py score path",
        "note": "Phase 1 bounds screen/defer; phase 2 _compute_state only for survivors",
    },
    {
        "item": "board_fingerprint(board)",
        "when": "per_solve (chess boards)",
        "where": "clear_chess_attack_cache in find_best_words",
        "note": "Computed once; skipped when BoardGraphContext.has_chess_pieces is false",
    },
    {
        "item": "unused_cards_on_board",
        "when": "per_candidate",
        "where": "Hanafuda scoring",
        "note": "Uses hanafuda_suit_mask bitmask + path-only edge cases (no board.flat)",
    },
    {
        "item": "rank_score_for_word + optimistic_mult_factor",
        "when": "per_candidate_miss",
        "where": "search.py _rank_score_for_candidate",
        "note": "Extra work after score_total_only on cache miss",
    },
]


@dataclass
class ContextBuildProfile:
    context_build_sec: float = 0.0
    solve_ctx_sec: float = 0.0
    graph_ctx_sec: float = 0.0
    board_scoring_ctx_sec: float = 0.0
    mult_rules_sec: float = 0.0
    inventory_ref_count: int = 0
    static_rule_count: int = 0
    cell_mask_count: int = 0
    active_mask_popcount: int = 0
    chess_piece_mask_popcount: int = 0
    use_split_pipeline: bool = False


@dataclass
class OptimizationGates:
    fast_rank: bool = False
    tier2_screen: bool = False
    tier2_two_phase: bool = False
    dfs_bb: bool = False


@dataclass
class AnalysisRow:
    label: str
    category: str
    wall_sec: float
    score_pct: float
    dfs_pct: float
    extend_pct: float
    chess_pct: float
    seed_pct: float
    setup_rank_pct: float
    mult_rank_pct: float
    tier2_screen_pct: float
    score_calls: int
    dfs_expansions: int
    sticker_count: int
    stamp_count: int
    mult_rule_count: int
    has_chess_pieces: bool
    has_number_tiles: bool
    hanafuda_level: int
    boss_id: str
    score_cache_hit_pct: float
    dict_path_cache_hit_pct: float
    chess_attack_cache_hit_pct: float
    grid_refs_cache_hit_pct: float
    board_flat_calls: int
    board_flat_cum_sec: float
    trie_steps: int
    trie_prunes: int
    trie_fast_accepts: int
    dfs_bb_prunes: int
    dfs_bb_calls: int
    tier2_screen_skips: int
    tier2_screen_calls: int
    tier2_rank_screen_skips: int
    tier2_phase1_calls: int
    tier2_phase2_calls: int
    tier2_phase2_deferred: int
    tier2_recommendation: str
    score_calls_per_expansion: float
    trie_prune_rate: float
    tier2_skip_rate: float
    dict_resolve_per_score_call: float
    best_word: str
    best_score: float
    dominant_phase: str
    context: ContextBuildProfile = field(default_factory=ContextBuildProfile)
    gates: OptimizationGates = field(default_factory=OptimizationGates)


@dataclass
class RunMetadata:
    budget: float
    wordlist: str
    workers: int
    timestamp: str
    fixture_count: int
    categories: dict[str, int]


def _pct_of_wall(sec: float, wall: float) -> float:
    return 100.0 * sec / wall if wall > 0 else 0.0


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator > 0 else 0.0


def context_build_profile(board, loadout) -> ContextBuildProfile:
    pipeline = ScoringPipeline()
    rules = pipeline.rules
    board = effective_board_for_loadout(board, loadout, rules)
    active = _active_indices(board)

    t_total = time.perf_counter()

    t0 = time.perf_counter()
    solve_ctx = build_solve_context(loadout, rules)
    solve_sec = time.perf_counter() - t0

    t0 = time.perf_counter()
    graph_ctx = build_board_graph_context(board)
    graph_sec = time.perf_counter() - t0

    t0 = time.perf_counter()
    board_scoring_ctx = build_board_scoring_context(
        board, loadout, solve_ctx, graph_ctx, rules
    )
    board_scoring_sec = time.perf_counter() - t0

    t0 = time.perf_counter()
    mult_rules = loadout_mult_rules(
        loadout,
        rules,
        board=board,
        path=[active[0]] if active else [],
        solve_context=solve_ctx,
    )
    mult_sec = time.perf_counter() - t0

    total_sec = time.perf_counter() - t_total
    static_count = len(board_scoring_ctx.static_sticker_specs) + len(
        board_scoring_ctx.static_stamp_specs
    )

    return ContextBuildProfile(
        context_build_sec=total_sec,
        solve_ctx_sec=solve_sec,
        graph_ctx_sec=graph_sec,
        board_scoring_ctx_sec=board_scoring_sec,
        mult_rules_sec=mult_sec,
        inventory_ref_count=len(solve_ctx.inventory_refs),
        static_rule_count=static_count,
        cell_mask_count=len(board_scoring_ctx.cell_masks),
        active_mask_popcount=graph_ctx.active_mask.bit_count(),
        chess_piece_mask_popcount=graph_ctx.chess_piece_mask.bit_count(),
        use_split_pipeline=board_scoring_ctx.use_split_pipeline,
    )


def optimization_gates(board, loadout) -> OptimizationGates:
    pipeline = ScoringPipeline()
    rules = pipeline.rules
    board = effective_board_for_loadout(board, loadout, rules)
    solve_ctx = build_solve_context(loadout, rules)
    graph_ctx = build_board_graph_context(board)
    has_number = any(is_number_like_tile(t) for t in board.flat)
    return OptimizationGates(
        fast_rank=loadout_allows_fast_rank(loadout),
        tier2_screen=loadout_allows_tier2_screen(solve_ctx, loadout),
        tier2_two_phase=loadout_allows_tier2_two_phase(solve_ctx, loadout),
        dfs_bb=loadout_allows_dfs_bb(
            solve_ctx,
            loadout,
            has_number_tiles=has_number,
            has_chess_pieces=graph_ctx.has_chess_pieces,
        ),
    )


def board_features(board, loadout) -> dict:
    pipeline = ScoringPipeline()
    board_eff = effective_board_for_loadout(board, loadout, pipeline.rules)
    graph_ctx = build_board_graph_context(board_eff)
    mult_rules = loadout_mult_rules(
        loadout,
        pipeline.rules,
        board=board_eff,
        path=[_active_indices(board_eff)[0]] if _active_indices(board_eff) else [],
        solve_context=build_solve_context(loadout, pipeline.rules),
    )
    return {
        "sticker_count": len(loadout.stickers),
        "stamp_count": len(loadout.stamps),
        "mult_rule_count": len(mult_rules),
        "has_chess_pieces": graph_ctx.has_chess_pieces,
        "has_number_tiles": any(is_number_like_tile(t) for t in board_eff.flat),
        "hanafuda_level": hanafuda_sticker_level(loadout),
        "boss_id": (loadout.boss_id or "").strip(),
    }


def profile_board_flat_cum_sec(
    board,
    loadout,
    *,
    dictionary: WordDictionary,
    wordlist_path: Path,
    budget: float,
    workers: int,
) -> float:
    """Return cumulative seconds in Board.flat via cProfile (extra search pass)."""
    from cursed_words_solver.search_parallel import resolve_search_workers

    searcher = WordSearcher(
        dictionary=dictionary,
        min_len=1,
        max_len=25,
        time_budget=budget,
        wordlist_path=wordlist_path,
        search_workers=resolve_search_workers(workers),
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


def build_analysis_row(
    label: str,
    category: str,
    board,
    loadout,
    results,
    timing: SearchTiming,
    *,
    elapsed: float,
    context: ContextBuildProfile,
    gates: OptimizationGates,
    features: dict,
    profile_flat: bool = False,
    dictionary: WordDictionary | None = None,
    wordlist_path: Path | None = None,
    budget: float = 12.0,
    workers: int = 1,
) -> AnalysisRow:
    total_score = timing.score_sec + timing.final_score_sec
    score_pct = _pct_of_wall(total_score, elapsed)
    explore_pct = 100.0 * max(0.0, elapsed - total_score) / elapsed if elapsed else 0.0
    dominant = "scoring" if score_pct >= explore_pct else "dfs_exploration"

    sticker_total = features["sticker_count"] + features["stamp_count"]
    rec_timing = SearchTiming(
        wall_sec=timing.wall_sec or elapsed,
        score_sec=total_score,
        score_calls=timing.score_calls,
    )
    tier2_rec = rec_timing.tier2_recommendation(sticker_count=sticker_total)

    flat_sec = 0.0
    if profile_flat and dictionary is not None and wordlist_path is not None:
        flat_sec = profile_board_flat_cum_sec(
            board,
            loadout,
            dictionary=dictionary,
            wordlist_path=wordlist_path,
            budget=budget,
            workers=workers,
        )

    dict_misses = timing.dict_path_cache_misses
    tier2_calls = timing.tier2_screen_calls

    return AnalysisRow(
        label=label,
        category=category,
        wall_sec=elapsed,
        score_pct=score_pct,
        dfs_pct=_pct_of_wall(timing.dfs_sec, elapsed),
        extend_pct=_pct_of_wall(timing.extend_sec, elapsed),
        chess_pct=_pct_of_wall(timing.chess_sec, elapsed),
        seed_pct=_pct_of_wall(timing.seed_sec, elapsed),
        setup_rank_pct=_pct_of_wall(timing.setup_rank_sec, elapsed),
        mult_rank_pct=_pct_of_wall(timing.mult_rank_sec, elapsed),
        tier2_screen_pct=_pct_of_wall(timing.tier2_screen_sec, elapsed),
        score_calls=timing.score_calls,
        dfs_expansions=timing.dfs_expansions,
        sticker_count=features["sticker_count"],
        stamp_count=features["stamp_count"],
        mult_rule_count=features["mult_rule_count"],
        has_chess_pieces=features["has_chess_pieces"],
        has_number_tiles=features["has_number_tiles"],
        hanafuda_level=features["hanafuda_level"],
        boss_id=features["boss_id"],
        score_cache_hit_pct=hit_pct(
            timing.score_cache_hits, timing.score_cache_misses
        ),
        dict_path_cache_hit_pct=hit_pct(
            timing.dict_path_cache_hits, timing.dict_path_cache_misses
        ),
        chess_attack_cache_hit_pct=hit_pct(
            timing.chess_attack_cache_hits, timing.chess_attack_cache_misses
        ),
        grid_refs_cache_hit_pct=hit_pct(
            timing.grid_refs_cache_hits, timing.grid_refs_cache_misses
        ),
        board_flat_calls=timing.board_flat_calls,
        board_flat_cum_sec=flat_sec,
        trie_steps=timing.trie_steps,
        trie_prunes=timing.trie_prunes,
        trie_fast_accepts=timing.trie_fast_accepts,
        dfs_bb_prunes=timing.dfs_bb_prunes,
        dfs_bb_calls=timing.dfs_bb_calls,
        tier2_screen_skips=timing.tier2_screen_skips,
        tier2_screen_calls=timing.tier2_screen_calls,
        tier2_rank_screen_skips=timing.tier2_rank_screen_skips,
        tier2_phase1_calls=timing.tier2_phase1_calls,
        tier2_phase2_calls=timing.tier2_phase2_calls,
        tier2_phase2_deferred=timing.tier2_phase2_deferred,
        tier2_recommendation=tier2_rec,
        score_calls_per_expansion=_rate(timing.score_calls, timing.dfs_expansions),
        trie_prune_rate=_rate(timing.trie_prunes, timing.trie_steps),
        tier2_skip_rate=_rate(timing.tier2_screen_skips, tier2_calls),
        dict_resolve_per_score_call=_rate(dict_misses, timing.score_calls),
        best_word=results[0].word if results else "",
        best_score=results[0].score if results else 0.0,
        dominant_phase=dominant,
        context=context,
        gates=gates,
    )


def run_one(
    label: str,
    category: str,
    board,
    loadout,
    *,
    dictionary: WordDictionary,
    wordlist_path: Path,
    budget: float,
    workers: int | str,
    top_n: int,
    profile_flat: bool,
) -> AnalysisRow:
    from cursed_words_solver.search_parallel import resolve_search_workers

    worker_count = resolve_search_workers(workers)
    context = context_build_profile(board, loadout)
    gates = optimization_gates(board, loadout)
    features = board_features(board, loadout)

    searcher = WordSearcher(
        dictionary=dictionary,
        min_len=1,
        max_len=25,
        time_budget=budget,
        wordlist_path=wordlist_path,
        search_workers=worker_count,
    )
    t0 = time.perf_counter()
    results = searcher.find_best_words(board, loadout, top_n=top_n)
    elapsed = time.perf_counter() - t0
    timing = searcher.last_search_timing
    if timing is None:
        raise RuntimeError("SearchTiming missing")

    return build_analysis_row(
        label,
        category,
        board,
        loadout,
        results,
        timing,
        elapsed=elapsed,
        context=context,
        gates=gates,
        features=features,
        profile_flat=profile_flat,
        dictionary=dictionary,
        wordlist_path=wordlist_path,
        budget=budget,
        workers=worker_count,
    )


def collect_default_cases(
    *,
    categories: list[str] | None = None,
) -> list[tuple[Path, str, str]]:
    cases: list[tuple[Path, str, str]] = []
    for category, paths in DEFAULT_FIXTURES_BY_CATEGORY.items():
        if categories and category not in categories:
            continue
        for path in paths:
            if path.exists():
                cases.append((path, category, path.stem))
    return cases


def collect_cases(
    *,
    paths: list[Path],
    latest: int,
    round_logs: bool,
    mismatches_only: bool,
    max_rounds: int,
    sample_every: int,
    categories: list[str] | None,
) -> list[tuple[Path | None, str, str, bool]]:
    """Return (path, category, label, is_round_log). path=None for synthetic."""
    if paths:
        return [(p, "custom", p.stem, False) for p in paths]
    if round_logs:
        log_paths = collect_round_log_paths(
            mismatches_only=mismatches_only,
            max_rounds=max_rounds,
            sample_every=max(1, sample_every),
        )
        return [(p, "round_log", p.stem, True) for p in log_paths]
    if latest > 0:
        latest_paths = collect_fixture_paths(
            paths=[],
            count=latest,
            mismatches_dir=_ROOT / "tests" / "fixtures" / "mismatches",
            default_fixtures=None,
        )
        return [(p, "latest", p.stem, False) for p in latest_paths]
    defaults = collect_default_cases(categories=categories)
    return [(p, cat, label, False) for p, cat, label in defaults]


def _category_counts(rows: list[AnalysisRow]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.category] = counts.get(row.category, 0) + 1
    return counts


def _summary_recommendations(rows: list[AnalysisRow]) -> list[str]:
    lines: list[str] = []
    by_cat: dict[str, list[AnalysisRow]] = {}
    for row in rows:
        by_cat.setdefault(row.category, []).append(row)

    for cat in ("chess", "sticker", "hanafuda", "number", "boss"):
        cat_rows = by_cat.get(cat, [])
        if cat_rows:
            avg = sum(r.score_pct for r in cat_rows) / len(cat_rows)
            lines.append(f"  {cat.capitalize()}-heavy avg score time: {avg:.1f}% of wall")

    flat_pcts = [
        100.0 * r.board_flat_cum_sec / r.wall_sec
        for r in rows
        if r.wall_sec > 0 and r.board_flat_cum_sec > 0
    ]
    if flat_pcts:
        flat_share = sum(flat_pcts) / len(flat_pcts)
        lines.append(f"  Board.flat cProfile share:     ~{flat_share:.2f}% of wall (avg)")
    else:
        lines.append(
            "  Board.flat: use board_flat_calls counter (run --profile-flat for cProfile share)"
        )

    chess_rows = by_cat.get("chess", [])
    sticker_rows = by_cat.get("sticker", [])
    avg_chess = (
        sum(r.score_pct for r in chess_rows) / len(chess_rows) if chess_rows else None
    )
    avg_sticker = (
        sum(r.score_pct for r in sticker_rows) / len(sticker_rows)
        if sticker_rows
        else None
    )

    if avg_sticker is not None and avg_sticker >= 55:
        lines.append(
            "  -> Sticker-heavy boards: scoring dominates; optimize pipeline precompute"
        )
    elif avg_chess is not None and avg_chess < 40:
        lines.append(
            "  -> Chess-heavy boards: DFS dominates; chess cache + neighbor gen matter"
        )
    else:
        lines.append("  -> Mixed profile: tune per board type")

    avg_flat_calls = sum(r.board_flat_calls for r in rows) / len(rows) if rows else 0
    if flat_pcts:
        flat_share = sum(flat_pcts) / len(flat_pcts)
        if flat_share < 1.0:
            lines.append(
                "  -> Board.flat allocation is negligible vs scoring/DFS; skip caching flat"
            )
        else:
            lines.append(
                "  -> Board.flat has measurable cost; consider cached flat list per solve"
            )
    elif avg_flat_calls <= 10:
        lines.append(
            f"  -> Board.flat calls low (avg {avg_flat_calls:.0f}); indexing fast-path is effective"
        )

    return lines


def print_report(rows: list[AnalysisRow], metadata: RunMetadata) -> None:
    print("=" * 80)
    print("RUN METADATA")
    print("=" * 80)
    print(f"  Timestamp:  {metadata.timestamp}")
    print(f"  Budget:     {metadata.budget}s")
    print(f"  Wordlist:   {metadata.wordlist}")
    print(f"  Workers:    {metadata.workers}")
    print(f"  Fixtures:   {metadata.fixture_count} ({metadata.categories})")
    print()

    print("=" * 80)
    print("1. HOT-PATH PROFILE (phase % of wall)")
    print("=" * 80)
    print(
        f"{'fixture':<28} {'cat':<8} {'wall':>6} {'score':>6} {'dfs':>6} "
        f"{'ext':>6} {'ch':>6} {'calls':>7} {'expand':>8} {'dom':>12}"
    )
    print("-" * 80)
    for r in rows:
        print(
            f"{r.label:<28} {r.category:<8} {r.wall_sec:6.2f}s "
            f"{r.score_pct:5.1f}% {r.dfs_pct:5.1f}% {r.extend_pct:5.1f}% "
            f"{r.chess_pct:5.1f}% {r.score_calls:7d} {r.dfs_expansions:8d} "
            f"{r.dominant_phase:>12}"
        )

    print()
    print("=" * 80)
    print("2. CACHE HIT RATES")
    print("=" * 80)
    print(
        f"{'fixture':<28} {'score':>6} {'dict':>6} {'chess':>6} {'grid':>6} "
        f"{'flat':>6} {'flat_sec':>8}"
    )
    print("-" * 80)
    for r in rows:
        print(
            f"{r.label:<28} {r.score_cache_hit_pct:5.1f}% "
            f"{r.dict_path_cache_hit_pct:5.1f}% {r.chess_attack_cache_hit_pct:5.1f}% "
            f"{r.grid_refs_cache_hit_pct:5.1f}% {r.board_flat_calls:6d} "
            f"{r.board_flat_cum_sec:8.3f}s"
        )

    print()
    print("=" * 80)
    print("3. TRIE + DFS PRUNING")
    print("=" * 80)
    print(
        f"{'fixture':<28} {'steps':>9} {'prunes':>9} {'fast':>8} "
        f"{'bb_pr':>8} {'bb_call':>8} {'expand':>9}"
    )
    print("-" * 80)
    for r in rows:
        print(
            f"{r.label:<28} {r.trie_steps:9d} {r.trie_prunes:9d} "
            f"{r.trie_fast_accepts:8d} {r.dfs_bb_prunes:8d} {r.dfs_bb_calls:8d} "
            f"{r.dfs_expansions:9d}"
        )

    print()
    print("=" * 80)
    print("4. TIER-2 TWO-PHASE")
    print("=" * 80)
    print(
        f"{'fixture':<28} {'skip':>7} {'calls':>7} {'p1':>7} {'p2':>7} "
        f"{'def':>7} {'t2%':>6} {'rec':>20}"
    )
    print("-" * 80)
    for r in rows:
        print(
            f"{r.label:<28} {r.tier2_screen_skips:7d} {r.tier2_screen_calls:7d} "
            f"{r.tier2_phase1_calls:7d} {r.tier2_phase2_calls:7d} "
            f"{r.tier2_phase2_deferred:7d} {r.tier2_screen_pct:5.1f}% "
            f"{r.tier2_recommendation:>20}"
        )

    print()
    print("=" * 80)
    print("5. CONTEXT PRECOMPUTE (per fixture)")
    print("=" * 80)
    print(
        f"{'fixture':<28} {'total':>7} {'solve':>7} {'graph':>7} {'board':>7} "
        f"{'mult':>7} {'inv':>5} {'static':>7} {'masks':>6}"
    )
    print("-" * 80)
    for r in rows:
        c = r.context
        print(
            f"{r.label:<28} {c.context_build_sec:7.3f}s {c.solve_ctx_sec:7.3f}s "
            f"{c.graph_ctx_sec:7.3f}s {c.board_scoring_ctx_sec:7.3f}s "
            f"{c.mult_rules_sec:7.3f}s {c.inventory_ref_count:5d} "
            f"{c.static_rule_count:7d} {c.cell_mask_count:6d}"
        )

    print()
    print("  Static precompute audit:")
    for entry in PRECOMPUTE_AUDIT:
        print(f"    [{entry['when']}] {entry['item']}")
        print(f"      {entry['note']}")

    print()
    print("=" * 80)
    print("6. OPTIMIZATION GATING")
    print("=" * 80)
    print(
        f"{'fixture':<28} {'fast':>5} {'t2scr':>6} {'t2ph':>5} {'dfsbb':>6} "
        f"{'stk':>4} {'chess':>6} {'num':>4} {'han':>4} {'boss':>8}"
    )
    print("-" * 80)
    for r in rows:
        g = r.gates
        print(
            f"{r.label:<28} {int(g.fast_rank):5d} {int(g.tier2_screen):6d} "
            f"{int(g.tier2_two_phase):5d} {int(g.dfs_bb):6d} "
            f"{r.sticker_count + r.stamp_count:4d} {int(r.has_chess_pieces):6d} "
            f"{int(r.has_number_tiles):4d} {r.hanafuda_level:4d} "
            f"{r.boss_id or '-':>8}"
        )

    print()
    print("=" * 80)
    print("7. DERIVED RATES")
    print("=" * 80)
    print(
        f"{'fixture':<28} {'sc/exp':>8} {'prune%':>8} {'t2skip%':>8} {'dict/sc':>8}"
    )
    print("-" * 80)
    for r in rows:
        print(
            f"{r.label:<28} {r.score_calls_per_expansion:8.4f} "
            f"{100.0 * r.trie_prune_rate:7.1f}% "
            f"{100.0 * r.tier2_skip_rate:7.1f}% "
            f"{r.dict_resolve_per_score_call:8.4f}"
        )

    print()
    print("=" * 80)
    print("8. SUMMARY & RECOMMENDATIONS")
    print("=" * 80)
    for line in _summary_recommendations(rows):
        print(line)
    print()


def _wordlist_label(wordlist_path: str) -> str:
    p = Path(wordlist_path)
    try:
        rel = p.relative_to(_ROOT)
        return str(rel).replace("\\", "/")
    except ValueError:
        name = p.name
        if name in ("game_words.txt", "enable1.txt"):
            return f"game/{name}"
        return name


def format_markdown_report(rows: list[AnalysisRow], metadata: RunMetadata) -> str:
    lines: list[str] = []
    wl_label = _wordlist_label(metadata.wordlist)
    lines.append("# Data Structure Analysis Results")
    lines.append("")
    lines.append(
        f"Generated from `scripts/analyze_data_structures.py` "
        f"({metadata.budget}s budget, {wl_label}, workers={metadata.workers})."
    )
    lines.append(f"Run at: {metadata.timestamp}")
    lines.append("")

    lines.append("## 1. Hot-path profile: scoring vs DFS")
    lines.append("")
    lines.append(
        "| Fixture | Category | Wall | Score % | DFS % | Extend % | Chess % | "
        "Score calls | DFS expansions | Dominant |"
    )
    lines.append(
        "|---------|----------|------|---------|-------|----------|---------|"
        "-------------|----------------|----------|"
    )
    for r in rows:
        lines.append(
            f"| {r.label} | {r.category} | {r.wall_sec:.1f}s | {r.score_pct:.1f}% | "
            f"{r.dfs_pct:.1f}% | {r.extend_pct:.1f}% | {r.chess_pct:.1f}% | "
            f"{r.score_calls:,} | {r.dfs_expansions:,} | {r.dominant_phase} |"
        )
    lines.append("")
    lines.append(
        "**Finding:** Wall time is split across DFS exploration, extension passes, "
        "chess/number work, and `score_total_only`. "
        "`SearchTiming.score_sec` tracks only `score_total_only` on the search hot path; "
        "other phase fields are separate."
    )
    lines.append("")
    lines.append(
        "See also [`SEARCH_ARCHITECTURE.md`](SEARCH_ARCHITECTURE.md) for the full "
        "context stack and optimization gating."
    )
    lines.append("")

    lines.append("### 1b. Tier-2 screening and DFS branch-and-bound")
    lines.append("")
    lines.append("| Fixture | t2 skips | t2 calls | phase1 | phase2 | deferred | bb prunes | bb calls |")
    lines.append("|---------|----------|----------|--------|--------|----------|-----------|----------|")
    for r in rows:
        lines.append(
            f"| {r.label} | {r.tier2_screen_skips} | {r.tier2_screen_calls} | "
            f"{r.tier2_phase1_calls} | {r.tier2_phase2_calls} | {r.tier2_phase2_deferred} | "
            f"{r.dfs_bb_prunes} | {r.dfs_bb_calls} |"
        )
    lines.append("")
    lines.append("| Counter | Meaning |")
    lines.append("| ------- | ------- |")
    lines.append("| `tier2_screen_skips` | Candidates whose upper bound cannot beat the heap |")
    lines.append("| `tier2_rank_screen_skips` | Additional rank-bound skips in phase 1 |")
    lines.append("| `tier2_phase1_calls` | Candidates screened in phase 1 |")
    lines.append("| `tier2_phase2_calls` | Deferred candidates fully scored in phase 2 |")
    lines.append("| `tier2_phase2_deferred` | Candidates deferred from phase 1 |")
    lines.append("| `dfs_bb_prunes` | DFS branches pruned by prefix upper bound |")
    lines.append("| `dfs_bb_calls` | Prefix bound evaluations during DFS |")
    lines.append("")

    lines.append("## 2. Cache hit rates")
    lines.append("")
    lines.append(
        "| Fixture | Score cache | Dict path cache | Chess attack cache | "
        "Grid refs cache | Board.flat calls |"
    )
    lines.append(
        "|---------|-------------|-----------------|--------------------|"
        "-----------------|------------------|"
    )
    for r in rows:
        lines.append(
            f"| {r.label} | {r.score_cache_hit_pct:.1f}% | "
            f"{r.dict_path_cache_hit_pct:.1f}% | {r.chess_attack_cache_hit_pct:.1f}% | "
            f"{r.grid_refs_cache_hit_pct:.1f}% | {r.board_flat_calls} |"
        )
    lines.append("")
    lines.append(
        "*Chess boards use once-per-solve `board_fingerprint` in attack cache keys; "
        "Hanafuda scoring uses precomputed `hanafuda_suit_mask`.*"
    )
    lines.append("")

    lines.append("## 3. Per-solve vs per-candidate recomputations")
    lines.append("")
    lines.append("| Item | When | Notes |")
    lines.append("|------|------|-------|")
    for entry in PRECOMPUTE_AUDIT:
        lines.append(f"| `{entry['item']}` | {entry['when']} | {entry['note']} |")
    lines.append("")
    lines.append("### Per-fixture context build timings")
    lines.append("")
    lines.append(
        "| Fixture | Total | Solve ctx | Graph ctx | Board scoring | Mult rules | "
        "Inventory refs | Static rules | Cell masks | Split pipeline |"
    )
    lines.append(
        "|---------|-------|-----------|-----------|---------------|------------|"
        "----------------|--------------|------------|----------------|"
    )
    for r in rows:
        c = r.context
        lines.append(
            f"| {r.label} | {c.context_build_sec:.3f}s | {c.solve_ctx_sec:.3f}s | "
            f"{c.graph_ctx_sec:.3f}s | {c.board_scoring_ctx_sec:.3f}s | "
            f"{c.mult_rules_sec:.3f}s | {c.inventory_ref_count} | {c.static_rule_count} | "
            f"{c.cell_mask_count} | {c.use_split_pipeline} |"
        )
    lines.append("")

    lines.append("## 4. Board.flat access cost")
    lines.append("")
    lines.append(
        "`Board.get_by_index()` indexes `tiles[row][col]` directly. "
        "`board_flat_calls` tracks direct `.flat` property access only."
    )
    lines.append("")
    lines.append("| Fixture | Board.flat calls | cProfile flat sec |")
    lines.append("|---------|------------------|-------------------|")
    for r in rows:
        flat_note = f"{r.board_flat_cum_sec:.3f}s" if r.board_flat_cum_sec > 0 else "—"
        lines.append(f"| {r.label} | {r.board_flat_calls} | {flat_note} |")
    lines.append("")

    lines.append("## 5. Optimization gating")
    lines.append("")
    lines.append(
        "| Fixture | fast_rank | tier2_screen | tier2_two_phase | dfs_bb | "
        "Stickers+stamps | Chess | Number | Hanafuda lvl | Boss |"
    )
    lines.append(
        "|---------|-----------|--------------|-----------------|--------|"
        "-----------------|-------|--------|--------------|------|"
    )
    for r in rows:
        g = r.gates
        lines.append(
            f"| {r.label} | {g.fast_rank} | {g.tier2_screen} | {g.tier2_two_phase} | "
            f"{g.dfs_bb} | {r.sticker_count + r.stamp_count} | {r.has_chess_pieces} | "
            f"{r.has_number_tiles} | {r.hanafuda_level} | {r.boss_id or '—'} |"
        )
    lines.append("")

    lines.append("## 6. Instrumentation")
    lines.append("")
    lines.append("`SearchTiming` reports score/dict/chess/grid_refs cache hits/misses, "
                 "board_flat_calls, trie steps/prunes/fast_accepts, tier-2 counters, "
                 "and dfs_bb prunes/calls.")
    lines.append("")
    lines.append("Run analysis:")
    lines.append("")
    lines.append("```bash")
    lines.append("python scripts/analyze_data_structures.py --budget 12")
    lines.append("python scripts/analyze_data_structures.py --write-doc")
    lines.append(
        "python scripts/profile_search.py tests/fixtures/mismatches/20260526_231923.json --budget 12"
    )
    lines.append("```")
    lines.append("")

    lines.append("## 7. Summary")
    lines.append("")
    for line in _summary_recommendations(rows):
        lines.append(line.lstrip())
    lines.append("")

    return "\n".join(lines)


def row_to_json_dict(row: AnalysisRow) -> dict:
    data = asdict(row)
    return data


def main() -> None:
    from cursed_words_solver.config import RUN_STATE_PATH
    from cursed_words_solver.search_parallel import resolve_search_workers

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Mismatch JSON, board JSON, or run_state JSON paths",
    )
    parser.add_argument(
        "--run-state",
        action="store_true",
        help=f"Analyze {RUN_STATE_PATH} from melmod",
    )
    parser.add_argument(
        "--latest",
        type=int,
        default=0,
        metavar="N",
        help="Analyze N newest tests/fixtures/mismatches/*.json",
    )
    parser.add_argument("--budget", type=float, default=12.0)
    parser.add_argument("--wordlist", type=Path, default=None)
    parser.add_argument("--workers", default="1")
    parser.add_argument("--top-n", type=int, default=3)
    parser.add_argument(
        "--category",
        action="append",
        choices=sorted(DEFAULT_FIXTURES_BY_CATEGORY.keys()),
        help="Filter default fixtures by category (repeatable)",
    )
    parser.add_argument(
        "--profile-flat",
        action="store_true",
        help="Run extra cProfile pass for Board.flat cumulative seconds (slow)",
    )
    parser.add_argument(
        "--skip-flat-profile",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--write-doc",
        nargs="?",
        const=str(_ROOT / "docs" / "DATA_STRUCTURE_ANALYSIS.md"),
        metavar="PATH",
        help="Write markdown report (default: docs/DATA_STRUCTURE_ANALYSIS.md)",
    )
    parser.add_argument(
        "--round-logs",
        action="store_true",
        help="Analyze boards from ~/.cursed_words_solver/round_logs/",
    )
    parser.add_argument("--mismatches-only", action="store_true")
    parser.add_argument("--max-rounds", type=int, default=0, metavar="N")
    parser.add_argument("--sample-every", type=int, default=1, metavar="K")
    parser.add_argument("--use-config-budget", action="store_true")
    args = parser.parse_args()

    profile_flat = args.profile_flat

    budget = (
        default_budget_from_config(args.budget)
        if args.use_config_budget
        else args.budget
    )
    workers = resolve_search_workers(args.workers)

    paths: list[Path] = list(args.paths)
    if args.run_state:
        if not RUN_STATE_PATH.exists():
            raise SystemExit(f"run_state not found: {RUN_STATE_PATH}")
        paths = [RUN_STATE_PATH]

    cases = collect_cases(
        paths=paths,
        latest=args.latest if not args.run_state else 0,
        round_logs=args.round_logs and not args.run_state,
        mismatches_only=args.mismatches_only,
        max_rounds=args.max_rounds,
        sample_every=max(1, args.sample_every),
        categories=args.category,
    )
    if not cases:
        raise SystemExit("No analysis fixtures found")

    wl = resolve_wordlist(args.wordlist)
    dictionary = WordDictionary(wl)
    rows: list[AnalysisRow] = []

    for path, category, label, is_round_log in cases:
        if path is not None and not path.exists():
            print(f"skip (missing): {path}", file=sys.stderr)
            continue
        try:
            if path is None:
                continue
            board, loadout, loaded_label = load_fixture_auto(path, round_log=is_round_log)
            if loaded_label:
                label = loaded_label.removesuffix(".json")
        except Exception as exc:
            name = path.name if path else label
            print(f"skip ({name}): {exc}", file=sys.stderr)
            continue
        print(f"Analyzing {label} ({category})...", file=sys.stderr)
        row = run_one(
            label,
            category,
            board,
            loadout,
            dictionary=dictionary,
            wordlist_path=wl,
            budget=budget,
            workers=args.workers,
            top_n=args.top_n,
            profile_flat=profile_flat,
        )
        rows.append(row)

    if not rows:
        raise SystemExit("No fixtures analyzed successfully")

    metadata = RunMetadata(
        budget=budget,
        wordlist=str(wl),
        workers=workers,
        timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        fixture_count=len(rows),
        categories=_category_counts(rows),
    )

    if args.write_doc:
        doc_path = Path(args.write_doc)
        doc_path.write_text(format_markdown_report(rows, metadata), encoding="utf-8")
        print(f"Wrote {doc_path}", file=sys.stderr)

    if args.json:
        print(
            json.dumps(
                {
                    "metadata": asdict(metadata),
                    "rows": [row_to_json_dict(r) for r in rows],
                    "precompute_audit": PRECOMPUTE_AUDIT,
                },
                indent=2,
            )
        )
    elif not args.write_doc:
        print_report(rows, metadata)


if __name__ == "__main__":
    main()
