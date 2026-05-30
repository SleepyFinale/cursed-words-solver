"""Octacles unlock stamp catalog and scoring (wiki: Unlocked when unlocking Octacles)."""

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


def test_oden_letter_and_chess_counts_one_category():
    """Letter tiles are not Oden categories; all chess pieces share one bucket."""
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
