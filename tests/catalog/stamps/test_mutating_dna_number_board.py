"""Mutating DNA on number-board paths (game MutatingDNA.ApplyTileBonus parity)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.scoring_conditions import (
    apply_mutating_dna_bonus,
    tile_string_representation,
)
from tests.regression.test_scoring_mismatches import (
    _adjust_birthday_cake_pre_word_extras,
    _adjust_mutating_dna_extras,
    _run_state_for_replay,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "mismatches"


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


def test_tile_string_representation_number():
    data = json.loads((FIXTURES / "20260615_174109.json").read_text(encoding="utf-8"))
    run_state = _run_state_for_replay(data)
    board = parse_board_from_run_state(run_state)
    assert board is not None
    tile = board.get_by_index(22)
    assert tile_string_representation(tile) == "1"
    assert tile_string_representation(tile, for_word_validity=True) == "!"


def test_mutating_dna_first_use_no_bonus():
    data = json.loads((FIXTURES / "20260615_174109.json").read_text(encoding="utf-8"))
    run_state = _run_state_for_replay(data)
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    assert board is not None and loadout is not None
    loadout.extras["mutating_dna_letter_counts"] = "{}"
    tile_scores = [12.0]
    tile_bonus, word_bonus = apply_mutating_dna_bonus(
        board, [22], tile_scores, loadout
    )
    assert tile_bonus == 0.0
    assert word_bonus == 0.0
    assert tile_scores == [12.0]


@pytest.mark.parametrize(
    "fixture_name,expected",
    [
        ("20260615_174109.json", 24),
        ("20260615_174218.json", 26),
        ("20260615_174554.json", 105),
        ("20260615_175616.json", 139),
        ("20260615_175729.json", 38),
    ],
)
def test_mutating_dna_number_board_scores(fixture_name: str, expected: int):
    assert _score_fixture(fixture_name) == expected
