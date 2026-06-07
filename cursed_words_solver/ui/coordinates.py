"""Convert melmod Win32 physical pixels to Qt logical overlay coordinates."""

from __future__ import annotations

from cursed_words_solver.config import Region


def melmod_dpr_at(x: int, y: int) -> float:
    """Device pixel ratio at a virtual-desktop point (1.0 when Qt unavailable)."""
    try:
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QGuiApplication

        if QGuiApplication.instance() is None:
            return 1.0
        screen = QGuiApplication.screenAt(QPoint(int(x), int(y)))
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is None:
            return 1.0
        return float(screen.devicePixelRatio())
    except Exception:
        return 1.0


def physical_to_qt_region(region: Region, *, dpr: float | None = None) -> Region:
    if not region.is_valid():
        return region
    if dpr is None:
        dpr = melmod_dpr_at(region.x, region.y)
    if dpr <= 1.0:
        return region
    return Region(
        int(round(region.x / dpr)),
        int(round(region.y / dpr)),
        max(1, int(round(region.width / dpr))),
        max(1, int(round(region.height / dpr))),
    )


def physical_to_qt_point(
    x: float,
    y: float,
    *,
    dpr: float | None = None,
    anchor_x: int | None = None,
    anchor_y: int | None = None,
) -> tuple[float, float]:
    if dpr is None:
        ax = int(anchor_x if anchor_x is not None else x)
        ay = int(anchor_y if anchor_y is not None else y)
        dpr = melmod_dpr_at(ax, ay)
    if dpr <= 1.0:
        return x, y
    return x / dpr, y / dpr


def physical_to_qt_cell_centers(
    centers: dict[int, tuple[float, float]],
    *,
    anchor_x: int,
    anchor_y: int,
    dpr: float | None = None,
) -> dict[int, tuple[float, float]]:
    if dpr is None:
        dpr = melmod_dpr_at(anchor_x, anchor_y)
    if dpr <= 1.0:
        return centers
    return {
        idx: physical_to_qt_point(x, y, dpr=dpr)
        for idx, (x, y) in centers.items()
    }


def physical_to_qt_sizes(
    sizes: dict[int, tuple[float, float]],
    *,
    dpr: float | None = None,
    anchor_x: int | None = None,
    anchor_y: int | None = None,
) -> dict[int, tuple[float, float]]:
    if dpr is None:
        ax = int(anchor_x if anchor_x is not None else 0)
        ay = int(anchor_y if anchor_y is not None else 0)
        dpr = melmod_dpr_at(ax, ay)
    if dpr <= 1.0:
        return sizes
    return {
        idx: (w / dpr, h / dpr)
        for idx, (w, h) in sizes.items()
    }


def convert_melmod_overlay_to_qt(
    board: Region,
    rack: Region,
    board_cell_centers: dict[int, tuple[float, float]] | None,
    rack_slot_centers: dict[int, tuple[float, float]] | None,
    rack_slot_sizes: dict[int, tuple[float, float]] | None = None,
    rack_tile_height: int | None = None,
) -> tuple[
    Region,
    Region,
    dict[int, tuple[float, float]] | None,
    dict[int, tuple[float, float]] | None,
    dict[int, tuple[float, float]] | None,
    int | None,
]:
    """Scale melmod physical-pixel layout into Qt logical coordinates."""
    dpr = melmod_dpr_at(board.x, board.y)
    if dpr <= 1.0:
        return board, rack, board_cell_centers, rack_slot_centers, rack_slot_sizes, rack_tile_height
    qt_board = physical_to_qt_region(board, dpr=dpr)
    qt_rack = physical_to_qt_region(rack, dpr=dpr) if rack.is_valid() else rack
    qt_cells = (
        physical_to_qt_cell_centers(
            board_cell_centers,
            anchor_x=board.x,
            anchor_y=board.y,
            dpr=dpr,
        )
        if board_cell_centers
        else None
    )
    qt_slots = (
        physical_to_qt_cell_centers(
            rack_slot_centers,
            anchor_x=board.x,
            anchor_y=board.y,
            dpr=dpr,
        )
        if rack_slot_centers
        else None
    )
    qt_sizes = (
        physical_to_qt_sizes(
            rack_slot_sizes,
            anchor_x=board.x,
            anchor_y=board.y,
            dpr=dpr,
        )
        if rack_slot_sizes
        else None
    )
    qt_tile_height = (
        max(1, int(round(rack_tile_height / dpr))) if rack_tile_height else None
    )
    return qt_board, qt_rack, qt_cells, qt_slots, qt_sizes, qt_tile_height
