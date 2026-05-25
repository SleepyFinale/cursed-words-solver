"""Frankenstein stitch and Overhand replay orchestration."""

from cursed_words_solver.models import Board, CurseType, Loadout, LoadoutItem, Tile, TileColor
from cursed_words_solver.rules.pipeline import ScoringPipeline


def _tile(row: int, col: int, ch: str = "A", score: int = 1, **kwargs) -> Tile:
    return Tile(
        row=row,
        col=col,
        char=ch,
        letter=ch,
        base_score=score,
        color=kwargs.get("color", TileColor.COLORLESS),
        curse=kwargs.get("curse", CurseType.LETTER),
        number_value=kwargs.get("number_value"),
        metadata=kwargs.get("metadata", {}),
    )


def _board() -> Board:
    return Board(tiles=[[_tile(r, c) for c in range(5)] for r in range(5)], money=0)


def test_frankenstein_replays_stitched_sticker():
    pipeline = ScoringPipeline()
    grid = [[_tile(r, c) for c in range(5)] for r in range(5)]
    grid[0][0] = _tile(0, 0, "4", 4, curse=CurseType.NUMBER, number_value=4)
    grid[0][1] = _tile(0, 1, "5", 5, curse=CurseType.NUMBER, number_value=5)
    grid[0][2] = _tile(0, 2, "6", 6, curse=CurseType.NUMBER, number_value=6)
    board = Board(tiles=grid, money=0)
    lo = Loadout(
        stickers=[
            LoadoutItem(id="frankenstein", name="Frankenstein", level=1, kind="sticker"),
            LoadoutItem(id="brain", name="Brain", level=1, kind="sticker"),
        ],
        extras={"stitched_sticker_ids": ["brain"]},
    )
    score, bd = pipeline.score(board, [0, 1, 2], "456", lo)
    effects = bd["pipeline"]["effects"]
    assert any("Frankenstein" in e or "brain" in e.lower() for e in effects)
    assert score > 3.0


def test_overhand_replays_stamp_at_matching_slot():
    pipeline = ScoringPipeline()
    board = _board()
    lo = Loadout(
        stickers=[LoadoutItem(id="overhand", name="Overhand", level=2, kind="sticker")],
        stamps=[LoadoutItem(id="avocado", name="Avocado", kind="stamp")],
        extras={"overhand_level": 2},
    )
    score, bd = pipeline.score(board, [0, 1, 2], "aaa", lo)
    assert any("Overhand" in e for e in bd["pipeline"]["effects"])
    assert score > 3.0
