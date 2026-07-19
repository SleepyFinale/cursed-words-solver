"""Quest unlock stamp catalog, scoring, and search (wiki: Unlocked when completing quests)."""

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
from cursed_words_solver.search import PathValidator, number_position_valid, resolve_letter

QUEST_STAMP_NAMES = [
    "Angel Investment",
    "Banana",
    "Bar Of Soap",
    "Busy Schedule",
    "Chick",
    "Christmas Tree",
    "Eraser",
    "Head Trauma",
    "Honeypot",
    "Juice Box",
    "Number Go Up",
    "Ruler",
    "Rosebud",
    "Spicy Pepper",
    "Tin Of Beans",
]

GRID_ONLY_SLUGS = {
    "angel_investment",
    "bar_of_soap",
    "busy_schedule",
    "christmas_tree",
    "eraser",
    "head_trauma",
    "honeypot",
    "juice_box",
    "number_go_up",
    "rosebud",
    "spicy_pepper",
    "tin_of_beans",
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


def test_all_quest_stamps_catalogued():
    pipeline = ScoringPipeline()
    for name in QUEST_STAMP_NAMES:
        slug = slugify_name(name)
        _key, rule = get_rule(pipeline.rules, "stamps", slug, name)
        assert rule is not None, slug
        assert rule.get("type") != "unmodeled", slug


def test_count_scoring_vs_grid_only_quest_stamps():
    pipeline = ScoringPipeline()
    assert_loadout_stamp_coverage(pipeline.rules, QUEST_STAMP_NAMES)



def test_banana_four_same_letters_doubles_word():
    board = _empty_board()
    path = []
    for c in range(4):
        board.tiles[0][c] = _tile(0, c, "A", 5)
        path.append(c)
    pipeline = ScoringPipeline()
    loadout = Loadout(stamps=[LoadoutItem(id="banana", name="Banana", kind="stamp")])
    score, bd = pipeline.score(board, path, "aaaa", loadout)
    base, _ = pipeline.score(board, path, "aaaa", Loadout())
    assert bd["multiplier"] == 2.0
    assert score == base * 2


def test_ruler_non_adjacent_steps_scale_word():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 10)
    board.tiles[0][2] = _tile(0, 2, "B", 10)
    board.tiles[0][4] = _tile(0, 4, "C", 10)
    path = [0, 2, 4]
    pipeline = ScoringPipeline()
    loadout = Loadout(stamps=[LoadoutItem(id="ruler", name="Ruler", kind="stamp")])
    score, bd = pipeline.score(board, path, "abc", loadout)
    assert bd["multiplier"] == 1.04


def test_ruler_uses_accumulated_distance_from_extras():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 10)
    board.tiles[0][1] = _tile(0, 1, "B", 10)
    board.tiles[0][4] = _tile(0, 4, "C", 10)
    path = [0, 1, 4]
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stamps=[LoadoutItem(id="ruler", name="Ruler", kind="stamp")],
        extras={"ruler_distance": "2"},
    )
    score, bd = pipeline.score(board, path, "abc", loadout)
    base, _ = pipeline.score(board, path, "abc", Loadout())
    assert bd["multiplier"] == 1.06
    assert score == int(base * 1.06)


def test_ruler_skips_when_distance_zero():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 10)
    board.tiles[0][1] = _tile(0, 1, "B", 10)
    pipeline = ScoringPipeline()
    loadout = Loadout(stamps=[LoadoutItem(id="ruler", name="Ruler", kind="stamp")])
    score, bd = pipeline.score(board, [0, 1], "ab", loadout)
    base, _ = pipeline.score(board, [0, 1], "ab", Loadout())
    assert bd["multiplier"] == 1.0
    assert score == base


def test_chick_level_one_stickers_scale_word():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 10)
    board.tiles[0][1] = _tile(0, 1, "B", 10)
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stamps=[LoadoutItem(id="chick", name="Chick", kind="stamp")],
        stickers=[
            LoadoutItem(id="s1", name="Sticker 1", level=1, kind="sticker"),
            LoadoutItem(id="s2", name="Sticker 2", level=1, kind="sticker"),
        ],
    )
    score, bd = pipeline.score(board, [0, 1], "ab", loadout)
    assert bd["multiplier"] == 3.0
    assert score == 60


def test_spicy_pepper_red_tile_resolves_as_s():
    board = _empty_board()
    tile = _tile(0, 0, "X", 1, color=TileColor.RED)
    loadout = Loadout(
        stamps=[LoadoutItem(id="spicy_pepper", name="Spicy Pepper", kind="stamp")]
    )
    flags = stamp_search_flags(loadout)
    assert resolve_letter(tile, 0, flags=flags) == "s"


def test_number_go_up_ascending_digits_relax_position():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "3", 3, curse=CurseType.NUMBER, number_value=3)
    board.tiles[0][1] = _tile(0, 1, "1", 1, curse=CurseType.NUMBER, number_value=1)
    board.tiles[0][2] = _tile(0, 2, "2", 2, curse=CurseType.NUMBER, number_value=2)
    loadout = Loadout(
        stamps=[LoadoutItem(id="number_go_up", name="Number Go Up", kind="stamp")]
    )
    flags = stamp_search_flags(loadout)
    assert number_position_valid(
        board.tiles[0][0], 0, flags=flags, segment="123"
    )
    assert number_position_valid(
        board.tiles[0][1], 1, flags=flags, segment="123"
    )
    assert number_position_valid(
        board.tiles[0][2], 2, flags=flags, segment="123"
    )


def test_honeypot_stitched_words_validate(tmp_path):
    wl = tmp_path / "words.txt"
    wl.write_text("cat\ndog\n", encoding="utf-8")
    d = WordDictionary(wl)
    validator = PathValidator(d, min_len=3)
    board = _empty_board()
    path = [0, 1, 2, 6, 7, 8]
    for i, idx in enumerate(path):
        ch = "catdog"[i]
        r, c = divmod(idx, 5)
        board.tiles[r][c] = _tile(r, c, ch.upper(), 1)
    loadout = Loadout(stamps=[LoadoutItem(id="honeypot", name="Honeypot", kind="stamp")])
    flags = stamp_search_flags(loadout)
    assert validator.word_ok(board, path, "catdog", stamp_flags=flags)
    assert not validator.word_ok(board, path, "catdog", stamp_flags=None)


def test_number_go_up_uses_path_values_not_word_digits(tmp_path):
    wl = tmp_path / "words.txt"
    wl.write_text("123\n", encoding="utf-8")
    d = WordDictionary(wl)
    validator = PathValidator(d, min_len=3)
    board = _empty_board()
    path = [0, 1, 2]
    board.tiles[0][0] = _tile(0, 0, "3", 3, curse=CurseType.NUMBER, number_value=3)
    board.tiles[0][1] = _tile(0, 1, "1", 1, curse=CurseType.NUMBER, number_value=1)
    board.tiles[0][2] = _tile(0, 2, "2", 2, curse=CurseType.NUMBER, number_value=2)
    loadout = Loadout(
        stamps=[LoadoutItem(id="number_go_up", name="Number Go Up", kind="stamp")]
    )
    flags = stamp_search_flags(loadout)
    assert not validator.word_ok(board, path, "123", stamp_flags=flags)


def test_honeypot_number_go_up_segment_local_positions():
    board = _empty_board()
    tiles = [
        _tile(0, 0, "3", 3, curse=CurseType.NUMBER, number_value=3),
        _tile(0, 1, "1", 1, curse=CurseType.NUMBER, number_value=1),
        _tile(0, 2, "4", 4, curse=CurseType.NUMBER, number_value=4),
        _tile(0, 3, "2", 2, curse=CurseType.NUMBER, number_value=2),
    ]
    for t in tiles:
        board.tiles[t.row][t.col] = t
    loadout = Loadout(
        stamps=[
            LoadoutItem(id="honeypot", name="Honeypot", kind="stamp"),
            LoadoutItem(id="number_go_up", name="Number Go Up", kind="stamp"),
        ]
    )
    flags = stamp_search_flags(loadout)
    assert number_position_valid(tiles[0], 0, flags=flags, segment="12")
    assert number_position_valid(tiles[1], 1, flags=flags, segment="12")
    assert number_position_valid(tiles[2], 0, flags=flags, segment="34")
    assert number_position_valid(tiles[3], 1, flags=flags, segment="34")
