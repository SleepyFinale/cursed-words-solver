"""Resolve overlay regions from melmod ui_layout or manual config."""

from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass
from typing import Any

from cursed_words_solver.config import AppConfig, Region
from cursed_words_solver.ui.board_geometry import RACK_MARKER_RADIUS_MAX
from cursed_words_solver.ui.coordinates import convert_melmod_overlay_to_qt

_RACK_PADDING = 8
_MIN_RACK_HEIGHT = 40
_MAX_SINGLE_ROW_RACK_HEIGHT = 80
_RACK_MARKER_MARGIN = 28
_BOARD_CELL_PADDING = 20
_MIN_BOARD_DIM = 100
_MIN_CELL_SPAN = 200
_MARKER_MARGIN_FACTOR = 0.45
_RACK_SLOT_Y_TOLERANCE = 60
_MIN_RACK_SLOT_SPAN = 100
_MIN_RACK_BLOCK_WIDTH = 100
_RACK_SLOT_COUNT = 5


@dataclass(frozen=True)
class OverlayRegions:
    board: Region
    rack: Region
    source: str
    board_cell_centers: dict[int, tuple[float, float]] | None = None
    rack_slot_centers: dict[int, tuple[float, float]] | None = None
    rack_slot_sizes: dict[int, tuple[float, float]] | None = None
    rack_tile_height: int | None = None
    board_region_repaired: bool = False
    rack_slot_corrected: bool = False
    rack_layout_collapsed: bool = False


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


def _storage_size_from_run_state(run_state: dict[str, Any] | None) -> int:
    if not run_state:
        return _RACK_SLOT_COUNT
    board_data = run_state.get("board")
    if not isinstance(board_data, dict):
        return _RACK_SLOT_COUNT
    tiles = board_data.get("tiles")
    if isinstance(tiles, list) and len(tiles) == 36:
        return 6
    return _RACK_SLOT_COUNT


def _remap_layout_cell_centers_to_storage(
    board_block: Any,
    centers: dict[int, tuple[float, float]] | None,
    run_state: dict[str, Any] | None,
) -> dict[int, tuple[float, float]] | None:
    """Map ui_layout cell indices (layout rows×cols) to solver storage indices."""
    if not centers or not isinstance(board_block, dict):
        return centers
    try:
        layout_rows = int(board_block.get("rows", _RACK_SLOT_COUNT))
        layout_cols = int(board_block.get("cols", _RACK_SLOT_COUNT))
    except (TypeError, ValueError):
        layout_rows = layout_cols = _RACK_SLOT_COUNT
    storage = _storage_size_from_run_state(run_state)
    if layout_rows >= storage and layout_cols >= storage:
        return centers
    if centers and max(centers) >= layout_rows * layout_cols:
        return centers

    board_data = run_state.get("board") if run_state else None
    if not isinstance(board_data, dict):
        return centers
    try:
        pmin_r = int(board_data.get("playable_min_row", 0))
        pmin_c = int(board_data.get("playable_min_col", 0))
    except (TypeError, ValueError):
        pmin_r = pmin_c = 0

    cells = board_block.get("cells")
    if isinstance(cells, list) and cells:
        remapped: dict[int, tuple[float, float]] = {}
        for cell in cells:
            if not isinstance(cell, dict):
                continue
            try:
                cell_row = int(cell.get("row", 0))
                cell_col = int(cell.get("col", 0))
                x = float(cell["x"])
                y = float(cell["y"])
            except (KeyError, TypeError, ValueError):
                continue
            storage_idx = (pmin_r + cell_row) * storage + (pmin_c + cell_col)
            remapped[storage_idx] = (x, y)
        return remapped or centers

    remapped = {}
    for idx, xy in centers.items():
        ui_row = idx // layout_cols
        ui_col = idx % layout_cols
        storage_idx = (pmin_r + ui_row) * storage + (pmin_c + ui_col)
        remapped[storage_idx] = xy
    return remapped


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
    *,
    slot_centers: dict[int, tuple[float, float]] | None = None,
) -> dict[int, tuple[float, float]] | None:
    if not isinstance(block, dict):
        return None
    slots = block.get("rack_slots")
    if not isinstance(slots, list) or not slots:
        return None
    centers = slot_centers or _parse_rack_slot_centers(block, run_state)
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


def _marker_margin_from_cell_centers(
    centers: dict[int, tuple[float, float]],
) -> int | None:
    """Margin so path circles (radius ~ pitch * 0.36) are not clipped at edges."""
    if len(centers) < 20:
        return None
    xs = [x for x, _ in centers.values()]
    ys = [y for _, y in centers.values()]
    span_w = max(xs) - min(xs)
    span_h = max(ys) - min(ys)
    if span_w < _MIN_CELL_SPAN or span_h < _MIN_CELL_SPAN:
        return None
    pitch = min(span_w, span_h) / 4.0
    return max(_BOARD_CELL_PADDING, int(math.ceil(pitch * _MARKER_MARGIN_FACTOR)))


def _board_region_from_cell_centers(
    centers: dict[int, tuple[float, float]],
    *,
    padding: int | None = None,
) -> Region | None:
    """Bounding box around exported tile centers (screen coordinates)."""
    if len(centers) < 20:
        return None
    margin = padding if padding is not None else _marker_margin_from_cell_centers(centers)
    if margin is None:
        return None
    xs = [x for x, _ in centers.values()]
    ys = [y for _, y in centers.values()]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    span_w = max_x - min_x
    span_h = max_y - min_y
    return Region(
        max(0, int(min_x) - margin),
        max(0, int(min_y) - margin),
        max(1, int(span_w) + 2 * margin),
        max(1, int(span_h) + 2 * margin),
    )


def _union_region(a: Region, b: Region) -> Region:
    """Smallest axis-aligned rect containing both regions."""
    if not a.is_valid():
        return b
    if not b.is_valid():
        return a
    left = min(a.x, b.x)
    top = min(a.y, b.y)
    right = max(a.x + a.width, b.x + b.width)
    bottom = max(a.y + a.height, b.y + b.height)
    return Region(left, top, max(1, right - left), max(1, bottom - top))


def _expand_board_region_for_markers(
    board: Region,
    cell_centers: dict[int, tuple[float, float]] | None,
) -> Region:
    """Ensure board overlay includes half-tile margin for numbered path circles."""
    if not board.is_valid() or not cell_centers or len(cell_centers) < 20:
        return board
    expanded = _board_region_from_cell_centers(cell_centers)
    if expanded is None:
        return board
    return _union_region(board, expanded)


def _sanitize_rack_slot_centers(
    centers: dict[int, tuple[float, float]],
    rack_block: Any,
) -> tuple[dict[int, tuple[float, float]], bool]:
    """Align rack slot Y to consumable_rack block when export drifts to another row."""
    if not centers:
        return centers, False
    original = dict(centers)
    rack_rect = _rect_from_block(rack_block)
    ys = [y for _, y in centers.values()]
    median_y = float(statistics.median(ys))
    corrected = False

    if rack_rect is not None and rack_rect.is_valid():
        rack_center_y = rack_rect.y + rack_rect.height / 2.0
        delta = rack_center_y - median_y
        if abs(delta) > _RACK_SLOT_Y_TOLERANCE:
            centers = {idx: (x, y + delta) for idx, (x, y) in centers.items()}
            median_y += delta
            corrected = True

    post_ys = [y for _, y in centers.values()]
    post_median = float(statistics.median(post_ys))
    filtered = {
        idx: (x, y)
        for idx, (x, y) in centers.items()
        if abs(y - post_median) <= _RACK_SLOT_Y_TOLERANCE
    }
    if len(filtered) >= 3:
        if len(filtered) != len(centers):
            corrected = True
        centers = filtered
    else:
        centers = original

    return centers, corrected


def _rack_slot_horizontal_span(centers: dict[int, tuple[float, float]]) -> float:
    if not centers:
        return 0.0
    xs = [x for x, _ in centers.values()]
    return max(xs) - min(xs)


def _rack_slot_y_aligned(centers: dict[int, tuple[float, float]], rack_block: Any) -> bool:
    rack_rect = _rect_from_block(rack_block)
    if rack_rect is None or not rack_rect.is_valid():
        return True
    median_y = float(statistics.median(y for _, y in centers.values()))
    rack_center_y = rack_rect.y + rack_rect.height / 2.0
    return abs(median_y - rack_center_y) <= _RACK_SLOT_Y_TOLERANCE


def _is_degenerate_rack_export(
    centers: dict[int, tuple[float, float]] | None,
    rack_block: Any,
) -> bool:
    if not centers or len(centers) < 2:
        return True
    if _rack_slot_horizontal_span(centers) < _MIN_RACK_SLOT_SPAN:
        return True
    rack_rect = _rect_from_block(rack_block)
    if rack_rect is not None and rack_rect.is_valid():
        slot_count = 0
        if isinstance(rack_block, dict):
            try:
                slot_count = int(rack_block.get("slot_count", 0))
            except (TypeError, ValueError):
                slot_count = 0
        if slot_count >= _RACK_SLOT_COUNT and rack_rect.width < _MIN_RACK_BLOCK_WIDTH:
            return True
    return False


def _is_valid_rack_layout(
    centers: dict[int, tuple[float, float]] | None,
    rack_block: Any,
) -> bool:
    if not centers or len(centers) < _RACK_SLOT_COUNT:
        return False
    if _is_degenerate_rack_export(centers, rack_block):
        return False
    if not _rack_slot_y_aligned(centers, rack_block):
        return False
    return _rack_slot_horizontal_span(centers) >= _MIN_RACK_SLOT_SPAN


def _synthesize_rack_slot_centers_from_block(
    rack_block: Any,
    *,
    slot_count: int = _RACK_SLOT_COUNT,
) -> dict[int, tuple[float, float]] | None:
    rack_rect = _rect_from_block(rack_block)
    if rack_rect is None or not rack_rect.is_valid():
        return None
    if rack_rect.width < _MIN_RACK_SLOT_SPAN:
        return None
    slot_w = float(rack_rect.width) / float(slot_count)
    center_y = rack_rect.y + rack_rect.height / 2.0
    return {
        i: (rack_rect.x + (i + 0.5) * slot_w, center_y) for i in range(slot_count)
    }


def _synthesize_rack_slot_centers_from_region(
    region: Region,
    *,
    slot_count: int = _RACK_SLOT_COUNT,
) -> dict[int, tuple[float, float]] | None:
    if not region.is_valid() or region.width < _MIN_RACK_SLOT_SPAN:
        return None
    slot_w = float(region.width) / float(slot_count)
    center_y = region.y + region.height / 2.0
    return {
        i: (region.x + (i + 0.5) * slot_w, center_y) for i in range(slot_count)
    }


def _rack_block_from_centers(
    centers: dict[int, tuple[float, float]],
    *,
    fallback: dict[str, Any] | None = None,
) -> dict[str, Any]:
    xs = [x for x, _ in centers.values()]
    ys = [y for _, y in centers.values()]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    block: dict[str, Any] = {
        "x": int(min_x) - _RACK_PADDING,
        "y": int(min_y) - _RACK_PADDING,
        "width": max(1, int(max_x - min_x) + 2 * _RACK_PADDING),
        "height": max(1, int(max_y - min_y) + 2 * _RACK_PADDING),
        "slot_count": len(centers),
        "rack_slots": [
            {
                "rack_index": idx,
                "x": int(round(x)),
                "y": int(round(y)),
                "width": 48,
                "height": 48,
            }
            for idx, (x, y) in sorted(centers.items())
        ],
    }
    if isinstance(fallback, dict):
        for key in ("slot_count",):
            if key in fallback:
                block[key] = fallback[key]
    return block


def _repair_degenerate_rack_layout(
    rack_block: Any,
    centers: dict[int, tuple[float, float]] | None,
    *,
    config: AppConfig | None = None,
) -> tuple[Any, dict[int, tuple[float, float]] | None, bool, bool]:
    """Recover collapsed rack exports via synthesis or manual calibration."""
    if not _is_degenerate_rack_export(centers, rack_block):
        return rack_block, centers, False, False

    if isinstance(rack_block, dict):
        synthesized = _synthesize_rack_slot_centers_from_block(rack_block)
        if synthesized is not None:
            return rack_block, synthesized, True, False

    if config is not None and config.rack_region.is_valid():
        manual_centers = _synthesize_rack_slot_centers_from_region(config.rack_region)
        if manual_centers is not None:
            manual_block = _rack_block_from_centers(manual_centers)
            return manual_block, manual_centers, True, False

    return rack_block, None, False, True


def _repair_board_region_from_cells(
    board: Region,
    cell_centers: dict[int, tuple[float, float]] | None,
) -> tuple[Region, bool]:
    """Replace degenerate melmod board rects using cell-center spread."""
    if not board.is_valid() or not cell_centers:
        return board, False
    repaired = _board_region_from_cell_centers(cell_centers)
    if repaired is None:
        return board, False
    suspicious = board.width < _MIN_BOARD_DIM or board.height < _MIN_BOARD_DIM
    if not suspicious:
        return board, False
    return repaired, True


def parse_ui_layout(
    run_state: dict[str, Any] | None,
    *,
    config: AppConfig | None = None,
) -> OverlayRegions | None:
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
    rack_slot_corrected = False
    rack_layout_collapsed = False

    rack_block, rack_slot_centers, collapsed_repaired, from_cache = (
        _repair_degenerate_rack_layout(
            rack_block, rack_slot_centers, config=config
        )
    )
    if collapsed_repaired:
        rack_slot_corrected = True
        rack_layout_collapsed = from_cache
    elif rack_slot_centers and isinstance(rack_block, dict):
        rack_slot_centers, y_corrected = _sanitize_rack_slot_centers(
            rack_slot_centers, rack_block
        )
        if y_corrected:
            rack_slot_corrected = True

    rack_slot_sizes = _parse_rack_slot_sizes(
        rack_block, run_state, slot_centers=rack_slot_centers
    )
    rack_tile_height = _rack_tile_height_from_block(rack_block)
    rack = _rect_from_block(rack_block) or Region()
    if rack_slot_centers:
        rack = _tight_rack_region(rack_slot_centers, rack)
    board_cell_centers = _parse_cell_centers(board_block)
    board_cell_centers = _remap_layout_cell_centers_to_storage(
        board_block, board_cell_centers, run_state
    )
    board, board_region_repaired = _repair_board_region_from_cells(
        board, board_cell_centers
    )
    board = _expand_board_region_for_markers(board, board_cell_centers)
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
        board_region_repaired=board_region_repaired,
        rack_slot_corrected=rack_slot_corrected,
        rack_layout_collapsed=rack_layout_collapsed,
    )


def cursedle_overlay_mode(run_state: dict[str, Any] | None) -> bool:
    """True when run_state is a Cursedle trial (no consumable rack)."""
    from cursed_words_solver.loadout import encounter_mode_from_run_state

    return encounter_mode_from_run_state(run_state) == "cursedle"


def _overlay_regions_without_rack(regions: OverlayRegions) -> OverlayRegions:
    return OverlayRegions(
        board=regions.board,
        rack=Region(),
        source=regions.source,
        board_cell_centers=regions.board_cell_centers,
        rack_slot_centers=None,
        rack_slot_sizes=None,
        rack_tile_height=None,
        board_region_repaired=regions.board_region_repaired,
        rack_slot_corrected=False,
        rack_layout_collapsed=False,
    )


def resolve_overlay_regions(
    run_state: dict[str, Any] | None,
    config: AppConfig,
) -> OverlayRegions:
    """Prefer melmod ui_layout; fall back to config.json manual regions."""
    parsed = parse_ui_layout(run_state, config=config)
    if parsed is not None:
        if cursedle_overlay_mode(run_state):
            return _overlay_regions_without_rack(parsed)
        return parsed
    regions = OverlayRegions(
        board=config.board_region,
        rack=config.rack_region,
        source="manual",
    )
    if cursedle_overlay_mode(run_state):
        return _overlay_regions_without_rack(regions)
    return regions


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
