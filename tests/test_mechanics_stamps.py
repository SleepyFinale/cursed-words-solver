"""Created-by-other-mechanics stamp catalog (Padlock stamp, Right Hand)."""

from cursed_words_solver.models import Board, Loadout, LoadoutItem, Tile, TileColor
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.rule_lookup import count_scoring_items, get_rule, slugify_name

MECHANICS_STAMP_NAMES = [
    "Padlock (stamp)",
    "Right Hand",
]

GRID_ONLY_SLUGS = {
    "padlock_stamp",
    "right_hand",
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


def test_all_mechanics_stamps_catalogued():
    pipeline = ScoringPipeline()
    for name in MECHANICS_STAMP_NAMES:
        slug = slugify_name(name)
        _key, rule = get_rule(pipeline.rules, "stamps", slug, name)
        assert rule is not None, slug
        assert rule.get("type") != "unmodeled", slug


def test_count_scoring_vs_grid_only_mechanics_stamps():
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stamps=[
            LoadoutItem(id=slugify_name(n), name=n, level=1, kind="stamp")
            for n in MECHANICS_STAMP_NAMES
        ]
    )
    scoring, total, grid_only = count_scoring_items(pipeline.rules, loadout)
    assert total == 2
    assert grid_only == len(GRID_ONLY_SLUGS)
    assert scoring == 0


def test_padlock_stamp_sell_cost_metadata():
    pipeline = ScoringPipeline()
    _key, rule = get_rule(pipeline.rules, "stamps", "padlock_stamp", "Padlock (stamp)")
    assert rule.get("effect_class") == "sell_cost"
    assert rule.get("sell_price_base") == 8
    assert rule.get("sell_price_upgrade") == 8
    assert rule.get("unique") is True
    assert "shop_price" not in rule


def test_right_hand_meta_for_human_hands():
    pipeline = ScoringPipeline()
    _key, rule = get_rule(pipeline.rules, "stamps", "right_hand", "Right Hand")
    assert rule.get("effect_class") == "meta"
    assert rule.get("unique") is True
    assert "favourite" in rule.get("wiki_effect", "").lower()
