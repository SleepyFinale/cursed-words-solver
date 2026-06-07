"""Static 5×5 topology bitboards and per-solve board graph context.

Precomputed at module load (indices 0–24, row-major):

- ``STANDARD_ADJACENCY`` / ``NEIGHBORS_8``: default 8-way letter movement
- ``STANDARD_ADJACENCY_WRAP`` / ``NEIGHBORS_8_WRAP``: same + Hungry Snake wrap
- ``KNIGHT_ADJACENCY`` / ``KNIGHT_TARGETS``: knight L-moves
- ``KING_STEP_MASK``: king one-step base (= ``NEIGHBORS_8``); legal king moves
  still require runtime capture/check filtering in ``chess_tiles``
- ``RAY_LINES`` / ``RAY_LINES_WRAP``: sliding rook/bishop/queen rays

Pawn, white-tile jumps, and Full Moon teleports are not static adjacency tables.
"""

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
    TileColor,
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
CURSE_CODE_FRACTION = _CURSE_TO_INT.get(CurseType.FRACTION, 0)
CURSE_CODE_NUMBER = _CURSE_TO_INT.get(CurseType.NUMBER, 0)

_COLOR_TO_CODE = {
    TileColor.COLORLESS: 0,
    TileColor.RED: 1,
    TileColor.BLUE: 2,
    TileColor.GREEN: 3,
    TileColor.GOLD: 4,
    TileColor.PURPLE: 5,
    TileColor.WHITE: 6,
}
RED_COLOR_CODE = 1


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

# Proposal-aligned aliases (same objects as the NEIGHBORS_* / KNIGHT_* tables).
STANDARD_ADJACENCY = NEIGHBORS_8
STANDARD_ADJACENCY_WRAP = NEIGHBORS_8_WRAP
KNIGHT_ADJACENCY = KNIGHT_TARGETS
KING_STEP_MASK = NEIGHBORS_8


def iter_mask(mask: int) -> Iterator[int]:
    while mask:
        bit = (mask & -mask).bit_length() - 1
        yield bit
        mask &= ~(1 << bit)


def lowest_bit_index(mask: int) -> int:
    return (mask & -mask).bit_length() - 1


def collect_mask_indices(mask: int, out: list[int]) -> int:
    """Fill ``out[0:n]`` with set-bit indices; return ``n``. Reuses ``out`` storage."""
    n = 0
    while mask:
        bit = (mask & -mask).bit_length() - 1
        out[n] = bit
        n += 1
        mask &= mask - 1
    return n


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
    wildcard_mask: int
    chess_curse: tuple[int, ...]
    chess_side_code: tuple[int, ...]
    has_chess_pieces: bool = False
    hanafuda_suit_mask: int = 0
    grid_base_score: int = 0
    coloured_tile_count: int = 0
    tile_base: tuple[float, ...] = field(default_factory=lambda: (0.0,) * CELL_COUNT)
    curse_code: tuple[int, ...] = field(default_factory=lambda: (0,) * CELL_COUNT)
    tile_color_code: tuple[int, ...] = field(default_factory=lambda: (0,) * CELL_COUNT)
    is_fraction: tuple[bool, ...] = field(default_factory=lambda: (False,) * CELL_COUNT)
    number_like: tuple[bool, ...] = field(default_factory=lambda: (False,) * CELL_COUNT)
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
    from cursed_words_solver.rules.base_scoring import tile_base_contribution
    from cursed_words_solver.rules.scoring_conditions import (
        NON_COLOUR_FOR_NUMBER_BONUS,
        _hanafuda_tile_has_suit,
    )

    active_mask = mask_from_active(board)
    chess_piece_mask = 0
    item_mask = 0
    wildcard_mask = 0
    chess_curse: list[int] = [0] * CELL_COUNT
    chess_side_code: list[int] = [0] * CELL_COUNT
    letter_masks: dict[str, int] = defaultdict(int)
    identical_chess: dict[tuple[str, str], int] = defaultdict(int)
    hanafuda_suit_mask = 0
    grid_base_score = 0
    coloured_tile_count = 0
    tile_base: list[float] = [0.0] * CELL_COUNT
    curse_code: list[int] = [0] * CELL_COUNT
    tile_color_code: list[int] = [0] * CELL_COUNT
    is_fraction: list[bool] = [False] * CELL_COUNT
    number_like: list[bool] = [False] * CELL_COUNT

    for idx in range(CELL_COUNT):
        if not board.is_active_index(idx):
            continue
        tile = board.get_by_index(idx)
        curse_code[idx] = _CURSE_TO_INT.get(tile.curse, 0)
        tile_color_code[idx] = _COLOR_TO_CODE.get(tile.color, 0)
        is_fraction[idx] = tile.curse == CurseType.FRACTION
        number_like[idx] = tile.curse in (CurseType.NUMBER, CurseType.FRACTION)
        if tile.curse == CurseType.ITEM:
            item_mask |= 1 << idx
        elif tile.curse == CurseType.WILDCARD:
            wildcard_mask |= 1 << idx
        else:
            tile_base[idx] = float(tile_base_contribution(tile, board.money))
        if _is_chess_piece(tile):
            chess_piece_mask |= 1 << idx
            chess_curse[idx] = curse_code[idx]
        if _chess_side_known(tile):
            chess_side_code[idx] = 1 if _chess_side(tile) == "black" else 2
        letter = _physical_letter(tile)
        if letter:
            letter_masks[letter] |= 1 << idx
        if _is_chess_piece(tile) and _chess_side_known(tile):
            key = (tile.curse.value, _chess_side(tile))
            identical_chess[key] |= 1 << idx
        if _hanafuda_tile_has_suit(tile):
            hanafuda_suit_mask |= 1 << idx
        grid_base_score += tile_base_contribution(tile, board.money)
        if tile.color not in NON_COLOUR_FOR_NUMBER_BONUS:
            coloured_tile_count += 1

    for idx in range(CELL_COUNT):
        if board.is_active_index(idx):
            continue
        row, col = divmod(idx, 5)
        tile = board.get(row, col)
        if tile is None:
            continue
        if _hanafuda_tile_has_suit(tile):
            hanafuda_suit_mask |= 1 << idx

    return BoardGraphContext(
        board=board,
        active_mask=active_mask,
        chess_piece_mask=chess_piece_mask,
        item_mask=item_mask,
        wildcard_mask=wildcard_mask,
        chess_curse=tuple(chess_curse),
        chess_side_code=tuple(chess_side_code),
        has_chess_pieces=bool(chess_piece_mask),
        hanafuda_suit_mask=hanafuda_suit_mask,
        grid_base_score=grid_base_score,
        coloured_tile_count=coloured_tile_count,
        tile_base=tuple(tile_base),
        curse_code=tuple(curse_code),
        tile_color_code=tuple(tile_color_code),
        is_fraction=tuple(is_fraction),
        number_like=tuple(number_like),
        letter_masks=dict(letter_masks),
        identical_chess_masks=dict(identical_chess),
    )
