"""PURPLE tiles count as RED and BLUE for sticker conditions."""

from __future__ import annotations

from cursed_words_solver.models import Board, CurseType, Tile, TileColor, tile_counts_as_color
from cursed_words_solver.rules.scoring_conditions import (
    count_color_on_path,
    has_blue_red_and_colourless_on_path,
    tile_matches_target,
)


def _purple_tile(idx: int = 0) -> Tile:
    r, c = divmod(idx, 5)
    return Tile(r, c, "A", "A", 1, TileColor.PURPLE, CurseType.LETTER)


def test_tile_counts_as_red_and_blue() -> None:
    t = _purple_tile()
    assert tile_counts_as_color(t, TileColor.RED)
    assert tile_counts_as_color(t, TileColor.BLUE)
    assert not tile_counts_as_color(t, TileColor.GREEN)


def test_tile_matches_target_red_blue() -> None:
    t = _purple_tile()
    assert tile_matches_target(t, "red")
    assert tile_matches_target(t, "blue")


def test_count_color_on_path_purple_as_red() -> None:
    board = Board(tiles=[[_purple_tile(0)]])
    assert count_color_on_path(board, [0], "red") == 1
    assert count_color_on_path(board, [0], "blue") == 1


def test_has_blue_red_and_colourless_with_purple() -> None:
    tiles = [
        [
            _purple_tile(0),
            Tile(0, 1, "B", "B", 1, TileColor.COLORLESS, CurseType.LETTER),
        ]
    ]
    board = Board(tiles=tiles)
    assert has_blue_red_and_colourless_on_path(board, [0, 1])
