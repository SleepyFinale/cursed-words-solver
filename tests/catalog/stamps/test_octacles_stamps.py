"""Octacles unlock stamp catalog and scoring (wiki: Unlocked when unlocking Octacles)."""

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
from cursed_words_solver.rules.rule_lookup import get_rule, slugify_name

from tests.catalog.stamps._coverage import assert_loadout_stamp_coverage

OCTACLES_STAMP_NAMES = [
    "Haunted Mirror",
    "Oden",
]

GRID_ONLY_SLUGS = {
    "haunted_mirror",
}


def _tile(
    row: int,
    col: int,
    ch: str,
    score: int,
    *,
    color=TileColor.COLORLESS,
    curse=CurseType.LETTER,
    number_value=None,
) -> Tile:
    return Tile(
        row=row,
        col=col,
        char=ch,
        letter=ch,
        base_score=score,
        color=color,
        curse=curse,
        number_value=number_value,
        metadata={"source": "melmod"},
    )


def _empty_board() -> Board:
    grid = [[_tile(r, c, "X", 1) for c in range(5)] for r in range(5)]
    return Board(tiles=grid, money=0)


def test_all_octacles_stamps_catalogued():
    pipeline = ScoringPipeline()
    for name in OCTACLES_STAMP_NAMES:
        slug = slugify_name(name)
        _key, rule = get_rule(pipeline.rules, "stamps", slug, name)
        assert rule is not None, slug
        assert rule.get("type") != "unmodeled", slug


def test_count_scoring_vs_grid_only_octacles_stamps():
    pipeline = ScoringPipeline()
    assert_loadout_stamp_coverage(pipeline.rules, OCTACLES_STAMP_NAMES)



def test_haunted_mirror_grid_scatter():
    pipeline = ScoringPipeline()
    _key, rule = get_rule(pipeline.rules, "stamps", "haunted_mirror", "Haunted Mirror")
    assert rule.get("effect_class") == "scatter"


def test_oden_two_curse_types_doubles_word():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "?", 5, curse=CurseType.WILDCARD)
    board.tiles[0][1] = _tile(0, 1, "2", 5, curse=CurseType.NUMBER, number_value=2)
    pipeline = ScoringPipeline()
    loadout = Loadout(stamps=[LoadoutItem(id="oden", name="Oden", kind="stamp")])
    score, bd = pipeline.score(board, [0, 1], "?2", loadout)
    assert bd["multiplier"] == 2.0
    assert score == 20


def test_oden_three_curse_types_triples_word():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "?", 4, curse=CurseType.WILDCARD)
    board.tiles[0][1] = _tile(0, 1, "2", 4, curse=CurseType.NUMBER, number_value=2)
    board.tiles[0][2] = Tile(
        0,
        2,
        "p",
        "?",
        4,
        TileColor.COLORLESS,
        CurseType.CHESS_PAWN,
        metadata={"chess_color": "white"},
    )
    pipeline = ScoringPipeline()
    loadout = Loadout(stamps=[LoadoutItem(id="oden", name="Oden", kind="stamp")])
    score, bd = pipeline.score(board, [0, 1, 2], "?2p", loadout)
    assert bd["multiplier"] == 3.0
    assert score == 36


def test_oden_letter_and_chess_counts_two_categories():
    """Two letter tiles plus chess → letter + chess_knight (×2)."""
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "Q", 10, curse=CurseType.LETTER)
    board.tiles[0][1] = _tile(0, 1, "U", 1, curse=CurseType.LETTER)
    board.tiles[0][2] = Tile(
        0,
        2,
        "?",
        "?",
        3,
        TileColor.COLORLESS,
        CurseType.CHESS_KNIGHT,
        metadata={"chess_color": "white"},
    )
    pipeline = ScoringPipeline()
    loadout = Loadout(stamps=[LoadoutItem(id="oden", name="Oden", kind="stamp")])
    score, bd = pipeline.score(board, [0, 1, 2], "quk", loadout)
    assert bd["multiplier"] == 2.0
    assert score == 28.0


def test_oden_single_letter_and_chess_counts_chess_only():
    """One letter tile does not activate the letter Oden bucket."""
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "Q", 10, curse=CurseType.LETTER)
    board.tiles[0][1] = Tile(
        0,
        1,
        "?",
        "?",
        3,
        TileColor.COLORLESS,
        CurseType.CHESS_KNIGHT,
        metadata={"chess_color": "white"},
    )
    pipeline = ScoringPipeline()
    loadout = Loadout(stamps=[LoadoutItem(id="oden", name="Oden", kind="stamp")])
    score, bd = pipeline.score(board, [0, 1], "qk", loadout)
    assert bd["multiplier"] == 1.0
    assert score == 13.0


def test_oden_currency_and_letters_doubles_word():
    """Mismatch 20260607_120420: 2+ letter tiles + currency → Oden ×2."""
    from cursed_words_solver.rules.scoring_conditions import unique_curse_type_count_on_path

    board = _empty_board()
    board.tiles[0][0] = Tile(
        0,
        0,
        "€",
        "€",
        0,
        TileColor.COLORLESS,
        CurseType.CURRENCY,
    )
    board.tiles[0][1] = _tile(0, 1, "N", 1)
    board.tiles[0][2] = _tile(0, 2, "S", 1)
    path = [0, 1, 2]
    assert unique_curse_type_count_on_path(board, path) == 2

    pipeline = ScoringPipeline()
    loadout = Loadout(stamps=[LoadoutItem(id="oden", name="Oden", kind="stamp")])
    score, bd = pipeline.score(board, path, "ens", loadout)
    assert bd["multiplier"] == 2.0
    assert score == 4.0
    assert any("×2.0 word (2 unique curse type(s))" in e for e in bd["pipeline"]["effects"])


def test_oden_joker_wildcard_is_card_category():
    """Joker ? tiles count as Cards; plain ? tiles count as Wild Tiles (separate Oden buckets)."""
    board = _empty_board()
    board.tiles[0][0] = Tile(
        0,
        0,
        "🃏",
        "?",
        1,
        TileColor.BLUE,
        CurseType.WILDCARD,
        metadata={"is_joker": True, "card_suit": "joker"},
    )
    board.tiles[0][1] = _tile(0, 1, "?", 1, curse=CurseType.WILDCARD)
    board.tiles[0][2] = Tile(
        0,
        2,
        "j",
        "?",
        4,
        TileColor.COLORLESS,
        CurseType.CHESS_KNIGHT,
        metadata={"chess_color": "white"},
    )
    pipeline = ScoringPipeline()
    loadout = Loadout(stamps=[LoadoutItem(id="oden", name="Oden", kind="stamp")])
    score, bd = pipeline.score(board, [0, 1, 2], "???", loadout)
    assert bd["multiplier"] == 3.0
    assert score == bd["tile_total"] * bd["multiplier"]


def test_oden_checkstop_path_categories():
    """Regression: checkstop path mixes joker wilds, plain wild, chess, item, currency → ×5."""
    from cursed_words_solver.rules.scoring_conditions import unique_curse_type_count_on_path

    board = _empty_board()
    board.tiles[1][3] = Tile(
        1,
        3,
        "🃏",
        "?",
        1,
        TileColor.BLUE,
        CurseType.WILDCARD,
        metadata={"is_joker": True, "card_suit": "joker"},
    )
    board.tiles[1][2] = Tile(
        1,
        2,
        "🃏",
        "?",
        0,
        TileColor.VOID,
        CurseType.WILDCARD,
        metadata={"is_joker": True, "card_suit": "joker"},
    )
    board.tiles[1][1] = Tile(
        1,
        1,
        "j",
        "?",
        4,
        TileColor.BLUE,
        CurseType.CHESS_KNIGHT,
        metadata={"chess_color": "black"},
    )
    board.tiles[1][0] = Tile(
        1,
        0,
        "?",
        "?",
        1,
        TileColor.BLUE,
        CurseType.WILDCARD,
        metadata={"card_suit": "diamonds"},
    )
    board.tiles[3][2] = Tile(
        3,
        2,
        "💥",
        "?",
        0,
        TileColor.BLUE,
        CurseType.ITEM,
        metadata={"scattered_item_id": "big_bang"},
    )
    board.tiles[4][1] = Tile(
        4,
        1,
        "₱",
        "₱",
        50,
        TileColor.SHINY,
        CurseType.CURRENCY,
    )
    path = [8, 7, 6, 5, 17, 21]
    assert unique_curse_type_count_on_path(board, path) == 5


def test_oden_suited_number_adds_card_category():
    """Isolated suited NUMBER still contributes card when the letter bucket is inactive."""
    from cursed_words_solver.rules.scoring_conditions import unique_curse_type_count_on_path

    board = _empty_board()
    board.tiles[0][0] = _tile(
        0,
        0,
        "7",
        7,
        curse=CurseType.NUMBER,
        number_value=7,
    )
    board.tiles[0][0].metadata["card_suit"] = "hearts"
    board.tiles[0][0].metadata["card_rank"] = "7"
    assert unique_curse_type_count_on_path(board, [0]) == 2


def test_oden_two_chess_pieces_count_separately():
    from cursed_words_solver.rules.scoring_conditions import unique_curse_type_count_on_path

    board = _empty_board()
    board.tiles[1][0] = Tile(
        1,
        0,
        "?",
        "?",
        0,
        TileColor.COLORLESS,
        CurseType.WILDCARD,
    )
    board.tiles[2][0] = Tile(
        2,
        0,
        "?",
        "?",
        3,
        TileColor.COLORLESS,
        CurseType.CHESS_BISHOP,
    )
    board.tiles[1][2] = Tile(
        1,
        2,
        "?",
        "?",
        15,
        TileColor.COLORLESS,
        CurseType.CHESS_KING,
    )
    board.tiles[2][3] = Tile(
        2,
        3,
        "€",
        "€",
        0,
        TileColor.COLORLESS,
        CurseType.CURRENCY,
    )
    path = [5, 10, 7, 13]
    assert unique_curse_type_count_on_path(board, path) == 4


def test_oden_bottega_path_six_categories():
    """Mismatch 20260607_115833: wildcard + bishop + king + currency + suited number → ×6."""
    from cursed_words_solver.rules.scoring_conditions import unique_curse_type_count_on_path

    board = _empty_board()
    board.tiles[1][0] = Tile(
        1,
        0,
        "?",
        "?",
        0,
        TileColor.COLORLESS,
        CurseType.WILDCARD,
    )
    board.tiles[2][0] = Tile(
        2,
        0,
        "?",
        "?",
        3,
        TileColor.COLORLESS,
        CurseType.CHESS_BISHOP,
    )
    board.tiles[3][0] = _tile(3, 0, "T", 1)
    board.tiles[1][2] = Tile(
        1,
        2,
        "?",
        "?",
        15,
        TileColor.COLORLESS,
        CurseType.CHESS_KING,
    )
    board.tiles[2][3] = Tile(
        2,
        3,
        "€",
        "€",
        0,
        TileColor.COLORLESS,
        CurseType.CURRENCY,
    )
    board.tiles[1][3] = _tile(1, 3, "G", 2)
    board.tiles[0][3] = Tile(
        0,
        3,
        "7",
        "7",
        7,
        TileColor.COLORLESS,
        CurseType.NUMBER,
        number_value=7,
        metadata={"card_suit": "hearts", "card_rank": "7"},
    )
    path = [5, 10, 2, 7, 13, 8, 3]
    assert unique_curse_type_count_on_path(board, path) == 6

    pipeline = ScoringPipeline()
    loadout = Loadout(stamps=[LoadoutItem(id="oden", name="Oden", kind="stamp")])
    score, bd = pipeline.score(board, path, "bottega", loadout)
    assert bd["multiplier"] == 6.0
    assert score == bd["tile_total"] * bd["multiplier"]


def test_oden_checkstop_score_regression():
    """Round log 20260530_153609: oden ×5 (not ×4) with poker ×3 and broom ×2."""
    board = _empty_board()
    board.tiles[1][3] = Tile(
        1,
        3,
        "🃏",
        "?",
        1,
        TileColor.BLUE,
        CurseType.WILDCARD,
        metadata={"is_joker": True, "card_suit": "joker"},
    )
    board.tiles[1][2] = Tile(
        1,
        2,
        "🃏",
        "?",
        0,
        TileColor.VOID,
        CurseType.WILDCARD,
        metadata={"is_joker": True, "card_suit": "joker"},
    )
    board.tiles[1][1] = Tile(
        1,
        1,
        "j",
        "?",
        4,
        TileColor.BLUE,
        CurseType.CHESS_KNIGHT,
        metadata={"chess_color": "black", "card_suit": "diamonds"},
    )
    board.tiles[3][0] = _tile(3, 0, "C", 50, color=TileColor.SHINY)
    board.tiles[3][1] = Tile(
        3,
        1,
        "j",
        "?",
        4,
        TileColor.BLUE,
        CurseType.CHESS_KNIGHT,
        metadata={"chess_color": "black", "card_suit": "diamonds"},
    )
    board.tiles[1][0] = Tile(
        1,
        0,
        "?",
        "?",
        1,
        TileColor.BLUE,
        CurseType.WILDCARD,
        metadata={"card_suit": "diamonds"},
    )
    board.tiles[2][1] = _tile(2, 1, "T", 1)
    board.tiles[3][2] = Tile(
        3,
        2,
        "💥",
        "?",
        0,
        TileColor.BLUE,
        CurseType.ITEM,
        metadata={"scattered_item_id": "big_bang", "card_suit": "joker"},
    )
    board.tiles[4][1] = Tile(
        4,
        1,
        "₱",
        "₱",
        50,
        TileColor.SHINY,
        CurseType.CURRENCY,
    )
    path = [8, 7, 6, 15, 16, 5, 11, 17, 21]
    loadout = Loadout(
        stickers=[
            LoadoutItem(id="poker_face", name="Poker Face", level=2),
            LoadoutItem(id="broom", name="Broom", level=2),
        ],
        stamps=[LoadoutItem(id="oden", name="Oden", kind="stamp")],
        extras={"pin_effect": "bucket"},
    )
    pipeline = ScoringPipeline()
    score, bd = pipeline.score(board, path, "checkstop", loadout)
    assert bd["multiplier"] == 30.0
    assert score == bd["tile_total"] * bd["multiplier"]
    assert any("×5.0 word (5 unique curse type(s))" in e for e in bd["pipeline"]["effects"])


def test_creaky_chair_pouffing_regression():
    """Round log 20260530_162804: curse_types_gte uses Oden buckets (card+wildcard+number → ×2 creaky)."""
    from cursed_words_solver.rules.scoring_conditions import (
        evaluate_sticker_condition,
        unique_curse_type_count_on_path,
    )

    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "F", 50, color=TileColor.SHINY)
    board.tiles[0][3] = Tile(
        0,
        3,
        "🃏",
        "?",
        0,
        TileColor.VOID,
        CurseType.WILDCARD,
        metadata={"source": "melmod", "is_joker": True, "card_suit": "joker"},
    )
    board.tiles[0][4] = _tile(0, 4, "?", 1, color=TileColor.BLUE, curse=CurseType.WILDCARD)
    board.tiles[1][1] = Tile(
        1,
        1,
        "🃏",
        "?",
        1,
        TileColor.RED,
        CurseType.WILDCARD,
        metadata={"source": "melmod", "is_joker": True, "card_suit": "joker"},
    )
    board.tiles[1][2] = Tile(
        1,
        2,
        "🃏",
        "?",
        0,
        TileColor.VOID,
        CurseType.WILDCARD,
        metadata={"source": "melmod", "is_joker": True, "card_suit": "joker"},
    )
    board.tiles[1][4] = _tile(1, 4, "?", 50, color=TileColor.SHINY, curse=CurseType.WILDCARD)
    board.tiles[2][4] = Tile(
        2,
        4,
        "?",
        "?",
        50,
        TileColor.SHINY,
        CurseType.WILDCARD,
        metadata={"card_suit": "clubs"},
    )
    board.tiles[3][3] = _tile(
        3,
        3,
        "8",
        9,
        color=TileColor.RED,
        curse=CurseType.NUMBER,
        number_value=8,
    )
    path = [3, 7, 6, 0, 4, 9, 14, 18]
    loadout = Loadout(
        stickers=[
            LoadoutItem(id="creaky_chair", name="Creaky Chair", level=1),
            LoadoutItem(id="broom", name="Broom", level=3),
            LoadoutItem(id="poker_face", name="Poker Face", level=3),
        ],
        stamps=[
            LoadoutItem(id="oden", name="Oden", kind="stamp"),
            LoadoutItem(id="dango", name="Dango", kind="stamp"),
        ],
        extras={"pin_effect": "bucket"},
    )
    assert unique_curse_type_count_on_path(board, path) == 3
    assert evaluate_sticker_condition(
        "curse_types_gte:3", board, path, "pouffing", loadout
    )
    pipeline = ScoringPipeline()
    score, bd = pipeline.score(board, path, "pouffing", loadout)
    assert bd["tile_total"] == 161
    assert bd["multiplier"] == 240.0
    assert score == 38640


def test_oden_whatas_path_five_categories():
    """Mismatch 20260607_122219: letter + rook + fraction + item + card suit → ×5."""
    from cursed_words_solver.rules.scoring_conditions import unique_curse_type_count_on_path

    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "h", 4)
    board.tiles[0][1] = Tile(
        0,
        1,
        "1/3",
        "0.3333333",
        4,
        TileColor.COLORLESS,
        CurseType.FRACTION,
        fraction_value=1 / 3,
        metadata={"source": "melmod"},
    )
    board.tiles[0][2] = Tile(
        0,
        2,
        "?",
        "?",
        0,
        TileColor.COLORLESS,
        CurseType.ITEM,
        metadata={
            "source": "melmod",
            "scattered_item_id": "lucky_scarf",
            "card_suit": "hearts",
        },
    )
    board.tiles[1][0] = Tile(
        1,
        0,
        "?",
        "?",
        5,
        TileColor.COLORLESS,
        CurseType.CHESS_ROOK,
        metadata={"source": "melmod", "chess_color": "black"},
    )
    board.tiles[1][1] = _tile(1, 1, "t", 1)
    board.tiles[1][2] = _tile(1, 2, "a", 1)
    path = [5, 0, 1, 6, 7, 2]
    assert unique_curse_type_count_on_path(board, path) == 5

    loadout = Loadout(
        stickers=[
            LoadoutItem(id="amphora", name="Amphora", level=3),
            LoadoutItem(id="hi_vis_jacket", name="Hi Vis Jacket", level=3),
            LoadoutItem(id="newspaper", name="Newspaper", level=1),
            LoadoutItem(id="creaky_chair", name="Creaky Chair", level=1),
            LoadoutItem(id="broom", name="Broom", level=1),
        ],
        stamps=[LoadoutItem(id="oden", name="Oden", kind="stamp")],
        extras={
            "birthday_cake_bonus": "21",
            "pin_effect": "random_access_memory",
            "pin_memory": (
                '[{"id":"birthday_cake","name":"Birthday Cake","level":1,'
                '"kind":"sticker","birthday_cake_bonus":21}]'
            ),
            "consumable_rack_count": "5",
        },
    )
    pipeline = ScoringPipeline()
    score, bd = pipeline.score(board, path, "whatas", loadout)
    assert score == 3330
    assert any("×5.0 word (5 unique curse type(s))" in e for e in bd["pipeline"]["effects"])
    assert any("Birthday Cake: 21 + 1" in e for e in bd["pipeline"]["effects"])


def test_oden_dhaba_letter_suppressed_when_letter_has_suit():
    """Mismatch 20260607_125551: suited letter tile → letter bucket suppressed → Oden ×4."""
    from cursed_words_solver.rules.scoring_conditions import unique_curse_type_count_on_path

    board = _empty_board()
    board.tiles[4][2] = Tile(
        4,
        2,
        "?",
        "?",
        0,
        TileColor.COLORLESS,
        CurseType.ITEM,
        metadata={"source": "melmod", "scattered_item_id": "brain"},
    )
    board.tiles[3][2] = Tile(
        3,
        2,
        "l",
        "?",
        15,
        TileColor.COLORLESS,
        CurseType.CHESS_KING,
        metadata={"source": "melmod", "chess_color": "black"},
    )
    board.tiles[2][1] = _tile(2, 1, "a", 1)
    board.tiles[3][1] = Tile(
        3,
        1,
        "?",
        "?",
        0,
        TileColor.COLORLESS,
        CurseType.WILDCARD,
        metadata={"source": "melmod", "card_suit": "spades"},
    )
    board.tiles[2][0] = Tile(
        2,
        0,
        "a",
        "A",
        1,
        TileColor.COLORLESS,
        CurseType.LETTER,
        metadata={"source": "melmod", "card_suit": "spades", "card_rank": "A"},
    )
    path = [22, 17, 11, 16, 10]
    assert unique_curse_type_count_on_path(board, path) == 4

    loadout = Loadout(
        stickers=[
            LoadoutItem(id="hi_vis_jacket", name="Hi Vis Jacket", level=3),
            LoadoutItem(id="newspaper", name="Newspaper", level=2),
            LoadoutItem(id="creaky_chair", name="Creaky Chair", level=1),
        ],
        stamps=[LoadoutItem(id="oden", name="Oden", kind="stamp")],
        extras={
            "birthday_cake_bonus": "26",
            "pin_effect": "random_access_memory",
            "pin_memory": (
                '[{"id":"birthday_cake","name":"Birthday Cake","level":1,'
                '"kind":"sticker","birthday_cake_bonus":26}]'
            ),
            "consumable_rack_count": "5",
        },
    )
    pipeline = ScoringPipeline()
    score, bd = pipeline.score(board, path, "dhaba", loadout)
    assert any("×4.0 word (4 unique curse type(s))" in e for e in bd["pipeline"]["effects"])


def test_oden_koala_path_four_categories():
    """Mismatch 20260607_132057: suited currency + 2 letters + number + wildcard → Oden ×4."""
    from cursed_words_solver.rules.scoring_conditions import unique_curse_type_count_on_path

    board = _empty_board()
    board.tiles[3][0] = Tile(
        3,
        0,
        "\u20ad",
        "\u20ad",
        0,
        TileColor.COLORLESS,
        CurseType.CURRENCY,
        metadata={"source": "melmod", "card_suit": "hearts", "card_rank": "\u20ad"},
    )
    board.tiles[3][4] = _tile(3, 4, "o", 1)
    board.tiles[3][3] = _tile(3, 3, "a", 1)
    board.tiles[4][2] = Tile(
        4,
        2,
        "4",
        "4",
        4,
        TileColor.COLORLESS,
        CurseType.NUMBER,
        number_value=4,
        metadata={"source": "melmod"},
    )
    board.tiles[4][3] = Tile(
        4,
        3,
        "?",
        "?",
        0,
        TileColor.COLORLESS,
        CurseType.WILDCARD,
        metadata={"source": "melmod", "card_suit": "clubs"},
    )
    path = [15, 19, 18, 22, 23]
    assert unique_curse_type_count_on_path(board, path) == 4

    loadout = Loadout(
        stickers=[
            LoadoutItem(id="hi_vis_jacket", name="Hi Vis Jacket", level=3),
            LoadoutItem(id="creaky_chair", name="Creaky Chair", level=1),
            LoadoutItem(id="broom", name="Broom", level=3),
        ],
        stamps=[LoadoutItem(id="oden", name="Oden", kind="stamp")],
        extras={
            "birthday_cake_bonus": "31",
            "pin_effect": "random_access_memory",
            "pin_memory": (
                '[{"id":"birthday_cake","name":"Birthday Cake","level":1,'
                '"kind":"sticker","birthday_cake_bonus":31}]'
            ),
            "consumable_rack_count": "5",
        },
    )
    pipeline = ScoringPipeline()
    score, bd = pipeline.score(board, path, "koala", loadout)
    assert any("×4.0 word (4 unique curse type(s))" in e for e in bd["pipeline"]["effects"])


def test_oden_haufs_path_four_categories():
    """Mismatch 20260607_133215: suited knight must not add card; letter suppressed → Oden ×4."""
    from cursed_words_solver.rules.scoring_conditions import unique_curse_type_count_on_path

    board = _empty_board()
    board.tiles[1][1] = Tile(
        1,
        1,
        "1",
        "1",
        1,
        TileColor.COLORLESS,
        CurseType.NUMBER,
        number_value=1,
        metadata={"source": "melmod"},
    )
    board.tiles[1][2] = Tile(
        1,
        2,
        "j",
        "?",
        0,
        TileColor.VOID,
        CurseType.CHESS_KNIGHT,
        metadata={"source": "melmod", "chess_color": "black", "card_suit": "hearts"},
    )
    board.tiles[3][3] = _tile(3, 3, "u", 1)
    board.tiles[4][4] = Tile(
        4,
        4,
        "🎸",
        "?",
        0,
        TileColor.COLORLESS,
        CurseType.ITEM,
        metadata={
            "source": "melmod",
            "scattered_item_id": "electric_guitar",
            "scattered_item_level": 1,
        },
    )
    board.tiles[4][3] = Tile(
        4,
        3,
        "l",
        "?",
        15,
        TileColor.COLORLESS,
        CurseType.CHESS_KING,
        metadata={"source": "melmod", "chess_color": "black"},
    )
    path = [6, 7, 18, 24, 23]
    assert unique_curse_type_count_on_path(board, path) == 4

    loadout = Loadout(stamps=[LoadoutItem(id="oden", name="Oden", kind="stamp")])
    pipeline = ScoringPipeline()
    _score, bd = pipeline.score(board, path, "haufs", loadout)
    assert any("×4.0 word (4 unique curse type(s))" in e for e in bd["pipeline"]["effects"])


def test_oden_ywroke_path_five_categories():
    """Mismatch 20260607_133025: item-only suit card dropped with 0 letters → Oden ×5."""
    from cursed_words_solver.rules.scoring_conditions import unique_curse_type_count_on_path

    board = _empty_board()
    board.tiles[0][1] = Tile(
        0,
        1,
        "¥",
        "¥",
        0,
        TileColor.COLORLESS,
        CurseType.CURRENCY,
        metadata={"source": "melmod"},
    )
    board.tiles[0][0] = Tile(
        0,
        0,
        "r",
        "?",
        5,
        TileColor.COLORLESS,
        CurseType.CHESS_ROOK,
        metadata={"source": "melmod", "chess_color": "white"},
    )
    board.tiles[0][3] = Tile(
        0,
        3,
        "?",
        "?",
        0,
        TileColor.COLORLESS,
        CurseType.WILDCARD,
        metadata={"source": "melmod"},
    )
    board.tiles[1][3] = Tile(
        1,
        3,
        "🎸",
        "?",
        0,
        TileColor.COLORLESS,
        CurseType.ITEM,
        metadata={
            "source": "melmod",
            "scattered_item_id": "electric_guitar",
            "scattered_item_level": 1,
            "card_suit": "diamonds",
        },
    )
    board.tiles[2][4] = Tile(
        2,
        4,
        "b",
        "?",
        3,
        TileColor.COLORLESS,
        CurseType.CHESS_BISHOP,
        metadata={"source": "melmod", "chess_color": "white"},
    )
    board.tiles[4][2] = Tile(
        4,
        2,
        "?",
        "?",
        0,
        TileColor.COLORLESS,
        CurseType.WILDCARD,
        metadata={"source": "melmod", "card_suit": "spades"},
    )
    path = [1, 0, 3, 8, 14, 22]
    assert unique_curse_type_count_on_path(board, path) == 5

    loadout = Loadout(
        stickers=[
            LoadoutItem(id="amphora", name="Amphora", level=4),
            LoadoutItem(id="hi_vis_jacket", name="Hi Vis Jacket", level=2),
            LoadoutItem(id="creaky_chair", name="Creaky Chair", level=1),
            LoadoutItem(id="broom", name="Broom", level=2),
        ],
        stamps=[
            LoadoutItem(id="golden_record", name="Golden Record", kind="stamp"),
            LoadoutItem(id="full_moon", name="Full Moon", kind="stamp"),
            LoadoutItem(id="hungry_snake", name="Hungry Snake", kind="stamp"),
            LoadoutItem(id="oden", name="Oden", kind="stamp"),
            LoadoutItem(id="number_factory", name="Number Factory", kind="stamp"),
        ],
        extras={
            "birthday_cake_bonus": "27",
            "pin_effect": "random_access_memory",
            "pin_memory": (
                '[{"id":"birthday_cake","name":"Birthday Cake","level":1,'
                '"kind":"sticker","birthday_cake_bonus":27}]'
            ),
            "consumable_rack_count": "5",
        },
    )
    pipeline = ScoringPipeline()
    score, bd = pipeline.score(board, path, "ywroke", loadout)
    assert any("×5.0 word (5 unique curse type(s))" in e for e in bd["pipeline"]["effects"])


def test_birthday_improve_uses_fraction_ceil():
    """Fraction tiles contribute ceil(numerator/denominator) to Birthday improve."""
    from cursed_words_solver.rules.scoring_conditions import birthday_cake_improve_for_path

    pipeline = ScoringPipeline()
    _key, rule = get_rule(pipeline.rules, "stickers", "birthday_cake", "Birthday Cake")

    def _fraction_at(col: int, glyph: str, face: str, value: float) -> None:
        board.tiles[0][col] = Tile(
            0,
            col,
            glyph,
            face,
            4,
            TileColor.COLORLESS,
            CurseType.FRACTION,
            fraction_value=value,
            metadata={"source": "melmod"},
        )

    board = _empty_board()
    _fraction_at(1, "1/3", "0.3333333", 1 / 3)
    assert birthday_cake_improve_for_path(board, [1], level=1, rule=rule) == 1

    board = _empty_board()
    _fraction_at(1, "2/3", "0.6666667", 2 / 3)
    assert birthday_cake_improve_for_path(board, [1], level=1, rule=rule) == 1

    board = _empty_board()
    _fraction_at(1, "4/5", "0.8", 4 / 5)
    assert birthday_cake_improve_for_path(board, [1], level=1, rule=rule) == 1

    board = _empty_board()
    _fraction_at(1, "\u215b", "0.125", 1 / 8)
    assert birthday_cake_improve_for_path(board, [1], level=1, rule=rule) == 0

    board = _empty_board()
    _fraction_at(1, "\u2150", "0.1428571", 1 / 7)
    assert birthday_cake_improve_for_path(board, [1], level=1, rule=rule) == 1


def test_oden_ippon_path_three_categories():
    """Mismatch 20260607_134340: suited NUMBER/FRACTION tiles use number bucket only → ×3."""
    from cursed_words_solver.loadout import (
        parse_board_from_run_state,
        parse_run_state,
        prepare_run_state_dict_for_scoring,
    )
    from cursed_words_solver.rules.scoring_conditions import unique_curse_type_count_on_path

    fixture = (
        Path(__file__).resolve().parents[2]
        / "fixtures"
        / "mismatches"
        / "20260607_134340.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    run_state = prepare_run_state_dict_for_scoring(data["run_state_snapshot"])
    board = parse_board_from_run_state(run_state)
    path = data["path"]
    assert unique_curse_type_count_on_path(board, path) == 3
    loadout = parse_run_state(run_state)
    score, _ = ScoringPipeline().score(board, path, data["word"], loadout)
    assert int(score) == data["actual_score"]


def test_oden_teggs_path_four_categories():
    """Mismatch 20260607_134502: scattered-item card suit does not add card bucket → ×4."""
    from cursed_words_solver.loadout import (
        parse_board_from_run_state,
        parse_run_state,
        prepare_run_state_dict_for_scoring,
    )
    from cursed_words_solver.rules.scoring_conditions import unique_curse_type_count_on_path

    fixture = (
        Path(__file__).resolve().parents[2]
        / "fixtures"
        / "mismatches"
        / "20260607_134502.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    run_state = prepare_run_state_dict_for_scoring(data["run_state_snapshot"])
    board = parse_board_from_run_state(run_state)
    path = data["path"]
    assert unique_curse_type_count_on_path(board, path) == 4
    loadout = parse_run_state(run_state)
    score, _ = ScoringPipeline().score(board, path, data["word"], loadout)
    assert int(score) == data["actual_score"]


def test_oden_lyne_golden_record_skips_oden_mult():
    """Mismatch 20260607_135939: GR short word, no letters → Oden skipped, not ×3."""
    from cursed_words_solver.loadout import (
        parse_board_from_run_state,
        parse_run_state,
        prepare_run_state_dict_for_scoring,
    )
    from cursed_words_solver.rules.scoring_conditions import (
        letter_tile_count_on_path,
        unique_curse_type_count_on_path,
    )

    fixture = (
        Path(__file__).resolve().parents[2]
        / "fixtures"
        / "mismatches"
        / "20260607_135939.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    run_state = prepare_run_state_dict_for_scoring(data["run_state_snapshot"])
    board = parse_board_from_run_state(run_state)
    path = data["path"]
    assert letter_tile_count_on_path(board, path) == 0
    assert unique_curse_type_count_on_path(board, path) == 3
    pipeline = ScoringPipeline()
    score, bd = pipeline.score(board, path, data["word"], parse_run_state(run_state))
    effects = bd["pipeline"]["effects"]
    assert not any("oden" in e.lower() and "×" in e for e in effects)
    assert int(score) != 2970


def test_oden_upsprings_path_seven_categories():
    """Mismatch 20260607_140102: long path keeps letter bucket → Oden ×7."""
    from cursed_words_solver.loadout import (
        parse_board_from_run_state,
        parse_run_state,
        prepare_run_state_dict_for_scoring,
    )
    from cursed_words_solver.rules.scoring_conditions import unique_curse_type_count_on_path

    fixture = (
        Path(__file__).resolve().parents[2]
        / "fixtures"
        / "mismatches"
        / "20260607_140102.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    run_state = prepare_run_state_dict_for_scoring(data["run_state_snapshot"])
    board = parse_board_from_run_state(run_state)
    path = data["path"]
    assert len(path) > 5
    assert unique_curse_type_count_on_path(board, path) == 7
    loadout = parse_run_state(run_state)
    score, bd = ScoringPipeline().score(board, path, data["word"], loadout)
    assert any("×7.0 word (7 unique curse type(s))" in e for e in bd["pipeline"]["effects"])


def test_oden_kaeing_michael_yeti_four_categories():
    """Mismatch 20260607_141217: suited letter merges card bucket → Oden ×4."""
    from cursed_words_solver.loadout import (
        parse_board_from_run_state,
        prepare_run_state_dict_for_scoring,
    )
    from cursed_words_solver.rules.scoring_conditions import unique_curse_type_count_on_path

    fixture = (
        Path(__file__).resolve().parents[2]
        / "fixtures"
        / "mismatches"
        / "20260607_141217.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    run_state = prepare_run_state_dict_for_scoring(data["run_state_snapshot"])
    board = parse_board_from_run_state(run_state)
    path = data["path"]
    assert unique_curse_type_count_on_path(board, path) == 4


def test_oden_unfrock_dense_path_four_categories():
    """Mismatch 20260607_141348: dense path drops letter bucket → Oden ×4."""
    from cursed_words_solver.loadout import (
        parse_board_from_run_state,
        prepare_run_state_dict_for_scoring,
    )
    from cursed_words_solver.rules.scoring_conditions import unique_curse_type_count_on_path

    fixture = (
        Path(__file__).resolve().parents[2]
        / "fixtures"
        / "mismatches"
        / "20260607_141348.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    run_state = prepare_run_state_dict_for_scoring(data["run_state_snapshot"])
    board = parse_board_from_run_state(run_state)
    path = data["path"]
    assert len(path) == 7
    assert unique_curse_type_count_on_path(board, path) == 4


def test_oden_tranqs_axolotl_three_categories():
    """Mismatch 20260607_141716: axolotl Q path merges suited letter card → Oden ×3."""
    from cursed_words_solver.loadout import (
        parse_board_from_run_state,
        prepare_run_state_dict_for_scoring,
    )
    from cursed_words_solver.rules.scoring_conditions import unique_curse_type_count_on_path

    fixture = (
        Path(__file__).resolve().parents[2]
        / "fixtures"
        / "mismatches"
        / "20260607_141716.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    run_state = prepare_run_state_dict_for_scoring(data["run_state_snapshot"])
    board = parse_board_from_run_state(run_state)
    path = data["path"]
    assert unique_curse_type_count_on_path(board, path) == 3


def test_golden_record_upon_all_letters_full_subtotal():
    """Mismatch 20260607_142006: one letter path uses full subtotal, not word-only."""
    from cursed_words_solver.loadout import (
        parse_board_from_run_state,
        parse_run_state,
        prepare_run_state_dict_for_scoring,
    )
    from cursed_words_solver.rules.scoring_conditions import (
        golden_record_multiplies_word_score_only,
        letter_tile_count_on_path,
    )

    fixture = (
        Path(__file__).resolve().parents[2]
        / "fixtures"
        / "mismatches"
        / "20260607_142006.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    run_state = prepare_run_state_dict_for_scoring(data["run_state_snapshot"])
    board = parse_board_from_run_state(run_state)
    path = data["path"]
    loadout = parse_run_state(run_state)
    assert letter_tile_count_on_path(board, path) == 1
    state = {"tile_scores": [0.0, 15.0, 1.0, 0.0], "word_score": 57.0}
    assert not golden_record_multiplies_word_score_only(loadout, board, path, state)
