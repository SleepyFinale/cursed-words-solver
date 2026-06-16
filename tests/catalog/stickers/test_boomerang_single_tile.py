"""Boomerang word_starts_ends_number on single-tile number paths."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
from cursed_words_solver.models import Board, CurseType, Tile, TileColor
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.scoring_conditions import path_starts_ends_number
from tests.regression.test_scoring_mismatches import (
    _adjust_birthday_cake_pre_word_extras,
    _adjust_mutating_dna_extras,
    _run_state_for_replay,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "mismatches"
BOOMERANG_FIXTURE = "20260615_190913.json"


def _score_fixture(fixture_name: str) -> int:
    data = json.loads((FIXTURES / fixture_name).read_text(encoding="utf-8"))
    run_state = _run_state_for_replay(data)
    board = parse_board_from_run_state(run_state)
    assert board is not None
    loadout = parse_run_state(run_state)
    assert loadout is not None
    _adjust_birthday_cake_pre_word_extras(
        run_state, data, board, data["path"], loadout
    )
    loadout = parse_run_state(run_state)
    _adjust_mutating_dna_extras(run_state, data, board, data["path"])
    loadout = parse_run_state(run_state)
    score, _ = ScoringPipeline().score(board, data["path"], data["word"], loadout)
    return int(score)


def test_path_starts_ends_number_single_number_tile():
    data = json.loads((FIXTURES / BOOMERANG_FIXTURE).read_text(encoding="utf-8"))
    run_state = _run_state_for_replay(data)
    board = parse_board_from_run_state(run_state)
    assert board is not None
    assert path_starts_ends_number(board, [0]) is True


def test_path_starts_ends_number_single_letter_tile():
    letter = Tile(0, 0, "A", "A", 2.0, TileColor.COLORLESS, CurseType.LETTER)
    board = Board(tiles=[[letter]])
    assert path_starts_ends_number(board, [0]) is False


def test_boomerang_single_tile_number_board_score():
    assert _score_fixture(BOOMERANG_FIXTURE) == 124
