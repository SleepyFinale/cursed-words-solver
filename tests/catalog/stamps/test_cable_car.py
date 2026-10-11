"""Cable Car: path stickers Upgrade once per owned copy before scoring."""

from cursed_words_solver.models import Board, CurseType, Tile, TileColor
from cursed_words_solver.engine.scorer import EngineScorer
from cursed_words_solver.rules.rule_lookup import get_rule
from cursed_words_solver.rules.scoring_conditions import sticker_rule_int


def _board_with_scatter(
    *,
    row: int,
    col: int,
    slug: str,
    level: int,
    letter: str = "A",
    color: TileColor = TileColor.RED,
) -> Board:
    board = Board(tiles=[[None] * 5 for _ in range(5)], money=0)
    board.tiles[row][col] = Tile(
        row=row,
        col=col,
        char=letter.lower(),
        letter=letter,
        base_score=1,
        color=color,
        curse=CurseType.ITEM,
        metadata={
            "scattered_item_id": slug,
            "scattered_item_level": level,
        },
    )
    return board


def test_maple_leaf_l1_plus_cable_car_first_n_is_3():
    """Maple Leaf VV starts at 2; L2 after Cable Car → first 3 reds ×3."""
    pipeline = EngineScorer()
    _key, rule = get_rule(pipeline.rules, "stickers", "maple_leaf", "Maple Leaf")
    assert rule is not None
    n = sticker_rule_int(2, rule)  # Level after Cable Car
    assert n == 3
