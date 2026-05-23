"""Achievement unlock sticker scoring."""

from cursed_words_solver.models import (
    Board,
    CurseType,
    Loadout,
    LoadoutItem,
    Tile,
    TileColor,
)
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.rule_lookup import count_scoring_items, get_rule, slugify_name

ACHIEVEMENT_STICKER_NAMES = [
    "Arrivals",
    "Axe",
    "Baby Bottle",
    "Brick",
    "Candle",
    "Castle",
    "Champagne",
    "Circus Tent",
    "Cocktail",
    "Coin Purse",
    "Confetti",
    "Creaky Chair",
    "Crystal Ball",
    "Cursed VHS",
    "Dagger",
    "Dancer",
    "Departures",
    "Diving Mask",
    "Down Under",
    "Fireworks",
    "Footprints",
    "Gold Fish",
    "Kangaroo",
    "Las Vegas",
    "Lollipop",
    "Newspaper",
    "Onigiri",
    "Overhand",
    "Parrot",
    "Postbox",
    "Radio",
    "Rex",
    "Roller Skate",
    "Rolodex",
    "Scissors",
    "Shield",
    "Snapshot",
    "Snowman",
    "Sticky Plaster",
    "Storm Cloud",
    "Under Construction",
    "Wriggly Worm",
]

GRID_ONLY_SLUGS = {
    "brick",
    "candle",
    "castle",
    "champagne",
    "coin_purse",
    "cursed_vhs",
    "dancer",
    "diving_mask",
    "fireworks",
    "gold_fish",
    "overhand",
    "radio",
    "rex",
    "roller_skate",
    "rolodex",
    "snapshot",
    "snowman",
    "sticky_plaster",
    "storm_cloud",
}


def _tile(
    row: int,
    col: int,
    ch: str,
    score: int,
    *,
    color=TileColor.COLORLESS,
    curse=CurseType.LETTER,
    metadata=None,
) -> Tile:
    meta = {"source": "melmod"}
    if metadata:
        meta.update(metadata)
    return Tile(
        row=row,
        col=col,
        char=ch,
        letter=ch,
        base_score=score,
        color=color,
        curse=curse,
        metadata=meta,
    )


def _card(row: int, col: int, rank: str, suit: str) -> Tile:
    return _tile(
        row,
        col,
        rank,
        2,
        curse=CurseType.CARD,
        metadata={"card_suit": suit, "card_rank": rank},
    )


def _empty_board() -> Board:
    grid = [[_tile(r, c, "X", 1) for c in range(5)] for r in range(5)]
    return Board(tiles=grid, money=0)


def test_all_achievement_stickers_catalogued():
    pipeline = ScoringPipeline()
    for name in ACHIEVEMENT_STICKER_NAMES:
        slug = slugify_name(name)
        _key, rule = get_rule(pipeline.rules, "stickers", slug, name)
        assert rule is not None, slug
        assert rule.get("type") != "unmodeled", slug


def test_count_scoring_vs_grid_only_achievement():
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[
            LoadoutItem(id=slugify_name(n), name=n, level=1, kind="sticker")
            for n in ACHIEVEMENT_STICKER_NAMES
        ]
    )
    scoring, total, grid_only = count_scoring_items(pipeline.rules, loadout)
    assert total == 42
    assert grid_only == len(GRID_ONLY_SLUGS)
    assert scoring == 42 - len(GRID_ONLY_SLUGS)


def test_arrivals_first_slot_multiplier():
    board = _empty_board()
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="arrivals", name="Arrivals", level=1)])
    score, bd = pipeline.score(board, [0], "x", loadout)
    base, _ = pipeline.score(board, [0], "x", Loadout())
    assert bd["multiplier"] == 1.5
    assert score == int(base * 1.5)


def test_departures_last_slot_bonus():
    board = _empty_board()
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="departures", name="Departures", level=1)])
    score, _ = pipeline.score(board, [0], "x", loadout)
    base, _ = pipeline.score(board, [0], "x", Loadout())
    assert score == base + 100


def test_axe_short_word_multiplier():
    board = _empty_board()
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="axe", name="Axe", level=1)])
    score, bd = pipeline.score(board, [0, 1, 2], "abc", loadout)
    base, _ = pipeline.score(board, [0, 1, 2], "abc", Loadout())
    assert bd["multiplier"] == 1.5
    assert score == int(base * 1.5)


def test_circus_tent_three_colours():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "R", 1, color=TileColor.RED)
    board.tiles[0][1] = _tile(0, 1, "B", 1, color=TileColor.BLUE)
    board.tiles[0][2] = _tile(0, 2, "C", 1, color=TileColor.COLORLESS)
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="circus_tent", name="Circus Tent", level=1)])
    score, bd = pipeline.score(board, [0, 1, 2], "rbc", loadout)
    base, _ = pipeline.score(board, [0, 1, 2], "rbc", Loadout())
    assert bd["multiplier"] == 1.5
    assert score == int(base * 1.5)


def test_postbox_uncursed_word():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 1)
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="postbox", name="Postbox", level=1)])
    score, bd = pipeline.score(board, [0], "a", loadout)
    base, _ = pipeline.score(board, [0], "a", Loadout())
    assert bd["multiplier"] == 2.0
    assert score == base * 2


def test_newspaper_colourless_word():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 1, color=TileColor.COLORLESS)
    board.tiles[0][1] = _tile(0, 1, "B", 1, color=TileColor.COLORLESS)
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="newspaper", name="Newspaper", level=1)])
    score, bd = pipeline.score(board, [0, 1], "ab", loadout)
    base, _ = pipeline.score(board, [0, 1], "ab", Loadout())
    assert bd["multiplier"] == 1.5
    assert score == int(base * 1.5)


def test_onigiri_colourless_flat_bonus():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 1, color=TileColor.COLORLESS)
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="onigiri", name="Onigiri", level=1)])
    score, _ = pipeline.score(board, [0], "a", loadout)
    base, _ = pipeline.score(board, [0], "a", Loadout())
    assert score == base + 20


def test_parrot_colourless_per_coloured_on_grid():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 1, color=TileColor.COLORLESS)
    board.tiles[0][1] = _tile(0, 1, "R", 1, color=TileColor.RED)
    board.tiles[1][0] = _tile(1, 0, "B", 1, color=TileColor.BLUE)
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="parrot", name="Parrot", level=1)])
    score, _ = pipeline.score(board, [0], "a", loadout)
    base, _ = pipeline.score(board, [0], "a", Loadout())
    assert score == base + 16


def test_dagger_king_take_bonus():
    board = _empty_board()
    board.tiles[0][0] = _tile(
        0,
        0,
        "K",
        5,
        color=TileColor.RED,
        curse=CurseType.CHESS_KING,
        metadata={"take": True},
    )
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="dagger", name="Dagger", level=1)])
    score, _ = pipeline.score(board, [0], "k", loadout)
    base, _ = pipeline.score(board, [0], "k", Loadout())
    assert score == base + 50


def test_las_vegas_two_suits():
    board = _empty_board()
    board.tiles[0][0] = _card(0, 0, "2", "hearts")
    board.tiles[0][1] = _card(0, 1, "3", "clubs")
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="las_vegas", name="Las Vegas", level=1)])
    score, bd = pipeline.score(board, [0, 1], "23", loadout)
    base, _ = pipeline.score(board, [0, 1], "23", Loadout())
    assert bd["multiplier"] == 2.0
    assert score == base * 2


def test_scissors_one_pair_multiplier():
    board = _empty_board()
    board.tiles[0][0] = _card(0, 0, "2", "hearts")
    board.tiles[0][1] = _card(0, 1, "2", "clubs")
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="scissors", name="Scissors", level=1)])
    score, bd = pipeline.score(board, [0, 1], "22", loadout)
    base, _ = pipeline.score(board, [0, 1], "22", Loadout())
    assert bd["multiplier"] == 1.25
    assert abs(score - base * 1.25) < 0.01


def test_down_under_negative_tile_mult():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 2)
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="down_under", name="Down Under", level=1)])
    score, bd = pipeline.score(board, [0], "a", loadout)
    base, _ = pipeline.score(board, [0], "a", Loadout())
    assert bd["pipeline"]["tile_scores"][0] == base * -3
    assert score == base * -3


def test_shield_blue_base_override():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 1, color=TileColor.BLUE)
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="shield", name="Shield", level=1)])
    score, bd = pipeline.score(board, [0], "a", loadout)
    base, _ = pipeline.score(board, [0], "a", Loadout())
    assert bd["base_total"] == 10
    assert score == 10


def test_crystal_ball_wildcard_bonus():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "?", 1, curse=CurseType.WILDCARD)
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[LoadoutItem(id="crystal_ball", name="Crystal Ball", level=1)],
        extras={"target_curse_type": "wildcard"},
    )
    score, _ = pipeline.score(board, [0], "?", loadout)
    base, _ = pipeline.score(board, [0], "?", Loadout())
    assert score == base + 70


def test_lollipop_restock_bonus():
    board = _empty_board()
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[LoadoutItem(id="lollipop", name="Lollipop", level=1)],
        extras={"shop_restock_count": "3"},
    )
    score, _ = pipeline.score(board, [0], "x", loadout)
    base, _ = pipeline.score(board, [0], "x", Loadout())
    assert score == base + 15


def test_candle_grid_scatter_catalog():
    pipeline = ScoringPipeline()
    _key, rule = get_rule(pipeline.rules, "stickers", "candle", "Candle")
    assert rule.get("effect_class") == "scatter"
