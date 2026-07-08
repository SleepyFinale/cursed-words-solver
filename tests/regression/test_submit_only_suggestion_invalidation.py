"""Regression tests for submit-only suggestion invalidation guards."""

from __future__ import annotations

import json

from cursed_words_solver.round_log import round_log_entries_are_word_submits
from cursed_words_solver import suggestion


def test_round_log_entries_ignore_non_submit_rows() -> None:
    rows = [
        {"round_id": "20260708_120000_001"},
        {"round_id": "20260708_120001_002", "submitted_word": "", "match_status": "score_match"},
        {"round_id": "20260708_120002_003", "submitted_word": "gast", "match_status": "unknown"},
    ]
    assert not round_log_entries_are_word_submits(rows)


def test_round_log_entries_detect_submit_rows() -> None:
    rows = [
        {"round_id": "20260708_120003_004", "submitted_word": "gast", "match_status": "score_match"},
    ]
    assert round_log_entries_are_word_submits(rows)


def test_poll_invalidate_clears_on_wordlist_signature_drift(
    tmp_path, monkeypatch
) -> None:
    last_path = tmp_path / "last_suggestion.json"
    blocked_path = tmp_path / "last_suggestion_blocked.json"
    monkeypatch.setattr(suggestion, "LAST_SUGGESTION_PATH", last_path)
    monkeypatch.setattr(suggestion, "LAST_SUGGESTION_BLOCKED_PATH", blocked_path)
    last_path.write_text(
        json.dumps(
            {
                "board_fingerprint": "board",
                "loadout_fingerprint": "loadout",
                "wordlist_signature": "game_words.txt|10|100",
            }
        ),
        encoding="utf-8",
    )

    reason = suggestion.poll_invalidate_last_suggestion(
        run_state_extras={},
        current_board_fp="board",
        current_loadout_fp="loadout",
        current_wordlist_sig=("game_words.txt", 11, 100),
    )

    assert reason == "wordlist changed"
    assert not last_path.exists()
