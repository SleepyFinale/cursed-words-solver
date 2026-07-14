"""Tests for per-solve BoardValueModel (no cross-solve cache)."""

from __future__ import annotations

from cursed_words_solver.board_scoring_context import build_board_scoring_context
from cursed_words_solver.board_value_model import build_board_value_model
from cursed_words_solver.graph_bitboard import build_board_graph_context
from cursed_words_solver.models import (
    Board,
    CurseType,
    Loadout,
    LoadoutItem,
    Tile,
    TileColor,
)
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.solve_context import build_solve_context


def _letter_board(chars: str, *, rows: int = 5, cols: int = 5) -> Board:
    tiles: list[list[Tile]] = []
    for r in range(rows):
        row: list[Tile] = []
        for c in range(cols):
            i = r * cols + c
            ch = chars[i % len(chars)]
            row.append(
                Tile(
                    row=r,
                    col=c,
                    char=ch,
                    letter=ch.lower(),
                    base_score=float(1 + (i % 5)),
                    color=TileColor.COLORLESS,
                    curse=CurseType.LETTER,
                )
            )
        tiles.append(row)
    return Board(tiles=tiles, money=0, rows=rows, cols=cols)


def test_value_model_rebuilds_from_live_contexts_only() -> None:
    board = _letter_board("ABCDEFGHIJKLMNOPQRSTUVWXY")
    # Mark a white teleport hub and a wildcard
    board.tiles[0][0] = Tile(
        row=0,
        col=0,
        char="?",
        letter="?",
        base_score=0.0,
        color=TileColor.WHITE,
        curse=CurseType.WILDCARD,
    )
    board.tiles[2][2] = Tile(
        row=2,
        col=2,
        char="A",
        letter="a",
        base_score=50.0,
        color=TileColor.SHINY,
        curse=CurseType.LETTER,
    )
    loadout = Loadout(money=0)
    rules = ScoringPipeline().rules
    solve_ctx = build_solve_context(loadout, rules)
    graph = build_board_graph_context(board)
    scoring_ctx = build_board_scoring_context(
        board, loadout, solve_ctx, graph, rules
    )
    model_a = build_board_value_model(
        board, loadout, solve_ctx, graph, scoring_ctx
    )
    model_b = build_board_value_model(
        board, loadout, solve_ctx, graph, scoring_ctx
    )
    assert model_a.cell_potential == model_b.cell_potential
    assert model_a.hub_mask & (1 << 0)
    assert model_a.cell_score(2 * 5 + 2) > model_a.cell_score(1)


def test_value_model_marks_required_consumable_as_must_include() -> None:
    board = _letter_board("ABCDEFGHIJKLMNOPQRSTUVWXY")
    loadout = Loadout(money=0)
    rules = ScoringPipeline().rules
    solve_ctx = build_solve_context(loadout, rules)
    graph = build_board_graph_context(board)
    scoring_ctx = build_board_scoring_context(
        board, loadout, solve_ctx, graph, rules
    )
    model = build_board_value_model(
        board,
        loadout,
        solve_ctx,
        graph,
        scoring_ctx,
        required_consumable_indices=frozenset({7}),
    )
    assert model.is_must_include(7)
    assert model.missing_must_include(0) == 1
    assert model.missing_must_include(1 << 7) == 0


def test_value_model_soft_covers_scattered_items() -> None:
    board = _letter_board("ABCDEFGHIJKLMNOPQRSTUVWXY")
    board.tiles[1][1] = Tile(
        row=1,
        col=1,
        char="*",
        letter="*",
        base_score=0.0,
        color=TileColor.COLORLESS,
        curse=CurseType.ITEM,
        metadata={"scattered_item_id": "tombstone"},
    )
    loadout = Loadout(
        money=0,
        stickers=[LoadoutItem(id="tombstone", name="Tombstone", level=1)],
    )
    rules = ScoringPipeline().rules
    solve_ctx = build_solve_context(loadout, rules)
    graph = build_board_graph_context(board)
    scoring_ctx = build_board_scoring_context(
        board, loadout, solve_ctx, graph, rules
    )
    model = build_board_value_model(
        board, loadout, solve_ctx, graph, scoring_ctx
    )
    assert model.is_soft_cover(1 * 5 + 1)
    assert model.item_count >= 1
    starts = model.ordered_starts(list(range(25)))
    assert starts[0] == 1 * 5 + 1 or model.start_priority(1 * 5 + 1) >= model.start_priority(
        starts[0]
    )


def test_value_model_number_start_priority_not_starved() -> None:
    """NUMBER tiles keep competitive start_priority despite branch_cost."""
    board = _letter_board("ABCDEFGHIJKLMNOPQRSTUVWXY")
    board.tiles[0][0] = Tile(
        row=0,
        col=0,
        char="1",
        letter="1",
        base_score=2.0,
        color=TileColor.BLUE,
        curse=CurseType.NUMBER,
        number_value=1,
    )
    board.tiles[0][1] = Tile(
        row=0,
        col=1,
        char="a",
        letter="a",
        base_score=2.0,
        color=TileColor.COLORLESS,
        curse=CurseType.LETTER,
    )
    loadout = Loadout(money=0)
    rules = ScoringPipeline().rules
    solve_ctx = build_solve_context(loadout, rules)
    graph = build_board_graph_context(board)
    scoring_ctx = build_board_scoring_context(
        board, loadout, solve_ctx, graph, rules
    )
    model = build_board_value_model(
        board, loadout, solve_ctx, graph, scoring_ctx
    )
    assert model.is_number(0)
    assert model.branch_penalty(0) > 0
    # Softened start penalty: low-face number should not rank far below equal-base letter
    assert model.start_priority(0) >= model.start_priority(1) - 2.0
