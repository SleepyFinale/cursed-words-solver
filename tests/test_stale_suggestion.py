"""Stale last_suggestion.json board fingerprint warnings."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

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
    grid_advanced_since_last_f8_warning,
    historic_previous_letter_mismatch_warning,
    is_export_catchup_drift,
    poll_invalidate_last_suggestion,
    run_state_historic_stale_warnings,
    stale_suggestion_warning,
    workflow_invalidate_suppressed_for_export_catchup,
    workflow_stale_vs_f8_snapshot,
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
    has_bicycle_pin: bool = True,
    has_mutating_dna_stamp: bool = True,
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
                submit_val = int(submit_raw)
            except ValueError:
                if not f8_raw and submit_raw:
                    notes.append(f"{key} f8=(empty) submit={submit_raw}")
                elif f8_raw and not submit_raw:
                    notes.append(f"{key} f8={f8_raw} submit=(empty)")
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
    assert merged["extras"]["historic_words"] == '[{"word":"beedie","score":808}]'
    assert merged["extras"]["previous_word_first_letter"] == "b"


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
    note = describe_f8_historic_catchup(
        embed_hist,
        merged_hist,
        grid_number=int(data["grid_number"]),
    )
    assert note is not None
    for fragment in data["expected_catchup_contains"]:
        assert fragment in note


def test_f8_merge_before_score_loadout_and_telescope_score(tmp_path, monkeypatch):
    """F8 must score with disk-caught-up historic, not the stale embed alone."""
    from cursed_words_solver.loadout import (
        RUN_STATE_PATH,
        merge_encounter_historic_for_f8_snapshot,
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
    run_state_path = tmp_path / "run_state.json"
    monkeypatch.setattr("cursed_words_solver.loadout.RUN_STATE_PATH", run_state_path)
    run_state_path.write_text(
        json.dumps({"extras": data["disk_extras"]}),
        encoding="utf-8",
    )

    embed_run_state = {"extras": dict(data["embed_extras"])}
    unmerged = parse_run_state(
        prepare_run_state_dict_for_scoring(embed_run_state)
    )
    assert _historic_words_count(unmerged.extras.get("historic_words", "")) == 1

    merged_state = merge_encounter_historic_for_f8_snapshot(embed_run_state)
    assert merged_state is not None
    merged = parse_run_state(prepare_run_state_dict_for_scoring(merged_state))
    assert _historic_words_count(merged.extras.get("historic_words", "")) == 2
    assert merged.extras.get("red_tiles_used_encounter") == 6

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
        extras=dict(unmerged.extras or {}),
    )
    merged_loadout = Loadout(
        stickers=list(base.stickers),
        extras=dict(merged.extras or {}),
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
    assert merged_hist == data["disk_extras"]["historic_words"]
    note = describe_f8_historic_catchup(
        embed_hist,
        merged_hist,
        grid_number=int(data["grid_number"]),
    )
    assert note is not None
    for fragment in data["expected_catchup_contains"]:
        assert fragment in note


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
    assert merged["extras"]["historic_words"] == '[{"word":"iliacus","score":880}]'


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
    assert merged["extras"]["historic_words"] == two_words


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
    assert extras["previous_word_first_letter"] == "f"


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
    assert "previous word letter s→f" in reason
    assert "historic words changed (0→1)" in reason


def test_workflow_stale_when_historic_count_increases():
    hist_f8 = '[{"word":"a"},{"word":"b"}]'
    hist_cur = '[{"word":"a"},{"word":"b"},{"word":"c"}]'
    reason = workflow_stale_vs_f8_snapshot(
        {"historic_words": hist_cur},
        {"historic_words": hist_f8},
    )
    assert reason is not None
    assert "historic words changed (2→3)" in reason


def test_workflow_stale_when_historic_same_count_content_differs():
    hist_f8 = '[{"word":"nek"},{"word":"not"}]'
    hist_cur = '[{"word":"nek"},{"word":"effs"}]'
    reason = workflow_stale_vs_f8_snapshot(
        {"historic_words": hist_cur},
        {"historic_words": hist_f8},
    )
    assert reason is not None
    assert "historic words changed" in reason
    assert "(2→3)" not in reason


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
    assert "historic words changed (2→3)" in reason
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
    assert "historic words changed (3→4)" in reason
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
    assert "previous word letter s→f" in reason
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
    assert "j→f" in note


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
        {"grid_number": "4", "historic_words": ""}
    )
    assert note is not None
    assert "F7" in note
    assert empty_historic_on_later_grid_warning({"grid_number": "1"}) is None
    assert (
        empty_historic_on_later_grid_warning(
            {"grid_number": "3", "historic_words": '[{"word":"x"}]'}
        )
        is None
    )


def test_run_state_historic_stale_warnings_includes_empty_historic():
    warns = run_state_historic_stale_warnings(
        {"grid_number": "4", "historic_words": ""}
    )
    assert any("F7" in w for w in warns)


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
    assert "1→2" in note


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
    assert reason is not None
    assert "board changed" in reason.lower()
    assert not suggestion_path.exists()


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


def test_poll_clears_workflow_drift_after_grace(tmp_path, monkeypatch):
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
    assert reason is not None
    assert "Played word since F8" in reason
    assert not suggestion_path.exists()


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
    assert workflow_invalidate_suppressed_for_export_catchup(
        poll_extras,
        current_board_fp=board_fp_current,
        search_budget_sec=45.0,
    )
    assert poll_invalidate_last_suggestion(
        poll_extras,
        current_board_fp=board_fp_current,
        search_budget_sec=45.0,
    ) is None
    assert suggestion_path.exists()


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
    assert f8_export_catchup_grace_sec(45.0) >= 50.0
    assert poll_invalidate_last_suggestion(
        poll_extras,
        current_board_fp=board_fp,
        search_budget_sec=45.0,
    ) is None
    assert suggestion_path.exists()


def test_loadout_reconcile_normalizes_previous_word_not_from_historic():
    from cursed_words_solver.loadout import reconcile_previous_word_first_letter_from_historic

    extras = {
        "previous_word_first_letter": "E",
        "historic_words": '[{"word":"zooty"}]',
    }
    reconcile_previous_word_first_letter_from_historic(extras)
    assert extras["previous_word_first_letter"] == "e"


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
    assert _historic_words_count(merged["extras"]["historic_words"]) == 2
    assert merged["extras"]["previous_word_first_letter"] == "f"


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
    assert "historic words changed" in reason
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
    assert merged["extras"]["historic_words"] == chipotle
    assert merged["extras"]["previous_word_first_letter"] == "c"


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
    assert merged["extras"]["historic_words"] == short


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
    assert merged["extras"]["historic_words"] == submit_hist


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
    assert merged["extras"]["historic_words"] == submit_hist


def test_rich_historic_word_previous_letter_not_from_font_tag():
    from cursed_words_solver.loadout import _previous_letter_from_historic_words

    norias_rich = (
        '[{"word":"JO<font=InterBold SDF>€</font>","score":38},'
        '{"word":"<font=InterBold SDF>₦</font>ORI<font=NotoEmoji-Regular SDF>🃏︎</font>",'
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
    """First word on grid 4: stale previous f must not ×1.5 when scoring cache empty."""
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
    run_state = prepare_run_state_dict_for_scoring(data.get("run_state_snapshot") or {})
    loadout = parse_run_state(run_state)
    board = parse_board_from_run_state(run_state)
    assert loadout is not None and board is not None

    path = data["path"]
    word = data["word"]
    pipeline = ScoringPipeline()

    stale_score, stale_trace = pipeline.score(board, path, word, loadout)
    assert stale_score == data["predicted_score_stale"]

    loadout.extras["scoring_previous_words_count"] = "0"
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
    assert merged_hist == data["disk_extras"]["historic_words"]
    note = describe_f8_historic_catchup(
        embed_hist,
        merged_hist,
        grid_number=int(data["grid_number_submit"]),
    )
    assert note is not None
    for fragment in data["expected_catchup_contains"]:
        assert fragment in note


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
    assert merged["extras"]["historic_words"] == hist


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
    assert "F7" in note


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
    warn = empty_historic_on_later_grid_warning({"grid_number": "2", "historic_words": ""})
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
