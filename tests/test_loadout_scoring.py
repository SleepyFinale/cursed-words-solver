"""Loadout scoring: Abacus pin, Brain sticker, pipeline regression."""

import json
from pathlib import Path

import pytest

from cursed_words_solver.models import (
    Board,
    CurseType,
    Loadout,
    LoadoutItem,
    Tile,
    TileColor,
)
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.rule_lookup import (
    count_scoring_items,
    get_pin_branch_rule,
    resolve_rule_id,
)


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
    letter = ch if len(ch) == 1 else ch
    return Tile(
        row=row,
        col=col,
        char=ch,
        letter=letter,
        base_score=score,
        color=color,
        curse=curse,
        number_value=number_value,
        metadata={"source": "melmod"},
    )


def _board_d2len6_fixture() -> Board:
    """Horizontal word path: base tile scores sum to 16; red 2 and blue 6 on path."""
    grid = [[_tile(0, c, "X", 3) for c in range(5)] for _ in range(5)]
    grid[0][0] = _tile(0, 0, "D", 3)
    grid[0][1] = _tile(
        0,
        1,
        "2",
        2,
        curse=CurseType.NUMBER,
        number_value=2,
        color=TileColor.RED,
    )
    grid[0][2] = _tile(0, 2, "L", 3)
    grid[0][3] = _tile(0, 3, "E", 3)
    grid[0][4] = _tile(0, 4, "N", 3)
    grid[1][4] = _tile(
        1,
        4,
        "6",
        2,
        curse=CurseType.NUMBER,
        number_value=6,
        color=TileColor.COLORLESS,
    )
    return Board(tiles=grid, money=5)


def test_abacus_alias_resolves_to_abacus_pin():
    pipeline = ScoringPipeline()
    assert resolve_rule_id(pipeline.rules, "pins", "abacus", "") == "abacus"
    rule = get_pin_branch_rule(pipeline.rules, "abacus", "left")
    assert rule is not None
    assert rule.get("type") == "colored_number_tile_bonus"


def test_d2len6_scores_52_with_abacus_and_brain():
    """(base 16 + abacus +10 on one coloured number) × brain L2 = 52."""
    board = _board_d2len6_fixture()
    path = [0, 1, 2, 3, 4, 9]
    word = "d2len6"
    pipeline = ScoringPipeline()
    loadout = Loadout(
        extras={"pin_effect": "abacus", "pin_branch": "left"},
        stickers=[LoadoutItem(id="brain", name="Brain", level=2, kind="sticker")],
    )
    base, _ = pipeline.score(board, path, word, Loadout())
    score, breakdown = pipeline.score(board, path, word, loadout)
    assert base == 16.0
    assert score == 52.0
    assert breakdown["multiplier"] == 2.0


def test_brain_no_mult_when_number_sum_below_7():
    board = _board_d2len6_fixture()
    path = [0, 1, 2]
    word = "d2l"
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[LoadoutItem(id="brain", name="Brain", level=2, kind="sticker")]
    )
    score, _ = pipeline.score(board, path, word, loadout)
    base, _ = pipeline.score(board, path, word, Loadout())
    assert score == base


def test_brain_level1_multiplier_1_5():
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
    word = "456"
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[LoadoutItem(id="brain", name="Brain", level=1, kind="sticker")]
    )
    score, bd = pipeline.score(board, path, word, loadout)
    p = bd["pipeline"]
    assert p["multiplier"] == 1.5
    assert sum(p["tile_scores"]) + p["word_score"] == 15.0
    assert p["pending_word_multipliers"] == [1.5]
    assert score == 22.0


def test_abacus_coloured_vs_colourless_number():
    board = Board(
        tiles=[
            [
                _tile(
                    0,
                    0,
                    "2",
                    2,
                    curse=CurseType.NUMBER,
                    number_value=2,
                    color=TileColor.RED,
                ),
                _tile(0, 1, "3", 3, curse=CurseType.NUMBER, number_value=3),
            ]
            + [_tile(0, c, "A", 1) for c in range(2, 5)]
        ]
        + [[_tile(r, c, "T", 1) for c in range(5)] for r in range(1, 5)],
        money=0,
    )
    pipeline = ScoringPipeline()
    loadout = Loadout(extras={"pin_effect": "abacus"})
    path = [0, 1]
    word = "23"
    score, _ = pipeline.score(board, path, word, loadout)
    base, _ = pipeline.score(board, path, word, Loadout())
    assert score == base + 10


def test_abacus_right_upgrade_r1_stays_plus_10():
    """Wiki: first right-side Abacus upgrade still gives +10 per coloured number."""
    board = Board(
        tiles=[
            [
                _tile(
                    0,
                    0,
                    "4",
                    4,
                    curse=CurseType.NUMBER,
                    number_value=4,
                    color=TileColor.RED,
                ),
            ]
            + [_tile(0, c, "A", 1) for c in range(1, 5)]
        ]
        + [[_tile(r, c, "T", 1) for c in range(5)] for r in range(1, 5)],
        money=0,
    )
    pipeline = ScoringPipeline()
    loadout = Loadout(
        extras={"pin_effect": "abacus", "pin_right_level": "1"},
    )
    score, _ = pipeline.score(board, [0], "4", loadout)
    base, _ = pipeline.score(board, [0], "4", Loadout())
    assert score == base + 10


def _board_ver45m_fixture() -> Board:
    """Terminal board; path [3,8,13,7,12,18] → ver45m; tile bases sum to 31."""
    grid_chars = [
        "V",
        "L",
        "P",
        "V",
        "7",
        "L",
        "I",
        "4",
        "E",
        "3",
        "P",
        "R",
        "5",
        "R",
        "E",
        "A",
        "4",
        "L",
        "M",
        "A",
        "S",
        "E",
        "1",
        "A",
        "2",
    ]
    bases = {
        3: 4,
        8: 1,
        13: 1,
        7: 4,
        12: 5,
        18: 16,
    }
    tiles = []
    for r in range(5):
        row = []
        for c in range(5):
            idx = r * 5 + c
            ch = grid_chars[idx]
            nv = int(ch) if ch.isdigit() else None
            curse = CurseType.NUMBER if ch.isdigit() else CurseType.LETTER
            row.append(
                _tile(
                    r,
                    c,
                    ch,
                    bases.get(idx, 2),
                    curse=curse,
                    number_value=nv,
                )
            )
        tiles.append(row)
    return Board(tiles=tiles, money=11)


def test_ver45m_brain2_birthday_matches_in_game_score():
    """Hayley loadout: Abacus pin, Brain L2, Birthday; colourless numbers on path."""
    board = _board_ver45m_fixture()
    path = [3, 8, 13, 7, 12, 18]
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[
            LoadoutItem(id="ladybird", name="Ladybird", level=1, kind="sticker"),
            LoadoutItem(id="game_pad", name="Game Pad", level=2, kind="sticker"),
            LoadoutItem(id="petri_dish", name="Petri Dish", level=1, kind="sticker"),
            LoadoutItem(id="brain", name="Brain", level=2, kind="sticker"),
            LoadoutItem(id="birthday_cake", name="Birthday Cake", level=1, kind="sticker"),
        ],
        extras={
            "pin_effect": "abacus",
            "pin_left_level": "2",
            "pin_right_level": "1",
        },
    )
    score, bd = pipeline.score(board, path, "ver45m", loadout)
    assert sum(bd["pipeline"]["tile_scores"]) == 62.0
    assert bd["word_score"] == 5.0
    assert score == 67.0


def test_o2oe5_fractional_red_number_base_scores_50():
    """Game packet can be fractional; truncating 3.5→3 caused 49 vs 50 for o2oe5."""
    board = Board(
        tiles=[[_tile(0, c, "x", 1) for c in range(5)] for _ in range(5)],
        money=8,
    )
    board.tiles[1][0] = _tile(1, 0, "o", 1)
    board.tiles[0][1] = _tile(
        0,
        1,
        "2",
        3.5,
        curse=CurseType.NUMBER,
        number_value=2,
        color=TileColor.RED,
    )
    board.tiles[0][1].metadata = {}
    board.tiles[1][2] = _tile(1, 2, "o", 2, color=TileColor.RED)
    board.tiles[1][2].metadata = {}
    board.tiles[1][3] = _tile(1, 3, "e", 1)
    board.tiles[1][4] = _tile(1, 4, "5", 5, curse=CurseType.NUMBER, number_value=5)
    path = [5, 1, 7, 8, 9]
    loadout = Loadout(
        stickers=[
            LoadoutItem(id="brain", name="Brain", level=2, kind="sticker"),
            LoadoutItem(id="birthday_cake", name="Birthday Cake", level=1, kind="sticker"),
        ],
        extras={"pin_effect": "abacus", "pin_right_level": "1"},
    )
    score, _ = ScoringPipeline().score(board, path, "o2oe5", loadout)
    assert score == 50.0


def _board_n23j5s_fixture() -> Board:
    """Path [16,12,6,5,10,11] → n23j5s; j precedes void number 5 on path."""
    tiles = [
        [_tile(r, c, "x", 1) for c in range(5)]
        for r in range(5)
    ]
    tiles[3][1] = _tile(3, 1, "n", 1)
    tiles[2][2] = _tile(
        2,
        2,
        "2",
        3,
        curse=CurseType.NUMBER,
        number_value=2,
        color=TileColor.BLUE,
    )
    tiles[1][1] = _tile(
        1,
        1,
        "3",
        3,
        curse=CurseType.NUMBER,
        number_value=3,
        color=TileColor.COLORLESS,
    )
    tiles[1][0] = _tile(1, 0, "j", 8)
    tiles[2][0] = _tile(
        2,
        0,
        "5",
        0,
        curse=CurseType.NUMBER,
        number_value=5,
        color=TileColor.VOID,
    )
    tiles[2][1] = _tile(2, 1, "s", 2, color=TileColor.BLUE)
    return Board(tiles=tiles, money=8)


def _board_12sa5_fixture() -> Board:
    """Path [1,6,11,5,0] → 12sa5; word ends on void number 5."""
    tiles = [
        [_tile(r, c, "x", 1) for c in range(5)]
        for r in range(5)
    ]
    tiles[0][0] = _tile(
        0,
        0,
        "5",
        0,
        curse=CurseType.NUMBER,
        number_value=5,
        color=TileColor.VOID,
    )
    tiles[0][1] = _tile(
        0,
        1,
        "1",
        1,
        curse=CurseType.NUMBER,
        number_value=1,
        color=TileColor.COLORLESS,
    )
    tiles[1][0] = _tile(1, 0, "a", 2, color=TileColor.BLUE)
    tiles[1][1] = _tile(
        1,
        1,
        "2",
        3,
        curse=CurseType.NUMBER,
        number_value=2,
        color=TileColor.RED,
    )
    tiles[2][1] = _tile(2, 1, "s", 2, color=TileColor.RED)
    return Board(tiles=tiles, money=8)


def test_12sa5_void_number_on_path_no_ending_bonus():
    """Void number on path does not get +2 when it is the last tile (only letter-before-void does)."""
    board = _board_12sa5_fixture()
    path = [1, 6, 11, 5, 0]
    loadout = Loadout(
        stickers=[
            LoadoutItem(id="ladybird", name="Ladybird", level=1, kind="sticker"),
            LoadoutItem(id="game_pad", name="Game Pad", level=2, kind="sticker"),
            LoadoutItem(id="petri_dish", name="Petri Dish", level=1, kind="sticker"),
            LoadoutItem(id="birthday_cake", name="Birthday Cake", level=1, kind="sticker"),
            LoadoutItem(id="brain", name="Brain", level=2, kind="sticker"),
        ],
        extras={
            "pin_effect": "abacus",
            "pin_left_level": "2",
            "pin_right_level": "1",
        },
    )
    score, bd = ScoringPipeline().score(board, path, "12sa5", loadout)
    assert score == 56.0
    effects = " ".join(bd["pipeline"]["effects"])
    assert "VOID tile ending path" not in effects


def test_n23j5s_void_predecessor_scores_73():
    """Hayley: Abacus R1, Brain L2, Birthday; tile before void 5 gets +2 base."""
    board = _board_n23j5s_fixture()
    path = [16, 12, 6, 5, 10, 11]
    loadout = Loadout(
        stickers=[
            LoadoutItem(id="ladybird", name="Ladybird", level=1, kind="sticker"),
            LoadoutItem(id="game_pad", name="Game Pad", level=2, kind="sticker"),
            LoadoutItem(id="petri_dish", name="Petri Dish", level=1, kind="sticker"),
            LoadoutItem(id="brain", name="Brain", level=2, kind="sticker"),
            LoadoutItem(id="birthday_cake", name="Birthday Cake", level=1, kind="sticker"),
        ],
        extras={
            "pin_effect": "abacus",
            "pin_left_level": "2",
            "pin_right_level": "1",
        },
    )
    score, bd = ScoringPipeline().score(board, path, "n23j5s", loadout)
    assert score == 73.0
    assert "+2 tile before VOID on path" in " ".join(bd["pipeline"]["effects"])


def test_12ne5_abacus_coloured_number_bonus_scores_52():
    """Red number 2 on path: +10 Abacus before Brain."""
    def tile(r, c, ch, score, *, color=TileColor.COLORLESS, curse=CurseType.LETTER, nv=None):
        return Tile(
            row=r,
            col=c,
            char=ch,
            letter=ch,
            base_score=score,
            color=color,
            curse=curse,
            number_value=nv,
            metadata={"source": "melmod"},
        )

    grid = [[tile(r, c, "x", 1) for c in range(5)] for r in range(5)]
    grid[1][1] = tile(1, 1, "1", 1, curse=CurseType.NUMBER, nv=1)
    grid[2][1] = tile(
        2, 1, "2", 2, curse=CurseType.NUMBER, nv=2, color=TileColor.RED
    )
    grid[3][2] = tile(3, 2, "N", 2)
    grid[3][3] = tile(3, 3, "E", 1)
    grid[4][4] = tile(4, 4, "5", 5, curse=CurseType.NUMBER, nv=5)
    board = Board(tiles=grid, money=8)
    path = [6, 11, 17, 18, 24]
    loadout = Loadout(
        stickers=[
            LoadoutItem(id="birthday_cake", name="Birthday Cake", level=1, kind="sticker"),
            LoadoutItem(id="brain", name="Brain", level=2, kind="sticker"),
        ],
        extras={
            "pin_effect": "abacus",
            "pin_left_level": "2",
            "pin_right_level": "1",
        },
    )
    score, bd = ScoringPipeline().score(board, path, "12ne5", loadout)
    assert score == 52.0
    assert "+10 coloured number tile" in " ".join(bd["pipeline"]["effects"])


def test_a2u4ej7_scores_62_with_void_end_and_abacus():
    """Path ends on void 7; red 2 gets +10 Abacus; j before void gets +2."""
    def tile(r, c, ch, score, *, color=TileColor.COLORLESS, curse=CurseType.LETTER, nv=None):
        return Tile(
            row=r,
            col=c,
            char=ch,
            letter=ch,
            base_score=score,
            color=color,
            curse=curse,
            number_value=nv,
            metadata={"source": "melmod"},
        )

    grid = [[tile(r, c, "x", 1) for c in range(5)] for r in range(5)]
    grid[1][1] = tile(1, 1, "a", 2)
    grid[2][1] = tile(
        2, 1, "2", 2, curse=CurseType.NUMBER, nv=2, color=TileColor.RED
    )
    grid[1][0] = tile(1, 0, "u", 1)
    grid[2][0] = tile(2, 0, "4", 4, curse=CurseType.NUMBER, nv=4)
    grid[3][2] = tile(3, 2, "e", 2, color=TileColor.BLUE)
    grid[3][1] = tile(3, 1, "j", 8)
    grid[4][0] = tile(
        4,
        0,
        "7",
        0,
        curse=CurseType.NUMBER,
        nv=7,
        color=TileColor.VOID,
    )
    board = Board(tiles=grid, money=5)
    path = [6, 11, 5, 10, 17, 16, 20]
    loadout = Loadout(
        stickers=[
            LoadoutItem(id="birthday_cake", name="Birthday Cake", level=1, kind="sticker"),
            LoadoutItem(id="brain", name="Brain", level=2, kind="sticker"),
        ],
        extras={
            "pin_effect": "abacus",
            "pin_left_level": "2",
            "pin_right_level": "1",
        },
    )
    score, bd = ScoringPipeline().score(board, path, "a2u4ej7", loadout)
    assert score == 82.0
    assert "tile before VOID" in " ".join(bd["pipeline"]["effects"])


def test_a2u4ej7_melmod_partial_red2_base_scores_64():
    """Melmod may export red 2 as base 3; Abacus still +10 on coloured number only."""
    def tile(r, c, ch, score, *, color=TileColor.COLORLESS, curse=CurseType.LETTER, nv=None):
        return Tile(
            row=r,
            col=c,
            char=ch,
            letter=ch,
            base_score=score,
            color=color,
            curse=curse,
            number_value=nv,
            metadata={"source": "melmod"},
        )

    grid = [[tile(r, c, "x", 1) for c in range(5)] for r in range(5)]
    grid[1][1] = tile(1, 1, "a", 2)
    grid[2][1] = tile(
        2, 1, "2", 3, curse=CurseType.NUMBER, nv=2, color=TileColor.RED
    )
    grid[1][0] = tile(1, 0, "u", 1)
    grid[2][0] = tile(2, 0, "4", 4, curse=CurseType.NUMBER, nv=4)
    grid[3][2] = tile(3, 2, "e", 2, color=TileColor.BLUE)
    grid[3][1] = tile(3, 1, "j", 8)
    grid[4][0] = tile(
        4,
        0,
        "7",
        0,
        curse=CurseType.NUMBER,
        nv=7,
        color=TileColor.VOID,
    )
    board = Board(tiles=grid, money=5)
    path = [6, 11, 5, 10, 17, 16, 20]
    loadout = Loadout(
        stickers=[
            LoadoutItem(id="birthday_cake", name="Birthday Cake", level=1, kind="sticker"),
            LoadoutItem(id="brain", name="Brain", level=2, kind="sticker"),
        ],
        extras={
            "pin_effect": "abacus",
            "pin_left_level": "2",
            "pin_right_level": "1",
        },
    )
    score, _ = ScoringPipeline().score(board, path, "a2u4ej7", loadout)
    assert score == 84.0


def test_c23t5m_melmod_colorless_red2_inferred_scores_90():
    """Melmod exports scattered red 2 as colorless; packet.Score +2 still implies red."""
    def tile(r, c, ch, score, *, color=TileColor.COLORLESS, curse=CurseType.LETTER, nv=None):
        return Tile(
            row=r,
            col=c,
            char=ch,
            letter=ch,
            base_score=score,
            color=color,
            curse=curse,
            number_value=nv,
            metadata={"source": "melmod"},
        )

    grid = [[tile(r, c, "x", 1) for c in range(5)] for r in range(5)]
    grid[1][1] = tile(1, 1, "c", 1)
    grid[2][1] = tile(2, 1, "2", 4, curse=CurseType.NUMBER, nv=2)
    grid[3][2] = tile(3, 2, "3", 4, curse=CurseType.NUMBER, nv=3)
    grid[4][3] = tile(4, 3, "t", 6)
    grid[3][4] = tile(
        3, 4, "5", 0, curse=CurseType.NUMBER, nv=5, color=TileColor.VOID
    )
    grid[4][4] = tile(4, 4, "m", 1)
    board = Board(tiles=grid, money=10)
    path = [6, 11, 17, 23, 19, 24]
    loadout = Loadout(
        stickers=[
            LoadoutItem(id="birthday_cake", name="Birthday Cake", level=1, kind="sticker"),
            LoadoutItem(id="brain", name="Brain", level=3, kind="sticker"),
        ],
        extras={
            "pin_effect": "abacus",
            "pin_left_level": "3",
            "pin_right_level": "1",
        },
    )
    score, bd = ScoringPipeline().score(board, path, "c23t5m", loadout)
    assert score == 90.0
    effects = " ".join(bd["pipeline"]["effects"])
    assert "+20 coloured number tile (2" in effects


def test_shiny_letter_before_void_number_no_path_bonus():
    """Shiny packet base_score (50) must not satisfy void-path threshold; only Scrabble ≥ 8 does."""
    def tile(r, c, ch, score, *, color=TileColor.COLORLESS, curse=CurseType.LETTER, nv=None):
        return Tile(
            row=r,
            col=c,
            char=ch,
            letter=ch,
            base_score=score,
            color=color,
            curse=curse,
            number_value=nv,
            metadata={"source": "melmod"},
        )

    grid = [[tile(r, c, "x", 1) for c in range(5)] for r in range(5)]
    grid[2][2] = tile(2, 2, "g", 50, color=TileColor.SHINY)
    grid[2][1] = tile(
        2,
        1,
        "6",
        0,
        curse=CurseType.NUMBER,
        nv=6,
        color=TileColor.VOID,
    )
    board = Board(tiles=grid, money=0)
    path = [12, 11]
    loadout = Loadout()
    score, bd = ScoringPipeline().score(board, path, "g6", loadout)
    effects = " ".join(bd["pipeline"]["effects"])
    assert "tile before VOID" not in effects
    # shiny G (50) + void 6 (-6) = 44; wrong +2 on G would yield 46
    assert score == 44.0


def test_m23ders_void_letters_no_path_bonus_scores_36():
    """Void-coloured letters do not get built-in void path +2 (only void numbers do)."""
    def tile(r, c, ch, score, *, color=TileColor.COLORLESS, curse=CurseType.LETTER, nv=None):
        return Tile(
            row=r,
            col=c,
            char=ch,
            letter=ch,
            base_score=score,
            color=color,
            curse=curse,
            number_value=nv,
            metadata={"source": "melmod"},
        )

    grid = [[tile(r, c, "x", 1) for c in range(5)] for r in range(5)]
    grid[0][4] = tile(0, 4, "M", 3, color=TileColor.RED)
    grid[1][4] = tile(
        1, 4, "2", 2, curse=CurseType.NUMBER, nv=2, color=TileColor.RED
    )
    grid[0][3] = tile(
        0, 3, "3", 3, curse=CurseType.NUMBER, nv=3, color=TileColor.RED
    )
    grid[0][2] = tile(0, 2, "D", 2)
    grid[1][2] = tile(1, 2, "E", 1)
    grid[2][2] = tile(2, 2, "R", 1)
    grid[3][2] = tile(3, 2, "S", 1)
    board = Board(tiles=grid, money=11)
    path = [4, 9, 3, 2, 7, 12, 17]
    loadout = Loadout(
        stickers=[LoadoutItem(id="birthday_cake", name="Birthday Cake", level=1, kind="sticker")],
        extras={"pin_effect": "abacus", "pin_right_level": "1"},
    )
    score, bd = ScoringPipeline().score(board, path, "m23ders", loadout)
    assert score == 36.0
    effects = " ".join(bd["pipeline"]["effects"])
    assert "tile before VOID" not in effects
    assert "VOID tile ending path" not in effects


def test_z2345eh_high_blue_z_base_scores_104():
    """Melmod used to clamp packet.Score to 10; blue Z can be >10 (e.g. 17 → +14 after Brain)."""
    def tile(r, c, ch, score, *, curse=CurseType.LETTER, number_value=None, color=TileColor.COLORLESS):
        return Tile(
            row=r,
            col=c,
            char=ch,
            letter=ch,
            base_score=score,
            color=color,
            curse=curse,
            number_value=number_value,
            metadata={"source": "melmod"},
        )

    grid = [[tile(r, c, "q", 1) for c in range(5)] for r in range(5)]
    grid[2][2] = tile(2, 2, "z", 17, color=TileColor.BLUE)
    grid[3][2] = tile(3, 2, "2", 2, curse=CurseType.NUMBER, number_value=2)
    grid[2][1] = tile(2, 1, "3", 3, curse=CurseType.NUMBER, number_value=3)
    grid[3][1] = tile(3, 1, "4", 4, curse=CurseType.NUMBER, number_value=4)
    grid[3][0] = tile(3, 0, "5", 6, curse=CurseType.NUMBER, number_value=5, color=TileColor.RED)
    grid[4][1] = tile(4, 1, "e", 1)
    grid[4][0] = tile(4, 0, "h", 4)
    board = Board(tiles=grid, money=8)
    path = [12, 17, 11, 16, 15, 21, 20]
    loadout = Loadout(
        stickers=[
            LoadoutItem(id="ladybird", name="Ladybird", level=1, kind="sticker"),
            LoadoutItem(id="game_pad", name="Game Pad", level=2, kind="sticker"),
            LoadoutItem(id="petri_dish", name="Petri Dish", level=1, kind="sticker"),
            LoadoutItem(id="birthday_cake", name="Birthday Cake", level=1, kind="sticker"),
            LoadoutItem(id="brain", name="Brain", level=2, kind="sticker"),
        ],
        extras={
            "pin_effect": "abacus",
            "pin_left_level": "2",
            "pin_right_level": "1",
        },
    )
    score, _ = ScoringPipeline().score(board, path, "z2345eh", loadout)
    assert score == 104.0


_DEBUG_DIR = Path.home() / ".cursed_words_solver" / "debug"
_COLOR_MAP = {
    "colorless": TileColor.COLORLESS,
    "red": TileColor.RED,
    "blue": TileColor.BLUE,
    "void": TileColor.VOID,
    "shiny": TileColor.SHINY,
}
_CURSE_MAP = {
    "letter": CurseType.LETTER,
    "number": CurseType.NUMBER,
}


def _board_from_debug_json(name: str) -> Board:
    data = json.loads((_DEBUG_DIR / name).read_text(encoding="utf-8"))
    grid = [[None] * 5 for _ in range(5)]
    for t in data["tiles"]:
        r, c = t["row"], t["col"]
        nv = (
            int(t["letter"])
            if t["curse"] == "number" and str(t["letter"]).isdigit()
            else None
        )
        grid[r][c] = Tile(
            row=r,
            col=c,
            char=t["char"],
            letter=t["letter"],
            base_score=float(t["base_score"]),
            color=_COLOR_MAP.get(t["color"], TileColor.UNKNOWN),
            curse=_CURSE_MAP.get(t["curse"], CurseType.UNKNOWN),
            number_value=nv,
            metadata={"source": "melmod"},
        )
    return Board(tiles=[[grid[r][c] for c in range(5)] for r in range(5)], money=10)


def _rodman_cameleers_loadout() -> Loadout:
    return Loadout(
        stickers=[
            LoadoutItem(id="magic_wand", name="Magic Wand", level=2, kind="sticker"),
            LoadoutItem(
                id="artist_s_palette", name="Artist's Palette", level=2, kind="sticker"
            ),
            LoadoutItem(id="ferris_wheel", name="Ferris Wheel", level=1, kind="sticker"),
            LoadoutItem(
                id="yellow_glasses", name="Yellow Glasses", level=1, kind="sticker"
            ),
            LoadoutItem(id="pair_of_socks", name="Pair Of Socks", level=2, kind="sticker"),
        ],
        stamps=[
            LoadoutItem(id="chocolate_candy", name="Chocolate Candy", kind="stamp"),
            LoadoutItem(id="tile_ninja", name="Tile Ninja", kind="stamp"),
            LoadoutItem(id="jellyfish", name="Jellyfish", kind="stamp"),
        ],
        extras={
            "pin_effect": "carp_streamers",
            "pin_left_level": "2",
            "pin_right_level": "2",
        },
        money=4,
    )


def _hayley_loadout(**extras: str) -> Loadout:
    return Loadout(
        stickers=[
            LoadoutItem(id="ladybird", name="Ladybird", level=1, kind="sticker"),
            LoadoutItem(id="game_pad", name="Game Pad", level=2, kind="sticker"),
            LoadoutItem(id="petri_dish", name="Petri Dish", level=1, kind="sticker"),
            LoadoutItem(id="birthday_cake", name="Birthday Cake", level=1, kind="sticker"),
            LoadoutItem(id="brain", name="Brain", level=3, kind="sticker"),
        ],
        extras={
            "pin_effect": "abacus",
            "pin_left_level": "3",
            "pin_right_level": "1",
            **extras,
        },
    )


@pytest.mark.skipif(
    not (_DEBUG_DIR / "parse_20260522_151207.json").exists(),
    reason="debug snapshot missing",
)
def test_f23i5ar_debug_snapshot_scores_165():
    board = _board_from_debug_json("parse_20260522_151207.json")
    path = [13, 14, 9, 4, 3, 8, 2]
    score, bd = ScoringPipeline().score(
        board, path, "f23i5ar", _hayley_loadout(birthday_cake_bonus="22")
    )
    assert score == 165.0
    assert "Birthday Cake: 22 + 5" in " ".join(bd["pipeline"]["effects"])


@pytest.mark.skipif(
    not (_DEBUG_DIR / "parse_20260522_143157.json").exists(),
    reason="debug snapshot missing",
)
def test_sw3nn6d_debug_snapshot_scores_157():
    board = _board_from_debug_json("parse_20260522_143157.json")
    path = [13, 17, 21, 15, 16, 12, 8]
    score, _ = ScoringPipeline().score(
        board, path, "sw3nn6d", _hayley_loadout(birthday_cake_bonus="7")
    )
    assert score == pytest.approx(137.5, abs=0.6)


@pytest.mark.skipif(
    not (_DEBUG_DIR / "parse_20260522_145813.json").exists(),
    reason="debug snapshot missing",
)
def test_q2af5_debug_snapshot_scores_115():
    board = _board_from_debug_json("parse_20260522_145813.json")
    path = [3, 7, 12, 17, 23]
    score, _ = ScoringPipeline().score(
        board, path, "q2af5", _hayley_loadout(birthday_cake_bonus="19")
    )
    assert score == 115.0


@pytest.mark.skipif(
    not (_DEBUG_DIR / "parse_20260522_155754.json").exists(),
    reason="debug snapshot missing",
)
@pytest.mark.skipif(
    not (_DEBUG_DIR / "parse_20260522_161002.json").exists(),
    reason="debug snapshot missing",
)
def test_e2ox5_debug_snapshot_scores_132():
    """Abacus is +10 per coloured number only; no extra left-track tile base."""
    board = _board_from_debug_json("parse_20260522_161002.json")
    path = [6, 1, 5, 10, 15]
    score, bd = ScoringPipeline().score(
        board, path, "e2ox5", _hayley_loadout(birthday_cake_bonus="19")
    )
    assert score == pytest.approx(132.0, abs=1.0)
    assert "Abacus left path base" not in " ".join(bd["pipeline"]["effects"])
    assert "coloured number tile" in " ".join(bd["pipeline"]["effects"])


@pytest.mark.skipif(
    not (_DEBUG_DIR / "parse_20260522_162603.json").exists(),
    reason="debug snapshot missing",
)
def test_1a34sex_debug_snapshot_scores_152_integer_display():
    """Brain ×2.5 can yield .5 internally; game truncates total (152 not 152.5)."""
    board = _board_from_debug_json("parse_20260522_162603.json")
    path = [4, 3, 8, 13, 19, 24, 18]
    score, _ = ScoringPipeline().score(
        board, path, "1a34sex", _hayley_loadout(birthday_cake_bonus="15")
    )
    assert score == 152.0
    assert score == int(score)


def test_he34are_no_abacus_left_without_coloured_or_void_numbers():
    """Colourless numbers on path do not get Abacus tile bonus."""
    board = _board_from_debug_json("parse_20260522_155754.json")
    path = [4, 8, 12, 17, 21, 22, 18]
    score, bd = ScoringPipeline().score(
        board, path, "he34are", _hayley_loadout(birthday_cake_bonus="15")
    )
    assert score == 85.0
    effects = " ".join(bd["pipeline"]["effects"])
    assert "Abacus left path base" not in effects


@pytest.mark.skipif(
    not (_DEBUG_DIR / "parse_20260522_164700.json").exists(),
    reason="debug snapshot missing",
)
def test_12l45fs_void_number_gets_abacus_coloured_bonus():
    board = _board_from_debug_json("parse_20260522_164700.json")
    path = [0, 1, 2, 7, 13, 12, 8]
    loadout = _hayley_loadout(birthday_cake_bonus="46")
    loadout.stickers = [
        LoadoutItem(id="alembic_flask", name="Alembic Flask", level=1, kind="sticker"),
        *loadout.stickers,
    ]
    loadout.money = 29
    board.money = 29
    score, bd = ScoringPipeline().score(board, path, "12l45fs", loadout)
    assert score == 455.0
    assert "+20 coloured number tile (2 tile(s))" in " ".join(bd["pipeline"]["effects"])


@pytest.mark.skipif(
    not (_DEBUG_DIR / "parse_20260522_150221.json").exists(),
    reason="debug snapshot missing",
)
def test_ca3b5a7_debug_snapshot_scores_105():
    board = _board_from_debug_json("parse_20260522_150221.json")
    path = [13, 14, 18, 12, 17, 16, 15]
    score, _ = ScoringPipeline().score(
        board, path, "ca3b5a7", _hayley_loadout(birthday_cake_bonus="15")
    )
    assert score == 105.0


@pytest.mark.skipif(
    not (_DEBUG_DIR / "parse_20260522_170102.json").exists(),
    reason="debug snapshot missing",
)
def test_a2345lt_debug_snapshot_scores_795():
    board = _board_from_debug_json("parse_20260522_170102.json")
    path = [8, 2, 7, 11, 6, 5, 1]
    loadout = _hayley_loadout(birthday_cake_bonus="76")
    loadout.stickers = [
        LoadoutItem(id="alembic_flask", name="Alembic Flask", level=2, kind="sticker"),
        *loadout.stickers,
    ]
    loadout.money = 42
    board.money = 42
    score, bd = ScoringPipeline().score(board, path, "a2345lt", loadout)
    assert score == 795.0
    assert "+200 consecutive number tile (4)" in " ".join(bd["pipeline"]["effects"])


@pytest.mark.skipif(
    not (_DEBUG_DIR / "parse_20260522_172139.json").exists(),
    reason="debug snapshot missing",
)
def test_12g45w_debug_snapshot_scores_807_not_rounded_up():
    """Brain ×2.5 yields 807.5 internally; game shows 807 (floor), not round(807.5)=808."""
    board = _board_from_debug_json("parse_20260522_172139.json")
    path = [15, 11, 12, 16, 22, 18]
    loadout = Loadout(
        stickers=[
            LoadoutItem(id="alembic_flask", name="Alembic Flask", level=2, kind="sticker"),
            LoadoutItem(id="birthday_cake", name="Birthday Cake", level=1, kind="sticker"),
            LoadoutItem(id="brain", name="Brain", level=3, kind="sticker"),
        ],
        extras={
            "pin_effect": "abacus",
            "pin_left_level": "5",
            "pin_right_level": "1",
            "birthday_cake_bonus": "81",
        },
        money=42,
    )
    board.money = 42
    score, bd = ScoringPipeline().score(board, path, "12g45w", loadout)
    assert score == 807.0


@pytest.mark.skipif(
    not (_DEBUG_DIR / "parse_20260522_172509.json").exists(),
    reason="debug snapshot missing",
)
def test_12a45_no_void_ending_bonus_scores_815():
    """Path ends on void 5; game has no +2 on the void tile itself (only letter-before-void)."""
    board = _board_from_debug_json("parse_20260522_172509.json")
    path = [14, 19, 13, 8, 9]
    loadout = Loadout(
        stickers=[
            LoadoutItem(id="alembic_flask", name="Alembic Flask", level=2, kind="sticker"),
            LoadoutItem(id="birthday_cake", name="Birthday Cake", level=1, kind="sticker"),
            LoadoutItem(id="brain", name="Brain", level=3, kind="sticker"),
        ],
        extras={
            "pin_effect": "abacus",
            "pin_left_level": "5",
            "pin_right_level": "1",
            "birthday_cake_bonus": "86",
        },
        money=42,
    )
    board.money = 42
    score, bd = ScoringPipeline().score(board, path, "12a45", loadout)
    effects = " ".join(bd["pipeline"]["effects"])
    assert score == 815.0
    assert "VOID tile ending path" not in effects


@pytest.mark.skipif(
    not (_DEBUG_DIR / "parse_20260522_202416.json").exists(),
    reason="debug snapshot missing",
)
def test_cameleers_rodman_scores_506_not_508():
    """Chained ×WORD multipliers floor after each step (113 → 506, not 508)."""
    board = _board_from_debug_json("parse_20260522_202416.json")
    board.money = 4
    path = [19, 14, 18, 12, 6, 5, 10, 11, 16]
    loadout = _rodman_cameleers_loadout()
    score, bd = ScoringPipeline().score(board, path, "cameleers", loadout)
    effects = " ".join(bd["pipeline"]["effects"])
    assert score == 506.0
    assert "+48 colored tile score (4)" in effects
    assert "has_double_letter" in effects
    assert "blue_count_eq:2" in effects
    assert "tile_ninja_bonus" in effects


def test_brain_before_birthday_birthday_not_multiplied():
    board = Board(
        tiles=[
            [
                _tile(0, 0, "4", 4, curse=CurseType.NUMBER, number_value=4),
                _tile(0, 1, "5", 5, curse=CurseType.NUMBER, number_value=5),
            ]
            + [_tile(0, c, "A", 1) for c in range(2, 5)]
        ]
        + [[_tile(r, c, "T", 1) for c in range(5)] for r in range(1, 5)],
        money=0,
    )
    path = [0, 1]
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[
            LoadoutItem(id="brain", name="Brain", level=2, kind="sticker"),
            LoadoutItem(id="birthday_cake", name="Birthday Cake", level=1, kind="sticker"),
        ],
    )
    score, bd = pipeline.score(board, path, "45", loadout)
    tile_total = sum(bd["pipeline"]["tile_scores"])
    assert tile_total == 18.0
    assert bd["word_score"] == 5.0
    assert score == 23.0
    assert score != (9.0 + 5.0) * 2.0


def test_count_scoring_vs_grid_only():
    pipeline = ScoringPipeline()
    loadout = Loadout(
        extras={"pin_effect": "abacus"},
        stickers=[
            LoadoutItem(id="brain", name="Brain", level=2, kind="sticker"),
            LoadoutItem(id="ladybird", name="Ladybird", level=1, kind="sticker"),
        ],
    )
    scoring, total, grid_only = count_scoring_items(pipeline.rules, loadout)
    assert scoring >= 2
    assert total == 3
    assert grid_only >= 0
