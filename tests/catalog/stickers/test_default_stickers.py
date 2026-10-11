"""Default-unlocked sticker scoring (wiki: Unlocked by default)."""

import json
from pathlib import Path

from cursed_words_solver.models import Board, CurseType, Loadout, LoadoutItem, Tile, TileColor
from cursed_words_solver.engine.scorer import EngineScorer
from cursed_words_solver.rules.rule_lookup import slugify_name

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

    pipeline = EngineScorer()
    for name in DEFAULT_STICKER_NAMES:
        slug = slugify_name(name)
        _key, rule = get_rule(pipeline.rules, "stickers", slug, name)
        assert rule is not None, slug
        assert rule.get("type") != "unmodeled", slug


def test_artists_palette_colored_tile_bonus():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 2, color=TileColor.RED)
    board.tiles[0][1] = _tile(0, 1, "B", 2)
    pipeline = EngineScorer()
    loadout = Loadout(
        stickers=[
            LoadoutItem(id="artist_s_palette", name="Artist's Palette", level=1)
        ]
    )
    score, bd = pipeline.score(board, [0, 1], "ab", loadout)
    base, _ = pipeline.score(board, [0, 1], "ab", Loadout())
    assert score == base + 6


def test_artists_palette_applies_to_white_tile():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 1, color=TileColor.WHITE)
    pipeline = EngineScorer()
    loadout = Loadout(
        stickers=[
            LoadoutItem(id="artist_s_palette", name="Artist's Palette", level=1)
        ]
    )
    score, _ = pipeline.score(board, [0], "a", loadout)
    base, _ = pipeline.score(board, [0], "a", Loadout())
    assert score == base + 6


def test_dango_counts_white_as_unique_colour():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 2, color=TileColor.WHITE)
    board.tiles[0][1] = _tile(0, 1, "B", 2, color=TileColor.RED)
    pipeline = EngineScorer()
    loadout = Loadout(stamps=[LoadoutItem(id="dango", name="Dango", level=1)])
    score, _ = pipeline.score(board, [0, 1], "ab", loadout)
    base, _ = pipeline.score(board, [0, 1], "ab", Loadout())
    assert score == base * 2


def test_blueberries_ends_blue_multiplier():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "C", 2)
    board.tiles[0][1] = _tile(0, 1, "A", 2, color=TileColor.BLUE)
    pipeline = EngineScorer()
    loadout = Loadout(stickers=[LoadoutItem(id="blueberries", name="Blueberries", level=1)])
    score, bd = pipeline.score(board, [0, 1], "ca", loadout)
    assert bd["multiplier"] == 2.0
    assert score == (4 + 0) * 2


def test_dusty_coffin_void_unused():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 2)
    board.tiles[4][4] = _tile(4, 4, "Z", 0, color=TileColor.VOID)
    pipeline = EngineScorer()
    loadout = Loadout(stickers=[LoadoutItem(id="dusty_coffin", name="Dusty Coffin", level=1)])
    score, bd = pipeline.score(board, [0], "a", loadout)
    base, _ = pipeline.score(board, [0], "a", Loadout())
    assert score == base + 8


def test_dusty_coffin_skips_void_whose_face_is_on_path():
    """Dusty matches path faces, not dictionary letters (game GetStringRepresentation)."""
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "B", 2)
    board.tiles[2][2] = _tile(2, 2, "A", 0, color=TileColor.VOID)
    board.tiles[4][4] = _tile(4, 4, "Z", 0, color=TileColor.VOID)
    pipeline = EngineScorer()
    loadout = Loadout(stickers=[LoadoutItem(id="dusty_coffin", name="Dusty Coffin", level=1)])
    # Path face is only B — both voids count even though word contains A.
    score, bd = pipeline.score(board, [0], "baa", loadout)
    base, _ = pipeline.score(board, [0], "baa", Loadout())
    assert bd["word_score"] == 16
    assert score == base + 16


def test_dusty_coffin_excludes_void_face_present_on_path():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "B", 2)
    board.tiles[0][1] = _tile(0, 1, "Q", 0, color=TileColor.VOID)
    board.tiles[4][4] = _tile(4, 4, "Z", 0, color=TileColor.VOID)
    pipeline = EngineScorer()
    loadout = Loadout(stickers=[LoadoutItem(id="dusty_coffin", name="Dusty Coffin", level=1)])
    score, bd = pipeline.score(board, [0, 1], "ba", loadout)
    base, _ = pipeline.score(board, [0, 1], "ba", Loadout())
    # Path faces {b,q} exclude the on-path void Q; only Z counts.
    assert bd["word_score"] == 8
    assert score == base + 8


def test_dusty_coffin_counts_void_currency_symbols_not_in_word():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 2)
    board.tiles[0][1] = _tile(0, 1, "₮", 0, color=TileColor.VOID, curse=CurseType.CURRENCY)
    board.tiles[0][2] = _tile(0, 2, "₡", 0, color=TileColor.VOID, curse=CurseType.CURRENCY)
    board.tiles[4][4] = _tile(4, 4, "Z", 0, color=TileColor.VOID)
    pipeline = EngineScorer()
    loadout = Loadout(stickers=[LoadoutItem(id="dusty_coffin", name="Dusty Coffin", level=1)])
    score, bd = pipeline.score(board, [0], "at", loadout)
    base, _ = pipeline.score(board, [0], "at", Loadout())
    assert bd["word_score"] == 24
    assert score == base + 24


def test_dusty_coffin_number_void_digit_not_in_word():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 2)
    board.tiles[3][1] = Tile(
        row=3,
        col=1,
        char="8",
        letter="8",
        base_score=0.0,
        color=TileColor.VOID,
        curse=CurseType.NUMBER,
        number_value=8,
        metadata={"source": "melmod"},
    )
    pipeline = EngineScorer()
    loadout = Loadout(stickers=[LoadoutItem(id="dusty_coffin", name="Dusty Coffin", level=1)])
    score, bd = pipeline.score(board, [0], "a", loadout)
    base, _ = pipeline.score(board, [0], "a", Loadout())
    assert bd["word_score"] == 8
    assert score == base + 8


def test_dusty_coffin_counts_void_item_tiles():
    """Game DustyCoffin counts VOID item tiles via GetStringRepresentation."""
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "G", 2)
    board.tiles[4][1] = Tile(
        row=4,
        col=1,
        char="🗝️",
        letter="A",
        base_score=0.0,
        color=TileColor.VOID,
        curse=CurseType.ITEM,
        metadata={"source": "melmod", "scattered_item_id": "ornate_key"},
    )
    board.tiles[0][1] = _tile(0, 1, "₮", 0, color=TileColor.VOID, curse=CurseType.CURRENCY)
    pipeline = EngineScorer()
    loadout = Loadout(stickers=[LoadoutItem(id="dusty_coffin", name="Dusty Coffin", level=1)])
    score, bd = pipeline.score(board, [0], "groggy", loadout)
    base, _ = pipeline.score(board, [0], "groggy", Loadout())
    assert bd["word_score"] == 16
    assert score == base + 16


def test_dusty_coffin_counts_unused_void_item_when_letter_in_word():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "R", 1)
    board.tiles[4][3] = _tile(4, 3, "$", 0, color=TileColor.VOID, curse=CurseType.CURRENCY)
    board.tiles[0][3] = Tile(
        row=0,
        col=3,
        char="🧁",
        letter="I",
        base_score=0.0,
        color=TileColor.VOID,
        curse=CurseType.ITEM,
        metadata={"source": "melmod", "scattered_item_id": "rainbow_sprinkles"},
    )
    pipeline = EngineScorer()
    loadout = Loadout(stickers=[LoadoutItem(id="dusty_coffin", name="Dusty Coffin", level=1)])
    score, bd = pipeline.score(board, [0], "requin", loadout)
    base, _ = pipeline.score(board, [0], "requin", Loadout())
    assert bd["word_score"] == 16
    assert score == base + 16


def test_dusty_coffin_uses_only_unused_void_tiles_mismatch_shape():
    """megabyte mismatch: two VOID tiles on path, one VOID currency off-path."""
    board = _empty_board()
    board.tiles[4][3] = _tile(4, 3, "M", 3)
    board.tiles[3][4] = _tile(3, 4, "⚰️", 0, curse=CurseType.ITEM)
    board.tiles[2][3] = Tile(
        row=2,
        col=3,
        char="🎡",
        letter="G",
        base_score=0.0,
        color=TileColor.VOID,
        curse=CurseType.ITEM,
        metadata={"source": "melmod", "scattered_item_id": "ferris_wheel"},
    )
    board.tiles[2][4] = _tile(2, 4, "฿", 0, color=TileColor.VOID, curse=CurseType.CURRENCY)
    board.tiles[3][2] = _tile(3, 2, "₣", 0, color=TileColor.VOID, curse=CurseType.CURRENCY)
    path = [23, 19, 13, 14]
    pipeline = EngineScorer()
    loadout = Loadout(stickers=[LoadoutItem(id="dusty_coffin", name="Dusty Coffin", level=1)])
    score, bd = pipeline.score(board, path, "megabyte", loadout)
    base, _ = pipeline.score(board, path, "megabyte", Loadout())
    assert bd["word_score"] == 8
    assert score == base + 8


def test_fire_extinguisher_unused_red():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 2)
    board.tiles[1][0] = _tile(1, 0, "R", 2, color=TileColor.RED)
    pipeline = EngineScorer()
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
    pipeline = EngineScorer()
    loadout = Loadout(stickers=[LoadoutItem(id="egg", name="Egg", level=1)])
    score, bd = pipeline.score(board, [0, 1], "ab", loadout)
    assert bd["multiplier"] == 1.5


def test_egg_vowel_uses_path_first_letter():
    """Dictionary 'ex' starts with a vowel; path wildcard then X does not (mismatch 20260608_123837)."""
    board = _empty_board()
    board.tiles[0][3] = _tile(0, 3, "?", 1, curse=CurseType.WILDCARD)
    board.tiles[0][3].letter = "?"
    board.tiles[0][4] = _tile(0, 4, "X", 1)
    pipeline = EngineScorer()
    loadout = Loadout(stickers=[LoadoutItem(id="egg", name="Egg", level=2)])
    with_egg, _ = pipeline.score(board, [3, 4], "ex", loadout)
    base, _ = pipeline.score(board, [3, 4], "ex", Loadout())
    assert with_egg == base


def test_egg_skips_when_path_starts_consonant_ova_style():
    """Dictionary 'ova' starts with a vowel; first letter tile on path is V (mismatch 20260608_124049)."""
    board = _empty_board()
    board.tiles[4][0] = _tile(4, 0, "?", 1, curse=CurseType.CHESS_QUEEN)
    board.tiles[4][0].letter = "?"
    board.tiles[0][1] = _tile(0, 1, "V", 2)
    board.tiles[1][1] = _tile(1, 1, "?", 1, curse=CurseType.CHESS_QUEEN)
    board.tiles[1][1].letter = "?"
    pipeline = EngineScorer()
    loadout = Loadout(stickers=[LoadoutItem(id="egg", name="Egg", level=2)])
    with_egg, _ = pipeline.score(board, [20, 1, 6], "ova", loadout)
    base, _ = pipeline.score(board, [20, 1, 6], "ova", Loadout())
    assert with_egg == base


def test_egg_skips_when_path_starts_with_currency():
    """Egg checks tiles[0] only; currency glyphs are never vowels (sughs 20260717)."""
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "$", 0, curse=CurseType.CURRENCY)
    board.tiles[0][1] = _tile(0, 1, "U", 2, color=TileColor.BLUE)
    board.tiles[0][2] = _tile(0, 2, "G", 0, curse=CurseType.CURRENCY)
    board.tiles[0][2].char = "₲"
    board.tiles[0][3] = _tile(0, 3, "H", 5, color=TileColor.RED)
    board.tiles[0][4] = _tile(0, 4, "S", 1)
    pipeline = EngineScorer()
    loadout = Loadout(stickers=[LoadoutItem(id="egg", name="Egg", level=2)])
    path = [0, 1, 2, 3, 4]
    with_egg, _ = pipeline.score(board, path, "sughs", loadout)
    base, _ = pipeline.score(board, path, "sughs", Loadout())
    assert with_egg == base


def test_first_letter_on_path_includes_leading_currency_map():
    from cursed_words_solver.rules.scoring_conditions import first_letter_on_path

    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "$", 0, curse=CurseType.CURRENCY)
    board.tiles[0][1] = _tile(0, 1, "U", 1)
    assert first_letter_on_path(board, [0, 1]) == "s"


def test_maple_leaf_first_two_red_tiles():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 2, color=TileColor.RED)
    board.tiles[0][1] = _tile(0, 1, "B", 2, color=TileColor.RED)
    board.tiles[0][2] = _tile(0, 2, "C", 2, color=TileColor.RED)
    pipeline = EngineScorer()
    loadout = Loadout(stickers=[LoadoutItem(id="maple_leaf", name="Maple Leaf", level=1)])
    score, _ = pipeline.score(board, [0, 1, 2], "abc", loadout)
    # first two reds ×3 tile, third red unchanged
    assert score == 2 * 3 + 2 * 3 + 2


def test_sly_spy_consonant_multiply():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "B", 4)
    board.tiles[0][1] = _tile(0, 1, "E", 1, color=TileColor.RED)  # vowel, not consonant
    pipeline = EngineScorer()
    loadout = Loadout(stickers=[LoadoutItem(id="sly_spy", name="Sly Spy", level=1)])
    score, _ = pipeline.score(board, [0, 1], "be", loadout)
    assert score == 4 * 2 + 1


def test_credit_card_money_word_score():
    board = Board(tiles=_empty_board().tiles, money=5)
    board.tiles[0][0] = _tile(0, 0, "A", 2)
    pipeline = EngineScorer()
    loadout = Loadout(
        money=5,
        stickers=[LoadoutItem(id="credit_card", name="Credit Card", level=1)],
    )
    score, bd = pipeline.score(board, [0], "a", loadout)
    assert bd["word_score"] == 10


def test_credit_card_money_includes_currency_earned_this_word():
    """Per-$ stickers use bank after GetMoneyFromCurrencyTiles (+$1 per $ tile)."""
    board = Board(tiles=_empty_board().tiles, money=5)
    board.tiles[0][0] = _tile(0, 0, "$", 0, curse=CurseType.CURRENCY)
    board.tiles[0][1] = _tile(0, 1, "A", 2)
    pipeline = EngineScorer()
    loadout = Loadout(
        money=5,
        stickers=[LoadoutItem(id="credit_card", name="Credit Card", level=1)],
    )
    score, bd = pipeline.score(board, [0, 1], "a", loadout)
    assert bd["word_score"] == 12
    assert score == 14


def test_credit_card_money_does_not_compound_across_repeated_scoring():
    """Search scores many candidates; currency must not permanently raise loadout.money."""
    board = Board(tiles=_empty_board().tiles, money=2)
    board.tiles[0][0] = _tile(0, 0, "$", 0, curse=CurseType.CURRENCY)
    board.tiles[0][1] = _tile(0, 1, "A", 2)
    loadout = Loadout(
        money=2,
        stickers=[LoadoutItem(id="credit_card", name="Credit Card", level=1)],
    )
    pipeline = EngineScorer()
    for _ in range(100):
        pipeline.score_total_only(board, [0, 1], "a", loadout)
    assert loadout.money == 2
    assert board.money == 2


def test_credit_card_money_uses_bank_not_currency_tile_value():
    board = Board(tiles=_empty_board().tiles, money=5)
    board.tiles[0][0] = _tile(0, 0, "₩", 0, curse=CurseType.CURRENCY)
    board.tiles[0][1] = _tile(0, 1, "A", 2)
    pipeline = EngineScorer()
    loadout = Loadout(
        money=5,
        stickers=[LoadoutItem(id="credit_card", name="Credit Card", level=1)],
    )
    score, bd = pipeline.score(board, [0, 1], "a", loadout)
    assert bd["word_score"] == 12
    assert score == 14


def test_wheezy_vixen_no_multiply_when_currency_before_letter():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "$", 0, curse=CurseType.CURRENCY)
    board.tiles[0][1] = _tile(0, 1, "E", 1)
    board.tiles[0][2] = _tile(0, 2, "E", 1)
    board.tiles[0][3] = _tile(0, 3, "P", 3)
    pipeline = EngineScorer()
    loadout = Loadout(
        stickers=[LoadoutItem(id="wheezy_vixen", name="Wheezy Vixen", level=2)],
    )
    # Word starts with D (not vwxyz); path's first letter tile would be E.
    score, bd = pipeline.score(board, [0, 1, 2, 3], "deep", loadout)
    assert bd["multiplier"] == 1.0
    assert score == 5


def test_wheezy_vixen_no_multiply_when_currency_substitutes_w():
    """womby mismatch: ₩ substitutes for W in the word but first letter tile is O."""
    board = _empty_board()
    board.tiles[0][0] = Tile(
        row=0,
        col=0,
        char="₩",
        letter="W",
        base_score=0,
        curse=CurseType.CURRENCY,
    )
    board.tiles[0][1] = _tile(0, 1, "O", 1)
    board.tiles[0][2] = _tile(0, 2, "M", 3)
    board.tiles[0][3] = _tile(0, 3, "B", 3)
    board.tiles[0][4] = _tile(0, 4, "Y", 4)
    pipeline = EngineScorer()
    loadout = Loadout(
        stickers=[LoadoutItem(id="wheezy_vixen", name="Wheezy Vixen", level=2)],
    )
    score, bd = pipeline.score(board, list(range(5)), "womby", loadout)
    assert bd["multiplier"] == 1.0
    assert score == 11


def test_wheezy_vixen_no_multiply_when_yen_substitutes_y():
    """youthly mismatch 20260717: ¥→Y via CURRENCY_MAP must not trigger Wheezy."""
    board = _empty_board()
    board.tiles[0][0] = Tile(
        row=0,
        col=0,
        char="¥",
        letter="¥",
        base_score=0,
        curse=CurseType.CURRENCY,
    )
    board.tiles[0][1] = _tile(0, 1, "O", 1)
    board.tiles[0][2] = _tile(0, 2, "U", 1)
    board.tiles[0][3] = _tile(0, 3, "T", 1)
    board.tiles[0][4] = _tile(0, 4, "H", 4)
    board.tiles[1][0] = _tile(1, 0, "L", 1)
    board.tiles[1][1] = Tile(
        row=1,
        col=1,
        char="¥",
        letter="¥",
        base_score=0,
        curse=CurseType.CURRENCY,
    )
    pipeline = EngineScorer()
    loadout = Loadout(
        stickers=[LoadoutItem(id="wheezy_vixen", name="Wheezy Vixen", level=1)],
    )
    path = [0, 1, 2, 3, 4, 5, 6]
    score, bd = pipeline.score(board, path, "youthly", loadout)
    assert bd["multiplier"] == 1.0
    # Base tile sum: 0+1+1+1+4+1+0 = 8
    assert score == 8


def test_wheezy_vixen_no_multiply_when_word_starts_t_but_path_starts_currency_then_y():
    """tynde mismatch: path's first letter tile is Y but submitted word starts with T."""
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "$", 0, curse=CurseType.CURRENCY)
    board.tiles[0][1] = _tile(0, 1, "Y", 4)
    board.tiles[0][2] = _tile(0, 2, "N", 1)
    board.tiles[0][3] = _tile(0, 3, "D", 2)
    board.tiles[0][4] = _tile(0, 4, "E", 1)
    pipeline = EngineScorer()
    loadout = Loadout(
        stickers=[LoadoutItem(id="wheezy_vixen", name="Wheezy Vixen", level=2)],
    )
    score, bd = pipeline.score(board, list(range(5)), "tynde", loadout)
    assert bd["multiplier"] == 1.0
    assert score == 8


def test_wheezy_vixen_multiply_when_path_starts_with_v():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "V", 4)
    board.tiles[0][1] = _tile(0, 1, "I", 1)
    board.tiles[0][2] = _tile(0, 2, "B", 3)
    board.tiles[0][3] = _tile(0, 3, "E", 1)
    board.tiles[0][4] = _tile(0, 4, "S", 1)
    pipeline = EngineScorer()
    loadout = Loadout(
        stickers=[LoadoutItem(id="wheezy_vixen", name="Wheezy Vixen", level=2)],
    )
    score, bd = pipeline.score(board, list(range(5)), "vibes", loadout)
    assert bd["multiplier"] == 3.0
    assert score == 30


def test_chequered_flag_first_grid_extra():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 10)
    pipeline = EngineScorer()
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
    pipeline = EngineScorer()
    loadout = Loadout(
        stickers=[LoadoutItem(id="chips", name="Chips", level=1)],
        extras={"previous_word_first_letter": "a"},
    )
    score, bd = pipeline.score(board, [0], "cat", loadout)
    assert bd["multiplier"] == 1.5


def test_sunflower_money_multiplier():
    board = Board(tiles=_empty_board().tiles, money=10)
    board.tiles[0][0] = _tile(0, 0, "A", 5)
    pipeline = EngineScorer()
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
    pipeline = EngineScorer()
    loadout = Loadout(
        stickers=[LoadoutItem(id="yellow_glasses", name="Yellow Glasses", level=1)]
    )
    # Consecutive B on path; word "aba" has no double letter in the string.
    score, bd = pipeline.score(board, [0, 1, 2], "aba", loadout)
    assert bd["multiplier"] == 1.5
    base, _ = pipeline.score(board, [0, 1, 2], "aba", Loadout())
    assert score == int(base * 1.5)


def test_yellow_glasses_no_double_across_chess_tile():
    """Chess submit char breaks path; same letter on both sides must not count."""
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "S", 1)
    board.tiles[0][1] = Tile(
        row=0,
        col=1,
        char="t",
        letter="?",
        base_score=6.0,
        color=TileColor.COLORLESS,
        curse=CurseType.CHESS_ROOK,
        metadata={"chess_color": "black"},
    )
    board.tiles[0][2] = _tile(0, 2, "S", 1)
    pipeline = EngineScorer()
    loadout = Loadout(
        stickers=[LoadoutItem(id="yellow_glasses", name="Yellow Glasses", level=1)]
    )
    base, _ = pipeline.score(board, [0, 1, 2], "sts", Loadout())
    score, bd = pipeline.score(board, [0, 1, 2], "sts", loadout)
    assert bd["multiplier"] == 1.0
    assert score == base


def test_yellow_glasses_no_double_across_chess_bishop():
    """Bishop submit char between equal letters (bemeant-style) must not count."""
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "E", 1)
    board.tiles[0][1] = Tile(
        row=0,
        col=1,
        char="n",
        letter="?",
        base_score=4.0,
        color=TileColor.COLORLESS,
        curse=CurseType.CHESS_BISHOP,
        metadata={"chess_color": "black"},
    )
    board.tiles[0][2] = _tile(0, 2, "E", 1)
    pipeline = EngineScorer()
    loadout = Loadout(
        stickers=[LoadoutItem(id="yellow_glasses", name="Yellow Glasses", level=1)]
    )
    base, _ = pipeline.score(board, [0, 1, 2], "ene", Loadout())
    score, bd = pipeline.score(board, [0, 1, 2], "ene", loadout)
    assert bd["multiplier"] == 1.0
    assert score == base


def test_yellow_glasses_double_letter_currency_path_uses_word():
    """Currency tiles hide path letters; double letters in the submitted word still count."""
    board = _empty_board()
    for col, glyph in enumerate(("₱", "₣", "₣", "₮")):
        board.tiles[0][col] = _tile(0, col, glyph, 16, curse=CurseType.CURRENCY)
    pipeline = EngineScorer()
    loadout = Loadout(
        stickers=[LoadoutItem(id="yellow_glasses", name="Yellow Glasses", level=3)]
    )
    score, bd = pipeline.score(board, [0, 1, 2, 3], "pfft", loadout)
    base, _ = pipeline.score(board, [0, 1, 2, 3], "pfft", Loadout())
    assert bd["multiplier"] == 2.5
    assert score == int(base * 2.5)


def _wildcard_tile(row: int, col: int, score: int = 1) -> Tile:
    return Tile(
        row=row,
        col=col,
        char="?",
        letter="?",
        base_score=score,
        color=TileColor.BLUE,
        curse=CurseType.WILDCARD,
        metadata={"source": "melmod"},
    )


def test_yellow_glasses_two_adjacent_wildcards_double():
    """Two adjacent wildcard tiles are a double (blank glyph matches blank glyph).

    'jazzy' on J-?-?-Z-Y earns Yellow Glasses from the two adjacent wildcards at
    path positions 1-2, regardless of the letters they spell (a, z).
    """
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "J", 8)
    board.tiles[0][1] = _wildcard_tile(0, 1)
    board.tiles[0][2] = _wildcard_tile(0, 2)
    board.tiles[0][3] = _tile(0, 3, "Z", 10)
    board.tiles[0][4] = _tile(0, 4, "Y", 4)
    pipeline = EngineScorer()
    loadout = Loadout(
        stickers=[LoadoutItem(id="yellow_glasses", name="Yellow Glasses", level=1)]
    )
    score, bd = pipeline.score(board, [0, 1, 2, 3, 4], "jazzy", loadout)
    assert bd["multiplier"] == 1.5
    base, _ = pipeline.score(board, [0, 1, 2, 3, 4], "jazzy", Loadout())
    assert score == int(base * 1.5)


def test_yellow_glasses_wildcard_with_real_letter_not_double():
    """A wildcard is a blank glyph: it never doubles with an adjacent real letter.

    The game does not treat 'kee' (real K, wildcard-e, real E) as a double, even
    though the wildcard spells 'e' next to the real E (see the 'akees' 153-vs-102
    mismatch). Yellow Glasses must not apply here.
    """
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "K", 5)
    board.tiles[0][1] = _wildcard_tile(0, 1)
    board.tiles[0][2] = _tile(0, 2, "E", 1)
    pipeline = EngineScorer()
    loadout = Loadout(
        stickers=[LoadoutItem(id="yellow_glasses", name="Yellow Glasses", level=1)]
    )
    score, bd = pipeline.score(board, [0, 1, 2], "kee", loadout)
    assert bd["multiplier"] == 1.0
    base, _ = pipeline.score(board, [0, 1, 2], "kee", Loadout())
    assert score == base


def test_ham_sandwich_no_bonus_fraction_start_wildcard_end():
    """Fraction start + wildcard end must not match as two blank glyphs (atmoses capture).

    Fraction tiles export with internal letter \"?\" for word building, but
    GetStringRepresentation is the fraction glyph — not \"?\". Ham must not fire
    when only the wildcard endpoint is blank.
    """
    board = _empty_board()
    board.tiles[1][0] = Tile(
        row=1,
        col=0,
        char="⅐",
        letter="?",
        base_score=8.0,
        color=TileColor.COLORLESS,
        curse=CurseType.FRACTION,
        fraction_value=1 / 7,
        metadata={"source": "melmod"},
    )
    board.tiles[1][1] = _wildcard_tile(1, 1, score=0)
    for col, ch, score in ((2, "T", 1), (3, "M", 2), (4, "O", 1)):
        board.tiles[1][col] = _tile(1, col, ch, score)
    board.tiles[2][0] = _tile(2, 0, "S", 1)
    board.tiles[2][1] = _tile(2, 1, "E", 1)
    board.tiles[2][2] = _tile(2, 2, "S", 1)
    pipeline = EngineScorer()
    loadout = Loadout(
        stickers=[LoadoutItem(id="ham_sandwich", name="Ham Sandwich", level=1)]
    )
    path = [5, 6, 7, 8, 9, 10, 11]
    word = "atmoses"
    score, _ = pipeline.score(board, path, word, loadout)
    base, _ = pipeline.score(board, path, word, Loadout())
    assert score == base


def test_ham_sandwich_no_bonus_when_endpoint_is_blank():
    """A blank endpoint reads '?', so a resolved spelling must not earn Ham Sandwich.

    The game compares tiles[0]/tiles[last] GetStringRepresentation(); for the
    'kno??' path (real K + trailing wildcards) the last tile is '?', so even though
    the score-maximizing spelling is 'knock' (k==k), Ham Sandwich does NOT fire
    (the 'knosp' 378-vs-55 mismatch).
    """
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "K", 5)
    board.tiles[0][1] = _tile(0, 1, "N", 1)
    board.tiles[0][2] = _tile(0, 2, "O", 1)
    board.tiles[0][3] = _wildcard_tile(0, 3)
    board.tiles[0][4] = _wildcard_tile(0, 4)
    pipeline = EngineScorer()
    loadout = Loadout(
        stickers=[LoadoutItem(id="ham_sandwich", name="Ham Sandwich", level=1)]
    )
    score, _ = pipeline.score(board, [0, 1, 2, 3, 4], "knock", loadout)
    base, _ = pipeline.score(board, [0, 1, 2, 3, 4], "knock", Loadout())
    assert score == base


def test_ham_sandwich_bonus_on_equal_real_endpoints():
    """Two equal real-letter endpoints (e.g. 'whew') do earn Ham Sandwich."""
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "W", 4)
    board.tiles[0][1] = _tile(0, 1, "H", 4)
    board.tiles[0][2] = _tile(0, 2, "E", 1)
    board.tiles[0][3] = _tile(0, 3, "W", 4)
    pipeline = EngineScorer()
    loadout = Loadout(
        stickers=[LoadoutItem(id="ham_sandwich", name="Ham Sandwich", level=1)]
    )
    score, _ = pipeline.score(board, [0, 1, 2, 3], "whew", loadout)
    base, _ = pipeline.score(board, [0, 1, 2, 3], "whew", Loadout())
    assert score > base


def test_ham_sandwich_two_blank_endpoints_match():
    """Two blank endpoints compare '?'=='?', so Ham Sandwich fires (game behavior)."""
    board = _empty_board()
    board.tiles[0][0] = _wildcard_tile(0, 0)
    board.tiles[0][1] = _tile(0, 1, "A", 1)
    board.tiles[0][2] = _wildcard_tile(0, 2)
    pipeline = EngineScorer()
    loadout = Loadout(
        stickers=[LoadoutItem(id="ham_sandwich", name="Ham Sandwich", level=1)]
    )
    score, _ = pipeline.score(board, [0, 1, 2], "cat", loadout)
    base, _ = pipeline.score(board, [0, 1, 2], "cat", Loadout())
    assert score > base


def test_hi_vis_uses_post_placement_consumable_count():
    """Placing a consumable removes it from the rack, lowering the Hi-Vis multiplier.

    Decompiled HiVisJacket multiplies by consumables still owned and drops one on
    submit, so a placed consumable must not be counted (knosp x4.0 with 5 vs the
    game's x3.4 with 4).
    """
    from cursed_words_solver.consumable_placement import (
        loadout_after_consumable_placements,
    )
    from cursed_words_solver.rules.scoring_conditions import consumable_rack_count

    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "C", 2)
    board.tiles[0][1] = _tile(0, 1, "A", 2)
    board.tiles[0][2] = _tile(0, 2, "T", 2)
    pipeline = EngineScorer()
    pre = Loadout(
        stickers=[LoadoutItem(id="hi_vis_jacket", name="Hi Vis Jacket", level=1)],
        extras={"consumable_rack_count": 5},
    )
    assert consumable_rack_count(pre) == 5
    post = loadout_after_consumable_placements(pre, 1)
    assert consumable_rack_count(post) == 4

    _score_pre, bd_pre = pipeline.score(board, [0, 1, 2], "cat", pre)
    _score_post, bd_post = pipeline.score(board, [0, 1, 2], "cat", post)
    assert bd_pre["multiplier"] > 1.0
    assert bd_post["multiplier"] < bd_pre["multiplier"]


def test_hi_vis_defers_word_bonus_before_stilton_blueberries_stack():
    """Hi-Vis before Stilton queues ×WORD; finalize stacks with Blueberries (affidation).

    Decompiled HiVisJacket.ApplyWordBonus queues a multiplicative WordBonusToken;
    it must not multiply the subtotal before later +tile-score stickers. With
    Hi-Vis ×4 and Blueberries ×4 on a 231 tile sum after Stilton, score is 3696.
    """
    from cursed_words_solver.loadout import (
        parse_board_from_run_state,
        parse_run_state,
        prepare_run_state_dict_for_scoring,
    )

    fixture = (
        Path(__file__).resolve().parents[2]
        / "fixtures"
        / "mismatches"
        / "20260605_205912.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    run_state = prepare_run_state_dict_for_scoring(data["run_state_snapshot"])
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    pipeline = EngineScorer()
    path = data["path"]
    score, _bd, trace = pipeline.score_with_trace(board, path, data["word"], loadout)
    assert score == 3696
    hi_vis_step = next(
        s
        for s in trace
        if s.get("phase") == "rule" and s.get("rule_id") == "hi_vis_jacket"
    )
    assert hi_vis_step.get("word_score", 0) == 0
    multiply_rules = [
        s.get("rule_id")
        for s in trace
        if s.get("phase") == "multiply"
    ]
    assert "hi_vis_jacket" in multiply_rules
    assert "blueberries" in multiply_rules
