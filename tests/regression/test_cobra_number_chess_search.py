"""Regression: Cobra min-len 8 board with number start + chess captures (20260708)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cursed_words_solver.config import ensure_wordlist
from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
from cursed_words_solver.rules.boss_effects import boss_word_constraints
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.stamp_behaviors import stamp_search_flags_mask
from cursed_words_solver.search import PathValidator, WordSearcher
from cursed_words_solver.ui.board_geometry import path_from_melmod_indices

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "round_logs"
    / "20260708_220259_005.json"
)
SUBMITTED_WORD = "duumvirates"
SUBMITTED_MELMOD_PATH = [3, 9, 4, 0, 1, 6, 11, 17, 18, 14, 13]


@pytest.fixture(scope="module")
def cobra_board_loadout():
    if not FIXTURE.exists():
        pytest.skip("cobra number+chess round-log fixture required")
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    board = parse_board_from_run_state(data["run_state"])
    loadout = parse_run_state(data["run_state"])
    assert board is not None and loadout is not None
    return board, loadout, data


def test_cobra_min_len_is_eight(cobra_board_loadout):
    _board, loadout, _data = cobra_board_loadout
    rules = ScoringPipeline().rules
    constraints = boss_word_constraints(loadout, rules, default_max_len=25)
    assert constraints.min_len == 8


def test_submitted_path_is_valid(cobra_board_loadout):
    board, loadout, data = cobra_board_loadout
    dictionary = WordDictionary(ensure_wordlist())
    path = path_from_melmod_indices(board, SUBMITTED_MELMOD_PATH)
    assert data["actual"]["word"] == SUBMITTED_WORD
    validator = PathValidator(dictionary, min_len=8)
    validator.quest_loadout = loadout
    flags = stamp_search_flags_mask(loadout)
    assert dictionary.contains(SUBMITTED_WORD)
    assert validator.word_ok(board, path, SUBMITTED_WORD, flags)


def test_find_best_words_finds_words_serial(cobra_board_loadout):
    board, loadout, _data = cobra_board_loadout
    rules = ScoringPipeline().rules
    constraints = boss_word_constraints(loadout, rules, default_max_len=25)
    dictionary = WordDictionary(ensure_wordlist())
    searcher = WordSearcher(
        dictionary=dictionary,
        min_len=constraints.min_len,
        max_len=min(25, constraints.max_len),
        time_budget=60.0,
        search_workers=1,
    )
    results = searcher.find_best_words(board, loadout, top_n=5)
    assert results, "search must find at least one valid word on Cobra number+chess board"
    timing = searcher.last_search_timing
    assert timing is not None
    assert timing.score_calls > 0


@pytest.mark.skipif(
    not FIXTURE.exists(),
    reason="cobra number+chess fixture required",
)
def test_find_best_words_finds_words_parallel(cobra_board_loadout):
    board, loadout, _data = cobra_board_loadout
    rules = ScoringPipeline().rules
    constraints = boss_word_constraints(loadout, rules, default_max_len=25)
    dictionary = WordDictionary(ensure_wordlist())
    searcher = WordSearcher(
        dictionary=dictionary,
        min_len=constraints.min_len,
        max_len=min(25, constraints.max_len),
        time_budget=60.0,
        search_workers=8,
    )
    results = searcher.find_best_words(board, loadout, top_n=3)
    assert results, "parallel search must find words on Cobra number+chess board"
