"""DLC item ports (engine/dlc_items.py) on boards with DLC glyph tiles.

Expected values follow the decompiled ``ApplyTileBonus`` / ``ApplyWordBonus`` /
``ApplySubmissionBonus`` bodies (docs/game-research/_decompiled/dlc).
"""

from __future__ import annotations

import random

from cursed_words_solver.engine import EnginePlan
from cursed_words_solver.engine.model import ZODIAC_ORDER
from cursed_words_solver.models import Board, Loadout

from tests.engine.test_engine_item_rules import _loadout, _state, _word_mult, var
from tests.engine.test_engine_units import _board

ROWS = ["catdo", "xxxxx", "xxxxx", "xxxxx", "xxxxx"]
DIE = {n: chr(0x2680 + n - 1) for n in range(1, 7)}


def _domino(a: int, b: int) -> str:
    return chr(0x1F031 + 7 * a + b)


def _put(board: Board, r: int, c: int, glyph: str, letter: str, value: int, **extra) -> None:
    raw = {"glyph": glyph, "letter": letter, "value": value, "type": "Normal"}
    raw.update(extra)
    board.tiles[r][c].metadata["game_tile"] = raw


def _plan(board: Board, loadout: Loadout | None = None) -> EnginePlan:
    return EnginePlan.build(board, loadout or Loadout())


def score(board: Board, path, loadout: Loadout | None = None) -> int:
    return _plan(board, loadout).score(list(path), "").int_score


def test_dlc_board_uses_reference_scorer() -> None:
    b = _board(ROWS)
    _put(b, 0, 0, "Dice", DIE[3], 3)
    assert _plan(b).dlc_ref


def test_watermelon_adds_pips_and_die_faces() -> None:
    b = _board(ROWS)
    _put(b, 0, 0, "Dice", DIE[4], 4)
    _put(b, 0, 1, "Domino", _domino(2, 3), 5)
    base = score(b, [0, 1, 2])
    assert score(b, [0, 1, 2], _loadout(["watermelon_slice"])) == base + (4 + 5) * var("watermelon_slice")


def test_taxi_needs_three_dominoes() -> None:
    b = _board(ROWS)
    for c in range(3):
        _put(b, 0, c, "Domino", _domino(1, c + 1), c + 2)
    base = score(b, [0, 1, 2])
    assert score(b, [0, 1, 2], _loadout(["taxi"])) == _word_mult(base, var("taxi"))
    assert score(b, [0, 1], _loadout(["taxi"])) == score(b, [0, 1])


def test_sunrise_scales_with_zodiac_position() -> None:
    b = _board(ROWS)
    _put(b, 0, 0, "Zodiac", ZODIAC_ORDER[4], 1)  # Leo: position 5
    base = score(b, [0, 1, 2])
    assert score(b, [0, 1, 2], _loadout(["sunrise"])) == base + 5 * var("sunrise")


def test_saw_needs_a_connected_wire() -> None:
    b = _board(["cxc", "xxx", "xxx"])
    _put(b, 0, 1, "Wire", "║", 2)
    base = score(b, [0, 1, 2])
    assert score(b, [0, 1, 2], _loadout(["saw"])) == base + 2 * (var("saw") - 1)
    b2 = _board(["cxa", "xxx", "xxx"])
    _put(b2, 0, 1, "Wire", "║", 2)
    assert score(b2, [0, 1, 2], _loadout(["saw"])) == score(b2, [0, 1, 2])


def test_taco_multiplies_tiles_inside_brackets() -> None:
    b = _board(ROWS)
    _put(b, 0, 0, "Bracket", "(", 0)
    _put(b, 0, 2, "Bracket", ")", 0)
    base = score(b, [0, 1, 2])
    a_value = 1  # "a" sits inside the brackets
    assert score(b, [0, 1, 2], _loadout(["taco"])) == base + a_value * (var("taco") - 1)


def test_betting_slip_uses_expected_roll_and_sampling() -> None:
    b = _board(ROWS)
    _put(b, 0, 0, "Dice", DIE[5], 5)
    load = _loadout(["betting_slip"])
    plan = _plan(b, load)
    base = score(b, [0, 1, 2])
    res = plan.score([0, 1, 2], "")
    assert res.nondeterministic
    # P(d20 <= 5) = 1/4: expected multiplier 100 + (V - 100) / 4 percent.
    expected = base * (100 + (var("betting_slip") - 100) * 0.25) / 100
    assert abs(float(res.score) - expected) <= 1


def test_wire_connection_through_power_of_friendship_colours() -> None:
    from cursed_words_solver.engine.dlc_items import wire_connected
    from cursed_words_solver.engine.state import Ctx

    b = _board(["cxa", "xxx", "xxx"])
    _put(b, 0, 0, "Letter", "c", 3, type="Red")
    _put(b, 0, 1, "Wire", "╚", 2)
    _put(b, 0, 2, "Letter", "a", 2, type="Red")
    plan = _plan(b)
    tiles = [plan.grid.tiles[i] for i in (0, 1, 2)]
    ctx = Ctx(plan.grid, tiles, [], [], 1, [], [], [], None, [], False, False, 0, "")
    assert not wire_connected(ctx, tiles)
    ctx.unpacked = [type("I", (), {"cls": "PowerOfFriendship"})()]
    assert wire_connected(ctx, tiles)


def test_rng_samples_dice_rolls() -> None:
    b = _board(ROWS)
    _put(b, 0, 0, "Dice", DIE[3], 3)
    plan = _plan(b, _loadout(["cricket_bat"]))
    base = score(b, [0, 1, 2])
    seen = set()
    for seed in range(40):
        plan.rng = random.Random(seed)
        seen.add(plan.score([0, 1, 2], "").int_score)
    plan.rng = None
    assert seen == {base, base + var("cricket_bat")}


def test_gloves_counts_hyper_curse_tiles_on_grid() -> None:
    b = _board(ROWS)
    _put(b, 1, 0, "HyperCurse", "#", 0)
    _put(b, 1, 1, "HyperCurse", "#", 0)
    base = score(b, [0, 1, 2])
    gloves = _state("gloves", Count=3)
    assert score(b, [0, 1, 2], _loadout([gloves])) == _word_mult(base, 100 + 5)
