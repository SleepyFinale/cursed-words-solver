"""Octacles unlock stamp catalog and scoring (wiki: Unlocked when unlocking Octacles)."""



from cursed_words_solver.models import Board, CurseType, Loadout, LoadoutItem, Tile, TileColor
from cursed_words_solver.engine.scorer import EngineScorer
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
    pipeline = EngineScorer()
    for name in OCTACLES_STAMP_NAMES:
        slug = slugify_name(name)
        _key, rule = get_rule(pipeline.rules, "stamps", slug, name)
        assert rule is not None, slug
        assert rule.get("type") != "unmodeled", slug


def test_count_scoring_vs_grid_only_octacles_stamps():
    pipeline = EngineScorer()
    assert_loadout_stamp_coverage(pipeline.rules, OCTACLES_STAMP_NAMES)


def test_haunted_mirror_grid_scatter():
    pipeline = EngineScorer()
    _key, rule = get_rule(pipeline.rules, "stamps", "haunted_mirror", "Haunted Mirror")
    assert rule.get("effect_class") == "scatter"


def test_oden_joker_wildcard_with_chess_doubles_not_triples():
    """Single joker wildcard + chess → ×2 (card + chess), not ×3 with spurious blank."""
    board = _empty_board()
    board.tiles[0][0] = Tile(
        0,
        0,
        "🃏",
        "?",
        0,
        TileColor.COLORLESS,
        CurseType.WILDCARD,
        metadata={"is_joker": True, "card_suit": "joker"},
    )
    board.tiles[0][1] = Tile(
        0,
        1,
        "k",
        "?",
        9,
        TileColor.COLORLESS,
        CurseType.CHESS_KNIGHT,
        metadata={"chess_color": "white"},
    )
    pipeline = EngineScorer()
    loadout = Loadout(stamps=[LoadoutItem(id="oden", name="Oden", kind="stamp")])
    score, bd = pipeline.score(board, [0, 1], "??", loadout)
    assert bd["multiplier"] == 2.0
    assert score == bd["tile_total"] * bd["multiplier"]
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "?", 5, curse=CurseType.WILDCARD)
    board.tiles[0][1] = _tile(0, 1, "2", 5, curse=CurseType.NUMBER, number_value=2)
    pipeline = EngineScorer()
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
    pipeline = EngineScorer()
    loadout = Loadout(stamps=[LoadoutItem(id="oden", name="Oden", kind="stamp")])
    score, bd = pipeline.score(board, [0, 1, 2], "?2p", loadout)
    assert bd["multiplier"] == 3.0
    assert score == 36


def test_oden_letter_and_chess_counts_chess_only():
    """Plain letters have no CurseType in game; only chess contributes → no Oden mult."""
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
    pipeline = EngineScorer()
    loadout = Loadout(stamps=[LoadoutItem(id="oden", name="Oden", kind="stamp")])
    score, bd = pipeline.score(board, [0, 1, 2], "quk", loadout)
    assert bd["multiplier"] == 1.0
    assert score == 14.0


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
    pipeline = EngineScorer()
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
    pipeline = EngineScorer()
    loadout = Loadout(stamps=[LoadoutItem(id="oden", name="Oden", kind="stamp")])
    score, bd = pipeline.score(board, [0, 1, 2], "???", loadout)
    assert bd["multiplier"] == 3.0
    assert score == bd["tile_total"] * bd["multiplier"]


def test_birthday_improve_uses_fraction_ceil():
    """Fraction tiles contribute ceil(numerator/denominator) to Birthday improve."""
    from cursed_words_solver.rules.scoring_conditions import birthday_cake_improve_for_path

    pipeline = EngineScorer()
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


def test_birthday_improve_counts_playing_card_number_tile():
    """Mismatch 20260708_131219: spades-8 NUMBER on path counts toward Birthday improve."""
    from cursed_words_solver.models import CurseType, Tile, TileColor
    from cursed_words_solver.rules.scoring_conditions import birthday_cake_improve_for_path

    pipeline = EngineScorer()
    _key, rule = get_rule(pipeline.rules, "stickers", "birthday_cake", "Birthday Cake")

    board = _empty_board()
    board.tiles[3][4] = Tile(
        3,
        4,
        "8",
        "8",
        9,
        TileColor.BLUE,
        CurseType.NUMBER,
        number_value=8,
        metadata={"card_suit": "spades", "card_rank": "8", "source": "melmod"},
    )
    board.tiles[4][2] = Tile(
        4,
        2,
        "6",
        "6",
        7,
        TileColor.BLUE,
        CurseType.NUMBER,
        number_value=6,
        metadata={"source": "melmod"},
    )
    # Path uses spades 8 (index 19) and blue 6 (index 22) on a 5x5 board.
    path = [19, 22]
    assert birthday_cake_improve_for_path(board, path, level=3, rule=rule) == 24
