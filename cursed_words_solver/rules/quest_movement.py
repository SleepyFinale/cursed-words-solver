"""Quest movement overrides (SicilianDefense / Knight Time)."""

from __future__ import annotations

from cursed_words_solver.graph_bitboard import (
    KNIGHT_TARGETS,
    BoardGraphContext,
    get_valid_extensions,
    iter_mask,
)
from cursed_words_solver.models import Board, CurseType, TileColor
from cursed_words_solver.rules.chess_tiles import (
    _television_item_neighbors_mask,
)
from cursed_words_solver.rules.quest_effects import quest_constraints
from cursed_words_solver.models import Loadout
from cursed_words_solver.rules.stamp_behaviors import (
    FLAG_CHESS_KING_QUEEN_ITEM_MOVEMENT,
    FLAG_DOUBLE_LETTER_TELEPORT,
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

_NEIGHBOR_SCRATCH: list[int] = [0] * 25


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
    mask = 0
    if last_tile.color == TileColor.WHITE:
        mask |= _white_portal_mask(board, cell_id, visited_mask, active_mask=active_mask)
    if flag_test(flags, FLAG_DOUBLE_LETTER_TELEPORT):
        mask |= _double_letter_teleport_mask(
            board, cell_id, visited_mask, graph_ctx=graph_ctx
        )
    mask |= KNIGHT_TARGETS[cell_id] & active_mask & ~visited_mask
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
