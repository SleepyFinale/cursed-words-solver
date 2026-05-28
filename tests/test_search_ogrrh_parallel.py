"""Regression: parallel search on Q-heavy Axolotl board (OGRRH / MYRRH path)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cursed_words_solver.config import GAME_WORDLIST_PATH
from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
from cursed_words_solver.rules.stamp_behaviors import stamp_search_flags
from cursed_words_solver.search import PathValidator, WordSearcher
from cursed_words_solver.search_parallel import shutdown_search_pool, warmup_search_pool

FIXTURE = (
    Path(__file__).resolve().parent / "fixtures" / "boards" / "20260527_ogrrh_axolotl.json"
)
MYRRH_PATH = [7, 1, 5, 14, 19, 24]


@pytest.fixture(autouse=True)
def _reset_search_pool():
    yield
    shutdown_search_pool(wait=True)


def _board_and_loadout():
    if not FIXTURE.exists():
        pytest.skip("OGRRH board fixture required")
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    run_state = data["run_state"]
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    assert board is not None
    return board, loadout


@pytest.mark.skipif(
    not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024,
    reason="game wordlist required",
)
def test_myrrhy_path_valid():
    board, loadout = _board_and_loadout()
    d = WordDictionary(GAME_WORDLIST_PATH)
    flags = stamp_search_flags(loadout)
    v = PathValidator(d, min_len=1)
    assert v.word_ok(board, MYRRH_PATH, "myrrhy", flags)
    assert v.word_ok(board, MYRRH_PATH, "myrrh", flags)


@pytest.mark.skipif(
    not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024,
    reason="game wordlist required",
)
@pytest.mark.slow
def test_ogrrh_board_serial_search_finds_words():
    board, loadout = _board_and_loadout()
    d = WordDictionary(GAME_WORDLIST_PATH)
    searcher = WordSearcher(
        dictionary=d,
        min_len=1,
        max_len=25,
        time_budget=20.0,
        wordlist_path=GAME_WORDLIST_PATH,
        search_workers=1,
    )
    results = searcher.find_best_words(board, loadout, top_n=5)
    assert results, "serial search should find candidates on OGRRH board"


@pytest.mark.skipif(
    not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024,
    reason="game wordlist required",
)
@pytest.mark.slow
def test_ogrrh_board_parallel_search_finds_words():
    board, loadout = _board_and_loadout()
    d = WordDictionary(GAME_WORDLIST_PATH)
    warmup_search_pool(GAME_WORDLIST_PATH, 2)
    searcher = WordSearcher(
        dictionary=d,
        min_len=1,
        max_len=25,
        time_budget=25.0,
        wordlist_path=GAME_WORDLIST_PATH,
        search_workers=2,
    )
    results = searcher.find_best_words(board, loadout, top_n=5)
    assert results, "parallel search should find candidates (serial fallback / digit pass)"
    timing = searcher.last_search_timing
    assert timing is not None


@pytest.mark.skipif(
    not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024,
    reason="game wordlist required",
)
def test_myrrhy_path_scores_220():
    """Game accepted MYRRHY on path OGRRH6 (Full Moon R-teleport); pipeline must match."""
    from cursed_words_solver.rules.pipeline import ScoringPipeline
    from cursed_words_solver.suggestion import dictionary_word_for_path

    board, loadout = _board_and_loadout()
    d = WordDictionary(GAME_WORDLIST_PATH)
    pipeline = ScoringPipeline()
    aligned = dictionary_word_for_path(
        board,
        MYRRH_PATH,
        "ogrrh6",
        loadout,
        d,
        min_len=1,
        pipeline=pipeline,
    )
    assert aligned is not None
    assert "myrrh" in aligned
    score = pipeline.score_total_only(board, MYRRH_PATH, aligned, loadout)
    assert score == 220
