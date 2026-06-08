"""Shop board prep, catalog lift, and purchase/sell intelligence."""

from __future__ import annotations

from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.models import (
    Board,
    CurseType,
    Loadout,
    LoadoutItem,
    SellCandidate,
    ShopOffer,
    ShopState,
    Tile,
    TileColor,
)
from cursed_words_solver.shop_advisor import _is_duplicate_buy, run_shop_advisor
from cursed_words_solver.shop_boards import (
    prepare_boards_for_shop_sim,
    prepare_loadout_for_shop_sim,
)
from cursed_words_solver.shop_economy import can_add_offer, is_upgrade_offer, money_to_word_equiv
from cursed_words_solver.shop_item_value import catalog_lift_for_offer
from cursed_words_solver.shop_simulation import (
    SimulationConfig,
    SimulationContext,
    _apply_purchase,
    evaluate_purchase,
    evaluate_sell,
    evaluate_sell_swaps,
)
from tests.helpers.boards import _make_wordlist


def _colorless_board(*, melmod: bool = True) -> Board:
    tiles = [
        [
            Tile(
                r,
                c,
                "c",
                "c",
                1,
                TileColor.COLORLESS,
                CurseType.LETTER,
                metadata={"source": "melmod"} if melmod else {},
            )
            for c in range(5)
        ]
        for r in range(5)
    ]
    tiles[0][0] = Tile(0, 0, "c", "c", 1, TileColor.COLORLESS, CurseType.LETTER)
    tiles[0][1] = Tile(0, 1, "a", "a", 1, TileColor.COLORLESS, CurseType.LETTER)
    tiles[0][2] = Tile(0, 2, "t", "t", 1, TileColor.COLORLESS, CurseType.LETTER)
    return Board(tiles=tiles)


def _red_board() -> Board:
    tiles = [
        [
            Tile(r, c, "r", "r", 2, TileColor.RED, CurseType.LETTER)
            for c in range(5)
        ]
        for r in range(5)
    ]
    tiles[1][1] = Tile(1, 1, "e", "e", 1, TileColor.COLORLESS, CurseType.LETTER)
    tiles[1][2] = Tile(1, 2, "d", "d", 1, TileColor.COLORLESS, CurseType.LETTER)
    return Board(tiles=tiles)


def test_prepare_boards_strips_melmod_source():
    board = _colorless_board(melmod=True)
    prepared = prepare_boards_for_shop_sim([board])[0]
    assert all(
        t.metadata.get("source") is None for t in prepared.flat if prepared.is_active_index(t.index)
    )


def test_prepare_loadout_allows_grid_sim():
    loadout = Loadout(stickers=[LoadoutItem(id="fountain", name="Fountain", level=1)])
    prepared = prepare_loadout_for_shop_sim(loadout)
    assert str(prepared.extras.get("board_from_melmod")).lower() == "false"
    assert prepared.extras.get("scatter_seed") is not None


def test_fountain_catalog_lift_positive():
    loadout = prepare_loadout_for_shop_sim(
        Loadout(extras={"grids_remaining": "3"})
    )
    offer = ShopOffer(slot="sticker", index=0, id="fountain", name="Fountain", level=1, price=5)
    lift, kind = catalog_lift_for_offer(offer, loadout, [_colorless_board(melmod=False)])
    assert lift > 0
    assert kind == "grid setup"


def test_fountain_purchase_lift_with_board_prep(tmp_path):
    wl = _make_wordlist(tmp_path)
    dictionary = WordDictionary(wl)
    loadout = prepare_loadout_for_shop_sim(
        Loadout(extras={"grids_remaining": "2"})
    )
    boards = prepare_boards_for_shop_sim([_colorless_board()])
    offer = ShopOffer(slot="sticker", index=0, id="fountain", name="Fountain", level=1, price=3)
    config = SimulationConfig(budget_sec=1.5, max_boards=1, total_budget_sec=0)
    lift, net, reason = evaluate_purchase(
        offer,
        loadout,
        None,
        boards,
        dictionary,
        config=config,
    )
    assert lift > 0 or net > 0
    assert reason


def test_sell_fountain_not_raw_cash_only(tmp_path):
    wl = _make_wordlist(tmp_path)
    dictionary = WordDictionary(wl)
    loadout = prepare_loadout_for_shop_sim(
        Loadout(
            stickers=[LoadoutItem(id="fountain", name="Fountain", level=1)],
            extras={"grids_remaining": "2"},
        )
    )
    boards = prepare_boards_for_shop_sim([_colorless_board()])
    candidate = SellCandidate(
        kind="sticker",
        slot=0,
        id="fountain",
        name="Fountain",
        level=1,
        sell_value=5,
    )
    config = SimulationConfig(budget_sec=1.5, max_boards=1, total_budget_sec=0)
    _loss, net, _reason = evaluate_sell(
        candidate, loadout, boards, dictionary, config=config
    )
    raw_cash = money_to_word_equiv(5, word_per_dollar=config.word_per_dollar)
    assert net < raw_cash


def test_telescope_catalog_lift_with_reds(tmp_path):
    loadout = prepare_loadout_for_shop_sim(
        Loadout(extras={"grids_remaining": "2", "red_tiles_used_encounter": "2"})
    )
    offer = ShopOffer(slot="sticker", index=0, id="telescope", name="Telescope", level=1, price=8)
    lift, kind = catalog_lift_for_offer(offer, loadout, [_red_board()])
    assert lift > 0
    assert kind == "encounter red bonus"


def test_swap_guard_suppresses_sell_when_buy_not_better(tmp_path):
    wl = _make_wordlist(tmp_path)
    dictionary = WordDictionary(wl)
    loadout = prepare_loadout_for_shop_sim(
        Loadout(
            stickers=[LoadoutItem(id="fountain", name="Fountain", level=1)],
            money=20,
            extras={"grids_remaining": "2"},
        )
    )
    shop = ShopState(
        restock_cost=2,
        offers=[
            ShopOffer(
                slot="sticker",
                index=0,
                id="telescope",
                name="Telescope",
                level=1,
                price=8,
            )
        ],
    )
    sells = [
        SellCandidate(
            kind="sticker",
            slot=0,
            id="fountain",
            name="Fountain",
            level=1,
            sell_value=5,
        )
    ]
    config = SimulationConfig(
        budget_sec=0.3,
        max_boards=1,
        total_budget_sec=3.0,
        monte_carlo_samples=3,
        search_workers=1,
    )
    advice = run_shop_advisor(loadout, shop, sells, dictionary, config=config)
    assert not advice.sells
    assert any("sell→buy swap" in w for w in advice.warnings)


def test_backpack_flip_flop_no_sell(tmp_path):
    """Selling Backpack for $6 to buy Ladybird should not show as +293 WORD."""
    wl = _make_wordlist(tmp_path)
    dictionary = WordDictionary(wl)
    loadout = prepare_loadout_for_shop_sim(
        Loadout(
            stickers=[LoadoutItem(id="backpack", name="Backpack", level=1)],
            money=6,
            extras={"grids_remaining": "2"},
        )
    )
    shop = ShopState(
        restock_cost=2,
        offers=[
            ShopOffer(
                slot="sticker",
                index=0,
                id="ladybird",
                name="Ladybird",
                level=1,
                price=3,
            ),
            ShopOffer(
                slot="sticker",
                index=1,
                id="backpack",
                name="Backpack",
                level=1,
                price=5,
            ),
        ],
    )
    sells = [
        SellCandidate(
            kind="sticker",
            slot=0,
            id="backpack",
            name="Backpack",
            level=1,
            sell_value=6,
        )
    ]
    config = SimulationConfig(
        budget_sec=0.5,
        max_boards=1,
        total_budget_sec=5.0,
        monte_carlo_samples=3,
        search_workers=1,
    )
    advice = run_shop_advisor(loadout, shop, sells, dictionary, config=config)
    assert not advice.sells
    buy_labels = [b.label for b in advice.buys]
    assert not any("Backpack" in label for label in buy_labels)


def test_sell_swaps_integrated_not_cash_profit(tmp_path):
    wl = _make_wordlist(tmp_path)
    dictionary = WordDictionary(wl)
    loadout = prepare_loadout_for_shop_sim(
        Loadout(
            stickers=[LoadoutItem(id="backpack", name="Backpack", level=1)],
            money=6,
            extras={"grids_remaining": "2"},
        )
    )
    boards = prepare_boards_for_shop_sim([_colorless_board()])
    config = SimulationConfig(budget_sec=1.0, max_boards=1, total_budget_sec=0)
    ctx = SimulationContext.create(boards, dictionary, config)
    candidate = SellCandidate(
        kind="sticker",
        slot=0,
        id="backpack",
        name="Backpack",
        level=1,
        sell_value=6,
    )
    offers = [
        ShopOffer(
            slot="sticker",
            index=0,
            id="ladybird",
            name="Ladybird",
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
        baseline=0.0,
        margin_word=50.0,
    )
    assert not swaps


def test_no_buy_duplicate_sticker():
    loadout = Loadout(stickers=[LoadoutItem(id="backpack", name="Backpack", level=1)])
    offer = ShopOffer(slot="sticker", index=0, id="backpack", name="Backpack", level=1, price=5)
    assert _is_duplicate_buy(offer, loadout)
    upgrade = ShopOffer(slot="sticker", index=0, id="backpack", name="Backpack", level=2, price=8)
    assert not _is_duplicate_buy(upgrade, loadout)


def test_upgrade_allowed_when_sticker_slots_full():
    stickers = [
        LoadoutItem(id=f"s{i}", name=f"S{i}", level=1) for i in range(4)
    ] + [LoadoutItem(id="backpack", name="Backpack", level=1)]
    loadout = Loadout(stickers=stickers)
    assert can_add_offer(
        ShopOffer(slot="sticker", index=0, id="other", name="Other", level=1, price=5),
        loadout,
    ) is False
    upgrade = ShopOffer(
        slot="sticker", index=1, id="backpack", name="Backpack", level=2, price=8
    )
    assert is_upgrade_offer(upgrade, loadout)
    assert can_add_offer(upgrade, loadout)


def test_apply_purchase_upgrades_in_place():
    loadout = Loadout(stickers=[LoadoutItem(id="backpack", name="Backpack", level=1)])
    offer = ShopOffer(slot="sticker", index=0, id="backpack", name="Backpack", level=2, price=8)
    result = _apply_purchase(loadout, offer)
    assert len(result.stickers) == 1
    assert result.stickers[0].level == 2


def test_restock_skips_when_reserve_would_break():
    from cursed_words_solver.shop_reserve import build_shop_run_context
    from cursed_words_solver.shop_simulation import evaluate_restock_ev

    loadout = Loadout(
        money=12,
        extras={"shop_node": "ShopZero", "boss_area_number": "2"},
    )
    shop = ShopState(restock_cost=3)
    run_ctx = build_shop_run_context(loadout)
    rec = evaluate_restock_ev(
        loadout,
        shop,
        [],
        WordDictionary([]),
        config=SimulationConfig(),
        run_ctx=run_ctx,
    )
    assert rec.action == "no"
    assert "reserve" in rec.reason.lower()
