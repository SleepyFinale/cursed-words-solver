"""Stale F8 workflow drift detection and poll invalidation."""

from __future__ import annotations

import json
from pathlib import Path

from cursed_words_solver.suggestion import (
    has_played_word_since_f8_embed,
    poll_invalidate_last_suggestion,
    poll_invalidation_is_workflow_stale,
    workflow_stale_vs_f8_snapshot,
)


def test_workflow_stale_detects_letter_mismatch():
    f8 = {
        "previous_word_first_letter": "y",
        "scoring_previous_words_count": "3",
        "historic_words": "[]",
    }
    live = {
        "previous_word_first_letter": "t",
        "scoring_previous_words_count": "1",
        "historic_words": "[]",
    }
    reason = workflow_stale_vs_f8_snapshot(live, f8)
    assert reason is not None
    assert "previous word letter y→t" in reason
    assert "scoring previous words count" not in reason


def test_workflow_stale_spc_forward_advance_only():
    f8 = {"scoring_previous_words_count": "0", "historic_words": "[]"}
    live = {"scoring_previous_words_count": "1", "historic_words": "[]"}
    reason = workflow_stale_vs_f8_snapshot(live, f8)
    assert reason is not None
    assert "scoring previous words count 0→1" in reason

    backward = workflow_stale_vs_f8_snapshot(f8, live)
    assert backward is None


def test_has_played_word_since_f8_embed_mirrors_melmod():
    embed = {"scoring_previous_words_count": "0", "historic_words": "[]"}
    live = {"scoring_previous_words_count": "1", "historic_words": "[]"}
    assert has_played_word_since_f8_embed(live, embed)
    assert not has_played_word_since_f8_embed(embed, live)


def test_workflow_stale_ignores_matching_extras():
    extras = {
        "previous_word_first_letter": "a",
        "scoring_previous_words_count": "2",
        "historic_words": '[{"word":"test","score":1}]',
    }
    assert workflow_stale_vs_f8_snapshot(extras, dict(extras)) is None


def test_poll_invalidation_is_workflow_stale_prefix():
    assert poll_invalidation_is_workflow_stale("workflow drift (historic words changed)")
    assert not poll_invalidation_is_workflow_stale("loadout changed")
    assert not poll_invalidation_is_workflow_stale(None)


def test_poll_invalidate_clears_on_workflow_forward_advance_same_board(
    tmp_path, monkeypatch
):
    board_fp = (
        "8|4,0:₲/currency/colorless;4,1:¥/currency/colorless;"
        "4,2:N/letter/colorless;4,3:A/letter/colorless;4,4:฿/currency/colorless;"
        "3,0:T/letter/colorless;3,1:R/letter/colorless;3,2:B/letter/colorless;"
        "3,3:A/letter/colorless;3,4:I/letter/colorless;2,0:A/letter/colorless;"
        "2,1:€/currency/colorless;2,2:M/letter/colorless;2,3:₱/currency/colorless;"
        "2,4:E/letter/colorless;1,0:A/letter/colorless;1,1:U/letter/colorless;"
        "1,2:D/letter/colorless;1,3:A/letter/colorless;1,4:J/letter/colorless;"
        "0,0:€/currency/colorless;0,1:M/letter/colorless;0,2:N/letter/colorless;"
        "0,3:T/letter/colorless;0,4:₭/currency/colorless;"
    )
    suggestion_path = tmp_path / "last_suggestion.json"
    monkeypatch.setattr(
        "cursed_words_solver.suggestion.LAST_SUGGESTION_PATH",
        suggestion_path,
    )
    payload = {
        "word": "game",
        "path": [11, 5, 1, 6],
        "predicted_score": 200,
        "board_fingerprint": board_fp,
        "loadout_fingerprint": "test-loadout",
        "run_state_snapshot": {
            "extras": {
                "scoring_previous_words_count": "0",
                "historic_words": "[]",
            }
        },
    }
    suggestion_path.write_text(json.dumps(payload), encoding="utf-8")

    live_extras = {
        "scoring_previous_words_count": "1",
        "historic_words": "[]",
    }
    reason = poll_invalidate_last_suggestion(
        live_extras,
        current_board_fp=board_fp,
        current_loadout_fp="test-loadout",
    )
    assert reason is not None
    assert poll_invalidation_is_workflow_stale(reason)
    assert not suggestion_path.exists()


def test_poll_invalidate_no_clear_when_embed_matches_live_game_export(
    tmp_path, monkeypatch,
):
    """After embed fix, matching game export must not false-clear on poll."""
    board_fp = "8|0,0:A/letter/colorless;"
    suggestion_path = tmp_path / "last_suggestion.json"
    monkeypatch.setattr(
        "cursed_words_solver.suggestion.LAST_SUGGESTION_PATH",
        suggestion_path,
    )
    extras = {
        "scoring_previous_words_count": "1",
        "historic_words": "[]",
    }
    payload = {
        "word": "game",
        "path": [0],
        "predicted_score": 200,
        "board_fingerprint": board_fp,
        "loadout_fingerprint": "test-loadout",
        "run_state_snapshot": {"extras": dict(extras)},
    }
    suggestion_path.write_text(json.dumps(payload), encoding="utf-8")

    reason = poll_invalidate_last_suggestion(
        dict(extras),
        current_board_fp=board_fp,
        current_loadout_fp="test-loadout",
    )
    assert reason is None
    assert suggestion_path.exists()


def test_poll_invalidate_no_clear_on_spc_backward_drift_same_board(
    tmp_path, monkeypatch
):
    """Split-brain embed (low spc) vs live game export must not false-clear."""
    board_fp = "8|0,0:A/letter/colorless;"
    suggestion_path = tmp_path / "last_suggestion.json"
    monkeypatch.setattr(
        "cursed_words_solver.suggestion.LAST_SUGGESTION_PATH",
        suggestion_path,
    )
    payload = {
        "word": "game",
        "path": [0],
        "predicted_score": 200,
        "board_fingerprint": board_fp,
        "loadout_fingerprint": "test-loadout",
        "run_state_snapshot": {
            "extras": {
                "scoring_previous_words_count": "0",
                "historic_words": "[]",
            }
        },
    }
    suggestion_path.write_text(json.dumps(payload), encoding="utf-8")

    live_extras = {
        "scoring_previous_words_count": "1",
        "historic_words": "[]",
    }
    # Embed spc=0 vs live spc=1 without forward advance from embed baseline:
    # has_played_word is True (0→1), so this clears — that's correct when user
    # played a word after F8. False-positive case is embed=1 live=1 after fix.
    # Test backward: embed=1, live=0 must not clear.
    payload["run_state_snapshot"]["extras"]["scoring_previous_words_count"] = "1"
    suggestion_path.write_text(json.dumps(payload), encoding="utf-8")
    live_extras["scoring_previous_words_count"] = "0"

    reason = poll_invalidate_last_suggestion(
        live_extras,
        current_board_fp=board_fp,
        current_loadout_fp="test-loadout",
    )
    assert reason is None
    assert suggestion_path.exists()
