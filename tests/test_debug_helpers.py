"""Tests for debugging helpers."""

from __future__ import annotations

from cursed_words_solver.f8_messages import gather_block_reason
from cursed_words_solver.known_failing import is_known_failing, known_failing_stems
from cursed_words_solver.suggestion import f8_should_block_save
from cursed_words_solver.trace_compare import compare_traces
from cursed_words_solver.triage import triage_capture


def test_gather_block_reason_specific_field():
    assert gather_block_reason(["tile_ninja_consumables_used"]) == (
        "gather_incomplete:tile_ninja_consumables_used"
    )
    assert gather_block_reason([]) == "gather_incomplete"


def test_f8_should_block_save_gather_missing():
    blocked, reason = f8_should_block_save(
        gather_succeeded=False,
        gather_missing=["historic_words"],
    )
    assert blocked
    assert reason == "gather_incomplete:historic_words"


def test_known_failing_registry_loads():
    stems = known_failing_stems()
    assert "20260605_173757" in stems
    assert is_known_failing("20260605_173757")


def test_compare_traces_detects_tile_drift():
    pred = [{"phase": "rule", "rule_id": "oden", "tile_scores": [1, 2], "word_score": 0}]
    actual = [{"item_name": "Oden", "tile_scores": [1, 3], "word_bonus": 0}]
    diff = compare_traces(pred, actual)
    assert diff.has_divergence
    assert "tile_scores" in diff.summary


def test_triage_known_failing_fixture():
    result = triage_capture({}, stem="20260605_173757")
    assert result.category == "replay_gap"
