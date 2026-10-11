"""Setup-aware search ranking prefers investment words when configured."""

from __future__ import annotations

from cursed_words_solver.models import Board, CurseType, Loadout, Tile, TileColor
from cursed_words_solver.setup_value import project_setup_delta


def _tile(row: int, col: int, ch: str, score: float, *, number: float | None = None) -> Tile:
    curse = CurseType.NUMBER if number is not None else CurseType.LETTER
    return Tile(
        row=row,
        col=col,
        char=ch,
        letter=ch,
        base_score=score,
        color=TileColor.VOID if number else TileColor.SHINY,
        curse=curse,
        number_value=int(number) if number is not None else None,
    )


def _board_with_high_number() -> Board:
    grid = [[_tile(r, c, "A", 1) for c in range(5)] for r in range(5)]
    grid[2][2] = _tile(2, 2, "9", 9, number=9.0)
    grid[2][3] = _tile(2, 3, "E", 1)
    grid[2][4] = _tile(2, 4, "T", 1)
    return Board(tiles=grid, money=0)


def test_project_tile_ninja_stamp_absent_without_stamp():
    grid = [[_tile(r, c, "A", 1) for c in range(5)] for r in range(5)]
    grid[0][0] = Tile(0, 0, "G", "G", 1, metadata={"consumable": True})
    board = Board(tiles=grid, money=0)
    loadout = Loadout(extras={"grids_remaining": "3"})
    delta = project_setup_delta(board, [0], "g", loadout)
    assert delta.tile_ninja_bonus == 0.0
