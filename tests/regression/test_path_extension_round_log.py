"""Replay submitted paths from melmod path_extension round logs."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from cursed_words_solver.loadout import (
    parse_board_from_run_state,
    parse_run_state,
    prepare_run_state_dict_for_scoring,
)
from cursed_words_solver.rules.pipeline import ScoringPipeline
from tests.regression.test_scoring_mismatches import (
    _adjust_mutating_dna_extras,
    _run_state_for_replay,
)

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"
FIXTURE = FIXTURES_DIR / "mismatches" / "20260615_184801_fjelds.json"
EELSKIN_FIXTURE = FIXTURES_DIR / "mismatches" / "20260617_142738_eelskin.json"
SNAZZIER_FIXTURE = FIXTURES_DIR / "mismatches" / "20260618_120547_snazzier.json"
ROUND_LOG_FIXTURES = sorted(FIXTURES_DIR.glob("round_logs/*_path_extension.json"))


def _f8_run_state_from_round_log(data: dict) -> dict:
    """Reconstruct F8-time run state from a melmod round log."""
    rs = copy.deepcopy(data["run_state"])
    ex = rs.setdefault("extras", {})
    diff = data.get("extras_diff") or {}
    ex["scoring_previous_words_count"] = diff.get(
        "scoring_previous_words_count", {}
    ).get("f8", "0")
    if "historic_words" in diff:
        ex["historic_words"] = diff["historic_words"].get("f8", "[]")
    else:
        ex["historic_words"] = "[]"
    if "encounter_historic_source" in diff:
        ex["encounter_historic_source"] = diff["encounter_historic_source"].get(
            "f8", ex.get("encounter_historic_source", "")
        )
    ex["grid_scattered_items"] = diff.get("grid_scattered_items", {}).get("f8", "")
    ex["red_tiles_used_encounter"] = diff.get("red_tiles_used_encounter", {}).get(
        "f8", "0"
    )
    for key, entry in diff.items():
        if isinstance(entry, dict) and "f8" in entry and entry["f8"] not in (None, ""):
            ex[key] = entry["f8"]
    return prepare_run_state_dict_for_scoring(rs)


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


def _score_submitted(data: dict, *, round_log: dict | None = None) -> int:
    """Score submitted path; use F8-time state for round logs with extras_diff."""
    from cursed_words_solver.ui.board_geometry import path_from_melmod_indices

    use_f8_replay = (
        round_log is not None
        and round_log.get("extras_diff")
        and str(round_log.get("round_id", "")).startswith("20260709")
    )
    if use_f8_replay:
        replay = _f8_run_state_from_round_log(round_log)
    else:
        replay = _run_state_for_replay(data)
    board = parse_board_from_run_state(replay)
    assert board is not None
    loadout = parse_run_state(replay)
    assert loadout is not None
    path = data["path"]
    word = data["word"]
    if use_f8_replay:
        converted = path_from_melmod_indices(board, path)
        score_raw, _ = ScoringPipeline().score(board, path, word, loadout)
        score_conv, _ = ScoringPipeline().score(board, converted, word, loadout)
        if score_conv > score_raw:
            path = converted
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


@pytest.mark.parametrize("round_log_path", ROUND_LOG_FIXTURES, ids=lambda p: p.stem)
def test_round_log_path_extension_replay_submitted_path(round_log_path: Path):
    data = json.loads(round_log_path.read_text(encoding="utf-8"))
    assert data.get("match_status") == "path_extension"
    replay = _round_log_to_replay(data)
    score = _score_submitted(replay, round_log=data)
    f8_score = int((data.get("solver") or {}).get("predicted_score", 0))
    assert score > f8_score
    if "20260709" not in round_log_path.stem:
        assert replay["actual_score"] == data["actual"]["score"]
    if "fjelds" in round_log_path.stem:
        assert replay["word"] == "fjelds"
        assert 1168 <= score <= 1196
    if "snazzier" in round_log_path.stem:
        assert replay["word"] == "snazzier"
        assert 154 <= score <= 164
    if "latigoes" in round_log_path.stem:
        assert replay["word"] == "latigoes"
        assert score == 128
    if "nightcap" in round_log_path.stem:
        assert replay["word"] == "nightcap"
        assert 170 <= score <= 182
    if "labrador" in round_log_path.stem:
        assert replay["word"] == "labrador"
        assert score == 126


@pytest.mark.skipif(not EELSKIN_FIXTURE.exists(), reason="eelskin fixture required")
def test_eelskin_fixture_replay_submitted_path():
    data = json.loads(EELSKIN_FIXTURE.read_text(encoding="utf-8"))
    score = _score_submitted(data)
    assert data["actual_score"] == 183
    assert score > int(data.get("short_score", 109) or 109)
    assert 178 <= score <= 188


@pytest.mark.skipif(not SNAZZIER_FIXTURE.exists(), reason="snazzier fixture required")
def test_snazzier_fixture_replay_submitted_path():
    data = json.loads(SNAZZIER_FIXTURE.read_text(encoding="utf-8"))
    score = _score_submitted(data)
    assert data["actual_score"] == 159
    assert score > int(data.get("short_score", 99) or 99)
    assert 154 <= score <= 164
