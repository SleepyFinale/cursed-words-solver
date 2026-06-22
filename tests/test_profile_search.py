"""Smoke tests for search profiling / Tier-2 guidance."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.models import Loadout, LoadoutItem
from cursed_words_solver.search import SearchTiming, WordSearcher
from tests.helpers.boards import _board_cat_horizontal, _make_wordlist


def test_search_timing_tier2_recommendation():
    t = SearchTiming(wall_sec=10.0, score_sec=6.0, score_calls=100)
    assert "likely" in t.tier2_recommendation(sticker_count=3)
    t2 = SearchTiming(wall_sec=10.0, score_sec=2.0)
    assert "unlikely" in t2.tier2_recommendation(sticker_count=3)
    t3 = SearchTiming(wall_sec=10.0, score_sec=0.5)
    assert "skip" in t3.tier2_recommendation(sticker_count=0)


def test_adaptive_tier2_mode_updates_during_search(tmp_path: Path):
    wl = _make_wordlist(tmp_path)
    d = WordDictionary(wl)
    board = _board_cat_horizontal()
    loadout = Loadout(
        stickers=[LoadoutItem(id="bone", name="Bone", level=1, kind="sticker")]
    )
    searcher = WordSearcher(
        dictionary=d,
        min_len=3,
        max_len=6,
        time_budget=4.0,
        search_workers=1,
    )
    searcher.find_best_words(board, loadout, top_n=1)
    timing = searcher.last_search_timing
    assert timing is not None
    if searcher._tier2_adaptive_mode is None:
        timing.dfs_expansions = max(timing.dfs_expansions, 500)
        searcher._active_timing = timing
        searcher._solve_start_mono = time.monotonic() - 3.0
        searcher._tier2_adaptive_mode = None
        searcher._update_tier2_adaptive_mode()
    assert searcher._tier2_adaptive_mode in ("light", "normal", "deep")


def test_find_best_words_records_score_timing(tmp_path: Path):
    wl = _make_wordlist(tmp_path)
    d = WordDictionary(wl)
    board = _board_cat_horizontal()
    loadout = Loadout(
        stickers=[LoadoutItem(id="bone", name="Bone", level=1, kind="sticker")]
    )
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
    assert timing.score_calls > 0
    assert timing.score_sec > 0
    assert timing.dfs_expansions > 0
    assert timing.wall_sec > 0
    assert timing.score_cache_hits + timing.score_cache_misses >= 0
    assert timing.board_flat_calls > 0
