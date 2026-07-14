"""Path rank model and finite item upper bounds."""

from cursed_words_solver.fast_rank import (
    path_has_scattered_grid_items,
    tier2_immediate_upper_bound,
)
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
from cursed_words_solver.mult_search import loadout_mult_rules
from cursed_words_solver.path_rank_model import (
    approximate_path_rank,
    extract_path_features,
)
from cursed_words_solver.rules.boss_effects import load_rules_catalog
from cursed_words_solver.solve_context import build_solve_context


def _board() -> Board:
    tiles = [
        [
            Tile(r, c, "a", "A", 2, TileColor.COLORLESS, CurseType.LETTER)
            for c in range(5)
        ]
        for r in range(5)
    ]
    tiles[0][0] = Tile(0, 0, "👻", "?", 0, TileColor.COLORLESS, CurseType.ITEM)
    tiles[0][1] = Tile(0, 1, "👻", "?", 0, TileColor.COLORLESS, CurseType.ITEM)
    return Board(tiles=tiles)


def test_item_upper_bound_is_finite() -> None:
    board = _board()
    path = [0, 1, 2]
    assert path_has_scattered_grid_items(board, path)
    rules = load_rules_catalog()
    loadout = Loadout(
        stamps=[LoadoutItem(id="banana", name="Banana", kind="stamp")]
    )
    ctx = build_solve_context(loadout, rules)
    graph = build_board_graph_context(board)
    mult = loadout_mult_rules(loadout, rules, board=board, path=path, solve_context=ctx)
    ub = tier2_immediate_upper_bound(
        board, path, "xxx", loadout, ctx, mult, graph_ctx=graph
    )
    assert ub < 1e12
    assert ub > 0


def test_path_rank_prefers_longer_cover() -> None:
    board = _board()
    rules = load_rules_catalog()
    loadout = Loadout()
    ctx = build_solve_context(loadout, rules)
    graph = build_board_graph_context(board)
    aff = build_loadout_affordances(board, loadout, ctx, graph, rules=rules)
    short = approximate_path_rank(board, [2, 3], graph, aff)
    long = approximate_path_rank(board, [0, 1, 2, 3, 4, 5], graph, aff)
    assert long >= short
    feats = extract_path_features(board, [0, 1, 2], graph, aff)
    assert feats.item_frac > 0
