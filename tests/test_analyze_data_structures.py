"""Tests for structure-analysis instrumentation and analyze_data_structures script."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.models import (
    Loadout,
    LoadoutItem,
    board_flat_call_count,
    reset_board_flat_call_count,
)
from cursed_words_solver.rules.chess_tiles import (
    chess_attack_cache_stats,
    reset_chess_attack_cache_stats,
)
from cursed_words_solver.search import SearchTiming, WordSearcher
from tests.helpers.boards import _board_cat_horizontal, _make_wordlist

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.analyze_data_structures as ads  # noqa: E402
from scripts.search_profile_common import hit_pct  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_search_pool():
    yield
    from cursed_words_solver.search_parallel import shutdown_search_pool

    shutdown_search_pool(wait=True)


def test_search_timing_cache_counters(tmp_path: Path):
    wl = _make_wordlist(tmp_path)
    d = WordDictionary(wl)
    board = _board_cat_horizontal()
    loadout = Loadout(
        stickers=[LoadoutItem(id="bone", name="Bone", level=1, kind="sticker")]
    )
    reset_board_flat_call_count()
    reset_chess_attack_cache_stats()
    searcher = WordSearcher(
        dictionary=d,
        min_len=3,
        max_len=6,
        time_budget=1.0,
        search_workers=1,
    )
    results = searcher.find_best_words(board, loadout, top_n=1)
    assert results
    timing = searcher.last_search_timing
    assert timing is not None
    assert timing.score_cache_hits + timing.score_cache_misses > 0
    assert timing.board_flat_calls > 0
    assert timing.board_flat_calls == board_flat_call_count()
    ch, cm = chess_attack_cache_stats()
    assert ch == timing.chess_attack_cache_hits
    assert cm == timing.chess_attack_cache_misses
    assert timing.trie_steps > 0
    assert timing.trie_fast_accepts >= 1


def test_hit_pct():
    assert hit_pct(0, 0) == 0.0
    assert hit_pct(0, 10) == 0.0
    assert hit_pct(10, 0) == 100.0
    assert hit_pct(3, 7) == 30.0


def test_analysis_row_from_timing():
    board = _board_cat_horizontal()
    loadout = Loadout(
        stickers=[LoadoutItem(id="bone", name="Bone", level=1, kind="sticker")]
    )
    timing = SearchTiming(
        wall_sec=2.0,
        score_sec=0.5,
        final_score_sec=0.1,
        dfs_sec=1.0,
        extend_sec=0.2,
        chess_sec=0.05,
        seed_sec=0.05,
        setup_rank_sec=0.02,
        mult_rank_sec=0.03,
        tier2_screen_sec=0.01,
        score_calls=40,
        dfs_expansions=200,
        score_cache_hits=10,
        score_cache_misses=30,
        dict_path_cache_hits=20,
        dict_path_cache_misses=20,
        chess_attack_cache_hits=0,
        chess_attack_cache_misses=0,
        grid_refs_cache_hits=5,
        grid_refs_cache_misses=5,
        board_flat_calls=4,
        trie_steps=500,
        trie_prunes=50,
        trie_fast_accepts=3,
        tier2_screen_skips=2,
        tier2_screen_calls=10,
        tier2_phase1_calls=8,
        tier2_phase2_calls=1,
        tier2_phase2_deferred=1,
        dfs_bb_prunes=4,
        dfs_bb_calls=20,
    )
    results = [MagicMock(word="cat", score=12.0)]
    context = ads.ContextBuildProfile(
        context_build_sec=0.01,
        solve_ctx_sec=0.002,
        graph_ctx_sec=0.003,
        board_scoring_ctx_sec=0.004,
        mult_rules_sec=0.001,
        inventory_ref_count=3,
        static_rule_count=1,
        cell_mask_count=12,
    )
    gates = ads.OptimizationGates(
        fast_rank=False,
        tier2_screen=True,
        tier2_two_phase=True,
        dfs_bb=True,
    )
    features = {
        "sticker_count": 1,
        "stamp_count": 0,
        "mult_rule_count": 0,
        "has_chess_pieces": False,
        "has_number_tiles": False,
        "hanafuda_level": 0,
        "boss_id": "",
    }
    row = ads.build_analysis_row(
        "test_fixture",
        "sticker",
        board,
        loadout,
        results,
        timing,
        elapsed=2.0,
        context=context,
        gates=gates,
        features=features,
    )
    assert row.label == "test_fixture"
    assert row.score_pct == pytest.approx(30.0)
    assert row.dfs_pct == pytest.approx(50.0)
    assert row.score_cache_hit_pct == pytest.approx(25.0)
    assert row.grid_refs_cache_hit_pct == pytest.approx(50.0)
    assert row.score_calls_per_expansion == pytest.approx(0.2)
    assert row.trie_prune_rate == pytest.approx(0.1)
    assert row.tier2_skip_rate == pytest.approx(0.2)
    assert row.dict_resolve_per_score_call == pytest.approx(0.5)
    assert row.dominant_phase == "dfs_exploration"
    assert row.gates.tier2_screen is True


def test_context_build_profile():
    board = _board_cat_horizontal()
    loadout = Loadout(
        stickers=[LoadoutItem(id="shield", name="Shield", level=1, kind="sticker")]
    )
    profile = ads.context_build_profile(board, loadout)
    assert profile.context_build_sec > 0
    assert profile.solve_ctx_sec >= 0
    assert profile.graph_ctx_sec >= 0
    assert profile.active_mask_popcount > 0
    assert profile.cell_mask_count > 0
    assert profile.inventory_ref_count >= 0


def test_optimization_gates():
    board = _board_cat_horizontal()
    empty = ads.optimization_gates(board, Loadout())
    sticker = ads.optimization_gates(
        board,
        Loadout(stickers=[LoadoutItem(id="bone", name="Bone", level=1, kind="sticker")]),
    )
    assert empty.fast_rank is True
    assert sticker.fast_rank is False


def test_format_report_smoke():
    row = ads.AnalysisRow(
        label="smoke",
        category="minimal",
        wall_sec=1.0,
        score_pct=10.0,
        dfs_pct=80.0,
        extend_pct=5.0,
        chess_pct=0.0,
        seed_pct=0.0,
        setup_rank_pct=0.0,
        mult_rank_pct=0.0,
        tier2_screen_pct=0.0,
        score_calls=10,
        dfs_expansions=100,
        sticker_count=1,
        stamp_count=0,
        mult_rule_count=0,
        has_chess_pieces=False,
        has_number_tiles=False,
        hanafuda_level=0,
        boss_id="",
        score_cache_hit_pct=50.0,
        dict_path_cache_hit_pct=50.0,
        chess_attack_cache_hit_pct=0.0,
        grid_refs_cache_hit_pct=0.0,
        board_flat_calls=4,
        board_flat_cum_sec=0.0,
        trie_steps=50,
        trie_prunes=5,
        trie_fast_accepts=1,
        dfs_bb_prunes=0,
        dfs_bb_calls=0,
        tier2_screen_skips=0,
        tier2_screen_calls=0,
        tier2_rank_screen_skips=0,
        tier2_phase1_calls=0,
        tier2_phase2_calls=0,
        tier2_phase2_deferred=0,
        tier2_recommendation="unlikely",
        score_calls_per_expansion=0.1,
        trie_prune_rate=0.1,
        tier2_skip_rate=0.0,
        dict_resolve_per_score_call=0.5,
        best_word="cat",
        best_score=10.0,
        dominant_phase="dfs_exploration",
    )
    metadata = ads.RunMetadata(
        budget=1.0,
        wordlist="test.txt",
        workers=1,
        timestamp="2026-01-01 00:00 UTC",
        fixture_count=1,
        categories={"minimal": 1},
    )
    buf = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf
    try:
        ads.print_report([row], metadata)
    finally:
        sys.stdout = old_stdout
    output = buf.getvalue()
    assert "RUN METADATA" in output
    assert "CACHE HIT RATES" in output
    assert "OPTIMIZATION GATING" in output

    md = ads.format_markdown_report([row], metadata)
    assert "# Data Structure Analysis Results" in md
    assert "| smoke |" in md


def test_json_payload_shape():
    row = ads.AnalysisRow(
        label="json",
        category="minimal",
        wall_sec=1.0,
        score_pct=5.0,
        dfs_pct=90.0,
        extend_pct=3.0,
        chess_pct=0.0,
        seed_pct=0.0,
        setup_rank_pct=0.0,
        mult_rank_pct=0.0,
        tier2_screen_pct=0.0,
        score_calls=5,
        dfs_expansions=50,
        sticker_count=0,
        stamp_count=0,
        mult_rule_count=0,
        has_chess_pieces=False,
        has_number_tiles=False,
        hanafuda_level=0,
        boss_id="",
        score_cache_hit_pct=0.0,
        dict_path_cache_hit_pct=0.0,
        chess_attack_cache_hit_pct=0.0,
        grid_refs_cache_hit_pct=0.0,
        board_flat_calls=2,
        board_flat_cum_sec=0.0,
        trie_steps=10,
        trie_prunes=1,
        trie_fast_accepts=0,
        dfs_bb_prunes=0,
        dfs_bb_calls=0,
        tier2_screen_skips=0,
        tier2_screen_calls=0,
        tier2_rank_screen_skips=0,
        tier2_phase1_calls=0,
        tier2_phase2_calls=0,
        tier2_phase2_deferred=0,
        tier2_recommendation="skip",
        score_calls_per_expansion=0.1,
        trie_prune_rate=0.1,
        tier2_skip_rate=0.0,
        dict_resolve_per_score_call=0.0,
        best_word="a",
        best_score=1.0,
        dominant_phase="dfs_exploration",
    )
    data = ads.row_to_json_dict(row)
    assert "context" in data
    assert "gates" in data
    assert "grid_refs_cache_hit_pct" in data
    assert "tier2_phase1_calls" in data
    payload = {
        "rows": [data],
        "precompute_audit": ads.PRECOMPUTE_AUDIT,
    }
    json.dumps(payload)


def test_collect_default_cases_respects_category_filter():
    cases = ads.collect_default_cases(categories=["chess"])
    assert cases
    assert all(cat == "chess" for _, cat, _ in cases)


def test_load_nested_run_state_board_fixture():
    path = (
        ROOT
        / "tests"
        / "fixtures"
        / "boards"
        / "20260527_hayley_abacus.json"
    )
    if not path.exists():
        pytest.skip("hayley abacus board fixture required")
    from scripts.search_profile_common import load_fixture_auto

    _board, _loadout, label = load_fixture_auto(path)
    assert label == "20260527_hayley_abacus"


def test_default_fixtures_exist():
    missing = []
    for category, paths in ads.DEFAULT_FIXTURES_BY_CATEGORY.items():
        for path in paths:
            if not path.exists():
                missing.append(f"{category}: {path.name}")
    assert not missing, f"Missing default fixtures: {missing}"


@pytest.mark.slow
def test_analyze_script_smoke_fixture(tmp_path: Path):
    wl = _make_wordlist(tmp_path)
    d = WordDictionary(wl)
    board = _board_cat_horizontal()
    loadout = Loadout(
        stickers=[LoadoutItem(id="bone", name="Bone", level=1, kind="sticker")]
    )
    row = ads.run_one(
        "minimal_smoke",
        "minimal",
        board,
        loadout,
        dictionary=d,
        wordlist_path=wl,
        budget=1.0,
        workers=1,
        top_n=1,
        profile_flat=False,
    )
    assert row.wall_sec > 0
    assert row.score_calls > 0
    assert row.dfs_expansions > 0
    assert row.context.context_build_sec > 0
    assert row.best_word
