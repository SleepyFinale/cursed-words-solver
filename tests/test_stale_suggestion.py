"""Stale last_suggestion.json board fingerprint warnings."""

from __future__ import annotations

import json
from pathlib import Path

from cursed_words_solver.suggestion import (
    clear_stale_last_suggestion_if_loadout_changed,
    stale_suggestion_warning,
)


def _patch_suggestion_path(tmp_path: Path, monkeypatch) -> Path:
    suggestion_path = tmp_path / "last_suggestion.json"
    monkeypatch.setattr(
        "cursed_words_solver.suggestion.LAST_SUGGESTION_PATH", suggestion_path
    )
    return suggestion_path


def test_stale_suggestion_warning_board_mismatch(tmp_path, monkeypatch):
    suggestion_path = _patch_suggestion_path(tmp_path, monkeypatch)
    suggestion_path.write_text(
        json.dumps(
            {
                "board_fingerprint": "board-a",
                "loadout_fingerprint": "same-loadout",
            }
        ),
        encoding="utf-8",
    )
    msg = stale_suggestion_warning(
        "board-b", current_loadout_fp="same-loadout"
    )
    assert msg is not None
    assert "board changed" in msg.lower()
    assert "f8" in msg.lower()
    assert "f7" not in msg.lower()


def test_stale_suggestion_warning_loadout_mismatch(tmp_path, monkeypatch):
    suggestion_path = _patch_suggestion_path(tmp_path, monkeypatch)
    suggestion_path.write_text(
        json.dumps(
            {
                "board_fingerprint": "board-a",
                "loadout_fingerprint": "old-loadout",
            }
        ),
        encoding="utf-8",
    )
    msg = stale_suggestion_warning(
        "board-b", current_loadout_fp="new-loadout"
    )
    assert msg is not None
    assert "different run" in msg.lower()
    assert "f8" in msg.lower()


def test_stale_suggestion_warning_none_when_fingerprint_matches(tmp_path, monkeypatch):
    suggestion_path = _patch_suggestion_path(tmp_path, monkeypatch)
    suggestion_path.write_text(
        json.dumps({"board_fingerprint": "same-board"}),
        encoding="utf-8",
    )
    assert stale_suggestion_warning("same-board") is None


def test_stale_suggestion_warning_none_when_no_file(tmp_path, monkeypatch):
    _patch_suggestion_path(tmp_path, monkeypatch)
    assert stale_suggestion_warning("any") is None


def test_clear_stale_last_suggestion_when_loadout_changes(tmp_path, monkeypatch):
    suggestion_path = _patch_suggestion_path(tmp_path, monkeypatch)
    suggestion_path.write_text(
        json.dumps({"loadout_fingerprint": "old"}),
        encoding="utf-8",
    )
    assert clear_stale_last_suggestion_if_loadout_changed("new") is True
    assert not suggestion_path.exists()


def test_clear_stale_last_suggestion_no_op_when_loadout_matches(tmp_path, monkeypatch):
    suggestion_path = _patch_suggestion_path(tmp_path, monkeypatch)
    suggestion_path.write_text(
        json.dumps({"loadout_fingerprint": "same"}),
        encoding="utf-8",
    )
    assert clear_stale_last_suggestion_if_loadout_changed("same") is False
    assert suggestion_path.exists()


def test_clear_stale_last_suggestion_no_op_when_no_file(tmp_path, monkeypatch):
    _patch_suggestion_path(tmp_path, monkeypatch)
    assert clear_stale_last_suggestion_if_loadout_changed("any") is False
