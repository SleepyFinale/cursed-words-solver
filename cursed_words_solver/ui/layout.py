"""Resolve overlay regions from melmod ui_layout or manual config."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from cursed_words_solver.config import AppConfig, Region
from cursed_words_solver.ui.board_geometry import RACK_MARKER_RADIUS_MAX
from cursed_words_solver.ui.coordinates import convert_melmod_overlay_to_qt

_RACK_PADDING = 8
_MIN_RACK_HEIGHT = 40
_MAX_SINGLE_ROW_RACK_HEIGHT = 80
_RACK_MARKER_MARGIN = 28


@dataclass(frozen=True)
class OverlayRegions:
    board: Region
    rack: Region
    source: str
    board_cell_centers: dict[int, tuple[float, float]] | None = None
    rack_slot_centers: dict[int, tuple[float, float]] | None = None
    rack_slot_sizes: dict[int, tuple[float, float]] | None = None
    rack_tile_height: int | None = None


def _rect_from_block(block: Any) -> Region | None:
    if not isinstance(block, dict):
        return None
    try:
        width = int(block.get("width", 0))
        height = int(block.get("height", 0))
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    try:
        return Region(
            x=int(block.get("x", 0)),
            y=int(block.get("y", 0)),
            width=width,
            height=height,
        )
    except (TypeError, ValueError):
        return None


def _parse_cell_centers(block: Any) -> dict[int, tuple[float, float]] | None:
    if not isinstance(block, dict):
        return None
    cells = block.get("cells")
    if not isinstance(cells, list) or not cells:
        return None
    result: dict[int, tuple[float, float]] = {}
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        try:
            idx = int(cell["index"])
            x = float(cell["x"])
            y = float(cell["y"])
        except (KeyError, TypeError, ValueError):
            continue
        result[idx] = (x, y)
    return result or None


def _consumable_count_from_run_state(run_state: dict[str, Any] | None) -> int | None:
    if not run_state:
        return None
    extras = run_state.get("extras")
    if not isinstance(extras, dict):
        return None
    raw = extras.get("consumable_rack")
    if isinstance(raw, str) and raw.strip():
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return len(data)
        except json.JSONDecodeError:
            pass
    return None


def _filter_rack_slot_centers(
    block: Any,
    centers: dict[int, tuple[float, float]],
    run_state: dict[str, Any] | None,
) -> dict[int, tuple[float, float]]:
    if not centers:
        return centers
    slot_count = 0
    if isinstance(block, dict):
        try:
            slot_count = int(block.get("slot_count", 0))
        except (TypeError, ValueError):
            slot_count = 0
    if slot_count <= 5:
        return centers
    consumable_count = _consumable_count_from_run_state(run_state)
    if consumable_count is not None and consumable_count <= 5:
        filtered = {k: v for k, v in centers.items() if k < 5}
        if filtered:
            return filtered
    ys = sorted({y for _, y in centers.values()})
    if len(ys) >= 2 and ys[-1] - ys[0] > 80:
        return centers
    filtered = {k: v for k, v in centers.items() if k < 5}
    return filtered or centers


def _parse_rack_slot_centers(
    block: Any,
    run_state: dict[str, Any] | None = None,
) -> dict[int, tuple[float, float]] | None:
    if not isinstance(block, dict):
        return None
    slots = block.get("rack_slots")
    if not isinstance(slots, list) or not slots:
        return None
    result: dict[int, tuple[float, float]] = {}
    for slot in slots:
        if not isinstance(slot, dict):
            continue
        try:
            rack_index = int(slot["rack_index"])
            x = float(slot["x"])
            y = float(slot["y"])
        except (KeyError, TypeError, ValueError):
            continue
        result[rack_index] = (x, y)
    if not result:
        return None
    return _filter_rack_slot_centers(block, result, run_state)


def _parse_rack_slot_sizes(
    block: Any,
    run_state: dict[str, Any] | None = None,
) -> dict[int, tuple[float, float]] | None:
    if not isinstance(block, dict):
        return None
    slots = block.get("rack_slots")
    if not isinstance(slots, list) or not slots:
        return None
    centers = _parse_rack_slot_centers(block, run_state)
    if not centers:
        return None
    result: dict[int, tuple[float, float]] = {}
    for slot in slots:
        if not isinstance(slot, dict):
            continue
        try:
            rack_index = int(slot["rack_index"])
            width = float(slot.get("width", 0))
            height = float(slot.get("height", 0))
        except (KeyError, TypeError, ValueError):
            continue
        if rack_index not in centers or width <= 0 or height <= 0:
            continue
        result[rack_index] = (width, height)
    return result or None


def _rack_tile_height_from_block(block: Any) -> int | None:
    if not isinstance(block, dict):
        return None
    try:
        height = int(block.get("height", 0))
    except (TypeError, ValueError):
        return None
    return height if height > 0 else None


def _tight_rack_region(
    centers: dict[int, tuple[float, float]],
    fallback: Region,
    *,
    padding: int = _RACK_PADDING,
) -> Region:
    if not centers:
        return fallback
    xs = [x for x, _ in centers.values()]
    ys = [y for _, y in centers.values()]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    span_h = int(max_y - min_y)
    exported_h = fallback.height if fallback.is_valid() else _MIN_RACK_HEIGHT
    vertical_marker_pad = _RACK_MARKER_MARGIN + int(RACK_MARKER_RADIUS_MAX)
    if span_h <= 0:
        tile_h = max(exported_h, _MIN_RACK_HEIGHT)
        height = tile_h + 2 * vertical_marker_pad
    else:
        if exported_h > _MAX_SINGLE_ROW_RACK_HEIGHT:
            exported_h = _MAX_SINGLE_ROW_RACK_HEIGHT
        height = max(span_h + 2 * padding, exported_h, _MIN_RACK_HEIGHT)
        height = height + 2 * _RACK_MARKER_MARGIN
    mid_y = (min_y + max_y) / 2.0
    y = int(round(mid_y - height / 2.0))
    x = int(min_x) - padding - _RACK_MARKER_MARGIN
    width = max(1, int(max_x - min_x) + 2 * padding + 2 * _RACK_MARKER_MARGIN)
    return Region(max(0, x), max(0, y), width, height)


def parse_ui_layout(run_state: dict[str, Any] | None) -> OverlayRegions | None:
    """Parse melmod-exported ui_layout from run_state.json."""
    if not run_state:
        return None
    layout = run_state.get("ui_layout")
    if not isinstance(layout, dict):
        return None
    board_block = layout.get("board")
    board = _rect_from_block(board_block)
    if board is None or not board.is_valid():
        return None
    rack_block = layout.get("consumable_rack")
    rack_slot_centers = _parse_rack_slot_centers(rack_block, run_state)
    rack_slot_sizes = _parse_rack_slot_sizes(rack_block, run_state)
    rack_tile_height = _rack_tile_height_from_block(rack_block)
    rack = _rect_from_block(rack_block) or Region()
    if rack_slot_centers:
        rack = _tight_rack_region(rack_slot_centers, rack)
    board_cell_centers = _parse_cell_centers(board_block)
    board, rack, board_cell_centers, rack_slot_centers, rack_slot_sizes, rack_tile_height = (
        convert_melmod_overlay_to_qt(
            board,
            rack,
            board_cell_centers,
            rack_slot_centers,
            rack_slot_sizes,
            rack_tile_height,
        )
    )
    return OverlayRegions(
        board=board,
        rack=rack,
        source="melmod",
        board_cell_centers=board_cell_centers,
        rack_slot_centers=rack_slot_centers,
        rack_slot_sizes=rack_slot_sizes,
        rack_tile_height=rack_tile_height,
    )


def resolve_overlay_regions(
    run_state: dict[str, Any] | None,
    config: AppConfig,
) -> OverlayRegions:
    """Prefer melmod ui_layout; fall back to config.json manual regions."""
    parsed = parse_ui_layout(run_state)
    if parsed is not None:
        return parsed
    return OverlayRegions(
        board=config.board_region,
        rack=config.rack_region,
        source="manual",
    )


def ui_layout_export_status(run_state: dict[str, Any] | None) -> str | None:
    """Return export_diagnostics.ui_layout_status when ui_layout is missing."""
    if not run_state or run_state.get("ui_layout") is not None:
        return None
    diag = run_state.get("export_diagnostics")
    if isinstance(diag, dict):
        status = diag.get("ui_layout_status")
        if isinstance(status, str) and status:
            return status
    return "missing"


def overlay_regions_ready(regions: OverlayRegions) -> bool:
    return regions.board.is_valid()


def describe_overlay_source(regions: OverlayRegions) -> str:
    if regions.source == "melmod":
        parts = [f"board {regions.board.width}×{regions.board.height} at ({regions.board.x},{regions.board.y})"]
        cell_count = len(regions.board_cell_centers or {})
        if cell_count:
            parts.append(f"{cell_count} cells")
        if regions.rack.is_valid():
            parts.append(
                f"rack {regions.rack.width}×{regions.rack.height} at ({regions.rack.x},{regions.rack.y})"
            )
            slot_count = len(regions.rack_slot_centers or {})
            if slot_count:
                parts.append(f"{slot_count} rack slots")
        return "melmod (auto): " + "; ".join(parts)
    parts: list[str] = []
    if regions.board.is_valid():
        parts.append(
            f"board {regions.board.width}×{regions.board.height} at ({regions.board.x},{regions.board.y})"
        )
    if regions.rack.is_valid():
        parts.append(
            f"rack {regions.rack.width}×{regions.rack.height} at ({regions.rack.x},{regions.rack.y})"
        )
    if parts:
        return "manual (F10): " + "; ".join(parts)
    return "manual (F10): not set — press F10 to calibrate"
