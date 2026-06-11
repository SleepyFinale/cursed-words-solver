"""F8 snapshot gather and single-press workflow."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from cursed_words_solver.config import AppConfig, LAST_SUGGESTION_PATH
from cursed_words_solver.f8_snapshot import (
    F8Snapshot,
    F8SuggestionSession,
    _build_snapshot_from_run_state,
    _extras_missing_for_loadout,
    gather_f8_snapshot,
    session_from_snapshot,
)
from cursed_words_solver.loadout import parse_board_from_run_state
from cursed_words_solver.models import Loadout, LoadoutItem
from cursed_words_solver.fingerprints import board_tiles_fingerprint_suffix
from cursed_words_solver.round_log import (
    last_round_log_submit_word,
    last_submit_effective_first_letter,
    last_submit_first_letter,
)
from cursed_words_solver.suggestion import (
    f8_prediction_workflow_stale_warning,
    poll_invalidate_last_suggestion,
    f8_should_block_save,
)


def test_app_config_no_auto_solve():
    cfg = AppConfig()
    assert "auto_solve_after_submit" not in cfg.__dataclass_fields__


def test_f8_should_block_save_trusts_gather():
    blocked, _ = f8_should_block_save(gather_succeeded=True, mid_solve_grid_advanced=False)
    assert not blocked


def test_f8_should_block_save_blocks_grid_advance():
    blocked, reason = f8_should_block_save(
        gather_succeeded=True,
        mid_solve_grid_advanced=True,
    )
    assert blocked
    assert reason == "grid_advanced_during_solve"


def test_f8_should_block_save_workflow_stale():
    blocked, reason = f8_should_block_save(
        gather_succeeded=True,
        workflow_stale_warn=(
            "F8 prediction may be wrong (previous word letter e→m) — press F8 again."
        ),
    )
    assert blocked
    assert reason == "workflow_extras_stale"


def test_last_submit_first_letter_from_round_log(tmp_path, monkeypatch):
    import cursed_words_solver.round_log as round_log_mod

    index_path = tmp_path / "index.jsonl"
    index_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "round_id": "20260610_142818_534",
                        "submitted_word": "euouae",
                        "match_status": "score_match",
                    }
                ),
                json.dumps(
                    {
                        "round_id": "20260610_142858_948",
                        "submitted_word": "malvesies",
                        "match_status": "stale_f8_extras",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(round_log_mod, "ROUND_LOG_INDEX_PATH", index_path)
    assert last_round_log_submit_word() == "malvesies"
    assert last_submit_first_letter() == "m"


def test_last_submit_effective_first_letter_from_round_log(tmp_path, monkeypatch):
    import cursed_words_solver.round_log as round_log_mod

    log_dir = tmp_path / "round_logs"
    log_dir.mkdir()
    round_id = "20260610_185834_528"
    log_path = log_dir / f"{round_id}.json"
    log_path.write_text(
        json.dumps(
            {
                "actual": {
                    "word": "yeehaw",
                    "path": [6, 12, 14, 8, 9, 13],
                    "submitted_word_first_letter": "e",
                },
                "run_state": {"board": {"tiles": []}, "extras": {}},
            }
        ),
        encoding="utf-8",
    )
    index_path = log_dir / "index.jsonl"
    index_path.write_text(
        json.dumps(
            {
                "round_id": round_id,
                "file": str(log_path),
                "submitted_word": "yeehaw",
                "match_status": "score_mismatch",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(round_log_mod, "ROUND_LOG_INDEX_PATH", index_path)
    monkeypatch.setattr(round_log_mod, "ROUND_LOG_DIR", log_dir)
    assert last_submit_first_letter() == "y"
    assert last_submit_effective_first_letter() == "e"


def test_f8_prediction_workflow_stale_warning_blocks_save():
    warn = f8_prediction_workflow_stale_warning(
        {"previous_word_first_letter": "m"},
        {"previous_word_first_letter": "e"},
    )
    assert warn is not None
    blocked, reason = f8_should_block_save(
        gather_succeeded=True,
        workflow_stale_warn=warn,
    )
    assert blocked
    assert reason == "workflow_extras_stale"


def _board_run_state(*, prev_letter: str, count: str = "1") -> dict:
    return {
        "board": {
            "tiles": [
                {
                    "row": r,
                    "col": c,
                    "char": "a",
                    "letter": "A",
                    "base_score": 1,
                    "color": "colorless",
                    "curse": "letter",
                    "active": True,
                }
                for r in range(5)
                for c in range(5)
            ],
            "money": 13,
        },
        "character": "Test",
        "stickers": [],
        "stamps": [{"id": "limnophila", "name": "Limnophila", "kind": "stamp"}],
        "extras": {
            "grid_number": "2",
            "previous_word_first_letter": prev_letter,
            "scoring_previous_words_count": count,
            "historic_words": "[]",
        },
    }


def test_gather_waits_for_prev_letter_after_submit(tmp_path, monkeypatch):
    from cursed_words_solver import config as config_mod
    import cursed_words_solver.round_log as round_log_mod

    run_state_path = tmp_path / "run_state.json"
    monkeypatch.setattr(config_mod, "RUN_STATE_PATH", run_state_path)

    index_path = tmp_path / "index.jsonl"
    index_path.write_text(
        json.dumps(
            {
                "round_id": "20260610_142818_534",
                "submitted_word": "malvesies",
                "match_status": "score_match",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(round_log_mod, "ROUND_LOG_INDEX_PATH", index_path)

    calls = {"n": 0}

    def fake_load():
        calls["n"] += 1
        state = _board_run_state(
            prev_letter="m" if calls["n"] >= 3 else "e",
            count="1",
        )
        run_state_path.write_text(json.dumps(state), encoding="utf-8")
        return json.loads(run_state_path.read_text(encoding="utf-8"))

    monkeypatch.setattr(
        "cursed_words_solver.f8_snapshot.load_run_state_raw",
        fake_load,
    )
    monkeypatch.setattr(
        "cursed_words_solver.loadout.load_run_state_raw",
        fake_load,
    )

    snap = gather_f8_snapshot(
        rules={},
        extras_timeout_sec=2.0,
        poll_sec=0.05,
    )
    assert snap.extras_ready
    assert snap.loadout is not None
    assert snap.loadout.extras["previous_word_first_letter"] == "m"
    assert calls["n"] >= 3


def test_gather_first_word_without_round_log_submit(tmp_path, monkeypatch):
    from cursed_words_solver import config as config_mod
    import cursed_words_solver.round_log as round_log_mod

    run_state_path = tmp_path / "run_state.json"
    state = _board_run_state(prev_letter="a")
    run_state_path.write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.setattr(config_mod, "RUN_STATE_PATH", run_state_path)

    index_path = tmp_path / "index.jsonl"
    index_path.write_text("", encoding="utf-8")
    monkeypatch.setattr(round_log_mod, "ROUND_LOG_INDEX_PATH", index_path)

    snap = gather_f8_snapshot(rules={}, extras_timeout_sec=1.0, poll_sec=0.05)
    assert snap.extras_ready
    assert snap.loadout is not None


def test_session_from_snapshot(tmp_path, monkeypatch):
    from cursed_words_solver import config as config_mod
    from cursed_words_solver import loadout as loadout_mod
    import cursed_words_solver.round_log as round_log_mod

    run_state = {
        "board": {
            "tiles": [
                {
                    "row": r,
                    "col": c,
                    "char": "a",
                    "letter": "A",
                    "base_score": 1,
                    "color": "colorless",
                    "curse": "letter",
                    "active": True,
                }
                for r in range(5)
                for c in range(5)
            ],
            "money": 5,
        },
        "character": "Test",
        "stickers": [],
        "stamps": [],
        "extras": {"grid_number": "1"},
    }
    run_state_path = tmp_path / "run_state.json"
    run_state_path.write_text(json.dumps(run_state), encoding="utf-8")
    monkeypatch.setattr(config_mod, "RUN_STATE_PATH", run_state_path)
    monkeypatch.setattr(loadout_mod, "RUN_STATE_PATH", run_state_path)
    index_path = tmp_path / "index.jsonl"
    index_path.write_text("", encoding="utf-8")
    monkeypatch.setattr(round_log_mod, "ROUND_LOG_INDEX_PATH", index_path)

    snap = gather_f8_snapshot(rules={})
    session = session_from_snapshot(snap)
    assert session is not None
    assert session.grid_number == 1


def test_poll_keeps_suggestion_with_active_session_same_tiles(
    tmp_path, monkeypatch
):
    from cursed_words_solver import suggestion as suggestion_mod

    suggestion_path = tmp_path / "last_suggestion.json"
    monkeypatch.setattr(suggestion_mod, "LAST_SUGGESTION_PATH", suggestion_path)

    tiles = "4,0:R/letter/colorless;4,1:A/letter/colorless;"
    board_fp = f"5|{tiles}"
    created = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
    suggestion_path.write_text(
        json.dumps(
            {
                "created_at": created,
                "board_fingerprint": board_fp,
                "loadout_fingerprint": "loadout-a",
                "run_state_snapshot": {
                    "extras": {
                        "historic_words": "",
                        "previous_word_first_letter": "a",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    session = F8SuggestionSession(
        board_fingerprint=board_fp,
        loadout_fingerprint="loadout-a",
        board_tiles_fingerprint=board_tiles_fingerprint_suffix(board_fp),
        grid_number=1,
    )
    poll_extras = {
        "historic_words": '[{"word":"new"}]',
        "previous_word_first_letter": "n",
    }
    assert poll_invalidate_last_suggestion(
        poll_extras,
        current_board_fp=board_fp,
        current_loadout_fp="loadout-a",
        active_session=session,
    ) is None
    assert suggestion_path.exists()


def test_tile_ninja_missing_consumables_used_blocks_f8_gather():
    board = parse_board_from_run_state(_board_run_state(prev_letter=""))
    loadout = Loadout(
        stamps=[LoadoutItem(id="tile_ninja", name="Tile Ninja", kind="stamp")],
        extras={"consumable_rack_count": 5},
    )
    missing = _extras_missing_for_loadout(
        loadout,
        board,
        {"tile_ninja_bonus": "0", "tile_ninja_bonus_last_known": "0"},
    )
    assert "tile_ninja_consumables_used" in missing

    ready = _extras_missing_for_loadout(
        loadout,
        board,
        {"tile_ninja_consumables_used": "10"},
    )
    assert "tile_ninja_consumables_used" not in ready


def test_tile_ninja_missing_export_marks_extras_not_ready():
    run_state = _board_run_state(prev_letter="")
    run_state["stamps"] = [
        {"id": "tile_ninja", "name": "Tile Ninja", "kind": "stamp"},
    ]
    run_state["extras"]["tile_ninja_bonus"] = "0"
    run_state["extras"]["tile_ninja_bonus_last_known"] = "0"
    run_state["extras"]["consumable_rack"] = json.dumps(
        [
            {
                "rack_index": 0,
                "letter": "A",
                "char_display": "a",
                "color": "red",
                "curse": "letter",
                "base_score": 2,
            }
        ]
    )
    snapshot = _build_snapshot_from_run_state(run_state, rules={})
    assert not snapshot.extras_ready
    assert any("tile_ninja_consumables_used" in w for w in snapshot.warnings)
