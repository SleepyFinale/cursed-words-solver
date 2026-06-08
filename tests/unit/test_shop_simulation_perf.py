"""Shop simulation caching, deadline cap, and restock deduplication."""

from __future__ import annotations

import time
from unittest.mock import patch

from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.models import Board, CurseType, Loadout, LoadoutItem, ShopOffer, ShopState, Tile, TileColor
from cursed_words_solver.shop_advisor import run_shop_advisor
from cursed_words_solver.shop_simulation import (
    SimulationConfig,
    SimulationContext,
    evaluate_loadout_value,
    evaluate_purchase,
    evaluate_restock_ev,
)
from tests.helpers.boards import _make_wordlist


def _tiny_board() -> Board:
    tiles = [
        [
            Tile(r, c, "c", "c", 1, TileColor.SHINY, CurseType.LETTER)
            for c in range(5)
        ]
        for r in range(5)
    ]
    tiles[0][1] = Tile(0, 1, "a", "a", 1, TileColor.SHINY, CurseType.LETTER)
    tiles[0][2] = Tile(0, 2, "t", "t", 1, TileColor.SHINY, CurseType.LETTER)
    return Board(tiles=tiles)


def test_loadout_value_cache_hits(tmp_path):
    wl = _make_wordlist(tmp_path)
    dictionary = WordDictionary(wl)
    loadout = Loadout(stickers=[LoadoutItem(id="brain", name="Brain", level=1)])
    boards = [_tiny_board()]
    config = SimulationConfig(budget_sec=0.5, max_boards=1, total_budget_sec=30.0)
    ctx = SimulationContext.create(boards, dictionary, config)

    evaluate_loadout_value(ctx, loadout)
    searches_after_first = ctx.search_count
    cache_size_after_first = len(ctx._score_cache)

    evaluate_loadout_value(ctx, loadout)
    searches_after_second = ctx.search_count

    assert cache_size_after_first >= 1
    assert searches_after_second == searches_after_first


def test_deadline_returns_without_hanging(tmp_path):
    wl = _make_wordlist(tmp_path)
    dictionary = WordDictionary(wl)
    loadout = Loadout()
    boards = [_tiny_board()]
    config = SimulationConfig(
        budget_sec=5.0,
        max_boards=1,
        total_budget_sec=0.05,
        monte_carlo_samples=20,
    )
    ctx = SimulationContext.create(boards, dictionary, config)
    time.sleep(0.06)

    started = time.monotonic()
    value = evaluate_loadout_value(ctx, loadout)
    elapsed = time.monotonic() - started

    assert elapsed < 1.0
    assert value == 0.0
    assert ctx.budget_exhausted


def test_restock_uses_buy_nets_without_re_evaluating_offers(tmp_path):
    wl = _make_wordlist(tmp_path)
    dictionary = WordDictionary(wl)
    loadout = Loadout()
    boards = [_tiny_board()]
    shop = ShopState(
        restock_cost=2,
        offers=[
            ShopOffer(slot="sticker", index=0, id="brain", name="Brain", price=1, level=1),
        ],
    )
    config = SimulationConfig(budget_sec=0.2, max_boards=1, monte_carlo_samples=3)
    ctx = SimulationContext.create(boards, dictionary, config)

    with patch(
        "cursed_words_solver.shop_simulation.evaluate_purchase",
        return_value=(10.0, 5.0),
    ) as mock_purchase:
        rec = evaluate_restock_ev(
            loadout,
            shop,
            boards,
            dictionary,
            config=config,
            ctx=ctx,
            buy_nets={0: 100.0},
            baseline=100.0,
        )

    assert rec.action == "skip"
    mock_purchase.assert_not_called()


def test_run_shop_advisor_completes_quickly_with_tight_budget(tmp_path):
    wl = _make_wordlist(tmp_path)
    dictionary = WordDictionary(wl)
    loadout = Loadout(money=20, extras={"grids_remaining": "2"})
    offers = [
        ShopOffer(
            slot="sticker",
            index=i,
            id=f"item_{i}",
            name=f"Item {i}",
            price=3,
            level=1,
        )
        for i in range(8)
    ]
    shop = ShopState(restock_cost=2, offers=offers)
    config = SimulationConfig(
        budget_sec=0.2,
        max_boards=1,
        total_budget_sec=2.0,
        monte_carlo_samples=3,
        search_workers=1,
    )

    started = time.monotonic()
    advice = run_shop_advisor(
        loadout,
        shop,
        [],
        dictionary,
        config=config,
    )
    elapsed = time.monotonic() - started

    assert elapsed < 5.0
    assert advice.restock is not None
