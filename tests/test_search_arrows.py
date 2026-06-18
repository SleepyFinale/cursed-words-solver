"""Arrow tile movement in word search."""

from __future__ import annotations

from cursed_words_solver.arrow_tiles import (
    arrow_ray_target_mask,
    build_arrow_target_masks,
)
from cursed_words_solver.graph_bitboard import build_board_graph_context, index_of
from cursed_words_solver.models import Board, CurseType, Tile, TileColor
from cursed_words_solver.search import neighbors_mask
from cursed_words_solver.rules.stamp_behaviors import FLAG_HORIZONTAL_WRAP


def _board_from_tiles(specs: list[tuple[int, int, str, str]]) -> Board:
    """(row, col, letter/char, curse) per active tile; others inactive."""
    tiles: list[list[Tile]] = [
        [
            Tile(r, c, ".", ".", 0, TileColor.COLORLESS, CurseType.LETTER)
            for c in range(5)
        ]
        for r in range(5)
    ]
    active = [False] * 25
    for row, col, ch, curse in specs:
        ct = CurseType.ARROW if curse == "arrow" else CurseType.LETTER
        tiles[row][col] = Tile(row, col, ch, ch, 1, TileColor.COLORLESS, ct)
        active[row * 5 + col] = True
    return Board(tiles=tiles, active=active)


def test_arrow_right_points_along_row() -> None:
  # row 2: C → → D  (arrow at col 1 points right to col 2,3,4...)
  board = _board_from_tiles(
    [
      (2, 0, "c", "letter"),
      (2, 1, "→", "arrow"),
      (2, 2, "a", "letter"),
      (2, 3, "t", "letter"),
    ]
  )
  graph = build_board_graph_context(board)
  arrow_idx = index_of(2, 1)
  assert graph.arrow_mask & (1 << arrow_idx)
  visited = 1 << arrow_idx
  nbrs = neighbors_mask(
    board, visited, cell_id=arrow_idx, graph_ctx=graph
  )
  assert index_of(2, 2) in [i for i in range(25) if nbrs & (1 << i)]
  assert index_of(2, 0) not in [i for i in range(25) if nbrs & (1 << i)]


def test_arrow_does_not_use_standard_adjacency() -> None:
  board = _board_from_tiles(
    [
      (1, 1, "→", "arrow"),
      (1, 2, "a", "letter"),
      (0, 1, "b", "letter"),
    ]
  )
  graph = build_board_graph_context(board)
  arrow_idx = index_of(1, 1)
  visited = 1 << arrow_idx
  nbrs = neighbors_mask(board, visited, cell_id=arrow_idx, graph_ctx=graph)
  assert not (nbrs & (1 << index_of(0, 1)))


def test_arrow_ray_collects_multiple_tiles() -> None:
  active = 0
  for r, c in ((2, 2), (2, 3), (2, 4)):
    active |= 1 << index_of(r, c)
  mask = arrow_ray_target_mask(
    index_of(2, 1), (1, 0), active, horizontal_wrap=False
  )
  assert mask & (1 << index_of(2, 2))
  assert mask & (1 << index_of(2, 3))
  assert mask & (1 << index_of(2, 4))


def test_build_arrow_target_masks_precomputed() -> None:
  board = _board_from_tiles([(2, 1, "→", "arrow"), (2, 3, "x", "letter")])
  active = sum(1 << index_of(r, c) for r, c in ((2, 1), (2, 3)))
  arrow_mask, base, wrap = build_arrow_target_masks(board, active)
  assert arrow_mask & (1 << index_of(2, 1))
  assert base[index_of(2, 1)] & (1 << index_of(2, 3))


def test_arrow_hungry_snake_wrap_ray() -> None:
    # Arrow at col 4 pointing right: next step off-grid wraps to col 0 (Hungry Snake).
    board = _board_from_tiles(
        [
            (2, 4, "→", "arrow"),
            (2, 0, "z", "letter"),
        ]
    )
    graph = build_board_graph_context(board)
    arrow_idx = index_of(2, 4)
    visited = 1 << arrow_idx
    nbrs = neighbors_mask(
        board,
        visited,
        cell_id=arrow_idx,
        flags=FLAG_HORIZONTAL_WRAP,
        graph_ctx=graph,
    )
    assert nbrs & (1 << index_of(2, 0))
