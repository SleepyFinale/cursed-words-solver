"""Post-search historic_words catchup and in-search disk refresh."""

from __future__ import annotations

import json

import pytest

from cursed_words_solver.f8_snapshot import (
    F8Snapshot,
    _build_snapshot_from_run_state,
    catchup_historic_gather_after_search,
    historic_words_gather_pending,
    sole_gather_miss_is_historic,
    try_refresh_historic_extras_from_disk,
)
from cursed_words_solver.models import Board, CurseType, Loadout, Tile, TileColor
from cursed_words_solver.suggestion import f8_should_block_save


def _board_run_state(*, extras: dict | None = None) -> dict:
    tiles = [
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
    ]
    return {
        "board": {"tiles": tiles, "money": 4},
        "character": "Test",
        "stickers": [],
        "stamps": [],
        "extras": extras or {"grid_number": "2", "scoring_previous_words_count": "1"},
    }


def _telescope_board() -> Board:
    board = Board(tiles=[[None] * 5 for _ in range(5)], money=4)
    board.tiles[0][3] = Tile(
        0,
        3,
        "t",
        "E",
        0,
        color=TileColor.RED,
        curse=CurseType.ITEM,
        metadata={"scattered_item_id": "telescope", "scattered_item_level": 1},
    )
    return board


def test_sole_gather_miss_is_historic():
    snap = F8Snapshot(
        run_state={},
        board=_telescope_board(),
        loadout=Loadout(extras={"grid_number": "2"}),
        board_available=True,
        extras_ready=False,
        gather_missing=["historic_words"],
    )
    assert sole_gather_miss_is_historic(snap)
    snap.gather_missing = ["historic_words", "consumable_rack"]
    assert not sole_gather_miss_is_historic(snap)


def _sandy_grid2_run_state(*, extras: dict | None = None) -> dict:
    """Grid-2 board from a Sandy Saguaro session (paths from grid 1 won't match)."""
    rows = ["IRWNE", "LJUHE", "ELTGV", "DRHRO", "AOOBE"]
    tiles = []
    for r, row in enumerate(rows):
        for c, ch in enumerate(row):
            tiles.append(
                {
                    "row": r,
                    "col": c,
                    "char": ch.lower(),
                    "letter": ch,
                    "base_score": 1,
                    "color": "colorless",
                    "curse": "letter",
                    "active": True,
                }
            )
    base_extras = {
        "grid_number": "2",
        "scoring_previous_words_count": "1",
        "encounter_historic_source": "live",
    }
    if extras:
        base_extras.update(extras)
    return {
        "board": {"tiles": tiles, "money": 4},
        "character": "Sandy Saguaro",
        "stickers": [{"id": "telescope", "name": "Telescope", "level": 1}],
        "stamps": [],
        "extras": base_extras,
    }


def test_grid2_prior_grid_historic_path_mismatch_preserves_metadata():
    """Grid-2: prior-grid paths are kept as metadata-only for Telescope/scoring."""
    virginia_hist = json.dumps(
        [
            {
                "word": "VIRGINIA",
                "score": 24,
                "path": [4, 8, 13, 17, 11, 6, 1, 7],
            }
        ]
    )
    run_state = _sandy_grid2_run_state(
        extras={
            "historic_words": virginia_hist,
            "previous_word_first_letter": "v",
        }
    )
    snap = _build_snapshot_from_run_state(run_state, rules={})
    assert snap.extras_ready
    assert not historic_words_gather_pending(snap)
    assert snap.loadout is not None
    extras = snap.loadout.extras
    assert extras.get("encounter_historic_source") == "historic_metadata_only"
    rows = json.loads(extras["historic_words"])
    assert len(rows) == 1
    assert rows[0]["word"] == "VIRGINIA"
    assert rows[0]["score"] == 24
    assert "path" not in rows[0]


def test_catchup_live_only_does_not_unblock_from_disk_alone(tmp_path, monkeypatch):
    """Post-search catchup does not merge disk historic; F8 live export required."""
    from cursed_words_solver.loadout import RUN_STATE_PATH

    run_state_path = tmp_path / "run_state.json"
    monkeypatch.setattr("cursed_words_solver.loadout.RUN_STATE_PATH", run_state_path)

    virginia_hist = json.dumps(
        [
            {
                "word": "VIRGINIA",
                "score": 24,
                "path": [4, 8, 13, 17, 11, 6, 1, 7],
            }
        ]
    )
    disk_state = _sandy_grid2_run_state(
        extras={
            "historic_words": virginia_hist,
            "previous_word_first_letter": "v",
        }
    )
    run_state_path.write_text(json.dumps(disk_state), encoding="utf-8")

    embed = _sandy_grid2_run_state(
        extras={
            "grid_number": "2",
            "scoring_previous_words_count": "1",
            "historic_words": "",
        }
    )
    snap = _build_snapshot_from_run_state(embed, rules={})
    assert historic_words_gather_pending(snap)

    updated, note, stale, behind = catchup_historic_gather_after_search(
        snap,
        rules={},
        catchup_timeout_sec=0.3,
        reexport_poll_sec=0,
    )
    assert historic_words_gather_pending(updated)
    assert not updated.extras_ready
    assert behind is None


def test_catchup_live_only_disk_historic_not_merged(tmp_path, monkeypatch):
    from cursed_words_solver.loadout import RUN_STATE_PATH

    run_state_path = tmp_path / "run_state.json"
    monkeypatch.setattr("cursed_words_solver.loadout.RUN_STATE_PATH", run_state_path)

    disk_hist = json.dumps([{"word": "AAA", "score": 10, "path": [0, 1, 2]}])
    run_state_path.write_text(
        json.dumps(
            _board_run_state(
                extras={
                    "grid_number": "2",
                    "scoring_previous_words_count": "1",
                    "historic_words": disk_hist,
                    "encounter_historic_source": "live",
                }
            )
        ),
        encoding="utf-8",
    )

    embed = _board_run_state(
        extras={
            "grid_number": "2",
            "scoring_previous_words_count": "1",
            "historic_words": "",
        }
    )
    snap = _build_snapshot_from_run_state(embed, rules={})
    assert historic_words_gather_pending(snap)

    updated, note, stale, behind = catchup_historic_gather_after_search(
        snap,
        rules={},
        catchup_timeout_sec=0.3,
        reexport_poll_sec=0,
    )
    assert historic_words_gather_pending(updated)
    assert not updated.extras_ready
    assert note is None
    assert stale is None
    assert behind is None


def test_catchup_still_blocks_when_historic_stays_empty(tmp_path, monkeypatch):
    from cursed_words_solver.loadout import RUN_STATE_PATH

    run_state_path = tmp_path / "run_state.json"
    monkeypatch.setattr("cursed_words_solver.loadout.RUN_STATE_PATH", run_state_path)

    empty_state = _board_run_state(
        extras={
            "grid_number": "2",
            "scoring_previous_words_count": "1",
            "historic_words": "",
        }
    )
    run_state_path.write_text(json.dumps(empty_state), encoding="utf-8")

    snap = _build_snapshot_from_run_state(empty_state, rules={})
    assert historic_words_gather_pending(snap)

    updated, note, stale, behind = catchup_historic_gather_after_search(
        snap,
        rules={},
        catchup_timeout_sec=0.15,
        reexport_poll_sec=0,
    )
    assert historic_words_gather_pending(updated)
    assert not updated.extras_ready
    assert note is None

    blocked, reason = f8_should_block_save(
        gather_succeeded=False,
        gather_missing=updated.gather_missing or None,
        historic_catchup_stale_note=stale,
        behind_disk_warn=behind,
        loadout=updated.loadout,
        board=updated.board,
    )
    assert blocked
    assert reason == "gather_incomplete:historic_words"


def test_try_refresh_historic_extras_from_disk(tmp_path, monkeypatch):
    from cursed_words_solver.loadout import RUN_STATE_PATH

    run_state_path = tmp_path / "run_state.json"
    monkeypatch.setattr("cursed_words_solver.loadout.RUN_STATE_PATH", run_state_path)

    disk_hist = json.dumps([{"word": "AAA", "score": 5, "path": [0, 1, 2]}])
    run_state_path.write_text(
        json.dumps(
            _board_run_state(
                extras={
                    "grid_number": "2",
                    "scoring_previous_words_count": "1",
                    "historic_words": disk_hist,
                    "encounter_historic_source": "live",
                }
            )
        ),
        encoding="utf-8",
    )

    board = _telescope_board()
    loadout = Loadout(
        extras={
            "grid_number": "2",
            "scoring_previous_words_count": "1",
            "historic_words": "",
        }
    )
    assert try_refresh_historic_extras_from_disk(loadout, board)
    assert loadout.extras["historic_words"] == disk_hist


def test_catchup_then_embed_projects_to_submit_extras(tmp_path, monkeypatch):
    """Post-search catchup merges disk historic; embed must match projected run_state."""
    from cursed_words_solver.f8_snapshot import embed_f8_snapshot
    from cursed_words_solver.loadout import RUN_STATE_PATH

    run_state_path = tmp_path / "run_state.json"
    monkeypatch.setattr("cursed_words_solver.loadout.RUN_STATE_PATH", run_state_path)

    one_word = json.dumps([{"word": "LACERATING", "score": 13}])
    run_state = _board_run_state(
        extras={
            "grid_number": "2",
            "scoring_previous_words_count": "1",
            "historic_words": one_word,
            "previous_word_first_letter": "l",
            "encounter_historic_source": "live",
        }
    )
    run_state_path.write_text(json.dumps(run_state), encoding="utf-8")

    stale_two = json.dumps(
        [
            {"word": "REWiLDINGS", "score": 16},
            {"word": "LACERATING", "score": 13},
        ]
    )
    snap = _build_snapshot_from_run_state(
        _board_run_state(
            extras={
                "grid_number": "2",
                "scoring_previous_words_count": "2",
                "historic_words": stale_two,
                "previous_word_first_letter": "r",
            }
        ),
        rules={},
    )
    updated, _, _, _ = catchup_historic_gather_after_search(
        snap,
        rules={},
        catchup_timeout_sec=0.2,
        reexport_poll_sec=0,
    )
    embed = embed_f8_snapshot(updated, scoring_loadout=updated.loadout)
    assert isinstance(embed, dict)
    extras = embed.get("extras")
    assert isinstance(extras, dict)
    assert extras.get("historic_words") == one_word
    assert extras.get("previous_word_first_letter") == "l"


def test_grid2_does_not_infer_spc_from_prior_grid_historic():
    """Grid-2 F8: empty scoring cache must not backfill spc from encounter-wide historic."""
    from cursed_words_solver.loadout import reconcile_scoring_previous_words_count

    grid1_hist = json.dumps(
        [
            {
                "word": "GRIDONE",
                "score": 1125,
                "path": [5, 10, 6, 12, 18, 22, 23, 24, 19, 14, 8, 3],
            }
        ]
    )
    extras = {
        "grid_number": "2",
        "historic_words": grid1_hist,
        "scoring_previous_words_count": "0",
        "encounter_historic_source": "grid2_disk_fallback",
    }
    reconcile_scoring_previous_words_count(extras)
    assert extras["scoring_previous_words_count"] == "0"
    assert extras["historic_words"] == grid1_hist


def test_grid2_stale_historic_source_does_not_infer_spc():
    from cursed_words_solver.loadout import reconcile_scoring_previous_words_count

    extras = {
        "grid_number": "2",
        "historic_words": json.dumps([{"word": "STALE", "score": 1}]),
        "scoring_previous_words_count": "0",
        "encounter_historic_source": "historic_paths_stale",
    }
    reconcile_scoring_previous_words_count(extras)
    assert extras["scoring_previous_words_count"] == "0"
