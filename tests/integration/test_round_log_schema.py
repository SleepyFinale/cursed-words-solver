"""Validate melmod per-round log JSON schema and helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cursed_words_solver.round_log import (
    derive_match_status,
    validate_round_log,
)

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "round_logs"


@pytest.mark.parametrize(
    (
        "solver_available",
        "path_matches",
        "path_prefix_extension",
        "board_matches",
        "predicted",
        "actual",
        "expected",
    ),
    [
        (False, False, False, True, 0, 0, "no_suggestion"),
        (True, False, False, True, 100, 100, "path_mismatch"),
        (True, False, True, True, 595, 920, "path_extension"),
        (True, False, True, False, 100, 100, "path_mismatch"),
        (True, True, False, True, 100, 90, "score_mismatch"),
        (True, True, False, True, 100, 100, "score_match"),
    ],
)
def test_derive_match_status(
    solver_available: bool,
    path_matches: bool,
    path_prefix_extension: bool,
    board_matches: bool,
    predicted: int,
    actual: int,
    expected: str,
) -> None:
    assert (
        derive_match_status(
            solver_available=solver_available,
            path_matches=path_matches,
            path_prefix_extension=path_prefix_extension,
            board_matches=board_matches,
            predicted_score=predicted,
            actual_score=actual,
        )
        == expected
    )


def test_sample_fixture_validates() -> None:
    path = FIXTURE_DIR / "sample_score_match.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert validate_round_log(data) == []
    assert data["match_status"] == "score_match"
    assert data["solver"]["available"] is True
    assert data["comparison"]["score_delta"] == 0


def test_validate_round_log_catches_missing_blocks() -> None:
    errors = validate_round_log({"schema_version": 2, "match_status": "bogus"})
    assert any("schema_version" in e for e in errors)
    assert any("match_status" in e for e in errors)
    assert any("solver" in e for e in errors)
