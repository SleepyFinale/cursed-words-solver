"""Stale last_suggestion.json board fingerprint warnings."""

from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from cursed_words_solver.models import Loadout
from cursed_words_solver.suggestion import (
    F8_EXPORT_CATCHUP_GRACE_SEC,
    f8_export_catchup_grace_sec,
    _historic_words_count,
    _last_historic_word_first_letter,
    _mutating_dna_letter_counts_equal,
    clear_stale_last_suggestion_if_context_changed,
    clear_stale_last_suggestion_if_loadout_changed,
    clear_stale_last_suggestion_if_fingerprint_changed,
    clear_stale_last_suggestion_if_workflow_changed,
    empty_historic_on_later_grid_warning,
    fingerprint_invalidate_suppressed_for_post_f8_export,
    f8_prior_suggestion_stale_note,
    f8_should_block_save,
    grid_advanced_since_last_f8_warning,
    grid_one_historic_cache_mismatch_warning,
    grid_transition_workflow_bleed_warning,
    is_disk_catchup_drift,
    is_embed_stale_drift,
    loadout_needs_encounter_historic,
    loadout_needs_previous_word_letter,
    historic_previous_letter_mismatch_warning,
    is_export_catchup_drift,
    poll_invalidate_last_suggestion,
    run_state_historic_stale_warnings,
    stale_suggestion_warning,
    workflow_invalidate_suppressed_for_export_catchup,
    f8_prediction_workflow_stale_warning,
    workflow_stale_vs_f8_snapshot,
)
from cursed_words_solver.loadout import (
    parse_board_from_run_state,
    reconcile_encounter_historic_for_scoring,
    sanitize_run_state_snapshot_for_f8,
)


def _is_same_submit_bicycle_increment(
    extras_diff: dict[str, dict[str, str]],
    delta: int,
    *,
    per_card: int = 1,
    suited_on_path: int = -1,
) -> bool:
    """Mirror melmod IsSameSubmitBicycleIncrement."""
    if delta <= 0:
        return False
    if per_card <= 0:
        per_card = 1

    suited = suited_on_path
    if suited < 0:
        entry = extras_diff.get("bicycle_suited_on_path")
        if entry:
            try:
                suited = int(str(entry.get("submit", "") or ""))
            except ValueError:
                suited = 0

    if suited <= 0 and delta > 0 and delta % per_card == 0:
        inferred = delta // per_card
        if suited <= 0 or suited * per_card != delta:
            suited = inferred

    if suited <= 0:
        return False
    return delta == suited * per_card


def _try_parse_bicycle_acc(extras: dict[str, str]) -> int:
    for key in ("bicycle_word_score_bonus", "cards_submitted"):
        raw = extras.get(key)
        if raw is None:
            continue
        try:
            return max(0, int(raw))
        except (TypeError, ValueError):
            continue
    return -1


def _rewind_submit_bicycle_to_pre_word(
    submit_extras: dict[str, str],
    f8_extras: dict[str, str],
    suited_on_path: int,
    per_card: int,
) -> None:
    """Mirror melmod RewindSubmitBicycleToPreWord."""
    if per_card <= 0:
        per_card = 1
    f8_acc = _try_parse_bicycle_acc(f8_extras)
    if f8_acc < 0:
        return
    submit_acc = _try_parse_bicycle_acc(submit_extras)
    if submit_acc < 0 or submit_acc <= f8_acc:
        return
    delta = submit_acc - f8_acc
    suited = suited_on_path
    if delta > 0 and delta % per_card == 0:
        inferred = delta // per_card
        if suited <= 0 or suited * per_card != delta:
            suited = inferred
    if suited > 0 and delta == suited * per_card:
        pre = submit_acc - per_card * suited
        if pre >= 0:
            submit_extras["bicycle_word_score_bonus"] = str(pre)
            submit_extras["cards_submitted"] = str(pre)


def _merge_mutating_dna_for_stale_compare(
    merged: dict[str, str] | None,
    scoring_extras: dict[str, str] | None,
) -> None:
    """Mirror melmod MergeMutatingDnaForStaleCompare."""
    if merged is None or scoring_extras is None:
        return
    workflow_dna = str(merged.get("mutating_dna_letter_counts", "") or "")
    scoring_dna = str(scoring_extras.get("mutating_dna_letter_counts", "") or "")
    if _mutating_dna_letter_counts_equal(workflow_dna, scoring_dna):
        return
    if _is_empty_mutating_dna_json(workflow_dna) and not _is_empty_mutating_dna_json(
        scoring_dna
    ):
        merged["mutating_dna_letter_counts"] = scoring_dna


def _is_empty_mutating_dna_json(raw: str) -> bool:
    text = (raw or "").strip()
    return not text or text in ("{}", "[]")


def _prepare_extras_for_bicycle_stale_compare(
    workflow_extras: dict[str, str] | None,
    scoring_extras: dict[str, str] | None,
    f8_extras: dict[str, str] | None,
    *,
    suited_on_path: int = -1,
    per_card: int = 1,
) -> dict[str, str]:
    """Mirror melmod PrepareExtrasForBicycleStaleCompare."""
    merged = _merge_pin_derived_for_stale_check(workflow_extras, scoring_extras)
    _merge_mutating_dna_for_stale_compare(merged, scoring_extras)
    if not f8_extras:
        return merged
    if per_card <= 0:
        per_card = 1
    _rewind_submit_bicycle_to_pre_word(merged, f8_extras, suited_on_path, per_card)
    return merged


_PIN_DERIVED_STALE_KEYS = (
    "bicycle_word_score_bonus",
    "cards_submitted",
    "bicycle_suited_on_path",
)


def _merge_pin_derived_for_stale_check(
    workflow_extras: dict[str, str] | None,
    scoring_extras: dict[str, str] | None,
) -> dict[str, str]:
    """Mirror melmod MergePinDerivedExtrasForStaleCheck."""
    if workflow_extras:
        merged = dict(workflow_extras)
    elif scoring_extras:
        merged = dict(scoring_extras)
    else:
        merged = {}
    if not scoring_extras:
        return merged
    for key in _PIN_DERIVED_STALE_KEYS:
        if key in scoring_extras:
            merged[key] = scoring_extras[key] or ""
    return merged


def _stale_f8_extras_note(
    extras_diff: dict[str, dict[str, str]],
    *,
    per_card: int = 1,
    has_bicycle_pin: bool = True,
    has_mutating_dna_stamp: bool = True,
    score_matched: bool = False,
) -> str | None:
    """Mirror melmod ExtrasDiffHelper stale-key rules (post fix)."""
    notes: list[str] = []
    if has_bicycle_pin:
        for key in ("cards_submitted", "bicycle_word_score_bonus"):
            entry = extras_diff.get(key)
            if not entry:
                continue
            f8_raw = str(entry.get("f8", "") or "")
            submit_raw = str(entry.get("submit", "") or "")
            try:
                f8_val = int(f8_raw)
            except ValueError:
                if not f8_raw and submit_raw:
                    notes.append(f"{key} f8=(empty) submit={submit_raw}")
                elif f8_raw and not submit_raw:
                    notes.append(f"{key} f8={f8_raw} submit=(empty)")
                continue
            try:
                submit_val = int(submit_raw)
            except ValueError:
                if not submit_raw:
                    if f8_val == 0:
                        continue
                    notes.append(f"{key} f8={f8_val} submit=(empty)")
                    continue
                notes.append(f"{key} f8={f8_val} submit={submit_raw}")
                continue
            if submit_val > f8_val:
                delta = submit_val - f8_val
                if (
                    score_matched
                    and per_card > 0
                    and 0 < delta <= per_card
                    and delta % per_card == 0
                ):
                    continue
                if not _is_same_submit_bicycle_increment(
                    extras_diff, delta, per_card=per_card
                ):
                    notes.append(f"{key} f8={f8_val} submit={submit_val}")

    for key in ("tile_ninja_consumables_used", "tile_ninja_word_bonus_percent"):
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
            elif f8_raw and not submit_raw:
                notes.append(f"{key} f8={f8_raw} submit=(empty)")
            continue
        if submit_val > f8_val:
            notes.append(f"{key} f8={f8_val} submit={submit_val}")

    if entry := extras_diff.get("historic_words"):
        f8_raw = str(entry.get("f8", "") or "").strip()
        submit_raw = str(entry.get("submit", "") or "").strip()
        if f8_raw != submit_raw and (f8_raw or submit_raw):
            notes.append("historic_words changed")

    if has_mutating_dna_stamp:
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
    return "F8 snapshot stale â€” " + "; ".join(notes)


def test_tile_ninja_extras_drift_is_stale_f8():
    """Mismatch 20260619_011718: consumables_used 21â†’23 is workflow stale, not solver bug."""
    extras_diff = {
        "tile_ninja_consumables_used": {"f8": "21", "submit": "23"},
        "tile_ninja_word_bonus_percent": {"f8": "162", "submit": "166"},
    }
    note = _stale_f8_extras_note(extras_diff, has_bicycle_pin=False)
    assert note is not None
    assert "tile_ninja_consumables_used f8=21 submit=23" in note
    assert "tile_ninja_word_bonus_percent f8=162 submit=166" in note


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


def test_clear_stale_on_startup_board_fingerprint_mismatch(tmp_path, monkeypatch):
    """Startup path: board_fp drift clears last_suggestion once (no poll duplicate)."""
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
    cleared = clear_stale_last_suggestion_if_fingerprint_changed(
        "board-b",
        current_loadout_fp="same-loadout",
    )
    assert cleared is not None
    assert not suggestion_path.exists()
    assert poll_invalidate_last_suggestion(
        {},
        current_board_fp="board-b",
        current_loadout_fp="same-loadout",
    ) is None


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
        {
            "cards_submitted": {"f8": "30", "submit": "32"},
            "bicycle_suited_on_path": {"f8": "", "submit": "1"},
        }
    )
    assert note is not None
    assert "cards_submitted f8=30 submit=32" in note


def test_stale_f8_mirror_bicycle_f8_zero_submit_empty_not_stale():
    note = _stale_f8_extras_note(
        {
            "cards_submitted": {"f8": "0", "submit": ""},
            "bicycle_word_score_bonus": {"f8": "0", "submit": ""},
        }
    )
    assert note is None


def test_stale_f8_mirror_bicycle_merge_from_scoring_extras_not_stale():
    workflow = {
        "historic_words": "[]",
        "previous_word_first_letter": "f",
    }
    scoring = {
        "bicycle_word_score_bonus": "2",
        "cards_submitted": "2",
    }
    merged = _merge_pin_derived_for_stale_check(workflow, scoring)
    f8_extras = {
        "bicycle_word_score_bonus": "2",
        "cards_submitted": "2",
        "historic_words": "[]",
    }
    extras_diff = {
        k: {"f8": f8_extras.get(k, ""), "submit": merged.get(k, "")}
        for k in set(f8_extras) | set(merged)
    }
    note = _stale_f8_extras_note(extras_diff)
    assert note is None


def test_stale_f8_mirror_bicycle_f8_two_submit_empty_without_merge_is_stale():
    note = _stale_f8_extras_note(
        {
            "cards_submitted": {"f8": "2", "submit": ""},
            "bicycle_word_score_bonus": {"f8": "2", "submit": ""},
        }
    )
    assert note is not None


def test_stale_f8_mirror_capture_preseed_bicycle_live_pin_not_stale():
    """Mirror capture-time pre-seed: empty submit extras + live pin matching F8."""
    workflow = {
        "historic_words": "[]",
        "previous_word_first_letter": "f",
    }
    f8_extras = {
        "bicycle_word_score_bonus": "25",
        "cards_submitted": "25",
        "historic_words": "[]",
    }
    authoritative = dict(workflow)
    live_pin = "25"
    authoritative["bicycle_word_score_bonus"] = live_pin
    authoritative["cards_submitted"] = live_pin
    extras_diff = {
        k: {"f8": f8_extras.get(k, ""), "submit": authoritative.get(k, "")}
        for k in set(f8_extras) | set(authoritative)
    }
    note = _stale_f8_extras_note(extras_diff)
    assert note is None


def test_stale_f8_mirror_predicted_post_submit_bicycle_not_stale():
    """Post-submit scoring extras rewound to pre-word — f8=33 + 3 suited → submit 36."""
    f8_extras = {
        "bicycle_word_score_bonus": "33",
        "cards_submitted": "33",
        "historic_words": "[]",
    }
    preword = {
        "bicycle_word_score_bonus": "33",
        "cards_submitted": "33",
        "historic_words": "[]",
    }
    post_submit = {
        "bicycle_word_score_bonus": "36",
        "cards_submitted": "36",
        "bicycle_suited_on_path": "3",
        "historic_words": "[]",
    }
    merged = _prepare_extras_for_bicycle_stale_compare(
        preword, post_submit, f8_extras, suited_on_path=3, per_card=1
    )
    extras_diff = {
        k: {"f8": f8_extras.get(k, ""), "submit": merged.get(k, "")}
        for k in set(f8_extras) | set(merged)
    }
    note = _stale_f8_extras_note(extras_diff)
    assert note is None


def test_stale_f8_rewind_feisty_post_submit_not_stale():
    """Bones session feisty: f8=88, post-submit acc=90, 2 suited @ per_card=1."""
    f8_extras = {
        "bicycle_word_score_bonus": "88",
        "cards_submitted": "88",
    }
    preword = {"bicycle_word_score_bonus": "88", "cards_submitted": "88"}
    post_submit = {
        "bicycle_word_score_bonus": "90",
        "cards_submitted": "90",
        "bicycle_suited_on_path": "2",
    }
    merged = _prepare_extras_for_bicycle_stale_compare(
        preword, post_submit, f8_extras, suited_on_path=2, per_card=1
    )
    extras_diff = {
        k: {"f8": f8_extras.get(k, ""), "submit": merged.get(k, "")}
        for k in set(f8_extras) | set(merged)
    }
    assert _stale_f8_extras_note(extras_diff) is None


def test_stale_f8_rewind_acca_bicycle_fixture_not_stale():
    """Michael encounter acca: post-submit acc +2 @ per_card=2 is benign after rewind."""
    f8_extras = {
        "bicycle_word_score_bonus": "197",
        "cards_submitted": "197",
    }
    post_submit = {
        "bicycle_word_score_bonus": "199",
        "cards_submitted": "199",
        "bicycle_suited_on_path": "3",
    }
    merged = _prepare_extras_for_bicycle_stale_compare(
        dict(post_submit),
        dict(post_submit),
        f8_extras,
        suited_on_path=3,
        per_card=2,
    )
    extras_diff = {
        "bicycle_word_score_bonus": {
            "f8": "197",
            "submit": merged.get("bicycle_word_score_bonus", ""),
        },
        "cards_submitted": {
            "f8": "197",
            "submit": merged.get("cards_submitted", ""),
        },
        "bicycle_suited_on_path": {"f8": "", "submit": "3"},
    }
    assert _stale_f8_extras_note(extras_diff, per_card=2) is None


def test_acca_bicycle_stale_round_log_fixture():
    """Vendored 20260629_223913 acca capture: bicycle stale clears after rewind."""
    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "round_logs"
        / "20260629_223913_acca_bicycle_stale.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    diff = data["extras_diff"]
    f8_extras = {
        key: str(entry.get("f8", "") or "")
        for key, entry in diff.items()
        if key in ("bicycle_word_score_bonus", "cards_submitted")
    }
    submit_raw = {
        key: str(entry.get("submit", "") or "")
        for key, entry in diff.items()
        if key in ("bicycle_word_score_bonus", "cards_submitted", "bicycle_suited_on_path")
    }
    suited = int(submit_raw.get("bicycle_suited_on_path") or "0")
    merged = _prepare_extras_for_bicycle_stale_compare(
        submit_raw,
        submit_raw,
        f8_extras,
        suited_on_path=suited,
        per_card=2,
    )
    bicycle_diff = {
        key: {"f8": f8_extras.get(key, ""), "submit": merged.get(key, "")}
        for key in ("bicycle_word_score_bonus", "cards_submitted")
    }
    bicycle_diff["bicycle_suited_on_path"] = diff["bicycle_suited_on_path"]
    assert _stale_f8_extras_note(bicycle_diff, per_card=2) is None


_STALE_F8_BOSS_KEYS = (
    "boss_area_number",
    "boss_floor_modification",
    "boss_modifiers",
    "boss_modifier_floor_mods",
    "boss_id",
    "boss_cursed",
)


def _f8_extras_had_finale_boss_metadata(f8_extras: dict[str, str]) -> bool:
    probe = str(f8_extras.get("michael_finale_probe", "") or "")
    if "finale=1" in probe.lower():
        return True
    try:
        phase = int(str(f8_extras.get("michael_phase", "") or "").strip())
    except ValueError:
        phase = -1
    if phase >= 4:
        return True
    try:
        enc_min = int(str(f8_extras.get("encounter_min_word_length", "") or "").strip())
    except ValueError:
        enc_min = -1
    if enc_min >= 25:
        return True
    try:
        michael_min = int(str(f8_extras.get("michael_min_word_length", "") or "").strip())
    except ValueError:
        michael_min = -1
    return michael_min >= 25


def _is_benign_finale_boss_clear_drift(
    f8_extras: dict[str, str],
    submit_extras: dict[str, str],
) -> bool:
    if not _f8_extras_had_finale_boss_metadata(f8_extras):
        return False
    for key in _STALE_F8_BOSS_KEYS:
        f8_val = str(f8_extras.get(key, "") or "").strip()
        submit_val = str(submit_extras.get(key, "") or "").strip()
        if f8_val and submit_val:
            return False
    for key in (
        "michael_phase",
        "michael_min_word_length",
        "encounter_min_word_length",
        "michael_finale_probe",
        "michael_summoned_bosses_defeated",
    ):
        f8_val = str(f8_extras.get(key, "") or "").strip()
        submit_val = str(submit_extras.get(key, "") or "").strip()
        if f8_val and submit_val:
            return False
    return True


def _has_boss_extras_drift(
    extras_diff: dict[str, dict[str, str]],
    f8_extras: dict[str, str],
    submit_extras: dict[str, str],
) -> bool:
    if _is_benign_finale_boss_clear_drift(f8_extras, submit_extras):
        return False
    notes: list[str] = []
    for key in _STALE_F8_BOSS_KEYS:
        entry = extras_diff.get(key)
        if not entry:
            continue
        f8_val = str(entry.get("f8", "") or "").strip()
        submit_val = str(entry.get("submit", "") or "").strip()
        if f8_val != submit_val and (f8_val or submit_val):
            notes.append(key)
    return bool(notes)


def test_finale_boss_clear_drift_not_stale():
    """Post-Michael grid: F8 finale boss keys cleared on submit are benign."""
    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "round_logs"
        / "20260629_224652_finale_boss_stale.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    diff = data["extras_diff"]
    f8_extras = {key: str(entry.get("f8", "") or "") for key, entry in diff.items()}
    submit_extras = {key: str(entry.get("submit", "") or "") for key, entry in diff.items()}
    assert _is_benign_finale_boss_clear_drift(f8_extras, submit_extras)
    assert not _has_boss_extras_drift(diff, f8_extras, submit_extras)


def test_sanitize_run_state_strips_finale_boss_on_grid_advance():
    """F8 sanitize drops Michael finale embed when run_node_type is no longer Boss."""
    from cursed_words_solver.loadout import FINALE_BOSS_EMBED_KEYS

    run_state = {
        "boss_id": "michael",
        "boss_name": "Michael",
        "extras": {
            "run_node_type": "Normal",
            "grid_number": "2",
            "boss_area_number": "6",
            "boss_floor_modification": "3",
            "michael_phase": "4",
            "michael_min_word_length": "25",
            "michael_finale_probe": "finale=1,michael_boss=1",
        },
    }
    loadout = Loadout()
    sanitized = sanitize_run_state_snapshot_for_f8(run_state, loadout)
    extras = sanitized.get("extras") or {}
    for key in FINALE_BOSS_EMBED_KEYS + ("boss_area_number", "boss_floor_modification"):
        assert key not in extras
    assert sanitized.get("boss_id") == ""


def test_stale_f8_rewind_tinklers_post_submit_not_stale():
    """Bones session tinklers: f8=106, post-submit acc=107, 1 suited @ per_card=1."""
    f8_extras = {
        "bicycle_word_score_bonus": "106",
        "cards_submitted": "106",
    }
    preword = {"bicycle_word_score_bonus": "106", "cards_submitted": "106"}
    post_submit = {
        "bicycle_word_score_bonus": "107",
        "cards_submitted": "107",
        "bicycle_suited_on_path": "1",
    }
    merged = _prepare_extras_for_bicycle_stale_compare(
        preword, post_submit, f8_extras, suited_on_path=1, per_card=1
    )
    extras_diff = {
        k: {"f8": f8_extras.get(k, ""), "submit": merged.get(k, "")}
        for k in set(f8_extras) | set(merged)
    }
    assert _stale_f8_extras_note(extras_diff) is None


def test_stale_f8_rewind_invalid_per_card_increment_still_stale():
    """f8=106 submit=107 with per_card=3 is not a valid same-submit increment."""
    f8_extras = {
        "bicycle_word_score_bonus": "106",
        "cards_submitted": "106",
    }
    preword = {"bicycle_word_score_bonus": "106", "cards_submitted": "106"}
    post_submit = {
        "bicycle_word_score_bonus": "107",
        "cards_submitted": "107",
    }
    merged = _prepare_extras_for_bicycle_stale_compare(
        preword, post_submit, f8_extras, suited_on_path=1, per_card=3
    )
    extras_diff = {
        k: {"f8": f8_extras.get(k, ""), "submit": merged.get(k, "")}
        for k in set(f8_extras) | set(merged)
    }
    note = _stale_f8_extras_note(extras_diff, per_card=3)
    assert note is not None
    assert "bicycle_word_score_bonus f8=106 submit=107" in note


def test_poll_invalidate_clears_on_bicycle_fingerprint_drift(tmp_path, monkeypatch):
    from cursed_words_solver.suggestion import (
        LAST_SUGGESTION_PATH,
        poll_invalidate_last_suggestion,
    )

    path = tmp_path / "last_suggestion.json"
    monkeypatch.setattr("cursed_words_solver.suggestion.LAST_SUGGESTION_PATH", path)
    path.write_text(
        json.dumps(
            {
                "board_fingerprint": "board|same",
                "loadout_fingerprint": "Bones The Dog|5|postal_horn:2|joker:3|bicycle:left|88",
                "run_state_snapshot": {
                    "extras": {
                        "bicycle_word_score_bonus": "88",
                        "cards_submitted": "88",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    reason = poll_invalidate_last_suggestion(
        {"bicycle_word_score_bonus": "90", "cards_submitted": "90"},
        current_board_fp="board|same",
        current_loadout_fp="Bones The Dog|5|postal_horn:2|joker:3|bicycle:left|88",
    )
    assert reason is not None
    assert "bicycle drift" in reason
    assert not path.exists()


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


def test_stale_f8_score_match_per_card_bicycle_embed_not_stale():
    """abbey-style: post-word pin embed +1 while score matched (62→63, 5 suited on path)."""
    extras_diff = {
        "cards_submitted": {"f8": "62", "submit": "63"},
        "bicycle_word_score_bonus": {"f8": "62", "submit": "63"},
        "bicycle_suited_on_path": {"f8": "", "submit": "5"},
    }
    assert _stale_f8_extras_note(extras_diff) is not None
    assert _stale_f8_extras_note(extras_diff, score_matched=True) is None


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


def test_stale_f8_bicycle_keys_ignored_without_bicycle_pin():
    note = _stale_f8_extras_note(
        {
            "cards_submitted": {"f8": "203", "submit": ""},
            "bicycle_word_score_bonus": {"f8": "203", "submit": ""},
        },
        has_bicycle_pin=False,
    )
    assert note is None


def test_stale_f8_mutating_dna_ignored_without_stamp():
    note = _stale_f8_extras_note(
        {
            "mutating_dna_letter_counts": {
                "f8": '{"a":99}',
                "submit": "{}",
            }
        },
        has_mutating_dna_stamp=False,
    )
    assert note is None


def test_stale_f8_workflow_drift_still_detected_without_bicycle_pin():
    note = _stale_f8_extras_note(
        {
            "historic_words": {"f8": "", "submit": '[{"word":"foo"}]'},
            "previous_word_first_letter": {"f8": "y", "submit": "f"},
        },
        has_bicycle_pin=False,
        has_mutating_dna_stamp=False,
    )
    assert note is not None
    assert "historic_words changed" in note
    assert "previous_word_first_letter f8='y' submit='f'" in note


def test_merge_encounter_historic_for_f8_snapshot_from_disk(tmp_path, monkeypatch):
    from cursed_words_solver.loadout import (
        RUN_STATE_PATH,
        merge_encounter_historic_for_f8_snapshot,
    )

    run_state_path = tmp_path / "run_state.json"
    monkeypatch.setattr("cursed_words_solver.loadout.RUN_STATE_PATH", run_state_path)
    run_state_path.write_text(
        json.dumps(
            {
                "extras": {
                    "historic_words": '[{"word":"beedie","score":808}]',
                    "previous_word_first_letter": "b",
                    "grid_number": "2",
                }
            }
        ),
        encoding="utf-8",
    )
    embed = {
        "extras": {
            "historic_words": "",
            "previous_word_first_letter": "q",
            "grid_number": "2",
        }
    }
    merged = merge_encounter_historic_for_f8_snapshot(embed)
    assert merged is not None
    assert merged["extras"]["historic_words"] == ""
    assert merged["extras"]["previous_word_first_letter"] == "q"


def test_merge_encounter_historic_with_retry_live_only_no_disk_pull(
    tmp_path, monkeypatch
):
    """F8 solve uses live gather only — merge does not pull ahead-of-embed disk historic."""
    from cursed_words_solver.loadout import (
        RUN_STATE_PATH,
        merge_encounter_historic_for_f8_with_retry,
    )

    run_state_path = tmp_path / "run_state.json"
    monkeypatch.setattr("cursed_words_solver.loadout.RUN_STATE_PATH", run_state_path)
    run_state_path.write_text(
        json.dumps(
            {
                "extras": {
                    "historic_words": '[{"word":"prior","score":10}]',
                    "previous_word_first_letter": "p",
                    "grid_number": "2",
                    "encounter_historic_source": "live",
                }
            }
        ),
        encoding="utf-8",
    )
    embed = {
        "extras": {
            "historic_words": "",
            "grid_number": "2",
            "encounter_historic_source": "live",
        }
    }
    merged, stale = merge_encounter_historic_for_f8_with_retry(
        embed, max_retries=1, delay_sec=0
    )
    assert stale is None
    assert merged is not None
    hist = str(merged["extras"].get("historic_words", "") or "").strip()
    assert not hist or hist == "[]"


def test_describe_f8_historic_catchup_pissers_grid3(tmp_path, monkeypatch):
    from cursed_words_solver.loadout import (
        RUN_STATE_PATH,
        describe_f8_historic_catchup,
        merge_encounter_historic_for_f8_snapshot,
    )

    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "stale_f8_pissers_historic_catchup.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    run_state_path = tmp_path / "run_state.json"
    monkeypatch.setattr("cursed_words_solver.loadout.RUN_STATE_PATH", run_state_path)
    run_state_path.write_text(
        json.dumps({"extras": data["disk_extras"]}),
        encoding="utf-8",
    )
    embed = {"extras": dict(data["embed_extras"])}
    embed_hist = embed["extras"]["historic_words"]
    merged = merge_encounter_historic_for_f8_snapshot(embed)
    assert merged is not None
    merged_hist = merged["extras"]["historic_words"]
    assert merged_hist == embed_hist
    note = describe_f8_historic_catchup(
        embed_hist,
        merged_hist,
        grid_number=int(data["grid_number"]),
    )
    assert note is None


def test_f8_merge_before_score_loadout_and_telescope_score(tmp_path, monkeypatch):
    """F8 scores with live historic in gather state (no disk merge)."""
    from cursed_words_solver.loadout import (
        parse_run_state,
        prepare_run_state_dict_for_scoring,
    )
    from cursed_words_solver.models import Board, Loadout, LoadoutItem, Tile, TileColor
    from cursed_words_solver.rules.pipeline import ScoringPipeline

    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "stale_f8_pissers_historic_catchup.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    live_run_state = {"extras": dict(data["disk_extras"])}
    loadout = parse_run_state(prepare_run_state_dict_for_scoring(live_run_state))
    assert _historic_words_count(loadout.extras.get("historic_words", "")) == 2
    assert loadout.extras.get("red_tiles_used_encounter") == 6

    board = Board(
        tiles=[[None] * 5 for _ in range(5)],
        active=[True] * 25,
    )
    board.tiles[0][0] = Tile(
        row=0, col=0, char="A", letter="A", base_score=2, color=TileColor.RED
    )
    board.tiles[0][1] = Tile(
        row=0, col=1, char="B", letter="B", base_score=2, color=TileColor.RED
    )
    pipeline = ScoringPipeline()
    base = Loadout(
        stickers=[LoadoutItem(id="telescope", name="Telescope", level=2)],
    )
    stale_loadout = Loadout(
        stickers=list(base.stickers),
        extras=dict(data["embed_extras"]),
    )
    merged_loadout = Loadout(
        stickers=list(base.stickers),
        extras=dict(loadout.extras or {}),
    )
    stale_score, _ = pipeline.score(board, [0, 1], "ab", stale_loadout)
    merged_score, _ = pipeline.score(board, [0, 1], "ab", merged_loadout)
    assert stale_score != merged_score


def test_merge_encounter_historic_grid_advanced_stale_embed(tmp_path, monkeypatch):
    """recrafts round: embed marked grid_advanced but still had prior-grid historic."""
    from cursed_words_solver.loadout import (
        RUN_STATE_PATH,
        describe_f8_historic_catchup,
        merge_encounter_historic_for_f8_snapshot,
    )

    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "stale_f8_recrafts_grid_advance.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    run_state_path = tmp_path / "run_state.json"
    monkeypatch.setattr("cursed_words_solver.loadout.RUN_STATE_PATH", run_state_path)
    run_state_path.write_text(
        json.dumps({"extras": data["disk_extras"]}),
        encoding="utf-8",
    )
    embed = {"extras": dict(data["embed_extras"])}
    embed_hist = embed["extras"]["historic_words"]
    merged = merge_encounter_historic_for_f8_snapshot(embed)
    assert merged is not None
    merged_hist = merged["extras"]["historic_words"]
    assert merged_hist == embed_hist
    note = describe_f8_historic_catchup(
        embed_hist,
        merged_hist,
        grid_number=int(data["grid_number"]),
    )
    assert note is None


def test_merge_encounter_historic_prefers_shorter_fresh_on_grid_advance(
    tmp_path, monkeypatch
):
    from cursed_words_solver.loadout import (
        RUN_STATE_PATH,
        merge_encounter_historic_for_f8_snapshot,
    )

    run_state_path = tmp_path / "run_state.json"
    monkeypatch.setattr("cursed_words_solver.loadout.RUN_STATE_PATH", run_state_path)
    run_state_path.write_text(
        json.dumps(
            {
                "extras": {
                    "historic_words": '[{"word":"iliacus","score":880}]',
                    "grid_number": "2",
                }
            }
        ),
        encoding="utf-8",
    )
    embed = {
        "extras": {
            "historic_words": '[{"word":"a"},{"word":"b"},{"word":"c"},{"word":"d"}]',
            "grid_number": "2",
        }
    }
    merged = merge_encounter_historic_for_f8_snapshot(embed)
    assert merged is not None
    assert merged["extras"]["historic_words"] == embed["extras"]["historic_words"]


def test_merge_encounter_historic_prefers_longer_fresh_when_missing_word(
    tmp_path, monkeypatch
):
    from cursed_words_solver.loadout import (
        RUN_STATE_PATH,
        merge_encounter_historic_for_f8_snapshot,
    )

    run_state_path = tmp_path / "run_state.json"
    monkeypatch.setattr("cursed_words_solver.loadout.RUN_STATE_PATH", run_state_path)
    two_words = (
        '[{"word":"iliacus","score":880},'
        '{"word":"teepee","score":492,"red_tile_count":1}]'
    )
    run_state_path.write_text(
        json.dumps({"extras": {"historic_words": two_words, "grid_number": "3"}}),
        encoding="utf-8",
    )
    embed = {
        "extras": {
            "historic_words": '[{"word":"iliacus","score":880}]',
            "grid_number": "3",
        }
    }
    merged = merge_encounter_historic_for_f8_snapshot(embed)
    assert merged is not None
    assert merged["extras"]["historic_words"] == embed["extras"]["historic_words"]


def test_sanitize_run_state_snapshot_strips_stale_bicycle_for_bucket_pin(
    tmp_path, monkeypatch
):
    from cursed_words_solver.loadout import (
        RUN_STATE_PATH,
        sanitize_run_state_snapshot_for_f8,
    )
    from cursed_words_solver.models import Loadout

    monkeypatch.setattr(
        "cursed_words_solver.loadout.RUN_STATE_PATH",
        tmp_path / "run_state.json",
    )
    loadout = Loadout(
        character="Octacles",
        stickers=[],
        stamps=[],
        extras={"pin_effect": "bucket"},
    )
    run_state = {
        "extras": {
            "bicycle_word_score_bonus": "203",
            "cards_submitted": "203",
            "pin_effect": "bucket",
            "previous_word_first_letter": "f",
        }
    }
    cleaned = sanitize_run_state_snapshot_for_f8(run_state, loadout)
    assert cleaned is not None
    extras = cleaned["extras"]
    assert "bicycle_word_score_bonus" not in extras
    assert "cards_submitted" not in extras
    assert extras.get("previous_word_first_letter") == "f"


def test_historic_words_count_edge_cases():
    assert _historic_words_count("") == 0
    assert _historic_words_count("[]") == 0
    assert _historic_words_count('[{"word":"a"}]') == 1
    assert _historic_words_count("not json") == 0


def test_workflow_stale_reason_string():
    reason = workflow_stale_vs_f8_snapshot(
        {"previous_word_first_letter": "f", "historic_words": '[{"word":"x"}]'},
        {"previous_word_first_letter": "s", "historic_words": "[]"},
    )
    assert reason is not None
    assert "previous word letter" in reason
    assert "historic words changed" in reason


def test_workflow_stale_when_historic_count_increases():
    hist_f8 = '[{"word":"a"},{"word":"b"}]'
    hist_cur = '[{"word":"a"},{"word":"b"},{"word":"c"}]'
    reason = workflow_stale_vs_f8_snapshot(
        {"historic_words": hist_cur},
        {"historic_words": hist_f8},
    )
    assert reason is not None
    assert "historic words changed" in reason
    assert "2" in reason and "3" in reason


def test_workflow_stale_when_historic_same_count_content_differs():
    hist_f8 = '[{"word":"nek"},{"word":"not"}]'
    hist_cur = '[{"word":"nek"},{"word":"effs"}]'
    reason = workflow_stale_vs_f8_snapshot(
        {"historic_words": hist_cur},
        {"historic_words": hist_f8},
    )
    assert reason is not None
    assert "historic words metadata changed" in reason

def test_grid2_empty_historic_not_blocked_when_stale_pruned_no_telescope(
    tmp_path, monkeypatch
):
    """Grid 2 without Telescope: stale disk historic pruned after board refresh."""
    from cursed_words_solver.loadout import (
        RUN_STATE_PATH,
        sanitize_run_state_snapshot_for_f8,
    )
    from cursed_words_solver.models import Board, Loadout

    def _tile(idx: int, ch: str) -> dict:
        row, col = divmod(idx, 5)
        return {
            "row": row,
            "col": col,
            "char": ch,
            "letter": ch,
            "base_score": 1,
            "color": "shiny",
            "curse": "letter",
            "active": True,
        }

    tiles = [_tile(i, "Z") for i in range(25)]
    run_state_path = tmp_path / "run_state.json"
    monkeypatch.setattr("cursed_words_solver.loadout.RUN_STATE_PATH", run_state_path)
    run_state_path.write_text(
        json.dumps(
            {
                "board": {"rows": 5, "cols": 5, "tiles": tiles, "money": 8},
                "extras": {
                    "grid_number": "2",
                    "scoring_previous_words_count": "1",
                    "historic_words": json.dumps(
                        [{"word": "cyanate", "score": 69, "path": [0, 1, 2, 3, 4]}]
                    ),
                },
            }
        ),
        encoding="utf-8",
    )
    merged_run_state = json.loads(run_state_path.read_text(encoding="utf-8"))
    board = Board(tiles=[[None] * 5 for _ in range(5)], money=0)
    loadout = Loadout(extras={"grid_number": "2"})
    assert not loadout_needs_encounter_historic(loadout, board)
    f8_snapshot = sanitize_run_state_snapshot_for_f8(merged_run_state, loadout)
    f8_extras = f8_snapshot["extras"]
    empty_warn = empty_historic_on_later_grid_warning(f8_extras)
    blocked, reason = f8_should_block_save(
        historic_catchup_stale_note=None,
        empty_hist_warn=empty_warn,
        hist_stale_note=None,
        behind_disk_warn=None,
        workflow_stale_warn=None,
        grid_adv_warn=None,
        loadout=loadout,
        board=board,
        f8_extras=f8_extras,
    )
    assert not blocked
    assert reason is None


def test_behind_disk_false_positive_when_stale_historic_pruned(tmp_path, monkeypatch):
    """Disk historic from a prior board is pruned; embed empty must not lag-block."""
    from cursed_words_solver.loadout import (
        RUN_STATE_PATH,
        f8_historic_still_behind_disk_warning,
        sanitize_run_state_snapshot_for_f8,
    )
    from cursed_words_solver.models import (
        Board,
        CurseType,
        Loadout,
        Tile,
        TileColor,
    )

    def _tile(idx: int, ch: str) -> dict:
        row, col = divmod(idx, 5)
        return {
            "row": row,
            "col": col,
            "char": ch,
            "letter": ch,
            "base_score": 1,
            "color": "shiny",
            "curse": "letter",
            "active": True,
        }

    tiles = [_tile(i, "Z") for i in range(25)]
    run_state_path = tmp_path / "run_state.json"
    monkeypatch.setattr("cursed_words_solver.loadout.RUN_STATE_PATH", run_state_path)
    run_state_path.write_text(
        json.dumps(
            {
                "board": {"rows": 5, "cols": 5, "tiles": tiles, "money": 8},
                "extras": {
                    "grid_number": "2",
                    "scoring_previous_words_count": "1",
                    "historic_words": json.dumps(
                        [{"word": "oxyphil", "score": 63, "path": [0, 1, 2, 3, 4]}]
                    ),
                },
            }
        ),
        encoding="utf-8",
    )
    merged_run_state = json.loads(run_state_path.read_text(encoding="utf-8"))
    board = Board(tiles=[[None] * 5 for _ in range(5)], money=0)
    board.tiles[2][2] = Tile(
        2,
        2,
        "t",
        "E",
        0,
        color=TileColor.RED,
        curse=CurseType.ITEM,
        metadata={"scattered_item_id": "telescope", "scattered_item_level": 1},
    )
    loadout = Loadout(extras={"grid_number": "2"})
    f8_snapshot = sanitize_run_state_snapshot_for_f8(merged_run_state, loadout)
    f8_extras = f8_snapshot["extras"]
    assert _historic_words_count(str(f8_extras.get("historic_words", "") or "")) == 1
    assert (
        f8_historic_still_behind_disk_warning(
            f8_extras,
            board=parse_board_from_run_state(merged_run_state),
        )
        is None
    )
    empty_warn = empty_historic_on_later_grid_warning(f8_extras)
    blocked, reason = f8_should_block_save(
        historic_catchup_stale_note=None,
        empty_hist_warn=empty_warn,
        hist_stale_note=None,
        behind_disk_warn=None,
        workflow_stale_warn=None,
        grid_adv_warn=None,
        loadout=loadout,
        board=board,
        f8_extras=f8_extras,
    )
    assert not blocked
    assert reason is None


def test_workflow_stale_false_positive_after_word_play_prune():
    """Board refresh prunes stale historic from F8 embed; symmetric reconcile must not block."""

    def _tile(idx: int, ch: str) -> dict:
        row, col = divmod(idx, 5)
        return {
            "row": row,
            "col": col,
            "char": ch,
            "letter": ch,
            "base_score": 1,
            "color": "shiny",
            "curse": "letter",
            "active": True,
        }

    tiles = [_tile(i, "Z") for i in range(25)]
    merged_run_state = {
        "character": "Rodman",
        "board": {"rows": 5, "cols": 5, "tiles": tiles, "money": 8},
        "extras": {
            "grid_number": "2",
            "scoring_previous_words_count": "1",
            "encounter_historic_source": "live",
            "historic_words": json.dumps(
                [{"word": "oxyphil", "score": 63, "path": [0, 1, 2, 3, 4]}]
            ),
        },
    }
    loadout = Loadout(extras={"grid_number": "2"})
    f8_snapshot = sanitize_run_state_snapshot_for_f8(merged_run_state, loadout)
    assert f8_snapshot is not None
    f8_extras = f8_snapshot["extras"]
    run_extras = merged_run_state["extras"]

    assert workflow_stale_vs_f8_snapshot(run_extras, f8_extras) is None

    blocked, _ = f8_should_block_save(
        historic_catchup_stale_note=None,
        empty_hist_warn=None,
        hist_stale_note=None,
        behind_disk_warn=None,
        workflow_stale_warn=None,
        grid_adv_warn=None,
        loadout=loadout,
        board=parse_board_from_run_state(merged_run_state),
        f8_extras=f8_extras,
    )
    assert not blocked


def test_clear_when_historic_count_increases_reason(tmp_path, monkeypatch):
    suggestion_path = _patch_suggestion_path(tmp_path, monkeypatch)
    hist_f8 = '[{"word":"a"},{"word":"b"}]'
    hist_cur = '[{"word":"a"},{"word":"b"},{"word":"c"}]'
    suggestion_path.write_text(
        json.dumps(
            {
                "board_fingerprint": "board-a",
                "run_state_snapshot": {
                    "extras": {"historic_words": hist_f8},
                },
            }
        ),
        encoding="utf-8",
    )
    reason = clear_stale_last_suggestion_if_workflow_changed(
        {"historic_words": hist_cur}
    )
    assert reason is not None
    assert "historic words changed" in reason
    assert "2" in reason and "3" in reason
    assert not suggestion_path.exists()


def test_clear_when_historic_words_grows(tmp_path, monkeypatch):
    suggestion_path = _patch_suggestion_path(tmp_path, monkeypatch)
    suggestion_path.write_text(
        json.dumps(
            {
                "board_fingerprint": "board-a",
                "run_state_snapshot": {
                    "extras": {
                        "historic_words": '[{"word":"a"},{"word":"b"},{"word":"c"}]',
                        "previous_word_first_letter": "s",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    reason = clear_stale_last_suggestion_if_workflow_changed(
        {
            "historic_words": '[{"word":"a"},{"word":"b"},{"word":"c"},{"word":"d"}]',
            "previous_word_first_letter": "s",
        }
    )
    assert reason is not None
    assert "historic words changed" in reason
    assert "3" in reason and "4" in reason
    assert not suggestion_path.exists()


def test_clear_when_prev_letter_changes(tmp_path, monkeypatch):
    suggestion_path = _patch_suggestion_path(tmp_path, monkeypatch)
    suggestion_path.write_text(
        json.dumps(
            {
                "board_fingerprint": "board-a",
                "run_state_snapshot": {
                    "extras": {"previous_word_first_letter": "s"}
                },
            }
        ),
        encoding="utf-8",
    )
    reason = clear_stale_last_suggestion_if_workflow_changed(
        {"previous_word_first_letter": "f"}
    )
    assert reason is not None
    assert "previous word letter" in reason
    assert not suggestion_path.exists()


def test_no_clear_when_historic_unchanged(tmp_path, monkeypatch):
    suggestion_path = _patch_suggestion_path(tmp_path, monkeypatch)
    historic = '[{"word":"a"},{"word":"b"}]'
    suggestion_path.write_text(
        json.dumps(
            {
                "board_fingerprint": "board-a",
                "run_state_snapshot": {
                    "extras": {
                        "historic_words": historic,
                        "previous_word_first_letter": "s",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    assert (
        clear_stale_last_suggestion_if_workflow_changed(
            {
                "historic_words": historic,
                "previous_word_first_letter": "s",
            }
        )
        is None
    )
    assert suggestion_path.exists()


def test_f8_prior_suggestion_stale_note_when_workflow_drifted(tmp_path, monkeypatch):
    suggestion_path = _patch_suggestion_path(tmp_path, monkeypatch)
    suggestion_path.write_text(
        json.dumps(
            {
                "board_fingerprint": "board-a",
                "run_state_snapshot": {
                    "extras": {"previous_word_first_letter": "j"}
                },
            }
        ),
        encoding="utf-8",
    )
    note = f8_prior_suggestion_stale_note({"previous_word_first_letter": "f"})
    assert note is not None
    assert "Played a word since last F8" in note
    assert "j" in note and "f" in note


def test_f8_prior_suggestion_stale_note_none_when_aligned(tmp_path, monkeypatch):
    suggestion_path = _patch_suggestion_path(tmp_path, monkeypatch)
    suggestion_path.write_text(
        json.dumps(
            {
                "board_fingerprint": "board-a",
                "run_state_snapshot": {
                    "extras": {"previous_word_first_letter": "j"}
                },
            }
        ),
        encoding="utf-8",
    )
    assert f8_prior_suggestion_stale_note({"previous_word_first_letter": "j"}) is None


def test_last_historic_word_first_letter_skips_markup():
    hist = '[{"word":"REXINE","score":30},{"word":"JOI<font>x</font>TY","score":68}]'
    assert _last_historic_word_first_letter(hist) == "j"


def test_historic_previous_letter_mismatch_warning():
    note = historic_previous_letter_mismatch_warning(
        {
            "previous_word_first_letter": "j",
            "historic_words": '[{"word":"rexine","score":30}]',
        }
    )
    assert note is not None
    assert "rexine" in note or "r" in note


def test_empty_historic_on_later_grid_warning():
    note = empty_historic_on_later_grid_warning(
        {
            "grid_number": "4",
            "historic_words": "",
            "scoring_previous_words_count": "2",
        }
    )
    assert note is not None
    assert "F8" in note or "f8" in note.lower()
    assert empty_historic_on_later_grid_warning({"grid_number": "1"}) is None
    assert (
        empty_historic_on_later_grid_warning(
            {"grid_number": "3", "historic_words": '[{"word":"x"}]'}
        )
        is None
    )
    assert (
        empty_historic_on_later_grid_warning(
            {
                "grid_number": "2",
                "historic_words": "",
                "scoring_previous_words_count": "0",
            }
        )
        is None
    )


def test_run_state_historic_stale_warnings_includes_empty_historic():
    warns = run_state_historic_stale_warnings(
        {
            "grid_number": "4",
            "historic_words": "",
            "scoring_previous_words_count": "1",
        }
    )
    assert any("F8" in w or "f8" in w.lower() for w in warns)


def test_grid_advanced_since_last_f8_warning(tmp_path, monkeypatch):
    suggestion_path = _patch_suggestion_path(tmp_path, monkeypatch)
    suggestion_path.write_text(
        json.dumps(
            {
                "run_state_snapshot": {
                    "extras": {"grid_number": "1"},
                },
            }
        ),
        encoding="utf-8",
    )
    note = grid_advanced_since_last_f8_warning({"grid_number": "2"})
    assert note is not None
    assert "1" in note and "2" in note


def test_run_state_historic_stale_warnings_collects_both(tmp_path, monkeypatch):
    suggestion_path = _patch_suggestion_path(tmp_path, monkeypatch)
    suggestion_path.write_text(
        json.dumps(
            {
                "run_state_snapshot": {
                    "extras": {"grid_number": "1"},
                },
            }
        ),
        encoding="utf-8",
    )
    warnings = run_state_historic_stale_warnings(
        {
            "grid_number": "2",
            "previous_word_first_letter": "j",
            "historic_words": '[{"word":"rexine"}]',
        }
    )
    assert len(warnings) >= 2


def test_grid_transition_stale_f8_extras_diff_fixture():
    """Golden repro: grid-1 historic in F8 embed vs grid-2 submit (jiggiest session)."""
    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "stale_f8_grid_transition_extras_diff.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    extras_diff = data["extras_diff"]
    note = _stale_f8_extras_note(extras_diff, has_mutating_dna_stamp=False)
    assert note is not None
    for fragment in data["expected_stale_note_contains"]:
        assert fragment in note


def test_is_export_catchup_drift_historic_count_increase():
    assert is_export_catchup_drift(
        {"historic_words": ""},
        {"historic_words": '[{"word":"gie"}]'},
    )


def test_is_export_catchup_drift_letter_only_when_historic_unchanged():
    assert is_export_catchup_drift(
        {"historic_words": "[]", "previous_word_first_letter": "g"},
        {"historic_words": "[]", "previous_word_first_letter": "s"},
    )


def test_is_export_catchup_drift_false_when_historic_same_count_content_differs():
    hist = '[{"word":"nek"},{"word":"not"}]'
    hist2 = '[{"word":"nek"},{"word":"effs"}]'
    assert not is_export_catchup_drift(
        {"historic_words": hist},
        {"historic_words": hist2},
    )


def test_is_export_catchup_drift_same_count_prev_letter_and_historic_refresh():
    assert is_export_catchup_drift(
        {
            "historic_words": '[{"word":"foo"}]',
            "previous_word_first_letter": "n",
        },
        {
            "historic_words": '[{"word":"bar"}]',
            "previous_word_first_letter": "q",
        },
    )


def test_board_tiles_fingerprint_suffix_strips_money_prefix():
    from cursed_words_solver.fingerprints import board_tiles_fingerprint_suffix

    tiles = "4,0:R/letter/colorless;"
    assert board_tiles_fingerprint_suffix(f"5|{tiles}") == tiles
    assert board_tiles_fingerprint_suffix(tiles) == tiles


def test_poll_suppresses_board_money_drift_within_grace(tmp_path, monkeypatch):
    suggestion_path = _patch_suggestion_path(tmp_path, monkeypatch)
    tiles = "4,0:R/letter/colorless;4,1:A/letter/colorless;"
    board_fp_saved = f"5|{tiles}"
    board_fp_current = f"3|{tiles}"
    created = datetime.now(timezone.utc).isoformat()
    suggestion_path.write_text(
        json.dumps(
            {
                "created_at": created,
                "board_fingerprint": board_fp_saved,
                "loadout_fingerprint": "same-loadout",
            }
        ),
        encoding="utf-8",
    )
    assert fingerprint_invalidate_suppressed_for_post_f8_export(board_fp_current)
    assert poll_invalidate_last_suggestion(
        {},
        current_board_fp=board_fp_current,
        current_loadout_fp="same-loadout",
    ) is None
    assert suggestion_path.exists()

    old = (datetime.now(timezone.utc) - timedelta(seconds=F8_EXPORT_CATCHUP_GRACE_SEC + 1)).isoformat()
    suggestion_path.write_text(
        json.dumps(
            {
                "created_at": old,
                "board_fingerprint": board_fp_saved,
                "loadout_fingerprint": "same-loadout",
            }
        ),
        encoding="utf-8",
    )
    reason = poll_invalidate_last_suggestion(
        {},
        current_board_fp=board_fp_current,
        current_loadout_fp="same-loadout",
    )
    assert reason is None
    assert suggestion_path.exists()


def test_poll_suppresses_letter_drift_when_historic_same_count_refreshed(
    tmp_path, monkeypatch
):
    suggestion_path = _patch_suggestion_path(tmp_path, monkeypatch)
    board_fp = "board-letter-catchup"
    created = datetime.now(timezone.utc).isoformat()
    suggestion_path.write_text(
        json.dumps(
            {
                "created_at": created,
                "board_fingerprint": board_fp,
                "run_state_snapshot": {
                    "extras": {
                        "historic_words": '[{"word":"foo"}]',
                        "previous_word_first_letter": "n",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    poll_extras = {
        "historic_words": '[{"word":"bar"}]',
        "previous_word_first_letter": "q",
    }
    assert workflow_invalidate_suppressed_for_export_catchup(
        poll_extras,
        current_board_fp=board_fp,
    )
    assert poll_invalidate_last_suggestion(
        poll_extras,
        current_board_fp=board_fp,
    ) is None
    assert suggestion_path.exists()


def test_poll_suppresses_workflow_clear_within_grace(tmp_path, monkeypatch):
    suggestion_path = _patch_suggestion_path(tmp_path, monkeypatch)
    board_fp = "board-catchup-test"
    created = datetime.now(timezone.utc).isoformat()
    suggestion_path.write_text(
        json.dumps(
            {
                "created_at": created,
                "board_fingerprint": board_fp,
                "run_state_snapshot": {
                    "extras": {
                        "historic_words": "",
                        "previous_word_first_letter": "g",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    assert suggestion_path.exists()
    assert workflow_invalidate_suppressed_for_export_catchup(
        {
            "historic_words": '[{"word":"snub"}]',
            "previous_word_first_letter": "s",
        },
        current_board_fp=board_fp,
    )
    assert poll_invalidate_last_suggestion(
        {
            "historic_words": '[{"word":"snub"}]',
            "previous_word_first_letter": "s",
        },
        current_board_fp=board_fp,
    ) is None
    assert suggestion_path.exists()


def test_poll_suppresses_workflow_disk_catchup_after_grace(tmp_path, monkeypatch):
    suggestion_path = _patch_suggestion_path(tmp_path, monkeypatch)
    board_fp = "board-catchup-old"
    old = (datetime.now(timezone.utc) - timedelta(seconds=F8_EXPORT_CATCHUP_GRACE_SEC + 1)).isoformat()
    suggestion_path.write_text(
        json.dumps(
            {
                "created_at": old,
                "board_fingerprint": board_fp,
                "run_state_snapshot": {
                    "extras": {"historic_words": "", "previous_word_first_letter": "g"}
                },
            }
        ),
        encoding="utf-8",
    )
    reason = poll_invalidate_last_suggestion(
        {
            "historic_words": '[{"word":"x"}]',
            "previous_word_first_letter": "s",
        },
        current_board_fp=board_fp,
    )
    assert reason is None
    assert suggestion_path.exists()


def test_poll_suppresses_disk_catchup_after_search_budget_grace(
    tmp_path, monkeypatch
):
    suggestion_path = _patch_suggestion_path(tmp_path, monkeypatch)
    board_fp = "2|4,0:A/letter/colorless;"
    old = (
        datetime.now(timezone.utc)
        - timedelta(seconds=f8_export_catchup_grace_sec(60.0) + 1)
    ).isoformat()
    suggestion_path.write_text(
        json.dumps(
            {
                "created_at": old,
                "board_fingerprint": board_fp,
                "run_state_snapshot": {
                    "extras": {
                        "historic_words": "",
                        "previous_word_first_letter": "g",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    poll_extras = {
        "historic_words": '[{"word":"penne"},{"word":"zooty"}]',
        "previous_word_first_letter": "s",
    }
    assert poll_invalidate_last_suggestion(
        poll_extras,
        current_board_fp=board_fp,
        search_budget_sec=60.0,
    ) is None
    assert suggestion_path.exists()


def test_poll_clears_when_board_fingerprint_changes(tmp_path, monkeypatch):
    suggestion_path = _patch_suggestion_path(tmp_path, monkeypatch)
    created = datetime.now(timezone.utc).isoformat()
    suggestion_path.write_text(
        json.dumps(
            {
                "created_at": created,
                "board_fingerprint": "board-a",
                "run_state_snapshot": {"extras": {"historic_words": ""}},
            }
        ),
        encoding="utf-8",
    )
    reason = poll_invalidate_last_suggestion(
        {"historic_words": '[{"word":"x"}]'},
        current_board_fp="board-b",
    )
    assert reason is not None


def test_poll_suppresses_historic_catchup_with_money_only_board_fp_drift(
    tmp_path, monkeypatch
):
    """Money-only board fp drift still suppresses; historic advance with embed prior clears."""
    suggestion_path = _patch_suggestion_path(tmp_path, monkeypatch)
    tiles = "4,0:R/letter/colorless;"
    board_fp_saved = f"5|{tiles}"
    board_fp_current = f"3|{tiles}"
    created = datetime.now(timezone.utc).isoformat()
    suggestion_path.write_text(
        json.dumps(
            {
                "created_at": created,
                "board_fingerprint": board_fp_saved,
                "run_state_snapshot": {
                    "extras": {
                        "historic_words": "[]",
                        "previous_word_first_letter": "",
                        "scoring_previous_words_count": "0",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    poll_extras = {
        "historic_words": '[{"word":"penne"}]',
        "previous_word_first_letter": "p",
        "scoring_previous_words_count": "1",
    }
    assert workflow_invalidate_suppressed_for_export_catchup(
        poll_extras,
        current_board_fp=board_fp_current,
        search_budget_sec=60.0,
    )
    assert poll_invalidate_last_suggestion(
        poll_extras,
        current_board_fp=board_fp_current,
        search_budget_sec=60.0,
    ) is None
    assert suggestion_path.exists()

    suggestion_path.write_text(
        json.dumps(
            {
                "created_at": created,
                "board_fingerprint": board_fp_current,
                "run_state_snapshot": {
                    "extras": {
                        "historic_words": '[{"word":"penne"}]',
                        "previous_word_first_letter": "e",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    poll_extras = {
        "historic_words": '[{"word":"penne"},{"word":"zooty"}]',
        "previous_word_first_letter": "f",
    }
    assert not workflow_invalidate_suppressed_for_export_catchup(
        poll_extras,
        current_board_fp=board_fp_current,
        search_budget_sec=60.0,
    )
    reason = poll_invalidate_last_suggestion(
        poll_extras,
        current_board_fp=board_fp_current,
        search_budget_sec=60.0,
    )
    assert reason is not None
    assert reason.startswith("workflow drift (")
    assert not suggestion_path.exists()


def test_poll_suppresses_historic_catchup_within_search_budget_grace(
    tmp_path, monkeypatch
):
    suggestion_path = _patch_suggestion_path(tmp_path, monkeypatch)
    board_fp = "2|4,0:A/letter/colorless;"
    created = datetime.now(timezone.utc).isoformat()
    suggestion_path.write_text(
        json.dumps(
            {
                "created_at": created,
                "board_fingerprint": board_fp,
                "run_state_snapshot": {
                    "extras": {
                        "historic_words": '[{"word":"penne"}]',
                        "previous_word_first_letter": "e",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    poll_extras = {
        "historic_words": '[{"word":"penne"},{"word":"zooty"}]',
        "previous_word_first_letter": "f",
    }
    assert f8_export_catchup_grace_sec(60.0) == F8_EXPORT_CATCHUP_GRACE_SEC
    assert not workflow_invalidate_suppressed_for_export_catchup(
        poll_extras,
        current_board_fp=board_fp,
        search_budget_sec=60.0,
    )
    reason = poll_invalidate_last_suggestion(
        poll_extras,
        current_board_fp=board_fp,
        search_budget_sec=60.0,
    )
    assert reason is not None
    assert reason.startswith("workflow drift (")
    assert not suggestion_path.exists()


def test_loadout_reconcile_normalizes_previous_word_not_from_historic():
    from cursed_words_solver.loadout import reconcile_previous_word_first_letter_from_historic

    extras = {
        "previous_word_first_letter": "E",
        "historic_words": '[{"word":"zooty"}]',
        "scoring_previous_words_count": "1",
    }
    reconcile_previous_word_first_letter_from_historic(extras)
    assert extras["previous_word_first_letter"] == "e"


def test_reconcile_prev_letter_from_historic_when_scoring_cache_empty():
    from cursed_words_solver.loadout import (
        f8_historic_stale_after_merge_warning,
        reconcile_previous_word_first_letter_from_historic,
    )

    extras = {
        "grid_number": "2",
        "scoring_previous_words_count": "0",
        "previous_word_first_letter": "f",
        "historic_words": '[{"word":"rectifies","score":30}]',
    }
    reconcile_previous_word_first_letter_from_historic(extras)
    assert extras["previous_word_first_letter"] == "r"
    assert f8_historic_stale_after_merge_warning(extras) is None


def test_reconcile_clears_stale_prev_letter_grid2_empty_historic():
    from cursed_words_solver.loadout import reconcile_previous_word_first_letter_from_historic

    extras = {
        "grid_number": "2",
        "previous_word_first_letter": "s",
        "historic_words": "",
    }
    reconcile_previous_word_first_letter_from_historic(extras)
    assert "previous_word_first_letter" not in extras


def test_f8_snapshot_merge_refreshes_historic_same_grid(tmp_path, monkeypatch):
    from cursed_words_solver.loadout import (
        RUN_STATE_PATH,
        merge_encounter_historic_for_f8_snapshot,
    )

    run_state_path = tmp_path / "run_state.json"
    monkeypatch.setattr("cursed_words_solver.loadout.RUN_STATE_PATH", run_state_path)
    two_words = '[{"word":"penne"},{"word":"zooty"}]'
    run_state_path.write_text(
        json.dumps(
            {
                "extras": {
                    "historic_words": two_words,
                    "previous_word_first_letter": "f",
                    "grid_number": "2",
                }
            }
        ),
        encoding="utf-8",
    )
    embed = {
        "extras": {
            "historic_words": '[{"word":"penne"}]',
            "previous_word_first_letter": "e",
            "grid_number": "2",
        }
    }
    merged = merge_encounter_historic_for_f8_snapshot(embed)
    assert merged is not None
    assert _historic_words_count(merged["extras"]["historic_words"]) == 1
    assert merged["extras"]["previous_word_first_letter"] == "e"


def test_gownmen_round_log_workflow_stale_matches_python():
    fixture = (
        Path(__file__).resolve().parent / "fixtures" / "gownmen_stale_f8_round_log.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    extras_diff = data.get("extras_diff") or {}
    f8_extras = {
        k: (v.get("f8") if isinstance(v, dict) else "")
        for k, v in extras_diff.items()
    }
    submit_extras = {
        k: (v.get("submit") if isinstance(v, dict) else "")
        for k, v in extras_diff.items()
    }
    reason = workflow_stale_vs_f8_snapshot(submit_extras, f8_extras)
    assert reason is not None
    assert (
        "historic words changed" in reason
        or "historic words metadata changed" in reason
    )
    assert "e" in reason and "f" in reason
    # Same historic count but different words — true stale, not export catch-up.
    assert not is_export_catchup_drift(f8_extras, submit_extras)


def test_merge_replaces_historic_same_count_different_word(tmp_path, monkeypatch):
    from cursed_words_solver.loadout import (
        RUN_STATE_PATH,
        merge_encounter_historic_for_f8_snapshot,
    )

    run_state_path = tmp_path / "run_state.json"
    monkeypatch.setattr("cursed_words_solver.loadout.RUN_STATE_PATH", run_state_path)
    chipotle = '[{"word":"chipotle","score":36}]'
    penne = '[{"word":"penne","score":23}]'
    run_state_path.write_text(
        json.dumps(
            {
                "extras": {
                    "historic_words": chipotle,
                    "previous_word_first_letter": "c",
                    "grid_number": "2",
                }
            }
        ),
        encoding="utf-8",
    )
    embed = {
        "extras": {
            "historic_words": penne,
            "previous_word_first_letter": "p",
            "grid_number": "2",
        }
    }
    merged = merge_encounter_historic_for_f8_snapshot(embed)
    assert merged is not None
    assert merged["extras"]["historic_words"] == penne
    assert merged["extras"]["previous_word_first_letter"] == "p"


def test_merge_prefers_shorter_fresh_on_same_grid(tmp_path, monkeypatch):
    from cursed_words_solver.loadout import (
        RUN_STATE_PATH,
        merge_encounter_historic_for_f8_snapshot,
    )

    run_state_path = tmp_path / "run_state.json"
    monkeypatch.setattr("cursed_words_solver.loadout.RUN_STATE_PATH", run_state_path)
    short = '[{"word":"tiffany"}]'
    long_hist = '[{"word":"a"},{"word":"b"},{"word":"c"}]'
    run_state_path.write_text(
        json.dumps(
            {"extras": {"historic_words": short, "grid_number": "2"}},
        ),
        encoding="utf-8",
    )
    embed = {
        "extras": {"historic_words": long_hist, "grid_number": "2"},
    }
    merged = merge_encounter_historic_for_f8_snapshot(embed)
    assert merged is not None
    assert merged["extras"]["historic_words"] == long_hist


def test_zoccos_same_count_fixture_merge(tmp_path, monkeypatch):
    from cursed_words_solver.loadout import (
        RUN_STATE_PATH,
        _historic_words_json_prefer_fresh,
        merge_encounter_historic_for_f8_snapshot,
    )

    fixture = (
        Path(__file__).resolve().parent / "fixtures" / "stale_f8_zoccos_same_count.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    diff = data["extras_diff"]
    f8_hist = diff["historic_words"]["f8"]
    submit_hist = diff["historic_words"]["submit"]
    assert (
        _historic_words_json_prefer_fresh(
            f8_hist,
            submit_hist,
            embed_grid=2,
            fresh_grid=2,
        )
        == submit_hist
    )

    run_state_path = tmp_path / "run_state.json"
    monkeypatch.setattr("cursed_words_solver.loadout.RUN_STATE_PATH", run_state_path)
    run_state_path.write_text(
        json.dumps(
            {
                "extras": {
                    "historic_words": submit_hist,
                    "previous_word_first_letter": diff["previous_word_first_letter"][
                        "submit"
                    ],
                    "grid_number": data["grid_number"],
                }
            }
        ),
        encoding="utf-8",
    )
    embed = {
        "extras": {
            "historic_words": f8_hist,
            "previous_word_first_letter": diff["previous_word_first_letter"]["f8"],
            "grid_number": data["grid_number"],
        }
    }
    merged = merge_encounter_historic_for_f8_snapshot(embed)
    assert merged["extras"]["historic_words"] == embed["extras"]["historic_words"]


def test_joey_shorter_submit_fixture_merge(tmp_path, monkeypatch):
    from cursed_words_solver.loadout import (
        RUN_STATE_PATH,
        _historic_words_json_prefer_fresh,
        merge_encounter_historic_for_f8_snapshot,
    )

    fixture = (
        Path(__file__).resolve().parent / "fixtures" / "stale_f8_joey_shorter_submit.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    diff = data["extras_diff"]
    f8_hist = diff["historic_words"]["f8"]
    submit_hist = diff["historic_words"]["submit"]
    assert (
        _historic_words_json_prefer_fresh(
            f8_hist,
            submit_hist,
            embed_grid=2,
            fresh_grid=2,
        )
        == submit_hist
    )

    run_state_path = tmp_path / "run_state.json"
    monkeypatch.setattr("cursed_words_solver.loadout.RUN_STATE_PATH", run_state_path)
    run_state_path.write_text(
        json.dumps(
            {"extras": {"historic_words": submit_hist, "grid_number": data["grid_number"]}},
        ),
        encoding="utf-8",
    )
    merged = merge_encounter_historic_for_f8_snapshot(
        {"extras": {"historic_words": f8_hist, "grid_number": data["grid_number"]}}
    )
    assert merged["extras"]["historic_words"] == f8_hist


def test_rich_historic_word_previous_letter_not_from_font_tag():
    from cursed_words_solver.loadout import _previous_letter_from_historic_words

    norias_rich = (
        '[{"word":"JO<font=InterBold SDF>â‚¬</font>","score":38},'
        '{"word":"<font=InterBold SDF>â‚¦</font>ORI<font=NotoEmoji-Regular SDF>ðŸƒï¸Ž</font>",'
        '"score":21,"path":[0,5,11,16,17,18]}]'
    )
    assert _previous_letter_from_historic_words(norias_rich) == "o"


def test_word_starts_after_previous_skips_grid_one():
    from cursed_words_solver.models import Loadout, LoadoutItem
    from cursed_words_solver.rules.scoring_conditions import explain_sticker_condition
    from tests.catalog.stickers.test_default_stickers import _empty_board, _tile

    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "R", 1)
    board.tiles[0][1] = _tile(0, 1, "O", 1)
    loadout = Loadout(
        stamps=[LoadoutItem(id="limnophila", name="Limnophila", level=1, kind="stamp")],
        extras={
            "grid_number": "1",
            "previous_word_first_letter": "o",
        },
    )
    met, detail = explain_sticker_condition(
        "word_starts_after_previous",
        board,
        [0, 1],
        "ro",
        loadout,
        applying_sticker_id="limnophila",
    )
    assert met is False
    assert "previous word" in detail


def test_glaived_grid4_first_word_limnophila_off():
    """First word on grid 4: stale previous f must not Ã—1.5 when scoring cache empty."""
    from cursed_words_solver.loadout import (
        parse_board_from_run_state,
        parse_run_state,
        prepare_run_state_dict_for_scoring,
    )
    from cursed_words_solver.rules.pipeline import ScoringPipeline

    fixture_path = (
        Path(__file__).resolve().parent / "fixtures" / "glaived_grid4_first_word.json"
    )
    if not fixture_path.exists():
        pytest.skip("glaived grid4 fixture not present")

    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    raw_snapshot = data.get("run_state_snapshot") or {}
    board = parse_board_from_run_state(raw_snapshot)
    assert board is not None

    path = data["path"]
    word = data["word"]
    pipeline = ScoringPipeline()

    stale_loadout = parse_run_state(raw_snapshot)
    stale_score, stale_trace = pipeline.score(board, path, word, stale_loadout)
    assert stale_score == data["actual_score"]

    run_state = prepare_run_state_dict_for_scoring(dict(raw_snapshot))
    loadout = parse_run_state(run_state)
    fixed_score, fixed_trace = pipeline.score(board, path, word, loadout)
    assert fixed_score == data["actual_score"]
    assert fixed_score == 18

    limno = [s for s in fixed_trace if getattr(s, "rule_id", None) == "limnophila"]
    assert not any(getattr(s, "applied", False) for s in limno)

    loadout2 = parse_run_state(run_state)
    loadout2.extras["historic_words"] = data["stale_f8_historic"]
    loadout2.extras["scoring_previous_words_count"] = "0"
    stale_f8_score, _ = pipeline.score(board, path, word, loadout2)
    assert stale_f8_score == data["actual_score"]


def test_rojaks_mismatch_grid_one_limnophila_off():
    """Grid 1: encounter historic previous must not trigger Limnophila (61 not 91)."""
    from cursed_words_solver.loadout import (
        parse_board_from_run_state,
        parse_run_state,
        prepare_run_state_dict_for_scoring,
    )
    from cursed_words_solver.rules.pipeline import ScoringPipeline

    mismatch_path = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "mismatches"
        / "20260603_155126.json"
    )
    if not mismatch_path.exists():
        pytest.skip("rojaks mismatch fixture not present")

    data = json.loads(mismatch_path.read_text(encoding="utf-8"))
    run_state = prepare_run_state_dict_for_scoring(data.get("run_state_snapshot") or {})
    loadout = parse_run_state(run_state)
    board = parse_board_from_run_state(run_state)
    assert loadout is not None and board is not None

    path = data["path"]
    word = data["word"]
    pipeline = ScoringPipeline()
    score, trace = pipeline.score(board, path, word, loadout)
    assert score == data["actual_score"]
    assert score == 61
    limno = [s for s in trace if getattr(s, "rule_id", None) == "limnophila"]
    assert not any(getattr(s, "applied", False) for s in limno)


def test_divergent_mismatch_rich_historic_scores_actual():
    """Rich-text historic must not leave previous 'f' from '<font'; Limnophila off at 88."""
    from cursed_words_solver.loadout import (
        parse_board_from_run_state,
        parse_run_state,
        prepare_run_state_dict_for_scoring,
    )
    from cursed_words_solver.rules.pipeline import ScoringPipeline

    mismatch_path = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "mismatches"
        / "20260603_154325.json"
    )
    if not mismatch_path.exists():
        pytest.skip("divergent mismatch fixture not present")

    data = json.loads(mismatch_path.read_text(encoding="utf-8"))
    run_state = prepare_run_state_dict_for_scoring(data.get("run_state_snapshot") or {})
    loadout = parse_run_state(run_state)
    board = parse_board_from_run_state(run_state)
    assert loadout is not None and board is not None

    path = data["path"]
    word = data["word"]
    pipeline = ScoringPipeline()
    score, _ = pipeline.score(board, path, word, loadout)
    assert score == data["actual_score"]
    assert score == 88


def test_chipotle_mismatch_stale_f_overpredicts_limnophila():
    """Grid 1 skips Limnophila; stale previous f no longer over-predicts (was 54, game 36)."""
    from cursed_words_solver.loadout import (
        parse_board_from_run_state,
        parse_run_state,
        prepare_run_state_dict_for_scoring,
    )
    from cursed_words_solver.rules.pipeline import ScoringPipeline

    mismatch_path = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "mismatches"
        / "20260603_152933.json"
    )
    if not mismatch_path.exists():
        pytest.skip("chipotle mismatch fixture not present")

    data = json.loads(mismatch_path.read_text(encoding="utf-8"))
    run_state = prepare_run_state_dict_for_scoring(data.get("run_state_snapshot") or {})
    loadout = parse_run_state(run_state)
    board = parse_board_from_run_state(run_state)
    assert loadout is not None and board is not None

    path = data["path"]
    word = data["word"]
    pipeline = ScoringPipeline()

    score, _ = pipeline.score(board, path, word, loadout)
    assert score == data["actual_score"]
    assert score == 36


def test_ruin_underexport_stale_f8_extras_diff_fixture():
    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "stale_f8_ruin_underexport_extras_diff.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    extras_diff = data["extras_diff"]
    note = _stale_f8_extras_note(extras_diff, has_mutating_dna_stamp=False)
    assert note is not None
    for fragment in data["expected_stale_note_contains"]:
        assert fragment in note


def test_teepee_grid2_overexport_stale_f8_extras_diff_fixture():
    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "stale_f8_teepee_grid2_overexport_extras_diff.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    note = _stale_f8_extras_note(data["extras_diff"], has_mutating_dna_stamp=False)
    assert note is not None
    for fragment in data["expected_stale_note_contains"]:
        assert fragment in note


def test_fanny_grid3_underexport_stale_f8_extras_diff_fixture():
    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "stale_f8_fanny_grid3_underexport_extras_diff.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    note = _stale_f8_extras_note(data["extras_diff"], has_mutating_dna_stamp=False)
    assert note is not None
    for fragment in data["expected_stale_note_contains"]:
        assert fragment in note


def test_grid2_underexport_stale_f8_extras_diff_fixture():
    """Golden repro: empty F8 historic on grid 2 vs submit with grid-1 ATTEST (jailor session)."""
    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "stale_f8_grid2_underexport_extras_diff.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    extras_diff = data["extras_diff"]
    note = _stale_f8_extras_note(extras_diff, has_mutating_dna_stamp=False)
    assert note is not None
    for fragment in data["expected_stale_note_contains"]:
        assert fragment in note


def test_abided_underexport_stale_f8_extras_diff_fixture():
    """Golden repro: empty F8 historic on grid 4 vs submit with 3 encounter words (abided)."""
    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "stale_f8_abided_underexport_extras_diff.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    extras_diff = data["extras_diff"]
    note = _stale_f8_extras_note(extras_diff, has_mutating_dna_stamp=False)
    assert note is not None
    for fragment in data["expected_stale_note_contains"]:
        assert fragment in note


def test_owsen_grid2_underexport_stale_f8_extras_diff_fixture():
    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "stale_f8_owsen_grid2_underexport.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    note = _stale_f8_extras_note(data["extras_diff"], has_mutating_dna_stamp=False)
    assert note is not None
    for fragment in data["expected_stale_note_contains"]:
        assert fragment in note


def test_gyrene_missing_owsen_historic_catchup(tmp_path, monkeypatch):
    from cursed_words_solver.loadout import (
        RUN_STATE_PATH,
        describe_f8_historic_catchup,
        merge_encounter_historic_for_f8_snapshot,
    )

    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "stale_f8_gyrene_missing_owsen.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    run_state_path = tmp_path / "run_state.json"
    monkeypatch.setattr("cursed_words_solver.loadout.RUN_STATE_PATH", run_state_path)
    run_state_path.write_text(
        json.dumps({"extras": data["disk_extras"]}),
        encoding="utf-8",
    )
    embed = {"extras": dict(data["embed_extras"])}
    embed_hist = embed["extras"]["historic_words"]
    merged = merge_encounter_historic_for_f8_snapshot(embed)
    assert merged is not None
    merged_hist = merged["extras"]["historic_words"]
    assert merged_hist == embed_hist
    note = describe_f8_historic_catchup(
        embed_hist,
        merged_hist,
        grid_number=int(data["grid_number_submit"]),
    )
    assert note is None


def test_grid_advanced_not_intentionally_cleared():
    from cursed_words_solver.loadout import _encounter_historic_intentionally_cleared

    assert not _encounter_historic_intentionally_cleared(
        {"encounter_historic_source": "grid_advanced"}
    )
    assert not _encounter_historic_intentionally_cleared(
        {"encounter_historic_source": "grid1_no_scoring_cache"}
    )
    assert _encounter_historic_intentionally_cleared(
        {"encounter_historic_source": "grid_start_cleared"}
    )


def test_grid1_no_scoring_cache_does_not_block_grid2_disk_catchup(tmp_path, monkeypatch):
    from cursed_words_solver.loadout import merge_encounter_historic_for_f8_snapshot

    hist = '[{"word":"stigmatal","score":2752,"red_tile_count":7}]'
    run_state_path = tmp_path / "run_state.json"
    monkeypatch.setattr("cursed_words_solver.loadout.RUN_STATE_PATH", run_state_path)
    run_state_path.write_text(
        json.dumps(
            {
                "extras": {
                    "grid_number": "2",
                    "historic_words": hist,
                    "encounter_historic_source": "live",
                }
            }
        ),
        encoding="utf-8",
    )
    embed = {
        "extras": {
            "grid_number": "2",
            "historic_words": "",
            "encounter_historic_source": "grid1_no_scoring_cache",
        }
    }
    merged = merge_encounter_historic_for_f8_snapshot(embed)
    assert merged is not None
    assert merged["extras"]["historic_words"] == ""


def test_loadout_fingerprint_stale_warning_detects_mismatch():
    from cursed_words_solver.loadout import loadout_fingerprint_stale_warning
    from cursed_words_solver.models import Loadout, LoadoutItem

    loadout = Loadout(
        character="Sandy Saguaro",
        money=11,
        stickers=[LoadoutItem(id="lucky_scarf", name="Lucky Scarf", level=3)],
        extras={
            "loadout_fingerprint": "Sandy Saguaro|11|lucky_scarf:2|-|mahjong_red_dragon:right"
        },
    )
    note = loadout_fingerprint_stale_warning(loadout)
    assert note is not None
    assert "lucky_scarf:2" in note
    assert "lucky_scarf:3" in note


def test_penill_historic_shrink_stale_f8_extras_diff_fixture():
    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "stale_f8_penill_historic_shrink.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    note = _stale_f8_extras_note(data["extras_diff"], has_mutating_dna_stamp=False)
    assert note is not None
    for fragment in data["expected_stale_note_contains"]:
        assert fragment in note


def test_penill_historic_shrink_prefer_fresh_on_same_grid():
    from cursed_words_solver.loadout import _historic_words_json_prefer_fresh

    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "stale_f8_penill_historic_shrink.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    preferred = _historic_words_json_prefer_fresh(
        data["embed_hist"],
        data["disk_hist"],
        embed_grid=int(data["grid_number"]),
        fresh_grid=int(data["grid_number"]),
    )
    assert preferred == data["disk_hist"]


def test_f8_prediction_workflow_stale_warning_penill():
    from cursed_words_solver.suggestion import f8_prediction_workflow_stale_warning

    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "stale_f8_penill_historic_shrink.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    note = f8_prediction_workflow_stale_warning(
        {
            "historic_words": data["disk_hist"],
            "grid_number": data["grid_number"],
        },
        {
            "historic_words": data["embed_hist"],
            "grid_number": data["grid_number"],
        },
    )
    assert note is not None
    assert "historic words changed" in note or "historic_words changed" in note
    assert "F8 again" in note


def test_penill_mismatch_stale_workflow_one_point_delta():
    """penill f8#637: stale embed missed CYLIX; game delta +1 vs stale F8 prediction."""
    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "mismatches"
        / "20260607_145101.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    assert data["stale_f8_extras"] is True
    assert data["predicted_score"] == 82
    assert data["actual_score"] == 83
    assert data["actual_score"] - data["predicted_score"] == 1
    diff = data["extras_diff"]["historic_words"]
    assert _historic_words_count(diff["f8"]) == 1
    assert _historic_words_count(diff["submit"]) == 2


def test_grid2_with_historic_no_empty_warning():
    """Grid 2 with encounter historic populated should not block F8 save."""
    assert (
        empty_historic_on_later_grid_warning(
            {
                "grid_number": "2",
                "historic_words": '[{"word":"eyestripe","red_tile_count":7}]',
            }
        )
        is None
    )


def test_seemelesse_grid2_underexport_stale_f8_fixture():
    """Golden repro: 20260608_153433 empty F8 historic vs 1-word submit on grid 2."""
    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "stale_f8_seemelesse_grid2_underexport.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    note = _stale_f8_extras_note(data["extras_diff"], has_mutating_dna_stamp=False)
    assert note is not None
    for fragment in data["expected_stale_note_contains"]:
        assert fragment in note
    warn = empty_historic_on_later_grid_warning(
        {
            "grid_number": "2",
            "historic_words": "",
            "scoring_previous_words_count": "1",
        }
    )
    assert warn is not None


def test_schematised_cross_grid_stale_f8_fixture():
    """Golden repro: 20260608_154114 grid-3 F8 historic on grid-2 submit."""
    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "stale_f8_schematised_cross_grid_bleed.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    note = _stale_f8_extras_note(data["extras_diff"], has_mutating_dna_stamp=False)
    assert note is not None
    for fragment in data["expected_stale_note_contains"]:
        assert fragment in note


def test_schematised_mismatch_stale_f8_embed_flag():
    """schematised: path/board match but stale F8 embed (2pt rounding only)."""
    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "mismatches"
        / "20260608_154114.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    assert data["stale_f8_extras"] is True
    assert data["predicted_score"] == 3248
    assert data["actual_score"] == 3250
    assert "historic_words changed" in data["stale_f8_reason"]


def test_f8_should_not_block_when_grid2_has_historic_and_telescope():
    from cursed_words_solver.models import (
        Board,
        CurseType,
        Loadout,
        Tile,
        TileColor,
    )

    board = Board(tiles=[[None] * 5 for _ in range(5)], money=0)
    board.tiles[2][2] = Tile(
        2,
        2,
        "t",
        "E",
        0,
        color=TileColor.RED,
        curse=CurseType.ITEM,
        metadata={"scattered_item_id": "telescope", "scattered_item_level": 1},
    )
    loadout = Loadout(extras={"grid_number": "2"})
    assert loadout_needs_encounter_historic(loadout, board)
    blocked, reason = f8_should_block_save(
        historic_catchup_stale_note=None,
        empty_hist_warn=empty_historic_on_later_grid_warning(
            {"grid_number": "2", "historic_words": ""}
        ),
        hist_stale_note=None,
        behind_disk_warn=None,
        workflow_stale_warn=None,
        grid_adv_warn=None,
        loadout=loadout,
        board=board,
        f8_extras={
            "grid_number": "2",
            "historic_words": '[{"word":"eyestripe","red_tile_count":7}]',
        },
    )
    assert not blocked
    assert reason is None


def test_f8_should_block_when_telescope_and_historic_still_empty(
    tmp_path, monkeypatch
):
    from cursed_words_solver.models import (
        Board,
        CurseType,
        Loadout,
        Tile,
        TileColor,
    )

    monkeypatch.setattr(
        "cursed_words_solver.loadout.RUN_STATE_PATH",
        tmp_path / "run_state.json",
    )
    board = Board(tiles=[[None] * 5 for _ in range(5)], money=0)
    board.tiles[2][2] = Tile(
        2,
        2,
        "t",
        "E",
        0,
        color=TileColor.RED,
        curse=CurseType.ITEM,
        metadata={"scattered_item_id": "telescope", "scattered_item_level": 1},
    )
    loadout = Loadout(extras={"grid_number": "2"})
    empty_warn = empty_historic_on_later_grid_warning(
        {"grid_number": "2", "historic_words": ""}
    )
    blocked, reason = f8_should_block_save(
        gather_succeeded=False,
        loadout=loadout,
        board=board,
    )
    assert blocked
    assert reason and reason.startswith("gather_incomplete")


def test_f8_should_not_warn_grid2_empty_historic_fresh_grid(tmp_path, monkeypatch):
    """Grid 2 word 1: empty historic with spc=0 is valid (no Telescope on board)."""
    from cursed_words_solver.models import Board, Loadout

    monkeypatch.setattr(
        "cursed_words_solver.loadout.RUN_STATE_PATH",
        tmp_path / "run_state.json",
    )
    board = Board(tiles=[[None] * 5 for _ in range(5)], money=0)
    loadout = Loadout(extras={"grid_number": "2"})
    empty_warn = empty_historic_on_later_grid_warning(
        {
            "grid_number": "2",
            "historic_words": "",
            "scoring_previous_words_count": "0",
        }
    )
    assert empty_warn is None
    assert not loadout_needs_encounter_historic(loadout, board)
    blocked, reason = f8_should_block_save(
        gather_succeeded=True,
        loadout=loadout,
        board=board,
    )
    assert not blocked
    assert reason is None


def test_describe_f8_prediction_historic_stale_equal_count_prev_letter_drift():
    """Jouncy-shaped: same historic count, prev letter r→l (rewildings vs lacerating)."""
    from cursed_words_solver.suggestion import describe_f8_prediction_historic_stale_note

    f8 = {
        "historic_words": '[{"word":"REWiLDINGS","score":16}]',
        "previous_word_first_letter": "r",
        "scoring_previous_words_count": "1",
    }
    auth = {
        "historic_words": '[{"word":"LACERATING","score":13}]',
        "previous_word_first_letter": "l",
        "scoring_previous_words_count": "1",
    }
    note = describe_f8_prediction_historic_stale_note(f8, auth)
    assert note is not None
    assert "previous word letter drift" in note


def test_f8_should_block_grid2_submit_projection_mismatch(tmp_path, monkeypatch):
    """Rodman grid 2: block save when embed historic overshoots projected run_state."""
    from cursed_words_solver.models import Board, Loadout

    run_state_path = tmp_path / "run_state.json"
    monkeypatch.setattr("cursed_words_solver.loadout.RUN_STATE_PATH", run_state_path)
    one_word = json.dumps([{"word": "LACERATING", "score": 13}])
    run_state_path.write_text(
        json.dumps(
            {
                "board": {"tiles": [], "money": 0},
                "extras": {
                    "grid_number": "2",
                    "scoring_previous_words_count": "1",
                    "historic_words": one_word,
                    "previous_word_first_letter": "l",
                },
            }
        ),
        encoding="utf-8",
    )
    two_words = json.dumps(
        [
            {"word": "REWiLDINGS", "score": 16},
            {"word": "LACERATING", "score": 13},
        ]
    )
    embed_extras = {
        "grid_number": "2",
        "scoring_previous_words_count": "2",
        "historic_words": two_words,
        "previous_word_first_letter": "r",
    }
    loadout = Loadout(extras=embed_extras)
    board = Board(tiles=[[None] * 5 for _ in range(5)], money=0)
    blocked, reason = f8_should_block_save(
        gather_succeeded=True,
        loadout=loadout,
        board=board,
        f8_extras=embed_extras,
        submit_projected_extras={
            "grid_number": "2",
            "scoring_previous_words_count": "1",
            "historic_words": one_word,
            "previous_word_first_letter": "l",
        },
    )
    assert blocked
    assert reason == "submit_projection_mismatch"


def test_loadout_needs_previous_word_letter_grid1_bento_off():
    from cursed_words_solver.models import Loadout, LoadoutItem

    loadout = Loadout(
        stamps=[LoadoutItem(id="bento_box", name="Bento Box", kind="stamp")],
        extras={
            "grid_number": "1",
            "previous_word_first_letter": "f",
            "historic_words": '[{"word":"oATIpFY","score":25}]',
        },
    )
    assert not loadout_needs_previous_word_letter(loadout)


def test_f8_should_not_block_prev_letter_mismatch_grid1_bento():
    from cursed_words_solver.loadout import f8_historic_stale_after_merge_warning
    from cursed_words_solver.models import Board, Loadout, LoadoutItem

    extras = {
        "grid_number": "1",
        "previous_word_first_letter": "f",
        "historic_words": (
            '[{"word":"oUERIoE","score":10,"path":[8,3,7,11,10,5,0]},'
            '{"word":"oATIpFY","score":25,"path":[7,2,1,6,5,10,11]}]'
        ),
        "scoring_previous_words_count": "2",
    }
    hist_stale = f8_historic_stale_after_merge_warning(extras)
    assert hist_stale is not None
    loadout = Loadout(
        stamps=[LoadoutItem(id="bento_box", name="Bento Box", kind="stamp")],
        extras=extras,
    )
    blocked, reason = f8_should_block_save(
        historic_catchup_stale_note=None,
        empty_hist_warn=None,
        hist_stale_note=hist_stale,
        behind_disk_warn=None,
        workflow_stale_warn=None,
        grid_adv_warn=None,
        loadout=loadout,
        board=Board(tiles=[[None] * 5 for _ in range(5)], money=0),
        f8_extras=extras,
    )
    assert not blocked
    assert reason is None


def test_f8_should_block_prev_letter_mismatch_grid2_bento():
    from cursed_words_solver.loadout import f8_historic_stale_after_merge_warning
    from cursed_words_solver.models import Board, Loadout, LoadoutItem

    extras = {
        "grid_number": "2",
        "previous_word_first_letter": "f",
        "historic_words": '[{"word":"oATIpFY","score":25,"path":[7,2,1,6,5,10,11]}]',
        "scoring_previous_words_count": "1",
    }
    hist_stale = f8_historic_stale_after_merge_warning(extras)
    assert hist_stale is not None
    loadout = Loadout(
        stamps=[LoadoutItem(id="bento_box", name="Bento Box", kind="stamp")],
        extras=extras,
    )
    assert loadout_needs_previous_word_letter(loadout)
    blocked, reason = f8_should_block_save(
        gather_succeeded=True,
        hist_stale_note=hist_stale,
        loadout=loadout,
        board=Board(tiles=[[None] * 5 for _ in range(5)], money=0),
    )
    assert blocked
    assert reason == "bento_previous_word_stale"


def test_f8_should_block_bento_grid2_stale_grid1_prev_letter():
    """First word on grid 2 must not trust grid-1 previous_word_first_letter for Bento."""
    from cursed_words_solver.loadout import f8_historic_stale_after_merge_warning
    from cursed_words_solver.models import Board, Loadout, LoadoutItem

    loadout = Loadout(
        stamps=[LoadoutItem(id="bento_box", name="Bento Box", kind="stamp")],
        extras={
            "grid_number": "4",
            "scoring_previous_words_count": "0",
            "previous_word_first_letter": "r",
            "historic_words": '[{"word":"greenways","score":10}]',
        },
    )
    assert loadout_needs_previous_word_letter(loadout)
    blocked, reason = f8_should_block_save(
        gather_succeeded=True,
        hist_stale_note=f8_historic_stale_after_merge_warning(loadout.extras),
        loadout=loadout,
        board=Board(tiles=[[None] * 5 for _ in range(5)], money=0),
    )
    assert blocked
    assert reason == "bento_previous_word_stale"


def _collect_workflow_drift_notes_for_capture(
    extras_diff: dict[str, dict[str, str]],
    *,
    has_mutating_dna_stamp: bool = True,
) -> list[str]:
    """Workflow keys only â€” mirror melmod CollectWorkflowDriftNotes."""
    notes: list[str] = []
    if entry := extras_diff.get("historic_words"):
        f8_raw = str(entry.get("f8", "") or "").strip()
        submit_raw = str(entry.get("submit", "") or "").strip()
        if f8_raw != submit_raw and (f8_raw or submit_raw):
            notes.append("historic_words changed")

    if has_mutating_dna_stamp:
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

    if entry := extras_diff.get("scoring_previous_words_count"):
        try:
            f8_count = int(str(entry.get("f8", "") or "0"))
            submit_count = int(str(entry.get("submit", "") or "0"))
        except ValueError:
            f8_count = submit_count = 0
        if f8_count > submit_count:
            notes.append(
                f"scoring_previous_words_count f8={f8_count} submit={submit_count}"
            )

    return notes


def _describe_stale_f8_workflow_drift_capture_block(
    extras_diff: dict[str, dict[str, str]],
    *,
    has_mutating_dna_stamp: bool = True,
) -> str | None:
    """Mirror melmod DescribeStaleF8WorkflowDrift for pre-sync capture block."""
    notes = _collect_workflow_drift_notes_for_capture(
        extras_diff,
        has_mutating_dna_stamp=has_mutating_dna_stamp,
    )
    if not notes:
        return None
    return (
        "F8 snapshot stale â€” played word(s) since F8 â€” press F8 again "
        "before submitting the overlay suggestion (" + "; ".join(notes) + ")"
    )


def test_presync_workflow_drift_blocks_capture_satisfy_fixture():
    """satisfy f8#401: stale embed (prev=u) vs submit (prev=f) must block before sync."""
    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "mismatches"
        / "20260609_104918.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    diff = data["extras_diff"]
    note = _describe_stale_f8_workflow_drift_capture_block(diff)
    assert note is not None
    assert "previous_word_first_letter f8='u' submit='f'" in note
    assert "historic_words changed" in note
    assert data["stale_f8_extras"] is True
    assert data["predicted_score"] == 17
    assert data["actual_score"] == 25


def test_satisfy_stale_f8_solver_matches_stale_prediction_on_merged_snapshot():
    """Merged submit extras replay scores 17 (= stale F8); 25 was in-game Bento on pre-submit board."""
    from cursed_words_solver.loadout import (
        parse_board_from_run_state,
        parse_run_state,
        prepare_run_state_dict_for_scoring,
    )
    from cursed_words_solver.rules.pipeline import ScoringPipeline
    from cursed_words_solver.rules.scoring_conditions import (
        apply_snapshot_phased_session_extras,
    )

    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "mismatches"
        / "20260609_104918.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    run_state = prepare_run_state_dict_for_scoring(dict(data["run_state_snapshot"]))
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    apply_snapshot_phased_session_extras(loadout, board)
    score, _ = ScoringPipeline().score(board, data["path"], data["word"], loadout)
    assert int(score) == data["predicted_score"] == 17
    assert data["actual_score"] == 25
    assert data["stale_f8_extras"] is True


def test_is_embed_stale_drift_historic_shrink():
    f8 = {"historic_words": '[{"word":"a"},{"word":"b"}]'}
    cur = {"historic_words": '[{"word":"c"}]'}
    assert is_embed_stale_drift(f8, cur)
    assert not is_disk_catchup_drift(f8, cur)


def test_is_embed_stale_drift_scattered_cleared():
    f8 = {
        "historic_words": '[{"word":"a"}]',
        "grid_scattered_items": '[{"row":0,"col":1,"id":"telescope","level":1}]',
    }
    cur = {"historic_words": '[{"word":"a"}]', "grid_scattered_items": ""}
    assert is_embed_stale_drift(f8, cur)
    assert not is_disk_catchup_drift(f8, cur)


def test_poll_keeps_suggestion_on_workflow_drift_same_board_fp(
    tmp_path, monkeypatch
):
    """Workflow extras may lag on the same grid; only tile changes invalidate."""
    suggestion_path = _patch_suggestion_path(tmp_path, monkeypatch)
    board_fp = "board-shrink-test"
    created = datetime.now(timezone.utc).isoformat()
    suggestion_path.write_text(
        json.dumps(
            {
                "created_at": created,
                "board_fingerprint": board_fp,
                "run_state_snapshot": {
                    "extras": {
                        "historic_words": '[{"word":"a"},{"word":"b"}]',
                        "previous_word_first_letter": "f",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    poll_extras = {
        "historic_words": '[{"word":"c"}]',
        "previous_word_first_letter": "m",
    }
    reason = poll_invalidate_last_suggestion(
        poll_extras,
        current_board_fp=board_fp,
    )
    assert reason is None
    assert suggestion_path.exists()


def test_diets_grid2_bleed_fixture():
    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "stale_f8_diets_grid2_bleed.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    bleed = grid_transition_workflow_bleed_warning(data["run_state_extras"])
    assert bleed is not None
    for fragment in data["expected_bleed_warning_contains"]:
        assert fragment in bleed
    blocked, reason = f8_should_block_save(
        gather_succeeded=True,
        loadout=None,
        board=None,
    )
    assert not blocked
    assert reason is None
    note = _describe_stale_f8_workflow_drift_capture_block(
        data["extras_diff"],
        has_mutating_dna_stamp=False,
    )
    assert note is not None
    for fragment in data["expected_stale_note_contains"]:
        assert fragment in note


def test_diets_grid2_merge_prefers_disk_historic(tmp_path, monkeypatch):
    from cursed_words_solver.loadout import (
        RUN_STATE_PATH,
        merge_encounter_historic_for_f8_snapshot,
    )

    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "stale_f8_diets_grid2_bleed.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    run_state_path = tmp_path / "run_state.json"
    monkeypatch.setattr("cursed_words_solver.loadout.RUN_STATE_PATH", run_state_path)
    run_state_path.write_text(
        json.dumps({"extras": data["disk_extras"]}),
        encoding="utf-8",
    )
    embed = {
        "extras": {
            "historic_words": data["run_state_extras"]["historic_words"],
            "grid_number": "2",
            "encounter_historic_source": "grid_advanced_disk",
            "scoring_previous_words_count": "4",
        }
    }
    merged = merge_encounter_historic_for_f8_snapshot(embed)
    assert merged is not None
    assert merged["extras"]["historic_words"] == data["run_state_extras"]["historic_words"]


def test_grid_one_historic_cache_mismatch_warning():
    extras = {
        "grid_number": "1",
        "historic_words": (
            '[{"word":"rectifies","red_tile_count":6},'
            '{"word":"balistas","red_tile_count":7},'
            '{"word":"zephyrs","red_tile_count":8}]'
        ),
        "scoring_previous_words_count": "0",
        "encounter_historic_source": "live",
    }
    note = grid_one_historic_cache_mismatch_warning(extras)
    assert note is not None
    assert "Grid 1" in note
    assert "scoring cache" in note.lower()
    assert note in run_state_historic_stale_warnings(extras)


def test_f8_should_block_grid_one_historic_cache_mismatch_with_telescope():
    from cursed_words_solver.models import Board, CurseType, Loadout, Tile, TileColor

    board = Board(tiles=[[None] * 5 for _ in range(5)], money=0)
    board.tiles[2][2] = Tile(
        2,
        2,
        "t",
        "E",
        0,
        color=TileColor.RED,
        curse=CurseType.ITEM,
        metadata={"scattered_item_id": "telescope", "scattered_item_level": 1},
    )
    loadout = Loadout(extras={"grid_number": "1"})
    f8_extras = {
        "grid_number": "1",
        "historic_words": '[{"word":"zephyrs","red_tile_count":8}]',
        "scoring_previous_words_count": "0",
    }
    grid_one_warn = grid_one_historic_cache_mismatch_warning(f8_extras)
    assert grid_one_warn is not None
    blocked, reason = f8_should_block_save(
        gather_succeeded=True,
        loadout=loadout,
        board=board,
    )
    assert not blocked
    assert reason is None


def test_spc_regression_blocks_capture():
    diff = {
        "scoring_previous_words_count": {"f8": "3", "submit": "0"},
    }
    note = _describe_stale_f8_workflow_drift_capture_block(diff, has_mutating_dna_stamp=False)
    assert note is not None
    assert "scoring_previous_words_count f8=3 submit=0" in note


def test_bostangi_historic_shrink_fixture():
    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "stale_f8_bostangi_historic_shrink.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    assert is_embed_stale_drift(data["f8_embed_extras"], data["live_extras"])
    note = _describe_stale_f8_workflow_drift_capture_block(
        data["extras_diff"],
        has_mutating_dna_stamp=False,
    )
    assert note is not None
    for fragment in data["expected_capture_block_contains"]:
        assert fragment in note
    assert data["predicted_score"] == data["actual_score"]


def _is_benign_workflow_shrink_drift(
    extras_diff: dict[str, dict[str, str]],
    *,
    has_mutating_dna_stamp: bool = True,
) -> bool:
    """Mirror melmod ExtrasDiffHelper.IsBenignWorkflowShrinkDrift."""
    if not extras_diff:
        return False

    if entry := extras_diff.get("previous_word_first_letter"):
        f8_raw = str(entry.get("f8", "") or "").strip()
        submit_raw = str(entry.get("submit", "") or "").strip()
        if f8_raw and submit_raw and f8_raw.lower() != submit_raw.lower():
            return False

    if has_mutating_dna_stamp:
        if entry := extras_diff.get("mutating_dna_letter_counts"):
            f8_raw = str(entry.get("f8", "") or "")
            submit_raw = str(entry.get("submit", "") or "")
            if not _mutating_dna_letter_counts_equal(f8_raw, submit_raw):
                return False

    has_shrink = False

    if entry := extras_diff.get("historic_words"):
        from cursed_words_solver.loadout import _historic_words_count

        f8_raw = str(entry.get("f8", "") or "").strip()
        submit_raw = str(entry.get("submit", "") or "").strip()
        f8_count = _historic_words_count(f8_raw)
        submit_count = _historic_words_count(submit_raw)
        if submit_count > f8_count:
            return False
        if f8_count > submit_count:
            has_shrink = True
        elif f8_raw != submit_raw and (f8_count > 0 or submit_count > 0):
            has_shrink = True

    if entry := extras_diff.get("scoring_previous_words_count"):
        try:
            f8_count = int(str(entry.get("f8", "") or "0"))
            submit_count = int(str(entry.get("submit", "") or "0"))
        except ValueError:
            f8_count = submit_count = 0
        if submit_count > f8_count:
            return False
        if f8_count > submit_count:
            has_shrink = True

    return has_shrink


def test_poll_round_log_submits_tails_index(tmp_path, monkeypatch):
    from cursed_words_solver.round_log import poll_round_log_submits

    index_path = tmp_path / "index.jsonl"
    monkeypatch.setattr("cursed_words_solver.round_log.ROUND_LOG_INDEX_PATH", index_path)

    entries, offset = poll_round_log_submits(0)
    assert entries == []
    assert offset == 0

    line1 = json.dumps(
        {
            "round_id": "20260609_120000_001",
            "match_status": "score_match",
            "submitted_word": "alpha",
            "solver_word": "alpha",
        }
    )
    index_path.write_text(line1 + "\n", encoding="utf-8")

    entries, offset = poll_round_log_submits(0)
    assert len(entries) == 1
    assert entries[0]["match_status"] == "score_match"
    assert offset == index_path.stat().st_size

    line2 = json.dumps(
        {
            "round_id": "20260609_120001_002",
            "match_status": "stale_f8_extras",
            "submitted_word": "beta",
            "solver_word": "gamma",
        }
    )
    with index_path.open("a", encoding="utf-8") as handle:
        handle.write(line2 + "\n")

    entries, new_offset = poll_round_log_submits(offset)
    assert len(entries) == 1
    assert entries[0]["match_status"] == "stale_f8_extras"
    assert new_offset == index_path.stat().st_size


def test_is_benign_workflow_shrink_joey_fixture():
    fixture = (
        Path(__file__).resolve().parent / "fixtures" / "stale_f8_joey_shorter_submit.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    diff = dict(data["extras_diff"])
    diff["scoring_previous_words_count"] = {"f8": "3", "submit": "1"}
    diff["previous_word_first_letter"] = {"f8": "t", "submit": "t"}
    assert _is_benign_workflow_shrink_drift(diff, has_mutating_dna_stamp=False)


def test_is_benign_workflow_shrink_false_on_letter_mismatch():
    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "mismatches"
        / "20260609_104918.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    assert not _is_benign_workflow_shrink_drift(data["extras_diff"])


def test_project_workflow_extras_for_f8_embed_joey(tmp_path, monkeypatch):
    from cursed_words_solver.loadout import (
        RUN_STATE_PATH,
        _previous_letter_from_historic_words,
        _scoring_previous_words_count_from_extras,
        project_workflow_extras_for_f8_embed,
    )

    fixture = (
        Path(__file__).resolve().parent / "fixtures" / "stale_f8_joey_shorter_submit.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    f8_hist = data["extras_diff"]["historic_words"]["f8"]
    submit_hist = data["extras_diff"]["historic_words"]["submit"]

    run_state_path = tmp_path / "run_state.json"
    monkeypatch.setattr("cursed_words_solver.loadout.RUN_STATE_PATH", run_state_path)
    run_state_path.write_text(
        json.dumps(
            {
                "extras": {
                    "historic_words": submit_hist,
                    "grid_number": data["grid_number"],
                    "scoring_previous_words_count": "1",
                    "previous_word_first_letter": "t",
                }
            }
        ),
        encoding="utf-8",
    )

    extras = {
        "historic_words": f8_hist,
        "grid_number": data["grid_number"],
        "scoring_previous_words_count": "3",
        "previous_word_first_letter": "c",
    }
    project_workflow_extras_for_f8_embed(extras, board=None)
    assert extras["historic_words"] == f8_hist
    assert _scoring_previous_words_count_from_extras(extras) == 3


def test_embed_f8_snapshot_merges_scoring_loadout_workflow_extras(
    tmp_path, monkeypatch
):
    from cursed_words_solver.f8_snapshot import F8Snapshot, embed_f8_snapshot
    from cursed_words_solver.loadout import (
        RUN_STATE_PATH,
        _scoring_previous_words_count_from_extras,
    )
    from cursed_words_solver.models import Loadout

    run_state_path = tmp_path / "run_state.json"
    monkeypatch.setattr("cursed_words_solver.loadout.RUN_STATE_PATH", run_state_path)
    run_state_path.write_text(
        json.dumps(
            {
                "extras": {
                    "grid_number": "5",
                    "historic_words": "",
                    "encounter_historic_source": "live",
                    "scoring_previous_words_count": "0",
                }
            }
        ),
        encoding="utf-8",
    )

    scoring_loadout = Loadout(
        extras={
            "grid_number": "5",
            "historic_words": "",
            "encounter_historic_source": "live",
            "scoring_previous_words_count": "4",
            "previous_word_first_letter": "z",
        }
    )
    snapshot = F8Snapshot(
        run_state={
            "extras": {
                "grid_number": "5",
                "historic_words": "",
                "encounter_historic_source": "live",
                "scoring_previous_words_count": "4",
                "previous_word_first_letter": "z",
            }
        },
        board=None,
        loadout=scoring_loadout,
        board_available=True,
    )
    embedded = embed_f8_snapshot(snapshot, scoring_loadout=scoring_loadout)
    assert embedded is not None
    assert _scoring_previous_words_count_from_extras(embedded["extras"]) == 4
    assert embedded["extras"].get("previous_word_first_letter") == "z"


def test_reconcile_clamps_stale_spc_after_grid_advance(tmp_path, monkeypatch):
    from cursed_words_solver.loadout import (
        reconcile_encounter_historic_for_scoring,
        _scoring_previous_words_count_from_extras,
    )

    extras = {
        "grid_number": "5",
        "historic_words": "",
        "encounter_historic_source": "grid_advanced",
        "scoring_previous_words_count": "4",
        "previous_word_first_letter": "z",
    }
    reconcile_encounter_historic_for_scoring(extras, board=None)
    assert _scoring_previous_words_count_from_extras(extras) == 0
    assert "previous_word_first_letter" not in extras


def test_sanitize_run_state_snapshot_for_f8_projects_workflow_extras(
    tmp_path, monkeypatch
):
    from cursed_words_solver.loadout import (
        RUN_STATE_PATH,
        sanitize_run_state_snapshot_for_f8,
        _scoring_previous_words_count_from_extras,
    )
    from cursed_words_solver.models import Loadout

    fixture = (
        Path(__file__).resolve().parent / "fixtures" / "stale_f8_joey_shorter_submit.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    f8_hist = data["extras_diff"]["historic_words"]["f8"]
    submit_hist = data["extras_diff"]["historic_words"]["submit"]

    run_state_path = tmp_path / "run_state.json"
    monkeypatch.setattr("cursed_words_solver.loadout.RUN_STATE_PATH", run_state_path)
    run_state_path.write_text(
        json.dumps(
            {
                "extras": {
                    "historic_words": submit_hist,
                    "grid_number": data["grid_number"],
                    "scoring_previous_words_count": "1",
                    "previous_word_first_letter": "t",
                }
            }
        ),
        encoding="utf-8",
    )

    embed = {
        "extras": {
            "historic_words": f8_hist,
            "grid_number": data["grid_number"],
            "scoring_previous_words_count": "3",
            "previous_word_first_letter": "c",
        }
    }
    sanitized = sanitize_run_state_snapshot_for_f8(embed, Loadout())
    assert sanitized is not None
    assert sanitized["extras"]["historic_words"] == f8_hist
    assert _scoring_previous_words_count_from_extras(sanitized["extras"]) == 3


def test_benign_shrink_presync_workflow_cleared_after_projection():
    """C# parity: benign shrink syncs before block â€” projected diff has no workflow drift."""
    diff = {
        "historic_words": {
            "f8": '[{"word":"A"},{"word":"B"},{"word":"C"}]',
            "submit": '[{"word":"TIFFANY"}]',
        },
        "scoring_previous_words_count": {"f8": "3", "submit": "1"},
        "previous_word_first_letter": {"f8": "t", "submit": "t"},
    }
    assert _is_benign_workflow_shrink_drift(diff, has_mutating_dna_stamp=False)
    projected_diff = {
        "historic_words": {
            "f8": diff["historic_words"]["submit"],
            "submit": diff["historic_words"]["submit"],
        },
        "scoring_previous_words_count": {"f8": "1", "submit": "1"},
        "previous_word_first_letter": {"f8": "t", "submit": "t"},
    }
    assert _describe_stale_f8_workflow_drift_capture_block(
        projected_diff,
        has_mutating_dna_stamp=False,
    ) is None


def test_bento_err_historic_shrink_letter_drift_not_benign():
    """Rodman grid-2 err: stale F8 historic shrink must not be benign with Bento."""
    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "mismatches"
        / "20260621_085505.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    diff = data["extras_diff"]
    assert not _is_benign_workflow_shrink_drift(diff, has_mutating_dna_stamp=False)
    note = _stale_f8_extras_note(diff, has_mutating_dna_stamp=False)
    assert note is not None
    assert "previous_word_first_letter f8='e' submit='r'" in note


def test_bento_jitter_historic_shrink_letter_drift_not_benign():
    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "mismatches"
        / "20260621_085720.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    diff = data["extras_diff"]
    assert not _is_benign_workflow_shrink_drift(diff, has_mutating_dna_stamp=False)
    note = _stale_f8_extras_note(diff, has_mutating_dna_stamp=False)
    assert note is not None
    assert "previous_word_first_letter f8='j' submit='h'" in note


def test_bento_err_stale_prev_letter_overpredicts():
    """Stale previous_word_first_letter applies Bento; submit projection scores 813."""
    from dataclasses import replace

    from cursed_words_solver.models import LoadoutItem
    from cursed_words_solver.rules.pipeline import ScoringPipeline
    from cursed_words_solver.loadout import parse_run_state
    from tests.regression.test_scoring_mismatches import _run_state_for_replay

    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "mismatches"
        / "20260621_085505.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    run_state = _run_state_for_replay(data)
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    assert board is not None
    has_bento = any(
        (s.id or "").lower() in ("bento_box", "bento") for s in (loadout.stamps or [])
    )
    if not has_bento:
        loadout.stamps = list(loadout.stamps or []) + [
            LoadoutItem(id="bento_box", name="Bento Box", kind="stamp", level=1),
        ]
    pipeline = ScoringPipeline()
    score, _, trace = pipeline.score_with_trace(
        board, data["path"], data["word"], loadout
    )
    assert int(score) == int(data["actual_score"])
    bento_steps = [
        s for s in trace if str(s.get("rule_id", "")).lower() == "bento_box"
    ]
    assert not any(s.get("applied") for s in bento_steps)

    stale_extras = dict(loadout.extras or {})
    stale_extras["previous_word_first_letter"] = "e"
    stale_loadout = replace(loadout, extras=stale_extras)
    stale_score, _, stale_trace = pipeline.score_with_trace(
        board, data["path"], data["word"], stale_loadout
    )
    assert int(stale_score) == int(data["actual_score"])
    stale_bento = [
        s for s in stale_trace if str(s.get("rule_id", "")).lower() == "bento_box"
    ]
    assert not any(s.get("applied") for s in stale_bento)


def test_jitter_bento_stale_f8_historic_replay():
    """Regression 20260621_085720: stale F8 historic must not apply Bento to jitter."""
    from cursed_words_solver.rules.pipeline import ScoringPipeline
    from cursed_words_solver.loadout import (
        parse_board_from_run_state,
        parse_run_state,
        prepare_run_state_dict_for_scoring,
    )

    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "mismatches"
        / "20260621_085720.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    run_state = prepare_run_state_dict_for_scoring(
        dict(data.get("run_state_snapshot") or {})
    )
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    assert board is not None
    pipeline = ScoringPipeline()
    score, _, trace = pipeline.score_with_trace(
        board, data["path"], data["word"], loadout
    )
    assert int(score) == int(data["actual_score"])
    bento_steps = [
        s for s in trace if str(s.get("rule_id", "")).lower() == "bento_box"
    ]
    assert not any(s.get("applied") for s in bento_steps)


def test_merge_encounter_historic_fixes_bento_prev_letter(tmp_path, monkeypatch):
    """Live gather uses stale embed as-is (no disk catch-up for Bento letter)."""
    from cursed_words_solver.loadout import (
        merge_encounter_historic_for_f8_snapshot,
        parse_run_state,
    )

    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "mismatches"
        / "20260621_085505.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    stale_embed = copy.deepcopy(data["run_state_snapshot"])
    stale_extras = stale_embed.setdefault("extras", {})
    stale_extras["historic_words"] = data["extras_diff"]["historic_words"]["f8"]
    stale_extras["previous_word_first_letter"] = "e"
    stale_extras["scoring_previous_words_count"] = "3"

    merged = merge_encounter_historic_for_f8_snapshot(stale_embed)
    assert merged is not None
    merged_extras = merged.get("extras") or {}
    assert merged_extras.get("previous_word_first_letter") == "e"
    assert _historic_words_count(str(merged_extras.get("historic_words", ""))) == 3

    loadout = parse_run_state(merged)
    assert str((loadout.extras or {}).get("previous_word_first_letter")) == "e"


def test_poll_round_log_submits_tails_index(tmp_path, monkeypatch):
    from cursed_words_solver.config import ROUND_LOG_INDEX_PATH
    from cursed_words_solver.round_log import poll_round_log_submits

    index_path = tmp_path / "index.jsonl"
    monkeypatch.setattr("cursed_words_solver.round_log.ROUND_LOG_INDEX_PATH", index_path)

    entries, offset = poll_round_log_submits(0)
    assert entries == []
    assert offset == 0

    line1 = json.dumps(
        {
            "round_id": "20260609_120000_001",
            "match_status": "score_match",
            "submitted_word": "alpha",
            "solver_word": "alpha",
        }
    )
    index_path.write_text(line1 + "\n", encoding="utf-8")

    entries, offset = poll_round_log_submits(0)
    assert len(entries) == 1
    assert entries[0]["match_status"] == "score_match"
    assert offset == index_path.stat().st_size

    line2 = json.dumps(
        {
            "round_id": "20260609_120001_002",
            "match_status": "stale_f8_extras",
            "submitted_word": "beta",
            "solver_word": "gamma",
        }
    )
    with index_path.open("a", encoding="utf-8") as handle:
        handle.write(line2 + "\n")

    entries, new_offset = poll_round_log_submits(offset)
    assert len(entries) == 1
    assert entries[0]["match_status"] == "stale_f8_extras"
    assert new_offset == index_path.stat().st_size


def test_is_benign_workflow_shrink_joey_fixture():
    fixture = (
        Path(__file__).resolve().parent / "fixtures" / "stale_f8_joey_shorter_submit.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    diff = dict(data["extras_diff"])
    diff["scoring_previous_words_count"] = {"f8": "3", "submit": "1"}
    diff["previous_word_first_letter"] = {"f8": "t", "submit": "t"}
    assert _is_benign_workflow_shrink_drift(diff, has_mutating_dna_stamp=False)


def test_is_benign_workflow_shrink_false_on_letter_mismatch():
    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "mismatches"
        / "20260609_104918.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    assert not _is_benign_workflow_shrink_drift(data["extras_diff"])


def test_project_workflow_extras_for_f8_embed_joey(tmp_path, monkeypatch):
    from cursed_words_solver.loadout import (
        RUN_STATE_PATH,
        _previous_letter_from_historic_words,
        _scoring_previous_words_count_from_extras,
        project_workflow_extras_for_f8_embed,
    )

    fixture = (
        Path(__file__).resolve().parent / "fixtures" / "stale_f8_joey_shorter_submit.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    f8_hist = data["extras_diff"]["historic_words"]["f8"]
    submit_hist = data["extras_diff"]["historic_words"]["submit"]

    run_state_path = tmp_path / "run_state.json"
    monkeypatch.setattr("cursed_words_solver.loadout.RUN_STATE_PATH", run_state_path)
    run_state_path.write_text(
        json.dumps(
            {
                "extras": {
                    "historic_words": submit_hist,
                    "grid_number": data["grid_number"],
                    "scoring_previous_words_count": "1",
                    "previous_word_first_letter": "t",
                }
            }
        ),
        encoding="utf-8",
    )

    extras = {
        "historic_words": f8_hist,
        "grid_number": data["grid_number"],
        "scoring_previous_words_count": "3",
        "previous_word_first_letter": "c",
    }
    project_workflow_extras_for_f8_embed(extras, board=None)
    assert extras["historic_words"] == f8_hist
    assert _scoring_previous_words_count_from_extras(extras) == 3


def test_embed_f8_snapshot_projects_workflow_extras(tmp_path, monkeypatch):
    from cursed_words_solver.f8_snapshot import F8Snapshot, embed_f8_snapshot
    from cursed_words_solver.loadout import (
        RUN_STATE_PATH,
        _scoring_previous_words_count_from_extras,
        parse_run_state,
    )

    fixture = (
        Path(__file__).resolve().parent / "fixtures" / "stale_f8_joey_shorter_submit.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    f8_hist = data["extras_diff"]["historic_words"]["f8"]
    submit_hist = data["extras_diff"]["historic_words"]["submit"]

    run_state_path = tmp_path / "run_state.json"
    monkeypatch.setattr("cursed_words_solver.loadout.RUN_STATE_PATH", run_state_path)
    run_state_path.write_text(
        json.dumps(
            {
                "extras": {
                    "historic_words": submit_hist,
                    "grid_number": data["grid_number"],
                    "scoring_previous_words_count": "1",
                    "previous_word_first_letter": "t",
                }
            }
        ),
        encoding="utf-8",
    )

    run_state = {
        "extras": {
            "historic_words": f8_hist,
            "grid_number": data["grid_number"],
            "scoring_previous_words_count": "3",
            "previous_word_first_letter": "c",
        }
    }
    loadout = parse_run_state(run_state)
    embedded = embed_f8_snapshot(
        F8Snapshot(
            run_state=run_state,
            board=None,
            loadout=loadout,
            board_available=False,
        ),
        scoring_loadout=loadout,
    )
    assert embedded is not None
    assert embedded["extras"]["historic_words"] == f8_hist
    assert _scoring_previous_words_count_from_extras(embedded["extras"]) == 3


def _bicycle_word_bonus_from_solver_trace(trace: list) -> int | None:
    for step in trace or []:
        if not isinstance(step, dict):
            continue
        rule_id = str(step.get("rule_id", "") or "").lower()
        game_class = str(step.get("game_class", "") or "").lower()
        if rule_id not in ("bicycle", "cards_submitted_word_bonus") and game_class != "bicycle":
            continue
        try:
            return int(step.get("word_score", 0))
        except (TypeError, ValueError):
            continue
    return None


def _bicycle_word_bonus_from_actual_trace(trace: list) -> int | None:
    for step in trace or []:
        if not isinstance(step, dict):
            continue
        if str(step.get("item_id", "") or "").lower() != "bicycle":
            continue
        try:
            return int(step.get("word_bonus", 0))
        except (TypeError, ValueError):
            continue
    return None


def test_tige_capture_bicycle_trace_drift():
    """Live capture where preview pin drift lowered F8 bicycle prediction vs game."""
    path = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "mismatches"
        / "20260629_172603.json"
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    predicted_bicycle = _bicycle_word_bonus_from_solver_trace(data.get("predicted_trace"))
    actual_bicycle = _bicycle_word_bonus_from_actual_trace(data.get("actual_trace"))
    assert predicted_bicycle == 9
    assert actual_bicycle == 11
    assert data.get("stale_f8_extras") is False
    assert int(data["predicted_score"]) < int(data["actual_score"])


FLEECE_DNA_FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "round_logs"
    / "20260629_220953_fleece_dna_stale.json"
)
KIERIE_DNA_FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "round_logs"
    / "20260629_221116_kierie_dna_stale.json"
)


def test_merge_mutating_dna_for_stale_compare_prefers_scoring():
    workflow = {"mutating_dna_letter_counts": "{}"}
    scoring = {"mutating_dna_letter_counts": '{"m":2,"a":1}'}
    merged = _prepare_extras_for_bicycle_stale_compare(workflow, scoring, {})
    assert merged["mutating_dna_letter_counts"] == '{"m":2,"a":1}'


@pytest.mark.parametrize(
    "fixture_path",
    [FLEECE_DNA_FIXTURE, KIERIE_DNA_FIXTURE],
)
def test_fleece_kierie_mutating_dna_not_stale_when_submit_matches_f8(fixture_path: Path):
    if not fixture_path.exists():
        pytest.skip(f"{fixture_path.name} required")
    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    extras_diff = data.get("extras_diff") or {}
    dna_entry = extras_diff.get("mutating_dna_letter_counts")
    assert isinstance(dna_entry, dict)
    f8_dna = str(dna_entry.get("f8") or "")
    assert f8_dna and f8_dna != "{}"
    note = _stale_f8_extras_note(
        {"mutating_dna_letter_counts": {"f8": f8_dna, "submit": f8_dna}}
    )
    assert note is None


def test_fleece_kierie_mutating_dna_was_stale_before_authoritative_fix():
    if not FLEECE_DNA_FIXTURE.exists():
        pytest.skip("fleece fixture required")
    data = json.loads(FLEECE_DNA_FIXTURE.read_text(encoding="utf-8"))
    extras_diff = data.get("extras_diff") or {}
    assert _stale_f8_extras_note(extras_diff) is not None
    assert "mutating_dna_letter_counts changed" in _stale_f8_extras_note(extras_diff)

