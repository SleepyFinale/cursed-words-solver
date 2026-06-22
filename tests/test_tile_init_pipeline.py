"""Pre-item tile scoring: glitch, currency, pink, poison."""

from __future__ import annotations

from cursed_words_solver.models import Board, CurseType, Loadout, LoadoutItem, Tile, TileColor
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.tile_scoring import (
    apply_tile_init,
    currency_money_from_path,
    initial_tile_scores,
    path_needs_scoring_board_copy,
    pink_store_money,
    settle_glitch_tiles,
)


def _board_with(*specs: tuple[int, TileColor, CurseType]) -> Board:
    tiles = [
        [
            Tile(r, c, "A", "A", 1, TileColor.COLORLESS, CurseType.LETTER)
            for c in range(5)
        ]
        for r in range(5)
    ]
    for idx, color, curse in specs:
        r, c = divmod(idx, 5)
        tiles[r][c] = Tile(r, c, "A", "A", 1, color, curse)
    return Board(tiles=tiles, money=5)


def test_path_needs_scoring_board_copy_only_for_glitch() -> None:
    plain = _board_with((0, TileColor.COLORLESS, CurseType.LETTER))
    assert not path_needs_scoring_board_copy(plain, [0])
    glitch = _board_with((0, TileColor.GLITCH, CurseType.LETTER))
    assert path_needs_scoring_board_copy(glitch, [0])


def test_glitch_settle_deterministic() -> None:
    board = _board_with((0, TileColor.GLITCH, CurseType.LETTER))
    path = [0]
    loadout = Loadout(extras={"run_seed": "test"})
    a = settle_glitch_tiles(board, path, loadout)
    color_a = board.get_by_index(0).color
    board2 = _board_with((0, TileColor.GLITCH, CurseType.LETTER))
    settle_glitch_tiles(board2, path, loadout)
    assert a == [0]
    assert board2.get_by_index(0).color == color_a
    assert board2.get_by_index(0).color != TileColor.GLITCH


def test_currency_adds_money() -> None:
    board = _board_with((0, TileColor.COLORLESS, CurseType.CURRENCY))
    assert currency_money_from_path(board, [0]) == 1


def test_initial_tile_scores_void_cedilla_grid1_not_zero() -> None:
    """narcissist: grid-1 void currency on path uses melmod init (not ITEM skip)."""
    board = _board_with()
    r, c = divmod(17, 5)
    board.tiles[r][c] = Tile(
        r,
        c,
        "₡",
        "₡",
        0,
        TileColor.VOID,
        CurseType.CURRENCY,
        metadata={"source": "melmod"},
    )
    loadout = Loadout(extras={"grid_number": "1"})
    scores, _ = initial_tile_scores(
        board, [0, 1, 2, 17], money=0, loadout=loadout, word="aaaa"
    )
    assert scores[3] == 0.0


def test_pink_spends_money() -> None:
    board = _board_with(
        (0, TileColor.PINK, CurseType.LETTER),
        (1, TileColor.PINK, CurseType.LETTER),
    )
    loadout = Loadout(money=3)
    saved = pink_store_money(board, [0, 1], loadout)
    assert saved == 2
    assert loadout.extras.get("pink_saved_this_word") == "2"


def test_tile_init_trace_phases() -> None:
    board = _board_with((0, TileColor.GLITCH, CurseType.LETTER))
    loadout = Loadout(money=10, extras={"run_seed": "x"})
    state = {
        "word": "A",
        "path": [0],
        "base_score": 0,
        "tile_scores": [0],
        "word_score": 0,
        "multiplier": 1.0,
        "money_bonus": 0,
        "effects": [],
        "pending_word_multipliers": [],
    }
    trace: list[dict] = []

    def _trace(st, phase, **kw):
        trace.append({"phase": phase, **kw})

    apply_tile_init(board, [0], "A", loadout, state, trace_step=_trace)
    phases = [t.get("phase_detail") or t.get("phase") for t in trace]
    assert "glitch_settle" in phases or "init_scores" in phases


def test_poison_applied_post_multiply() -> None:
    board = _board_with((0, TileColor.COLORLESS, CurseType.WILDCARD))
    loadout = Loadout(
        stamps=[LoadoutItem(id="oden", name="Oden", kind="stamp")],
        extras={
            "historic_words": '[{"word":"gree","score":10,"green_tile_count":1}]',
            "encounter_score_earned": "10",
        },
    )
    pipe = ScoringPipeline()
    final, _, tr = pipe.score_with_trace(board, [0], "A", loadout)
    assert final == 2.0  # 1 tile + 1 poison after ×1 oden
    assert any(s.get("phase") == "poison" for s in tr)
    assert not any(s.get("phase_detail") == "poison" for s in tr)


def test_poison_from_extras_fallback() -> None:
    """Deprecated green_poison_bonus extra still works for old fixtures."""
    board = _board_with((0, TileColor.COLORLESS, CurseType.LETTER))
    loadout = Loadout(extras={"green_poison_bonus": "12.5"})
    pipe = ScoringPipeline()
    final, _, tr = pipe.score_with_trace(board, [0], "A", loadout)
    assert final == 13.5
    assert any(s.get("phase") == "poison" for s in tr)
