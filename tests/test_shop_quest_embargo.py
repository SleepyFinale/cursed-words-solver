"""Embargo quest shop filtering and sell block."""

from cursed_words_solver.game_shop.advice_resolve import resolve_advice_actions
from cursed_words_solver.game_shop.types import AdviceData, ItemTag, ShopAdviceContext
from cursed_words_solver.models import Loadout, ShopOffer, ShopState
from cursed_words_solver.rules.shop_quest_effects import filter_shop_offers
from cursed_words_solver.shop_advisor import run_shop_advisor


def test_filter_embargoed_offers() -> None:
    loadout = Loadout(
        extras={
            "challenge_game_class": "Embargo",
            "embargoed_item_types": "Blueberries",
        }
    )
    shop = ShopState(
        offers=[
            ShopOffer(slot="sticker", index=0, id="blueberries", name="Blueberries", price=5),
            ShopOffer(slot="sticker", index=1, id="tombstone", name="Tombstone", price=4),
        ]
    )
    filtered = filter_shop_offers(loadout, shop)
    ids = {o.id for o in filtered.offers}
    assert "blueberries" not in ids
    assert "tombstone" in ids


def test_embargo_blocks_sell_in_resolve() -> None:
    advice = AdviceData(build=ItemTag.BLUE_BUILD, should_sell=True)
    ctx = ShopAdviceContext(
        money=10,
        sticker_count=5,
        stamp_count=2,
        tile_count=0,
        inventory=[],
        shop_items=[],
        shop_tiles=[],
        restock_cost=3,
        free_item_available=False,
        block_sell=True,
    )
    out = resolve_advice_actions(advice, ctx, free_item_active=False)
    assert not out.should_sell


def test_embargo_advisor_no_sell_action() -> None:
    from cursed_words_solver.models import LoadoutItem

    loadout = Loadout(
        money=3,
        stickers=[
            LoadoutItem(id=f"s{i}", name=f"S{i}", level=1) for i in range(5)
        ],
        extras={"challenge_game_class": "Embargo"},
    )
    shop = ShopState(
        offers=[
            ShopOffer(slot="sticker", index=0, id="april_shower", name="April Shower", price=8),
        ]
    )
    advice = run_shop_advisor(loadout, shop)
    assert not advice.sells
