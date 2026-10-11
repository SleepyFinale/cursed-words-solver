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

from dataclasses import dataclass, field
from typing import Iterator

from cursed_words_solver.models import (
    Board,
    CurseType,
    TileColor,
)

GRID_SIZE = 5
CELL_COUNT = 25
MAX_GRID_SIZE = 6

_ADJACENCY_CACHE: dict[tuple[int, int, bool, str], tuple[tuple[int, ...], ...]] = {}
_RAY_LINES_CACHE: dict[
    tuple[int, int, bool], tuple[tuple[tuple[int, ...], ...], ...]
] = {}


def _adjacency_cache_key(
    rows: int, cols: int, *, horizontal_wrap: bool, kind: str
) -> tuple[int, int, bool, str]:
    return (rows, cols, horizontal_wrap, kind)


def _knight_step(
    row: int,
    col: int,
    dr: int,
    dc: int,
    *,
    rows: int,
    cols: int,
    horizontal_wrap: bool,
) -> tuple[int, int] | None:
    """One knight L-step; Hungry Snake wraps columns with modulo (game: x % width)."""
    nr, nc = row + dr, col + dc
    if not (0 <= nr < rows):
        return None
    if 0 <= nc < cols:
        return nr, nc
    if horizontal_wrap:
        return nr, (nc + cols) % cols
    return None


def _build_knight_targets_for(
    rows: int, cols: int, *, horizontal_wrap: bool = False
) -> tuple[int, ...]:
    key = _adjacency_cache_key(rows, cols, horizontal_wrap=horizontal_wrap, kind="knight")
    cached = _ADJACENCY_CACHE.get(key)
    if cached is not None:
        return cached  # type: ignore[return-value]
    out: list[int] = []
    for idx in range(rows * cols):
        row, col = divmod(idx, cols)
        mask = 0
        for dr, dc in KNIGHT_DIRS:
            nxt = _knight_step(
                row, col, dr, dc, rows=rows, cols=cols, horizontal_wrap=horizontal_wrap
            )
            if nxt is not None:
                nr, nc = nxt
                mask |= 1 << index_of_rows_cols(nr, nc, cols)
        out.append(mask)
    result = tuple(out)
    _ADJACENCY_CACHE[key] = result  # type: ignore[assignment]
    return result


def index_of_rows_cols(row: int, col: int, cols: int) -> int:
    return row * cols + col


def ray_lines_for_board(
    board: Board, *, horizontal_wrap: bool = False
) -> tuple[tuple[tuple[int, ...], ...], ...]:
    """Sliding-piece ray lines for ``board`` dimensions (rook/bishop/queen)."""
    rows, cols = board.storage_rows, board.storage_cols
    if rows == GRID_SIZE and cols == GRID_SIZE:
        return RAY_LINES_WRAP if horizontal_wrap else RAY_LINES
    return _build_ray_lines_for(rows, cols, horizontal_wrap=horizontal_wrap)


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


def _ray_step(
    row: int,
    col: int,
    dr: int,
    dc: int,
    *,
    horizontal_wrap: bool,
    rows: int = GRID_SIZE,
    cols: int = GRID_SIZE,
) -> tuple[int, int] | None:
    nr, nc = row + dr, col + dc
    if 0 <= nr < rows and 0 <= nc < cols:
        return nr, nc
    if not horizontal_wrap or not (0 <= nr < rows):
        return None
    last_col = cols - 1
    if col == last_col and dc > 0:
        return nr, 0
    if col == 0 and dc < 0:
        return nr, last_col
    return None


def _build_ray_lines_for(
    rows: int, cols: int, *, horizontal_wrap: bool
) -> tuple[tuple[tuple[int, ...], ...], ...]:
    key = (rows, cols, horizontal_wrap)
    cached = _RAY_LINES_CACHE.get(key)
    if cached is not None:
        return cached
    lines: list[tuple[tuple[int, ...], ...]] = []
    for idx in range(rows * cols):
        row, col = divmod(idx, cols)
        cell_lines: list[tuple[int, ...]] = []
        for dr, dc in DIRS_8:
            line: list[int] = []
            r, c = row, col
            seen: set[tuple[int, int]] = set()
            while True:
                nxt = _ray_step(
                    r,
                    c,
                    dr,
                    dc,
                    horizontal_wrap=horizontal_wrap,
                    rows=rows,
                    cols=cols,
                )
                if nxt is None or nxt in seen:
                    break
                seen.add(nxt)
                nr, nc = nxt
                line.append(index_of_rows_cols(nr, nc, cols))
                r, c = nr, nc
            cell_lines.append(tuple(line))
        lines.append(tuple(cell_lines))
    result = tuple(lines)
    _RAY_LINES_CACHE[key] = result
    return result


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
            if col == 0:
                for dr in (-1, 0, 1):
                    nr = row + dr
                    if 0 <= nr < GRID_SIZE:
                        mask |= 1 << index_of(nr, 4)
            elif col == 4:
                for dr in (-1, 0, 1):
                    nr = row + dr
                    if 0 <= nr < GRID_SIZE:
                        mask |= 1 << index_of(nr, 0)
        out.append(mask)
    return out


def _build_knight_targets() -> list[int]:
    return list(_build_knight_targets_for(GRID_SIZE, GRID_SIZE, horizontal_wrap=False))


def _build_knight_targets_wrap() -> list[int]:
    return list(_build_knight_targets_for(GRID_SIZE, GRID_SIZE, horizontal_wrap=True))


def _build_ray_lines(*, horizontal_wrap: bool) -> tuple[tuple[tuple[int, ...], ...], ...]:
    return _build_ray_lines_for(
        GRID_SIZE, GRID_SIZE, horizontal_wrap=horizontal_wrap
    )


def _build_static_tables() -> tuple[list[int], list[int], list[int], list[int], tuple, tuple]:
    return (
        _build_neighbors_8(horizontal_wrap=False),
        _build_neighbors_8(horizontal_wrap=True),
        _build_knight_targets(),
        _build_knight_targets_wrap(),
        _build_ray_lines(horizontal_wrap=False),
        _build_ray_lines(horizontal_wrap=True),
    )


(
    NEIGHBORS_8,
    NEIGHBORS_8_WRAP,
    KNIGHT_TARGETS,
    KNIGHT_TARGETS_WRAP,
    RAY_LINES,
    RAY_LINES_WRAP,
) = _build_static_tables()

# Proposal-aligned aliases (same objects as the NEIGHBORS_* / KNIGHT_* tables).
STANDARD_ADJACENCY = NEIGHBORS_8
STANDARD_ADJACENCY_WRAP = NEIGHBORS_8_WRAP
KNIGHT_ADJACENCY = KNIGHT_TARGETS
KING_STEP_MASK = NEIGHBORS_8


def knight_targets_for_cell(
    cell_id: int,
    *,
    rows: int = GRID_SIZE,
    cols: int = GRID_SIZE,
    horizontal_wrap: bool = False,
) -> int:
    """Knight L-move destinations from cell_id (bitmask)."""
    if rows == GRID_SIZE and cols == GRID_SIZE:
        table = KNIGHT_TARGETS_WRAP if horizontal_wrap else KNIGHT_TARGETS
        return table[cell_id]
    table = _build_knight_targets_for(rows, cols, horizontal_wrap=horizontal_wrap)
    return table[cell_id]


def iter_mask(mask: int) -> Iterator[int]:
    while mask:
        bit = (mask & -mask).bit_length() - 1
        yield bit
        mask &= ~(1 << bit)


def mask_from_indices(indices: list[int] | tuple[int, ...]) -> int:
    m = 0
    for idx in indices:
        m |= 1 << idx
    return m


def get_valid_extensions(candidates_mask: int, visited_mask: int) -> int:
    return candidates_mask & ~visited_mask


@dataclass(frozen=True)
class BoardGraphContext:
    """Precomputed per-solve masks and tile metadata indexed by board cell."""

    board: Board
    cell_count: int
    neighbors_8: tuple[int, ...]
    neighbors_8_wrap: tuple[int, ...]
    knight_targets: tuple[int, ...]
    ray_lines: tuple[tuple[tuple[int, ...], ...], ...]
    ray_lines_wrap: tuple[tuple[tuple[int, ...], ...], ...]
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
    item_tile_base: tuple[float, ...] = field(
        default_factory=lambda: (0.0,) * CELL_COUNT
    )
    curse_code: tuple[int, ...] = field(default_factory=lambda: (0,) * CELL_COUNT)
    tile_color_code: tuple[int, ...] = field(default_factory=lambda: (0,) * CELL_COUNT)
    is_fraction: tuple[bool, ...] = field(default_factory=lambda: (False,) * CELL_COUNT)
    number_like: tuple[bool, ...] = field(default_factory=lambda: (False,) * CELL_COUNT)
    letter_masks: dict[str, int] = field(default_factory=dict)
    full_moon_masks: dict[str, int] = field(default_factory=dict)
    identical_chess_masks: dict[tuple[str, str], int] = field(default_factory=dict)
    black_piece_mask: int = 0
    white_piece_mask: int = 0
    # [allies_can_take][side 0=black 1=white][start_cell]
    knight_land_mask: tuple[tuple[tuple[int, ...], ...], ...] = field(
        default_factory=lambda: (((), ()), ((), ()))
    )
    king_step_mask: tuple[tuple[tuple[int, ...], ...], ...] = field(
        default_factory=lambda: (((), ()), ((), ()))
    )
    king_step_mask_wrap: tuple[tuple[tuple[int, ...], ...], ...] = field(
        default_factory=lambda: (((), ()), ((), ()))
    )
    arrow_mask: int = 0
    arrow_target_masks: tuple[int, ...] = field(
        default_factory=lambda: (0,) * CELL_COUNT
    )
    arrow_target_masks_wrap: tuple[int, ...] = field(
        default_factory=lambda: (0,) * CELL_COUNT
    )

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

    def _side_index(self, moving_side: str) -> int:
        return 0 if moving_side == "black" else 1

    def knight_land_for(
        self, start_idx: int, moving_side: str, *, allies_can_take: bool
    ) -> int:
        allies_i = 1 if allies_can_take else 0
        return self.knight_land_mask[allies_i][self._side_index(moving_side)][start_idx]

    def king_step_for(
        self,
        start_idx: int,
        moving_side: str,
        *,
        allies_can_take: bool,
        horizontal_wrap: bool,
    ) -> int:
        allies_i = 1 if allies_can_take else 0
        table = self.king_step_mask_wrap if horizontal_wrap else self.king_step_mask
        return table[allies_i][self._side_index(moving_side)][start_idx]


