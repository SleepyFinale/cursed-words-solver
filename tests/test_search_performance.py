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
    fast_rank_lower_bound,
    loadout_allows_fast_rank,
)
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
    clear_chess_attack_cache()
    row, col, side, visited = 2, 2, "white", 1 << 12
    a = is_square_attacked(board, row, col, side, visited)
    b = is_square_attacked(board, row, col, side, visited)
    assert a == b


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
