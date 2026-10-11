"""Call Of The Void: 6×6 ring board export and parse."""

from __future__ import annotations



from cursed_words_solver.board_display import format_board_grid
from cursed_words_solver.loadout import parse_board_from_run_state


def _void_ring_tile(row: int, col: int, *, letter: str = "", active: bool = True) -> dict:
    return {
        "row": row,
        "col": col,
        "char": letter.lower() if letter else "",
        "letter": letter,
        "base_score": 1.0 if active and letter else 0.0,
        "color": "colorless",
        "curse": "inactive" if not active else "letter",
        "active": active,
    }


def _build_call_of_void_export() -> dict:
    """6×6 storage with center 4×4 void; perimeter letters on edges."""
    tiles: list[dict] = []
    letters = {
        (0, 0): "T",
        (0, 5): "A",
        (5, 0): "I",
        (5, 5): "E",
        (5, 1): "O",
        (5, 2): "T",
        (5, 3): "L",
    }
    for display_row in range(6):
        for col in range(6):
            on_edge = display_row in (0, 5) or col in (0, 5)
            letter = letters.get((display_row, col), "X" if on_edge else "")
            active = on_edge
            tiles.append(_void_ring_tile(display_row, col, letter=letter, active=active))

    return {
        "board": {
            "source": "melmod",
            "row_order": "top_first",
            "rows": 6,
            "cols": 6,
            "playable_origin": "full",
            "playable_min_row": 0,
            "playable_max_row": 5,
            "playable_min_col": 0,
            "playable_max_col": 5,
            "tiles": tiles,
        }
    }


def test_parse_call_of_void_6x6_ring() -> None:
    board = parse_board_from_run_state(_build_call_of_void_export())
    assert board is not None
    assert board.rows == 6
    assert board.cols == 6
    assert board.storage_rows == 6
    assert board.cell_count == 36
    assert sum(board.active) == 20
    assert board.is_active_cell(0, 0)
    assert not board.is_active_cell(2, 2)
    assert board.get(5, 1).letter == "O"


def test_format_call_of_void_shows_void_center() -> None:
    board = parse_board_from_run_state(_build_call_of_void_export())
    assert board is not None
    text = format_board_grid(board)
    lines = text.split("\n")
    assert len(lines) == 6
    assert "..." in lines[2] or ". . ." in lines[2]
