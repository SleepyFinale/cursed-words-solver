"""Bones The Dog unlock stamp catalog and behavior (wiki: Unlocked when unlocking Bones The Dog)."""

from cursed_words_solver.models import Board, CurseType, Tile
from cursed_words_solver.engine.scorer import EngineScorer
from cursed_words_solver.rules.rule_lookup import get_rule, slugify_name

from tests.catalog.stamps._coverage import assert_loadout_stamp_coverage

BONES_STAMP_NAMES = [
    "Card Shark",
    "Martini",
    "Four Leaf Clover",
    "Go Fish!",
    "Magician's Hat",
    "Smart Shirt",
    "Valentine's Day Card",
]

GRID_ONLY_SLUGS = {
    "card_shark",
    "four_leaf_clover",
    "go_fish",
    "magician_s_hat",
    "smart_shirt",
    "valentine_s_day_card",
}


def _card(row: int, col: int, rank: str, suit: str, score: int = 2) -> Tile:
    return Tile(
        row=row,
        col=col,
        char=rank,
        letter=rank,
        base_score=score,
        curse=CurseType.CARD,
        metadata={"source": "melmod", "card_suit": suit, "card_rank": rank},
    )


def _letter(row: int, col: int, ch: str, score: int = 1) -> Tile:
    return Tile(
        row=row,
        col=col,
        char=ch,
        letter=ch,
        base_score=score,
        metadata={"source": "melmod"},
    )


def _empty_board() -> Board:
    grid = [[_letter(r, c, "X", 1) for c in range(5)] for r in range(5)]
    return Board(tiles=grid, money=0)


def test_all_bones_stamps_catalogued():
    pipeline = EngineScorer()
    for name in BONES_STAMP_NAMES:
        slug = slugify_name(name)
        _key, rule = get_rule(pipeline.rules, "stamps", slug, name)
        assert rule is not None, slug
        assert rule.get("type") != "unmodeled", slug


def test_count_scoring_vs_grid_only_bones_stamps():
    pipeline = EngineScorer()
    assert_loadout_stamp_coverage(pipeline.rules, BONES_STAMP_NAMES)
