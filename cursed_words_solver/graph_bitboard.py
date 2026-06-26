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
MAX_GRID_SIZE = 6

_ADJACENCY_CACHE: dict[tuple[int, int, bool, str], tuple[tuple[int, ...], ...]] = {}


def _adjacency_cache_key(
    rows: int, cols: int, *, horizontal_wrap: bool, kind: str
) -> tuple[int, int, bool, str]:
    return (rows, cols, horizontal_wrap, kind)


def _build_neighbors_8_for(rows: int, cols: int, *, horizontal_wrap: bool) -> tuple[int, ...]:
    key = _adjacency_cache_key(rows, cols, horizontal_wrap=horizontal_wrap, kind="n8")
    cached = _ADJACENCY_CACHE.get(key)
    if cached is not None:
        return cached  # type: ignore[return-value]
    out: list[int] = []
    for idx in range(rows * cols):
        row, col = divmod(idx, cols)
        mask = 0
        for dr, dc in DIRS_8:
            nr, nc = row + dr, col + dc
            if 0 <= nr < rows and 0 <= nc < cols:
                mask |= 1 << index_of_rows_cols(nr, nc, cols)
            elif horizontal_wrap and 0 <= nr < rows:
                wnc = (nc + cols) % cols
                mask |= 1 << index_of_rows_cols(nr, wnc, cols)
        out.append(mask)
    result = tuple(out)
    _ADJACENCY_CACHE[key] = result  # type: ignore[assignment]
    return result


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


def adjacency_for_board(
    board: Board, *, horizontal_wrap: bool = False
) -> tuple[int, ...]:
    rows, cols = board.storage_rows, board.storage_cols
    if rows == GRID_SIZE and cols == GRID_SIZE:
        return NEIGHBORS_8_WRAP if horizontal_wrap else NEIGHBORS_8
    return _build_neighbors_8_for(rows, cols, horizontal_wrap=horizontal_wrap)


def knight_adjacency_for_board(board: Board) -> tuple[int, ...]:
    rows, cols = board.storage_rows, board.storage_cols
    if rows == GRID_SIZE and cols == GRID_SIZE:
        return KNIGHT_TARGETS
    return _build_knight_targets_for(rows, cols)
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
    for i in range(board.cell_count):
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
    """Precomputed per-solve masks and tile metadata indexed by board cell."""

    board: Board
    cell_count: int
    neighbors_8: tuple[int, ...]
    neighbors_8_wrap: tuple[int, ...]
    knight_targets: tuple[int, ...]
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


def _build_piece_land_masks(
    step_masks: tuple[int, ...] | list[int],
    *,
    active_mask: int,
    chess_piece_mask: int,
    chess_side_code: tuple[int, ...],
    moving_side_code: int,
    allies_can_take: bool,
    cell_count: int,
) -> tuple[int, ...]:
    """Precompute landable targets per start cell for one moving side."""
    out: list[int] = []
    for start_idx in range(cell_count):
        land = 0
        for idx in iter_mask(step_masks[start_idx] & active_mask):
            if chess_piece_mask & (1 << idx):
                side_code = chess_side_code[idx]
                if side_code == 0:
                    continue
                if side_code == moving_side_code:
                    if allies_can_take:
                        land |= 1 << idx
                else:
                    land |= 1 << idx
            else:
                land |= 1 << idx
        out.append(land)
    return tuple(out)


def _build_chess_neighbor_masks(
    *,
    active_mask: int,
    chess_piece_mask: int,
    chess_side_code: tuple[int, ...],
    black_piece_mask: int,
    white_piece_mask: int,
    neighbors_8: tuple[int, ...],
    knight_targets: tuple[int, ...],
    neighbors_8_wrap: tuple[int, ...],
    cell_count: int,
) -> tuple[
    tuple[tuple[tuple[int, ...], ...], ...],
    tuple[tuple[tuple[int, ...], ...], ...],
    tuple[tuple[tuple[int, ...], ...], ...],
]:
    knight_tables: list[list[tuple[int, ...]]] = [[], []]
    king_tables: list[list[tuple[int, ...]]] = [[], []]
    king_wrap_tables: list[list[tuple[int, ...]]] = [[], []]
    for allies_i, allies in enumerate((False, True)):
        for side_code, _side_mask in ((1, black_piece_mask), (2, white_piece_mask)):
            knight_tables[allies_i].append(
                _build_piece_land_masks(
                    knight_targets,
                    active_mask=active_mask,
                    chess_piece_mask=chess_piece_mask,
                    chess_side_code=chess_side_code,
                    moving_side_code=side_code,
                    allies_can_take=allies,
                    cell_count=cell_count,
                )
            )
            king_tables[allies_i].append(
                _build_piece_land_masks(
                    neighbors_8,
                    active_mask=active_mask,
                    chess_piece_mask=chess_piece_mask,
                    chess_side_code=chess_side_code,
                    moving_side_code=side_code,
                    allies_can_take=allies,
                    cell_count=cell_count,
                )
            )
            king_wrap_tables[allies_i].append(
                _build_piece_land_masks(
                    neighbors_8_wrap,
                    active_mask=active_mask,
                    chess_piece_mask=chess_piece_mask,
                    chess_side_code=chess_side_code,
                    moving_side_code=side_code,
                    allies_can_take=allies,
                    cell_count=cell_count,
                )
            )
    return (
        (tuple(knight_tables[0]), tuple(knight_tables[1])),
        (tuple(king_tables[0]), tuple(king_tables[1])),
        (tuple(king_wrap_tables[0]), tuple(king_wrap_tables[1])),
    )


def build_board_graph_context(board: Board) -> BoardGraphContext:
    from cursed_words_solver.rules.base_scoring import tile_base_contribution
    from cursed_words_solver.rules.scoring_conditions import (
        NON_COLOUR_FOR_NUMBER_BONUS,
        _hanafuda_tile_has_suit,
    )

    active_mask = mask_from_active(board)
    cell_count = board.cell_count
    neighbors_8 = adjacency_for_board(board, horizontal_wrap=False)
    neighbors_8_wrap = adjacency_for_board(board, horizontal_wrap=True)
    knight_targets = knight_adjacency_for_board(board)
    chess_piece_mask = 0
    black_piece_mask = 0
    white_piece_mask = 0
    item_mask = 0
    wildcard_mask = 0
    item_tile_base = [0.0] * cell_count
    chess_curse: list[int] = [0] * cell_count
    chess_side_code: list[int] = [0] * cell_count
    letter_masks: dict[str, int] = defaultdict(int)
    identical_chess: dict[tuple[str, str], int] = defaultdict(int)
    hanafuda_suit_mask = 0
    grid_base_score = 0
    coloured_tile_count = 0
    tile_base: list[float] = [0.0] * cell_count
    curse_code: list[int] = [0] * cell_count
    tile_color_code: list[int] = [0] * cell_count
    is_fraction: list[bool] = [False] * cell_count
    number_like: list[bool] = [False] * cell_count

    for idx in range(cell_count):
        if not board.is_active_index(idx):
            continue
        tile = board.get_by_index(idx)
        curse_code[idx] = _CURSE_TO_INT.get(tile.curse, 0)
        tile_color_code[idx] = _COLOR_TO_CODE.get(tile.color, 0)
        is_fraction[idx] = tile.curse == CurseType.FRACTION
        number_like[idx] = tile.curse in (CurseType.NUMBER, CurseType.FRACTION)
        if tile.curse == CurseType.ITEM:
            item_mask |= 1 << idx
            item_tile_base[idx] = float(tile_base_contribution(tile, board.money))
        elif tile.curse == CurseType.WILDCARD:
            wildcard_mask |= 1 << idx
        else:
            tile_base[idx] = float(tile_base_contribution(tile, board.money))
        if _is_chess_piece(tile):
            chess_piece_mask |= 1 << idx
            chess_curse[idx] = curse_code[idx]
        if _chess_side_known(tile):
            if _chess_side(tile) == "black":
                chess_side_code[idx] = 1
                if _is_chess_piece(tile):
                    black_piece_mask |= 1 << idx
            else:
                chess_side_code[idx] = 2
                if _is_chess_piece(tile):
                    white_piece_mask |= 1 << idx
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

    for idx in range(cell_count):
        if board.is_active_index(idx):
            continue
        row, col = board.coords_at(idx)
        tile = board.get(row, col)
        if tile is None:
            continue
        if _hanafuda_tile_has_suit(tile):
            hanafuda_suit_mask |= 1 << idx

    chess_side_tuple = tuple(chess_side_code)
    knight_land_mask, king_step_mask, king_step_mask_wrap = _build_chess_neighbor_masks(
        active_mask=active_mask,
        chess_piece_mask=chess_piece_mask,
        chess_side_code=chess_side_tuple,
        black_piece_mask=black_piece_mask,
        white_piece_mask=white_piece_mask,
        neighbors_8=neighbors_8,
        knight_targets=knight_targets,
        neighbors_8_wrap=neighbors_8_wrap,
        cell_count=cell_count,
    )

    from cursed_words_solver.arrow_tiles import build_arrow_target_masks

    arrow_mask, arrow_target_masks, arrow_target_masks_wrap = build_arrow_target_masks(
        board, active_mask
    )

    return BoardGraphContext(
        board=board,
        cell_count=cell_count,
        neighbors_8=neighbors_8,
        neighbors_8_wrap=neighbors_8_wrap,
        knight_targets=knight_targets,
        active_mask=active_mask,
        chess_piece_mask=chess_piece_mask,
        item_mask=item_mask,
        wildcard_mask=wildcard_mask,
        item_tile_base=tuple(item_tile_base),
        chess_curse=tuple(chess_curse),
        chess_side_code=chess_side_tuple,
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
        black_piece_mask=black_piece_mask,
        white_piece_mask=white_piece_mask,
        knight_land_mask=knight_land_mask,
        king_step_mask=king_step_mask,
        king_step_mask_wrap=king_step_mask_wrap,
        arrow_mask=arrow_mask,
        arrow_target_masks=arrow_target_masks,
        arrow_target_masks_wrap=arrow_target_masks_wrap,
    )
