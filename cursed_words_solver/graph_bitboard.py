"""Static 5×5 topology bitboards and per-solve board graph context."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterator

from cursed_words_solver.models import (
    CHESS_CURSES,
    CURRENCY_MAP,
    Board,
    CurseType,
    Tile,
    normalize_tile_glyph,
)

GRID_SIZE = 5
CELL_COUNT = 25
DIR_COUNT = 8

DIRS_8 = [
    (-1, -1), (-1, 0), (-1, 1),
    (0, -1),           (0, 1),
    (1, -1),  (1, 0),  (1, 1),
]

KNIGHT_DIRS = [
    (-2, -1), (-2, 1), (-1, -2), (-1, 2),
    (1, -2), (1, 2), (2, -1), (2, 1),
]

# Indices into DIRS_8 / RAY_LINES direction slots
STRAIGHT_DIR_INDICES = (1, 3, 4, 6)
DIAG_DIR_INDICES = (0, 2, 5, 7)

_CURSE_TO_INT = {c: i + 1 for i, c in enumerate(CurseType)}


def index_of(row: int, col: int) -> int:
    return row * GRID_SIZE + col


def _wrap_partner_col(col: int) -> int | None:
    if col == 0:
        return 4
    if col == 4:
        return 0
    return None


def _ray_step(
    row: int,
    col: int,
    dr: int,
    dc: int,
    *,
    horizontal_wrap: bool,
) -> tuple[int, int] | None:
    nr, nc = row + dr, col + dc
    if 0 <= nr < GRID_SIZE and 0 <= nc < GRID_SIZE:
        return nr, nc
    if not horizontal_wrap or not (0 <= nr < GRID_SIZE):
        return None
    if col == 4 and dc > 0:
        return nr, 0
    if col == 0 and dc < 0:
        return nr, 4
    return None


def _build_neighbors_8(*, horizontal_wrap: bool) -> list[int]:
    out: list[int] = []
    for idx in range(CELL_COUNT):
        row, col = divmod(idx, GRID_SIZE)
        mask = 0
        for dr, dc in DIRS_8:
            nr, nc = row + dr, col + dc
            if 0 <= nr < GRID_SIZE and 0 <= nc < GRID_SIZE:
                mask |= 1 << index_of(nr, nc)
        if horizontal_wrap:
            partner = _wrap_partner_col(col)
            if partner is not None:
                mask |= 1 << index_of(row, partner)
        out.append(mask)
    return out


def _build_knight_targets() -> list[int]:
    out: list[int] = []
    for idx in range(CELL_COUNT):
        row, col = divmod(idx, GRID_SIZE)
        mask = 0
        for dr, dc in KNIGHT_DIRS:
            nr, nc = row + dr, col + dc
            if 0 <= nr < GRID_SIZE and 0 <= nc < GRID_SIZE:
                mask |= 1 << index_of(nr, nc)
        out.append(mask)
    return out


def _build_ray_lines(*, horizontal_wrap: bool) -> tuple[tuple[tuple[int, ...], ...], ...]:
    lines: list[tuple[tuple[int, ...], ...]] = []
    for idx in range(CELL_COUNT):
        row, col = divmod(idx, GRID_SIZE)
        cell_lines: list[tuple[int, ...]] = []
        for dr, dc in DIRS_8:
            line: list[int] = []
            r, c = row, col
            seen: set[tuple[int, int]] = set()
            while True:
                nxt = _ray_step(r, c, dr, dc, horizontal_wrap=horizontal_wrap)
                if nxt is None or nxt in seen:
                    break
                seen.add(nxt)
                nr, nc = nxt
                line.append(index_of(nr, nc))
                r, c = nr, nc
            cell_lines.append(tuple(line))
        lines.append(tuple(cell_lines))
    return tuple(lines)


def _build_static_tables() -> tuple[list[int], list[int], list[int], tuple, tuple]:
    return (
        _build_neighbors_8(horizontal_wrap=False),
        _build_neighbors_8(horizontal_wrap=True),
        _build_knight_targets(),
        _build_ray_lines(horizontal_wrap=False),
        _build_ray_lines(horizontal_wrap=True),
    )


(
    NEIGHBORS_8,
    NEIGHBORS_8_WRAP,
    KNIGHT_TARGETS,
    RAY_LINES,
    RAY_LINES_WRAP,
) = _build_static_tables()


def iter_mask(mask: int) -> Iterator[int]:
    while mask:
        bit = (mask & -mask).bit_length() - 1
        yield bit
        mask &= ~(1 << bit)


def lowest_bit_index(mask: int) -> int:
    return (mask & -mask).bit_length() - 1


def mask_from_indices(indices: list[int] | tuple[int, ...]) -> int:
    m = 0
    for idx in indices:
        m |= 1 << idx
    return m


def mask_from_active(board: Board) -> int:
    m = 0
    for i in range(CELL_COUNT):
        if board.is_active_index(i):
            m |= 1 << i
    return m


def get_valid_extensions(candidates_mask: int, visited_mask: int) -> int:
    return candidates_mask & ~visited_mask


def _is_chess_piece(tile: Tile) -> bool:
    return tile.curse in CHESS_CURSES


def _chess_side(tile: Tile) -> str:
    side = str(tile.metadata.get("chess_color", "") or "").lower()
    if side in ("black", "white"):
        return side
    return ""


def _chess_side_known(tile: Tile) -> bool:
    return _chess_side(tile) in ("black", "white")


def _physical_letter(tile: Tile) -> str:
    if _is_chess_piece(tile):
        return ""
    if tile.curse in (CurseType.WILDCARD, CurseType.FRACTION):
        return ""
    glyph = normalize_tile_glyph(tile.char or "")
    if tile.curse == CurseType.CURRENCY:
        return glyph if glyph in CURRENCY_MAP else ""
    if len(glyph) == 1 and glyph.isalpha():
        return glyph.upper()
    return ""


@dataclass(frozen=True)
class BoardGraphContext:
    """Precomputed per-solve masks and tile metadata indexed 0–24."""

    board: Board
    active_mask: int
    chess_piece_mask: int
    item_mask: int
    chess_curse: tuple[int, ...]
    chess_side_code: tuple[int, ...]
    letter_masks: dict[str, int] = field(default_factory=dict)
    identical_chess_masks: dict[tuple[str, str], int] = field(default_factory=dict)

    def is_active(self, idx: int) -> bool:
        return bool(self.active_mask & (1 << idx))

    def is_chess_piece_at(self, idx: int) -> bool:
        return bool(self.chess_piece_mask & (1 << idx))

    def chess_side_at(self, idx: int) -> str:
        code = self.chess_side_code[idx]
        if code == 1:
            return "black"
        if code == 2:
            return "white"
        return ""


def build_board_graph_context(board: Board) -> BoardGraphContext:
    active_mask = mask_from_active(board)
    chess_piece_mask = 0
    item_mask = 0
    chess_curse: list[int] = [0] * CELL_COUNT
    chess_side_code: list[int] = [0] * CELL_COUNT
    letter_masks: dict[str, int] = defaultdict(int)
    identical_chess: dict[tuple[str, str], int] = defaultdict(int)

    for idx in range(CELL_COUNT):
        if not board.is_active_index(idx):
            continue
        tile = board.get_by_index(idx)
        if tile.curse == CurseType.ITEM:
            item_mask |= 1 << idx
        if _is_chess_piece(tile):
            chess_piece_mask |= 1 << idx
            chess_curse[idx] = _CURSE_TO_INT.get(tile.curse, 0)
        if _chess_side_known(tile):
            chess_side_code[idx] = 1 if _chess_side(tile) == "black" else 2
        letter = _physical_letter(tile)
        if letter:
            letter_masks[letter] |= 1 << idx
        if _is_chess_piece(tile) and _chess_side_known(tile):
            key = (tile.curse.value, _chess_side(tile))
            identical_chess[key] |= 1 << idx

    return BoardGraphContext(
        board=board,
        active_mask=active_mask,
        chess_piece_mask=chess_piece_mask,
        item_mask=item_mask,
        chess_curse=tuple(chess_curse),
        chess_side_code=tuple(chess_side_code),
        letter_masks=dict(letter_masks),
        identical_chess_masks=dict(identical_chess),
    )
