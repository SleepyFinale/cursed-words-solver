"""Shop reserve, leave-shop, and freeze advice."""

from __future__ import annotations

from cursed_words_solver.models import (
    ActionRecommendation,
    Loadout,
    LoadoutItem,
    RankedAction,
    ShopOffer,
    ShopState,
)
from cursed_words_solver.shop_reserve import (
    build_shop_run_context,
    evaluate_freeze_candidates,
    filter_ranked_buys,
    passes_marginal,
    passes_reserve,
    should_leave_shop,
)


def _loadout(*, money: int = 20, shop_node: str = "ShopZero", area: int = 2) -> Loadout:
    return Loadout(
        money=money,
        extras={"shop_node": shop_node, "boss_area_number": str(area)},
    )


def test_shop_zero_two_shops_remaining_reserve():
    ctx = build_shop_run_context(_loadout(shop_node="ShopZero", area=3))
    assert ctx.shops_remaining == 2
    assert ctx.money_reserve == 22  # (8+3)*2
    assert ctx.min_net == 30.0


def test_shop_two_no_reserve():
    ctx = build_shop_run_context(_loadout(shop_node="ShopTwo"))
    assert ctx.shops_remaining == 0
    assert ctx.money_reserve == 0
    assert ctx.min_net == 0.0


def test_missing_shop_node_fallback():
    ctx = build_shop_run_context(Loadout(money=10, extras={}))
    assert ctx.shops_remaining == 1
    assert not ctx.shop_node_known


def test_passes_marginal_blocks_weak_buy():
    ctx = build_shop_run_context(_loadout(shop_node="ShopOne"))
    assert not passes_marginal(7.0, ctx)
    assert passes_marginal(20.0, ctx)


def test_upgrade_half_marginal_hurdle():
    ctx = build_shop_run_context(_loadout(shop_node="ShopOne"))
    assert not passes_marginal(7.0, ctx, upgrade=True)
    assert passes_marginal(9.0, ctx, upgrade=True)


def test_passes_reserve_strict():
    ctx = build_shop_run_context(_loadout(shop_node="ShopZero", area=2, money=25))
    assert ctx.money_reserve == 20
    assert passes_reserve(5, 25, ctx)
    assert not passes_reserve(10, 25, ctx)


def test_upgrade_soft_reserve():
    ctx = build_shop_run_context(_loadout(shop_node="ShopZero", money=25))
    assert not passes_reserve(10, 25, ctx, net=50.0, upgrade=False)
    assert passes_reserve(10, 25, ctx, net=50.0, upgrade=True)


def test_filter_ranked_buys_blocks_marginal():
    loadout = _loadout(shop_node="ShopOne", money=15)
    shop = ShopState()
    ctx = build_shop_run_context(loadout)
    offer = ShopOffer(slot="sticker", index=0, id="fountain", name="Fountain", price=5)
    buys = [
        RankedAction(
            action="buy",
            label="Buy Fountain",
            net_value=7.0,
            offer_index=0,
        )
    ]
    approved, blocked = filter_ranked_buys(
        buys,
        loadout,
        shop,
        {0: offer},
        ctx,
        use_free=False,
    )
    assert not approved
    assert len(blocked) == 1


def test_should_leave_shop_when_nothing_actionable():
    ctx = build_shop_run_context(_loadout(shop_node="ShopTwo"))
    leave, reason = should_leave_shop([], [], None, ctx=ctx)
    assert leave
    assert "Last shop" in reason


def test_freeze_unaffordable_strong_offer():
    loadout = _loadout(shop_node="ShopZero", money=8)
    shop = ShopState(
        offers=[
            ShopOffer(
                slot="sticker",
                index=0,
                id="fountain",
                name="Fountain",
                price=13,
            )
        ]
    )
    ctx = build_shop_run_context(loadout)
    offer = shop.offers[0]

    def _never_duplicate(_offer: ShopOffer, _lo: Loadout) -> bool:
        return False

    freezes = evaluate_freeze_candidates(
        loadout,
        shop,
        [offer],
        ctx=ctx,
        buy_lifts={0: 80.0},
        buy_nets={0: 10.0},
        approved_buy_indices=set(),
        use_free=False,
        is_duplicate_buy=_never_duplicate,
    )
    assert len(freezes) == 1
    assert "Fountain" in freezes[0].label
    assert "Can't afford" in freezes[0].reason


def test_no_freeze_when_erupting_volcano_owned():
    loadout = Loadout(
        money=8,
        stickers=[LoadoutItem(id="erupting_volcano", name="Erupting Volcano", level=1)],
        extras={"shop_node": "ShopZero"},
    )
    shop = ShopState(
        offers=[
            ShopOffer(slot="sticker", index=0, id="fountain", name="Fountain", price=13)
        ]
    )
    ctx = build_shop_run_context(loadout)

    def _never_duplicate(_offer: ShopOffer, _lo: Loadout) -> bool:
        return False

    freezes = evaluate_freeze_candidates(
        loadout,
        shop,
        shop.offers,
        ctx=ctx,
        buy_lifts={0: 80.0},
        buy_nets={0: 10.0},
        approved_buy_indices=set(),
        use_free=False,
        is_duplicate_buy=_never_duplicate,
    )
    assert not freezes


def test_no_freeze_already_frozen():
    loadout = _loadout(money=8)
    shop = ShopState(
        offers=[
            ShopOffer(
                slot="sticker",
                index=0,
                id="fountain",
                name="Fountain",
                price=13,
                frozen=True,
            )
        ]
    )
    ctx = build_shop_run_context(loadout)

    def _never_duplicate(_offer: ShopOffer, _lo: Loadout) -> bool:
        return False

    freezes = evaluate_freeze_candidates(
        loadout,
        shop,
        shop.offers,
        ctx=ctx,
        buy_lifts={0: 80.0},
        buy_nets={0: 10.0},
        approved_buy_indices=set(),
        use_free=False,
        is_duplicate_buy=_never_duplicate,
    )
    assert not freezes


def test_marginal_blocks_zero_price_discount_buy():
    loadout = Loadout(
        money=17,
        extras={"shop_node": "ShopZero", "boss_area_number": "1"},
    )
    shop = ShopState()
    ctx = build_shop_run_context(loadout)
    offer = ShopOffer(
        slot="sticker",
        index=0,
        id="under_construction",
        name="Under Construction",
        price=0,
    )
    buys = [
        RankedAction(
            action="buy",
            label="Buy Under Construction",
            net_value=1.0,
            score_lift=1.0,
            offer_index=0,
        )
    ]
    approved, blocked = filter_ranked_buys(
        buys,
        loadout,
        shop,
        {0: offer},
        ctx,
        use_free=False,
    )
    assert not approved
    assert len(blocked) == 1


def test_marginal_blocks_shop_marked_free_at_shop_zero():
    loadout = Loadout(
        money=17,
        extras={"shop_node": "ShopZero", "boss_area_number": "1"},
    )
    shop = ShopState()
    ctx = build_shop_run_context(loadout)
    offer = ShopOffer(
        slot="sticker",
        index=0,
        id="under_construction",
        name="Under Construction",
        price=0,
        free=True,
    )
    buys = [
        RankedAction(
            action="buy",
            label="Buy Under Construction",
            net_value=1.0,
            score_lift=1.0,
            offer_index=0,
        )
    ]
    approved, blocked = filter_ranked_buys(
        buys,
        loadout,
        shop,
        {0: offer},
        ctx,
        use_free=False,
    )
    assert not approved
    assert len(blocked) == 1


def test_marginal_blocks_paid_buy_when_free_item_available():
    """Global free-purchase must not bypass reserve/marginal filtering."""
    loadout = Loadout(
        money=23,
        extras={"shop_node": "ShopZero", "boss_area_number": "1"},
    )
    shop = ShopState(free_item_available=True)
    ctx = build_shop_run_context(loadout)
    offer = ShopOffer(
        slot="sticker",
        index=0,
        id="fireworks",
        name="Fireworks",
        price=8,
    )
    buys = [
        RankedAction(
            action="buy",
            label="Buy Fireworks",
            net_value=7.0,
            score_lift=7.0,
            offer_index=0,
        )
    ]
    approved, blocked = filter_ranked_buys(
        buys,
        loadout,
        shop,
        {0: offer},
        ctx,
        use_free=True,
    )
    assert not approved
    assert len(blocked) == 1


def test_leave_shop_with_freeze_hint():
    ctx = build_shop_run_context(_loadout(shop_node="ShopZero"))
    freezes = [
        RankedAction(action="freeze", label="Freeze Fountain", net_value=80.0)
    ]
    leave, reason = should_leave_shop(
        [],
        [],
        ActionRecommendation(action="no", label="Skip restock"),
        ctx=ctx,
        freezes=freezes,
    )
    assert leave
    assert "Freeze Fountain" in reason
