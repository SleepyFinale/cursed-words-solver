"""Arrow tile movement in word search."""

from __future__ import annotations

from cursed_words_solver.arrow_tiles import (
    arrow_ray_target_mask,
    build_arrow_target_masks,
)
from cursed_words_solver.graph_bitboard import build_board_graph_context, index_of
from cursed_words_solver.models import Board, CurseType, Tile, TileColor
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


def test_arrow_ray_collects_multiple_tiles() -> None:
  active = 0
  for r, c in ((2, 2), (2, 3), (2, 4)):
    active |= 1 << index_of(r, c)
  mask = arrow_ray_target_mask(
    index_of(2, 1), (1, 0), active, rows=5, cols=5, horizontal_wrap=False
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
