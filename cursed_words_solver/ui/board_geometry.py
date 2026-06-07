"""Board overlay coordinate math (no Qt dependencies)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cursed_words_solver.config import Region
from cursed_words_solver.models import Board

_GRID_SLOTS = 5


def playable_bounds(board: Board) -> tuple[int, int, int, int] | None:
    """Return (min_row, max_row, min_col, max_col) for active playable cells."""
    min_r, max_r, min_c, max_c = _GRID_SLOTS, -1, _GRID_SLOTS, -1
    for r in range(_GRID_SLOTS):
        for c in range(_GRID_SLOTS):
            if board.is_active_cell(r, c):
                min_r = min(min_r, r)
                max_r = max(max_r, r)
                min_c = min(min_c, c)
                max_c = max(max_c, c)
    if max_r < 0:
        return None
    return min_r, max_r, min_c, max_c


def _is_shrunk_grid(board: Board) -> bool:
    return board.rows < _GRID_SLOTS or board.cols < _GRID_SLOTS


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
    row, col = idx // _GRID_SLOTS, idx % _GRID_SLOTS
    bounds = playable_bounds(board) if board else None
    shrunk = board is not None and _is_shrunk_grid(board) and bounds is not None
    if shrunk:
        min_r, max_r, min_c, max_c = bounds
        playable_h = max_r - min_r + 1
        playable_w = max_c - min_c + 1
        row_margin = (_GRID_SLOTS - playable_h) / 2.0
        col_margin = (_GRID_SLOTS - playable_w) / 2.0
        slot_row = row - min_r + row_margin
        slot_col = col - min_c + col_margin
    else:
        slot_row = row
        slot_col = col
    return (slot_col + 0.5) * slot_w, (slot_row + 0.5) * slot_h


def path_geometry(
    region: Region,
    path: list[int],
    board: Board | None = None,
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
        cx, cy = _index_center(idx, slot_w=slot_w, slot_h=slot_h, board=board)
        steps.append(PathStep(x=cx, y=cy, step=step))
    return steps


def placement_geometry(
    region: Region,
    placements: list[Any],
    board: Board | None = None,
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
        cx, cy = _index_center(int(idx), slot_w=slot_w, slot_h=slot_h, board=board)
        markers.append(
            PlacementMarker(x=cx, y=cy, letter=str(letter or "?").upper())
        )
    return markers
