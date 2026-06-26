"""Quest movement overrides (SicilianDefense / Knight Time)."""

from __future__ import annotations

from cursed_words_solver.graph_bitboard import (
    BoardGraphContext,
    get_valid_extensions,
    iter_mask,
    knight_targets_for_cell,
)
from cursed_words_solver.models import Board, CurseType, Loadout, TileColor
from cursed_words_solver.rules.chess_tiles import (
    _television_item_neighbors_mask,
    can_land_on_chess_square,
    chess_side,
    chess_side_known,
    is_chess_piece,
    knight_neighbors_mask,
)
from cursed_words_solver.rules.quest_effects import quest_constraints
from cursed_words_solver.rules.stamp_behaviors import (
    FLAG_CHESS_ALLIES_CAN_TAKE,
    FLAG_CHESS_KING_QUEEN_ITEM_MOVEMENT,
    FLAG_DOUBLE_LETTER_TELEPORT,
    FLAG_HORIZONTAL_WRAP,
    SearchFlagsMask,
    coerce_search_flags,
    flag_test,
)


def _active_indices(board: Board) -> list[int]:
    return [i for i in range(25) if board.is_active_index(i)]


def _double_letter_teleport_mask(
    board: Board,
    cell_id: int,
    visited_mask: int,
    *,
    graph_ctx: BoardGraphContext | None = None,
) -> int:
    from cursed_words_solver.search import _double_letter_teleport_mask as _dlt

    return _dlt(board, cell_id, visited_mask, graph_ctx=graph_ctx)


def sicilian_defense_active(loadout: Loadout | None) -> bool:
    return quest_constraints(loadout).knight_only


def _white_portal_mask(
    board: Board,
    cell_id: int,
    visited_mask: int,
    *,
    active_mask: int,
) -> int:
    last = board.get_by_index(cell_id)
    if last.color != TileColor.WHITE:
        return 0
    return get_valid_extensions(active_mask, visited_mask) & ~(1 << cell_id)


def _sicilian_knight_attack_mask(
    board: Board,
    cell_id: int,
    *,
    horizontal_wrap: bool,
) -> int:
    """Knight-move destinations from cell_id (attacks / geometric reach)."""
    rows, cols = board.storage_rows, board.storage_cols
    active = sum(1 << i for i in _active_indices(board))
    return (
        knight_targets_for_cell(
            cell_id,
            rows=rows,
            cols=cols,
            horizontal_wrap=horizontal_wrap,
        )
        & active
    )


def _sicilian_king_threat_mask(
    board: Board,
    king_idx: int,
    *,
    visited_mask: int,
    active_mask: int,
    horizontal_wrap: bool = False,
    graph_ctx: BoardGraphContext | None = None,
) -> int:
    """Squares a Sicilian king may not enter (mirrors GetSicilianDefenseThreatSquares)."""
    king_tile = board.get_by_index(king_idx)
    if not chess_side_known(king_tile):
        return 0
    king_side = chess_side(king_tile)
    threat = 0
    for idx in _active_indices(board):
        if idx == king_idx:
            continue
        tile = board.get_by_index(idx)
        if not is_chess_piece(tile) or not chess_side_known(tile):
            continue
        if chess_side(tile) == king_side:
            continue
        # Threat uses GetKnightMoves(..., allowFriendlyCapture: true): all geometric
        # knight destinations (letters included), not landability-filtered.
        threat |= _sicilian_knight_attack_mask(
            board, idx, horizontal_wrap=horizontal_wrap
        )
    return threat & active_mask


def _sicilian_letter_knight_land_mask(
    board: Board,
    cell_id: int,
    visited_mask: int,
    *,
    horizontal_wrap: bool,
    active_mask: int,
    allies_can_take: bool,
    graph_ctx: BoardGraphContext | None,
) -> int:
    """Knight-only landable squares for non-chess tiles (Knight Time)."""
    candidates = (
        _sicilian_knight_attack_mask(board, cell_id, horizontal_wrap=horizontal_wrap)
        & active_mask
        & ~visited_mask
    )
    mask = 0
    for idx in iter_mask(candidates):
        tile = board.get_by_index(idx)
        if is_chess_piece(tile):
            if not chess_side_known(tile):
                continue
            tile_side = chess_side(tile)
            if not allies_can_take and can_land_on_chess_square(
                board,
                idx,
                tile_side,
                visited_mask,
                allies_can_take=False,
            ):
                continue
            opp = "black" if tile_side == "white" else "white"
            if not can_land_on_chess_square(
                board,
                idx,
                opp,
                visited_mask,
                allies_can_take=False,
            ):
                continue
        mask |= 1 << idx
    return mask


def sicilian_neighbors_mask(
    board: Board,
    cell_id: int,
    visited_mask: int,
    *,
    flags: SearchFlagsMask = 0,
    graph_ctx: BoardGraphContext | None = None,
    active_mask: int | None = None,
) -> int:
    """Knight-only movement branch (SicilianDefense / Knight Time)."""
    flags = coerce_search_flags(flags)
    if active_mask is None:
        active_mask = graph_ctx.active_mask if graph_ctx else sum(
            1 << i for i in _active_indices(board)
        )
    last_tile = board.get_by_index(cell_id)
    allies = flag_test(flags, FLAG_CHESS_ALLIES_CAN_TAKE)
    horizontal_wrap = flag_test(flags, FLAG_HORIZONTAL_WRAP)
    mask = 0
    if last_tile.color == TileColor.WHITE:
        mask |= _white_portal_mask(board, cell_id, visited_mask, active_mask=active_mask)
    if flag_test(flags, FLAG_DOUBLE_LETTER_TELEPORT):
        mask |= _double_letter_teleport_mask(
            board, cell_id, visited_mask, graph_ctx=graph_ctx
        )
    if is_chess_piece(last_tile) and chess_side_known(last_tile):
        mask |= knight_neighbors_mask(
            board,
            cell_id,
            visited_mask,
            moving_side=chess_side(last_tile),
            allies_can_take=allies,
            graph_ctx=graph_ctx,
            horizontal_wrap=horizontal_wrap,
        )
    else:
        mask |= _sicilian_letter_knight_land_mask(
            board,
            cell_id,
            visited_mask,
            horizontal_wrap=horizontal_wrap,
            active_mask=active_mask,
            allies_can_take=allies,
            graph_ctx=graph_ctx,
        )
    if last_tile.curse == CurseType.CHESS_KING and chess_side_known(last_tile):
        mask &= ~_sicilian_king_threat_mask(
            board,
            cell_id,
            visited_mask=visited_mask,
            active_mask=active_mask,
            horizontal_wrap=horizontal_wrap,
            graph_ctx=graph_ctx,
        )
    if flag_test(flags, FLAG_CHESS_KING_QUEEN_ITEM_MOVEMENT) and last_tile.curse in (
        CurseType.CHESS_KING,
        CurseType.CHESS_PAWN,
    ):
        item_mask = graph_ctx.item_mask if graph_ctx else 0
        if item_mask:
            mask |= _television_item_neighbors_mask(
                visited_mask,
                item_mask=item_mask,
                active_mask=active_mask,
            )
    return mask


def neighbors_mask_for_quest(
    board: Board,
    visited_mask: int,
    *,
    cell_id: int,
    flags: SearchFlagsMask,
    graph_ctx: BoardGraphContext | None,
    loadout: Loadout | None,
    standard_mask: int,
) -> int:
    if not sicilian_defense_active(loadout):
        return standard_mask
    return sicilian_neighbors_mask(
        board,
        cell_id,
        visited_mask,
        flags=flags,
        graph_ctx=graph_ctx,
    )
