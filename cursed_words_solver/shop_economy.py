"""Shop pricing, sell value, and slot constraints."""

from __future__ import annotations

from cursed_words_solver.models import Loadout, SellCandidate, ShopOffer, ShopState


def _has_stamp(loadout: Loadout, stamp_id: str) -> bool:
    sid = stamp_id.lower()
    return any((s.id or "").lower() == sid for s in loadout.stamps)


def _has_sticker(loadout: Loadout, sticker_id: str) -> bool:
    sid = sticker_id.lower()
    return any((s.id or "").lower() == sid for s in loadout.stickers)


def owned_sticker_level(loadout: Loadout, sticker_id: str) -> int:
    sid = sticker_id.lower()
    for sticker in loadout.stickers:
        if (sticker.id or "").lower() == sid:
            return max(1, sticker.level)
    return 0


def is_sticker_foiled(loadout: Loadout, sticker_id: str) -> bool:
    sid = sticker_id.lower()
    extras = loadout.extras or {}
    foil_ids = extras.get("foil_sticker_ids") or []
    return sid in {str(x).lower() for x in foil_ids}


def is_upgrade_offer(offer: ShopOffer, loadout: Loadout) -> bool:
    """True when the shop offer upgrades an owned sticker (level or foil)."""
    if offer.slot != "sticker":
        return False
    oid = (offer.id or "").lower()
    owned = owned_sticker_level(loadout, oid)
    if owned <= 0:
        return False
    if max(1, offer.level or 1) > owned:
        return True
    return bool(offer.foil) and not is_sticker_foiled(loadout, oid)


def _int_extra(loadout: Loadout, key: str, default: int = 0) -> int:
    extras = loadout.extras or {}
    try:
        return int(extras.get(key, default))
    except (TypeError, ValueError):
        return default


def _bool_extra(loadout: Loadout, key: str) -> bool:
    extras = loadout.extras or {}
    val = extras.get(key)
    if isinstance(val, bool):
        return val
    return str(val or "").strip().lower() in {"1", "true", "yes"}


def effective_purchase_price(
    offer: ShopOffer,
    loadout: Loadout,
    shop: ShopState | None,
    *,
    use_free_item: bool = False,
) -> int:
    """Effective dollars to pay for an offer after stamp/shop modifiers."""
    if offer.sold:
        return 0
    if offer.free or use_free_item:
        return 0

    price = max(0, offer.price)
    if _has_stamp(loadout, "blessing_of_the_shopkeeper"):
        return 10

    if _has_stamp(loadout, "avocado") and not _bool_extra(loadout, "frozen_in_shop"):
        price *= 2

    if offer.frozen and _has_stamp(loadout, "downward_trending_chart"):
        visits = max(1, _int_extra(loadout, "shop_visit_count", 1))
        price = max(0, price - 2 * visits)

    if _is_red_description_item(offer) and _has_stamp(loadout, "young_cardinal"):
        price = max(0, price - 4)

    return max(0, price)


def _is_red_description_item(offer: ShopOffer) -> bool:
    text = f"{offer.name} {offer.id}".lower()
    return "red" in text


def net_sell_proceeds(candidate: SellCandidate, loadout: Loadout) -> int:
    """Cash change from selling (negative when sell costs money)."""
    if candidate.costs_money_to_sell:
        return -max(0, candidate.sell_cost)

    value = max(0, candidate.sell_value)
    if _has_stamp(loadout, "receipt"):
        return value
    if (candidate.id or "").lower() == "nest_egg":
        return 0
    return value


def restock_cost(loadout: Loadout, shop: ShopState | None) -> int:
    """Next shop restock price in dollars."""
    if shop is not None and shop.restock_cost > 0:
        base = shop.restock_cost
    else:
        restocks = _int_extra(loadout, "shop_restock_count", 0)
        base = 1 + restocks

    if _has_stamp(loadout, "fried_shrimp"):
        base = max(0, base - 1)

    return max(0, base)


def can_afford(price: int, loadout: Loadout) -> bool:
    return loadout.money >= price


def sticker_slots_available(loadout: Loadout) -> int:
    max_slots = 5
    locked = _int_extra(loadout, "sticker_slots_locked", 0)
    return max(0, max_slots - locked - len(loadout.stickers))


def stamp_slots_available(loadout: Loadout) -> int:
    max_slots = 5
    locked = _int_extra(loadout, "stamp_slots_locked", 0)
    return max(0, max_slots - locked - len(loadout.stamps))


def can_add_offer(offer: ShopOffer, loadout: Loadout) -> bool:
    if offer.slot == "sticker":
        if is_upgrade_offer(offer, loadout):
            return True
        return sticker_slots_available(loadout) > 0
    if offer.slot == "stamp":
        return stamp_slots_available(loadout) > 0
    return True


def free_item_applies(shop: ShopState | None, loadout: Loadout) -> bool:
    if shop is not None and shop.free_item_available:
        return True
    if shop is not None and shop.angel_investment_available:
        return True
    return False


def money_to_word_equiv(dollars: int, *, word_per_dollar: float = 50.0) -> float:
    return float(dollars) * word_per_dollar
