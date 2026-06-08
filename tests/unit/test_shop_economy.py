"""Shop economy rules."""

from __future__ import annotations

from cursed_words_solver.models import Loadout, LoadoutItem, SellCandidate, ShopOffer, ShopState
from cursed_words_solver.shop_economy import (
    effective_purchase_price,
    net_sell_proceeds,
    restock_cost,
    sticker_slots_available,
)


def test_blessing_flat_ten_dollars():
    loadout = Loadout(stamps=[LoadoutItem(id="blessing_of_the_shopkeeper", name="Blessing", kind="stamp")])
    offer = ShopOffer(slot="stamp", index=0, id="genie", name="Genie", price=25)
    assert effective_purchase_price(offer, loadout, None) == 10


def test_avocado_doubles_price():
    loadout = Loadout(stamps=[LoadoutItem(id="avocado", name="Avocado", kind="stamp")])
    offer = ShopOffer(slot="sticker", index=0, id="brain", name="Brain", price=6)
    assert effective_purchase_price(offer, loadout, None) == 12


def test_free_item_zero_cost():
    loadout = Loadout()
    offer = ShopOffer(slot="sticker", index=0, id="brain", name="Brain", price=6, free=True)
    assert effective_purchase_price(offer, loadout, None) == 0


def test_padlock_sell_costs_money():
    candidate = SellCandidate(
        kind="stamp",
        slot=0,
        id="padlock",
        name="Padlock",
        sell_value=0,
        sell_cost=8,
        costs_money_to_sell=True,
    )
    assert net_sell_proceeds(candidate, Loadout()) == -8


def test_restock_uses_shop_field():
    loadout = Loadout(extras={"shop_restock_count": "2"})
    shop = ShopState(restock_cost=4)
    assert restock_cost(loadout, shop) == 4


def test_fried_shrimp_discount():
    loadout = Loadout(
        stamps=[LoadoutItem(id="fried_shrimp", name="Fried Shrimp", kind="stamp")],
        extras={"shop_restock_count": "1"},
    )
    assert restock_cost(loadout, None) == 1


def test_sticker_slot_limit():
    loadout = Loadout(stickers=[LoadoutItem(id=f"s{i}", name=f"S{i}") for i in range(5)])
    assert sticker_slots_available(loadout) == 0
