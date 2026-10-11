"""Engine item rules with no real-game capture yet (one test per item).

Every other scoring item is pinned by real captures the engine reproduces
exactly (tests/engine/test_engine_captures.py, test_capture_fixtures.py).
These are checked against the decompiled ``ApplyTileBonus`` /
``ApplyWordBonus``; expected values use the item's default component value.
"""

from __future__ import annotations

import json

from cursed_words_solver.engine import EnginePlan
from cursed_words_solver.engine.item_data import ITEMS
from cursed_words_solver.models import Board, CurseType, Loadout, Tile, TileColor

from tests.engine.test_engine_units import _board


def var(slug: str, i: int = 0) -> int:
    return ITEMS[slug].components[i][2]


def _state(slug: str, **fields) -> dict:
    info = ITEMS[slug]
    return {"id": slug, "levels": [c[0] for c in info.components], "values": [c[2] for c in info.components], "fields": fields}


def _loadout(stickers=(), stamps=(), pin=None, extras=None, **kw) -> Loadout:
    """Exact item slots (5 + 5, ``None`` = empty) like melmod's item_states."""
    def slots(entries):
        out = [(_state(e) if isinstance(e, str) else e) for e in entries]
        return out + [None] * (5 - len(out))

    states = {"stickers": slots(stickers), "stamps": slots(stamps)}
    if pin is not None:
        states["pin"] = pin
    ex = {"item_states": json.dumps(states)}
    ex.update(extras or {})
    return Loadout(extras=ex, **kw)


def score(board: Board, path, loadout: Loadout | None = None, word: str = "") -> int:
    return EnginePlan.build(board, loadout or Loadout()).score(list(path), word).int_score


ROWS = ["catdo", "xxxxx", "xxxxx", "xxxxx", "xxxxx"]


def _word_mult(base: int, percent: int) -> int:
    return base * percent // 100


# ---------------------------------------------------------------- word multipliers


def test_axe_multiplies_words_of_three_tiles_or_fewer() -> None:
    b = _board(ROWS)
    assert score(b, [0, 1, 2], _loadout(["axe"])) == _word_mult(score(b, [0, 1, 2]), var("axe"))
    assert score(b, [0, 1, 2, 3], _loadout(["axe"])) == score(b, [0, 1, 2, 3])


def test_wriggly_worm_needs_ten_tiles() -> None:
    b = _board(["abcde", "fghij", "xxxxx", "xxxxx", "xxxxx"])
    ten = [0, 1, 2, 3, 4, 9, 8, 7, 6, 5]
    assert score(b, ten, _loadout(["wriggly_worm"])) == _word_mult(score(b, ten), var("wriggly_worm"))
    assert score(b, ten[:9], _loadout(["wriggly_worm"])) == score(b, ten[:9])


def test_erupting_volcano_is_always_x1_5() -> None:
    b = _board(ROWS)
    assert score(b, [0, 1], _loadout(["erupting_volcano"])) == _word_mult(score(b, [0, 1]), 150)


def test_arrivals_only_from_first_sticker_slot() -> None:
    b = _board(ROWS)
    base = score(b, [0, 1, 2])
    assert score(b, [0, 1, 2], _loadout(["arrivals"])) == _word_mult(base, var("arrivals"))
    assert score(b, [0, 1, 2], _loadout([None, "arrivals"])) == base


def test_departures_only_from_fifth_sticker_slot() -> None:
    b = _board(ROWS)
    base = score(b, [0, 1, 2])
    assert score(b, [0, 1, 2], _loadout([None, None, None, None, "departures"])) == base + var("departures")
    assert score(b, [0, 1, 2], _loadout(["departures"])) == base


def test_chequered_flag_only_on_grid_one() -> None:
    b = _board(ROWS)
    base = score(b, [0, 1, 2])
    flag = var("chequered_flag") * 100
    assert score(b, [0, 1, 2], _loadout(["chequered_flag"], extras={"grid_number": "1"})) == _word_mult(base, flag)
    assert score(b, [0, 1, 2], _loadout(["chequered_flag"], extras={"grid_number": "2"})) == base


def test_baby_bottle_needs_exactly_two_blanks() -> None:
    b = _board(["??a?x", "xxxxx", "xxxxx", "xxxxx", "xxxxx"])
    assert score(b, [0, 1, 2], _loadout(["baby_bottle"])) == _word_mult(score(b, [0, 1, 2]), var("baby_bottle"))
    assert score(b, [0, 1, 2, 3], _loadout(["baby_bottle"])) == score(b, [0, 1, 2, 3])


def test_confetti_needs_five_non_normal_colours() -> None:
    colors = {(0, 0): TileColor.RED, (0, 1): TileColor.BLUE, (0, 2): TileColor.GOLD, (0, 3): TileColor.SHINY, (0, 4): TileColor.PINK}
    b = _board(["abcde", "xxxxx", "xxxxx", "xxxxx", "xxxxx"], colors)
    five = [0, 1, 2, 3, 4]
    assert score(b, five, _loadout(["confetti"])) == _word_mult(score(b, five), 100 * var("confetti"))
    assert score(b, five[:4], _loadout(["confetti"])) == score(b, five[:4])


def test_postbox_needs_no_cursed_tile() -> None:
    b = _board(["ab1xx", "xxxxx", "xxxxx", "xxxxx", "xxxxx"])
    assert score(b, [0, 1], _loadout(["postbox"])) == _word_mult(score(b, [0, 1]), 100 * var("postbox"))
    assert score(b, [0, 1, 2], _loadout(["postbox"])) == score(b, [0, 1, 2])  # number tiles are cursed


def test_ambulance_only_when_tile_values_sum_negative() -> None:
    b = _board(ROWS, {(0, 0): TileColor.VOID, (0, 1): TileColor.VOID})
    assert score(b, [0, 1], _loadout(["ambulance"])) == _word_mult(score(b, [0, 1]), var("ambulance"))
    plain = _board(ROWS)
    assert score(plain, [0, 1], _loadout(["ambulance"])) == score(plain, [0, 1])


def test_chick_counts_level_one_stickers() -> None:
    b = _board(ROWS)
    base = score(b, [0, 1, 2])
    two = _loadout(["axe", "jigsaw_piece"], stamps=["chick"])  # word-neutral on this path except Axe
    with_axe_only = score(b, [0, 1, 2], _loadout(["axe", "jigsaw_piece"]))
    assert score(b, [0, 1, 2], two) == _word_mult(with_axe_only, 100 + 2 * 20)
    assert base > 0


def test_silly_puppy_counts_other_animal_items() -> None:
    animals = [s for s, i in ITEMS.items() if i.animal and s != "silly_puppy" and len(i.components) == 1]
    b = _board(ROWS)
    base = score(b, [0, 1])
    assert score(b, [0, 1], _loadout(stamps=["silly_puppy"])) == base
    loadout = _loadout([animals[0]], stamps=["silly_puppy"])
    without_puppy = score(b, [0, 1], _loadout([animals[0]]))
    assert score(b, [0, 1], loadout) == _word_mult(without_puppy, 125)


def test_piggy_bank_coin_purse_uses_its_count() -> None:
    b = _board(ROWS)
    purse = _state("piggy_bank", Count=40)
    assert score(b, [0, 1, 2], _loadout([purse])) == _word_mult(score(b, [0, 1, 2]), 140)
    assert score(b, [0, 1, 2], _loadout(["piggy_bank"])) == score(b, [0, 1, 2])


def test_error_item_multiplies_by_glitch_tiles_used_plus_one() -> None:
    b = _board(ROWS)
    err = _state("error", NumberOfGlitchTilesUsed=2)
    assert score(b, [0, 1, 2], _loadout([err])) == _word_mult(score(b, [0, 1, 2]), 300)
    broken = _state("error", NumberOfGlitchTilesUsed=2, IsBroken=True)
    assert score(b, [0, 1, 2], _loadout([broken])) == score(b, [0, 1, 2])


# ---------------------------------------------------------------- additive word bonuses


def test_base_camp_adds_value_of_every_available_tile() -> None:
    b = _board(ROWS)
    grid_total = sum(t.value for t in EnginePlan.build(b, Loadout()).grid.available)
    assert score(b, [0, 1, 2], _loadout(["base_camp"])) == score(b, [0, 1, 2]) + var("base_camp") * grid_total


def test_jigsaw_piece_only_when_tile_scores_sum_to_zero() -> None:
    b = _board(["??xxx", "xxxxx", "xxxxx", "xxxxx", "xxxxx"])  # blanks are worth 0
    assert score(b, [0, 1], _loadout(["jigsaw_piece"])) == score(b, [0, 1]) + var("jigsaw_piece")
    plain = _board(ROWS)
    assert score(plain, [0, 1], _loadout(["jigsaw_piece"])) == score(plain, [0, 1])


def test_dartboard_hits_its_target_number() -> None:
    b = _board(ROWS)
    total = sum(t.value for t in EnginePlan.build(b, Loadout()).grid.tiles[:3])
    hit = _state("dartboard", _targetNumber=total)
    miss = _state("dartboard", _targetNumber=total + 1)
    assert score(b, [0, 1, 2], _loadout([hit])) == score(b, [0, 1, 2]) + var("dartboard")
    assert score(b, [0, 1, 2], _loadout([miss])) == score(b, [0, 1, 2])


def test_lollipop_adds_its_bonus_field() -> None:
    b = _board(ROWS)
    assert score(b, [0, 1], _loadout([_state("lollipop", Bonus=15)])) == score(b, [0, 1]) + 15


def test_stamp_album_adds_stamp_costs() -> None:
    b = _board(ROWS)
    cost = ITEMS["builder"].cost  # a stamp with no effect on this path
    album = _loadout(["stamp_album"], stamps=["builder"])
    assert score(b, [0, 1], album) == score(b, [0, 1]) + var("stamp_album") * cost


def test_crystal_ball_adds_when_path_has_chosen_curse() -> None:
    b = _board(["?bxxx", "xxxxx", "xxxxx", "xxxxx", "xxxxx"])
    ball = _state("crystal_ball", ChosenCurseType="Blank")
    assert score(b, [0, 1], _loadout([ball])) == score(b, [0, 1]) + var("crystal_ball")
    assert score(b, [1, 6], _loadout([ball])) == score(b, [1, 6])


# ---------------------------------------------------------------- tile bonuses


def test_numbers_giraffe_multiplies_numbers_by_position() -> None:
    b = _board(["123xx", "xxxxx", "xxxxx", "xxxxx", "xxxxx"])
    trace = EnginePlan.build(b, _loadout(["giraffe"])).score([0, 1, 2]).steps[-1].ts
    assert list(trace) == [1, 4, 9]


def test_builder_multiplies_placed_consumables_by_their_count() -> None:
    b = _board(ROWS)
    for c in (0, 1):
        b.tiles[0][c].metadata["was_consumable"] = True
    base_ts = EnginePlan.build(b, Loadout()).score([0, 1, 2]).steps[-1].ts
    ts = EnginePlan.build(b, _loadout(stamps=["builder"])).score([0, 1, 2]).steps[-1].ts
    assert list(ts) == [base_ts[0] * 2, base_ts[1] * 2, base_ts[2]]


def _chess(r: int, c: int, curse: CurseType, colour: str, value: float = 5.0) -> Tile:
    t = Tile(r, c, "?", "?", value, curse=curse, metadata={"source": "melmod", "chess_color": colour})
    return t


def test_eight_ball_adds_to_its_selected_piece() -> None:
    b = _board(ROWS)
    b.tiles[0][3] = _chess(0, 3, CurseType.CHESS_ROOK, "white")
    ball = _state("magic_8_ball", _selectedPiece="Rook")
    base_ts = EnginePlan.build(b, Loadout()).score([2, 3]).steps[-1].ts
    ts = EnginePlan.build(b, _loadout([ball])).score([2, 3]).steps[-1].ts
    assert list(ts) == [base_ts[0], base_ts[1] + var("magic_8_ball")]


def test_kangaroo_adds_rook_move_distance() -> None:
    b = _board(ROWS)
    b.tiles[2][0] = _chess(2, 0, CurseType.CHESS_ROOK, "white")
    plan = EnginePlan.build(b, _loadout(["kangaroo"]))
    # Rook at storage (2, 0) -> (0, 0): a two-square slide.
    ts = plan.score([10, 0]).steps[-1].ts
    base = EnginePlan.build(b, Loadout()).score([10, 0]).steps[-1].ts
    assert ts[0] == base[0] + 2 * var("kangaroo")


def test_dagger_rewards_taking_a_king() -> None:
    b = _board(ROWS)
    b.tiles[0][0] = _chess(0, 0, CurseType.CHESS_ROOK, "white")
    b.tiles[0][3] = _chess(0, 3, CurseType.CHESS_KING, "black")
    base = score(b, [0, 3])
    assert score(b, [0, 3], _loadout(["dagger"])) == base + var("dagger")


def test_pocket_money_pays_first_number_on_grid_one() -> None:
    b = _board(["a7x3x", "xxxxx", "xxxxx", "xxxxx", "xxxxx"])
    plan = EnginePlan.build(b, _loadout(["pocket_money"], extras={"grid_number": "1"}))
    assert plan.score([0, 1]).steps[-1].money - EnginePlan.build(b, Loadout()).score([0, 1]).steps[-1].money == 7


def test_wind_chime_needs_five_suited_tiles() -> None:
    b = _board(["abcde", "xxxxx", "xxxxx", "xxxxx", "xxxxx"])
    for c, suit in enumerate(("hearts", "spades", "clubs", "diamonds", "hearts")):
        b.tiles[0][c].metadata["card_suit"] = suit
    five = [0, 1, 2, 3, 4]
    assert score(b, five, _loadout(["wind_chime"])) == _word_mult(score(b, five), var("wind_chime") * 100)
    assert score(b, five[:4], _loadout(["wind_chime"])) == score(b, five[:4])
