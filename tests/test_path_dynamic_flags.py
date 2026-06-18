"""Path-scattered stamp flags during DFS."""

from __future__ import annotations

from cursed_words_solver.models import Board, CurseType, Tile, TileColor
from cursed_words_solver.rules.stamp_behaviors import (
    FLAG_HORIZONTAL_WRAP,
    path_scattered_search_flags_mask,
    stamp_search_flags_mask,
)
from cursed_words_solver.search import neighbors_mask
from cursed_words_solver.graph_bitboard import build_board_graph_context, index_of


def _tile(
    row: int,
    col: int,
    *,
    curse: CurseType = CurseType.LETTER,
    ch: str = "a",
    scattered_id: str | None = None,
) -> Tile:
    meta = {"scattered_item_id": scattered_id} if scattered_id else {}
    return Tile(row, col, ch, ch, 1, TileColor.COLORLESS, curse, metadata=meta)


def test_scattered_hungry_snake_enables_wrap_on_path() -> None:
    tiles = [
        [_tile(r, c) for c in range(5)]
        for r in range(5)
    ]
    tiles[2][0] = _tile(2, 0, curse=CurseType.ITEM, scattered_id="hungry_snake")
    tiles[2][4] = _tile(2, 4, ch="z")
    board = Board(tiles=tiles)
    path = [index_of(2, 0), index_of(2, 1)]
    base = stamp_search_flags_mask(None)
    flags = path_scattered_search_flags_mask(board, path, base)
    assert flag_test_wrap(flags)


def flag_test_wrap(mask: int) -> bool:
    return bool(mask & FLAG_HORIZONTAL_WRAP)


def test_neighbors_use_path_scattered_snake_wrap() -> None:
    tiles = [
        [_tile(r, c) for c in range(5)]
        for r in range(5)
    ]
    tiles[2][0] = _tile(2, 0, curse=CurseType.ITEM, scattered_id="hungry_snake")
    tiles[2][4] = _tile(2, 4, ch="z")
    board = Board(tiles=tiles)
    graph = build_board_graph_context(board)
    path = [index_of(2, 0)]
    flags = path_scattered_search_flags_mask(board, path, 0)
    nbrs = neighbors_mask(
        board,
        1 << path[0],
        cell_id=path[0],
        flags=flags,
        graph_ctx=graph,
    )
    # From col 0 with wrap, can reach col 4 on same row.
    assert nbrs & (1 << index_of(2, 4))
