"""Tests for melmod ui_layout overlay region resolution."""

from cursed_words_solver.config import AppConfig, Region
from cursed_words_solver.ui.layout import (
    describe_overlay_source,
    overlay_regions_ready,
    parse_ui_layout,
    resolve_overlay_regions,
    ui_layout_export_status,
)


def test_parse_ui_layout_board_and_rack():
    run_state = {
        "ui_layout": {
            "coordinate_space": "screen_top_left",
            "board": {
                "x": 100,
                "y": 200,
                "width": 700,
                "height": 700,
                "cells": [
                    {"row": 0, "col": 0, "index": 0, "x": 170, "y": 270},
                    {"row": 0, "col": 1, "index": 1, "x": 310, "y": 270},
                ],
            },
            "consumable_rack": {
                "x": 2400,
                "y": 570,
                "width": 290,
                "height": 44,
                "rack_slots": [
                    {"rack_index": 0, "x": 2429, "y": 592},
                    {"rack_index": 4, "x": 2661, "y": 592},
                ],
            },
        }
    }
    parsed = parse_ui_layout(run_state)
    assert parsed is not None
    assert parsed.source == "melmod"
    assert parsed.board == Region(100, 200, 700, 700)
    assert parsed.rack == Region(2393, 524, 304, 136)
    assert parsed.rack_tile_height == 44
    assert parsed.board_cell_centers == {0: (170.0, 270.0), 1: (310.0, 270.0)}
    assert parsed.rack_slot_centers == {0: (2429.0, 592.0), 4: (2661.0, 592.0)}


def test_parse_ui_layout_missing_board():
    assert parse_ui_layout({"ui_layout": {"consumable_rack": {"x": 1, "y": 2, "width": 3, "height": 4}}}) is None


def test_resolve_prefers_melmod_over_config():
    config = AppConfig(
        board_region=Region(1, 2, 3, 4),
        rack_region=Region(5, 6, 7, 8),
    )
    run_state = {
        "ui_layout": {
            "board": {"x": 100, "y": 200, "width": 700, "height": 700},
            "consumable_rack": {"x": 2400, "y": 570, "width": 290, "height": 44},
        }
    }
    regions = resolve_overlay_regions(run_state, config)
    assert regions.source == "melmod"
    assert regions.board.width == 700
    assert regions.rack.x == 2400


def test_resolve_falls_back_to_config():
    config = AppConfig(
        board_region=Region(10, 20, 300, 300),
        rack_region=Region(40, 50, 100, 40),
    )
    regions = resolve_overlay_regions(None, config)
    assert regions.source == "manual"
    assert regions.board == config.board_region
    assert regions.rack == config.rack_region


def test_overlay_regions_ready():
    assert overlay_regions_ready(
        resolve_overlay_regions(
            {"ui_layout": {"board": {"x": 0, "y": 0, "width": 10, "height": 10}}},
            AppConfig(),
        )
    )
    assert not overlay_regions_ready(resolve_overlay_regions(None, AppConfig()))


def test_describe_overlay_source_melmod():
    regions = resolve_overlay_regions(
        {
            "ui_layout": {
                "board": {
                    "x": 100,
                    "y": 200,
                    "width": 700,
                    "height": 700,
                    "cells": [{"row": 0, "col": 0, "index": 0, "x": 170, "y": 270}],
                },
                "consumable_rack": {
                    "x": 2400,
                    "y": 570,
                    "width": 290,
                    "height": 44,
                    "rack_slots": [{"rack_index": 0, "x": 2429, "y": 592}],
                },
            }
        },
        AppConfig(),
    )
    text = describe_overlay_source(regions)
    assert text.startswith("melmod (auto):")
    assert "700×700" in text
    assert "1 cells" in text
    assert "rack" in text
    assert "1 rack slots" in text


def test_ui_layout_export_status_from_diagnostics():
    run_state = {
        "ui_layout": None,
        "export_diagnostics": {"ui_layout_status": "board_bounds_empty"},
    }
    assert ui_layout_export_status(run_state) == "board_bounds_empty"
    assert ui_layout_export_status({"ui_layout": {"board": {"x": 0, "y": 0, "width": 1, "height": 1}}}) is None


def test_parse_ui_layout_solver_row_flip():
    """Index 0 is top row (low Y); index 20 is bottom row (high Y)."""
    run_state = {
        "ui_layout": {
            "board": {
                "x": 100,
                "y": 150,
                "width": 700,
                "height": 700,
                "cells": [
                    {"row": 0, "col": 0, "index": 0, "x": 170, "y": 260},
                    {"row": 4, "col": 0, "index": 20, "x": 170, "y": 960},
                ],
            }
        }
    }
    parsed = parse_ui_layout(run_state)
    assert parsed is not None
    assert parsed.board_cell_centers[0] == (170.0, 260.0)
    assert parsed.board_cell_centers[20] == (170.0, 960.0)
    assert parsed.board_cell_centers[0][1] < parsed.board_cell_centers[20][1]


def test_parse_ui_layout_filters_collapsed_rack_slots():
    run_state = {
        "extras": {
            "consumable_rack": '[{"rack_index":0},{"rack_index":1},{"rack_index":2},{"rack_index":3},{"rack_index":4}]',
        },
        "ui_layout": {
            "board": {"x": 0, "y": 0, "width": 100, "height": 100},
            "consumable_rack": {
                "x": 2900,
                "y": 700,
                "width": 414,
                "height": 278,
                "slot_count": 10,
                "rack_slots": [
                    {"rack_index": 0, "x": 3019, "y": 741},
                    {"rack_index": 4, "x": 3328, "y": 741},
                    {"rack_index": 5, "x": 2979, "y": 955},
                    {"rack_index": 9, "x": 2979, "y": 955},
                ],
            },
        },
    }
    parsed = parse_ui_layout(run_state)
    assert parsed is not None
    assert parsed.rack_slot_centers is not None
    assert 5 not in parsed.rack_slot_centers
    assert parsed.rack.height >= 80
    assert parsed.rack.width >= 300


def test_rack_region_fits_rightmost_marker():
    """Rightmost slot center plus circle radius must stay inside rack overlay."""
    from cursed_words_solver.ui.board_geometry import (
        rack_marker_radius,
        rack_placement_geometry,
    )

    run_state = {
        "ui_layout": {
            "board": {"x": 0, "y": 0, "width": 100, "height": 100},
            "consumable_rack": {
                "x": 2900,
                "y": 700,
                "width": 374,
                "height": 65,
                "slot_count": 5,
                "rack_slots": [
                    {"rack_index": 0, "x": 3019, "y": 741, "width": 61, "height": 52},
                    {"rack_index": 4, "x": 3328, "y": 741, "width": 61, "height": 52},
                ],
            },
        }
    }
    regions = parse_ui_layout(run_state)
    assert regions is not None
    assert regions.rack.height == 65 + 2 * (28 + 18)
    markers = rack_placement_geometry(
        regions.rack,
        [23],
        [{"index": 23, "rack_index": 4, "letter": "1"}],
        rack_slot_centers=regions.rack_slot_centers,
    )
    assert len(markers) == 1
    slot_w, slot_h = 61.0, 52.0
    if regions.rack_slot_sizes:
        sizes = list(regions.rack_slot_sizes.values())
        slot_w, slot_h = sizes[0]
    radius = rack_marker_radius(
        markers[0].x,
        markers[0].y,
        slot_w,
        slot_h,
        float(regions.rack.width),
        float(regions.rack.height),
    )
    assert markers[0].x - radius >= 0
    assert markers[0].x + radius <= regions.rack.width
    assert markers[0].y - radius >= 0
    assert markers[0].y + radius <= regions.rack.height
