"""Achievement unlock stamp catalog, scoring, and search (wiki: various achievements)."""

import math
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
from cursed_words_solver.rules.scoring_conditions import (
    neapolitan_base_percent_from_loadout,
)

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



def test_blessing_of_the_fairies_cursed_boss_scale():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 10)
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stamps=[LoadoutItem(id="blessing_of_the_fairies", name="Blessing of the Fairies", kind="stamp")],
        extras={"cursed_bosses_defeated_count": "2"},
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
    effects = bd["pipeline"]["effects"]
    assert any("Heart On Fire:" in e and "longest RED run 3" in e for e in effects)


def test_neapolitan_three_colours():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 1, color=TileColor.RED)
    board.tiles[0][1] = _tile(0, 1, "B", 1, color=TileColor.BLUE)
    board.tiles[0][2] = _tile(0, 2, "C", 1, color=TileColor.COLORLESS)
    pipeline = ScoringPipeline()
    loadout = Loadout(stamps=[LoadoutItem(id="neapolitan", name="Neapolitan", kind="stamp")])
    score, bd = pipeline.score(board, [0, 1, 2], "abc", loadout)
    assert bd["multiplier"] == 1.0


def test_neapolitan_uses_live_percent_from_extras():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 5, color=TileColor.RED)
    board.tiles[0][1] = _tile(0, 1, "B", 5, color=TileColor.BLUE)
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stamps=[LoadoutItem(id="neapolitan", name="Neapolitan", kind="stamp")],
        extras={"neapolitan_percent": "110"},
    )
    score, bd = pipeline.score(board, [0, 1], "ab", loadout)
    base, _ = pipeline.score(board, [0, 1], "ab", Loadout())
    assert bd["multiplier"] == 1.1
    assert score == math.floor(base * 1.1)


def test_neapolitan_prefers_cached_when_stale_live_export():
    """Stale F7 export at 100% must not beat last_known 110% (hafting class)."""
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 5, color=TileColor.RED)
    board.tiles[0][1] = _tile(0, 1, "B", 5, color=TileColor.BLUE)
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stamps=[LoadoutItem(id="neapolitan", name="Neapolitan", kind="stamp")],
        extras={
            "neapolitan_percent": "100",
            "neapolitan_percent_last_known": "110",
        },
    )
    score, bd = pipeline.score(board, [0, 1], "ab", loadout)
    base, _ = pipeline.score(board, [0, 1], "ab", Loadout())
    assert bd["multiplier"] == 1.1
    assert score == math.floor(base * 1.1)


def test_neapolitan_prefers_cached_when_stale_high_live_export():
    """F8 live export above last_known must not inflate submit (sweepy class)."""
    loadout = Loadout(
        extras={
            "neapolitan_percent": "150",
            "neapolitan_percent_last_known": "145",
        },
    )
    pct, src = neapolitan_base_percent_from_loadout(loadout)
    assert pct == 145
    assert src == "cached"


def test_neapolitan_prefers_live_over_stale_higher_cache():
    """When live is not stale-high, live export wins over lower last_known."""
    loadout = Loadout(
        extras={
            "neapolitan_percent": "125",
            "neapolitan_percent_last_known": "120",
        },
    )
    pct, src = neapolitan_base_percent_from_loadout(loadout)
    assert pct == 125
    assert src == "live"


def test_neapolitan_uses_last_known_when_live_missing_only():
    loadout = Loadout(extras={"neapolitan_percent_last_known": "125"})
    pct, src = neapolitan_base_percent_from_loadout(loadout)
    assert pct == 125
    assert src == "cached"


def test_neapolitan_live_wins_when_higher_than_cached():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 5, color=TileColor.RED)
    board.tiles[0][1] = _tile(0, 1, "B", 5, color=TileColor.BLUE)
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stamps=[LoadoutItem(id="neapolitan", name="Neapolitan", kind="stamp")],
        extras={
            "neapolitan_percent": "110",
            "neapolitan_percent_last_known": "105",
        },
    )
    score, bd = pipeline.score(board, [0, 1], "ab", loadout)
    base, _ = pipeline.score(board, [0, 1], "ab", Loadout())
    assert bd["multiplier"] == 1.1
    assert score == math.floor(base * 1.1)


def test_neapolitan_uses_cached_percent_when_live_missing():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 5, color=TileColor.RED)
    board.tiles[0][1] = _tile(0, 1, "B", 5, color=TileColor.BLUE)
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stamps=[LoadoutItem(id="neapolitan", name="Neapolitan", kind="stamp")],
        extras={"neapolitan_percent_last_known": "115"},
    )
    score, bd = pipeline.score(board, [0, 1], "ab", loadout)
    base, _ = pipeline.score(board, [0, 1], "ab", Loadout())
    assert bd["multiplier"] == 1.15
    assert score == math.floor(base * 1.15)


def test_neapolitan_submit_simulation_uses_cached_baseline():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 5, color=TileColor.RED)
    board.tiles[0][1] = _tile(0, 1, "B", 5, color=TileColor.BLUE)
    board.tiles[0][2] = _tile(0, 2, "C", 5, color=TileColor.SHINY)
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stamps=[LoadoutItem(id="neapolitan", name="Neapolitan", kind="stamp")],
        extras={
            "neapolitan_percent_last_known": "115",
            "simulate_submit_improvements": True,
        },
    )
    score, bd = pipeline.score(board, [0, 1, 2], "abc", loadout)
    base, _ = pipeline.score(board, [0, 1, 2], "abc", Loadout())
    assert bd["multiplier"] == 1.2
    assert score == math.floor(base * 1.2)


def test_neapolitan_skips_when_below_three_colours():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 5, color=TileColor.SHINY)
    board.tiles[0][1] = _tile(0, 1, "B", 5, color=TileColor.COLORLESS)
    board.tiles[0][2] = _tile(0, 2, "C", 5, color=TileColor.COLORLESS)
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stamps=[LoadoutItem(id="neapolitan", name="Neapolitan", kind="stamp")],
        extras={"neapolitan_percent": "110"},
    )
    score, bd = pipeline.score(board, [0, 1, 2], "abc", loadout)
    base, _ = pipeline.score(board, [0, 1, 2], "abc", Loadout())
    assert bd["multiplier"] == 1.1
    assert score == math.floor(base * 1.1)


def test_neapolitan_applies_stored_percent_with_one_colour_no_improve():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 5, color=TileColor.COLORLESS)
    board.tiles[0][1] = _tile(0, 1, "B", 5, color=TileColor.BLUE)
    board.tiles[0][2] = _tile(0, 2, "C", 5, color=TileColor.COLORLESS)
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stamps=[LoadoutItem(id="neapolitan", name="Neapolitan", kind="stamp")],
        extras={"neapolitan_percent": "145"},
    )
    score, bd = pipeline.score(board, [0, 1, 2], "abc", loadout)
    base, _ = pipeline.score(board, [0, 1, 2], "abc", Loadout())
    assert bd["multiplier"] == 1.45
    assert score == math.floor(base * 1.45)


def test_neapolitan_improves_with_void_red_blue_without_simulate_flag():
    """yappy/abbes: VOID counts toward 3-colour improve at score time."""
    board = _empty_board()
    board.tiles[1][2] = _tile(1, 2, "₱", 0, color=TileColor.VOID, curse=CurseType.CURRENCY)
    board.tiles[2][2] = _tile(2, 2, "₱", 5, color=TileColor.RED, curse=CurseType.CURRENCY)
    board.tiles[3][2] = _tile(3, 2, "¥", 5, color=TileColor.BLUE, curse=CurseType.CURRENCY)
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stamps=[LoadoutItem(id="neapolitan", name="Neapolitan", kind="stamp")],
        extras={
            "neapolitan_percent": "155",
            "neapolitan_percent_last_known": "155",
        },
    )
    score, bd = pipeline.score(board, [7, 12, 17], "abc", loadout)
    base, _ = pipeline.score(board, [7, 12, 17], "abc", Loadout())
    assert bd["multiplier"] == 1.6
    assert score == math.floor(base * 1.6)


def test_neapolitan_strips_f8_preview_when_under_three_colours():
    """ngwees: F8 export 155 with 2 colours → ×1.50 not ×1.55."""
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 5, color=TileColor.COLORLESS)
    board.tiles[0][1] = _tile(0, 1, "B", 5, color=TileColor.RED)
    board.tiles[0][2] = _tile(0, 2, "C", 5, color=TileColor.VOID)
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stamps=[LoadoutItem(id="neapolitan", name="Neapolitan", kind="stamp")],
        extras={
            "neapolitan_percent": "155",
            "neapolitan_percent_last_known": "155",
        },
    )
    score, bd = pipeline.score(board, [0, 1, 2], "abc", loadout)
    base, _ = pipeline.score(board, [0, 1, 2], "abc", Loadout())
    assert bd["multiplier"] == 1.5
    assert score == math.floor(base * 1.5)


def test_neapolitan_does_not_strip_encounter_tier_175():
    """bott: live 175 with 2 path colours is real tier, not F8 preview to strip."""
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 5, color=TileColor.BLUE)
    board.tiles[0][1] = _tile(0, 1, "B", 5, color=TileColor.VOID)
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stamps=[LoadoutItem(id="neapolitan", name="Neapolitan", kind="stamp")],
        extras={
            "neapolitan_percent": "175",
            "neapolitan_percent_last_known": "175",
            "grid_number": "3",
        },
    )
    score, bd = pipeline.score(board, [0, 1], "ab", loadout)
    base, _ = pipeline.score(board, [0, 1], "ab", Loadout())
    assert bd["multiplier"] == 1.75
    assert score == math.floor(base * 1.75)


def _neapolitan_three_colour_board() -> Board:
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 5, color=TileColor.RED)
    board.tiles[0][1] = _tile(0, 1, "B", 5, color=TileColor.BLUE)
    board.tiles[0][2] = _tile(0, 2, "C", 5, color=TileColor.VOID)
    return board


def test_neapolitan_grid_cap_blocks_improve_on_grid_1_at_170():
    """battels: stale 175 on grid 1 with 3 colours clamps to ×1.70, no +5."""
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stamps=[LoadoutItem(id="neapolitan", name="Neapolitan", kind="stamp")],
        extras={
            "neapolitan_percent": "175",
            "neapolitan_percent_last_known": "175",
            "grid_number": "1",
        },
    )
    board = _neapolitan_three_colour_board()
    score, bd = pipeline.score(board, [0, 1, 2], "abc", loadout)
    base, _ = pipeline.score(board, [0, 1, 2], "abc", Loadout())
    assert bd["multiplier"] == 1.7
    assert score == math.floor(base * 1.7)


def test_neapolitan_clamps_stale_export_to_grid_cap():
    """battels F8: stale export 175 on grid 1 clamps to ×1.70, no improve."""
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stamps=[LoadoutItem(id="neapolitan", name="Neapolitan", kind="stamp")],
        extras={
            "neapolitan_percent": "175",
            "neapolitan_percent_last_known": "175",
            "grid_number": "1",
        },
    )
    board = _neapolitan_three_colour_board()
    score, bd = pipeline.score(board, [0, 1, 2], "abc", loadout)
    base, _ = pipeline.score(board, [0, 1, 2], "abc", Loadout())
    assert bd["multiplier"] == 1.7
    assert score == math.floor(base * 1.7)


def _neapolitan_two_colour_board() -> Board:
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 5, color=TileColor.RED)
    board.tiles[0][1] = _tile(0, 1, "B", 5, color=TileColor.BLUE)
    return board


def test_neapolitan_stale_above_cap_strips_to_cap_minus_five_with_two_colours():
    """ween F8: live 185 on grid 1 with 2 colours → ×1.65 (ends-in-5 stale preview)."""
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stamps=[LoadoutItem(id="neapolitan", name="Neapolitan", kind="stamp")],
        extras={
            "neapolitan_percent": "185",
            "neapolitan_percent_last_known": "185",
            "grid_number": "1",
        },
    )
    board = _neapolitan_two_colour_board()
    score, bd = pipeline.score(board, [0, 1], "ab", loadout)
    base, _ = pipeline.score(board, [0, 1], "ab", Loadout())
    assert bd["multiplier"] == 1.65
    assert score == math.floor(base * 1.65)


def test_neapolitan_stale_above_cap_keeps_cap_with_three_colours():
    """battels F8 guard: stale 175 on grid 1 with 3 colours stays at ×1.70."""
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stamps=[LoadoutItem(id="neapolitan", name="Neapolitan", kind="stamp")],
        extras={
            "neapolitan_percent": "175",
            "neapolitan_percent_last_known": "175",
            "grid_number": "1",
        },
    )
    board = _neapolitan_three_colour_board()
    score, bd = pipeline.score(board, [0, 1, 2], "abc", loadout)
    base, _ = pipeline.score(board, [0, 1, 2], "abc", Loadout())
    assert bd["multiplier"] == 1.7
    assert score == math.floor(base * 1.7)


def test_neapolitan_keeps_stored_tier_above_grid_cap_with_two_colours():
    """offends: grid 1 stored 175 with 2 colours → ×1.75, not stripped to ×1.65."""
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stamps=[LoadoutItem(id="neapolitan", name="Neapolitan", kind="stamp")],
        extras={
            "neapolitan_percent": "175",
            "neapolitan_percent_last_known": "175",
            "grid_number": "1",
        },
    )
    board = _neapolitan_two_colour_board()
    score, bd = pipeline.score(board, [0, 1], "ab", loadout)
    base, _ = pipeline.score(board, [0, 1], "ab", Loadout())
    assert bd["multiplier"] == 1.75
    assert score == math.floor(base * 1.75)


def test_neapolitan_improves_above_grid_cap_with_three_colours():
    """payees: grid 2 baseline 175 + improve → ×1.80."""
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stamps=[LoadoutItem(id="neapolitan", name="Neapolitan", kind="stamp")],
        extras={
            "neapolitan_percent": "175",
            "neapolitan_percent_last_known": "175",
            "grid_number": "2",
        },
    )
    board = _neapolitan_three_colour_board()
    score, bd = pipeline.score(board, [0, 1, 2], "abc", loadout)
    base, _ = pipeline.score(board, [0, 1, 2], "abc", Loadout())
    assert bd["multiplier"] == 1.8
    assert score == math.floor(base * 1.8)


def test_neapolitan_super_stale_improve_on_grid_1():
    """saccate: grid 1 F8 live 185 (super-stale) + improve → ×1.80."""
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stamps=[LoadoutItem(id="neapolitan", name="Neapolitan", kind="stamp")],
        extras={
            "neapolitan_percent": "185",
            "neapolitan_percent_last_known": "185",
            "grid_number": "1",
        },
    )
    board = _neapolitan_three_colour_board()
    score, bd = pipeline.score(board, [0, 1, 2], "abc", loadout)
    base, _ = pipeline.score(board, [0, 1, 2], "abc", Loadout())
    assert bd["multiplier"] == 1.8
    assert score == math.floor(base * 1.8)


def test_neapolitan_improves_from_cap_plus_five_on_grid_2():
    """pissy: grid 2 live 180 at cap+5 + improve → ×1.85."""
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stamps=[LoadoutItem(id="neapolitan", name="Neapolitan", kind="stamp")],
        extras={
            "neapolitan_percent": "180",
            "neapolitan_percent_last_known": "180",
            "grid_number": "2",
        },
    )
    board = _neapolitan_three_colour_board()
    score, bd = pipeline.score(board, [0, 1, 2], "abc", loadout)
    base, _ = pipeline.score(board, [0, 1, 2], "abc", Loadout())
    assert bd["multiplier"] == 1.85
    assert score == math.floor(base * 1.85)


def test_neapolitan_improves_from_cap_plus_five_on_grid_3():
    """nett: grid 3 live 185 at cap+5 + improve → ×1.90."""
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stamps=[LoadoutItem(id="neapolitan", name="Neapolitan", kind="stamp")],
        extras={
            "neapolitan_percent": "185",
            "neapolitan_percent_last_known": "185",
            "grid_number": "3",
        },
    )
    board = _neapolitan_three_colour_board()
    score, bd = pipeline.score(board, [0, 1, 2], "abc", loadout)
    base, _ = pipeline.score(board, [0, 1, 2], "abc", Loadout())
    assert bd["multiplier"] == 1.9
    assert score == math.floor(base * 1.9)


def test_neapolitan_improves_at_grid_cap_on_grid_3():
    """teenes: grid 3 baseline 180 + improve → ×1.85."""
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stamps=[LoadoutItem(id="neapolitan", name="Neapolitan", kind="stamp")],
        extras={
            "neapolitan_percent": "180",
            "neapolitan_percent_last_known": "180",
            "grid_number": "3",
        },
    )
    board = _neapolitan_three_colour_board()
    score, bd = pipeline.score(board, [0, 1, 2], "abc", loadout)
    base, _ = pipeline.score(board, [0, 1, 2], "abc", Loadout())
    assert bd["multiplier"] == 1.85
    assert score == math.floor(base * 1.85)


def test_neapolitan_improves_to_grid_cap_on_grid_2():
    """preppy: grid 2 cap 175 — 170 baseline + improve → ×1.75."""
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stamps=[LoadoutItem(id="neapolitan", name="Neapolitan", kind="stamp")],
        extras={
            "neapolitan_percent": "170",
            "neapolitan_percent_last_known": "170",
            "grid_number": "2",
        },
    )
    board = _neapolitan_three_colour_board()
    score, bd = pipeline.score(board, [0, 1, 2], "abc", loadout)
    base, _ = pipeline.score(board, [0, 1, 2], "abc", Loadout())
    assert bd["multiplier"] == 1.75
    assert score == math.floor(base * 1.75)


def test_neapolitan_stored_baseline_without_improve_on_grid_1():
    """eww: grid 1 stored 200%, <3 colours → ×2.0 not ×1.65."""
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stamps=[LoadoutItem(id="neapolitan", name="Neapolitan", kind="stamp")],
        extras={
            "neapolitan_percent": "200",
            "neapolitan_percent_last_known": "200",
            "grid_number": "1",
        },
    )
    board = _neapolitan_two_colour_board()
    score, bd = pipeline.score(board, [0, 1], "ab", loadout)
    base, _ = pipeline.score(board, [0, 1], "ab", Loadout())
    assert bd["multiplier"] == 2.0
    assert score == math.floor(base * 2.0)


def test_neapolitan_stored_baseline_without_improve_on_grid_2():
    """toy: grid 2 stored 200%, <3 colours → ×2.0."""
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stamps=[LoadoutItem(id="neapolitan", name="Neapolitan", kind="stamp")],
        extras={
            "neapolitan_percent": "200",
            "neapolitan_percent_last_known": "200",
            "grid_number": "2",
        },
    )
    board = _neapolitan_two_colour_board()
    score, bd = pipeline.score(board, [0, 1], "ab", loadout)
    base, _ = pipeline.score(board, [0, 1], "ab", Loadout())
    assert bd["multiplier"] == 2.0
    assert score == math.floor(base * 2.0)


def test_neapolitan_stored_baseline_without_improve_on_grid_2_210():
    """peeing: grid 2 stored 210%, <3 colours → ×2.10."""
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stamps=[LoadoutItem(id="neapolitan", name="Neapolitan", kind="stamp")],
        extras={
            "neapolitan_percent": "210",
            "neapolitan_percent_last_known": "210",
            "grid_number": "2",
        },
    )
    board = _neapolitan_two_colour_board()
    score, bd = pipeline.score(board, [0, 1], "ab", loadout)
    base, _ = pipeline.score(board, [0, 1], "ab", Loadout())
    assert bd["multiplier"] == 2.1
    assert score == math.floor(base * 2.1)


def test_neapolitan_stored_baseline_without_improve_on_grid_4():
    """week: grid 4 stored 205%, <3 colours → ×2.05."""
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stamps=[LoadoutItem(id="neapolitan", name="Neapolitan", kind="stamp")],
        extras={
            "neapolitan_percent": "205",
            "neapolitan_percent_last_known": "205",
            "grid_number": "4",
        },
    )
    board = _neapolitan_two_colour_board()
    score, bd = pipeline.score(board, [0, 1], "ab", loadout)
    base, _ = pipeline.score(board, [0, 1], "ab", Loadout())
    assert bd["multiplier"] == 2.05
    assert score == math.floor(base * 2.05)


def test_neapolitan_submit_improve_five_percent_on_grid_1_190():
    """asset: grid 1 live 190 + improve → ×1.90."""
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stamps=[LoadoutItem(id="neapolitan", name="Neapolitan", kind="stamp")],
        extras={
            "neapolitan_percent": "190",
            "neapolitan_percent_last_known": "190",
            "grid_number": "1",
        },
    )
    board = _neapolitan_three_colour_board()
    score, bd = pipeline.score(board, [0, 1, 2], "abc", loadout)
    base, _ = pipeline.score(board, [0, 1, 2], "abc", Loadout())
    assert bd["multiplier"] == 1.9
    assert score == math.floor(base * 1.9)


def test_neapolitan_submit_improve_five_percent_on_grid_2_195():
    """penny: grid 2 live 195 + improve → ×1.95."""
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stamps=[LoadoutItem(id="neapolitan", name="Neapolitan", kind="stamp")],
        extras={
            "neapolitan_percent": "195",
            "neapolitan_percent_last_known": "195",
            "grid_number": "2",
        },
    )
    board = _neapolitan_three_colour_board()
    score, bd = pipeline.score(board, [0, 1, 2], "abc", loadout)
    base, _ = pipeline.score(board, [0, 1, 2], "abc", Loadout())
    assert bd["multiplier"] == 1.95
    assert score == math.floor(base * 1.95)


def test_neapolitan_submit_improve_five_percent_on_grid_3_200():
    """feen: grid 3 live 200 + improve → ×2.00."""
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stamps=[LoadoutItem(id="neapolitan", name="Neapolitan", kind="stamp")],
        extras={
            "neapolitan_percent": "200",
            "neapolitan_percent_last_known": "200",
            "grid_number": "3",
        },
    )
    board = _neapolitan_three_colour_board()
    score, bd = pipeline.score(board, [0, 1, 2], "abc", loadout)
    base, _ = pipeline.score(board, [0, 1, 2], "abc", Loadout())
    assert bd["multiplier"] == 2.0
    assert score == math.floor(base * 2.0)


def test_neapolitan_submit_improve_five_percent_on_grid_3_205():
    """cann: grid 3 live 205 + improve → ×2.05."""
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stamps=[LoadoutItem(id="neapolitan", name="Neapolitan", kind="stamp")],
        extras={
            "neapolitan_percent": "205",
            "neapolitan_percent_last_known": "205",
            "grid_number": "3",
        },
    )
    board = _neapolitan_three_colour_board()
    score, bd = pipeline.score(board, [0, 1, 2], "abc", loadout)
    base, _ = pipeline.score(board, [0, 1, 2], "abc", Loadout())
    assert bd["multiplier"] == 2.05
    assert score == math.floor(base * 2.05)


def test_neapolitan_submit_improve_five_percent_on_grid_1_210():
    """kaases: grid 1 live 210 + improve → ×2.10."""
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stamps=[LoadoutItem(id="neapolitan", name="Neapolitan", kind="stamp")],
        extras={
            "neapolitan_percent": "210",
            "neapolitan_percent_last_known": "210",
            "grid_number": "1",
        },
    )
    board = _neapolitan_three_colour_board()
    score, bd = pipeline.score(board, [0, 1, 2], "abc", loadout)
    base, _ = pipeline.score(board, [0, 1, 2], "abc", Loadout())
    assert bd["multiplier"] == 2.1
    assert score == math.floor(base * 2.1)


def test_neapolitan_submit_improve_five_percent_on_grid_3_215():
    """kreng: grid 3 live 215 + improve → ×2.15."""
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stamps=[LoadoutItem(id="neapolitan", name="Neapolitan", kind="stamp")],
        extras={
            "neapolitan_percent": "215",
            "neapolitan_percent_last_known": "215",
            "grid_number": "3",
        },
    )
    board = _neapolitan_three_colour_board()
    score, bd = pipeline.score(board, [0, 1, 2], "abc", loadout)
    base, _ = pipeline.score(board, [0, 1, 2], "abc", Loadout())
    assert bd["multiplier"] == 2.15
    assert score == math.floor(base * 2.15)


def test_neapolitan_submit_improve_five_percent_on_grid_4_220():
    """beety: grid 4 live 220 + improve → ×2.20."""
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stamps=[LoadoutItem(id="neapolitan", name="Neapolitan", kind="stamp")],
        extras={
            "neapolitan_percent": "220",
            "neapolitan_percent_last_known": "220",
            "grid_number": "4",
        },
    )
    board = _neapolitan_three_colour_board()
    score, bd = pipeline.score(board, [0, 1, 2], "abc", loadout)
    base, _ = pipeline.score(board, [0, 1, 2], "abc", Loadout())
    assert bd["multiplier"] == 2.2
    assert score == math.floor(base * 2.2)


def test_neapolitan_submit_simulation_improves_from_baseline_with_three_colours():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 5, color=TileColor.RED)
    board.tiles[0][1] = _tile(0, 1, "B", 5, color=TileColor.BLUE)
    board.tiles[0][2] = _tile(0, 2, "C", 5, color=TileColor.SHINY)
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stamps=[LoadoutItem(id="neapolitan", name="Neapolitan", kind="stamp")],
        extras={
            "neapolitan_percent": "140",
            "neapolitan_percent_last_known": "140",
            "simulate_submit_improvements": True,
        },
    )
    score, bd = pipeline.score(board, [0, 1, 2], "abc", loadout)
    base, _ = pipeline.score(board, [0, 1, 2], "abc", Loadout())
    assert bd["multiplier"] == 1.45
    assert score == math.floor(base * 1.45)


def test_neapolitan_submit_simulation_only_improves_with_three_colours():
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stamps=[LoadoutItem(id="neapolitan", name="Neapolitan", kind="stamp")],
        extras={
            "neapolitan_percent": "110",
            "simulate_submit_improvements": True,
        },
    )
    board_low = _empty_board()
    board_low.tiles[0][0] = _tile(0, 0, "A", 5, color=TileColor.SHINY)
    board_low.tiles[0][1] = _tile(0, 1, "B", 5, color=TileColor.COLORLESS)
    board_low.tiles[0][2] = _tile(0, 2, "C", 5, color=TileColor.COLORLESS)
    _score_low, bd_low = pipeline.score(board_low, [0, 1, 2], "abc", loadout)
    assert bd_low["multiplier"] == 1.1

    board_high = _empty_board()
    board_high.tiles[0][0] = _tile(0, 0, "A", 5, color=TileColor.RED)
    board_high.tiles[0][1] = _tile(0, 1, "B", 5, color=TileColor.BLUE)
    board_high.tiles[0][2] = _tile(0, 2, "C", 5, color=TileColor.SHINY)
    _score_high, bd_high = pipeline.score(board_high, [0, 1, 2], "abc", loadout)
    assert bd_high["multiplier"] == 1.15


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
