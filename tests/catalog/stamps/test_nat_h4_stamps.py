"""Nat-H4 unlock stamp catalog and scoring (wiki: Unlocked when unlocking Nat-H4)."""

from cursed_words_solver.models import Board, Tile, TileColor
from cursed_words_solver.engine.scorer import EngineScorer
from cursed_words_solver.rules.rule_lookup import get_rule, slugify_name

from tests.catalog.stamps._coverage import assert_loadout_stamp_coverage

NAT_H4_STAMP_NAMES = [
    "Delivery Truck",
    "Filing Cabinet",
    "Steak",
]

GRID_ONLY_SLUGS = {
    "delivery_truck",
    "filing_cabinet",
}


def _tile(row: int, col: int, ch: str, score: int) -> Tile:
    return Tile(
        row=row,
        col=col,
        char=ch,
        letter=ch,
        base_score=score,
        color=TileColor.COLORLESS,
        metadata={"source": "melmod"},
    )


def _empty_board() -> Board:
    grid = [[_tile(r, c, "X", 1) for c in range(5)] for r in range(5)]
    return Board(tiles=grid, money=0)


def test_all_nat_h4_stamps_catalogued():
    pipeline = EngineScorer()
    for name in NAT_H4_STAMP_NAMES:
        slug = slugify_name(name)
        _key, rule = get_rule(pipeline.rules, "stamps", slug, name)
        assert rule is not None, slug
        assert rule.get("type") != "unmodeled", slug


def test_count_scoring_vs_grid_only_nat_h4_stamps():
    pipeline = EngineScorer()
    assert_loadout_stamp_coverage(pipeline.rules, NAT_H4_STAMP_NAMES)


def test_delivery_truck_shop_effect():
    pipeline = EngineScorer()
    _key, rule = get_rule(pipeline.rules, "stamps", "delivery_truck", "Delivery Truck")
    assert rule.get("effect_class") == "shop"


def test_filing_cabinet_grid_scatter():
    pipeline = EngineScorer()
    _key, rule = get_rule(pipeline.rules, "stamps", "filing_cabinet", "Filing Cabinet")
    assert rule.get("effect_class") == "scatter"


