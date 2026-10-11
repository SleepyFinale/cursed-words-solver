"""Mutating DNA on number-board paths (game MutatingDNA.ApplyTileBonus parity)."""

from __future__ import annotations

import json
from pathlib import Path


from tests.helpers.replay import engine_replay_score

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "mismatches"


def _score_fixture(fixture_name: str) -> int:
    return engine_replay_score(json.loads((FIXTURES / fixture_name).read_text(encoding="utf-8")))


def test_tweens_mutating_dna_sequential_within_word():
    """Regression: tweens second e gets +1 scaled by multipliers → 13930 total."""
    score = _score_fixture("20260629_212650.json")
    assert int(score) == 13930


