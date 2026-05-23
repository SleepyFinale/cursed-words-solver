"""Tests for on-board path highlight geometry."""

from cursed_words_solver.config import Region
from cursed_words_solver.ui.board_highlight import path_geometry


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
