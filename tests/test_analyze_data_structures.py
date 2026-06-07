"""Tests for structure-analysis instrumentation (cache counters)."""

from __future__ import annotations

from pathlib import Path

from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.models import Loadout, LoadoutItem, board_flat_call_count, reset_board_flat_call_count
from cursed_words_solver.rules.chess_tiles import chess_attack_cache_stats, reset_chess_attack_cache_stats
from cursed_words_solver.search import WordSearcher
from tests.helpers.boards import _board_cat_horizontal, _make_wordlist


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
