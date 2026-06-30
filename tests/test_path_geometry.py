"""Tests for on-board path highlight geometry."""

import json
from pathlib import Path

from cursed_words_solver.config import Region
from cursed_words_solver.loadout import parse_board_from_run_state
from cursed_words_solver.ui.board_geometry import (
    estimate_rack_slot_size,
    path_from_melmod_indices,
    path_geometry,
    placement_display_steps,
    rack_marker_radius,
    rack_placement_geometry,
    rack_slot_center,
)
from tests.integration.test_run_state_board import _bat_4x3_run_state
from tests.test_ui_layout import _bat_3x3_ui_layout_run_state


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


def test_rack_slot_center_five_slots():
    region = Region(x=0, y=0, width=500, height=80)
    left = rack_slot_center(region, 0)
    right = rack_slot_center(region, 4)
    assert left is not None and right is not None
    assert abs(left[0] - 50.0) < 0.1
    assert abs(left[1] - 40.0) < 0.1
    assert abs(right[0] - 450.0) < 0.1
    assert rack_slot_center(region, -1) is None
    assert rack_slot_center(region, 5) is None


def test_rack_placement_geometry_maps_path_steps():
    region = Region(x=0, y=0, width=500, height=80)
    path = [17, 18, 19, 16]
    placements = [
        {"index": 17, "rack_index": 0, "letter": "E"},
        {"index": 19, "rack_index": 4, "letter": "O"},
    ]
    markers = rack_placement_geometry(region, path, placements)
    assert len(markers) == 2
    assert markers[0].step == 1
    assert abs(markers[0].x - 50.0) < 0.1
    assert markers[1].step == 3
    assert abs(markers[1].x - 450.0) < 0.1


def test_rack_placement_geometry_skips_invalid_rack_index():
    region = Region(x=0, y=0, width=500, height=80)
    path = [17, 18]
    placements = [{"index": 17, "rack_index": -1, "letter": "E"}]
    assert rack_placement_geometry(region, path, placements) == []


def test_path_geometry_bat_3x3_uses_remapped_cell_centers():
    """Shrunk 3×3 overlay aligns when cell centers use storage indices."""
    from cursed_words_solver.ui.layout import parse_ui_layout

    run_state = _bat_3x3_ui_layout_run_state()
    regions = parse_ui_layout(run_state)
    assert regions is not None
    path = [20, 10, 22]
    steps = path_geometry(
        regions.board,
        path,
        cell_centers=regions.board_cell_centers,
    )
    assert len(steps) == 3
    br = regions.board
    expected = {
        20: (823 - br.x, 590 - br.y),
        10: (829 - br.x, 316 - br.y),
        22: (1096 - br.x, 589 - br.y),
    }
    for step, idx in zip(steps, path, strict=True):
        ex, ey = expected[idx]
        assert abs(step.x - ex) < 1.0, f"idx {idx} x"
        assert abs(step.y - ey) < 1.0, f"idx {idx} y"


def test_path_geometry_uses_melmod_cell_centers():
    region = Region(x=100, y=200, width=700, height=700)
    cell_centers = {
        0: (170.0, 270.0),
        2: (450.0, 270.0),
    }
    steps = path_geometry(region, [0, 2], cell_centers=cell_centers)
    assert len(steps) == 2
    assert abs(steps[0].x - 70.0) < 0.1
    assert abs(steps[0].y - 70.0) < 0.1
    assert abs(steps[1].x - 350.0) < 0.1
    assert abs(steps[1].y - 70.0) < 0.1


def test_rack_placement_geometry_uses_melmod_slot_centers():
    region = Region(x=2400, y=570, width=290, height=44)
    path = [17, 19]
    placements = [
        {"index": 17, "rack_index": 0, "letter": "E"},
        {"index": 19, "rack_index": 4, "letter": "O"},
    ]
    rack_slot_centers = {0: (2429.0, 592.0), 4: (2661.0, 592.0)}
    markers = rack_placement_geometry(
        region,
        path,
        placements,
        rack_slot_centers=rack_slot_centers,
    )
    assert len(markers) == 2
    assert abs(markers[0].x - 29.0) < 0.1
    assert abs(markers[0].y - 22.0) < 0.1
    assert abs(markers[1].x - 261.0) < 0.1
    assert abs(markers[1].y - 22.0) < 0.1


def test_path_geometry_index_15_uses_solver_cell_center():
    region = Region(x=1277, y=159, width=884, height=885)
    cell_centers = {
        15: (1378.0, 436.0),
        10: (1374.0, 617.0),
    }
    steps = path_geometry(region, [15, 10], cell_centers=cell_centers)
    assert abs(steps[0].x - 101.0) < 0.1
    assert abs(steps[0].y - 277.0) < 0.1
    assert abs(steps[1].x - 97.0) < 0.1
    assert abs(steps[1].y - 458.0) < 0.1


def test_rack_placement_geometry_fallback_when_not_on_path():
    region = Region(x=0, y=0, width=500, height=80)
    path = [15, 10, 6]
    placements = [{"index": 99, "rack_index": 0, "letter": "3"}]
    markers = rack_placement_geometry(region, path, placements)
    assert len(markers) == 1
    assert markers[0].step == 1
    assert abs(markers[0].x - 50.0) < 0.1


def test_placement_display_steps_prefers_path_step():
    path = [15, 10, 6]
    placements = [{"index": 6, "rack_index": 0, "letter": "3"}]
    steps = placement_display_steps(path, placements)
    assert steps == [(3, placements[0])]


def test_rack_marker_radius_caps_for_typical_slot():
    radius = rack_marker_radius(150.0, 40.0, 61.0, 52.0, 305.0, 97.0)
    assert abs(radius - 18.0) < 0.1


def test_rack_marker_radius_clamps_near_edge():
    radius = rack_marker_radius(295.0, 90.0, 61.0, 52.0, 305.0, 97.0)
    assert radius < 18.0
    assert radius + 1.0 <= 305.0 - 295.0


def test_estimate_rack_slot_size_uses_spacing_and_exported_height():
    region = Region(0, 0, 305, 97)
    centers = {
        0: (29.0, 48.0),
        1: (90.0, 48.0),
        2: (151.0, 48.0),
        3: (212.0, 48.0),
        4: (273.0, 48.0),
    }
    slot_w, slot_h = estimate_rack_slot_size(
        region,
        centers,
        exported_rack_height=52.0,
    )
    assert abs(slot_w - 61.0) < 1.0
    assert abs(slot_h - 52.0) < 0.1


def test_estimate_rack_slot_size_prefers_melmod_slot_sizes():
    region = Region(0, 0, 305, 97)
    sizes = {0: (61.0, 52.0), 4: (61.0, 52.0)}
    slot_w, slot_h = estimate_rack_slot_size(region, None, rack_slot_sizes=sizes)
    assert abs(slot_w - 61.0) < 0.1
    assert abs(slot_h - 52.0) < 0.1


NINA_OVERLAY_FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "round_logs"
    / "20260630_145629_nina_false_encoding.json"
)


def test_nina_overlay_path_geometry_aligns_with_melmod_cell_centers():
    """F8 highlight centers match exported ui_layout for Nina 5×5 session."""
    if not NINA_OVERLAY_FIXTURE.exists():
        import pytest

        pytest.skip("nina overlay fixture required")

    data = json.loads(NINA_OVERLAY_FIXTURE.read_text(encoding="utf-8"))
    board = parse_board_from_run_state(data["run_state"])
    assert board is not None

    ui_board = data["run_state"]["ui_layout"]["board"]
    region = Region(
        x=int(ui_board["x"]),
        y=int(ui_board["y"]),
        width=int(ui_board["width"]),
        height=int(ui_board["height"]),
    )
    cell_centers = {
        int(cell["index"]): (float(cell["x"]), float(cell["y"]))
        for cell in ui_board["cells"]
    }

    melmod_path = data["solver"]["path"]
    storage_path = path_from_melmod_indices(board, melmod_path)
    steps = path_geometry(region, storage_path, board, cell_centers=cell_centers)
    assert len(steps) == len(storage_path)

    by_index = {int(cell["index"]): cell for cell in ui_board["cells"]}
    for idx, step in zip(storage_path, steps, strict=True):
        cell = by_index[int(idx)]
        expected_x = float(cell["x"]) - region.x
        expected_y = float(cell["y"]) - region.y
        assert abs(step.x - expected_x) < 30.0
        assert abs(step.y - expected_y) < 30.0
