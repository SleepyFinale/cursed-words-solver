"""Dedicated regressions for 20260715 Cartwheeler trunc + Dusty/Circus finalize."""

import json
from pathlib import Path

import pytest

from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
from cursed_words_solver.engine.scorer import EngineScorer
from cursed_words_solver.rules.quest_scoring import effective_submit_score
from cursed_words_solver.ui.board_geometry import path_from_melmod_indices, path_to_melmod_indices
from tests.helpers.replay import FIXTURES, _replay_path, _run_state_for_replay

ROUND_LOGS = Path(__file__).resolve().parents[1] / "fixtures" / "round_logs"


@pytest.mark.parametrize(
    "stem,expected",
    [
        ("20260715_230936", 109),
        ("20260715_231128", 425),
    ],
)
def test_july15_scoring_mismatches(stem: str, expected: int) -> None:
    case_path = FIXTURES / f"{stem}.json"
    assert case_path.exists(), case_path
    data = json.loads(case_path.read_text(encoding="utf-8"))
    run_state = _run_state_for_replay(data)
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    path = _replay_path(board, data["path"])
    score, _ = EngineScorer().score(board, path, data["word"], loadout)
    assert int(effective_submit_score(score, loadout)) == expected == int(
        data["actual_score"]
    )


def test_amoeboa_path_mismatch_is_alternate_geometry() -> None:
    path = ROUND_LOGS / "20260715_231615_503_amoeboa_path_mismatch.json"
    if not path.exists():
        pytest.skip("amoeboa path_mismatch round log required")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data.get("match_status") == "path_mismatch"
    run_state = data.get("run_state_snapshot") or data.get("run_state")
    if run_state is None and isinstance(data.get("solver"), dict):
        run_state = data["solver"].get("run_state_snapshot")
    board = parse_board_from_run_state(run_state)
    assert board is not None
    sug = path_from_melmod_indices(board, data["solver"]["path"])
    sub = path_from_melmod_indices(board, data["actual"]["path"])
    assert sug != sub
    assert path_to_melmod_indices(board, sug) == data["solver"]["path"]
    assert path_from_melmod_indices(
        board, path_to_melmod_indices(board, sug)
    ) == sug
