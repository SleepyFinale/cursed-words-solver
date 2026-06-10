"""Tests for melmod ui_layout overlay region resolution."""

import json

import pytest

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
    assert regions.rack.width == 304
    assert len(regions.rack_slot_centers or {}) == 5


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
    assert "5 rack slots" in text


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


def _degenerate_board_cells():
    """25 cell centers spanning a normal 5×5 grid (modeled on a corrupt 6×5 export)."""
    cells = []
    for row in range(5):
        for col in range(5):
            cells.append(
                {
                    "row": row,
                    "col": col,
                    "index": row * 5 + col,
                    "x": 687 + col * 135,
                    "y": 183 + row * 135,
                }
            )
    return cells


def test_parse_ui_layout_repairs_degenerate_board_rect():
    run_state = {
        "ui_layout": {
            "board": {
                "x": 691,
                "y": 717,
                "width": 6,
                "height": 5,
                "cells": _degenerate_board_cells(),
            }
        }
    }
    parsed = parse_ui_layout(run_state)
    assert parsed is not None
    assert parsed.board_region_repaired is True
    assert parsed.board.width >= 200
    assert parsed.board.height >= 200
    assert parsed.board.width > 540 + 40
    assert parsed.board.height > 540 + 40
    assert len(parsed.board_cell_centers or {}) == 25
    assert parsed.board_cell_centers[0] == (687.0, 183.0)
    assert parsed.board_cell_centers[24] == (687.0 + 4 * 135, 183.0 + 4 * 135)


def test_parse_ui_layout_keeps_valid_board_rect():
    run_state = {
        "ui_layout": {
            "board": {
                "x": 620,
                "y": 119,
                "width": 673,
                "height": 668,
                "cells": _degenerate_board_cells(),
            }
        }
    }
    parsed = parse_ui_layout(run_state)
    assert parsed is not None
    assert parsed.board_region_repaired is False
    assert parsed.board == Region(620, 119, 673, 668)


def test_board_region_includes_marker_margin():
    """Tight cell-center bbox must grow enough that corner markers are not clipped."""
    cells = _degenerate_board_cells()
    run_state = {
        "ui_layout": {
            "board": {
                "x": 693,
                "y": 186,
                "width": 534,
                "height": 535,
                "cells": cells,
            }
        }
    }
    parsed = parse_ui_layout(run_state)
    assert parsed is not None
    br = parsed.board
    centers = parsed.board_cell_centers or {}
    min_inset = 36
    for idx in (0, 4, 20, 24):
        cx, cy = centers[idx]
        assert cx - br.x >= min_inset, f"cell {idx} too close to left edge"
        assert cy - br.y >= min_inset, f"cell {idx} too close to top edge"
        assert (br.x + br.width) - cx >= min_inset, f"cell {idx} too close to right edge"
        assert (br.y + br.height) - cy >= min_inset, f"cell {idx} too close to bottom edge"


def test_rack_slots_shifted_down_are_corrected():
    run_state = {
        "ui_layout": {
            "board": {"x": 0, "y": 0, "width": 100, "height": 100},
            "consumable_rack": {
                "x": 1579,
                "y": 532,
                "width": 281,
                "height": 48,
                "rack_slots": [
                    {
                        "rack_index": i,
                        "x": 1604 + i * 58,
                        "y": 726,
                        "width": 48,
                        "height": 48,
                    }
                    for i in range(5)
                ],
            },
        }
    }
    parsed = parse_ui_layout(run_state)
    assert parsed is not None
    assert parsed.rack_slot_corrected is True
    assert parsed.rack_slot_centers is not None
    for _idx, (_x, y) in parsed.rack_slot_centers.items():
        assert abs(y - 556.0) < 1.0
    rack_mid = parsed.rack.y + parsed.rack.height / 2.0
    assert abs(rack_mid - 556.0) < 80.0


def _good_rack_block():
    return {
        "x": 1579,
        "y": 532,
        "width": 281,
        "height": 48,
        "slot_count": 5,
        "rack_slots": [
            {
                "rack_index": i,
                "x": 1604 + i * 58,
                "y": 556,
                "width": 48,
                "height": 48,
            }
            for i in range(5)
        ],
    }


def _collapsed_rack_block():
    return {
        "x": 1565,
        "y": 697,
        "width": 58,
        "height": 58,
        "slot_count": 5,
        "rack_slots": [
            {
                "rack_index": i,
                "x": 1594,
                "y": 726,
                "width": 57,
                "height": 57,
            }
            for i in range(5)
        ],
    }


def test_degenerate_rack_detected():
    run_state = {
        "ui_layout": {
            "board": {"x": 0, "y": 0, "width": 100, "height": 100},
            "consumable_rack": _collapsed_rack_block(),
        }
    }
    parsed = parse_ui_layout(run_state)
    assert parsed is None or parsed.rack_slot_centers is None or parsed.rack_slot_corrected


def test_synthesize_slots_from_wide_rack_block():
    block = {
        "x": 1579,
        "y": 532,
        "width": 281,
        "height": 48,
        "slot_count": 5,
        "rack_slots": [
            {"rack_index": i, "x": 1594, "y": 726, "width": 48, "height": 48}
            for i in range(5)
        ],
    }
    run_state = {
        "ui_layout": {
            "board": {"x": 0, "y": 0, "width": 100, "height": 100},
            "consumable_rack": block,
        }
    }
    parsed = parse_ui_layout(run_state)
    assert parsed is not None
    assert parsed.rack_slot_corrected is True
    assert parsed.rack_slot_centers is not None
    xs = sorted(x for x, _ in parsed.rack_slot_centers.values())
    assert xs[-1] - xs[0] >= 200
    for _idx, (_x, y) in parsed.rack_slot_centers.items():
        assert abs(y - 556.0) < 2.0


def test_degenerate_collapsed_rack_uses_manual_fallback():
    from cursed_words_solver.config import AppConfig, Region

    config = AppConfig(
        rack_region=Region(x=100, y=500, width=400, height=60),
    )
    run_state = {
        "ui_layout": {
            "board": {"x": 0, "y": 0, "width": 100, "height": 100},
            "consumable_rack": _collapsed_rack_block(),
        }
    }
    parsed = parse_ui_layout(run_state, config=config)
    assert parsed is not None
    assert parsed.rack_slot_corrected is True
    assert parsed.rack_slot_centers is not None
    assert parsed.rack.width >= 200
