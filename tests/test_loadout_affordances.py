"""LoadoutAffordances compilation and side-slice budgets."""

from cursed_words_solver.board_scoring_context import build_board_scoring_context
from cursed_words_solver.board_value_model import build_board_value_model
from cursed_words_solver.graph_bitboard import build_board_graph_context
from cursed_words_solver.loadout_affordances import build_loadout_affordances
from cursed_words_solver.models import (
    Board,
    CurseType,
    Loadout,
    LoadoutItem,
    Tile,
    TileColor,
)
from cursed_words_solver.rules.boss_effects import load_rules_catalog
from cursed_words_solver.solve_context import build_solve_context


def _board_with_number_and_item() -> Board:
    tiles = []
    for r in range(5):
        row = []
        for c in range(5):
            row.append(
                Tile(
                    row=r,
                    col=c,
                    char="a",
                    letter="A",
                    base_score=1,
                    color=TileColor.COLORLESS,
                    curse=CurseType.LETTER,
                )
            )
        tiles.append(row)
    tiles[0][0] = Tile(
        0, 0, "1", "1", 1, TileColor.COLORLESS, CurseType.NUMBER, number_value=1
    )
    tiles[0][1] = Tile(
        0, 1, "👻", "?", 0, TileColor.COLORLESS, CurseType.ITEM
    )
    tiles[0][2] = Tile(
        0, 2, "👻", "?", 0, TileColor.COLORLESS, CurseType.ITEM
    )
    return Board(tiles=tiles)


def test_affordances_detect_digit_item_and_wrestlers() -> None:
    board = _board_with_number_and_item()
    rules = load_rules_catalog()
    loadout = Loadout(
        stickers=[LoadoutItem(id="wrestlers", name="Wrestlers", kind="sticker")],
        stamps=[LoadoutItem(id="banana", name="Banana", kind="stamp")],
    )
    solve_ctx = build_solve_context(loadout, rules)
    graph_ctx = build_board_graph_context(board)
    aff = build_loadout_affordances(
        board, loadout, solve_ctx, graph_ctx, rules=rules
    )
    assert aff.needs_digit_start
    assert aff.needs_item_cover
    assert aff.needs_suit_diverse_ends
    assert aff.rewards_high_letter_count
    assert "needs_digit_start" in aff.tags
    n, cover, i, c = aff.side_slice_budgets(20.0)
    assert n > 0 and i > 0
    assert cover == 0.0  # no Lab Coat / Abacus on this loadout


def test_affordances_detect_lab_coat_number_tiles() -> None:
    board = _board_with_number_and_item()
    # Need ≥3 numbers for number_cover_slice scheduling.
    tiles = [list(row) for row in board.tiles]
    tiles[1][0] = Tile(
        1, 0, "2", "2", 2, TileColor.BLUE, CurseType.NUMBER, number_value=2
    )
    tiles[1][1] = Tile(
        1, 1, "3", "3", 3, TileColor.BLUE, CurseType.NUMBER, number_value=3
    )
    board = Board(tiles=tiles)
    rules = load_rules_catalog()
    loadout = Loadout(
        stickers=[LoadoutItem(id="lab_coat", name="Lab Coat", level=1, kind="sticker")],
        stamps=[
            LoadoutItem(id="number_go_up", name="Number Go Up", level=1, kind="stamp")
        ],
        extras={"pin_effect": "abacus"},
    )
    solve_ctx = build_solve_context(loadout, rules)
    graph_ctx = build_board_graph_context(board)
    aff = build_loadout_affordances(
        board, loadout, solve_ctx, graph_ctx, rules=rules
    )
    assert aff.rewards_number_tiles
    assert aff.rewards_all_number_tiles
    assert "rewards_number_tiles" in aff.tags
    digit, cover, _item, _chess = aff.side_slice_budgets(40.0)
    assert digit > 0
    assert cover > 0
    scoring = build_board_scoring_context(
        board, loadout, solve_ctx, graph_ctx, rules
    )
    model = build_board_value_model(
        board,
        loadout,
        solve_ctx,
        graph_ctx,
        scoring,
        affordances=aff,
    )
    # Blue numbers soft-covered for beam guidance.
    assert model.soft_cover_mask & model.number_mask
    blue_idx = board.index_at(1, 0)
    assert model.is_soft_cover(blue_idx)


def test_value_model_reads_affordances() -> None:
    board = _board_with_number_and_item()
    rules = load_rules_catalog()
    loadout = Loadout(
        stickers=[LoadoutItem(id="wrestlers", name="Wrestlers", kind="sticker")]
    )
    solve_ctx = build_solve_context(loadout, rules)
    graph_ctx = build_board_graph_context(board)
    scoring = build_board_scoring_context(
        board, loadout, solve_ctx, graph_ctx, rules
    )
    aff = build_loadout_affordances(
        board, loadout, solve_ctx, graph_ctx, rules=rules
    )
    model = build_board_value_model(
        board,
        loadout,
        solve_ctx,
        graph_ctx,
        scoring,
        affordances=aff,
    )
    assert model.needs_suit_diverse_ends
    assert model.soft_must_include
