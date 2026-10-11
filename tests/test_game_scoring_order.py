"""Tests for game-accurate scoring order helpers."""

from cursed_words_solver.models import Board, CurseType, Loadout, LoadoutItem, Tile, TileColor
from cursed_words_solver.engine.scorer import EngineScorer


def _tile(row: int, col: int, ch: str, score: int, **kwargs) -> Tile:
    return Tile(row=row, col=col, char=ch, letter=ch, base_score=score, **kwargs)


def _green_colorless_board() -> Board:
    return Board(
        tiles=[
            [
                _tile(0, 0, "A", 3, color=TileColor.GREEN),
                _tile(0, 1, "B", 1, color=TileColor.COLORLESS),
            ]
            + [_tile(0, c, "T", 1) for c in range(2, 5)]
        ]
        + [[_tile(r, c, "T", 1) for c in range(5)] for r in range(1, 5)]
    )


def test_green_tile_gets_word_multiplier():
    board = _green_colorless_board()
    pipeline = EngineScorer()
    loadout = Loadout(
        stickers=[LoadoutItem(id="bone", name="Bone", level=2, kind="sticker")]
    )
    score, bd = pipeline.score(board, [0, 1], "ab", loadout)
    assert score == 8
    assert bd["multiplier"] == 2.0


def test_frankenstein_stitch_expands_in_sequence():
    pipeline = EngineScorer()
    board = Board(tiles=[[_tile(0, c, "A", 1) for c in range(5)]] * 5)
    grid = board.tiles
    grid[0][0] = _tile(0, 0, "4", 4, curse=CurseType.NUMBER, number_value=4)
    grid[0][1] = _tile(0, 1, "5", 5, curse=CurseType.NUMBER, number_value=5)
    grid[0][2] = _tile(0, 2, "6", 6, curse=CurseType.NUMBER, number_value=6)
    lo = Loadout(
        stickers=[LoadoutItem(id="frankenstein", name="Frankenstein", level=1)],
        extras={"stitched_sticker_ids": ["brain"]},
    )
    score, _ = pipeline.score(board, [0, 1, 2], "456", lo)
    assert score > 15.0
