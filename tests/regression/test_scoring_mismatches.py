"""Regression tests from melmod scoring mismatch captures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
from cursed_words_solver.rules.pipeline import ScoringPipeline

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "mismatches"


@pytest.mark.parametrize(
    "case_path",
    sorted(FIXTURES.glob("*.json")),
    ids=lambda p: p.stem,
)
def test_scoring_mismatch(case_path: Path) -> None:
    data = json.loads(case_path.read_text(encoding="utf-8"))
    run_state = data.get("run_state_snapshot")
    if not run_state:
        pytest.fail(f"{case_path.name}: missing run_state_snapshot")

    word = data["word"]
    path = data["path"]
    expected = int(data["actual_score"])

    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    pipeline = ScoringPipeline()
    score, _bd = pipeline.score(board, path, word, loadout)
    assert int(score) == expected
