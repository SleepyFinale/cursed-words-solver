"""Tests for melmod physical-pixel to Qt logical coordinate conversion."""

from cursed_words_solver.config import Region
from cursed_words_solver.ui.coordinates import (
    physical_to_qt_point,
    physical_to_qt_region,
)


def test_physical_to_qt_region_identity_at_1x():
    region = Region(1278, 161, 885, 884)
    assert physical_to_qt_region(region, dpr=1.0) == region


def test_physical_to_qt_region_scales_at_125():
    region = Region(1250, 125, 625, 500)
    scaled = physical_to_qt_region(region, dpr=1.25)
    assert scaled == Region(1000, 100, 500, 400)


def test_physical_to_qt_point_scales_at_125():
    x, y = physical_to_qt_point(1918.0, 978.0, dpr=1.25)
    assert abs(x - 1534.4) < 0.1
    assert abs(y - 782.4) < 0.1


def test_physical_to_qt_cell_centers_batch():
    from cursed_words_solver.ui.coordinates import physical_to_qt_cell_centers

    centers = {23: (1918.0, 978.0), 0: (1377.0, 255.0)}
    out = physical_to_qt_cell_centers(centers, anchor_x=1278, anchor_y=161, dpr=1.25)
    assert abs(out[23][0] - 1534.4) < 0.1
    assert abs(out[0][1] - 204.0) < 0.1
