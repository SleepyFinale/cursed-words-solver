"""Boomerang word_starts_ends_number on single-tile number paths."""

from __future__ import annotations

import json
from pathlib import Path


from tests.helpers.replay import engine_replay_score

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "mismatches"
BOOMERANG_FIXTURE = "20260615_190913.json"


def _score_fixture(fixture_name: str) -> int:
    return engine_replay_score(json.loads((FIXTURES / fixture_name).read_text(encoding="utf-8")))


def test_boomerang_single_tile_number_board_score():
    assert _score_fixture(BOOMERANG_FIXTURE) == 124
