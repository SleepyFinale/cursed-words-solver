"""Regression tests for F8 workflow stale fixes (session-derived)."""

from __future__ import annotations

import json
from pathlib import Path

from cursed_words_solver.f8_snapshot import (
    F8SuggestionSession,
    _build_snapshot_from_run_state,
    _encounter_historic_export_ready,
)
from cursed_words_solver.loadout import (
    align_embed_with_scoring_loadout,
    historic_metadata_matches_json,
)
from cursed_words_solver.models import Board, CurseType, Loadout, Tile, TileColor
from cursed_words_solver.suggestion import (
    f8_should_block_save,
    loadout_needs_historic_words_gather,
    poll_invalidate_last_suggestion,
    workflow_stale_vs_f8_snapshot,
)


def _simple_board() -> Board:
    board = Board(tiles=[[None] * 5 for _ in range(5)], money=10)
    for r in range(5):
        for c in range(5):
            board.tiles[r][c] = Tile(
                r,
                c,
                "a",
                "A",
                1,
                color=TileColor.BLUE,
                curse=CurseType.LETTER,
            )
    return board


def test_sam_gambit_spc2_requires_historic_gather_without_telescope():
    """Word 3+ on a grid: spc>0 must wait for historic export even without Telescope."""
    board = _simple_board()
    loadout = Loadout(
        character="Sam Gambit",
        stickers=[],
        stamps=[],
        extras={
            "grid_number": "2",
            "scoring_previous_words_count": "2",
            "historic_words": "",
        },
    )
    assert loadout_needs_historic_words_gather(loadout, board, loadout.extras)


def test_encounter_historic_not_ready_when_spc_exceeds_historic_rows():
    board = _simple_board()
    loadout = Loadout(extras={"grid_number": "2", "scoring_previous_words_count": "2"})
    hist = json.dumps([{"word": "ONE", "score": 10}])
    assert not _encounter_historic_export_ready(
        loadout.extras,
        hist,
        loadout=loadout,
        board=board,
    )
    two = json.dumps(
        [{"word": "ONE", "score": 10}, {"word": "TWO", "score": 20}]
    )
    assert _encounter_historic_export_ready(
        loadout.extras,
        two,
        loadout=loadout,
        board=board,
    )


def test_gather_missing_historic_when_spc2_and_one_row(tmp_path, monkeypatch):
    from cursed_words_solver.loadout import RUN_STATE_PATH

    run_state_path = tmp_path / "run_state.json"
    monkeypatch.setattr("cursed_words_solver.loadout.RUN_STATE_PATH", run_state_path)
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
            "money": 10,
        },
        "character": "Sam Gambit",
        "stickers": [],
        "stamps": [],
        "extras": {
            "grid_number": "2",
            "scoring_previous_words_count": "2",
            "historic_words": json.dumps([{"word": "ONE", "score": 10}]),
            "encounter_historic_source": "live",
            "board_from_melmod": "true",
        },
    }
    run_state_path.write_text(json.dumps(run_state), encoding="utf-8")
    snap = _build_snapshot_from_run_state(run_state)
    assert "historic_words" in (snap.gather_missing or [])


def test_workflow_stale_ignores_metadata_only_historic_string_diff():
    meta = json.dumps([{"word": "MIDGET", "score": 10}])
    full = json.dumps(
        [
            {
                "word": "MIDGET",
                "score": 10,
                "path": [0, 1, 2, 3, 4, 5],
            }
        ]
    )
    f8 = {
        "historic_words": meta,
        "scoring_previous_words_count": "1",
        "encounter_historic_source": "historic_metadata_only",
    }
    live = {
        "historic_words": full,
        "scoring_previous_words_count": "1",
        "encounter_historic_source": "live",
    }
    assert historic_metadata_matches_json(meta, full)
    assert workflow_stale_vs_f8_snapshot(live, f8) is None


def test_align_embed_promotes_historic_when_scoring_has_more_rows():
    board = _simple_board()
    embed = {
        "historic_words": json.dumps([{"word": "ONE", "score": 10}]),
        "scoring_previous_words_count": "1",
        "grid_number": "2",
    }
    scoring = {
        "historic_words": json.dumps(
            [{"word": "ONE", "score": 10}, {"word": "TWO", "score": 20}]
        ),
        "scoring_previous_words_count": "2",
        "grid_number": "2",
        "encounter_historic_source": "live",
    }
    align_embed_with_scoring_loadout(embed, scoring, board=board)
    assert len(json.loads(embed["historic_words"])) == 2
    assert embed["scoring_previous_words_count"] == "2"


def test_f8_should_block_save_when_embed_historic_short_of_spc():
    board = _simple_board()
    loadout = Loadout(
        extras={
            "grid_number": "2",
            "scoring_previous_words_count": "2",
            "historic_words": json.dumps(
                [{"word": "ONE", "score": 10}, {"word": "TWO", "score": 20}]
            ),
        }
    )
    f8_extras = {
        "historic_words": json.dumps([{"word": "ONE", "score": 10}]),
        "scoring_previous_words_count": "1",
        "grid_number": "2",
    }
    blocked, reason = f8_should_block_save(
        gather_succeeded=True,
        loadout=loadout,
        board=board,
        f8_extras=f8_extras,
        path=[0, 1, 2],
        scoring_word="abc",
    )
    assert blocked
    assert reason == "submit_projection_mismatch"


def test_poll_invalidate_clears_with_active_session_on_historic_advance(
    tmp_path, monkeypatch
):
    board_fp = "8|0,0:A/letter/colorless;"
    suggestion_path = tmp_path / "last_suggestion.json"
    monkeypatch.setattr(
        "cursed_words_solver.suggestion.LAST_SUGGESTION_PATH",
        suggestion_path,
    )
    f8_hist = json.dumps([{"word": "ONE", "score": 10}])
    live_hist = json.dumps(
        [{"word": "ONE", "score": 10}, {"word": "TWO", "score": 20}]
    )
    payload = {
        "word": "game",
        "path": [0],
        "predicted_score": 200,
        "board_fingerprint": board_fp,
        "loadout_fingerprint": "test-loadout",
        "run_state_snapshot": {
            "extras": {
                "scoring_previous_words_count": "1",
                "historic_words": f8_hist,
            }
        },
    }
    suggestion_path.write_text(json.dumps(payload), encoding="utf-8")

    session = F8SuggestionSession(
        board_fingerprint=board_fp,
        loadout_fingerprint="test-loadout",
        board_tiles_fingerprint="0,0:A/letter/colorless",
        grid_number=2,
    )
    reason = poll_invalidate_last_suggestion(
        {
            "scoring_previous_words_count": "2",
            "historic_words": live_hist,
        },
        current_board_fp=board_fp,
        current_loadout_fp="test-loadout",
        active_session=session,
    )
    assert reason is not None
    assert reason.startswith("workflow drift (")
    assert not suggestion_path.exists()
