"""Cursophobia search miss: F8 jato (+placed T on chess) vs jade/jaded.

Under Cursophobia, DFS used to expand onto chess ``?`` tiles. Those 26-way
wildcard explosions starved the shiny-J letter branch, so board-only search
topped out at joe/jor (~52). Consumable boost then placed T on the rook and
suggested jato (53). The player submitted jade (54) / jaded (56) without
placement.

Fix: prune quest-forbidden neighbors during expansion so letter paths win.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cursed_words_solver.config import GAME_WORDLIST_PATH
from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
from cursed_words_solver.rules.boss_effects import boss_word_constraints
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.quest_effects import quest_path_allowed
from cursed_words_solver.search import WordSearcher
from cursed_words_solver.ui.board_geometry import path_from_melmod_indices
from tests.regression.test_path_mismatch_round_log import _f8_run_state_from_extras_diff

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "round_logs"
    / "20260816_232600_025_jade_path_mismatch.json"
)

F8_WORD = "jato"
F8_SCORE = 53
SUBMITTED_WORD = "jade"
SUBMITTED_SCORE = 54
JADED_SCORE = 56


@pytest.fixture(scope="module")
def jade_board_loadout():
    if not FIXTURE.exists():
        pytest.skip("jade path_mismatch fixture required")
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    run_state = _f8_run_state_from_extras_diff(data)
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    assert board is not None and loadout is not None
    return data, board, loadout


@pytest.mark.skipif(not FIXTURE.exists(), reason="jade fixture required")
def test_jade_path_is_quest_allowed(jade_board_loadout):
    data, board, loadout = jade_board_loadout
    path = path_from_melmod_indices(board, data["actual"]["path"])
    assert quest_path_allowed(board, path, loadout=loadout)
    score, _ = ScoringPipeline().score(board, path, SUBMITTED_WORD, loadout)
    assert int(score) == SUBMITTED_SCORE


@pytest.mark.skipif(
    not FIXTURE.exists() or not GAME_WORDLIST_PATH.exists(),
    reason="jade fixture and game wordlist required",
)
def test_cursophobia_search_finds_jade_over_f8_jato(jade_board_loadout):
    _data, board, loadout = jade_board_loadout
    rules = ScoringPipeline().rules
    constraints = boss_word_constraints(loadout, rules, default_max_len=25)
    searcher = WordSearcher(
        dictionary=WordDictionary(GAME_WORDLIST_PATH),
        min_len=max(constraints.min_len, 3),
        max_len=constraints.max_len,
        search_workers=8,
        time_budget=15.0,
    )
    results = searcher.find_best_words(board, loadout, top_n=5)
    assert results, "search should find words on jade Cursophobia board"
    top = results[0]
    assert int(top.score) >= JADED_SCORE or (
        top.word == SUBMITTED_WORD and int(top.score) >= SUBMITTED_SCORE
    )
    assert int(top.score) > F8_SCORE
    assert top.word != F8_WORD
    words = {r.word for r in results}
    assert SUBMITTED_WORD in words or "jaded" in words
