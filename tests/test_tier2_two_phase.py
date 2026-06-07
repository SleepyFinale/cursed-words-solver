"""Tier-2 two-phase scoring and grid-refs cache."""

from __future__ import annotations

from cursed_words_solver.models import Board, CurseType, Loadout, LoadoutItem, Tile, TileColor
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.scoring_order import path_grid_item_refs
from cursed_words_solver.fast_rank import (
    tier2_immediate_lower_bound,
    tier2_immediate_upper_bound,
    tier2_rank_lower_bound,
)
from cursed_words_solver.solve_context import build_solve_context
from cursed_words_solver.mult_search import loadout_mult_rules
from tests.helpers.boards import _board_cat_horizontal


def _board_with_scattered_item() -> Board:
    board = _board_cat_horizontal()
    tile = board.get_by_index(12)
    board.tiles[tile.row][tile.col] = Tile(
        tile.row,
        tile.col,
        "?",
        "?",
        5.0,
        TileColor.COLORLESS,
        CurseType.ITEM,
        metadata={"scattered_item_id": "cocktail"},
    )
    return board


def test_path_grid_item_refs_cache_reuses_entry():
    board = _board_with_scattered_item()
    loadout = Loadout()
    rules = ScoringPipeline().rules
    path = [0, 1, 12]
    cache: dict = {}
    first = path_grid_item_refs(board, path, rules, loadout, cache=cache)
    second = path_grid_item_refs(board, path, rules, loadout, cache=cache)
    assert first == second
    assert len(cache) == 1
    assert cache[tuple(path)] is first


def test_tier2_bounds_bracket_full_score():
    board = _board_cat_horizontal()
    loadout = Loadout(
        stickers=[LoadoutItem(id="brain", name="Brain", level=1, kind="sticker")]
    )
    pipeline = ScoringPipeline()
    rules = pipeline.rules
    ctx = build_solve_context(loadout, rules)
    path = [0, 1, 2]
    word = "cat"
    mult_rules = loadout_mult_rules(loadout, rules, board=board, path=path)
    full = pipeline.score_total_only(board, path, word, loadout, solve_context=ctx)
    lb = tier2_immediate_lower_bound(board, path, word, loadout, ctx, mult_rules)
    ub = tier2_immediate_upper_bound(board, path, word, loadout, ctx, mult_rules)
    assert lb <= full <= ub
    rank_lb = tier2_rank_lower_bound(
        board,
        path,
        word,
        loadout,
        ctx,
        mult_rules,
        mult_weight=0.4,
    )
    assert rank_lb <= full


def test_searcher_grid_refs_cache_populated(tmp_path):
    from cursed_words_solver.dictionary import WordDictionary
    from cursed_words_solver.search import WordSearcher
    from tests.helpers.boards import _make_wordlist

    wl = _make_wordlist(tmp_path)
    board = _board_with_scattered_item()
    loadout = Loadout()
    searcher = WordSearcher(
        dictionary=WordDictionary(wl),
        min_len=3,
        max_len=6,
        time_budget=1.0,
    )
    results = searcher.find_best_words(board, loadout, top_n=1)
    assert results
    timing = searcher.last_search_timing
    assert timing is not None
    assert timing.grid_refs_cache_misses >= 1
    assert timing.grid_refs_cache_hits + timing.grid_refs_cache_misses >= 1
