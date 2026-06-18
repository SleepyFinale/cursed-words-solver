"""Replay submitted paths from melmod path_mismatch round logs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.search import WordSearcher
from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.config import GAME_WORDLIST_PATH
from cursed_words_solver.rules.stamp_behaviors import stamp_search_flags_mask
from cursed_words_solver.search import PathValidator
from tests.regression.test_scoring_mismatches import (
    _adjust_mutating_dna_extras,
    _run_state_for_replay,
)

ROUND_LOG_FIXTURES = sorted(
    (Path(__file__).resolve().parents[1] / "fixtures" / "round_logs").glob(
        "*_path_mismatch.json"
    )
)
FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "mismatches"
    / "20260615_181233_pow.json"
)
SPOOFERY_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "mismatches"
    / "20260615_193555_spoofery.json"
)
SPOOFERY_PATH = [17, 12, 13, 22, 23, 24, 18, 14]


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


@pytest.mark.skipif(not FIXTURE.exists(), reason="pow fixture required")
def test_pow_fixture_replay_submitted_path():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    score = _score_submitted(data)
    assert data["actual_score"] == 610
    assert score > int(data.get("predicted_score", 251) or 251)
    assert 608 <= score <= 616


@pytest.mark.skipif(not SPOOFERY_FIXTURE.exists(), reason="spoofery fixture required")
def test_spoofery_fixture_replay_submitted_path():
    data = json.loads(SPOOFERY_FIXTURE.read_text(encoding="utf-8"))
    score = _score_submitted(data)
    assert data["actual_score"] == 36
    assert score == 36


@pytest.mark.skipif(not SPOOFERY_FIXTURE.exists(), reason="spoofery fixture required")
def test_spoofery_search_finds_best_path():
    data = json.loads(SPOOFERY_FIXTURE.read_text(encoding="utf-8"))
    run_state = _run_state_for_replay(data)
    board = parse_board_from_run_state(run_state)
    assert board is not None
    loadout = parse_run_state(run_state)
    assert loadout is not None
    searcher = WordSearcher(
        dictionary=WordDictionary(GAME_WORDLIST_PATH),
        search_workers=8,
        time_budget=45.0,
    )
    results = searcher.find_best_words(board, loadout, top_n=5)
    assert results
    best = results[0]
    assert int(best.score) >= 36
    assert best.path == SPOOFERY_PATH
    validator = PathValidator(WordDictionary(GAME_WORDLIST_PATH))
    validator.quest_loadout = loadout
    flags = stamp_search_flags_mask(loadout)
    assert validator.word_ok(board, best.path, "spoofery", flags)


@pytest.mark.parametrize("round_log_path", ROUND_LOG_FIXTURES, ids=lambda p: p.stem)
def test_round_log_path_mismatch_replay_submitted_path(round_log_path: Path):
    data = json.loads(round_log_path.read_text(encoding="utf-8"))
    assert data.get("match_status") in ("path_mismatch", "path_extension")
    replay = _round_log_to_replay(data)
    score = _score_submitted(replay)
    f8_score = int((data.get("solver") or {}).get("predicted_score", 0))
    assert score > f8_score
    if "pow" in round_log_path.stem:
        assert replay["word"] == "pow"
        assert replay["path"] == [12, 7, 11]
        assert replay["actual_score"] == 610
        assert 608 <= score <= 616
