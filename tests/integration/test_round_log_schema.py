"""Validate melmod per-round log JSON schema and helpers."""

from __future__ import annotations

import json
from pathlib import Path


from cursed_words_solver.round_log import validate_round_log

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "round_logs"


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
