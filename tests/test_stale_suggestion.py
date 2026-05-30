"""Stale last_suggestion.json board fingerprint warnings."""

from __future__ import annotations

import json
from pathlib import Path

from cursed_words_solver.suggestion import (
    _mutating_dna_letter_counts_equal,
    clear_stale_last_suggestion_if_context_changed,
    clear_stale_last_suggestion_if_loadout_changed,
    stale_suggestion_warning,
)


def _is_same_submit_bicycle_increment(
    extras_diff: dict[str, dict[str, str]],
    delta: int,
    *,
    per_card: int = 1,
) -> bool:
    """Mirror melmod IsSameSubmitBicycleIncrement."""
    if delta <= 0:
        return False
    if per_card <= 0:
        per_card = 1

    suited = 0
    entry = extras_diff.get("bicycle_suited_on_path")
    if entry:
        try:
            suited = int(str(entry.get("submit", "") or ""))
        except ValueError:
            suited = 0

    if suited <= 0:
        return False
    return delta == suited * per_card


def _stale_f8_extras_note(
    extras_diff: dict[str, dict[str, str]],
    *,
    per_card: int = 1,
) -> str | None:
    """Mirror melmod ExtrasDiffHelper stale-key rules (post fix)."""
    notes: list[str] = []
    for key in ("cards_submitted", "bicycle_word_score_bonus"):
        entry = extras_diff.get(key)
        if not entry:
            continue
        f8_raw = str(entry.get("f8", "") or "")
        submit_raw = str(entry.get("submit", "") or "")
        try:
            f8_val = int(f8_raw)
            submit_val = int(submit_raw)
        except ValueError:
            if not f8_raw and submit_raw:
                notes.append(f"{key} f8=(empty) submit={submit_raw}")
            continue
        if submit_val > f8_val:
            if not _is_same_submit_bicycle_increment(
                extras_diff, submit_val - f8_val, per_card=per_card
            ):
                notes.append(f"{key} f8={f8_val} submit={submit_val}")

    if entry := extras_diff.get("historic_words"):
        f8_raw = str(entry.get("f8", "") or "").strip()
        submit_raw = str(entry.get("submit", "") or "").strip()
        if f8_raw != submit_raw and (f8_raw or submit_raw):
            notes.append("historic_words changed")

    if entry := extras_diff.get("mutating_dna_letter_counts"):
        f8_raw = str(entry.get("f8", "") or "")
        submit_raw = str(entry.get("submit", "") or "")
        if not _mutating_dna_letter_counts_equal(f8_raw, submit_raw):
            notes.append("mutating_dna_letter_counts changed")

    if entry := extras_diff.get("previous_word_first_letter"):
        f8_raw = str(entry.get("f8", "") or "").strip()
        submit_raw = str(entry.get("submit", "") or "").strip()
        if f8_raw and submit_raw and f8_raw.lower() != submit_raw.lower():
            notes.append(
                f"previous_word_first_letter f8='{f8_raw}' submit='{submit_raw}'"
            )

    if not notes:
        return None
    return "F8 snapshot stale — " + "; ".join(notes)


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


def test_stale_suggestion_warning_loadout_on_same_board(tmp_path, monkeypatch):
    suggestion_path = _patch_suggestion_path(tmp_path, monkeypatch)
    suggestion_path.write_text(
        json.dumps(
            {
                "board_fingerprint": "same-board",
                "loadout_fingerprint": "old-loadout",
            }
        ),
        encoding="utf-8",
    )
    msg = stale_suggestion_warning(
        "same-board", current_loadout_fp="new-loadout"
    )
    assert msg is not None
    assert "loadout changed" in msg.lower()
    assert "f8" in msg.lower()


def test_clear_stale_last_suggestion_when_extras_drift(tmp_path, monkeypatch):
    suggestion_path = _patch_suggestion_path(tmp_path, monkeypatch)
    suggestion_path.write_text(
        json.dumps(
            {
                "board_fingerprint": "same-board",
                "run_state_snapshot": {
                    "extras": {"bicycle_word_score_bonus": "22"},
                },
            }
        ),
        encoding="utf-8",
    )
    assert clear_stale_last_suggestion_if_context_changed(
        "same-board",
        run_state_extras={"bicycle_word_score_bonus": "23"},
    )
    assert not suggestion_path.exists()


def test_clear_stale_last_suggestion_no_op_when_board_differs(tmp_path, monkeypatch):
    suggestion_path = _patch_suggestion_path(tmp_path, monkeypatch)
    suggestion_path.write_text(
        json.dumps(
            {
                "board_fingerprint": "old-board",
                "run_state_snapshot": {
                    "extras": {"bicycle_word_score_bonus": "22"},
                },
            }
        ),
        encoding="utf-8",
    )
    assert not clear_stale_last_suggestion_if_context_changed(
        "new-board",
        run_state_extras={"bicycle_word_score_bonus": "23"},
    )
    assert suggestion_path.exists()


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


def test_mutating_dna_counts_equal_ignores_key_order():
    assert _mutating_dna_letter_counts_equal('{"a":1,"b":2}', '{"b":2,"a":1}')
    assert not _mutating_dna_letter_counts_equal('{"a":1}', '{"a":2}')


def test_clear_stale_when_mutating_dna_drift(tmp_path, monkeypatch):
    suggestion_path = _patch_suggestion_path(tmp_path, monkeypatch)
    suggestion_path.write_text(
        json.dumps(
            {
                "board_fingerprint": "same-board",
                "run_state_snapshot": {
                    "extras": {"mutating_dna_letter_counts": '{"a":1}'},
                },
            }
        ),
        encoding="utf-8",
    )
    assert clear_stale_last_suggestion_if_context_changed(
        "same-board",
        run_state_extras={"mutating_dna_letter_counts": '{"a":2}'},
    )
    assert not suggestion_path.exists()


def test_clear_stale_no_op_when_mutating_dna_json_equivalent(tmp_path, monkeypatch):
    suggestion_path = _patch_suggestion_path(tmp_path, monkeypatch)
    suggestion_path.write_text(
        json.dumps(
            {
                "board_fingerprint": "same-board",
                "run_state_snapshot": {
                    "extras": {"mutating_dna_letter_counts": '{"a":1,"b":2}'},
                },
            }
        ),
        encoding="utf-8",
    )
    assert not clear_stale_last_suggestion_if_context_changed(
        "same-board",
        run_state_extras={"mutating_dna_letter_counts": '{"b":2,"a":1}'},
    )
    assert suggestion_path.exists()


def test_stale_f8_mirror_suited_on_path_alone_not_stale():
    note = _stale_f8_extras_note(
        {"bicycle_suited_on_path": {"f8": "", "submit": "2"}}
    )
    assert note is None


def test_stale_f8_mirror_loadout_fingerprint_alone_not_stale():
    note = _stale_f8_extras_note(
        {
            "loadout_fingerprint": {
                "f8": "",
                "submit": "Char|1|stickers|stamps|-|pin:left|30",
            }
        }
    )
    assert note is None


def test_stale_f8_mirror_cards_submitted_higher_is_stale():
    note = _stale_f8_extras_note(
        {"cards_submitted": {"f8": "30", "submit": "32"}}
    )
    assert note is not None
    assert "cards_submitted f8=30 submit=32" in note


def test_stale_f8_mirror_bicycle_delta_equals_suited_not_stale():
    note = _stale_f8_extras_note(
        {
            "cards_submitted": {"f8": "34", "submit": "37"},
            "bicycle_suited_on_path": {"f8": "", "submit": "3"},
        }
    )
    assert note is None


def test_stale_f8_mirror_bicycle_delta_without_matching_suited_is_stale():
    note = _stale_f8_extras_note(
        {
            "cards_submitted": {"f8": "34", "submit": "37"},
            "bicycle_suited_on_path": {"f8": "", "submit": "1"},
        },
        per_card=1,
    )
    assert note is not None
    assert "cards_submitted f8=34 submit=37" in note


def test_stale_f8_mirror_bicycle_per_card_times_suited_not_stale():
    note = _stale_f8_extras_note(
        {
            "cards_submitted": {"f8": "39", "submit": "41"},
            "bicycle_suited_on_path": {"f8": "", "submit": "1"},
        },
        per_card=2,
    )
    assert note is None


def test_stale_f8_mirror_bicycle_per_card_one_delta_two_still_stale():
    note = _stale_f8_extras_note(
        {
            "cards_submitted": {"f8": "39", "submit": "41"},
            "bicycle_suited_on_path": {"f8": "", "submit": "1"},
        },
        per_card=1,
    )
    assert note is not None
    assert "cards_submitted f8=39 submit=41" in note
