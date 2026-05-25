"""Hayley Bayles unlock stamp scoring and search (wiki: Unlocked when unlocking Hayley Bayles)."""

from pathlib import Path

from cursed_words_solver.dictionary import WordDictionary
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
from cursed_words_solver.rules.stamp_behaviors import stamp_search_flags
from cursed_words_solver.search import (
    PathValidator,
    number_position_valid,
    resolve_letter,
)

HAYLEY_STAMP_NAMES = [
    "Flamingo",
    "Full Battery",
    "Microscope",
    "Test Tube",
]

GRID_ONLY_SLUGS = {
    "flamingo",
    "test_tube",
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


def test_all_hayley_stamps_catalogued():
    pipeline = ScoringPipeline()
    for name in HAYLEY_STAMP_NAMES:
        slug = slugify_name(name)
        _key, rule = get_rule(pipeline.rules, "stamps", slug, name)
        assert rule is not None, slug
        assert rule.get("type") != "unmodeled", slug


def test_count_scoring_vs_grid_only_hayley_stamps():
    pipeline = ScoringPipeline()
    assert_loadout_stamp_coverage(pipeline.rules, HAYLEY_STAMP_NAMES)



def test_full_battery_three_numbers_triples_word():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "1", 1, curse=CurseType.NUMBER, number_value=1)
    board.tiles[0][1] = _tile(0, 1, "2", 2, curse=CurseType.NUMBER, number_value=2)
    board.tiles[0][2] = _tile(0, 2, "3", 3, curse=CurseType.NUMBER, number_value=3)
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stamps=[LoadoutItem(id="full_battery", name="Full Battery", kind="stamp")]
    )
    score, bd = pipeline.score(board, [0, 1, 2], "123", loadout)
    assert bd["multiplier"] == 3.0
    assert score == 18


def test_microscope_uses_packet_base_score():
    board = _empty_board()
    board.tiles[0][0] = Tile(
        row=0,
        col=0,
        char="A",
        letter="A",
        base_score=1,
        color=TileColor.RED,
        curse=CurseType.LETTER,
    )
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stamps=[LoadoutItem(id="microscope", name="Microscope", kind="stamp")]
    )
    score, _ = pipeline.score(board, [0], "a", loadout)
    base, _ = pipeline.score(board, [0], "a", Loadout())
    assert score == 1
    assert base == 2


def test_flamingo_shiny_resolves_as_one():
    """Flamingo: shiny letters behave as 1s; shiny numbers keep normal position rules."""
    board = _empty_board()
    tile = _tile(0, 0, "S", 50, color=TileColor.SHINY)
    loadout = Loadout(
        stamps=[LoadoutItem(id="flamingo", name="Flamingo", kind="stamp")]
    )
    flags = stamp_search_flags(loadout)
    assert resolve_letter(tile, 0, flags=flags) == "1"
    assert number_position_valid(tile, 0, flags=flags)
    assert resolve_letter(tile, 3, flags=flags).lower() == "s"


def test_flamingo_shiny_number_uses_normal_position():
    loadout = Loadout(
        stamps=[LoadoutItem(id="flamingo", name="Flamingo", kind="stamp")]
    )
    flags = stamp_search_flags(loadout)
    five = _tile(
        0,
        0,
        "5",
        50,
        color=TileColor.SHINY,
        curse=CurseType.NUMBER,
        number_value=5,
    )
    six = _tile(
        0,
        1,
        "6",
        50,
        color=TileColor.SHINY,
        curse=CurseType.NUMBER,
        number_value=6,
    )
    assert number_position_valid(five, 4, flags=flags)
    assert number_position_valid(six, 5, flags=flags)
    assert not number_position_valid(five, 0, flags=flags)


def test_test_tube_number_position_plus_minus_one():
    board = _empty_board()
    tile = _tile(0, 1, "3", 3, curse=CurseType.NUMBER, number_value=3)
    loadout = Loadout(
        stamps=[LoadoutItem(id="test_tube", name="Test Tube", kind="stamp")]
    )
    flags = stamp_search_flags(loadout)
    assert number_position_valid(tile, 1, flags=flags)
    assert not number_position_valid(tile, 0, flags=flags)


def test_test_tube_number_word_digit_tolerance(tmp_path):
    wl = tmp_path / "words.txt"
    wl.write_text(
        "cat\ncar\ntar\nrat\nart\nthe\nbuy\ngame\nboo\nbook",
        encoding="utf-8",
    )
    d = WordDictionary(wl)
    board = _empty_board()
    board.tiles[2][1] = _tile(2, 1, "B", 3)
    board.tiles[2][2] = _tile(2, 2, "O", 1)
    board.tiles[2][3] = _tile(2, 3, "O", 1)
    board.tiles[2][4] = _tile(2, 4, "3", 3, curse=CurseType.NUMBER, number_value=3)
    loadout = Loadout(
        stamps=[LoadoutItem(id="test_tube", name="Test Tube", kind="stamp")]
    )
    flags = stamp_search_flags(loadout)
    validator = PathValidator(d, min_len=3)
    assert validator.word_ok(board, [11, 12, 13, 14], "boo4", flags)
