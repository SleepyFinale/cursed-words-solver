"""Masochist / Antiphilatelist / In The Beginning offer filtering."""

from cursed_words_solver.models import Loadout, ShopOffer, ShopState
from cursed_words_solver.rules.shop_quest_effects import filter_shop_offers


def _shop() -> ShopState:
    return ShopState(
        offers=[
            ShopOffer(slot="sticker", index=0, id="tombstone", name="Tombstone", price=4),
            ShopOffer(slot="stamp", index=0, id="newspaper", name="Newspaper", price=3),
            ShopOffer(slot="tile", index=0, id="tile", name="Tile", price=2),
        ]
    )


def test_masochist_filters_stickers() -> None:
    loadout = Loadout(extras={"challenge_game_class": "Masochist"})
    slots = {o.slot for o in filter_shop_offers(loadout, _shop()).offers}
    assert "sticker" not in slots
    assert "stamp" in slots


def test_antiphilatelist_filters_stamps() -> None:
    loadout = Loadout(extras={"challenge_game_class": "Antiphilatelist"})
    slots = {o.slot for o in filter_shop_offers(loadout, _shop()).offers}
    assert "stamp" not in slots
    assert "sticker" in slots


def test_in_the_beginning_tiles_only() -> None:
    loadout = Loadout(extras={"challenge_game_class": "InTheBeginning"})
    slots = {o.slot for o in filter_shop_offers(loadout, _shop()).offers}
    assert slots == {"tile"}
