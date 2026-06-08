"""Tests for the in-game ShopRecommendation port."""

from __future__ import annotations

from cursed_words_solver.game_shop.metadata import lookup_metadata_for_slug
from cursed_words_solver.game_shop.recommendation import (
    build_shop_context,
    compute_shop_advice,
    get_most_common_builds,
    select_advice_tier,
)
from cursed_words_solver.game_shop.types import (
    AdviceData,
    GameShopItem,
    GameShopTile,
    ItemFunction,
    ItemTag,
    ShopAdviceContext,
    player_should_restock,
)
from cursed_words_solver.game_shop.utility_advice import high_priority_utility_advice
from cursed_words_solver.models import Loadout, LoadoutItem, ShopOffer, ShopState
from cursed_words_solver.shop_advisor import run_shop_advisor


def _item(
    item_id: str,
    *,
    slot: str = "sticker",
    index: int = 0,
    price: int = 5,
) -> GameShopItem:
    meta = lookup_metadata_for_slug(item_id)
    return GameShopItem(
        id=item_id,
        name=item_id.replace("_", " ").title(),
        slot=slot,
        index=index,
        price=price,
        shop_advice_tags=frozenset(meta.shop_advice_tags if meta else ()),
        function_tags=frozenset(meta.function_tags if meta else ()),
        blacklisted=meta.blacklisted_from_shop_recommendations if meta else False,
    )


def test_player_should_restock_thresholds():
    assert player_should_restock(10, 2) is True
    assert player_should_restock(3, 2) is True
    assert player_should_restock(2, 3) is False
    assert player_should_restock(20, 5) is True
    assert player_should_restock(10, 6) is False
    assert player_should_restock(8, 5) is False


def test_get_most_common_builds_blue_scatter():
    inventory = [
        _item("april_shower"),
        _item("soaring_kite"),
        _item("blueberries"),
    ]
    builds = get_most_common_builds(inventory)
    assert ItemTag.BLUE_BUILD in builds


def test_april_shower_metadata_is_scatterer():
    meta = lookup_metadata_for_slug("april_shower")
    assert meta is not None
    assert "BlueBuild" in meta.shop_advice_tags
    assert "Scatterer" in meta.function_tags


def test_recommends_blue_scatter_when_missing():
    inventory = [_item("blueberries")]
    shop_items = [_item("april_shower", index=0, price=4)]
    ctx = ShopAdviceContext(
        money=10,
        sticker_count=1,
        stamp_count=1,
        tile_count=0,
        inventory=inventory,
        shop_items=shop_items,
        shop_tiles=[],
        restock_cost=2,
        free_item_available=False,
    )
    advice = select_advice_tier(ctx)
    assert advice.recommended_items
    assert advice.recommended_items[0].id == "april_shower"
    assert advice.function_fulfilled == ItemFunction.SCATTERER


def test_freeze_when_unaffordable():
    inventory = [_item("blueberries")]
    shop_items = [_item("april_shower", index=0, price=20)]
    ctx = ShopAdviceContext(
        money=5,
        sticker_count=1,
        stamp_count=1,
        tile_count=0,
        inventory=inventory,
        shop_items=shop_items,
        shop_tiles=[],
        restock_cost=2,
        free_item_available=False,
    )
    advice = compute_shop_advice(
        Loadout(
            stickers=[LoadoutItem(id="blueberries", name="Blueberries")],
            stamps=[],
            money=5,
        ),
        ShopState(
            restock_cost=2,
            offers=[
                ShopOffer(
                    slot="sticker",
                    index=0,
                    id="april_shower",
                    name="April Shower",
                    price=20,
                )
            ],
        ),
    )
    assert advice.should_freeze or advice.should_restock or advice.should_leave


def test_golden_scales_utility_advice():
    item = _item("golden_scales", price=10)
    ctx = ShopAdviceContext(
        money=15,
        sticker_count=1,
        stamp_count=0,
        tile_count=0,
        inventory=[],
        shop_items=[item],
        shop_tiles=[],
        restock_cost=2,
        free_item_available=False,
    )
    advice = high_priority_utility_advice(item, ctx, [])
    assert advice is not None
    assert advice.should_buy
    assert "golden" in advice.specific_reason.lower() or "Golden" in advice.specific_reason


def test_northern_cardinal_on_red_build():
    item = _item("young_cardinal", slot="stamp", price=8)
    inventory = [_item("cherries")]
    builds = get_most_common_builds(inventory)
    ctx = ShopAdviceContext(
        money=12,
        sticker_count=1,
        stamp_count=0,
        tile_count=0,
        inventory=inventory,
        shop_items=[item],
        shop_tiles=[],
        restock_cost=2,
        free_item_available=False,
    )
    from cursed_words_solver.game_shop.recommendation import get_build_data_for_build

    build_data = [get_build_data_for_build(b, inventory) for b in builds]
    advice = high_priority_utility_advice(item, ctx, build_data)
    assert advice is not None
    assert advice.build == ItemTag.RED_BUILD


def test_tile_advice_for_blue_build():
    inventory = [_item("april_shower"), _item("soaring_kite")]
    shop_tiles = [
        GameShopTile(index=0, price=3, color="blue", curse="letter", letter="T"),
    ]
    ctx = ShopAdviceContext(
        money=10,
        sticker_count=2,
        stamp_count=0,
        tile_count=2,
        inventory=inventory,
        shop_items=[],
        shop_tiles=shop_tiles,
        restock_cost=2,
        free_item_available=False,
    )
    from cursed_words_solver.game_shop.recommendation import get_tile_advice_data, get_build_data_for_build

    builds = [get_build_data_for_build(b, inventory) for b in get_most_common_builds(inventory)]
    tiles = get_tile_advice_data(builds, shop_tiles, money=10, tile_count=2)
    assert tiles
    assert tiles[0].recommended_tiles


def test_restock_when_nothing_useful():
    inventory = [_item("april_shower")]
    ctx = ShopAdviceContext(
        money=20,
        sticker_count=1,
        stamp_count=0,
        tile_count=0,
        inventory=inventory,
        shop_items=[],
        shop_tiles=[],
        restock_cost=2,
        free_item_available=False,
    )
    advice = AdviceData(build=ItemTag.BLUE_BUILD, recommended_items=[])
    from cursed_words_solver.game_shop.advice_resolve import resolve_advice_actions

    resolved = resolve_advice_actions(advice, ctx, free_item_active=False)
    assert resolved.should_restock


def test_run_shop_advisor_end_to_end():
    loadout = Loadout(
        stickers=[
            LoadoutItem(id="april_shower", name="April Shower"),
            LoadoutItem(id="soaring_kite", name="Soaring Kite"),
        ],
        stamps=[],
        money=15,
    )
    shop = ShopState(
        restock_cost=2,
        offers=[
            ShopOffer(
                slot="sticker",
                index=0,
                id="blueberries",
                name="Blueberries",
                price=6,
            ),
            ShopOffer(
                slot="stamp",
                index=0,
                id="genie",
                name="Genie",
                price=12,
            ),
        ],
    )
    advice = run_shop_advisor(loadout, shop)
    assert advice.reason or advice.buys or advice.restock or advice.leave_shop
