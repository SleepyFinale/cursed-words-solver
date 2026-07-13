"""Regression: Hyena fraction board must find words within F8 budget.

Round log 20260713_000552_853: F8 returned no_suggestion after ~731s DFS
(serial fallback, caps=[12..3]); player submitted stogy via $⅖OG⅖.
Root cause was long-first / max_len=25 caps on fraction boards (Bison
short-first excluded fractions) plus currency $ not mapping to S.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from cursed_words_solver.config import ensure_wordlist
from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
from cursed_words_solver.models import CurseType
from cursed_words_solver.rules.boss_effects import boss_word_constraints
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.stamp_behaviors import stamp_search_flags_mask
from cursed_words_solver.search import (
    PathValidator,
    WordSearcher,
    _number_board_cap_sequence,
    resolve_letter,
)
from cursed_words_solver.search_parallel import shutdown_search_pool
from cursed_words_solver.ui.board_geometry import path_from_melmod_indices

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "round_logs"
    / "20260713_000552_853.json"
)
SUBMITTED_WORD = "stogy"
SUBMITTED_MELMOD_PATH = [6, 7, 8, 3, 2]


@pytest.fixture(scope="module")
def hyena_board_loadout():
    if not FIXTURE.exists():
        pytest.skip("hyena fraction-board round-log fixture required")
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    board = parse_board_from_run_state(data["run_state"])
    loadout = parse_run_state(data["run_state"])
    assert board is not None and loadout is not None
    return board, loadout, data


def test_currency_dollar_resolves_to_s(hyena_board_loadout):
    board, _loadout, _data = hyena_board_loadout
    dollar = next(
        t
        for t in board.flat
        if t.curse == CurseType.CURRENCY and (t.char == "$" or t.letter in ("$", "S"))
    )
    assert resolve_letter(dollar, 0) == "S"


def test_fraction_tiles_are_not_wildcard_hubs(hyena_board_loadout):
    """Fraction letter '?' must not trigger Full Moon joker-cluster seeding."""
    from cursed_words_solver.search import _wildcard_start_indices

    board, _loadout, _data = hyena_board_loadout
    assert any(t.curse == CurseType.FRACTION for t in board.flat)
    assert _wildcard_start_indices(board) == []


def test_submitted_stogy_path_is_playable(hyena_board_loadout):
    board, loadout, data = hyena_board_loadout
    dictionary = WordDictionary(ensure_wordlist())
    path = path_from_melmod_indices(board, SUBMITTED_MELMOD_PATH)
    assert data["actual"]["word"] == SUBMITTED_WORD
    assert len(path) == 5
    assert dictionary.contains(SUBMITTED_WORD)
    validator = PathValidator(dictionary, min_len=3)
    validator.quest_loadout = loadout
    flags = stamp_search_flags_mask(loadout)
    assert validator.word_ok(board, path, SUBMITTED_WORD, flags)


def test_find_best_words_finds_words_serial(hyena_board_loadout):
    board, loadout, _data = hyena_board_loadout
    rules = ScoringPipeline().rules
    constraints = boss_word_constraints(loadout, rules, default_max_len=25)
    dictionary = WordDictionary(ensure_wordlist())
    searcher = WordSearcher(
        dictionary=dictionary,
        min_len=max(3, constraints.min_len),
        max_len=min(25, constraints.max_len),
        time_budget=30.0,
        search_workers=1,
    )
    results = searcher.find_best_words(board, loadout, top_n=5)
    assert results, "serial search must find at least one word on Hyena fraction board"
    timing = searcher.last_search_timing
    assert timing is not None
    assert timing.letter_dfs_added > 0 or timing.score_calls > 0
    assert not timing.number_board_empty_diag
    assert timing.dfs_caps[:6] == (3, 4, 5, 6, 7, 8)
    assert timing.dfs_caps != (12, 11, 10, 9, 8, 7, 6, 5, 4, 3)


def test_find_best_words_finds_words_parallel(hyena_board_loadout):
    board, loadout, _data = hyena_board_loadout
    rules = ScoringPipeline().rules
    constraints = boss_word_constraints(loadout, rules, default_max_len=25)
    dictionary = WordDictionary(ensure_wordlist())
    searcher = WordSearcher(
        dictionary=dictionary,
        min_len=max(3, constraints.min_len),
        max_len=min(25, constraints.max_len),
        time_budget=60.0,
        search_workers=8,
    )
    try:
        t0 = time.monotonic()
        results = searcher.find_best_words(board, loadout, top_n=5)
        elapsed = time.monotonic() - t0
        assert results, "parallel F8-like search must find words on Hyena fraction board"
        timing = searcher.last_search_timing
        assert timing is not None
        assert not timing.number_board_empty_diag
        assert timing.dfs_caps[:6] == (3, 4, 5, 6, 7, 8)
        assert elapsed < 70.0, f"parallel search took {elapsed:.1f}s (expected <70s)"
    finally:
        shutdown_search_pool()


def test_number_board_cap_sequence_still_short_first():
    assert _number_board_cap_sequence(3, 25)[:6] == [3, 4, 5, 6, 7, 8]
