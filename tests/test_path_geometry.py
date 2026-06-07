"""Tests for on-board path highlight geometry."""

from cursed_words_solver.config import Region
from cursed_words_solver.loadout import parse_board_from_run_state
from cursed_words_solver.ui.board_geometry import path_geometry
from tests.integration.test_run_state_board import _bat_4x3_run_state


def test_path_geometry_cell_centers_within_region():
    region = Region(x=100, y=200, width=500, height=500)
    steps = path_geometry(region, [0, 1, 2])
    assert len(steps) == 3
    assert steps[0].step == 1
    assert steps[2].step == 3
    # Index 0: row 0 col 0 -> center of first cell
    assert 40 < steps[0].x < 60
    assert 40 < steps[0].y < 60
    # Index 2: row 0 col 2
    assert 240 < steps[2].x < 260
    assert 40 < steps[2].y < 60
    for s in steps:
        assert 0 <= s.x <= region.width
        assert 0 <= s.y <= region.height


def test_path_geometry_empty_path():
    region = Region(x=0, y=0, width=100, height=100)
    assert path_geometry(region, []) == []


def test_path_geometry_invalid_region():
    region = Region()
    assert path_geometry(region, [0, 1]) == []


def test_path_geometry_bat_4x3_remaps_to_centered_slots():
    """Bat storage rows 2–4 map to visual slots 1–3 in the 5×5 frame."""
    board = parse_board_from_run_state(_bat_4x3_run_state())
    assert board is not None
    region = Region(x=0, y=0, width=500, height=500)
    # storage row 2, col 0 -> index 10 -> visual slot row 1, col 0.5
    steps = path_geometry(region, [10], board)
    assert len(steps) == 1
    assert abs(steps[0].x - 100.0) < 1.0
    assert abs(steps[0].y - 150.0) < 1.0
    # storage row 4, col 3 -> index 23 -> visual slot row 3, col 3.5
    steps = path_geometry(region, [23], board)
    assert abs(steps[0].x - 400.0) < 1.0
    assert abs(steps[0].y - 350.0) < 1.0


def test_path_geometry_copsy_path_step1_on_bottom_right():
    board = parse_board_from_run_state(_bat_4x3_run_state())
    assert board is not None
    region = Region(x=0, y=0, width=500, height=500)
    steps = path_geometry(region, [23, 22, 18, 17, 11], board)
    assert len(steps) == 5
    # Step 1: storage row 4 col 3 (bottom-right of 4×3)
    assert abs(steps[0].x - 400.0) < 1.0
    assert abs(steps[0].y - 350.0) < 1.0
    # Step 5: storage row 2 col 1 (top row, second column)
    assert abs(steps[4].x - 200.0) < 1.0
    assert abs(steps[4].y - 150.0) < 1.0


def test_parse_board_infers_playable_bounds_without_melmod_fields():
    data = _bat_4x3_run_state()
    del data["board"]["playable_origin"]
    del data["board"]["playable_min_row"]
    del data["board"]["playable_max_row"]
    del data["board"]["playable_min_col"]
    del data["board"]["playable_max_col"]
    board = parse_board_from_run_state(data)
    assert board is not None
    assert board.playable_min_row == 2
    assert board.playable_max_row == 4
    assert board.playable_min_col == 0
    assert board.playable_max_col == 3
    assert board.playable_origin == "bottom_left"


def test_parse_board_playable_bounds_from_run_state():
    board = parse_board_from_run_state(_bat_4x3_run_state())
    assert board is not None
    assert board.playable_origin == "bottom_left"
    assert board.playable_min_row == 2
    assert board.playable_max_row == 4
    assert board.playable_min_col == 0
    assert board.playable_max_col == 3
