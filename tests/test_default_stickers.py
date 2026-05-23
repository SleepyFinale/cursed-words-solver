"""Default-unlocked sticker scoring (wiki: Unlocked by default)."""

from cursed_words_solver.models import (
    Board,
    CurseType,
    Loadout,
    LoadoutItem,
    Tile,
    TileColor,
)
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.rule_lookup import count_scoring_items, slugify_name

DEFAULT_STICKER_NAMES = [
    "April Shower",
    "Artist's Palette",
    "Blueberries",
    "Chequered Flag",
    "Cherries",
    "Cherry Pie",
    "Chips",
    "Credit Card",
    "Dusty Coffin",
    "Egg",
    "Electric Guitar",
    "Fire Extinguisher",
    "Fountain",
    "Glass Of Milk",
    "Graduation Cap",
    "Ham Sandwich",
    "Hi Vis Jacket",
    "Lipstick",
    "Lucky Scarf",
    "Magic Wand",
    "Maple Leaf",
    "Ornate Key",
    "Pair Of Socks",
    "Pneumonia",
    "Sequoia Sapling",
    "Sly Spy",
    "Stilton",
    "Sunflower",
    "Telescope",
    "Wheezy Vixen",
    "Worn-out Jeans",
    "Yellow Glasses",
]

GRID_ONLY_SLUGS = {
    "april_shower",
    "cherries",
    "fountain",
    "lipstick",
    "magic_wand",
    "worn_out_jeans",
}


def _tile(
    row: int,
    col: int,
    ch: str,
    score: int,
    *,
    color=TileColor.COLORLESS,
    curse=CurseType.LETTER,
) -> Tile:
    return Tile(
        row=row,
        col=col,
        char=ch,
        letter=ch,
        base_score=score,
        color=color,
        curse=curse,
        metadata={"source": "melmod"},
    )


def _empty_board() -> Board:
    grid = [[_tile(r, c, "X", 1) for c in range(5)] for r in range(5)]
    return Board(tiles=grid, money=0)


def test_all_default_stickers_catalogued():
    from cursed_words_solver.rules.rule_lookup import get_rule

    pipeline = ScoringPipeline()
    for name in DEFAULT_STICKER_NAMES:
        slug = slugify_name(name)
        _key, rule = get_rule(pipeline.rules, "stickers", slug, name)
        assert rule is not None, slug
        assert rule.get("type") != "unmodeled", slug


def test_count_scoring_vs_grid_only_all_defaults():
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[
            LoadoutItem(id=slugify_name(n), name=n, level=1, kind="sticker")
            for n in DEFAULT_STICKER_NAMES
        ]
    )
    scoring, total, grid_only = count_scoring_items(pipeline.rules, loadout)
    assert total == 32
    assert grid_only == len(GRID_ONLY_SLUGS)
    assert scoring == 32 - len(GRID_ONLY_SLUGS)


def test_artists_palette_colored_tile_bonus():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 2, color=TileColor.RED)
    board.tiles[0][1] = _tile(0, 1, "B", 2)
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[
            LoadoutItem(id="artist_s_palette", name="Artist's Palette", level=1)
        ]
    )
    score, bd = pipeline.score(board, [0, 1], "ab", loadout)
    base, _ = pipeline.score(board, [0, 1], "ab", Loadout())
    assert score == base + 6


def test_blueberries_ends_blue_multiplier():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "C", 2)
    board.tiles[0][1] = _tile(0, 1, "A", 2, color=TileColor.BLUE)
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="blueberries", name="Blueberries", level=1)])
    score, bd = pipeline.score(board, [0, 1], "ca", loadout)
    assert bd["multiplier"] == 2.0
    assert score == (4 + 0) * 2


def test_dusty_coffin_void_unused():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 2)
    board.tiles[4][4] = _tile(4, 4, "Z", 0, color=TileColor.VOID)
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="dusty_coffin", name="Dusty Coffin", level=1)])
    score, bd = pipeline.score(board, [0], "a", loadout)
    base, _ = pipeline.score(board, [0], "a", Loadout())
    assert score == base + 8


def test_fire_extinguisher_unused_red():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 2)
    board.tiles[1][0] = _tile(1, 0, "R", 2, color=TileColor.RED)
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[LoadoutItem(id="fire_extinguisher", name="Fire Extinguisher", level=1)]
    )
    score, _ = pipeline.score(board, [0], "a", loadout)
    base, _ = pipeline.score(board, [0], "a", Loadout())
    assert score == base + 5


def test_egg_vowel_start_multiplier():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 3)
    board.tiles[0][1] = _tile(0, 1, "B", 3)
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="egg", name="Egg", level=1)])
    score, bd = pipeline.score(board, [0, 1], "ab", loadout)
    assert bd["multiplier"] == 1.5


def test_maple_leaf_first_two_red_tiles():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 2, color=TileColor.RED)
    board.tiles[0][1] = _tile(0, 1, "B", 2, color=TileColor.RED)
    board.tiles[0][2] = _tile(0, 2, "C", 2, color=TileColor.RED)
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="maple_leaf", name="Maple Leaf", level=1)])
    score, _ = pipeline.score(board, [0, 1, 2], "abc", loadout)
    # first two reds ×3 tile, third red unchanged
    assert score == 2 * 3 + 2 * 3 + 2


def test_sly_spy_consonant_multiply():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "B", 4)
    board.tiles[0][1] = _tile(0, 1, "E", 1, color=TileColor.RED)  # vowel, not consonant
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="sly_spy", name="Sly Spy", level=1)])
    score, _ = pipeline.score(board, [0, 1], "be", loadout)
    assert score == 4 * 2 + 1


def test_credit_card_money_word_score():
    board = Board(tiles=_empty_board().tiles, money=5)
    board.tiles[0][0] = _tile(0, 0, "A", 2)
    pipeline = ScoringPipeline()
    loadout = Loadout(
        money=5,
        stickers=[LoadoutItem(id="credit_card", name="Credit Card", level=1)],
    )
    score, bd = pipeline.score(board, [0], "a", loadout)
    assert bd["word_score"] == 10


def test_chequered_flag_first_grid_extra():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 10)
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[LoadoutItem(id="chequered_flag", name="Chequered Flag", level=1)],
        extras={"is_first_grid_of_encounter": True},
    )
    score, bd = pipeline.score(board, [0], "a", loadout)
    assert bd["multiplier"] == 2.0
    assert score == 20


def test_chips_alphabet_progression():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "C", 4)
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[LoadoutItem(id="chips", name="Chips", level=1)],
        extras={"previous_word_first_letter": "a"},
    )
    score, bd = pipeline.score(board, [0], "cat", loadout)
    assert bd["multiplier"] == 1.5


def test_telescope_red_encounter_bonus():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 2, color=TileColor.RED)
    board.tiles[0][1] = _tile(0, 1, "B", 2, color=TileColor.RED)
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[LoadoutItem(id="telescope", name="Telescope", level=2)],
        extras={"red_tiles_used_encounter": 3},
    )
    score, _ = pipeline.score(board, [0, 1], "ab", loadout)
    # each red: + level * reds_used = +6 per tile
    assert score == (2 + 6) + (2 + 6)


def test_sunflower_money_multiplier():
    board = Board(tiles=_empty_board().tiles, money=10)
    board.tiles[0][0] = _tile(0, 0, "A", 5)
    pipeline = ScoringPipeline()
    loadout = Loadout(
        money=10,
        stickers=[LoadoutItem(id="sunflower", name="Sunflower", level=1)],
    )
    score, bd = pipeline.score(board, [0], "a", loadout)
    assert bd["multiplier"] == 1.1
    assert score == 5.0  # floor(5 × 1.1)


def test_yellow_glasses_double_letter():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "B", 2)
    board.tiles[0][1] = _tile(0, 1, "B", 2)
    board.tiles[0][2] = _tile(0, 2, "A", 2)
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[LoadoutItem(id="yellow_glasses", name="Yellow Glasses", level=1)]
    )
    score, bd = pipeline.score(board, [0, 1, 2], "bba", loadout)
    assert bd["multiplier"] == 1.5
