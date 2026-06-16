"""Regression: letter word 'pow' on multi-digit number face (11/2/3 path)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
from cursed_words_solver.rules.pipeline import ScoringPipeline
from tests.regression.test_scoring_mismatches import (
    _adjust_mutating_dna_extras,
    _run_state_for_replay,
)

FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "mismatches"
    / "20260615_181233_pow.json"
)


def _score_fixture() -> int:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    run_state = _run_state_for_replay(data)
    board = parse_board_from_run_state(run_state)
    assert board is not None
    loadout = parse_run_state(run_state)
    assert loadout is not None
    _adjust_mutating_dna_extras(run_state, data, board, data["path"])
    loadout = parse_run_state(run_state)
    score, _ = ScoringPipeline().score(
        board, data["path"], data["word"], loadout
    )
    return int(score)


@pytest.mark.skipif(not FIXTURE.exists(), reason="fixture required")
def test_pow_multidigit_number_board_score():
    score = _score_fixture()
    # In-game 610; solver may be +6 on Mutating DNA pre-submit counts.
    assert 608 <= score <= 616


@pytest.mark.skipif(not FIXTURE.exists(), reason="fixture required")
def test_pow_beats_f8_single_tile_suggestion():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert data["actual_score"] == 610
    score = _score_fixture()
    assert score > 251
    assert score >= 600
