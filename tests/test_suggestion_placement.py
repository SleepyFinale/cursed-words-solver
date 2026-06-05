"""Placement-progress fingerprint tolerance (Python solver + melmod ConsumablePlacementHelper)."""

import json

from cursed_words_solver.config import LAST_SUGGESTION_PATH
from cursed_words_solver.fingerprints import board_fingerprint
from cursed_words_solver.models import Board
from cursed_words_solver.suggestion import (
    fingerprint_change_is_consumable_placement_progress,
    fingerprint_change_is_suggested_consumable_placement_only,
    fingerprint_invalidate_suppressed_for_consumable_placement,
    poll_invalidate_last_suggestion,
)
from tests.test_search import _tile


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


def test_fingerprint_change_is_consumable_placement_only():
    before = _board_with_cell(1, 1, "x")
    after = _board_with_cell(1, 1, "u")
    placements = [{"row": 1, "col": 1, "letter": "U", "index": 6}]
    assert fingerprint_change_is_suggested_consumable_placement_only(
        board_fingerprint(before),
        board_fingerprint(after),
        placements,
    )


def test_fingerprint_change_not_placement_only_when_other_cells_move():
    before = _board_with_cell(1, 1, "x")
    after = Board(tiles=[[_tile("x", r, c) for c in range(5)] for r in range(5)])
    after.tiles[1][1] = _tile("u", 1, 1)
    after.tiles[0][0] = _tile("z", 0, 0)
    placements = [{"row": 1, "col": 1, "letter": "U", "index": 6}]
    assert not fingerprint_change_is_suggested_consumable_placement_only(
        board_fingerprint(before),
        board_fingerprint(after),
        placements,
    )


def test_partial_placement_one_of_two_suppresses_stale():
    before = _two_placement_board(
        cell_a=(2, 3, "i"),
        cell_b=(3, 3, "x"),
    )
    after = _two_placement_board(
        cell_a=(2, 3, "i"),
        cell_b=(3, 3, "u"),
    )
    placements = [
        {"row": 3, "col": 3, "letter": "U", "index": 18},
        {"row": 2, "col": 3, "letter": "E", "index": 13},
    ]
    assert fingerprint_change_is_consumable_placement_progress(
        board_fingerprint(before),
        board_fingerprint(after),
        placements,
    )


def test_full_placement_two_of_two_suppresses_stale():
    before = _two_placement_board(
        cell_a=(2, 3, "i"),
        cell_b=(3, 3, "x"),
    )
    after = _two_placement_board(
        cell_a=(2, 3, "e"),
        cell_b=(3, 3, "u"),
    )
    placements = [
        {"row": 3, "col": 3, "letter": "U", "index": 18},
        {"row": 2, "col": 3, "letter": "E", "index": 13},
    ]
    assert fingerprint_change_is_consumable_placement_progress(
        board_fingerprint(before),
        board_fingerprint(after),
        placements,
    )


def test_placement_plus_unrelated_change_does_not_suppress():
    before = _two_placement_board(
        cell_a=(2, 3, "i"),
        cell_b=(3, 3, "x"),
    )
    after = Board(tiles=[[_tile("x", r, c) for c in range(5)] for r in range(5)])
    after.tiles[2][3] = _tile("e", 2, 3)
    after.tiles[3][3] = _tile("u", 3, 3)
    after.tiles[0][0] = _tile("z", 0, 0)
    placements = [
        {"row": 3, "col": 3, "letter": "U", "index": 18},
        {"row": 2, "col": 3, "letter": "E", "index": 13},
    ]
    assert not fingerprint_change_is_consumable_placement_progress(
        board_fingerprint(before),
        board_fingerprint(after),
        placements,
    )


def test_poll_invalidate_none_during_partial_placement():
    before = _two_placement_board(
        cell_a=(2, 3, "i"),
        cell_b=(3, 3, "x"),
    )
    after = _two_placement_board(
        cell_a=(2, 3, "i"),
        cell_b=(3, 3, "u"),
    )
    LAST_SUGGESTION_PATH.parent.mkdir(parents=True, exist_ok=True)
    LAST_SUGGESTION_PATH.write_text(
        json.dumps(
            {
                "board_fingerprint": board_fingerprint(before),
                "consumable_placements": [
                    {"row": 3, "col": 3, "letter": "U", "index": 18},
                    {"row": 2, "col": 3, "letter": "E", "index": 13},
                ],
            }
        ),
        encoding="utf-8",
    )
    assert fingerprint_invalidate_suppressed_for_consumable_placement(
        board_fingerprint(after)
    )
    assert (
        poll_invalidate_last_suggestion(
            {},
            current_board_fp=board_fingerprint(after),
        )
        is None
    )


def test_suppress_invalidate_when_placement_matches():
    before = board_fingerprint(_board_with_cell(1, 1, "x"))
    after = board_fingerprint(_board_with_cell(1, 1, "u"))
    LAST_SUGGESTION_PATH.parent.mkdir(parents=True, exist_ok=True)
    LAST_SUGGESTION_PATH.write_text(
        json.dumps(
            {
                "board_fingerprint": before,
                "consumable_placements": [
                    {"row": 1, "col": 1, "letter": "U", "index": 6}
                ],
            }
        ),
        encoding="utf-8",
    )
    assert fingerprint_invalidate_suppressed_for_consumable_placement(after)
