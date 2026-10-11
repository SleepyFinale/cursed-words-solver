"""Nat-H4 unlock sticker scoring."""

from cursed_words_solver.models import Board, Loadout, LoadoutItem, Tile, TileColor
from cursed_words_solver.engine.scorer import EngineScorer
from cursed_words_solver.rules.rule_lookup import get_rule, slugify_name

NAT_H4_STICKER_NAMES = [
    "Burrito",
    "Printer",
    "Retro Raider",
    "Signal Receiver",
    "Stamp Album",
    "Toolbox",
]

GRID_ONLY_SLUGS = {
    "printer",
    "retro_raider",
    "toolbox",
    "signal_receiver",
}


def _tile(row: int, col: int, ch: str, score: int) -> Tile:
    return Tile(
        row=row,
        col=col,
        char=ch,
        letter=ch,
        base_score=score,
        color=TileColor.COLORLESS,
        metadata={"source": "melmod"},
    )


def _empty_board() -> Board:
    grid = [[_tile(r, c, "X", 1) for c in range(5)] for r in range(5)]
    return Board(tiles=grid, money=0)


def test_all_nat_h4_stickers_catalogued():
    pipeline = EngineScorer()
    for name in NAT_H4_STICKER_NAMES:
        slug = slugify_name(name)
        _key, rule = get_rule(pipeline.rules, "stickers", slug, name)
        assert rule is not None, slug
        assert rule.get("type") != "unmodeled", slug


def test_grid_and_sell_stickers_catalog():
    pipeline = EngineScorer()
    for slug in ("printer", "retro_raider", "toolbox"):
        _key, rule = get_rule(pipeline.rules, "stickers", slug, slug)
        assert rule.get("effect_class") == "scatter"
    _key, rule = get_rule(pipeline.rules, "stickers", "signal_receiver", "Signal Receiver")
    assert rule.get("effect_class") == "sell"


def test_burrito_alone_no_multiplier():
    board = _empty_board()
    pipeline = EngineScorer()
    loadout = Loadout(stickers=[LoadoutItem(id="burrito", name="Burrito", level=1)])
    score, bd = pipeline.score(board, [0], "x", loadout)
    base, base_bd = pipeline.score(board, [0], "x", Loadout())
    assert bd["multiplier"] == 1.0
    assert score == base


def test_burrito_with_other_stickers():
    board = _empty_board()
    pipeline = EngineScorer()
    loadout = Loadout(
        stickers=[
            LoadoutItem(id="burrito", name="Burrito", level=1),
            LoadoutItem(id="printer", name="Printer", level=1),
            LoadoutItem(id="toolbox", name="Toolbox", level=1),
        ]
    )
    score, bd = pipeline.score(board, [0], "x", loadout)
    base, _ = pipeline.score(board, [0], "x", Loadout())
    assert bd["multiplier"] == 1.1
    assert score == int(base * 1.1)  # floor after ×WORD


def test_burrito_level2_rate():
    board = _empty_board()
    pipeline = EngineScorer()
    loadout = Loadout(
        stickers=[
            LoadoutItem(id="burrito", name="Burrito", level=2),
            LoadoutItem(id="stamp_album", name="Stamp Album", level=2),
        ]
    )
    score, bd = pipeline.score(board, [0], "x", loadout)
    base, _ = pipeline.score(board, [0], "x", Loadout())
    assert bd["multiplier"] == 1.2
    assert score == int(base * 1.2)  # floor after ×WORD


def test_stamp_album_no_stamps_no_extras():
    board = _empty_board()
    pipeline = EngineScorer()
    loadout = Loadout(stickers=[LoadoutItem(id="stamp_album", name="Stamp Album", level=1)])
    score, bd = pipeline.score(board, [0], "x", loadout)
    base, _ = pipeline.score(board, [0], "x", Loadout())
    assert score == base
    assert bd["multiplier"] == 1.0


def test_attend_grid_tombstone_retro_raider_replay_score_151():
    """20260709 attend: +80 void-adjacent at L2, ×1.5 YG → 151."""
    import json

    from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
    from tests.helpers.replay import (
        FIXTURES,
        _replay_path,
        _run_state_for_replay,
    )

    data = json.loads((FIXTURES / "20260709_144945.json").read_text(encoding="utf-8"))
    run_state = _run_state_for_replay(data)
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    path = _replay_path(board, data["path"])
    score, _ = EngineScorer().score(board, path, data["word"], loadout)
    assert int(score) == int(data["actual_score"]) == 151
