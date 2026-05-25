"""Achievement unlock stamp catalog, scoring, and search (wiki: various achievements)."""

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
from cursed_words_solver.search import PathValidator, resolve_letter_options

ACHIEVEMENT_STAMP_NAMES = [
    "Akoya Pearl",
    "Bank",
    "Bar Chart",
    "Beam Me Up",
    "Beefeater",
    "Big Bang",
    "Black Hole",
    "Blessing of the Fairies",
    "Blessing Of The Shopkeeper",
    "Bomb",
    "Book Of Openings",
    "Briefcase",
    "Builder",
    "Bunch Of Grapes",
    "Cable Car",
    "Cartwheeler",
    "Chess Board",
    "Disco Ball",
    "Diya",
    "Dove",
    "Dragon",
    "Eclipse",
    "Empty Jar",
    "Error",
    "Erupting Volcano",
    "Falling Leaf",
    "Fan",
    "Flashy Fountain Pen",
    "Fleur De Lis",
    "Food Poisoning",
    "Fortune Cookie",
    "Fraction Frog",
    "Fried Shrimp",
    "Genie",
    "Giraffe",
    "Globe Trotter",
    "Haunted House",
    "Head In The Clouds",
    "Heart On Fire",
    "Hourglass",
    "ID Card",
    "Jellyfish",
    "Jolly Roger",
    "King Of The Bridge",
    "Kokeshi Dolls",
    "Magnet",
    "Microphone",
    "Mushroom Upgrade",
    "Mutating DNA",
    "Neapolitan",
    "Number Factory",
    "Ogre",
    "Piece of Cake",
    "Piggy Bank",
    "Pizza Slice",
    "Pocket Money",
    "Receipt",
    "Red Balloon",
    "Rollercoaster",
    "Saguaro Seedling",
    "Sewing Needle",
    "Shaved Ice",
    "Silly Puppy",
    "Snail",
    "Spouting Whale",
    "Stack Of Pancakes",
    "Stadium",
    "Statue Of Liberty",
    "Stethoscope",
    "Stiletto",
    "Supervillain",
    "Surprise Delivery",
    "Suspension Bridge",
    "Takeout Box",
    "Television",
    "Torii Gate",
    "Trophy Of Wealth",
    "Twinkle Toes",
    "Underhand",
    "Unicorn",
    "Wheel",
    "Work of Art",
]

SCORING_SLUGS = {
    "blessing_of_the_fairies",
    "builder",
    "cartwheeler",
    "dove",
    "empty_jar",
    "error",
    "erupting_volcano",
    "giraffe",
    "head_in_the_clouds",
    "heart_on_fire",
    "kokeshi_dolls",
    "neapolitan",
    "piggy_bank",
    "shaved_ice",
    "silly_puppy",
    "stiletto",
}

GRID_ONLY_SLUGS = {slugify_name(n) for n in ACHIEVEMENT_STAMP_NAMES} - SCORING_SLUGS


def _tile(
    row: int,
    col: int,
    ch: str,
    score: int,
    *,
    color=TileColor.COLORLESS,
    curse=CurseType.LETTER,
    number_value=None,
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
        number_value=number_value,
        metadata=meta,
    )


def _empty_board() -> Board:
    grid = [[_tile(r, c, "X", 1) for c in range(5)] for r in range(5)]
    return Board(tiles=grid, money=0)


def test_all_achievement_stamps_catalogued():
    pipeline = ScoringPipeline()
    for name in ACHIEVEMENT_STAMP_NAMES:
        slug = slugify_name(name)
        _key, rule = get_rule(pipeline.rules, "stamps", slug, name)
        assert rule is not None, slug
        assert rule.get("type") != "unmodeled", slug


def test_count_scoring_vs_grid_only_achievement_stamps():
    pipeline = ScoringPipeline()
    assert_loadout_stamp_coverage(pipeline.rules, ACHIEVEMENT_STAMP_NAMES)



def test_blessing_of_the_fairies_fairy_scale():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 10)
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stamps=[LoadoutItem(id="blessing_of_the_fairies", name="Blessing of the Fairies", kind="stamp")],
        extras={"fairy_count": "2"},
    )
    score, bd = pipeline.score(board, [0], "a", loadout)
    base, _ = pipeline.score(board, [0], "a", Loadout())
    assert bd["multiplier"] == 2.0
    assert score == base * 2


def test_builder_consumable_count_multiplier():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "?", 5, metadata={"consumable": True})
    board.tiles[0][1] = _tile(0, 1, "?", 5, metadata={"consumable": True})
    pipeline = ScoringPipeline()
    loadout = Loadout(stamps=[LoadoutItem(id="builder", name="Builder", kind="stamp")])
    score, _ = pipeline.score(board, [0, 1], "??", loadout)
    base, _ = pipeline.score(board, [0, 1], "??", Loadout())
    assert score == base * 2


def test_cartwheeler_negative_per_tile():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 10)
    board.tiles[0][2] = _tile(0, 2, "B", 10)
    pipeline = ScoringPipeline()
    loadout = Loadout(stamps=[LoadoutItem(id="cartwheeler", name="Cartwheeler", kind="stamp")])
    score, bd = pipeline.score(board, [0, 2], "ab", loadout)
    assert abs(bd["multiplier"] - 1.21) < 0.01


def test_empty_jar_zero_money_doubles_word():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 10)
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stamps=[LoadoutItem(id="empty_jar", name="Empty Jar", kind="stamp")],
        money=0,
    )
    score, bd = pipeline.score(board, [0], "a", loadout)
    base, _ = pipeline.score(board, [0], "a", Loadout())
    assert bd["multiplier"] == 2.0
    assert score == base * 2


def test_giraffe_number_position_multiplier():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "1", 1, curse=CurseType.NUMBER, number_value=1)
    board.tiles[0][1] = _tile(0, 1, "2", 2, curse=CurseType.NUMBER, number_value=2)
    board.tiles[0][2] = _tile(0, 2, "3", 3, curse=CurseType.NUMBER, number_value=3)
    pipeline = ScoringPipeline()
    loadout = Loadout(stamps=[LoadoutItem(id="giraffe", name="Giraffe", kind="stamp")])
    score, bd = pipeline.score(board, [0, 1, 2], "123", loadout)
    assert bd["pipeline"]["tile_scores"] == [1.0, 4.0, 9.0]


def test_head_in_the_clouds_non_adjacent_path():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 10)
    board.tiles[0][2] = _tile(0, 2, "B", 10)
    pipeline = ScoringPipeline()
    loadout = Loadout(stamps=[LoadoutItem(id="head_in_the_clouds", name="Head In The Clouds", kind="stamp")])
    score, bd = pipeline.score(board, [0, 2], "ab", loadout)
    base, _ = pipeline.score(board, [0, 2], "ab", Loadout())
    assert bd["multiplier"] == 1.5
    assert score == base * 1.5


def test_heart_on_fire_red_run_multiplier():
    board = _empty_board()
    for c in range(3):
        board.tiles[0][c] = _tile(0, c, "A", 5, color=TileColor.RED)
    pipeline = ScoringPipeline()
    loadout = Loadout(stamps=[LoadoutItem(id="heart_on_fire", name="Heart On Fire", kind="stamp")])
    score, bd = pipeline.score(board, [0, 1, 2], "aaa", loadout)
    base, _ = pipeline.score(board, [0, 1, 2], "aaa", Loadout())
    assert bd["multiplier"] == 3.0
    assert score == base * 3


def test_neapolitan_three_colours():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 1, color=TileColor.RED)
    board.tiles[0][1] = _tile(0, 1, "B", 1, color=TileColor.BLUE)
    board.tiles[0][2] = _tile(0, 2, "C", 1, color=TileColor.COLORLESS)
    pipeline = ScoringPipeline()
    loadout = Loadout(stamps=[LoadoutItem(id="neapolitan", name="Neapolitan", kind="stamp")])
    score, bd = pipeline.score(board, [0, 1, 2], "abc", loadout)
    assert bd["multiplier"] == 1.0


def test_stiletto_red_half_grid_number():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 2, color=TileColor.RED)
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stamps=[LoadoutItem(id="stiletto", name="Stiletto", kind="stamp")],
        extras={"grid_number": "10"},
    )
    score, _ = pipeline.score(board, [0], "a", loadout)
    base, _ = pipeline.score(board, [0], "a", Loadout())
    assert score == base * 5


def test_silly_puppy_animal_stamps():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 10)
    board.tiles[0][1] = _tile(0, 1, "B", 10)
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stamps=[LoadoutItem(id="silly_puppy", name="Silly Puppy", kind="stamp")],
        extras={"animal_stamp_count": "2"},
    )
    score, bd = pipeline.score(board, [0, 1], "ab", loadout)
    assert bd["multiplier"] == 3.0


def test_bunch_of_grapes_roman_number_word(tmp_path):
    wl = tmp_path / "words.txt"
    wl.write_text("iv\n", encoding="utf-8")
    d = WordDictionary(wl)
    validator = PathValidator(d, min_len=2)
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "1", 1, curse=CurseType.NUMBER, number_value=1)
    board.tiles[0][1] = _tile(0, 1, "5", 5, curse=CurseType.NUMBER, number_value=5)
    loadout = Loadout(stamps=[LoadoutItem(id="bunch_of_grapes", name="Bunch Of Grapes", kind="stamp")])
    flags = stamp_search_flags(loadout)
    assert validator.word_ok(board, [0, 1], "iv", stamp_flags=flags)


def test_jellyfish_j_alternatives():
    tile = _tile(0, 0, "J", 1, color=TileColor.SHINY)
    loadout = Loadout(stamps=[LoadoutItem(id="jellyfish", name="Jellyfish", kind="stamp")])
    flags = stamp_search_flags(loadout)
    assert set(resolve_letter_options(tile, 0, flags=flags)) == {"h", "y"}


def test_suspension_bridge_red_letter_neighbors():
    tile = _tile(0, 0, "B", 1, color=TileColor.RED)
    loadout = Loadout(stamps=[LoadoutItem(id="suspension_bridge", name="Suspension Bridge", kind="stamp")])
    flags = stamp_search_flags(loadout)
    assert set(resolve_letter_options(tile, 0, flags=flags)) == {"a", "b", "c"}


def test_king_of_the_bridge_flag_wired():
    loadout = Loadout(stamps=[LoadoutItem(id="king_of_the_bridge", name="King Of The Bridge", kind="stamp")])
    flags = stamp_search_flags(loadout)
    assert flags.chess_allies_can_take


def test_television_movement_flag_wired():
    loadout = Loadout(stamps=[LoadoutItem(id="television", name="Television", kind="stamp")])
    flags = stamp_search_flags(loadout)
    assert flags.chess_king_queen_item_movement
