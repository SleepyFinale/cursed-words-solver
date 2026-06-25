"""Live-from-game historic export parity (no disk merge)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cursed_words_solver.f8_snapshot import F8Snapshot, embed_f8_snapshot
from cursed_words_solver.loadout import (
    _historic_words_count,
    _scoring_previous_words_count_from_extras,
    merge_encounter_historic_for_f8_snapshot,
    parse_run_state,
    project_workflow_extras_for_f8_embed,
    reconcile_encounter_historic_for_scoring,
)
from cursed_words_solver.models import Board, CurseType, Loadout, Tile, TileColor
from cursed_words_solver.suggestion import f8_historic_would_fail_submit_projection


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "round_logs"


def _rodman_grid2_board() -> Board:
    """3x3 playable board from 20260625_155542 ankara session (paths stale vs historic)."""
    layout = [
        ("A", "O", "K"),
        ("Q", "N", "R"),
        ("B", "A", "S"),
    ]
    board = Board(tiles=[[None] * 3 for _ in range(5)], money=9)
    for r, row in enumerate(layout):
        for c, ch in enumerate(row):
            board.tiles[r + 2][c] = Tile(
                r + 2,
                c,
                ch.lower(),
                ch,
                10,
                color=TileColor.BLUE,
                curse=CurseType.LETTER,
            )
    return board


def test_merge_encounter_historic_is_noop_even_when_disk_ahead(tmp_path, monkeypatch):
    from cursed_words_solver.loadout import RUN_STATE_PATH

    run_state_path = tmp_path / "run_state.json"
    monkeypatch.setattr("cursed_words_solver.loadout.RUN_STATE_PATH", run_state_path)
    run_state_path.write_text(
        json.dumps(
            {
                "extras": {
                    "historic_words": '[{"word":"beedie","score":808}]',
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


def test_same_grid_word2_path_stale_metadata_not_empty():
    board = _rodman_grid2_board()
    reefers = json.dumps(
        [
            {
                "word": "REEFERS",
                "score": 364,
                "path": [11, 5, 1, 0, 6, 7, 12],
                "red_tile_count": 2,
            }
        ]
    )
    extras = {
        "grid_number": "2",
        "scoring_previous_words_count": "2",
        "historic_words": reefers,
        "encounter_historic_source": "live",
        "red_tiles_used_encounter": "2",
    }
    reconcile_encounter_historic_for_scoring(extras, board=board)
    assert extras.get("encounter_historic_source") == "historic_metadata_only"
    assert _historic_words_count(extras["historic_words"]) == 1
    assert _scoring_previous_words_count_from_extras(extras) == 2
    rows = json.loads(extras["historic_words"])
    assert rows[0]["word"] == "REEFERS"
    assert "path" not in rows[0]


def test_embed_f8_snapshot_keeps_metadata_on_path_stale_round_log():
    data = json.loads(
        (FIXTURES / "20260625_155542_789_extras.json").read_text(encoding="utf-8")
    )
    live = data["live_export_extras"]
    board = _rodman_grid2_board()
    run_state = {
        "board": {"tiles": [], "money": 9},
        "character": "Rodman",
        "stickers": [],
        "stamps": [],
        "extras": dict(live),
    }
    loadout = parse_run_state(run_state)
    reconcile_encounter_historic_for_scoring(loadout.extras or {}, board=board)
    snap = F8Snapshot(
        run_state=run_state,
        board=board,
        loadout=loadout,
        board_available=True,
        extras_ready=True,
    )
    embedded = embed_f8_snapshot(snap, scoring_loadout=loadout)
    assert isinstance(embedded, dict)
    extras = embedded.get("extras")
    assert isinstance(extras, dict)
    assert _historic_words_count(extras.get("historic_words", "")) == 1
    assert _scoring_previous_words_count_from_extras(extras) == 2
    assert extras.get("encounter_historic_source") == "historic_metadata_only"


def test_grid2_word1_path_stale_keeps_prior_grid_metadata():
    """Grid-2 word 1 after advance: prior-grid path stale → metadata-only, not empty."""
    data = json.loads(
        (FIXTURES / "20260625_155318_917_extras.json").read_text(encoding="utf-8")
    )
    live = data["live_export_extras"]
    board = Board(tiles=[[None] * 5 for _ in range(5)], money=13)
    for idx in range(25):
        r, c = divmod(idx, 5)
        board.tiles[r][c] = Tile(
            r, c, "a", "A", 1, color=TileColor.COLORLESS, curse=CurseType.LETTER
        )
    extras = dict(live)
    reconcile_encounter_historic_for_scoring(extras, board=board)
    assert extras.get("encounter_historic_source") == "historic_metadata_only"
    assert _historic_words_count(extras["historic_words"]) == 1
    assert _scoring_previous_words_count_from_extras(extras) == 2
    rows = json.loads(extras["historic_words"])
    assert rows[0]["word"] == "EE"
    assert "path" not in rows[0]


def test_submit_projection_uses_scoring_extras_not_disk():
    board = _rodman_grid2_board()
    meta = json.dumps([{"word": "REEFERS", "score": 364, "red_tile_count": 2}])
    scoring = {
        "historic_words": meta,
        "scoring_previous_words_count": "2",
        "previous_word_first_letter": "r",
        "encounter_historic_source": "historic_metadata_only",
        "grid_number": "2",
    }
    embed = dict(scoring)
    assert f8_historic_would_fail_submit_projection(
        embed,
        scoring_extras=scoring,
        board=board,
    ) is None


def test_project_workflow_does_not_shrink_to_disk(tmp_path, monkeypatch):
    from cursed_words_solver.loadout import RUN_STATE_PATH

    run_state_path = tmp_path / "run_state.json"
    monkeypatch.setattr("cursed_words_solver.loadout.RUN_STATE_PATH", run_state_path)
    run_state_path.write_text(
        json.dumps(
            {
                "extras": {
                    "historic_words": '[{"word":"TIFFANY"}]',
                    "grid_number": "2",
                    "scoring_previous_words_count": "1",
                }
            }
        ),
        encoding="utf-8",
    )
    three_words = json.dumps(
        [{"word": "A"}, {"word": "B"}, {"word": "C"}]
    )
    extras = {
        "historic_words": three_words,
        "grid_number": "2",
        "scoring_previous_words_count": "3",
    }
    project_workflow_extras_for_f8_embed(extras, board=None)
    assert extras["historic_words"] == three_words
    assert _scoring_previous_words_count_from_extras(extras) == 3


def test_submit_projection_passes_with_metadata_only_embed():
    board = _rodman_grid2_board()
    full = json.dumps(
        [
            {
                "word": "REEFERS",
                "score": 364,
                "path": [11, 5, 1, 0, 6, 7, 12],
                "red_tile_count": 2,
            }
        ]
    )
    meta = json.dumps([{"word": "REEFERS", "score": 364, "red_tile_count": 2}])
    embed_extras = {
        "historic_words": meta,
        "scoring_previous_words_count": "2",
        "previous_word_first_letter": "r",
        "encounter_historic_source": "historic_metadata_only",
        "grid_number": "2",
    }
    scoring_extras = {
        "historic_words": full,
        "scoring_previous_words_count": "2",
        "previous_word_first_letter": "r",
        "encounter_historic_source": "live",
        "grid_number": "2",
    }
    assert not f8_historic_would_fail_submit_projection(
        embed_extras,
        scoring_extras=scoring_extras,
        board=board,
    )
