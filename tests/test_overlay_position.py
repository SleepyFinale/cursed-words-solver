"""Tests for result overlay board-aware positioning (no Qt)."""

from cursed_words_solver.config import Region
from cursed_words_solver.ui.overlay import (
    _column_fallback_origin,
    _rects_overlap,
    compute_result_panel_origin,
)


def test_above_board_centered_no_overlap():
    board = Region(400, 200, 500, 500)
    avail = Region(0, 0, 1920, 1080)
    panel_w, panel_h = 200, 80
    x, y = compute_result_panel_origin(
        panel_w,
        panel_h,
        board_region=board,
        avail=avail,
    )
    assert y + panel_h <= board.y
    assert not _rects_overlap(x, y, panel_w, panel_h, board)
    expected_x = board.x + (board.width - panel_w) // 2
    assert x == expected_x


def test_board_flush_to_top_uses_right_of_board():
    board = Region(400, 0, 500, 500)
    avail = Region(0, 0, 1920, 1080)
    panel_w, panel_h = 200, 80
    x, y = compute_result_panel_origin(
        panel_w,
        panel_h,
        board_region=board,
        avail=avail,
    )
    assert x >= board.x + board.width
    assert y == board.y
    assert not _rects_overlap(x, y, panel_w, panel_h, board)


def test_no_board_region_uses_column_fallback():
    avail = Region(0, 0, 1920, 1080)
    panel_w, panel_h = 200, 80
    x, y = compute_result_panel_origin(
        panel_w,
        panel_h,
        board_region=None,
        avail=avail,
    )
    expected = _column_fallback_origin(panel_w, panel_h, avail)
    assert (x, y) == expected


def test_panel_wider_than_board_places_outside():
    board = Region(800, 100, 300, 300)
    avail = Region(0, 0, 1920, 1080)
    panel_w, panel_h = 400, 80
    x, y = compute_result_panel_origin(
        panel_w,
        panel_h,
        board_region=board,
        avail=avail,
    )
    assert not _rects_overlap(x, y, panel_w, panel_h, board)
    # Above-board is first choice when it fits without overlapping.
    assert y + panel_h <= board.y or x >= board.x + board.width or x + panel_w <= board.x
