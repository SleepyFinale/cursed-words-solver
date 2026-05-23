"""Nat-H4 unlock sticker scoring."""

from cursed_words_solver.models import Board, Loadout, LoadoutItem, Tile, TileColor
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.rule_lookup import count_scoring_items, get_rule, slugify_name

NAT_H4_STICKER_NAMES = [
    "Burrito",
    "Printer",
    "Retro Raider",
    "Signal Receiver",
    "Stamp Album",
    "Toolbox",
]

GRID_ONLY_SLUGS = {
    "printer",
    "retro_raider",
    "toolbox",
    "signal_receiver",
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


def test_all_nat_h4_stickers_catalogued():
    pipeline = ScoringPipeline()
    for name in NAT_H4_STICKER_NAMES:
        slug = slugify_name(name)
        _key, rule = get_rule(pipeline.rules, "stickers", slug, name)
        assert rule is not None, slug
        assert rule.get("type") != "unmodeled", slug


def test_count_scoring_vs_grid_only_nat_h4():
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[
            LoadoutItem(id=slugify_name(n), name=n, level=1, kind="sticker")
            for n in NAT_H4_STICKER_NAMES
        ]
    )
    scoring, total, grid_only = count_scoring_items(pipeline.rules, loadout)
    assert total == 6
    assert grid_only == len(GRID_ONLY_SLUGS)
    assert scoring == 6 - len(GRID_ONLY_SLUGS)


def test_grid_and_sell_stickers_catalog():
    pipeline = ScoringPipeline()
    for slug in ("printer", "retro_raider", "toolbox"):
        _key, rule = get_rule(pipeline.rules, "stickers", slug, slug)
        assert rule.get("effect_class") == "scatter"
    _key, rule = get_rule(pipeline.rules, "stickers", "signal_receiver", "Signal Receiver")
    assert rule.get("effect_class") == "sell"


def test_burrito_alone_no_multiplier():
    board = _empty_board()
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="burrito", name="Burrito", level=1)])
    score, bd = pipeline.score(board, [0], "x", loadout)
    base, base_bd = pipeline.score(board, [0], "x", Loadout())
    assert bd["multiplier"] == 1.0
    assert score == base


def test_burrito_with_other_stickers():
    board = _empty_board()
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[
            LoadoutItem(id="burrito", name="Burrito", level=1),
            LoadoutItem(id="printer", name="Printer", level=1),
            LoadoutItem(id="toolbox", name="Toolbox", level=1),
        ]
    )
    score, bd = pipeline.score(board, [0], "x", loadout)
    base, _ = pipeline.score(board, [0], "x", Loadout())
    assert bd["multiplier"] == 1.1
    assert score == int(base * 1.1)  # floor after ×WORD


def test_burrito_level2_rate():
    board = _empty_board()
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[
            LoadoutItem(id="burrito", name="Burrito", level=2),
            LoadoutItem(id="stamp_album", name="Stamp Album", level=2),
        ]
    )
    score, bd = pipeline.score(board, [0], "x", loadout)
    base, _ = pipeline.score(board, [0], "x", Loadout())
    assert bd["multiplier"] == 1.2
    assert score == int(base * 1.2)  # floor after ×WORD


def test_stamp_album_from_extras():
    board = _empty_board()
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[LoadoutItem(id="stamp_album", name="Stamp Album", level=1)],
        extras={"stamps_shop_price_total": "12"},
    )
    score, bd = pipeline.score(board, [0], "x", loadout)
    base, _ = pipeline.score(board, [0], "x", Loadout())
    assert score == base + 12
    assert any("per_stamp_shop_price" in e for e in bd["pipeline"]["effects"])


def test_stamp_album_level2_from_extras():
    board = _empty_board()
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[LoadoutItem(id="stamp_album", name="Stamp Album", level=2)],
        extras={"stamps_shop_price_total": "12"},
    )
    score, _ = pipeline.score(board, [0], "x", loadout)
    base, _ = pipeline.score(board, [0], "x", Loadout())
    assert score == base + 24


def test_stamp_album_no_stamps_no_extras():
    board = _empty_board()
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="stamp_album", name="Stamp Album", level=1)])
    score, bd = pipeline.score(board, [0], "x", loadout)
    base, _ = pipeline.score(board, [0], "x", Loadout())
    assert score == base
    assert bd["multiplier"] == 1.0


def test_stamp_album_from_catalog_stamp_prices():
    board = _empty_board()
    pipeline = ScoringPipeline()
    stamps = [
        LoadoutItem(id="newspaper", name="Newspaper", level=1, kind="stamp"),
        LoadoutItem(id="moai", name="Moai", level=1, kind="stamp"),
    ]
    with_album = Loadout(
        stickers=[LoadoutItem(id="stamp_album", name="Stamp Album", level=1)],
        stamps=stamps,
    )
    stamps_only = Loadout(stamps=stamps)
    score_album, _ = pipeline.score(board, [0], "x", with_album)
    score_stamps, _ = pipeline.score(board, [0], "x", stamps_only)
    assert score_album - score_stamps == 20
