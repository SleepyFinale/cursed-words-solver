"""Hayley Bayles unlock sticker scoring."""

import json
from pathlib import Path

from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
from cursed_words_solver.models import (
    Board,
    CurseType,
    Loadout,
    LoadoutItem,
    Tile,
    TileColor,
)
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.rule_lookup import count_scoring_items, get_rule, slugify_name

HAYLEY_STICKER_NAMES = [
    "Alembic Flask",
    "Birthday Cake",
    "Boomerang",
    "Brain",
    "Lab Coat",
    "Ladybird",
    "Lucky Dice",
    "Petri Dish",
    "Soaring Kite",
    "Ten Pin Bowling",
    "Traffic Lights",
]

GRID_ONLY_SLUGS = {
    "ladybird",
    "petri_dish",
    "soaring_kite",
    "ten_pin_bowling",
    "traffic_lights",
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


def test_all_hayley_stickers_catalogued():
    pipeline = ScoringPipeline()
    for name in HAYLEY_STICKER_NAMES:
        slug = slugify_name(name)
        _key, rule = get_rule(pipeline.rules, "stickers", slug, name)
        assert rule is not None, slug
        assert rule.get("type") != "unmodeled", slug


def test_count_scoring_vs_grid_only_hayley():
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[
            LoadoutItem(id=slugify_name(n), name=n, level=1, kind="sticker")
            for n in HAYLEY_STICKER_NAMES
        ]
    )
    scoring, total, grid_only = count_scoring_items(pipeline.rules, loadout)
    assert total == 11
    assert grid_only == len(GRID_ONLY_SLUGS)
    assert scoring == 11 - len(GRID_ONLY_SLUGS)


def test_alembic_flask_consecutive_number_bonus():
    board = Board(
        tiles=[
            [
                _tile(0, 0, "4", 4, curse=CurseType.NUMBER, number_value=4),
                _tile(0, 1, "5", 5, curse=CurseType.NUMBER, number_value=5),
                _tile(0, 2, "6", 6, curse=CurseType.NUMBER, number_value=6),
            ]
            + [_tile(0, c, "A", 1) for c in range(3, 5)]
        ]
        + [[_tile(r, c, "T", 1) for c in range(5)] for r in range(1, 5)],
        money=0,
    )
    path = [0, 1, 2]
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[LoadoutItem(id="alembic_flask", name="Alembic Flask", level=1)]
    )
    score, bd = pipeline.score(board, path, "456", loadout)
    base, base_bd = pipeline.score(board, path, "456", Loadout())
    assert sum(bd["pipeline"]["tile_scores"]) == sum(base_bd["pipeline"]["tile_scores"]) + 75
    assert score == base + 75


def test_birthday_cake_accumulated_plus_improve():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "3", 3, curse=CurseType.NUMBER, number_value=3)
    board.tiles[0][1] = _tile(0, 1, "7", 7, curse=CurseType.NUMBER, number_value=7)
    board.tiles[0][2] = _tile(0, 2, "A", 2)
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[LoadoutItem(id="birthday_cake", name="Birthday Cake", level=1)],
        extras={"birthday_cake_bonus": "22"},
    )
    score, bd = pipeline.score(board, [0, 1, 2], "37a", loadout)
    base, _ = pipeline.score(board, [0, 1, 2], "37a", Loadout())
    assert score == base + 29
    assert "Birthday Cake: 22 + 7" in " ".join(bd["pipeline"]["effects"])


def test_bordonua_fraction_improve_rounds_to_match_game():
    """Regression: 0.875×3 must round to 3, not stay 2.625 (1602 not 1601)."""
    fixture = (
        Path(__file__).resolve().parents[2] / "fixtures" / "fraction_ov_run_state.json"
    )
    run_state = json.loads(fixture.read_text(encoding="utf-8"))
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    path = [13, 9, 8, 12, 7, 6, 2, 3]
    score, bd = ScoringPipeline().score(board, path, "bordonua", loadout)
    assert score == 1602.0
    assert "Birthday Cake: 139 + 3" in " ".join(bd["pipeline"]["effects"])


def test_boomerang_number_start_end_multiply():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "2", 2, curse=CurseType.NUMBER, number_value=2)
    board.tiles[0][1] = _tile(0, 1, "A", 4)
    board.tiles[0][2] = _tile(0, 2, "5", 5, curse=CurseType.NUMBER, number_value=5)
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="boomerang", name="Boomerang", level=1)])
    score, bd = pipeline.score(board, [0, 1, 2], "2a5", loadout)
    base, _ = pipeline.score(board, [0, 1, 2], "2a5", Loadout())
    assert bd["multiplier"] == 2.0
    assert score == base * 2


def test_boomerang_letter_ends_no_mult():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "2", 2, curse=CurseType.NUMBER, number_value=2)
    board.tiles[0][1] = _tile(0, 1, "B", 4)
    board.tiles[0][2] = _tile(0, 2, "C", 4)
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="boomerang", name="Boomerang", level=1)])
    score, bd = pipeline.score(board, [0, 1, 2], "2bc", loadout)
    base, _ = pipeline.score(board, [0, 1, 2], "2bc", Loadout())
    assert bd["multiplier"] == 1.0
    assert score == base


def test_lucky_dice_target_number_bonus():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "2", 2, curse=CurseType.NUMBER, number_value=2)
    board.tiles[0][1] = _tile(0, 1, "A", 3)
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[LoadoutItem(id="lucky_dice", name="Lucky Dice", level=1)],
        extras={"target_number": 2},
    )
    score, bd = pipeline.score(board, [0, 1], "2a", loadout)
    base, base_bd = pipeline.score(board, [0, 1], "2a", Loadout())
    assert bd["word_score"] == base_bd["word_score"] + 50
    assert score == base + 50


def test_abacus_only_coloured_number_tile_bonus_not_left_track():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "e", 2, color=TileColor.RED)
    board.tiles[0][1] = _tile(
        0,
        1,
        "2",
        3,
        curse=CurseType.NUMBER,
        number_value=2,
        color=TileColor.BLUE,
    )
    loadout = Loadout(extras={"pin_effect": "abacus", "pin_left_level": "3"})
    pipeline = ScoringPipeline()
    score, bd = pipeline.score(board, [0, 1], "e2", loadout)
    base, _ = pipeline.score(board, [0, 1], "e2", Loadout())
    assert score == base + 10
    assert "coloured number tile" in " ".join(bd["pipeline"]["effects"])
    assert "Abacus left path base" not in " ".join(bd["pipeline"]["effects"])


def test_lucky_dice_inactive_without_target():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "2", 2, curse=CurseType.NUMBER, number_value=2)
    board.tiles[0][1] = _tile(0, 1, "A", 3)
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="lucky_dice", name="Lucky Dice", level=1)])
    score, _ = pipeline.score(board, [0, 1], "2a", loadout)
    base, _ = pipeline.score(board, [0, 1], "2a", Loadout())
    assert score == base
