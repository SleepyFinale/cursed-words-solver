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
    prefix_rank_upper_bound,
    tier2_immediate_upper_bound,
    tier2_rank_lower_bound,
    tier2_rank_upper_bound,
)
from cursed_words_solver.graph_bitboard import RED_COLOR_CODE, build_board_graph_context
from cursed_words_solver.mult_search import loadout_mult_rules
from cursed_words_solver.solve_context import build_solve_context
from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
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
    mult_rules = loadout_mult_rules(loadout, rules, board=board, path=[0, 1, 2])
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
    mult_rules = loadout_mult_rules(loadout, rules, board=board, path=[0, 1, 2])
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
    mult_rules = loadout_mult_rules(loadout, rules, board=board, path=[0, 1, 2])
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
    assert not loadout_allows_tier2_screen(
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


def test_linguistic_cache_key_shared_for_equivalent_routes(tmp_path):
    """Non-chess boards key resolves by letter/tile sequence, not coordinates."""
    wl = _make_wordlist(tmp_path)
    d = WordDictionary(wl)
    board = _board_duplicate_vowel_routes()
    searcher = WordSearcher(dictionary=d, min_len=3, max_len=3, time_budget=2.0)
    path_a = [0, 1, 2]
    path_b = [5, 6, 7]
    key_a = searcher._linguistic_cache_key(board, path_a, chars=["c", "a", "t"])
    key_b = searcher._linguistic_cache_key(board, path_b, chars=["c", "a", "t"])
    assert key_a == key_b
    assert key_a != tuple(path_a)


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
    mult_rules = loadout_mult_rules(loadout, rules, board=board, path=[0, 1, 2])
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
    """Letter-only board: B&B prunes once no wildcards remain reachable."""
    wl = _make_wordlist(tmp_path)
    board = _board_cat_horizontal()
    loadout = Loadout(
        stickers=[
            LoadoutItem(id="red_rider", name="Red Rider", level=1, kind="sticker")
        ]
    )
    common = dict(
        dictionary=WordDictionary(wl),
        min_len=3,
        max_len=8,
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
    assert on.last_search_timing.dfs_expansions <= off.last_search_timing.dfs_expansions
    if on.last_search_timing.dfs_bb_prunes > 0:
        assert (
            on.last_search_timing.dfs_expansions
            < off.last_search_timing.dfs_expansions
        )


def test_linguistic_cache_key_spatial_on_chess_board(tmp_path):
    """Chess boards keep spatial path keys so capture geometry stays correct."""
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
    key = searcher._linguistic_cache_key(board, path, chars=["r", "a", "t"])
    assert key == tuple(path)
