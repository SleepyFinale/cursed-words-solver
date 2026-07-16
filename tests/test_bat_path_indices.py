"""Bat / shrunk-grid path index roundtrips (no cached maps)."""

from cursed_words_solver.loadout import parse_board_from_run_state
from cursed_words_solver.ui.board_geometry import (
    path_from_melmod_indices,
    path_to_melmod_indices,
    playable_bounds,
)
from tests.integration.test_run_state_board import _bat_4x3_run_state


def _bat_4x4_run_state() -> dict:
    """Bat 4×4 playable in rows 1–4, cols 0–3 of a 5×5 storage frame."""
    tiles = []
    for row in range(5):
        for col in range(5):
            in_play = row >= 1 and col <= 3
            ch = "A" if in_play else ""
            tiles.append(
                {
                    "row": row,
                    "col": col,
                    "char": ch,
                    "letter": ch,
                    "base_score": 1 if in_play else 0,
                    "color": "colorless",
                    "curse": "letter" if in_play else "inactive",
                    "active": in_play,
                }
            )
    return {
        "board": {
            "source": "melmod",
            "row_order": "top_first",
            "rows": 4,
            "cols": 4,
            "playable_origin": "bottom_left",
            "playable_min_row": 1,
            "playable_max_row": 4,
            "playable_min_col": 0,
            "playable_max_col": 3,
            "tiles": tiles,
        }
    }


def test_bat_4x4_path_roundtrip():
    board = parse_board_from_run_state(_bat_4x4_run_state())
    assert board is not None
    assert playable_bounds(board) == (1, 4, 0, 3)
    # storage: (2,3)=13, (3,3)=18, (4,1)=21
    storage = [13, 18, 12, 11, 10, 15, 21]
    melmod = path_to_melmod_indices(board, storage)
    assert path_from_melmod_indices(board, melmod) == storage
    assert path_to_melmod_indices(board, path_from_melmod_indices(board, melmod)) == melmod


def test_bat_4x3_nonsquare_path_roundtrip():
    """Playable height 3 ≠ width 4 — vertical flip must use height, not cols."""
    board = parse_board_from_run_state(_bat_4x3_run_state())
    assert board is not None
    assert board.rows == 3 and board.cols == 4
    assert playable_bounds(board) == (2, 4, 0, 3)
    # Top-left playable storage (2,0)=10 and bottom-right (4,3)=23
    storage = [10, 11, 12, 13, 23, 22]
    melmod = path_to_melmod_indices(board, storage)
    assert path_from_melmod_indices(board, melmod) == storage
    # Non-square: melmod indices must stay within height*width (=12)
    assert all(0 <= i < 12 for i in melmod)
    # Using width for the vertical flip would collide distinct rows — ensure
    # top-row and bottom-row storage map to different melmod indices.
    top = path_to_melmod_indices(board, [10])[0]  # row 2
    bottom = path_to_melmod_indices(board, [20])[0]  # row 4 col 0
    assert top != bottom
