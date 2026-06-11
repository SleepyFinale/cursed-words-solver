"""Lexographer zeros cursed tile scores post-items."""

from cursed_words_solver.models import Board, CurseType, Loadout, Tile, TileColor
from cursed_words_solver.rules.pipeline import ScoringPipeline


def _letter(idx: int, ch: str, *, curse=CurseType.LETTER) -> Tile:
    row, col = divmod(idx, 5)
    return Tile(
        row=row,
        col=col,
        char=ch,
        letter=ch,
        base_score=2,
        color=TileColor.COLORLESS,
        curse=curse,
    )


def test_lexographer_zeros_cursed_tiles_in_pipeline() -> None:
    path = [0, 1, 2]
    grid: list[list[Tile]] = []
    for r in range(5):
        row: list[Tile] = []
        for c in range(5):
            idx = r * 5 + c
            ch = "abc"[idx] if idx < 3 else "x"
            curse = CurseType.WILDCARD if idx == 1 else CurseType.LETTER
            row.append(_letter(idx, ch, curse=curse))
        grid.append(row)
    board = Board(tiles=grid, money=0)
    loadout = Loadout(extras={"challenge_game_class": "Lexographer"})
    state = ScoringPipeline()._compute_state(board, path, "abc", loadout)
    assert state["tile_scores"][1] == 0.0
    assert state["tile_scores"][0] != 0.0 or state["tile_scores"][2] != 0.0
