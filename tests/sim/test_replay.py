"""Replay harness tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from cursed_words_solver.sim.replay import replay_fixtures_dir, replay_reward_tier

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "round_logs"


def test_replay_sample_score_match_schema_only():
    path = FIXTURES / "sample_score_match.json"
    if not path.is_file():
        pytest.skip("fixture missing")
    import json

    data = json.loads(path.read_text(encoding="utf-8"))
    ok, msg = replay_reward_tier(data)
    assert msg in ("empty board", "ok") or ok


def test_replay_round_logs_dir():
    if not FIXTURES.is_dir():
        pytest.skip("no round_logs fixtures")
    report = replay_fixtures_dir(FIXTURES)
    assert report.total >= 1
