"""Tests for game-accurate scoring order helpers."""

from cursed_words_solver.models import Board, CurseType, Loadout, LoadoutItem, Tile, TileColor
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.scoring_order import (
    build_scoring_item_sequence,
    hourglass_reverses_order,
)


def _tile(row: int, col: int, ch: str, score: int, **kwargs) -> Tile:
    return Tile(row=row, col=col, char=ch, letter=ch, base_score=score, **kwargs)


def test_hourglass_reverses_inventory_order():
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[LoadoutItem(id="a", name="A", level=1)],
        stamps=[LoadoutItem(id="hourglass", name="Hourglass", kind="stamp")],
        extras={"hourglass_count": "1"},
    )
    assert hourglass_reverses_order(loadout, pipeline.rules)
    loadout2 = Loadout(
        stickers=[
            LoadoutItem(id="brain", name="Brain", level=1),
            LoadoutItem(id="chips", name="Chips", level=1),
        ],
        extras={"hourglass_count": "1"},
    )
    board = Board(tiles=[[_tile(0, c, "A", 1) for c in range(5)]] * 5)
    seq = build_scoring_item_sequence(board, [0], loadout2, pipeline.rules)
    assert [r.rule_id for r in seq if r.kind == "sticker"] == ["chips", "brain"]


def _green_colorless_board() -> Board:
    return Board(
        tiles=[
            [
                _tile(0, 0, "A", 3, color=TileColor.GREEN),
                _tile(0, 1, "B", 1, color=TileColor.COLORLESS),
            ]
            + [_tile(0, c, "T", 1) for c in range(2, 5)]
        ]
        + [[_tile(r, c, "T", 1) for c in range(5)] for r in range(1, 5)]
    )


def test_green_tile_transfers_to_word_score():
    board = Board(
        tiles=[
            [
                _tile(0, 0, "A", 3, color=TileColor.GREEN),
                _tile(0, 1, "B", 2, color=TileColor.RED),
            ]
            + [_tile(0, c, "T", 1) for c in range(2, 5)]
        ]
        + [[_tile(r, c, "T", 1) for c in range(5)] for r in range(1, 5)]
    )
    pipeline = ScoringPipeline()
    score, bd = pipeline.score(board, [0, 1], "ab", Loadout())
    p = bd["pipeline"]
    assert score == p["word_score"] + sum(p["tile_scores"])
    assert p["tile_scores"][0] == 0.0
    assert p["word_score"] == 3.0


def test_green_tile_gets_word_multiplier():
    board = _green_colorless_board()
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[LoadoutItem(id="bone", name="Bone", level=2, kind="sticker")]
    )
    score, bd = pipeline.score(board, [0, 1], "ab", loadout)
    assert score == 8
    assert bd["multiplier"] == 2.0


def test_green_transfer_before_finalize_mult():
    board = _green_colorless_board()
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[LoadoutItem(id="bone", name="Bone", level=2, kind="sticker")]
    )
    state = pipeline._compute_state(board, [0, 1], "ab", loadout)
    assert state["tile_scores"][0] == 0.0
    assert state["word_score"] == 3.0
    assert state["_green_transferred"] is True


def test_green_word_mult_with_additive_after():
    board = _green_colorless_board()
    board.money = 5
    pipeline = ScoringPipeline()
    loadout = Loadout(
        money=5,
        stickers=[
            LoadoutItem(id="bone", name="Bone", level=2, kind="sticker"),
            LoadoutItem(id="credit_card", name="Credit Card", level=1, kind="sticker"),
        ],
    )
    score, _bd = pipeline.score(board, [0, 1], "ab", loadout)
    assert score == 28


def test_score_with_trace_matches_score_for_green_word_mult():
    board = _green_colorless_board()
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[LoadoutItem(id="bone", name="Bone", level=2, kind="sticker")]
    )
    score, _bd = pipeline.score(board, [0, 1], "ab", loadout)
    trace_score, _bd2, trace = pipeline.score_with_trace(board, [0, 1], "ab", loadout)
    assert trace_score == score
    assert any(step.get("phase") == "green_transfer" for step in trace)


def test_hourglass_reverses_stacked_boss_order():
    pipeline = ScoringPipeline()
    board = Board(tiles=[[_tile(0, c, "A", 2) for c in range(5)]] * 5, money=10)
    path = list(range(5))
    extras = {
        "boss_modifiers": ["salamander", "robo_monkey"],
        "boss_modifier_floor_mods": '{"salamander": 9, "robo_monkey": 5}',
        "boss_area_number": 2,
        "run_seed": "t",
    }
    lo_normal = Loadout(boss_id="salamander", money=10, extras=extras)
    _, _, trace_normal = pipeline.score_with_trace(board, path, "aaaaa", lo_normal)
    boss_ids_normal = [
        step["rule_id"]
        for step in trace_normal
        if step.get("phase") == "boss_early"
    ]
    assert boss_ids_normal == ["salamander", "robo_monkey"]

    lo_hourglass = Loadout(
        boss_id="salamander",
        money=10,
        stamps=[LoadoutItem(id="hourglass", name="Hourglass", kind="stamp")],
        extras={**extras, "hourglass_count": "1"},
    )
    _, _, trace_hourglass = pipeline.score_with_trace(
        board, path, "aaaaa", lo_hourglass
    )
    boss_ids_hourglass = [
        step["rule_id"]
        for step in trace_hourglass
        if step.get("phase") == "boss_late"
    ]
    assert boss_ids_hourglass == ["robo_monkey", "salamander"]


def test_frankenstein_stitch_expands_in_sequence():
    pipeline = ScoringPipeline()
    board = Board(tiles=[[_tile(0, c, "A", 1) for c in range(5)]] * 5)
    grid = board.tiles
    grid[0][0] = _tile(0, 0, "4", 4, curse=CurseType.NUMBER, number_value=4)
    grid[0][1] = _tile(0, 1, "5", 5, curse=CurseType.NUMBER, number_value=5)
    grid[0][2] = _tile(0, 2, "6", 6, curse=CurseType.NUMBER, number_value=6)
    lo = Loadout(
        stickers=[LoadoutItem(id="frankenstein", name="Frankenstein", level=1)],
        extras={"stitched_sticker_ids": ["brain"]},
    )
    score, _ = pipeline.score(board, [0, 1, 2], "456", lo)
    assert score > 15.0
