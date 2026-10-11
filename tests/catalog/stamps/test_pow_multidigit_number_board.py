"""Regression: letter word 'pow' on multi-digit number face (11/2/3 path)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.helpers.replay import engine_replay_score

FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "mismatches"
    / "20260615_181233_pow.json"
)


def _score_fixture() -> int:
    return engine_replay_score(json.loads(FIXTURE.read_text(encoding="utf-8")))


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
