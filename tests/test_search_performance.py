"""Search performance: profiling harness, fast rank, chess cache, parallel workers."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cursed_words_solver.config import GAME_WORDLIST_PATH
from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.fast_rank import (
    build_search_tile_base,
    fast_rank_lower_bound,
    loadout_allows_fast_rank,
    loadout_allows_tier2_screen,
    loadout_allows_tier2_two_phase,
    number_aware_lower_bound,
    prefix_immediate_upper_bound,
    prefix_rank_upper_bound,
    tier2_immediate_upper_bound,
    tier2_rank_lower_bound,
    tier2_rank_upper_bound,
)
from cursed_words_solver.graph_bitboard import RED_COLOR_CODE, build_board_graph_context
from cursed_words_solver.mult_search import loadout_mult_rules
from cursed_words_solver.solve_context import build_solve_context
from cursed_words_solver.loadout import (
    parse_board_from_run_state,
    parse_run_state,
    prepare_run_state_dict_for_scoring,
)
from cursed_words_solver.models import Loadout, LoadoutItem
from cursed_words_solver.rules.chess_tiles import (
    clear_chess_attack_cache,
    is_square_attacked,
)
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.search import (
    WordSearcher,
    _chess_prefix_budget_sec,
    _chess_tile_count,
    REFINE_OVERRUN_SEC,
    _scale_post_dfs_reserves,
)
from tests.helpers.boards import _board_cat_horizontal, _make_wordlist
from tests.regression.test_scoring_mismatches import _run_state_for_replay

@pytest.fixture(autouse=True)
def _reset_search_pool():
    yield
    from cursed_words_solver.search_parallel import shutdown_search_pool

    shutdown_search_pool(wait=True)


CHESS_FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "mismatches"
    / "20260525_172555.json"
)

STICKER_FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "mismatches"
    / "20260526_231923.json"
)


def _chess_board_and_loadout():
    if not CHESS_FIXTURE.exists():
        pytest.skip("chess mismatch fixture required")
    data = json.loads(CHESS_FIXTURE.read_text(encoding="utf-8"))
    run_state = _run_state_for_replay(data)
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    assert board is not None
    return board, loadout


def test_loadout_allows_fast_rank_empty():
    assert loadout_allows_fast_rank(Loadout())
    assert not loadout_allows_fast_rank(
        Loadout(stickers=[LoadoutItem(id="brain", name="Brain", level=1, kind="sticker")])
    )


def test_fast_rank_lower_bound_le_full_score(tmp_path):
    board = _board_cat_horizontal()
    loadout = Loadout()
    pipeline = ScoringPipeline()
    path = [0, 1, 2]
    lb = fast_rank_lower_bound(board, path)
    full = pipeline.score_total_only(board, path, "cat", loadout)
    assert lb <= full


def test_fast_rank_finds_cat(tmp_path):
    wl = _make_wordlist(tmp_path)
    d = WordDictionary(wl)
    board = _board_cat_horizontal()
    searcher = WordSearcher(
        dictionary=d,
        min_len=3,
        max_len=8,
        time_budget=0.5,
        use_fast_rank=True,
        wordlist_path=wl,
    )
    results = searcher.find_best_words(board, Loadout(), top_n=1)
    assert results
    assert results[0].word == "cat"


def test_chess_attack_cache_consistent():
    board, _ = _chess_board_and_loadout()
    clear_chess_attack_cache(has_chess_pieces=True)
    row, col, side, visited = 2, 2, "white", 1 << 12
    a = is_square_attacked(board, row, col, side, visited)
    b = is_square_attacked(board, row, col, side, visited)
    assert a == b


def test_is_square_attacked_skips_flat_without_chess_pieces():
    from cursed_words_solver.models import board_flat_call_count, reset_board_flat_call_count
    from cursed_words_solver.rules.chess_tiles import (
        chess_attack_cache_stats,
        reset_chess_attack_cache_stats,
    )

    board = _board_cat_horizontal()
    clear_chess_attack_cache(has_chess_pieces=False)
    reset_chess_attack_cache_stats()
    reset_board_flat_call_count()
    for _ in range(50):
        assert not is_square_attacked(board, 2, 2, "white", set())
    assert board_flat_call_count() == 0
    hits, misses = chess_attack_cache_stats()
    assert hits == 0 and misses == 0


def test_unused_cards_on_board_bitmask_matches_flat_scan():
    from cursed_words_solver.encounter_board import effective_board_for_loadout
    from cursed_words_solver.graph_bitboard import build_board_graph_context
    from cursed_words_solver.rules.scoring_conditions import unused_cards_on_board

    if not STICKER_FIXTURE.exists():
        pytest.skip("sticker mismatch fixture required")
    data = json.loads(STICKER_FIXTURE.read_text(encoding="utf-8"))
    run_state = _run_state_for_replay(data)
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    assert board is not None
    pipeline = ScoringPipeline()
    board = effective_board_for_loadout(board, loadout, pipeline.rules)
    graph_ctx = build_board_graph_context(board)
    path = [14, 8, 3, 4, 9]
    legacy = unused_cards_on_board(board, path, hanafuda_suit_mask=0)
    fast = unused_cards_on_board(
        board, path, hanafuda_suit_mask=graph_ctx.hanafuda_suit_mask
    )
    assert fast == legacy


@pytest.mark.slow
@pytest.mark.skipif(
    not STICKER_FIXTURE.exists(),
    reason="sticker mismatch fixture required",
)
@pytest.mark.skipif(
    not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024,
    reason="game wordlist required",
)
def test_sticker_fixture_board_flat_calls_bounded():
    from cursed_words_solver.encounter_board import effective_board_for_loadout
    from cursed_words_solver.models import board_flat_call_count, reset_board_flat_call_count

    data = json.loads(STICKER_FIXTURE.read_text(encoding="utf-8"))
    run_state = _run_state_for_replay(data)
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    assert board is not None
    pipeline = ScoringPipeline()
    board = effective_board_for_loadout(board, loadout, pipeline.rules)
    reset_board_flat_call_count()
    searcher = WordSearcher(
        dictionary=WordDictionary(GAME_WORDLIST_PATH),
        min_len=1,
        max_len=25,
        time_budget=8.0,
        wordlist_path=GAME_WORDLIST_PATH,
        search_workers=1,
    )
    results = searcher.find_best_words(board, loadout, top_n=1)
    assert results
    timing = searcher.last_search_timing
    assert timing is not None
    assert timing.board_flat_calls == board_flat_call_count()
    assert timing.board_flat_calls < 5000


def test_chess_prefix_budget_adaptive():
    board, _ = _chess_board_and_loadout()
    assert _chess_tile_count(board) >= 6
    assert _chess_prefix_budget_sec(board) == 2.0
    cat = _board_cat_horizontal()
    assert _chess_tile_count(cat) < 3
    assert _chess_prefix_budget_sec(cat) == 0.0


@pytest.mark.slow
def test_profile_chess_fixture_completes():
    if not CHESS_FIXTURE.exists():
        pytest.skip("chess mismatch fixture required")
    if not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024:
        pytest.skip("game wordlist required")
    board, loadout = _chess_board_and_loadout()
    searcher = WordSearcher(
        dictionary=WordDictionary(GAME_WORDLIST_PATH),
        min_len=3,
        max_len=12,
        time_budget=3.0,
        wordlist_path=GAME_WORDLIST_PATH,
        search_workers=1,
    )
    results = searcher.find_best_words(board, loadout, top_n=3)
    assert results


@pytest.mark.slow
@pytest.mark.skipif(
    not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024,
    reason="game wordlist required",
)
def test_parallel_workers_smoke():
    from cursed_words_solver.search_parallel import warmup_search_pool

    board, loadout = _chess_board_and_loadout()
    warmup_search_pool(GAME_WORDLIST_PATH, 2)
    single = WordSearcher(
        dictionary=WordDictionary(GAME_WORDLIST_PATH),
        min_len=3,
        max_len=10,
        time_budget=2.0,
        wordlist_path=GAME_WORDLIST_PATH,
        search_workers=1,
    )
    multi = WordSearcher(
        dictionary=WordDictionary(GAME_WORDLIST_PATH),
        min_len=3,
        max_len=10,
        time_budget=2.0,
        wordlist_path=GAME_WORDLIST_PATH,
        search_workers=2,
    )
    r1 = single.find_best_words(board, loadout, top_n=1)
    r2 = multi.find_best_words(board, loadout, top_n=1)
    assert r1 and r2
    assert multi.last_search_timing is not None
    assert multi.last_search_timing.wall_sec < 15.0


def test_search_process_pool_entered_once_per_solve(tmp_path):
    wl = _make_wordlist(tmp_path)
    board = _board_cat_horizontal()
    mock_pool = MagicMock()
    with patch(
        "cursed_words_solver.search_parallel.get_search_pool",
        return_value=mock_pool,
    ) as mock_get:
        searcher = WordSearcher(
            dictionary=WordDictionary(wl),
            min_len=3,
            max_len=8,
            time_budget=0.3,
            wordlist_path=wl,
            search_workers=2,
        )
        searcher.find_best_words(board, Loadout(), top_n=1)
        mock_get.assert_called()
        assert mock_pool.submit.called


@pytest.mark.slow
@pytest.mark.skipif(
    not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024,
    reason="game wordlist required",
)
def test_parallel_search_near_budget():
    """Regression: parallel solve must not multiply wall time by cap-pass count."""
    from cursed_words_solver.search_parallel import warmup_search_pool

    board, loadout = _chess_board_and_loadout()
    budget = 8.0
    warmup_search_pool(GAME_WORDLIST_PATH, 2)
    searcher = WordSearcher(
        dictionary=WordDictionary(GAME_WORDLIST_PATH),
        min_len=3,
        max_len=12,
        time_budget=budget,
        wordlist_path=GAME_WORDLIST_PATH,
        search_workers=2,
    )
    t0 = time.perf_counter()
    results = searcher.find_best_words(board, loadout, top_n=1)
    elapsed = time.perf_counter() - t0
    assert results
    assert elapsed < budget * 2.5
    assert searcher.last_search_timing is not None
    assert searcher.last_search_timing.wall_sec < budget * 2.5


@pytest.mark.slow
def test_trie_pruning_metrics_letter_board(tmp_path):
    """Trie counters fire on letter-only DFS; fast accept finds dictionary words."""
    wl = _make_wordlist(tmp_path)
    d = WordDictionary(wl)
    board = _board_cat_horizontal()
    searcher = WordSearcher(
        dictionary=d,
        min_len=3,
        max_len=8,
        time_budget=1.0,
        wordlist_path=wl,
        search_workers=1,
    )
    results = searcher.find_best_words(board, Loadout(), top_n=3)
    assert results
    assert results[0].word == "cat"
    timing = searcher.last_search_timing
    assert timing is not None
    assert timing.trie_steps > 0
    assert timing.trie_fast_accepts >= 1


@pytest.mark.slow
@pytest.mark.skipif(
    not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024,
    reason="game wordlist required",
)
def test_trie_pruning_chess_fixture(tmp_path):
    """Chess fixture: trie prunes fire and search still completes."""
    board, loadout = _chess_board_and_loadout()
    searcher = WordSearcher(
        dictionary=WordDictionary(GAME_WORDLIST_PATH),
        min_len=3,
        max_len=12,
        time_budget=4.0,
        wordlist_path=GAME_WORDLIST_PATH,
        search_workers=1,
    )
    results = searcher.find_best_words(board, loadout, top_n=1)
    assert results
    timing = searcher.last_search_timing
    assert timing is not None
    assert timing.trie_steps > 0
    assert timing.dfs_expansions > 0


def _sticker_board_and_loadout():
    if not STICKER_FIXTURE.exists():
        pytest.skip("sticker mismatch fixture required")
    data = json.loads(STICKER_FIXTURE.read_text(encoding="utf-8"))
    run_state = _run_state_for_replay(data)
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    assert board is not None
    return board, loadout


def test_number_aware_lower_bound_le_full_score():
    board = _board_cat_horizontal()
    loadout = Loadout()
    pipeline = ScoringPipeline()
    rules = pipeline.rules
    graph_ctx = build_board_graph_context(board)
    path = [0, 1, 2]
    full = pipeline.score_total_only(board, path, "cat", loadout)
    lb = number_aware_lower_bound(
        board, path, loadout, rules, graph_ctx=graph_ctx
    )
    assert lb <= full + 1e-6


def test_tier2_upper_bound_ge_full_score():
    board = _board_cat_horizontal()
    loadout = Loadout(
        stickers=[
            LoadoutItem(id="red_rider", name="Red Rider", level=1, kind="sticker")
        ]
    )
    pipeline = ScoringPipeline()
    rules = pipeline.rules
    ctx = build_solve_context(loadout, rules)
    mult_rules = loadout_mult_rules(
        loadout, rules, board=board, path=[0, 1, 2], solve_context=ctx
    )
    path = [0, 1, 2]
    full = pipeline.score_total_only(board, path, "cat", loadout)
    ub = tier2_immediate_upper_bound(board, path, "cat", loadout, ctx, mult_rules)
    assert ub >= full


def test_tier2_upper_bound_ge_rank_score():
    board = _board_cat_horizontal()
    loadout = Loadout(
        stickers=[
            LoadoutItem(id="red_rider", name="Red Rider", level=1, kind="sticker")
        ]
    )
    searcher = WordSearcher(min_len=3, max_len=8, time_budget=1.0)
    rules = searcher.scoring.rules
    ctx = build_solve_context(loadout, rules)
    mult_rules = loadout_mult_rules(
        loadout, rules, board=board, path=[0, 1, 2], solve_context=ctx
    )
    path = [0, 1, 2]
    rank = searcher._rank_score_for_candidate(board, path, "cat", loadout)
    assert rank is not None
    ub = tier2_rank_upper_bound(
        board,
        path,
        "cat",
        loadout,
        ctx,
        mult_rules,
        mult_weight=searcher.mult_search_weight,
    )
    assert ub >= rank


def test_tier2_rank_lower_bound_le_full_score():
    board = _board_cat_horizontal()
    loadout = Loadout(
        stickers=[LoadoutItem(id="red_rider", name="Red Rider", level=1, kind="sticker")]
    )
    pipeline = ScoringPipeline()
    rules = pipeline.rules
    ctx = build_solve_context(loadout, rules)
    mult_rules = loadout_mult_rules(
        loadout, rules, board=board, path=[0, 1, 2], solve_context=ctx
    )
    path = [0, 1, 2]
    full = pipeline.score_total_only(board, path, "cat", loadout, solve_context=ctx)
    rank_lb = tier2_rank_lower_bound(
        board,
        path,
        "cat",
        loadout,
        ctx,
        mult_rules,
        mult_weight=0.4,
    )
    assert rank_lb <= full


def test_loadout_allows_tier2_two_phase_when_screen_enabled():
    rules = ScoringPipeline().rules
    sticker_only = Loadout(
        stickers=[LoadoutItem(id="brain", name="Brain", level=1, kind="sticker")]
    )
    ctx = build_solve_context(sticker_only, rules)
    assert loadout_allows_tier2_two_phase(ctx, sticker_only)


def test_loadout_allows_tier2_screen_gating():
    rules = ScoringPipeline().rules
    sticker_only = Loadout(
        stickers=[LoadoutItem(id="brain", name="Brain", level=1, kind="sticker")]
    )
    ctx_sticker = build_solve_context(sticker_only, rules)
    assert loadout_allows_tier2_screen(ctx_sticker, sticker_only)

    setup_loadout = Loadout(
        stickers=[
            LoadoutItem(id="birthday_cake", name="Birthday Cake", level=1, kind="sticker")
        ]
    )
    ctx_setup = build_solve_context(setup_loadout, rules)
    assert loadout_allows_tier2_screen(
        ctx_setup, setup_loadout, setup_weight=0.4
    )
    assert loadout_allows_tier2_screen(ctx_setup, setup_loadout, setup_weight=0.0)

    compound_loadout = Loadout(
        stickers=[LoadoutItem(id="brain", name="Brain", level=1, kind="sticker")],
        extras={"compound_word_percents_on_tile_sum": "10,20"},
    )
    ctx_compound = build_solve_context(compound_loadout, rules)
    assert not ctx_compound.tier2_screen_enabled


@pytest.mark.slow
@pytest.mark.skipif(
    not STICKER_FIXTURE.exists()
    or not GAME_WORDLIST_PATH.exists()
    or GAME_WORDLIST_PATH.stat().st_size < 1024,
    reason="sticker fixture and game wordlist required",
)
def test_tier2_screen_preserves_top_results():
    board, loadout = _sticker_board_and_loadout()
    common = dict(
        dictionary=WordDictionary(GAME_WORDLIST_PATH),
        min_len=3,
        max_len=12,
        time_budget=12.0,
        wordlist_path=GAME_WORDLIST_PATH,
        search_workers=1,
    )
    off = WordSearcher(**common, use_tier2_screen=False)
    on = WordSearcher(**common, use_tier2_screen=True)
    off_results = off.find_best_words(board, loadout, top_n=1)
    on_results = on.find_best_words(board, loadout, top_n=1)
    assert off_results and on_results
    assert off_results[0].word == on_results[0].word
    assert off_results[0].score == on_results[0].score


@pytest.mark.slow
@pytest.mark.skipif(
    not STICKER_FIXTURE.exists()
    or not GAME_WORDLIST_PATH.exists()
    or GAME_WORDLIST_PATH.stat().st_size < 1024,
    reason="sticker fixture and game wordlist required",
)
def test_tier2_screen_reduces_score_calls():
    board, loadout = _sticker_board_and_loadout()
    common = dict(
        dictionary=WordDictionary(GAME_WORDLIST_PATH),
        min_len=3,
        max_len=12,
        time_budget=12.0,
        wordlist_path=GAME_WORDLIST_PATH,
        search_workers=1,
    )
    off = WordSearcher(**common, use_tier2_screen=False)
    on = WordSearcher(**common, use_tier2_screen=True)
    off.find_best_words(board, loadout, top_n=3)
    on.find_best_words(board, loadout, top_n=3)
    assert off.last_search_timing is not None
    assert on.last_search_timing is not None
    assert on.last_search_timing.tier2_screen_skips > 0
    assert on.last_search_timing.score_calls < off.last_search_timing.score_calls


def _board_duplicate_vowel_routes():
    """Two routes spell 'cat' through equivalent letter tiles at different cells."""
    from cursed_words_solver.models import Board, CurseType, Tile, TileColor

    grid = [
        [Tile(r, c, "q", "Q", 1.0, TileColor.COLORLESS, CurseType.LETTER) for c in range(5)]
        for r in range(5)
    ]
    grid[0][0] = Tile(0, 0, "c", "C", 1.0, TileColor.COLORLESS, CurseType.LETTER)
    grid[0][1] = Tile(0, 1, "a", "A", 1.0, TileColor.COLORLESS, CurseType.LETTER)
    grid[0][2] = Tile(0, 2, "t", "T", 1.0, TileColor.COLORLESS, CurseType.LETTER)
    grid[1][0] = Tile(1, 0, "c", "C", 1.0, TileColor.COLORLESS, CurseType.LETTER)
    grid[1][1] = Tile(1, 1, "a", "A", 1.0, TileColor.COLORLESS, CurseType.LETTER)
    grid[1][2] = Tile(1, 2, "t", "T", 1.0, TileColor.COLORLESS, CurseType.LETTER)
    return Board(tiles=grid)


def test_linguistic_cache_key_uses_path_tuple(tmp_path):
    """Scoring-only dict cache keys use path coordinates (unique per traversal)."""
    wl = _make_wordlist(tmp_path)
    d = WordDictionary(wl)
    board = _board_duplicate_vowel_routes()
    searcher = WordSearcher(dictionary=d, min_len=3, max_len=3, time_budget=2.0)
    path_a = [0, 1, 2]
    path_b = [5, 6, 7]
    key_a = searcher._linguistic_cache_key(board, path_a)
    key_b = searcher._linguistic_cache_key(board, path_b)
    assert key_a == tuple(path_a)
    assert key_b == tuple(path_b)
    assert key_a != key_b


def test_prefix_rank_upper_bound_sound():
    board = _board_cat_horizontal()
    loadout = Loadout(
        stickers=[
            LoadoutItem(id="red_rider", name="Red Rider", level=1, kind="sticker")
        ]
    )
    rules = ScoringPipeline().rules
    ctx = build_solve_context(loadout, rules)
    graph_ctx = build_board_graph_context(board)
    mult_rules = loadout_mult_rules(
        loadout, rules, board=board, path=[0, 1, 2], solve_context=ctx
    )
    search_tile_base = build_search_tile_base(board, ctx, graph_ctx)
    path = [0, 1, 2]
    word = "cat"
    full_rank_ub = tier2_rank_upper_bound(
        board,
        path,
        word,
        loadout,
        ctx,
        mult_rules,
        mult_weight=0.4,
        graph_ctx=graph_ctx,
    )
    full_imm_ub = tier2_immediate_upper_bound(
        board,
        path,
        word,
        loadout,
        ctx,
        mult_rules,
        graph_ctx=graph_ctx,
    )
    visited = 0
    prefix_base = 0.0
    prefix_red = 0
    chars: list[str] = []
    for i, idx in enumerate(path):
        visited |= 1 << idx
        prefix_base += search_tile_base[idx]
        if graph_ctx.tile_color_code[idx] == RED_COLOR_CODE:
            prefix_red += 1
        chars.append(word[i])
        imm_ub = prefix_immediate_upper_bound(
            prefix_base,
            board,
            path[: i + 1],
            chars,
            visited,
            max(0, 3 - len(chars)),
            loadout,
            ctx,
            mult_rules,
            graph_ctx,
            search_tile_base,
            max_len=3,
            prefix_red_count=prefix_red,
        )
        bound = prefix_rank_upper_bound(
            prefix_base,
            board,
            path[: i + 1],
            chars,
            visited,
            max(0, 3 - len(chars)),
            loadout,
            ctx,
            mult_rules,
            graph_ctx,
            search_tile_base,
            mult_weight=0.4,
            max_len=3,
            prefix_red_count=prefix_red,
        )
        assert imm_ub >= full_imm_ub
        assert bound >= full_rank_ub


@pytest.mark.slow
@pytest.mark.skipif(
    not STICKER_FIXTURE.exists()
    or not GAME_WORDLIST_PATH.exists()
    or GAME_WORDLIST_PATH.stat().st_size < 1024,
    reason="sticker fixture and game wordlist required",
)
def test_dfs_bb_preserves_top_results():
    board, loadout = _sticker_board_and_loadout()
    common = dict(
        dictionary=WordDictionary(GAME_WORDLIST_PATH),
        min_len=3,
        max_len=12,
        time_budget=12.0,
        wordlist_path=GAME_WORDLIST_PATH,
        search_workers=1,
        use_tier2_screen=True,
    )
    off = WordSearcher(**common, use_dfs_bb=False)
    on = WordSearcher(**common, use_dfs_bb=True)
    off_results = off.find_best_words(board, loadout, top_n=1)
    on_results = on.find_best_words(board, loadout, top_n=1)
    assert off_results and on_results
    assert off_results[0].word == on_results[0].word
    assert off_results[0].score == on_results[0].score


def test_dfs_bb_reduces_expansions(tmp_path):
    """Letter-only board: B&B prunes once best score is known."""
    wl = _make_wordlist(tmp_path)
    board = _board_cat_horizontal()
    loadout = Loadout()
    common = dict(
        dictionary=WordDictionary(wl),
        min_len=3,
        max_len=3,
        time_budget=2.0,
        wordlist_path=wl,
        search_workers=1,
        use_tier2_screen=True,
        candidate_heap_size=1,
    )
    off = WordSearcher(**common, use_dfs_bb=False)
    on = WordSearcher(**common, use_dfs_bb=True)
    off.find_best_words(board, loadout, top_n=1)
    on.find_best_words(board, loadout, top_n=1)
    assert off.last_search_timing is not None
    assert on.last_search_timing is not None
    assert on.last_search_timing.dfs_bb_calls > 0
    assert on.last_search_timing.dfs_bb_prunes > 0
    assert on.last_search_timing.dfs_expansions < off.last_search_timing.dfs_expansions


@pytest.mark.slow
@pytest.mark.skipif(
    not STICKER_FIXTURE.exists()
    or not GAME_WORDLIST_PATH.exists()
    or GAME_WORDLIST_PATH.stat().st_size < 1024,
    reason="sticker fixture and game wordlist required",
)
def test_dfs_bb_prunes_sticker_fixture():
    """Sticker-heavy board: B&B should prune branches once best score is known."""
    board, loadout = _sticker_board_and_loadout()
    common = dict(
        dictionary=WordDictionary(GAME_WORDLIST_PATH),
        min_len=3,
        max_len=12,
        time_budget=12.0,
        wordlist_path=GAME_WORDLIST_PATH,
        search_workers=1,
        use_tier2_screen=True,
    )
    off = WordSearcher(**common, use_dfs_bb=False)
    on = WordSearcher(**common, use_dfs_bb=True)
    off.find_best_words(board, loadout, top_n=1)
    on.find_best_words(board, loadout, top_n=1)
    assert off.last_search_timing is not None
    assert on.last_search_timing is not None
    assert on.last_search_timing.dfs_bb_prunes > 0
    assert on.last_search_timing.dfs_bb_calls > 0
    assert on.last_search_timing.dfs_expansions <= off.last_search_timing.dfs_expansions


def test_dfs_bb_prunes_chess_board(tmp_path):
    """Chess piece on board: B&B runs on letter-only DFS branches."""
    from cursed_words_solver.models import Board, CurseType, Tile, TileColor

    wl = _make_wordlist(tmp_path)
    grid = [
        [Tile(r, c, "q", "Q", 1.0, TileColor.COLORLESS, CurseType.LETTER) for c in range(5)]
        for r in range(5)
    ]
    grid[0][0] = Tile(
        0, 0, "r", "R", 1.0, TileColor.COLORLESS, CurseType.CHESS_ROOK
    )
    grid[0][1] = Tile(0, 1, "c", "C", 1.0, TileColor.COLORLESS, CurseType.LETTER)
    grid[0][2] = Tile(0, 2, "a", "A", 1.0, TileColor.COLORLESS, CurseType.LETTER)
    grid[0][3] = Tile(0, 3, "t", "T", 1.0, TileColor.COLORLESS, CurseType.LETTER)
    board = Board(tiles=grid)
    loadout = Loadout()
    searcher = WordSearcher(
        dictionary=WordDictionary(wl),
        min_len=3,
        max_len=3,
        time_budget=2.0,
        wordlist_path=wl,
        search_workers=1,
        use_tier2_screen=True,
        use_dfs_bb=True,
        candidate_heap_size=1,
    )
    searcher.find_best_words(board, loadout, top_n=1)
    assert searcher.last_search_timing is not None
    assert searcher.last_search_timing.dfs_bb_calls > 0


def test_linguistic_cache_key_spatial_on_chess_board(tmp_path):
    """Dict resolve cache keys use path tuple on all boards."""
    from cursed_words_solver.models import Board, CurseType, Tile, TileColor

    wl = _make_wordlist(tmp_path)
    d = WordDictionary(wl)
    grid = [
        [Tile(r, c, "q", "Q", 1.0, TileColor.COLORLESS, CurseType.LETTER) for c in range(5)]
        for r in range(5)
    ]
    grid[0][0] = Tile(
        0, 0, "r", "R", 1.0, TileColor.COLORLESS, CurseType.CHESS_ROOK
    )
    board = Board(tiles=grid)
    searcher = WordSearcher(dictionary=d, min_len=3, max_len=3, time_budget=1.0)
    path = [0, 1, 2]
    key = searcher._linguistic_cache_key(board, path)
    assert key == tuple(path)


OCTACLES_FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "mismatches"
    / "20260615_134052.json"
)


def _octacles_curse_heavy_board_and_loadout():
    if not OCTACLES_FIXTURE.exists():
        pytest.skip("octacles curse-heavy fixture required")
    data = json.loads(OCTACLES_FIXTURE.read_text(encoding="utf-8"))
    run_state = _run_state_for_replay(data)
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    assert board is not None
    return board, loadout


def test_refine_provisional_heap_stops_at_deadline():
    """Tier-2 phase 2 must not run unbounded when the solve deadline has passed."""
    from cursed_words_solver.search import SearchTiming, _CandidateHeap

    board, loadout = _sticker_board_and_loadout()
    searcher = WordSearcher(
        dictionary=WordDictionary(GAME_WORDLIST_PATH) if GAME_WORDLIST_PATH.exists() else None,
        min_len=3,
        max_len=12,
        time_budget=5.0,
    )
    if searcher.dictionary is None:
        pytest.skip("game wordlist required")
    searcher._solve_ctx = build_solve_context(loadout, searcher.scoring.rules)
    timing = SearchTiming()
    searcher._active_timing = timing
    searcher._provisional_candidates = {
        (tuple(range(i, i + 3)), f"?w{i}"): float(1000 - i) for i in range(80)
    }
    heap = _CandidateHeap(50)
    searcher._refine_provisional_heap(
        board,
        loadout,
        heap,
        deadline=time.monotonic(),
    )
    assert timing.tier2_phase2_calls == 0


@pytest.mark.slow
@pytest.mark.skipif(
    not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024,
    reason="game wordlist required",
)
def test_curse_heavy_tier2_search_within_f8_budget():
    """Regression: tier-2 refine must not blow past the configured search budget."""
    from cursed_words_solver.search_parallel import warmup_search_pool

    board, loadout = _octacles_curse_heavy_board_and_loadout()
    budget = 12.0
    warmup_search_pool(GAME_WORDLIST_PATH, 2)
    searcher = WordSearcher(
        dictionary=WordDictionary(GAME_WORDLIST_PATH),
        min_len=1,
        max_len=25,
        time_budget=budget,
        wordlist_path=GAME_WORDLIST_PATH,
        search_workers=2,
    )
    solve_deadline = time.monotonic() + budget
    t0 = time.perf_counter()
    results = searcher.find_best_words(
        board,
        loadout,
        top_n=1,
        deadline=solve_deadline,
    )
    elapsed = time.perf_counter() - t0
    assert results
    timing = searcher.last_search_timing
    assert timing is not None
    assert timing.wall_sec < budget * 1.15 + REFINE_OVERRUN_SEC
    assert elapsed < budget * 1.15 + REFINE_OVERRUN_SEC
    if timing.tier2_phase2_deferred > 0:
        assert timing.tier2_phase2_calls <= timing.tier2_phase2_deferred


YICKER_FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "mismatches"
    / "20260615_142317_454.json"
)


def _yicker_board_and_loadout():
    if not YICKER_FIXTURE.exists():
        pytest.skip("yicker round-log fixture required")
    data = json.loads(YICKER_FIXTURE.read_text(encoding="utf-8"))
    run_state = prepare_run_state_dict_for_scoring(data["run_state"])
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    assert board is not None
    return board, loadout


def test_reserve_scaling_leaves_positive_main_slice():
    """Curse-heavy boards must keep at least 30% of budget for primary DFS."""
    board, _loadout = _yicker_board_and_loadout()
    from cursed_words_solver.search import is_fraction_tile, is_number_like_tile

    tb = 60.0
    has_num = any(is_number_like_tile(t) for t in board.flat)
    has_frac = any(is_fraction_tile(t) for t in board.flat)
    nr = min(10.0, tb * 0.45) if has_num else 0.0
    fr = min(15.0, tb * 0.35) if has_frac else 0.0
    cr = min(8.0, tb * 0.35) if _chess_tile_count(board) >= 3 else 0.0
    er = min(5.0, tb * 0.12)
    scaled = _scale_post_dfs_reserves(
        time_budget=tb,
        number_reserve=nr,
        void_reserve=0.0,
        fraction_cluster_reserve=fr,
        chess_reserve=cr,
        seed_reserve=0.0,
        extension_reserve=er,
    )
    main_slice = tb - sum(scaled[:7])
    assert main_slice >= tb * 0.30


def test_serial_workers_finds_candidates_on_yicker_board():
    if not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024:
        pytest.skip("game wordlist required")
    board, loadout = _yicker_board_and_loadout()
    searcher = WordSearcher(
        dictionary=WordDictionary(GAME_WORDLIST_PATH),
        min_len=1,
        max_len=25,
        time_budget=60.0,
        wordlist_path=GAME_WORDLIST_PATH,
        search_workers=1,
    )
    results = searcher.find_best_words(board, loadout=loadout, top_n=1)
    assert results
    timing = searcher.last_search_timing
    assert timing is not None
    assert timing.main_dfs_slice_sec >= 60.0 * 0.30


@pytest.mark.slow
@pytest.mark.skipif(
    not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024,
    reason="game wordlist required",
)
def test_yicker_board_finds_high_scoring_word():
    """Regression: da-prefix board must find yicker-class scores, not 2-letter junk."""
    from cursed_words_solver.search_parallel import warmup_search_pool

    board, loadout = _yicker_board_and_loadout()
    budget = 60.0
    warmup_search_pool(GAME_WORDLIST_PATH, 2)
    searcher = WordSearcher(
        dictionary=WordDictionary(GAME_WORDLIST_PATH),
        min_len=1,
        max_len=25,
        time_budget=budget,
        wordlist_path=GAME_WORDLIST_PATH,
        search_workers=8,
    )
    solve_deadline = time.monotonic() + budget
    t0 = time.monotonic()
    results = searcher.find_best_words(
        board,
        loadout,
        top_n=1,
        deadline=solve_deadline,
    )
    elapsed = time.monotonic() - t0
    assert results
    timing = searcher.last_search_timing
    assert timing is not None
    assert timing.wall_sec < budget + REFINE_OVERRUN_SEC + 35.0
    assert elapsed < budget + REFINE_OVERRUN_SEC + 35.0
    assert timing.main_dfs_slice_sec >= budget * 0.23
    best = results[0]
    assert best.score >= 2000 or best.word == "yicker"


SAM_GAMBIT_CURSE_HEAVY_FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "mismatches"
    / "20260529_113020.json"
)


def _sam_gambit_curse_heavy_board_and_loadout():
    if not SAM_GAMBIT_CURSE_HEAVY_FIXTURE.exists():
        pytest.skip("Sam Gambit curse-heavy fixture required")
    data = json.loads(SAM_GAMBIT_CURSE_HEAVY_FIXTURE.read_text(encoding="utf-8"))
    run_state = _run_state_for_replay(data)
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    assert board is not None
    return board, loadout


@pytest.mark.slow
@pytest.mark.skipif(
    not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024,
    reason="game wordlist required",
)
def test_sam_gambit_curse_heavy_within_f8_budget():
    """Regression: curse-heavy Sam Gambit extend must not blow past F8 budget."""
    from cursed_words_solver.search_parallel import warmup_search_pool

    board, loadout = _sam_gambit_curse_heavy_board_and_loadout()
    budget = 60.0
    warmup_search_pool(GAME_WORDLIST_PATH, 8)
    searcher = WordSearcher(
        dictionary=WordDictionary(GAME_WORDLIST_PATH),
        min_len=3,
        max_len=25,
        time_budget=budget,
        wordlist_path=GAME_WORDLIST_PATH,
        search_workers=8,
    )
    solve_deadline = time.monotonic() + budget
    t0 = time.perf_counter()
    results = searcher.find_best_words(
        board,
        loadout,
        top_n=1,
        deadline=solve_deadline,
    )
    elapsed = time.perf_counter() - t0
    assert results
    timing = searcher.last_search_timing
    assert timing is not None
    assert timing.wall_sec < 60.0
    assert timing.extend_sec < 30.0
    assert elapsed < 65.0
    best = results[0]
    assert len(best.path) >= 7
    assert best.score >= 50


SAM_GAMBIT_LIVE_BOARD_FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "mismatches"
    / "20260628_220029_975.json"
)


def _sam_gambit_live_board_and_loadout():
    if not SAM_GAMBIT_LIVE_BOARD_FIXTURE.exists():
        pytest.skip("Sam Gambit live-board round-log fixture required")
    from tests.regression.test_path_mismatch_round_log import _round_log_to_replay

    data = json.loads(SAM_GAMBIT_LIVE_BOARD_FIXTURE.read_text(encoding="utf-8"))
    run_state = _run_state_for_replay(_round_log_to_replay(data))
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    assert board is not None
    return board, loadout


@pytest.mark.slow
@pytest.mark.skipif(
    not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024,
    reason="game wordlist required",
)
def test_sam_gambit_live_board_within_f8_budget():
    """Regression: live curse-heavy Sam Gambit board must finish within hard F8 cap."""
    from cursed_words_solver.search_parallel import warmup_search_pool

    board, loadout = _sam_gambit_live_board_and_loadout()
    budget = 60.0
    warmup_search_pool(GAME_WORDLIST_PATH, 8)
    searcher = WordSearcher(
        dictionary=WordDictionary(GAME_WORDLIST_PATH),
        min_len=3,
        max_len=25,
        time_budget=budget,
        wordlist_path=GAME_WORDLIST_PATH,
        search_workers=8,
    )
    solve_deadline = time.monotonic() + budget
    t0 = time.perf_counter()
    results = searcher.find_best_words(
        board,
        loadout,
        top_n=1,
        deadline=solve_deadline,
    )
    elapsed = time.perf_counter() - t0
    assert results
    timing = searcher.last_search_timing
    assert timing is not None
    assert timing.wall_sec < 60.0
    assert elapsed < 65.0
    best = results[0]
    assert best.score >= 2000


XYLOMETERS_FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "mismatches"
    / "20260615_150843_021.json"
)
XYLOMETERS_PATH = [1, 4, 3, 8, 12, 17, 23, 24, 15, 21]


def _xylometers_board_and_loadout():
    if not XYLOMETERS_FIXTURE.exists():
        pytest.skip("xylometers round-log fixture required")
    data = json.loads(XYLOMETERS_FIXTURE.read_text(encoding="utf-8"))
    run_state = prepare_run_state_dict_for_scoring(data["run_state"])
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    assert board is not None
    return board, loadout


def test_xylometers_path_movement_ok_with_hungry_snake():
    from cursed_words_solver.rules.stamp_behaviors import stamp_search_flags_mask
    from cursed_words_solver.search import path_movement_ok

    board, loadout = _xylometers_board_and_loadout()
    flags = stamp_search_flags_mask(loadout)
    assert path_movement_ok(board, XYLOMETERS_PATH, flags=flags)


def test_xylometers_path_scores_like_game():
    board, loadout = _xylometers_board_and_loadout()
    score, _bd = ScoringPipeline().score(
        board, XYLOMETERS_PATH, "xylometers", loadout
    )
    assert score == pytest.approx(6615, abs=5)


@pytest.mark.slow
@pytest.mark.skipif(
    not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024,
    reason="game wordlist required",
)
def test_xylometers_board_finds_high_scoring_word():
    """Regression: Hungry Snake wrap path must reach xylometers, not short wildcard junk."""
    from cursed_words_solver.search_parallel import warmup_search_pool

    board, loadout = _xylometers_board_and_loadout()
    budget = 60.0
    warmup_search_pool(GAME_WORDLIST_PATH, 2)
    searcher = WordSearcher(
        dictionary=WordDictionary(GAME_WORDLIST_PATH),
        min_len=1,
        max_len=25,
        time_budget=budget,
        wordlist_path=GAME_WORDLIST_PATH,
        search_workers=8,
    )
    results = searcher.find_best_words(
        board,
        loadout,
        top_n=1,
        deadline=time.monotonic() + budget + REFINE_OVERRUN_SEC,
    )
    assert results
    timing = searcher.last_search_timing
    assert timing is not None
    assert timing.wall_sec < budget + REFINE_OVERRUN_SEC + 15.0
    best = results[0]
    assert best.score >= 6000
