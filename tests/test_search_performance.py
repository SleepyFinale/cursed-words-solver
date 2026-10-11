"""Search performance: profiling harness, fast rank, chess cache, parallel workers."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cursed_words_solver.config import GAME_WORDLIST_PATH
from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.graph_bitboard import RED_COLOR_CODE, build_board_graph_context
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
from cursed_words_solver.search import WordSearcher
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


def test_fast_rank_finds_cat(tmp_path):
    wl = _make_wordlist(tmp_path)
    d = WordDictionary(wl)
    board = _board_cat_horizontal()
    searcher = WordSearcher(
        dictionary=d,
        min_len=3,
        max_len=8,
        time_budget=0.5,
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
    )
    off = WordSearcher(**common, use_dfs_bb=False)
    on = WordSearcher(**common, use_dfs_bb=True)
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
