"""Search performance benchmarks and regression guards.

Tier 2 (two-phase base-score filtering, beam search) was evaluated after Tier 1:
sticker pipeline dominates per-word cost; Tier 1 removes duplicate scoring, defers
breakdown to finalists, caps candidates with a top-K heap, and orders neighbors by
base_score. Further tier-2 work is deferred unless profiling on real game boards
shows DFS expansion still dominates.
"""

from __future__ import annotations

import time

import pytest

from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.models import Loadout, LoadoutItem, TileColor
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.search import WordSearcher
from tests.helpers.boards import _board_123ifer_fixture, _board_cat_horizontal, _make_wordlist


def test_score_total_only_matches_full_score(tmp_path):
    wl = _make_wordlist(tmp_path)
    board = _board_cat_horizontal()
    loadout = Loadout(
        stickers=[
            LoadoutItem(id="red_rider", name="Red Rider", level=1, kind="sticker")
        ]
    )
    pipeline = ScoringPipeline()
    total = pipeline.score_total_only(board, [0, 1, 2], "cat", loadout)
    full, _ = pipeline.score(board, [0, 1, 2], "cat", loadout)
    assert total == full


def test_search_finds_cat_under_tight_budget(tmp_path):
    wl = _make_wordlist(tmp_path)
    d = WordDictionary(wl)
    searcher = WordSearcher(dictionary=d, min_len=3, max_len=8, time_budget=0.5)
    board = _board_cat_horizontal()
    results = searcher.find_best_words(board, top_n=1)
    assert results
    assert results[0].word == "cat"
    assert results[0].breakdown


@pytest.mark.slow
def test_search_benchmark_cat_board(tmp_path):
    """Regression: cat board should complete quickly with many expansions."""
    wl = _make_wordlist(tmp_path)
    d = WordDictionary(wl)
    board = _board_cat_horizontal()
    loadout = Loadout(
        stickers=[
            LoadoutItem(id="red_rider", name="Red Rider", level=1, kind="sticker")
        ]
    )
    searcher = WordSearcher(dictionary=d, min_len=3, max_len=8, time_budget=1.0)
    t0 = time.perf_counter()
    results = searcher.find_best_words(board, loadout, top_n=5)
    elapsed = time.perf_counter() - t0
    assert results
    assert results[0].word == "cat"
    assert elapsed < 1.5


@pytest.mark.slow
def test_search_benchmark_game_board_if_available():
    from cursed_words_solver.config import GAME_WORDLIST_PATH

    if not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024:
        pytest.skip("game wordlist not available")

    d = WordDictionary(GAME_WORDLIST_PATH)
    board = _board_123ifer_fixture()
    loadout = Loadout(
        stickers=[
            LoadoutItem(id="brain", name="Brain", level=3, kind="sticker"),
        ],
        money=8,
    )
    searcher = WordSearcher(dictionary=d, min_len=3, max_len=12, time_budget=2.0)
    t0 = time.perf_counter()
    results = searcher.find_best_words(board, loadout, top_n=10)
    elapsed = time.perf_counter() - t0
    words = {r.word for r in results}
    assert "123ifer" in words
    assert elapsed < 3.0
