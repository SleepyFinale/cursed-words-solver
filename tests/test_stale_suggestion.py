"""Stale last_suggestion.json board fingerprint warnings."""

from __future__ import annotations

import json
from pathlib import Path

from cursed_words_solver.config import LAST_SUGGESTION_PATH
from cursed_words_solver.suggestion import stale_suggestion_warning


def test_stale_suggestion_warning_when_fingerprint_differs(tmp_path, monkeypatch):
    suggestion_path = tmp_path / "last_suggestion.json"
    monkeypatch.setattr(
        "cursed_words_solver.suggestion.LAST_SUGGESTION_PATH", suggestion_path
    )
    suggestion_path.write_text(
        json.dumps({"board_fingerprint": "board-a"}),
        encoding="utf-8",
    )
    msg = stale_suggestion_warning("board-b")
    assert msg is not None
    assert "different board" in msg.lower()


def test_stale_suggestion_warning_none_when_fingerprint_matches(tmp_path, monkeypatch):
    suggestion_path = tmp_path / "last_suggestion.json"
    monkeypatch.setattr(
        "cursed_words_solver.suggestion.LAST_SUGGESTION_PATH", suggestion_path
    )
    suggestion_path.write_text(
        json.dumps({"board_fingerprint": "same-board"}),
        encoding="utf-8",
    )
    assert stale_suggestion_warning("same-board") is None


def test_stale_suggestion_warning_none_when_no_file(tmp_path, monkeypatch):
    suggestion_path = tmp_path / "missing.json"
    monkeypatch.setattr(
        "cursed_words_solver.suggestion.LAST_SUGGESTION_PATH", suggestion_path
    )
    assert stale_suggestion_warning("any") is None
