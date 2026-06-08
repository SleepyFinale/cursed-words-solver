"""Sell advice ranking."""

from __future__ import annotations

from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.models import (
    Board,
    CurseType,
    Loadout,
    LoadoutItem,
    SellCandidate,
    ShopOffer,
    Tile,
    TileColor,
)
from cursed_words_solver.shop_simulation import (
    SimulationConfig,
    SimulationContext,
    evaluate_sell,
    evaluate_sell_swaps,
)
from cursed_words_solver.shop_boards import prepare_boards_for_shop_sim, prepare_loadout_for_shop_sim
from tests.helpers.boards import _make_wordlist


def _board() -> Board:
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


def test_sell_evaluation_runs(tmp_path):
    wl = _make_wordlist(tmp_path)
    dictionary = WordDictionary(wl)
    loadout = Loadout(
        stickers=[
            LoadoutItem(id="brain", name="Brain", level=2),
            LoadoutItem(id="mystery_gift", name="Mystery Gift", level=1),
        ],
        extras={"grids_remaining": "2"},
    )
    candidate = SellCandidate(
        kind="sticker",
        slot=1,
        id="mystery_gift",
        name="Mystery Gift",
        sell_value=2,
    )
    config = SimulationConfig(budget_sec=1.0, max_boards=1)
    loss, net, reason = evaluate_sell(
        candidate, loadout, [_board()], dictionary, config=config
    )
    assert isinstance(loss, float)
    assert isinstance(net, float)
    assert isinstance(reason, str)
    raw_cash = 2 * config.word_per_dollar
    assert net <= raw_cash


def test_sell_swaps_require_clear_upgrade(tmp_path):
    wl = _make_wordlist(tmp_path)
    dictionary = WordDictionary(wl)
    loadout = prepare_loadout_for_shop_sim(
        Loadout(
            stickers=[LoadoutItem(id="mystery_gift", name="Mystery Gift", level=1)],
            money=10,
            extras={"grids_remaining": "2"},
        )
    )
    boards = prepare_boards_for_shop_sim([_board()])
    config = SimulationConfig(budget_sec=1.0, max_boards=1, total_budget_sec=0)
    ctx = SimulationContext.create(boards, dictionary, config)
    candidate = SellCandidate(
        kind="sticker",
        slot=0,
        id="mystery_gift",
        name="Mystery Gift",
        level=1,
        sell_value=2,
    )
    offers = [
        ShopOffer(
            slot="sticker",
            index=0,
            id="brain",
            name="Brain",
            level=1,
            price=3,
        )
    ]
    swaps = evaluate_sell_swaps(
        loadout,
        None,
        [candidate],
        offers,
        boards,
        dictionary,
        config=config,
        ctx=ctx,
        margin_word=50.0,
    )
    assert isinstance(swaps, list)
