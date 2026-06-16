"""Round-log path validation helper."""

from __future__ import annotations

import json
from pathlib import Path

from cursed_words_solver.debug_path import (
    format_validation_report,
    path_from_round_log,
    validate_submitted_path,
)

_FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "mismatches"
    / "20260615_215449_poetcraft.json"
)
_JUXTALITTORAL_FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "mismatches"
    / "20260615_231647_juxtalittoral.json"
)
_POETCRAFT_PATH = [8, 2, 7, 6, 11, 16, 22, 17, 12]
_JUXTALITTORAL_PATH = [16, 10, 6, 0, 1, 2, 17, 22, 23, 19, 13, 8, 12]


def test_validate_poetcraft_fixture_accepted() -> None:
    data = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    report = validate_submitted_path(
        {"run_state_snapshot": data["run_state_snapshot"]},
        _POETCRAFT_PATH,
    )
    assert report.accepted
    assert report.dictionary_word == "poetcraft"
    assert report.quest_allowed
    assert report.predicted_score > 0
    text = format_validation_report(report)
    assert "poetcraft" in text


def test_validate_juxtalittoral_fixture_accepted() -> None:
    data = json.loads(_JUXTALITTORAL_FIXTURE.read_text(encoding="utf-8"))
    report = validate_submitted_path(
        {"run_state_snapshot": data["run_state_snapshot"]},
        _JUXTALITTORAL_PATH,
    )
    assert report.accepted
    assert report.quest_allowed
    assert report.search_accepted
    assert report.predicted_score > 0
    text = format_validation_report(report)
    assert "accepted: True" in text


def test_path_from_round_log_shape() -> None:
    data = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    wrapped = {
        "actual": {"path": data["path"], "word": data["word"]},
        "run_state": data["run_state_snapshot"],
    }
    assert path_from_round_log(wrapped) == _POETCRAFT_PATH
