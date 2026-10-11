"""PURPLE tiles count as RED and BLUE for sticker conditions."""

from __future__ import annotations

from cursed_words_solver.models import CurseType, Tile, TileColor, tile_counts_as_color


def _purple_tile(idx: int = 0) -> Tile:
    r, c = divmod(idx, 5)
    return Tile(r, c, "A", "A", 1, TileColor.PURPLE, CurseType.LETTER)


def test_tile_counts_as_red_and_blue() -> None:
    t = _purple_tile()
    assert tile_counts_as_color(t, TileColor.RED)
    assert tile_counts_as_color(t, TileColor.BLUE)
    assert not tile_counts_as_color(t, TileColor.GREEN)
