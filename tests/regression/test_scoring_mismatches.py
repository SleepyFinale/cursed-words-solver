"""Regression tests from melmod scoring mismatch captures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
from cursed_words_solver.rules.pipeline import ScoringPipeline

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "mismatches"


def _run_state_for_replay(data: dict) -> dict:
    """Merge submit-time extras into the F8 snapshot so replay matches in-game scoring."""
    run_state = dict(data.get("run_state_snapshot") or {})
    extras = dict(run_state.get("extras") or {})
    extras.update(data.get("extras_snapshot") or {})
    if extras:
        run_state["extras"] = extras
    return run_state


def _money_from_actual_trace(data: dict) -> int | None:
    """Peak bank $ during scoring; F8 snapshot can be behind in-run earnings."""
    trace = data.get("actual_trace")
    if not isinstance(trace, list):
        return None
    peak = 0
    for step in trace:
        if isinstance(step, dict) and step.get("money") is not None:
            peak = max(peak, int(step["money"]))
    return peak if peak > 0 else None


@pytest.mark.parametrize(
    "case_path",
    sorted(FIXTURES.glob("*.json")),
    ids=lambda p: p.stem,
)
def test_scoring_mismatch(case_path: Path) -> None:
    data = json.loads(case_path.read_text(encoding="utf-8"))
    run_state = _run_state_for_replay(data)
    if not run_state:
        pytest.fail(f"{case_path.name}: missing run_state_snapshot")

    word = data["word"]
    path = data["path"]
    expected = int(data["actual_score"])

    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    replay_money = _money_from_actual_trace(data)
    if replay_money is not None:
        board.money = max(board.money, replay_money)
        loadout.money = max(loadout.money, replay_money)
    pipeline = ScoringPipeline()
    score, _bd = pipeline.score(board, path, word, loadout)
    assert int(score) == expected
