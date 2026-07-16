"""Cable Car: path stickers Upgrade once per owned copy before scoring."""

from cursed_words_solver.models import (
    Board,
    CurseType,
    Loadout,
    LoadoutItem,
    Tile,
    TileColor,
)
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.rule_lookup import get_rule
from cursed_words_solver.rules.scoring_conditions import (
    cable_car_stamp_count,
    grid_path_sticker_level,
    scaled_word_multiplier,
    sticker_rule_int,
)


def _board_with_scatter(
    *,
    row: int,
    col: int,
    slug: str,
    level: int,
    letter: str = "A",
    color: TileColor = TileColor.RED,
) -> Board:
    board = Board(tiles=[[None] * 5 for _ in range(5)], money=0)
    board.tiles[row][col] = Tile(
        row=row,
        col=col,
        char=letter.lower(),
        letter=letter,
        base_score=1,
        color=color,
        curse=CurseType.ITEM,
        metadata={
            "scattered_item_id": slug,
            "scattered_item_level": level,
        },
    )
    return board


def test_cable_car_stamp_count_counts_each_copy():
    loadout = Loadout(
        stamps=[
            LoadoutItem(id="cable_car", name="Cable Car", level=1),
            LoadoutItem(id="red_envelope", name="Red Envelope", level=1),
            LoadoutItem(id="cable_car", name="Cable Car", level=1),
        ]
    )
    assert cable_car_stamp_count(loadout) == 2
    assert cable_car_stamp_count(None) == 0


def test_grid_path_sticker_level_adds_cable_car_for_on_path_scatter():
    board = _board_with_scatter(row=0, col=0, slug="maple_leaf", level=1)
    loadout = Loadout(
        stamps=[LoadoutItem(id="cable_car", name="Cable Car", level=1)],
        extras={"grid_number": "1", "scoring_previous_words_count": "0"},
    )
    path = [0]
    level = grid_path_sticker_level(
        loadout,
        "maple_leaf",
        board=board,
        path=path,
        path_tile_index=0,
    )
    assert level == 2  # spawn L1 + one Cable Car


def test_grid_path_sticker_level_no_cable_car_without_stamp():
    board = _board_with_scatter(row=0, col=0, slug="maple_leaf", level=1)
    loadout = Loadout(
        extras={"grid_number": "1", "scoring_previous_words_count": "0"},
    )
    assert (
        grid_path_sticker_level(
            loadout,
            "maple_leaf",
            board=board,
            path=[0],
            path_tile_index=0,
        )
        == 1
    )


def test_maple_leaf_l1_plus_cable_car_first_n_is_3():
    """Maple Leaf VV starts at 2; L2 after Cable Car → first 3 reds ×3."""
    pipeline = ScoringPipeline()
    _key, rule = get_rule(pipeline.rules, "stickers", "maple_leaf", "Maple Leaf")
    assert rule is not None
    n = sticker_rule_int(2, rule)  # Level after Cable Car
    assert n == 3


def test_cherry_pie_l2_plus_cable_car_is_times_four():
    pipeline = ScoringPipeline()
    _key, rule = get_rule(pipeline.rules, "stickers", "cherry_pie", "Cherry Pie")
    assert rule is not None
    factor = scaled_word_multiplier(3, rule)  # L2 spawn + Cable Car
    assert factor == 4.0


def test_telescope_l3_plus_cable_car_uses_level_4():
    board = _board_with_scatter(row=1, col=0, slug="telescope", level=3)
    loadout = Loadout(
        stamps=[LoadoutItem(id="cable_car", name="Cable Car", level=1)],
        extras={
            "grid_number": "2",
            "scoring_previous_words_count": "1",
            "historic_words": "[]",
        },
    )
    level = grid_path_sticker_level(
        loadout,
        "telescope",
        board=board,
        path=[5],
        path_tile_index=0,
    )
    assert level == 4
