"""Board overlay coordinate math (no Qt dependencies)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cursed_words_solver.config import Region
from cursed_words_solver.models import Board

_GRID_SLOTS = 5
_RACK_SLOTS = 5
RACK_MARKER_RADIUS_MIN = 10.0
RACK_MARKER_RADIUS_MAX = 18.0
RACK_MARKER_RADIUS_FACTOR = 0.38
RACK_MARKER_PEN_WIDTH = 2.0


def playable_bounds(board: Board) -> tuple[int, int, int, int] | None:
    """Return (min_row, max_row, min_col, max_col) for active playable cells."""
    min_r, max_r, min_c, max_c = board.storage_rows, -1, board.storage_cols, -1
    for r in range(board.storage_rows):
        for c in range(board.storage_cols):
            if board.is_active_cell(r, c):
                min_r = min(min_r, r)
                max_r = max(max_r, r)
                min_c = min(min_c, c)
                max_c = max(max_c, c)
    if max_r < 0:
        return None
    return min_r, max_r, min_c, max_c


def _is_shrunk_grid(board: Board) -> bool:
    storage = max(board.rows, board.cols)
    return board.rows < storage or board.cols < storage


@dataclass(frozen=True)
class PathStep:
    """Center of a tile in overlay-local coordinates and draw order (1-based)."""

    x: float
    y: float
    step: int


@dataclass(frozen=True)
class PlacementMarker:
    """Suggested consumable placement cell (overlay-local coords)."""

    x: float
    y: float
    letter: str


def _index_center(
    idx: int,
    *,
    slot_w: float,
    slot_h: float,
    board: Board | None,
) -> tuple[float, float]:
    cols = board.storage_cols if board else _GRID_SLOTS
    rows = board.storage_rows if board else _GRID_SLOTS
    row, col = divmod(idx, cols)
    bounds = playable_bounds(board) if board else None
    shrunk = board is not None and _is_shrunk_grid(board) and bounds is not None
    if shrunk:
        min_r, max_r, min_c, max_c = bounds
        playable_h = max_r - min_r + 1
        playable_w = max_c - min_c + 1
        row_margin = (rows - playable_h) / 2.0
        col_margin = (cols - playable_w) / 2.0
        slot_row = row - min_r + row_margin
        slot_col = col - min_c + col_margin
    else:
        slot_row = row
        slot_col = col
    return (slot_col + 0.5) * slot_w, (slot_row + 0.5) * slot_h


@dataclass(frozen=True)
class RackMarker:
    """Suggested consumable rack slot (overlay-local coords, path step number)."""

    x: float
    y: float
    step: int


def _placement_record_index(placement: Any) -> int | None:
    idx = getattr(placement, "index", None)
    if idx is None and isinstance(placement, dict):
        idx = placement.get("index")
    if idx is None:
        row = getattr(placement, "row", None)
        col = getattr(placement, "col", None)
        if row is None and isinstance(placement, dict):
            row = placement.get("row")
            col = placement.get("col")
        if row is not None and col is not None:
            idx = int(row) * _GRID_SLOTS + int(col)
    return int(idx) if idx is not None else None


def _placement_record_rack_index(placement: Any) -> int:
    raw = getattr(placement, "rack_index", None)
    if raw is None and isinstance(placement, dict):
        raw = placement.get("rack_index")
    try:
        return int(raw) if raw is not None else -1
    except (TypeError, ValueError):
        return -1


def _absolute_to_local(
    region: Region,
    abs_x: float,
    abs_y: float,
) -> tuple[float, float]:
    return abs_x - float(region.x), abs_y - float(region.y)


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


def estimate_rack_slot_size(
    region: Region,
    rack_slot_centers: dict[int, tuple[float, float]] | None = None,
    *,
    exported_rack_height: float | None = None,
    rack_slot_sizes: dict[int, tuple[float, float]] | None = None,
    slot_count: int = _RACK_SLOTS,
) -> tuple[float, float]:
    """Estimate consumable rack tile width/height for marker sizing."""
    slot_w = float(region.width) / float(slot_count)
    slot_h = float(region.height) * 0.55

    if rack_slot_sizes:
        widths = [w for w, _ in rack_slot_sizes.values() if w > 0]
        heights = [h for _, h in rack_slot_sizes.values() if h > 0]
        median_w = _median(widths)
        median_h = _median(heights)
        if median_w is not None:
            slot_w = median_w
        if median_h is not None:
            slot_h = median_h

    if rack_slot_centers and len(rack_slot_centers) >= 2:
        xs = sorted(x for x, _ in rack_slot_centers.values())
        spacings = [
            xs[i + 1] - xs[i] for i in range(len(xs) - 1) if xs[i + 1] - xs[i] > 1.0
        ]
        median_spacing = _median(spacings)
        if median_spacing is not None:
            slot_w = median_spacing

    if exported_rack_height is not None and exported_rack_height > 0:
        slot_h = float(exported_rack_height)

    return slot_w, slot_h


def rack_marker_radius(
    x: float,
    y: float,
    slot_w: float,
    slot_h: float,
    region_w: float,
    region_h: float,
    *,
    pen_width: float = RACK_MARKER_PEN_WIDTH,
) -> float:
    """Radius for a rack marker circle that fits inside the tile square."""
    half_pen = pen_width * 0.5
    base = min(slot_w, slot_h) * RACK_MARKER_RADIUS_FACTOR
    radius = max(RACK_MARKER_RADIUS_MIN, min(RACK_MARKER_RADIUS_MAX, base))
    max_rx = min(x - half_pen, region_w - x - half_pen)
    max_ry = min(y - half_pen, region_h - y - half_pen)
    max_r = min(max_rx, max_ry)
    if max_r < RACK_MARKER_RADIUS_MIN:
        return max(0.0, max_r)
    return min(radius, max_r)


def rack_slot_center(
    region: Region,
    rack_index: int,
    *,
    slot_count: int = _RACK_SLOTS,
    rack_slot_centers: dict[int, tuple[float, float]] | None = None,
) -> tuple[float, float] | None:
    """Center of a consumable rack slot within a calibrated rack row region."""
    if rack_index < 0:
        return None
    if rack_slot_centers and rack_index in rack_slot_centers:
        return _absolute_to_local(region, *rack_slot_centers[rack_index])
    if not region.is_valid() or rack_index >= slot_count:
        return None
    slot_w = float(region.width) / float(slot_count)
    slot_h = float(region.height)
    return (rack_index + 0.5) * slot_w, slot_h * 0.5


def placement_display_steps(
    path: list[int],
    placements: list[Any],
) -> list[tuple[int, Any]]:
    """Map each placement to a display step (path step if on path, else placement order)."""
    index_to_step = {idx: step for step, idx in enumerate(path, start=1)}
    steps: list[tuple[int, Any]] = []
    for placement_order, placement in enumerate(placements, start=1):
        idx = _placement_record_index(placement)
        if idx is None:
            continue
        step = index_to_step.get(idx, placement_order)
        steps.append((step, placement))
    steps.sort(key=lambda item: item[0])
    return steps


def rack_placement_geometry(
    region: Region,
    path: list[int],
    placements: list[Any],
    *,
    slot_count: int = _RACK_SLOTS,
    rack_slot_centers: dict[int, tuple[float, float]] | None = None,
) -> list[RackMarker]:
    """Map suggested placements to rack slot centers with path step numbers."""
    if not region.is_valid() or not path or not placements:
        return []
    markers: list[RackMarker] = []
    for step, placement in placement_display_steps(path, placements):
        rack_index = _placement_record_rack_index(placement)
        if rack_index < 0:
            continue
        center = rack_slot_center(
            region,
            rack_index,
            slot_count=slot_count,
            rack_slot_centers=rack_slot_centers,
        )
        if center is None:
            continue
        markers.append(RackMarker(x=center[0], y=center[1], step=step))
    return markers


def path_geometry(
    region: Region,
    path: list[int],
    board: Board | None = None,
    *,
    cell_centers: dict[int, tuple[float, float]] | None = None,
) -> list[PathStep]:
    """Map tile indices to centers within a board region (overlay-local coords).

    Indices use the solver's 5×5 storage (row 0 = top). For shrunk Bat-style
    grids the active block may occupy storage rows 2–4 while the game renders
    those tiles centered in the calibrated 5×5 frame (e.g. 4×3 in slots 1–3).
    """
    if not region.is_valid() or not path:
        return []
    w, h = float(region.width), float(region.height)
    slot_w = w / float(_GRID_SLOTS)
    slot_h = h / float(_GRID_SLOTS)

    steps: list[PathStep] = []
    for step, idx in enumerate(path, start=1):
        if cell_centers and idx in cell_centers:
            cx, cy = _absolute_to_local(region, *cell_centers[idx])
        else:
            cx, cy = _index_center(idx, slot_w=slot_w, slot_h=slot_h, board=board)
        steps.append(PathStep(x=cx, y=cy, step=step))
    return steps


def placement_geometry(
    region: Region,
    placements: list[Any],
    board: Board | None = None,
    *,
    cell_centers: dict[int, tuple[float, float]] | None = None,
) -> list[PlacementMarker]:
    """Map consumable placement records to overlay-local centers."""
    if not region.is_valid() or not placements:
        return []
    w, h = float(region.width), float(region.height)
    slot_w = w / float(_GRID_SLOTS)
    slot_h = h / float(_GRID_SLOTS)
    markers: list[PlacementMarker] = []
    for placement in placements:
        idx = getattr(placement, "index", None)
        if idx is None and isinstance(placement, dict):
            idx = placement.get("index")
        if idx is None:
            row = getattr(placement, "row", None)
            col = getattr(placement, "col", None)
            if row is None and isinstance(placement, dict):
                row = placement.get("row")
                col = placement.get("col")
            if row is not None and col is not None:
                idx = int(row) * _GRID_SLOTS + int(col)
        if idx is None:
            continue
        letter = getattr(placement, "letter", None)
        if letter is None and isinstance(placement, dict):
            letter = placement.get("letter")
        if cell_centers and int(idx) in cell_centers:
            cx, cy = _absolute_to_local(region, *cell_centers[int(idx)])
        else:
            cx, cy = _index_center(int(idx), slot_w=slot_w, slot_h=slot_h, board=board)
        markers.append(
            PlacementMarker(x=cx, y=cy, letter=str(letter or "?").upper())
        )
    return markers


def _swap_indices(swap: Any, *, cols: int) -> tuple[int, int] | None:
    if swap is None:
        return None
    row_a = getattr(swap, "row_a", None)
    col_a = getattr(swap, "col_a", None)
    row_b = getattr(swap, "row_b", None)
    col_b = getattr(swap, "col_b", None)
    if isinstance(swap, dict):
        row_a = swap.get("row_a", row_a)
        col_a = swap.get("col_a", col_a)
        row_b = swap.get("row_b", row_b)
        col_b = swap.get("col_b", col_b)
    if row_a is None or col_a is None or row_b is None or col_b is None:
        return None
    return int(row_a) * cols + int(col_a), int(row_b) * cols + int(col_b)


def swap_geometry(
    region: Region,
    swap: Any,
    board: Board | None = None,
    *,
    cell_centers: dict[int, tuple[float, float]] | None = None,
) -> list[PlacementMarker]:
    """Map Twinkle Toes swap cells to overlay-local centers."""
    if not region.is_valid():
        return []
    cols = board.storage_cols if board is not None else _GRID_SLOTS
    rows = board.storage_rows if board is not None else _GRID_SLOTS
    indices = _swap_indices(swap, cols=cols)
    if indices is None:
        return []
    w, h = float(region.width), float(region.height)
    slot_w = w / float(max(1, cols))
    slot_h = h / float(max(1, rows))
    markers: list[PlacementMarker] = []
    for idx in indices:
        if cell_centers and int(idx) in cell_centers:
            cx, cy = _absolute_to_local(region, *cell_centers[int(idx)])
        else:
            cx, cy = _index_center(int(idx), slot_w=slot_w, slot_h=slot_h, board=board)
        markers.append(PlacementMarker(x=cx, y=cy, letter=""))
    return markers
