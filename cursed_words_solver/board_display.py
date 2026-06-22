"""ASCII board formatting for console and debug output."""

from __future__ import annotations

from cursed_words_solver.models import (
    CURRENCY_MAP,
    Board,
    CurseType,
    Tile,
    normalize_tile_glyph,
)
from cursed_words_solver.rules.fraction_tiles import format_fraction_tile


def _format_tile_char(tile: Tile) -> str:
    if tile.curse == CurseType.FRACTION:
        return format_fraction_tile(tile)
    if tile.curse == CurseType.NUMBER:
        face = (tile.letter or tile.char or "").strip()
        if face.isdigit():
            return face
    if tile.curse == CurseType.CURRENCY:
        sym = normalize_tile_glyph(tile.char or tile.letter or "")
        if sym in CURRENCY_MAP:
            return sym
        if tile.letter and len(tile.letter) == 1:
            return tile.letter.upper()
    ch = normalize_tile_glyph(tile.char if tile.char and tile.char != "?" else tile.letter)
    if not ch or ch == "?":
        return "?"
    if len(ch) == 1:
        return ch.upper()
    return ch[:1].upper()


def _active_cell_bounds(board: Board) -> tuple[int, int, int, int] | None:
    """Return (min_row, max_row, min_col, max_col) for active cells, or None."""
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


def format_playable_size(board: Board) -> str:
    """Game convention: width×height (cols×rows), e.g. 4×3 for four wide, three tall."""
    bounds = _active_cell_bounds(board)
    if bounds is not None:
        min_r, max_r, min_c, max_c = bounds
        width = max_c - min_c + 1
        height = max_r - min_r + 1
    else:
        width, height = board.cols, board.rows
    return f"{width}×{height}"


def format_board_grid(board: Board, *, compact: bool = False) -> str:
    """ASCII grid of tile chars.

    When *compact* is True and the board is smaller than 5×5, crop to the
    active-cell bounding box and prefix with playable dimensions.
    """
    use_compact = compact and (board.rows < 5 or board.cols < 5)
    bounds = _active_cell_bounds(board) if use_compact else None

    if bounds is not None:
        min_r, max_r, min_c, max_c = bounds
        lines = []
        for r in range(min_r, max_r + 1):
            cells = [
                _format_tile_char(board.tiles[r][c])
                for c in range(min_c, max_c + 1)
            ]
            lines.append(" ".join(cells))
        header = f"Playable {format_playable_size(board)}:"
        return header + "\n" + "\n".join(lines)

    lines = []
    for row in board.tiles:
        cells = []
        for t in row:
            if not board.is_active_cell(t.row, t.col):
                cells.append(".")
            else:
                cells.append(_format_tile_char(t))
        lines.append(" ".join(cells))
    return "\n".join(lines)
