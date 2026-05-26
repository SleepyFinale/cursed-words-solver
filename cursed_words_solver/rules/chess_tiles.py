"""Chess piece movement and attack rules (wiki: Curses — Chess pieces)."""

from __future__ import annotations

from collections import OrderedDict

from cursed_words_solver.fingerprints import board_fingerprint
from cursed_words_solver.models import (
    CHESS_CURSES,
    Board,
    CurseType,
    Tile,
)
from cursed_words_solver.rules.stamp_behaviors import StampSearchFlags

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

BLACK_HOME_ROW = 0
WHITE_HOME_ROW = 4
EN_PASSANT_BLACK_RANK = 1
EN_PASSANT_WHITE_RANK = 3

_ATTACK_CACHE_MAX = 8192
_attack_cache: OrderedDict[tuple, bool] = OrderedDict()


def _visited_cache_key(visited: int | set[int]) -> int | frozenset[int]:
    if isinstance(visited, set):
        return frozenset(visited)
    return visited


def clear_chess_attack_cache() -> None:
    """Clear attack lookup cache (call at start of each solve)."""
    _attack_cache.clear()


def index_of(row: int, col: int) -> int:
    return row * 5 + col


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


def _ray_neighbors(
    board: Board,
    start_idx: int,
    visited: int | set[int],
    *,
    moving_side: str,
    allies_can_take: bool,
    straight: bool = False,
    diagonal: bool = False,
) -> list[int]:
    row, col = start_idx // 5, start_idx % 5
    dirs: list[tuple[int, int]] = []
    if straight:
        dirs.extend(STRAIGHT_DIRS)
    if diagonal:
        dirs.extend(DIAG_DIRS)
    out: list[int] = []
    for dr, dc in dirs:
        step = 1
        while True:
            nr, nc = row + dr * step, col + dc * step
            if not (0 <= nr < 5 and 0 <= nc < 5):
                break
            idx = index_of(nr, nc)
            if not board.is_active_index(idx):
                step += 1
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
                step += 1
                continue
            out.append(idx)
            step += 1
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


def _pawn_forward_delta(side: str) -> int:
    return 1 if side == "black" else -1


def _pawn_attack_dirs(side: str) -> list[tuple[int, int]]:
    dr = _pawn_forward_delta(side)
    return [(dr, -1), (dr, 1)]


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
) -> list[int]:
    out: list[int] = []
    for dr, dc in _pawn_attack_dirs(side):
        nr, nc = row + dr, col + dc
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
            home = BLACK_HOME_ROW if moving_side == "black" else WHITE_HOME_ROW
            if row == home:
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
        )
    )
    out.extend(
        _en_passant_targets(board, row, col, moving_side, visited)
    )
    return out


def _is_square_attacked_by_pawn(
    board: Board,
    target_row: int,
    target_col: int,
    side: str,
    visited: int | set[int],
) -> bool:
    dr = _pawn_forward_delta(side)
    for dc in (-1, 1):
        pr, pc = target_row - dr, target_col - dc
        if not (0 <= pr < 5 and 0 <= pc < 5):
            continue
        idx = index_of(pr, pc)
        tile = _unvisited_chess_at(board, idx, visited)
        if tile is None:
            continue
        if (
            tile.curse == CurseType.CHESS_PAWN
            and chess_side_known(tile)
            and chess_side(tile) == side
        ):
            return True
    return False


def _is_square_attacked_by_knight(
    board: Board,
    target_row: int,
    target_col: int,
    side: str,
    visited: int | set[int],
) -> bool:
    for dr, dc in KNIGHT_DIRS:
        nr, nc = target_row + dr, target_col + dc
        if not (0 <= nr < 5 and 0 <= nc < 5):
            continue
        idx = index_of(nr, nc)
        tile = _unvisited_chess_at(board, idx, visited)
        if tile is None:
            continue
        if (
            tile.curse == CurseType.CHESS_KNIGHT
            and chess_side_known(tile)
            and chess_side(tile) == side
        ):
            return True
    return False


def _is_square_attacked_by_king(
    board: Board,
    target_row: int,
    target_col: int,
    side: str,
    visited: int | set[int],
) -> bool:
    for dr, dc in DIRS_8:
        nr, nc = target_row + dr, target_col + dc
        if not (0 <= nr < 5 and 0 <= nc < 5):
            continue
        idx = index_of(nr, nc)
        tile = _unvisited_chess_at(board, idx, visited)
        if tile is None:
            continue
        if (
            tile.curse == CurseType.CHESS_KING
            and chess_side_known(tile)
            and chess_side(tile) == side
        ):
            return True
    return False


def _is_square_attacked_by_sliding(
    board: Board,
    target_row: int,
    target_col: int,
    side: str,
    visited: int | set[int],
    *,
    straight: bool,
    diagonal: bool,
) -> bool:
    dirs: list[tuple[int, int]] = []
    if straight:
        dirs.extend(STRAIGHT_DIRS)
    if diagonal:
        dirs.extend(DIAG_DIRS)
    for dr, dc in dirs:
        step = 1
        while True:
            nr, nc = target_row + dr * step, target_col + dc * step
            if not (0 <= nr < 5 and 0 <= nc < 5):
                break
            idx = index_of(nr, nc)
            if not board.is_active_index(idx):
                step += 1
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
                break
            if _visited_has(visited, idx):
                step += 1
                continue
            step += 1
    return False


def _is_square_attacked_uncached(
    board: Board,
    row: int,
    col: int,
    by_side: str,
    visited: int | set[int],
) -> bool:
    if _is_square_attacked_by_pawn(board, row, col, by_side, visited):
        return True
    if _is_square_attacked_by_knight(board, row, col, by_side, visited):
        return True
    if _is_square_attacked_by_king(board, row, col, by_side, visited):
        return True
    if _is_square_attacked_by_sliding(
        board, row, col, by_side, visited, straight=True, diagonal=False
    ):
        return True
    if _is_square_attacked_by_sliding(
        board, row, col, by_side, visited, straight=False, diagonal=True
    ):
        return True
    return False


def is_square_attacked(
    board: Board,
    row: int,
    col: int,
    by_side: str,
    visited: int | set[int],
) -> bool:
    key = (
        board_fingerprint(board),
        _visited_cache_key(visited),
        row,
        col,
        by_side,
    )
    hit = _attack_cache.get(key)
    if hit is not None:
        _attack_cache.move_to_end(key)
        return hit
    result = _is_square_attacked_uncached(board, row, col, by_side, visited)
    _attack_cache[key] = result
    if len(_attack_cache) > _ATTACK_CACHE_MAX:
        _attack_cache.popitem(last=False)
    return result


def king_neighbors(
    board: Board,
    start_idx: int,
    visited: int | set[int],
    *,
    moving_side: str,
    allies_can_take: bool = False,
) -> list[int]:
    row, col = start_idx // 5, start_idx % 5
    opp = opposite_side(moving_side)
    out: list[int] = []
    for dr, dc in DIRS_8:
        nr, nc = row + dr, col + dc
        if not (0 <= nr < 5 and 0 <= nc < 5):
            continue
        idx = index_of(nr, nc)
        if not can_land_on_chess_square(
            board,
            idx,
            moving_side,
            visited,
            allies_can_take=allies_can_take,
        ):
            continue
        if is_square_attacked(board, nr, nc, opp, visited):
            continue
        out.append(idx)
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
    flags: StampSearchFlags,
) -> list[int]:
    """Curse-aware neighbors when stepping from a chess piece."""
    last_tile = board.get_by_index(path[-1])
    if not chess_side_known(last_tile):
        return []
    start_idx = path[-1]
    side = chess_side(last_tile)
    allies = flags.chess_allies_can_take

    curse = last_tile.curse
    if curse == CurseType.CHESS_KNIGHT:
        out = knight_neighbors(
            board, start_idx, visited, moving_side=side, allies_can_take=allies
        )
    elif curse == CurseType.CHESS_ROOK:
        out = _ray_neighbors(
            board,
            start_idx,
            visited,
            moving_side=side,
            allies_can_take=allies,
            straight=True,
        )
    elif curse == CurseType.CHESS_BISHOP:
        out = _ray_neighbors(
            board,
            start_idx,
            visited,
            moving_side=side,
            allies_can_take=allies,
            diagonal=True,
        )
    elif curse == CurseType.CHESS_QUEEN:
        out = _ray_neighbors(
            board,
            start_idx,
            visited,
            moving_side=side,
            allies_can_take=allies,
            straight=True,
            diagonal=True,
        )
    elif curse == CurseType.CHESS_KING:
        out = king_neighbors(
            board, start_idx, visited, moving_side=side, allies_can_take=allies
        )
    elif curse == CurseType.CHESS_PAWN:
        out = pawn_neighbors(
            board, start_idx, visited, moving_side=side, allies_can_take=allies
        )
    else:
        out = []

    if flags.chess_king_queen_item_movement and curse in (
        CurseType.CHESS_KING,
        CurseType.CHESS_QUEEN,
    ):
        seen = set(out)
        for idx in _television_item_neighbors(board, visited):
            if idx not in seen:
                out.append(idx)
                seen.add(idx)
    return out


def identical_chess_piece(a: Tile, b: Tile) -> bool:
    """Full Moon: teleport between identical chess pieces."""
    if not is_chess_piece(a) or not is_chess_piece(b):
        return False
    if not chess_side_known(a) or not chess_side_known(b):
        return False
    return a.curse == b.curse and chess_side(a) == chess_side(b)


def is_chess_capture_step(
    board: Board,
    from_idx: int,
    to_idx: int,
    *,
    allies_can_take: bool = False,
    path_prefix: list[int] | None = None,
    visited: int | set[int] | None = None,
) -> bool:
    """True when a chess step lands on an opponent (or ally take) or en passant."""
    from_tile = board.get_by_index(from_idx)
    if not is_chess_piece(from_tile) or not chess_side_known(from_tile):
        return False

    prefix = path_prefix if path_prefix is not None else [from_idx]
    visited_set: int | set[int] = (
        visited if visited is not None else {from_idx}
    )

    flags = StampSearchFlags(chess_allies_can_take=allies_can_take)
    if to_idx not in chess_neighbors(board, prefix, visited_set, flags):
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
