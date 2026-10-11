"""Placement-progress fingerprint tolerance (Python solver + melmod ConsumablePlacementHelper)."""

import json

from cursed_words_solver.config import LAST_SUGGESTION_PATH
from cursed_words_solver.fingerprints import board_fingerprint
from cursed_words_solver.models import Board
from cursed_words_solver.suggestion import poll_invalidate_last_suggestion
from tests.helpers.boards import letter_tile as _tile


def _board_with_cell(row: int, col: int, letter: str) -> Board:
    tiles = [[_tile("x", r, c) for c in range(5)] for r in range(5)]
    tiles[row][col] = _tile(letter, row, col)
    return Board(tiles=tiles)


def _two_placement_board(
    *,
    cell_a: tuple[int, int, str],
    cell_b: tuple[int, int, str],
) -> Board:
    tiles = [[_tile("x", r, c) for c in range(5)] for r in range(5)]
    for row, col, letter in (cell_a, cell_b):
        tiles[row][col] = _tile(letter, row, col)
    return Board(tiles=tiles)


def _board_fp_at(row: int, col: int, tile_segment: str, *, fill: str = "x/letter/colorless") -> str:
    """Melmod-style board fingerprint with one cell using a custom tile segment."""
    parts = ["0", "|"]
    for r in range(5):
        for c in range(5):
            seg = tile_segment if (r, c) == (row, col) else fill
            parts.extend([str(r), ",", str(c), ":", seg, ";"])
    return "".join(parts)


def _board_with_two_cells(
    cell_a: tuple[int, int, str],
    cell_b: tuple[int, int, str],
) -> Board:
    tiles = [[_tile("x", r, c) for c in range(5)] for r in range(5)]
    row_a, col_a, letter_a = cell_a
    row_b, col_b, letter_b = cell_b
    tiles[row_a][col_a] = _tile(letter_a, row_a, col_a)
    tiles[row_b][col_b] = _tile(letter_b, row_b, col_b)
    return Board(tiles=tiles)


def test_poll_invalidate_stale_for_wrong_twinkle_toes_swap():
    from cursed_words_solver.rules.twinkle_toes import swap_tile_contents, swap_to_record

    board = Board(tiles=[[_tile("x", r, c) for c in range(5)] for r in range(5)])
    board.tiles[1][4] = _tile("p", 1, 4)
    board.tiles[2][2] = _tile("l", 2, 2)
    board.tiles[0][0] = _tile("a", 0, 0)
    board.tiles[4][4] = _tile("z", 4, 4)
    idx_a = 1 * 5 + 4
    idx_b = 2 * 5 + 2
    wrong_idx_a = 0 * 5 + 0
    wrong_idx_b = 4 * 5 + 4
    before_fp = board_fingerprint(board)
    wrong_fp = board_fingerprint(
        swap_tile_contents(board, wrong_idx_a, wrong_idx_b)
    )
    swap = swap_to_record(idx_a, idx_b)
    assert wrong_fp != before_fp
    LAST_SUGGESTION_PATH.parent.mkdir(parents=True, exist_ok=True)
    LAST_SUGGESTION_PATH.write_text(
        json.dumps(
            {
                "board_fingerprint": before_fp,
                "twinkle_toes_swap": {
                    "row_a": swap.row_a,
                    "col_a": swap.col_a,
                    "row_b": swap.row_b,
                    "col_b": swap.col_b,
                },
            }
        ),
        encoding="utf-8",
    )
    reason = poll_invalidate_last_suggestion({}, current_board_fp=wrong_fp)
    assert reason is not None
    assert "board changed since last F8" in reason


def test_suppress_invalidate_when_twinkle_swap_and_consumable_placement():
    from cursed_words_solver.rules.twinkle_toes import swap_tile_contents, swap_to_record
    from cursed_words_solver.suggestion import (
        fingerprint_change_is_suggested_board_progress,
        fingerprint_invalidate_suppressed_for_suggested_board_change,
        stale_suggestion_warning,
    )

    board = Board(tiles=[[_tile("x", r, c) for c in range(5)] for r in range(5)])
    board.tiles[1][3] = _tile("q", 1, 3)
    board.tiles[4][4] = _tile("m", 4, 4)
    board.tiles[2][2] = _tile("g", 2, 2)
    idx_a = 1 * 5 + 3
    idx_b = 4 * 5 + 4
    swap = swap_to_record(idx_a, idx_b)
    swapped = swap_tile_contents(board, idx_a, idx_b)
    swapped.tiles[2][2] = _tile("k", 2, 2)
    before_fp = board_fingerprint(board)
    after_fp = board_fingerprint(swapped)
    swap_payload = {
        "row_a": swap.row_a,
        "col_a": swap.col_a,
        "row_b": swap.row_b,
        "col_b": swap.col_b,
    }
    placements = [{"row": 2, "col": 2, "letter": "K", "index": 12}]
    assert fingerprint_change_is_suggested_board_progress(
        before_fp,
        after_fp,
        placements=placements,
        swap=swap_payload,
    )
    LAST_SUGGESTION_PATH.parent.mkdir(parents=True, exist_ok=True)
    LAST_SUGGESTION_PATH.write_text(
        json.dumps(
            {
                "board_fingerprint": before_fp,
                "twinkle_toes_swap": swap_payload,
                "consumable_placements": placements,
            }
        ),
        encoding="utf-8",
    )
    assert fingerprint_invalidate_suppressed_for_suggested_board_change(after_fp)
    assert stale_suggestion_warning(after_fp) is None
    assert (
        poll_invalidate_last_suggestion(
            {},
            current_board_fp=after_fp,
        )
        is None
    )


def test_no_suppress_when_swap_ok_but_placement_wrong():
    from cursed_words_solver.rules.twinkle_toes import swap_tile_contents, swap_to_record

    board = Board(tiles=[[_tile("x", r, c) for c in range(5)] for r in range(5)])
    board.tiles[1][3] = _tile("q", 1, 3)
    board.tiles[4][4] = _tile("m", 4, 4)
    board.tiles[2][2] = _tile("g", 2, 2)
    idx_a = 1 * 5 + 3
    idx_b = 4 * 5 + 4
    swap = swap_to_record(idx_a, idx_b)
    swapped = swap_tile_contents(board, idx_a, idx_b)
    swapped.tiles[2][2] = _tile("z", 2, 2)
    before_fp = board_fingerprint(board)
    after_fp = board_fingerprint(swapped)
    LAST_SUGGESTION_PATH.parent.mkdir(parents=True, exist_ok=True)
    LAST_SUGGESTION_PATH.write_text(
        json.dumps(
            {
                "board_fingerprint": before_fp,
                "twinkle_toes_swap": {
                    "row_a": swap.row_a,
                    "col_a": swap.col_a,
                    "row_b": swap.row_b,
                    "col_b": swap.col_b,
                },
                "consumable_placements": [
                    {"row": 2, "col": 2, "letter": "K", "index": 12},
                ],
            }
        ),
        encoding="utf-8",
    )
    from cursed_words_solver.suggestion import (
        fingerprint_invalidate_suppressed_for_suggested_board_change,
    )

    assert not fingerprint_invalidate_suppressed_for_suggested_board_change(after_fp)
    reason = poll_invalidate_last_suggestion({}, current_board_fp=after_fp)
    assert reason is not None
