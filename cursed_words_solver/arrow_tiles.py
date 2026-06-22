"""Arrow tile movement (decompiled from game ``Arrows``)."""

from __future__ import annotations

from cursed_words_solver.graph_bitboard import GRID_SIZE, index_of
from cursed_words_solver.models import CurseType, Tile, normalize_tile_glyph

# Game ``Arrows.ArrowDirections``: Vector2Int(x, y) with x=col, y=row.
ARROW_GLYPH_TO_DELTA: dict[str, tuple[int, int]] = {
    "↑": (0, 1),
    "→": (1, 0),
    "↓": (0, -1),
    "←": (-1, 0),
    "↖": (-1, 1),
    "↗": (1, 1),
    "↘": (1, -1),
    "↙": (-1, -1),
}

ARROW_GLYPHS = frozenset(ARROW_GLYPH_TO_DELTA)


def arrow_glyph_from_tile(tile: Tile) -> str | None:
    """Return arrow direction glyph from tile face, if any."""
    if tile.curse != CurseType.ARROW:
        return None
    for raw in (tile.char, tile.letter):
        glyph = normalize_tile_glyph(raw or "")
        if glyph in ARROW_GLYPHS:
            return glyph
        if raw in ARROW_GLYPHS:
            return raw
    return None


def arrow_direction_delta(tile: Tile) -> tuple[int, int] | None:
    """(col_delta, row_delta) for an arrow tile, or None."""
    glyph = arrow_glyph_from_tile(tile)
    if glyph is None:
        return None
    return ARROW_GLYPH_TO_DELTA[glyph]


def arrow_ray_target_mask(
    start_idx: int,
    direction: tuple[int, int],
    active_mask: int,
    *,
    rows: int,
    cols: int,
    horizontal_wrap: bool,
) -> int:
    """All active cells along the arrow ray from ``start_idx`` (exclusive)."""
    row, col = divmod(start_idx, cols)
    dc, dr = direction
    cc, cr = col + dc, row + dr
    mask = 0
    max_steps = max(rows, cols)
    for _ in range(max_steps):
        hit = False
        if 0 <= cc < cols and 0 <= cr < rows:
            idx = cr * cols + cc
            if active_mask & (1 << idx):
                mask |= 1 << idx
                hit = True
        if not hit and horizontal_wrap and 0 <= cr < rows:
            wcc = (cc + cols) % cols
            widx = cr * cols + wcc
            if active_mask & (1 << widx):
                mask |= 1 << widx
        if cr < 0 or cr >= rows:
            break
        cc += dc
        cr += dr
    return mask


def build_arrow_target_masks(
    board,
    active_mask: int,
) -> tuple[int, tuple[int, ...], tuple[int, ...]]:
    """``arrow_mask``, per-cell ray targets, per-cell ray targets with hungry-snake wrap."""
    cols = board.storage_cols
    rows = board.storage_rows
    cell_count = board.cell_count
    arrow_mask = 0
    base: list[int] = [0] * cell_count
    wrap: list[int] = [0] * cell_count
    for idx in range(cell_count):
        if not (active_mask & (1 << idx)):
            continue
        tile = board.get_by_index(idx)
        if tile.curse != CurseType.ARROW:
            continue
        delta = arrow_direction_delta(tile)
        if delta is None:
            continue
        arrow_mask |= 1 << idx
        base[idx] = arrow_ray_target_mask(
            idx, delta, active_mask, rows=rows, cols=cols, horizontal_wrap=False
        )
        wrap[idx] = arrow_ray_target_mask(
            idx, delta, active_mask, rows=rows, cols=cols, horizontal_wrap=True
        )
    return arrow_mask, tuple(base), tuple(wrap)
