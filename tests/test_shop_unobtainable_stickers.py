"""Cannot-be-obtained-from-shop sticker scoring and catalog."""

from cursed_words_solver.models import Board, Loadout, LoadoutItem, Tile, TileColor
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.rule_lookup import count_scoring_items, get_rule, slugify_name

SHOP_UNOBTAINABLE_NAMES = [
    "Bone",
    "Frankenstein",
    "Left Hand",
    "Padlock (sticker)",
]

CATALOG_ONLY_SLUGS = {
    "frankenstein",
    "left_hand",
    "padlock_sticker",
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


def test_all_shop_unobtainable_catalogued():
    pipeline = ScoringPipeline()
    for name in SHOP_UNOBTAINABLE_NAMES:
        slug = slugify_name(name)
        _key, rule = get_rule(pipeline.rules, "stickers", slug, name)
        assert rule is not None, slug
        assert rule.get("type") != "unmodeled", slug


def test_count_scoring_vs_catalog():
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[
            LoadoutItem(id=slugify_name(n), name=n, level=1, kind="sticker")
            for n in SHOP_UNOBTAINABLE_NAMES
        ]
    )
    scoring, total, grid_only = count_scoring_items(pipeline.rules, loadout)
    assert total == 4
    assert grid_only == len(CATALOG_ONLY_SLUGS)
    assert scoring == 4 - len(CATALOG_ONLY_SLUGS)


def test_bone_multiplier_level_1():
    board = _empty_board()
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="bone", name="Bone", level=1)])
    score, bd = pipeline.score(board, [0], "x", loadout)
    base, base_bd = pipeline.score(board, [0], "x", Loadout())
    assert bd["multiplier"] == 1.5
    assert score == int(base * 1.5)  # floor after ×WORD
    assert base_bd["multiplier"] == 1.0


def test_bone_multiplier_level_3():
    board = _empty_board()
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="bone", name="Bone", level=3)])
    score, bd = pipeline.score(board, [0], "x", loadout)
    base, _ = pipeline.score(board, [0], "x", Loadout())
    assert bd["multiplier"] == 2.5
    assert score == int(base * 2.5)  # floor after ×WORD


def test_frankenstein_left_hand_padlock_catalog():
    pipeline = ScoringPipeline()
    _key, frank = get_rule(pipeline.rules, "stickers", "frankenstein", "Frankenstein")
    assert frank.get("effect_class") == "unique"
    _key, left = get_rule(pipeline.rules, "stickers", "left_hand", "Left Hand")
    assert left.get("effect_class") == "meta"
    _key, pad = get_rule(pipeline.rules, "stickers", "padlock_sticker", "Padlock (sticker)")
    assert pad.get("effect_class") == "sell_cost"
    assert pad.get("sell_price_base") == 8
    assert pad.get("sell_price_upgrade") == 8


def test_burrito_ignores_left_hand_level():
    board = _empty_board()
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[
            LoadoutItem(id="burrito", name="Burrito", level=1),
            LoadoutItem(id="left_hand", name="Left Hand", level=5),
            LoadoutItem(id="printer", name="Printer", level=2),
        ]
    )
    _score, bd = pipeline.score(board, [0], "x", loadout)
    # Burrito: 1 + 0.05 * other sticker levels (Printer L2 only; Left Hand excluded)
    assert abs(bd["multiplier"] - 1.1) < 1e-9
