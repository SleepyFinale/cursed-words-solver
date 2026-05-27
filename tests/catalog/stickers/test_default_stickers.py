"""Default-unlocked sticker scoring (wiki: Unlocked by default)."""

import json
from pathlib import Path

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
from cursed_words_solver.rules.scoring_conditions import (
    currency_letter_value,
    money_for_scoring,
    unique_vowels_in_word,
    unique_vowels_on_path,
)

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


def test_dusty_coffin_skips_void_whose_letter_is_in_word():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "B", 2)
    board.tiles[2][2] = _tile(2, 2, "A", 0, color=TileColor.VOID)
    board.tiles[4][4] = _tile(4, 4, "Z", 0, color=TileColor.VOID)
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="dusty_coffin", name="Dusty Coffin", level=1)])
    score, bd = pipeline.score(board, [0], "baa", loadout)
    base, _ = pipeline.score(board, [0], "baa", Loadout())
    assert bd["word_score"] == 8
    assert score == base + 8


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
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="dusty_coffin", name="Dusty Coffin", level=1)])
    score, bd = pipeline.score(board, [0], "a", loadout)
    base, _ = pipeline.score(board, [0], "a", Loadout())
    assert bd["word_score"] == 8
    assert score == base + 8


def test_pneumonia_counts_path_letter_vowels_not_dictionary_or_currency():
    """Mismatch 20260527_024904: €–A–R scored as 'ear' — only tile A counts for Pneumonia."""
    board = _empty_board()
    board.tiles[4][4] = _tile(4, 4, "€", 10, curse=CurseType.CURRENCY)
    board.tiles[3][3] = _tile(3, 3, "A", 1)
    board.tiles[4][2] = _tile(4, 2, "R", 1)
    path = [24, 18, 22]
    assert unique_vowels_in_word("ear") == 2
    assert unique_vowels_on_path(board, path) == 1
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[LoadoutItem(id="pneumonia", name="Pneumonia", level=2)],
        extras={"pin_effect": "bucket", "pin_branch": "right"},
    )
    score, bd = pipeline.score(board, path, "ear", loadout)
    assert bd["word_score"] == 20
    assert int(score) == 32


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


def test_credit_card_money_includes_currency_earned_this_word():
    """Per-$ stickers use bank after GetMoneyFromCurrencyTiles (+$1 per $ tile)."""
    board = Board(tiles=_empty_board().tiles, money=5)
    board.tiles[0][0] = _tile(0, 0, "$", 0, curse=CurseType.CURRENCY)
    board.tiles[0][1] = _tile(0, 1, "A", 2)
    pipeline = ScoringPipeline()
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
    pipeline = ScoringPipeline()
    for _ in range(100):
        pipeline.score_total_only(board, [0, 1], "a", loadout)
    assert loadout.money == 2
    assert board.money == 2


def test_credit_card_money_uses_bank_not_currency_tile_value():
    board = Board(tiles=_empty_board().tiles, money=5)
    board.tiles[0][0] = _tile(0, 0, "₩", 0, curse=CurseType.CURRENCY)
    board.tiles[0][1] = _tile(0, 1, "A", 2)
    pipeline = ScoringPipeline()
    loadout = Loadout(
        money=5,
        stickers=[LoadoutItem(id="credit_card", name="Credit Card", level=1)],
    )
    score, bd = pipeline.score(board, [0, 1], "a", loadout)
    assert bd["word_score"] == 12
    assert score == 14


def test_currency_letter_value_melmod_glyph():
    glyph = "<font=InterBold SDF>₩</font>"
    tile = _tile(0, 0, glyph, 0, curse=CurseType.CURRENCY)
    tile.letter = glyph
    assert currency_letter_value(tile) == 4

    board = Board(tiles=_empty_board().tiles, money=4)
    board.tiles[0][0] = tile
    board.tiles[0][1] = _tile(0, 1, "$", 0, curse=CurseType.CURRENCY)
    loadout = Loadout(money=4)
    assert money_for_scoring(board, [0, 1], loadout) == 4


def test_wheezy_vixen_no_multiply_when_currency_before_letter():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "$", 0, curse=CurseType.CURRENCY)
    board.tiles[0][1] = _tile(0, 1, "E", 1)
    board.tiles[0][2] = _tile(0, 2, "E", 1)
    board.tiles[0][3] = _tile(0, 3, "P", 3)
    pipeline = ScoringPipeline()
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
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[LoadoutItem(id="wheezy_vixen", name="Wheezy Vixen", level=2)],
    )
    score, bd = pipeline.score(board, list(range(5)), "womby", loadout)
    assert bd["multiplier"] == 1.0
    assert score == 11


def test_wheezy_vixen_no_multiply_when_word_starts_t_but_path_starts_currency_then_y():
    """tynde mismatch: path's first letter tile is Y but submitted word starts with T."""
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "$", 0, curse=CurseType.CURRENCY)
    board.tiles[0][1] = _tile(0, 1, "Y", 4)
    board.tiles[0][2] = _tile(0, 2, "N", 1)
    board.tiles[0][3] = _tile(0, 3, "D", 2)
    board.tiles[0][4] = _tile(0, 4, "E", 1)
    pipeline = ScoringPipeline()
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
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[LoadoutItem(id="wheezy_vixen", name="Wheezy Vixen", level=2)],
    )
    score, bd = pipeline.score(board, list(range(5)), "vibes", loadout)
    assert bd["multiplier"] == 3.0
    assert score == 30


def test_wheezy_vixen_skipped_for_speccy_currency_path():
    """speccy mismatch: word starts with s (not vwxyz); Wheezy must not queue a multiplier."""
    fixture = (
        Path(__file__).resolve().parents[2]
        / "fixtures"
        / "mismatches"
        / "20260523_163629.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state

    run_state = dict(data["run_state_snapshot"])
    extras = dict(run_state.get("extras") or {})
    extras.update(data.get("extras_snapshot") or {})
    run_state["extras"] = extras
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    from tests.regression.test_scoring_mismatches import _bank_money_for_replay

    path = data["path"]
    word = data["word"]

    replay_money = _bank_money_for_replay(data, board, path, loadout)
    if replay_money is not None:
        board.money = max(board.money, replay_money)
        loadout.money = max(loadout.money, replay_money)

    pipeline = ScoringPipeline()
    score, bd, trace = pipeline.score_with_trace(board, path, word, loadout)

    assert int(score) == int(data["actual_score"])
    wheezy = [s for s in trace if s.get("rule_id") == "wheezy_vixen"]
    assert len(wheezy) == 1
    step = wheezy[0]
    assert step["applied"] is False
    assert step["condition_met"] is False
    assert step["word_first_letter"] == "s"
    assert "vwxyz" in step["detail"].lower()

    pending = bd["pipeline"]["pending_word_multipliers"]
    rule_ids = [
        entry[1] if isinstance(entry, tuple) else ""
        for entry in pending
    ]
    assert "wheezy_vixen" not in rule_ids

    applied_multiply_rules = {
        str(s.get("rule_id", "")).lower()
        for s in trace
        if s.get("phase") == "rule"
        and s.get("applied")
        and "multiply" in str(s.get("effect_type", ""))
    }
    assert "wheezy_vixen" not in applied_multiply_rules
    assert "sunflower" in applied_multiply_rules

    multiply_steps = [s for s in trace if s.get("phase") == "multiply"]
    multiply_rule_ids = {str(s.get("rule_id", "")).lower() for s in multiply_steps}
    assert "wheezy_vixen" not in multiply_rule_ids
    assert "avocado" in multiply_rule_ids
    assert "bento_box" in multiply_rule_ids or "bento box" in multiply_rule_ids


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
    pipeline = ScoringPipeline()
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
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[LoadoutItem(id="yellow_glasses", name="Yellow Glasses", level=1)]
    )
    base, _ = pipeline.score(board, [0, 1, 2], "ene", Loadout())
    score, bd = pipeline.score(board, [0, 1, 2], "ene", loadout)
    assert bd["multiplier"] == 1.0
    assert score == base
