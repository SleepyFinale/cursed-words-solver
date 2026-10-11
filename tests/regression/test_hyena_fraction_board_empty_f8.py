"""Regression: Hyena fraction board must find words within F8 budget.

Round log 20260713_000552_853: F8 returned no_suggestion after ~731s DFS
(serial fallback, caps=[12..3]); player submitted stogy via $⅖OG⅖.
Root cause was long-first / max_len=25 caps on fraction boards (Bison
short-first excluded fractions) plus currency $ not mapping to S.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cursed_words_solver.config import ensure_wordlist
from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
from cursed_words_solver.rules.stamp_behaviors import stamp_search_flags_mask
from cursed_words_solver.search import PathValidator
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
