"""Regression: Cursedle probes must hit the concentrated solution tile core.

Live miss (2026-08-09): probes ABOHMS / DIRER / KNAVE / BUROO walked the red
ring around joker→snake→knight→queen and never stepped on those tiles. The
final guess used the same four tiles as ACHE in the wrong order.

Correct storage path: [15, 21, 14, 22].
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cursed_words_solver.cursedle_solver import (
    CURSEDLE_DICT_FILTER_MAX_CANDIDATES,
    _narrow_candidates_to_dictionary,
    _pick_probe_path,
    _untested_hot_tiles,
    filter_candidates,
    load_fairy_solution_dictionary,
    parse_cursedle_guesses,
)
from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.loadout import parse_board_from_run_state

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "cursedle" / "20260809_ache_path_order.json"
SOLUTION_CORE = {14, 15, 21, 22}


@pytest.fixture(scope="module")
def ache_board_and_guesses():
    if not FIXTURE.is_file():
        pytest.skip("ACHE path-order fixture missing")
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    board = parse_board_from_run_state(data)
    assert board is not None
    guesses = parse_cursedle_guesses(data.get("extras") or {})
    assert len(guesses) >= 3
    return board, guesses


def _dict_candidates(board, guesses):
    fairy, _warn = load_fairy_solution_dictionary()
    feedback = filter_candidates(board, guesses)
    if len(feedback) > CURSEDLE_DICT_FILTER_MAX_CANDIDATES:
        pytest.skip("candidate pool too large for dict narrowing in this environment")
    return _narrow_candidates_to_dictionary(board, feedback, fairy), fairy


def test_ache_hot_tiles_are_solution_core_after_two_probes(ache_board_and_guesses) -> None:
    board, all_guesses = ache_board_and_guesses
    candidates, _fairy = _dict_candidates(board, all_guesses[:2])
    assert len(candidates) > 1
    from cursed_words_solver.cursedle_solver import _tested_tile_indices

    hot = _untested_hot_tiles(candidates, _tested_tile_indices(board, all_guesses[:2]))
    assert SOLUTION_CORE <= hot


def test_ache_probe_after_two_guesses_hits_solution_core(ache_board_and_guesses) -> None:
    board, all_guesses = ache_board_and_guesses
    candidates, fairy = _dict_candidates(board, all_guesses[:2])
    dictionary = WordDictionary()
    picked = _pick_probe_path(
        board,
        candidates,
        dictionary,
        all_guesses[:2],
        solution_dictionary=fairy,
    )
    assert picked is not None
    path, _word = picked
    assert set(path) & SOLUTION_CORE, f"probe {path} missed solution core"


def test_ache_probe_after_three_guesses_hits_solution_core(ache_board_and_guesses) -> None:
    board, all_guesses = ache_board_and_guesses
    candidates, fairy = _dict_candidates(board, all_guesses[:3])
    dictionary = WordDictionary()
    picked = _pick_probe_path(
        board,
        candidates,
        dictionary,
        all_guesses[:3],
        solution_dictionary=fairy,
    )
    assert picked is not None
    path, _word = picked
    assert set(path) & SOLUTION_CORE, f"probe {path} missed solution core"
