"""Chess piece movement and attack rules (wiki: Curses — Chess pieces)."""

from __future__ import annotations

from collections import OrderedDict

from cursed_words_solver.fingerprints import board_fingerprint
from cursed_words_solver.graph_bitboard import (
    DIAG_DIR_INDICES,
    BoardGraphContext,
    KNIGHT_TARGETS,
    NEIGHBORS_8,
    NEIGHBORS_8_WRAP,
    STRAIGHT_DIR_INDICES,
    get_valid_extensions,
    iter_mask,
    knight_targets_for_cell,
    mask_from_indices,
)
from cursed_words_solver.models import (
    CHESS_CURSES,
    Board,
    CurseType,
    Loadout,
    Tile,
)
from cursed_words_solver.rules.stamp_behaviors import (
    FLAG_CHESS_ALLIES_CAN_TAKE,
    FLAG_CHESS_KING_QUEEN_ITEM_MOVEMENT,
    FLAG_HORIZONTAL_WRAP,
    SearchFlagsMask,
    coerce_search_flags,
    flag_set,
    flag_test,
)

DIRS_8 = [
    (-1, -1), (-1, 0), (-1, 1),
    (0, -1),           (0, 1),
    (1, -1),  (1, 0),  (1, 1),
]

KNIGHT_DIRS = [
    (-2, -1), (-2, 1), (-1, -2), (-1, 2),
    (1, -2), (1, 2), (2, -1), (2, 1),
]

STRAIGHT_DIRS = [(-1, 0), (1, 0), (0, -1), (0, 1)]
DIAG_DIRS = [(-1, -1), (-1, 1), (1, -1), (1, 1)]

EN_PASSANT_BLACK_RANK = 1
EN_PASSANT_WHITE_RANK = 3

_ATTACK_CACHE_MAX = 8192
_attack_cache: OrderedDict[tuple, bool] = OrderedDict()
_attack_cache_hits = 0
_attack_cache_misses = 0
_board_has_chess_pieces: bool = True
_solve_board_fingerprint: str | None = None


def chess_attack_cache_stats() -> tuple[int, int]:
    return _attack_cache_hits, _attack_cache_misses


def reset_chess_attack_cache_stats() -> None:
    global _attack_cache_hits, _attack_cache_misses
    _attack_cache_hits = 0
    _attack_cache_misses = 0


def _visited_cache_key(visited: int | set[int]) -> int | frozenset[int]:
    if isinstance(visited, set):
        return frozenset(visited)
    return visited


def solve_has_chess_pieces() -> bool:
    """Whether the current solve board has chess tiles (set via clear_chess_attack_cache)."""
    return _board_has_chess_pieces


def clear_chess_attack_cache(
    *,
    has_chess_pieces: bool = True,
    board_fingerprint: str | None = None,
) -> None:
    """Clear attack lookup cache (call at start of each solve)."""
    global _board_has_chess_pieces, _solve_board_fingerprint
    _attack_cache.clear()
    reset_chess_attack_cache_stats()
    _board_has_chess_pieces = has_chess_pieces
    _solve_board_fingerprint = board_fingerprint


def index_of(row: int, col: int) -> int:
    return row * 5 + col


def _wrap_partner_col(col: int) -> int | None:
    """Hungry Snake: col 0 and col 4 on the same row are adjacent."""
    if col == 0:
        return 4
    if col == 4:
        return 0
    return None


def _wrap_col_distance(c1: int, c2: int) -> int:
    """Column separation with horizontal wrap (5-wide grid)."""
    d = abs(c1 - c2)
    return min(d, 5 - d)


def _attack_origins(
    row: int,
    col: int,
    *,
    horizontal_wrap: bool,
) -> list[tuple[int, int]]:
    origins = [(row, col)]
    if horizontal_wrap:
        partner = _wrap_partner_col(col)
        if partner is not None:
            origins.append((row, partner))
    return origins


def _visited_has(visited: int | set[int], idx: int) -> bool:
    if isinstance(visited, set):
        return idx in visited
    return bool(visited & (1 << idx))


def _active_indices(board: Board) -> list[int]:
    return [i for i in range(25) if board.is_active_index(i)]


def chess_side_known(tile: Tile) -> bool:
    side = str(tile.metadata.get("chess_color", "") or "").lower()
    return side in ("black", "white")


def chess_side(tile: Tile) -> str:
    """Black = filled piece, white = outlined (wiki traditional names)."""
    side = str(tile.metadata.get("chess_color", "") or "").lower()
    if side in ("black", "white"):
        return side
    return ""


def missing_chess_color_warnings(board: Board) -> list[str]:
    """Warn when melmod/OCR did not export chess piece color."""
    warnings: list[str] = []
    for row in range(5):
        for col in range(5):
            tile = board.get(row, col)
            if tile is None or not is_chess_piece(tile) or chess_side_known(tile):
                continue
            warnings.append(
                f"Chess tile at ({row},{col}) missing color — pawn moves may be "
                "wrong; press F7 after rebuilding melmod"
            )
    return warnings


def is_chess_piece(tile: Tile) -> bool:
    return tile.curse in CHESS_CURSES


def opposite_side(side: str) -> str:
    return "white" if side == "black" else "black"


def _chess_piece_at(board: Board, idx: int) -> Tile | None:
    """Chess piece occupying idx, regardless of word-path visit state."""
    if not board.is_active_index(idx):
        return None
    tile = board.get_by_index(idx)
    if is_chess_piece(tile):
        return tile
    return None


def _unvisited_chess_at(
    board: Board,
    idx: int,
    visited: int | set[int],
) -> Tile | None:
    if _visited_has(visited, idx):
        return None
    return _chess_piece_at(board, idx)


def can_land_on_chess_square(
    board: Board,
    idx: int,
    moving_side: str,
    visited: int | set[int],
    *,
    allies_can_take: bool = False,
) -> bool:
    """Whether a chess move may end on idx."""
    if _visited_has(visited, idx):
        return False
    if not board.is_active_index(idx):
        return False
    tile = board.get_by_index(idx)
    if not is_chess_piece(tile):
        return True
    if not chess_side_known(tile):
        return False
    target_side = chess_side(tile)
    if target_side == moving_side:
        return allies_can_take
    return True


def _step_col_toward(
    col: int,
    target_col: int,
    *,
    horizontal_wrap: bool,
) -> int:
    if col == target_col:
        return col
    if horizontal_wrap and col == 4 and target_col < col:
        return 0 if target_col == 0 else col - 1
    if horizontal_wrap and col == 0 and target_col > col:
        return 4 if target_col == 4 else col + 1
    return col + (1 if target_col > col else -1)


def _ray_step(
    row: int,
    col: int,
    dr: int,
    dc: int,
    *,
    horizontal_wrap: bool,
) -> tuple[int, int] | None:
    """Next cell along a ray; col 0 and col 4 connect when horizontal_wrap."""
    nr, nc = row + dr, col + dc
    if 0 <= nr < 5 and 0 <= nc < 5:
        return nr, nc
    if not horizontal_wrap or not (0 <= nr < 5):
        return None
    # Only wrap when stepping off the left/right edge (not when already past the board).
    if col == 4 and dc > 0:
        return nr, 0
    if col == 0 and dc < 0:
        return nr, 4
    return None


def _can_land_on_chess_square_fast(
    graph_ctx: BoardGraphContext,
    idx: int,
    moving_side: str,
    visited_mask: int,
    *,
    allies_can_take: bool,
) -> bool:
    if visited_mask & (1 << idx):
        return False
    if not graph_ctx.is_active(idx):
        return False
    if not graph_ctx.is_chess_piece_at(idx):
        return True
    side = graph_ctx.chess_side_at(idx)
    if not side:
        return False
    if side == moving_side:
        return allies_can_take
    return True


def _ray_neighbors_mask(
    board: Board,
    start_idx: int,
    visited_mask: int,
    *,
    moving_side: str,
    allies_can_take: bool,
    straight: bool = False,
    diagonal: bool = False,
    horizontal_wrap: bool = False,
    graph_ctx: BoardGraphContext | None = None,
) -> int:
    if graph_ctx is not None:
        lines = (
            graph_ctx.ray_lines_wrap if horizontal_wrap else graph_ctx.ray_lines
        )
    else:
        from cursed_words_solver.graph_bitboard import ray_lines_for_board

        lines = ray_lines_for_board(board, horizontal_wrap=horizontal_wrap)
    dir_indices: list[int] = []
    if straight:
        dir_indices.extend(STRAIGHT_DIR_INDICES)
    if diagonal:
        dir_indices.extend(DIAG_DIR_INDICES)
    mask = 0
    for d in dir_indices:
        for idx in lines[start_idx][d]:
            if graph_ctx is not None:
                if not graph_ctx.is_active(idx):
                    continue
                if graph_ctx.is_chess_piece_at(idx):
                    if _can_land_on_chess_square_fast(
                        graph_ctx,
                        idx,
                        moving_side,
                        visited_mask,
                        allies_can_take=allies_can_take,
                    ):
                        mask |= 1 << idx
                    break
                if visited_mask & (1 << idx):
                    continue
                mask |= 1 << idx
            else:
                if not board.is_active_index(idx):
                    continue
                if _chess_piece_at(board, idx) is not None:
                    if can_land_on_chess_square(
                        board,
                        idx,
                        moving_side,
                        visited_mask,
                        allies_can_take=allies_can_take,
                    ):
                        mask |= 1 << idx
                    break
                if visited_mask & (1 << idx):
                    continue
                mask |= 1 << idx
    return mask


def knight_neighbors_mask(
    board: Board,
    start_idx: int,
    visited_mask: int,
    *,
    moving_side: str,
    allies_can_take: bool = False,
    graph_ctx: BoardGraphContext | None = None,
    horizontal_wrap: bool = False,
) -> int:
    if graph_ctx is not None and not horizontal_wrap:
        return (
            graph_ctx.knight_land_for(
                start_idx, moving_side, allies_can_take=allies_can_take
            )
            & ~visited_mask
        )
    rows, cols = board.storage_rows, board.storage_cols
    candidates = knight_targets_for_cell(
        start_idx,
        rows=rows,
        cols=cols,
        horizontal_wrap=horizontal_wrap,
    )
    mask = 0
    for idx in iter_mask(candidates):
        if can_land_on_chess_square(
            board,
            idx,
            moving_side,
            visited_mask,
            allies_can_take=allies_can_take,
        ):
            mask |= 1 << idx
    return mask


def king_neighbors_mask(
    board: Board,
    start_idx: int,
    visited_mask: int,
    *,
    moving_side: str,
    allies_can_take: bool = False,
    horizontal_wrap: bool = False,
    graph_ctx: BoardGraphContext | None = None,
) -> int:
    opp = opposite_side(moving_side)
    if graph_ctx is not None:
        candidates = (
            graph_ctx.king_step_for(
                start_idx,
                moving_side,
                allies_can_take=allies_can_take,
                horizontal_wrap=horizontal_wrap,
            )
            & ~visited_mask
        )
        mask = 0
        for idx in iter_mask(candidates):
            nr, nc = idx // 5, idx % 5
            if is_square_attacked(
                board, nr, nc, opp, visited_mask, horizontal_wrap=horizontal_wrap
            ):
                continue
            mask |= 1 << idx
        return mask
    base = NEIGHBORS_8_WRAP[start_idx] if horizontal_wrap else NEIGHBORS_8[start_idx]
    mask = 0
    for idx in iter_mask(base):
        nr, nc = idx // 5, idx % 5
        if not can_land_on_chess_square(
            board,
            idx,
            moving_side,
            visited_mask,
            allies_can_take=allies_can_take,
        ):
            continue
        if is_square_attacked(
            board, nr, nc, opp, visited_mask, horizontal_wrap=horizontal_wrap
        ):
            continue
        mask |= 1 << idx
    return mask


def pawn_neighbors_mask(
    board: Board,
    start_idx: int,
    visited_mask: int,
    *,
    moving_side: str,
    allies_can_take: bool = False,
    horizontal_wrap: bool = False,
) -> int:
    return mask_from_indices(
        pawn_neighbors(
            board,
            start_idx,
            visited_mask,
            moving_side=moving_side,
            allies_can_take=allies_can_take,
            horizontal_wrap=horizontal_wrap,
        )
    )


def _television_item_neighbors_mask(
    visited_mask: int,
    *,
    item_mask: int,
    active_mask: int,
) -> int:
    return get_valid_extensions(item_mask & active_mask, visited_mask)


def chess_neighbors_mask(
    board: Board,
    start_idx: int,
    visited_mask: int,
    flags: SearchFlagsMask,
    *,
    item_mask: int = 0,
    active_mask: int = 0,
    graph_ctx: BoardGraphContext | None = None,
) -> int:
    """Curse-aware neighbor bitmask when stepping from a chess piece."""
    flags = coerce_search_flags(flags)
    last_tile = board.get_by_index(start_idx)
    if not chess_side_known(last_tile):
        return 0
    side = chess_side(last_tile)
    allies = flag_test(flags, FLAG_CHESS_ALLIES_CAN_TAKE)
    wrap = flag_test(flags, FLAG_HORIZONTAL_WRAP)

    curse = last_tile.curse
    if curse == CurseType.CHESS_KNIGHT:
        mask = knight_neighbors_mask(
            board,
            start_idx,
            visited_mask,
            moving_side=side,
            allies_can_take=allies,
            graph_ctx=graph_ctx,
            horizontal_wrap=wrap,
        )
    elif curse == CurseType.CHESS_ROOK:
        mask = _ray_neighbors_mask(
            board,
            start_idx,
            visited_mask,
            moving_side=side,
            allies_can_take=allies,
            straight=True,
            horizontal_wrap=wrap,
            graph_ctx=graph_ctx,
        )
    elif curse == CurseType.CHESS_BISHOP:
        mask = _ray_neighbors_mask(
            board,
            start_idx,
            visited_mask,
            moving_side=side,
            allies_can_take=allies,
            diagonal=True,
            horizontal_wrap=wrap,
            graph_ctx=graph_ctx,
        )
    elif curse == CurseType.CHESS_QUEEN:
        mask = _ray_neighbors_mask(
            board,
            start_idx,
            visited_mask,
            moving_side=side,
            allies_can_take=allies,
            straight=True,
            diagonal=True,
            horizontal_wrap=wrap,
            graph_ctx=graph_ctx,
        )
    elif curse == CurseType.CHESS_KING:
        mask = king_neighbors_mask(
            board,
            start_idx,
            visited_mask,
            moving_side=side,
            allies_can_take=allies,
            horizontal_wrap=wrap,
            graph_ctx=graph_ctx,
        )
    elif curse == CurseType.CHESS_PAWN:
        mask = pawn_neighbors_mask(
            board,
            start_idx,
            visited_mask,
            moving_side=side,
            allies_can_take=allies,
            horizontal_wrap=wrap,
        )
    else:
        mask = 0

    if flag_test(flags, FLAG_CHESS_KING_QUEEN_ITEM_MOVEMENT) and curse in (
        CurseType.CHESS_KING,
        CurseType.CHESS_QUEEN,
    ):
        if not active_mask:
            active_mask = sum(1 << i for i in _active_indices(board))
        if not item_mask:
            item_mask = sum(
                1 << i
                for i in _active_indices(board)
                if board.get_by_index(i).curse == CurseType.ITEM
            )
        mask |= _television_item_neighbors_mask(
            visited_mask, item_mask=item_mask, active_mask=active_mask
        )
    return mask


def _ray_neighbors(
    board: Board,
    start_idx: int,
    visited: int | set[int],
    *,
    moving_side: str,
    allies_can_take: bool,
    straight: bool = False,
    diagonal: bool = False,
    horizontal_wrap: bool = False,
) -> list[int]:
    row, col = start_idx // 5, start_idx % 5
    dirs: list[tuple[int, int]] = []
    if straight:
        dirs.extend(STRAIGHT_DIRS)
    if diagonal:
        dirs.extend(DIAG_DIRS)
    out: list[int] = []
    for dr, dc in dirs:
        r, c = row, col
        seen: set[tuple[int, int]] = set()
        while True:
            nxt = _ray_step(r, c, dr, dc, horizontal_wrap=horizontal_wrap)
            if nxt is None or nxt in seen:
                break
            seen.add(nxt)
            nr, nc = nxt
            idx = index_of(nr, nc)
            if not board.is_active_index(idx):
                r, c = nr, nc
                continue
            if _chess_piece_at(board, idx) is not None:
                if can_land_on_chess_square(
                    board,
                    idx,
                    moving_side,
                    visited,
                    allies_can_take=allies_can_take,
                ):
                    out.append(idx)
                break
            if _visited_has(visited, idx):
                r, c = nr, nc
                continue
            out.append(idx)
            r, c = nr, nc
    return out


def knight_neighbors(
    board: Board,
    start_idx: int,
    visited: int | set[int],
    *,
    moving_side: str,
    allies_can_take: bool = False,
) -> list[int]:
    row, col = start_idx // 5, start_idx % 5
    out: list[int] = []
    for dr, dc in KNIGHT_DIRS:
        nr, nc = row + dr, col + dc
        if not (0 <= nr < 5 and 0 <= nc < 5):
            continue
        idx = index_of(nr, nc)
        if can_land_on_chess_square(
            board,
            idx,
            moving_side,
            visited,
            allies_can_take=allies_can_take,
        ):
            out.append(idx)
    return out


def _pawn_home_row(board: Board, side: str) -> int:
    """Wiki: white home = second from top; black home = second from bottom."""
    if side == "black":
        return board.playable_max_row - 1
    return board.playable_min_row + 1


def _pawn_forward_delta(side: str) -> int:
    return 1 if side == "black" else -1


def _pawn_attack_dirs(side: str) -> list[tuple[int, int]]:
    dr = _pawn_forward_delta(side)
    return [(dr, -1), (dr, 1)]


def _pawn_attack_cols(pawn_col: int, *, horizontal_wrap: bool) -> list[int]:
    """Columns a pawn on pawn_col can attack diagonally (Hungry Snake: col 0 ↔ 4)."""
    cols: list[int] = []
    if pawn_col > 0:
        cols.append(pawn_col - 1)
    if pawn_col < 4:
        cols.append(pawn_col + 1)
    if horizontal_wrap:
        partner = _wrap_partner_col(pawn_col)
        if partner is not None and partner not in cols:
            cols.append(partner)
    return cols


def _pawn_forward_clear(
    board: Board,
    row: int,
    col: int,
    side: str,
    visited: int | set[int],
) -> bool:
    dr = _pawn_forward_delta(side)
    nr, nc = row + dr, col
    if not (0 <= nr < 5 and 0 <= nc < 5):
        return False
    idx = index_of(nr, nc)
    if not board.is_active_index(idx) or _visited_has(visited, idx):
        return False
    return _unvisited_chess_at(board, idx, visited) is None


def _pawn_diagonal_capture(
    board: Board,
    row: int,
    col: int,
    side: str,
    visited: int | set[int],
    *,
    allies_can_take: bool,
    horizontal_wrap: bool = False,
) -> list[int]:
    dr = _pawn_forward_delta(side)
    out: list[int] = []
    for nc in _pawn_attack_cols(col, horizontal_wrap=horizontal_wrap):
        nr = row + dr
        if not (0 <= nr < 5 and 0 <= nc < 5):
            continue
        idx = index_of(nr, nc)
        target = _unvisited_chess_at(board, idx, visited)
        if target is None:
            continue
        if can_land_on_chess_square(
            board,
            idx,
            side,
            visited,
            allies_can_take=allies_can_take,
        ):
            out.append(idx)
    return out


def _en_passant_targets(
    board: Board,
    row: int,
    col: int,
    side: str,
    visited: int | set[int],
) -> list[int]:
    """Wiki simplified en passant (no move history)."""
    out: list[int] = []
    for dc in (-1, 1):
        adj_col = col + dc
        if not (0 <= adj_col < 5):
            continue
        if side == "black":
            if row != EN_PASSANT_BLACK_RANK:
                continue
            adj_idx = index_of(EN_PASSANT_BLACK_RANK, adj_col)
            adj = _unvisited_chess_at(board, adj_idx, visited)
            if adj is None or adj.curse != CurseType.CHESS_PAWN:
                continue
            if not chess_side_known(adj) or chess_side(adj) != "white":
                continue
            cap_row = EN_PASSANT_BLACK_RANK + 1
            cap_idx = index_of(cap_row, adj_col)
        else:
            if row != EN_PASSANT_WHITE_RANK:
                continue
            adj_idx = index_of(EN_PASSANT_WHITE_RANK, adj_col)
            adj = _unvisited_chess_at(board, adj_idx, visited)
            if adj is None or adj.curse != CurseType.CHESS_PAWN:
                continue
            if not chess_side_known(adj) or chess_side(adj) != "black":
                continue
            cap_row = EN_PASSANT_WHITE_RANK - 1
            cap_idx = index_of(cap_row, adj_col)
        if (
            board.is_active_index(cap_idx)
            and not _visited_has(visited, cap_idx)
            and _unvisited_chess_at(board, cap_idx, visited) is None
        ):
            out.append(cap_idx)
    return out


def pawn_neighbors(
    board: Board,
    start_idx: int,
    visited: int | set[int],
    *,
    moving_side: str,
    allies_can_take: bool = False,
    horizontal_wrap: bool = False,
) -> list[int]:
    row, col = start_idx // 5, start_idx % 5
    dr = _pawn_forward_delta(moving_side)
    out: list[int] = []

    nr, nc = row + dr, col
    if 0 <= nr < 5 and 0 <= nc < 5:
        fwd_idx = index_of(nr, nc)
        if can_land_on_chess_square(
            board,
            fwd_idx,
            moving_side,
            visited,
            allies_can_take=False,
        ) and _unvisited_chess_at(board, fwd_idx, visited) is None:
            out.append(fwd_idx)
            if row == _pawn_home_row(board, moving_side):
                nr2 = row + 2 * dr
                if 0 <= nr2 < 5:
                    idx2 = index_of(nr2, col)
                    if (
                        can_land_on_chess_square(
                            board,
                            idx2,
                            moving_side,
                            visited,
                            allies_can_take=False,
                        )
                        and _unvisited_chess_at(board, idx2, visited) is None
                        and _pawn_forward_clear(
                            board, row, col, moving_side, visited
                        )
                    ):
                        out.append(idx2)

    out.extend(
        _pawn_diagonal_capture(
            board,
            row,
            col,
            moving_side,
            visited,
            allies_can_take=allies_can_take,
            horizontal_wrap=horizontal_wrap,
        )
    )
    out.extend(
        _en_passant_targets(board, row, col, moving_side, visited)
    )
    return out


def _pawn_at_attacks_target(
    board: Board,
    pawn_row: int,
    pawn_col: int,
    target_row: int,
    target_col: int,
    side: str,
    visited: int | set[int],
    *,
    horizontal_wrap: bool = False,
) -> bool:
    dr = _pawn_forward_delta(side)
    if pawn_row + dr != target_row:
        return False
    if target_col not in _pawn_attack_cols(pawn_col, horizontal_wrap=horizontal_wrap):
        return False
    idx = index_of(pawn_row, pawn_col)
    tile = _chess_piece_at(board, idx)
    if tile is None:
        return False
    return (
        tile.curse == CurseType.CHESS_PAWN
        and chess_side_known(tile)
        and chess_side(tile) == side
    )


def _is_square_attacked_by_pawn(
    board: Board,
    target_row: int,
    target_col: int,
    side: str,
    visited: int | set[int],
    *,
    horizontal_wrap: bool = False,
) -> bool:
    dr = _pawn_forward_delta(side)
    for dc in (-1, 1):
        pr, pc = target_row - dr, target_col - dc
        if not (0 <= pr < 5 and 0 <= pc < 5):
            continue
        if _pawn_at_attacks_target(
            board,
            pr,
            pc,
            target_row,
            target_col,
            side,
            visited,
            horizontal_wrap=horizontal_wrap,
        ):
            return True
    if horizontal_wrap:
        partner = _wrap_partner_col(target_col)
        if partner is not None:
            pr, pc = target_row - dr, partner
            if 0 <= pr < 5 and _pawn_at_attacks_target(
                board,
                pr,
                pc,
                target_row,
                target_col,
                side,
                visited,
                horizontal_wrap=horizontal_wrap,
            ):
                return True
    return False


def _knight_at_attacks_target(
    board: Board,
    knight_row: int,
    knight_col: int,
    target_row: int,
    target_col: int,
    side: str,
    visited: int | set[int],
) -> bool:
    if abs(knight_row - target_row) == 2 and abs(knight_col - target_col) == 1:
        pass
    elif abs(knight_row - target_row) == 1 and abs(knight_col - target_col) == 2:
        pass
    else:
        return False
    idx = index_of(knight_row, knight_col)
    tile = _chess_piece_at(board, idx)
    if tile is None:
        return False
    return (
        tile.curse == CurseType.CHESS_KNIGHT
        and chess_side_known(tile)
        and chess_side(tile) == side
    )


def _is_square_attacked_by_knight(
    board: Board,
    target_row: int,
    target_col: int,
    side: str,
    visited: int | set[int],
    *,
    horizontal_wrap: bool = False,
) -> bool:
    for idx in _active_indices(board):
        tile = _chess_piece_at(board, idx)
        if tile is None:
            continue
        if (
            tile.curse != CurseType.CHESS_KNIGHT
            or not chess_side_known(tile)
            or chess_side(tile) != side
        ):
            continue
        fr, fc = idx // 5, idx % 5
        for orow, ocol in _attack_origins(
            fr, fc, horizontal_wrap=horizontal_wrap
        ):
            for dr, dc in KNIGHT_DIRS:
                if orow + dr == target_row and ocol + dc == target_col:
                    return True
    return False


def _king_at_attacks_target(
    board: Board,
    king_row: int,
    king_col: int,
    target_row: int,
    target_col: int,
    side: str,
    visited: int | set[int],
) -> bool:
    if max(abs(king_row - target_row), abs(king_col - target_col)) != 1:
        return False
    idx = index_of(king_row, king_col)
    tile = _chess_piece_at(board, idx)
    if tile is None:
        return False
    return (
        tile.curse == CurseType.CHESS_KING
        and chess_side_known(tile)
        and chess_side(tile) == side
    )


def _is_square_attacked_by_king(
    board: Board,
    target_row: int,
    target_col: int,
    side: str,
    visited: int | set[int],
    *,
    horizontal_wrap: bool = False,
) -> bool:
    for dr, dc in DIRS_8:
        nr, nc = target_row + dr, target_col + dc
        if not (0 <= nr < 5 and 0 <= nc < 5):
            continue
        if _king_at_attacks_target(
            board, nr, nc, target_row, target_col, side, visited
        ):
            return True
    if horizontal_wrap:
        partner = _wrap_partner_col(target_col)
        if partner is not None:
            for dr in (-1, 0, 1):
                nr = target_row + dr
                if not (0 <= nr < 5):
                    continue
                if _king_at_attacks_target(
                    board, nr, partner, target_row, target_col, side, visited
                ):
                    return True
    return False


def _ray_path_clear(
    board: Board,
    from_row: int,
    from_col: int,
    to_row: int,
    to_col: int,
    visited: int | set[int],
    *,
    horizontal_wrap: bool,
) -> bool:
    """True when no chess piece blocks between from and to (exclusive of from)."""
    r, c = from_row, from_col
    seen: set[tuple[int, int]] = {(from_row, from_col)}
    for _ in range(25):
        if (r, c) == (to_row, to_col):
            return True
        dr = 0 if r == to_row else (1 if to_row > r else -1)
        dc_raw = 0 if c == to_col else (1 if to_col > c else -1)
        if dr != 0 and c != to_col:
            nc = _step_col_toward(c, to_col, horizontal_wrap=horizontal_wrap)
            nr = r + dr
        elif dr == 0 and c != to_col:
            nc = _step_col_toward(c, to_col, horizontal_wrap=horizontal_wrap)
            nr = r
        else:
            nr, nc = r + dr, c + dc_raw
        if not (0 <= nr < 5 and 0 <= nc < 5):
            return False
        if (nr, nc) in seen:
            return False
        seen.add((nr, nc))
        idx = index_of(nr, nc)
        if not board.is_active_index(idx):
            r, c = nr, nc
            continue
        tile = board.get_by_index(idx)
        if is_chess_piece(tile):
            if _visited_has(visited, idx):
                r, c = nr, nc
                continue
            return False
        if _visited_has(visited, idx):
            r, c = nr, nc
            continue
        r, c = nr, nc
    return False


def _sliding_piece_attacks(
    board: Board,
    from_row: int,
    from_col: int,
    target_row: int,
    target_col: int,
    piece: Tile,
    visited: int | set[int],
    *,
    horizontal_wrap: bool,
) -> bool:
    curse = piece.curse
    row_delta = abs(target_row - from_row)
    col_delta = abs(target_col - from_col)
    wcol = (
        _wrap_col_distance(from_col, target_col)
        if horizontal_wrap
        else col_delta
    )
    if from_row == target_row and from_col == target_col:
        return False
    if curse in (CurseType.CHESS_ROOK, CurseType.CHESS_QUEEN):
        if row_delta != 0 and wcol != 0:
            return False
        if row_delta == 0 and wcol == 0:
            return False
    if curse in (CurseType.CHESS_BISHOP, CurseType.CHESS_QUEEN):
        if row_delta == 0:
            return False
        if row_delta != wcol:
            return False
    if curse == CurseType.CHESS_ROOK and row_delta != 0:
        return False
    if curse == CurseType.CHESS_BISHOP and row_delta == 0:
        return False
    return _ray_path_clear(
        board,
        from_row,
        from_col,
        target_row,
        target_col,
        visited,
        horizontal_wrap=horizontal_wrap,
    )


def _is_square_attacked_by_sliding(
    board: Board,
    target_row: int,
    target_col: int,
    side: str,
    visited: int | set[int],
    *,
    straight: bool,
    diagonal: bool,
    horizontal_wrap: bool = False,
) -> bool:
    dirs: list[tuple[int, int]] = []
    if straight:
        dirs.extend(STRAIGHT_DIRS)
    if diagonal:
        dirs.extend(DIAG_DIRS)
    for dr, dc in dirs:
        r, c = target_row, target_col
        seen: set[tuple[int, int]] = set()
        while True:
            nxt = _ray_step(r, c, dr, dc, horizontal_wrap=horizontal_wrap)
            if nxt is None or nxt in seen:
                break
            seen.add(nxt)
            nr, nc = nxt
            idx = index_of(nr, nc)
            if not board.is_active_index(idx):
                r, c = nr, nc
                continue
            tile = board.get_by_index(idx)
            if is_chess_piece(tile):
                if chess_side_known(tile) and chess_side(tile) == side:
                    if straight and tile.curse in (
                        CurseType.CHESS_ROOK,
                        CurseType.CHESS_QUEEN,
                    ):
                        return True
                    if diagonal and tile.curse in (
                        CurseType.CHESS_BISHOP,
                        CurseType.CHESS_QUEEN,
                    ):
                        return True
                if _visited_has(visited, idx):
                    r, c = nr, nc
                    continue
                break
            if _visited_has(visited, idx):
                r, c = nr, nc
                continue
            r, c = nr, nc
    if horizontal_wrap:
        for idx in _active_indices(board):
            tile = _chess_piece_at(board, idx)
            if tile is None or not chess_side_known(tile) or chess_side(tile) != side:
                continue
            curse = tile.curse
            ok = False
            if straight and curse in (CurseType.CHESS_ROOK, CurseType.CHESS_QUEEN):
                ok = True
            if diagonal and curse in (
                CurseType.CHESS_BISHOP,
                CurseType.CHESS_QUEEN,
            ):
                ok = True
            if not ok:
                continue
            fr, fc = idx // 5, idx % 5
            if _sliding_piece_attacks(
                board,
                fr,
                fc,
                target_row,
                target_col,
                tile,
                visited,
                horizontal_wrap=True,
            ):
                return True
    return False


def _is_square_attacked_uncached(
    board: Board,
    row: int,
    col: int,
    by_side: str,
    visited: int | set[int],
    *,
    horizontal_wrap: bool = False,
) -> bool:
    if _is_square_attacked_by_pawn(
        board, row, col, by_side, visited, horizontal_wrap=horizontal_wrap
    ):
        return True
    if _is_square_attacked_by_knight(
        board, row, col, by_side, visited, horizontal_wrap=horizontal_wrap
    ):
        return True
    if _is_square_attacked_by_king(
        board, row, col, by_side, visited, horizontal_wrap=horizontal_wrap
    ):
        return True
    if _is_square_attacked_by_sliding(
        board,
        row,
        col,
        by_side,
        visited,
        straight=True,
        diagonal=False,
        horizontal_wrap=horizontal_wrap,
    ):
        return True
    if _is_square_attacked_by_sliding(
        board,
        row,
        col,
        by_side,
        visited,
        straight=False,
        diagonal=True,
        horizontal_wrap=horizontal_wrap,
    ):
        return True
    return False


def is_square_attacked(
    board: Board,
    row: int,
    col: int,
    by_side: str,
    visited: int | set[int],
    *,
    horizontal_wrap: bool = False,
) -> bool:
    if not _board_has_chess_pieces:
        return False
    fp = (
        _solve_board_fingerprint
        if _solve_board_fingerprint is not None
        else board_fingerprint(board)
    )
    key = (
        fp,
        _visited_cache_key(visited),
        row,
        col,
        by_side,
        horizontal_wrap,
    )
    global _attack_cache_hits, _attack_cache_misses
    hit = _attack_cache.get(key)
    if hit is not None:
        _attack_cache_hits += 1
        _attack_cache.move_to_end(key)
        return hit
    _attack_cache_misses += 1
    result = _is_square_attacked_uncached(
        board, row, col, by_side, visited, horizontal_wrap=horizontal_wrap
    )
    _attack_cache[key] = result
    if len(_attack_cache) > _ATTACK_CACHE_MAX:
        _attack_cache.popitem(last=False)
    return result


def _try_king_destination(
    board: Board,
    idx: int,
    *,
    moving_side: str,
    opp: str,
    visited: int | set[int],
    allies_can_take: bool,
    horizontal_wrap: bool,
    out: list[int],
) -> None:
    nr, nc = idx // 5, idx % 5
    if not can_land_on_chess_square(
        board,
        idx,
        moving_side,
        visited,
        allies_can_take=allies_can_take,
    ):
        return
    if is_square_attacked(
        board, nr, nc, opp, visited, horizontal_wrap=horizontal_wrap
    ):
        return
    out.append(idx)


def king_neighbors(
    board: Board,
    start_idx: int,
    visited: int | set[int],
    *,
    moving_side: str,
    allies_can_take: bool = False,
    horizontal_wrap: bool = False,
) -> list[int]:
    row, col = start_idx // 5, start_idx % 5
    opp = opposite_side(moving_side)
    out: list[int] = []
    for dr, dc in DIRS_8:
        nr, nc = row + dr, col + dc
        if not (0 <= nr < 5 and 0 <= nc < 5):
            continue
        _try_king_destination(
            board,
            index_of(nr, nc),
            moving_side=moving_side,
            opp=opp,
            visited=visited,
            allies_can_take=allies_can_take,
            horizontal_wrap=horizontal_wrap,
            out=out,
        )
    if horizontal_wrap:
        partner = _wrap_partner_col(col)
        if partner is not None:
            _try_king_destination(
                board,
                index_of(row, partner),
                moving_side=moving_side,
                opp=opp,
                visited=visited,
                allies_can_take=allies_can_take,
                horizontal_wrap=horizontal_wrap,
                out=out,
            )
    return out


def _television_item_neighbors(
    board: Board,
    visited: int | set[int],
) -> list[int]:
    return [
        idx
        for idx in _active_indices(board)
        if not _visited_has(visited, idx)
        and board.get_by_index(idx).curse == CurseType.ITEM
    ]


def chess_neighbors(
    board: Board,
    path: list[int],
    visited: int | set[int],
    flags: SearchFlagsMask,
) -> list[int]:
    """Curse-aware neighbors when stepping from a chess piece."""
    visited_mask = (
        visited
        if isinstance(visited, int)
        else mask_from_indices(visited)
    )
    mask = chess_neighbors_mask(
        board, path[-1], visited_mask, flags
    )
    return list(iter_mask(mask))


def identical_chess_piece(a: Tile, b: Tile) -> bool:
    """Full Moon: teleport between identical chess pieces."""
    if not is_chess_piece(a) or not is_chess_piece(b):
        return False
    if not chess_side_known(a) or not chess_side_known(b):
        return False
    return a.curse == b.curse and chess_side(a) == chess_side(b)


def _capture_step_reachable(
    board: Board,
    from_idx: int,
    to_idx: int,
    *,
    prefix: list[int],
    visited_set: int | set[int],
    search_flags: SearchFlagsMask,
    loadout: Loadout | None,
) -> bool:
    if loadout is not None:
        from cursed_words_solver.rules.quest_movement import sicilian_defense_active

        if sicilian_defense_active(loadout):
            from cursed_words_solver.rules.quest_movement import (
                sicilian_neighbors_mask,
            )

            visited_mask = (
                visited_set
                if isinstance(visited_set, int)
                else mask_from_indices(visited_set)
            )
            mask = sicilian_neighbors_mask(
                board,
                from_idx,
                visited_mask,
                flags=search_flags,
            )
            return bool(mask & (1 << to_idx))
    return to_idx in chess_neighbors(board, prefix, visited_set, search_flags)


def is_chess_capture_step(
    board: Board,
    from_idx: int,
    to_idx: int,
    *,
    allies_can_take: bool = False,
    path_prefix: list[int] | None = None,
    visited: int | set[int] | None = None,
    flags: SearchFlagsMask = 0,
    loadout: Loadout | None = None,
) -> bool:
    """True when a chess step lands on an opponent (or ally take) or en passant."""
    from_tile = board.get_by_index(from_idx)
    if not is_chess_piece(from_tile) or not chess_side_known(from_tile):
        return False

    prefix = path_prefix if path_prefix is not None else [from_idx]
    visited_set: int | set[int] = (
        visited if visited is not None else {from_idx}
    )

    search_flags = coerce_search_flags(flags)
    if allies_can_take and not flag_test(search_flags, FLAG_CHESS_ALLIES_CAN_TAKE):
        search_flags = flag_set(search_flags, FLAG_CHESS_ALLIES_CAN_TAKE)
    elif allies_can_take and not search_flags:
        search_flags = FLAG_CHESS_ALLIES_CAN_TAKE
    if not _capture_step_reachable(
        board,
        from_idx,
        to_idx,
        prefix=prefix,
        visited_set=visited_set,
        search_flags=search_flags,
        loadout=loadout,
    ):
        return False

    to_tile = board.get_by_index(to_idx)
    side = chess_side(from_tile)

    if is_chess_piece(to_tile) and chess_side_known(to_tile):
        target_side = chess_side(to_tile)
        if target_side == side:
            return allies_can_take
        return True

    if from_tile.curse == CurseType.CHESS_PAWN:
        row, col = from_idx // 5, from_idx % 5
        if to_idx in _en_passant_targets(board, row, col, side, visited_set):
            return True

    return False
