"""Regression: cursed Bison number board must find short letter words.

Round log 20260712_231504_312: F8 returned no_suggestion after ~52s DFS;
player submitted reen (R→E→E→N, OOV for our wordlist). Root cause was
max_len=25 + number-wildcard branching exhausting the budget before short
in-dictionary letter words were found.
"""

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
from cursed_words_solver.search_parallel import shutdown_search_pool
from cursed_words_solver.ui.board_geometry import path_from_melmod_indices

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "round_logs"
    / "20260712_231504_312.json"
)
SUBMITTED_WORD = "reen"
SUBMITTED_MELMOD_PATH = [17, 18, 19, 14]


@pytest.fixture(scope="module")
def bison_board_loadout():
    if not FIXTURE.exists():
        pytest.skip("bison number-board round-log fixture required")
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    board = parse_board_from_run_state(data["run_state"])
    loadout = parse_run_state(data["run_state"])
    assert board is not None and loadout is not None
    return board, loadout, data


def test_submitted_reen_path_is_playable(bison_board_loadout):
    """Submitted path is adjacent letter tiles; game accepted reen (may be OOV for us)."""
    board, loadout, data = bison_board_loadout
    dictionary = WordDictionary(ensure_wordlist())
    path = path_from_melmod_indices(board, SUBMITTED_MELMOD_PATH)
    assert data["actual"]["word"] == SUBMITTED_WORD
    assert len(path) == 4
    letters = [
        (board.get_by_index(i).letter or board.get_by_index(i).char or "").lower()
        for i in path
    ]
    assert "".join(letters) == SUBMITTED_WORD
    # If our wordlist includes reen, validator must accept the path.
    if dictionary.contains(SUBMITTED_WORD):
        validator = PathValidator(dictionary, min_len=3)
        validator.quest_loadout = loadout
        flags = stamp_search_flags_mask(loadout)
        assert validator.word_ok(board, path, SUBMITTED_WORD, flags)
