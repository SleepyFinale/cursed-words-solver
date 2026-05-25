"""Nat-H4 unlock stamp catalog and scoring (wiki: Unlocked when unlocking Nat-H4)."""

from cursed_words_solver.models import Board, Loadout, LoadoutItem, Tile, TileColor
from cursed_words_solver.rules.pipeline import ScoringPipeline
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
    pipeline = ScoringPipeline()
    for name in NAT_H4_STAMP_NAMES:
        slug = slugify_name(name)
        _key, rule = get_rule(pipeline.rules, "stamps", slug, name)
        assert rule is not None, slug
        assert rule.get("type") != "unmodeled", slug


def test_count_scoring_vs_grid_only_nat_h4_stamps():
    pipeline = ScoringPipeline()
    assert_loadout_stamp_coverage(pipeline.rules, NAT_H4_STAMP_NAMES)



def test_delivery_truck_shop_effect():
    pipeline = ScoringPipeline()
    _key, rule = get_rule(pipeline.rules, "stamps", "delivery_truck", "Delivery Truck")
    assert rule.get("effect_class") == "shop"


def test_filing_cabinet_grid_scatter():
    pipeline = ScoringPipeline()
    _key, rule = get_rule(pipeline.rules, "stamps", "filing_cabinet", "Filing Cabinet")
    assert rule.get("effect_class") == "scatter"


def test_steak_rare_items_increase_multiplier():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 10)
    board.tiles[0][1] = _tile(0, 1, "B", 10)
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stamps=[LoadoutItem(id="steak", name="Steak", kind="stamp")],
        extras={"rare_item_count": "2"},
    )
    score, bd = pipeline.score(board, [0, 1], "ab", loadout)
    assert bd["multiplier"] == 3.0
    assert score == 60


def test_steak_no_rare_items_base_multiplier():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 10)
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stamps=[LoadoutItem(id="steak", name="Steak", kind="stamp")],
        extras={"rare_item_count": "0"},
    )
    score, bd = pipeline.score(board, [0], "a", loadout)
    base, _ = pipeline.score(board, [0], "a", Loadout())
    assert bd["multiplier"] == 1.0
    assert score == base
