"""Tests for game-accurate scoring order helpers."""

from cursed_words_solver.models import Board, CurseType, Loadout, LoadoutItem, Tile, TileColor
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.scoring_order import (
    build_scoring_item_sequence,
    hourglass_reverses_order,
)


def _tile(row: int, col: int, ch: str, score: int, **kwargs) -> Tile:
    return Tile(row=row, col=col, char=ch, letter=ch, base_score=score, **kwargs)


def test_hourglass_reverses_inventory_order():
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[LoadoutItem(id="a", name="A", level=1)],
        stamps=[LoadoutItem(id="hourglass", name="Hourglass", kind="stamp")],
        extras={"hourglass_count": "1"},
    )
    assert hourglass_reverses_order(loadout, pipeline.rules)
    loadout2 = Loadout(
        stickers=[
            LoadoutItem(id="brain", name="Brain", level=1),
            LoadoutItem(id="chips", name="Chips", level=1),
        ],
        extras={"hourglass_count": "1"},
    )
    board = Board(tiles=[[_tile(0, c, "A", 1) for c in range(5)]] * 5)
    seq = build_scoring_item_sequence(board, [0], loadout2, pipeline.rules)
    assert [r.rule_id for r in seq if r.kind == "sticker"] == ["chips", "brain"]


def test_green_tile_transfers_to_word_score():
    board = Board(
        tiles=[
            [
                _tile(0, 0, "A", 3, color=TileColor.GREEN),
                _tile(0, 1, "B", 2, color=TileColor.RED),
            ]
            + [_tile(0, c, "T", 1) for c in range(2, 5)]
        ]
        + [[_tile(r, c, "T", 1) for c in range(5)] for r in range(1, 5)]
    )
    pipeline = ScoringPipeline()
    score, bd = pipeline.score(board, [0, 1], "ab", Loadout())
    p = bd["pipeline"]
    assert score == p["word_score"] + sum(p["tile_scores"])


def test_frankenstein_stitch_expands_in_sequence():
    pipeline = ScoringPipeline()
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
