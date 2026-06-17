"""Replay submitted paths from melmod path_extension round logs."""

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

ROUND_LOG = Path(
    r"C:\Users\TheMi\.cursed_words_solver\round_logs\20260615_184801_748.json"
)
FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "mismatches"
    / "20260615_184801_fjelds.json"
)
EELSKIN_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "mismatches"
    / "20260617_142738_eelskin.json"
)


def _round_log_to_replay(data: dict) -> dict:
    """Normalize melmod round-log JSON into mismatch-replay shape."""
    solver = data.get("solver") or {}
    actual = data.get("actual") or {}
    return {
        "word": actual.get("word"),
        "path": actual.get("path"),
        "actual_score": actual.get("score"),
        "predicted_score": solver.get("predicted_score"),
        "board_fingerprint": solver.get("board_fingerprint"),
        "loadout_fingerprint": solver.get("loadout_fingerprint"),
        "run_state_snapshot": data.get("run_state"),
        "actual_trace": actual.get("trace"),
        "match_status": data.get("match_status"),
        "short_path": solver.get("path"),
        "short_word": solver.get("word"),
        "short_score": solver.get("predicted_score"),
    }


def _score_submitted(data: dict) -> int:
    replay = _run_state_for_replay(data)
    board = parse_board_from_run_state(replay)
    assert board is not None
    loadout = parse_run_state(replay)
    assert loadout is not None
    path = data["path"]
    word = data["word"]
    _adjust_mutating_dna_extras(replay, data, board, path)
    loadout = parse_run_state(replay)
    score, _ = ScoringPipeline().score(board, path, word, loadout)
    return int(score)


@pytest.mark.skipif(not FIXTURE.exists(), reason="fjelds fixture required")
def test_fjelds_fixture_replay_submitted_path():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    score = _score_submitted(data)
    assert data["actual_score"] == 1170
    assert score > int(data.get("short_score", 1146) or 1146)
    assert 1168 <= score <= 1196


@pytest.mark.skipif(not ROUND_LOG.exists(), reason="round log required")
def test_round_log_path_extension_replay_submitted_path():
    data = json.loads(ROUND_LOG.read_text(encoding="utf-8"))
    assert data.get("match_status") == "path_extension"
    replay = _round_log_to_replay(data)
    assert replay["word"] == "fjelds"
    assert replay["path"] == [8, 12, 17, 21, 16, 20]
    assert replay["short_path"] == [8, 12, 17, 21, 16]
    score = _score_submitted(replay)
    f8_score = int((data.get("solver") or {}).get("predicted_score", 0))
    assert f8_score == 1146
    assert score > f8_score
    assert replay["actual_score"] == 1170
    assert 1168 <= score <= 1196


@pytest.mark.skipif(not EELSKIN_FIXTURE.exists(), reason="eelskin fixture required")
def test_eelskin_fixture_replay_submitted_path():
    data = json.loads(EELSKIN_FIXTURE.read_text(encoding="utf-8"))
    score = _score_submitted(data)
    assert data["actual_score"] == 183
    assert score > int(data.get("short_score", 109) or 109)
    assert 178 <= score <= 188
