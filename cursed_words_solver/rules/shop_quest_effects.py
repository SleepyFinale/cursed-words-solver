"""Shop-only quest constraints (Shelf Life, Embargo, slot hides, etc.)."""

from __future__ import annotations

from dataclasses import dataclass, replace

from cursed_words_solver.game_shop.metadata import resolve_game_class
from cursed_words_solver.models import Loadout, ShopOffer, ShopState
from cursed_words_solver.rules.quest_effects import (
    active_quest_game_class,
    active_quest_name,
    active_quest_slug,
    load_quests_catalog,
)


@dataclass(frozen=True)
class ShopQuestConstraints:
    block_restock: bool = False
    block_sell: bool = False
    sticker_shop_enabled: bool = True
    stamp_shop_enabled: bool = True
    secret_santa: bool = False
    embargoed_game_classes: frozenset[str] = frozenset()
    zero_encounter_rewards: bool = False


def _parse_type_list(raw: str) -> frozenset[str]:
    return frozenset(s.strip() for s in (raw or "").split(",") if s.strip())


def embargoed_game_classes(loadout: Loadout | None) -> frozenset[str]:
    if loadout is None:
        return frozenset()
    extras = loadout.extras or {}
    classes: set[str] = set()
    classes.update(_parse_type_list(str(extras.get("embargoed_item_types", ""))))
    for slug in _parse_type_list(str(extras.get("embargoed_item_slugs", ""))):
        classes.add(resolve_game_class(slug))
    return frozenset(classes)


def offer_game_class(offer: ShopOffer) -> str:
    oid = (offer.id or "").strip()
    if not oid:
        return ""
    return resolve_game_class(oid)


def offer_is_embargoed(offer: ShopOffer, embargo_classes: frozenset[str]) -> bool:
    if not embargo_classes or offer.slot == "tile":
        return False
    gc = offer_game_class(offer)
    return bool(gc and gc in embargo_classes)


def shop_quest_constraints(loadout: Loadout | None) -> ShopQuestConstraints:
    if loadout is None:
        return ShopQuestConstraints()
    game_class = active_quest_game_class(loadout)
    if not game_class:
        return ShopQuestConstraints()
    slug = active_quest_slug(loadout)
    row = load_quests_catalog().get("quests", {}).get(slug) or {}
    if str(row.get("effect_class") or "") != "shop_only" and game_class not in (
        "DecisionParalysis",
        "SecretSanta",
        "Antiphilatelist",
        "Masochist",
        "InTheBeginning",
        "DoNotPassGo",
        "Embargo",
    ):
        return ShopQuestConstraints()

    sticker_shop = True
    stamp_shop = True
    if game_class in ("Masochist", "InTheBeginning"):
        sticker_shop = False
    if game_class in ("Antiphilatelist", "InTheBeginning"):
        stamp_shop = False

    return ShopQuestConstraints(
        block_restock=game_class == "DecisionParalysis",
        block_sell=game_class == "Embargo",
        sticker_shop_enabled=sticker_shop,
        stamp_shop_enabled=stamp_shop,
        secret_santa=game_class == "SecretSanta",
        embargoed_game_classes=embargoed_game_classes(loadout)
        if game_class == "Embargo"
        else frozenset(),
        zero_encounter_rewards=game_class == "DoNotPassGo",
    )


def filter_shop_offers(loadout: Loadout, shop: ShopState) -> ShopState:
    """Return shop copy with quest-disabled / embargoed offers removed."""
    quest = shop_quest_constraints(loadout)
    filtered: list[ShopOffer] = []
    for offer in shop.offers:
        if offer.sold:
            continue
        if offer.slot == "sticker" and not quest.sticker_shop_enabled:
            continue
        if offer.slot == "stamp" and not quest.stamp_shop_enabled:
            continue
        if offer_is_embargoed(offer, quest.embargoed_game_classes):
            continue
        filtered.append(offer)
    return replace(shop, offers=filtered)


def shop_quest_warnings(loadout: Loadout | None, shop: ShopState | None = None) -> list[str]:
    if loadout is None:
        return []
    quest = shop_quest_constraints(loadout)
    name = active_quest_name(loadout)
    warnings: list[str] = []
    if name:
        warnings.append(f"Quest: {name}")
    if quest.block_restock:
        warnings.append(
            "Shelf Life: manual shop restock is disabled; bought slots auto-refill."
        )
    if quest.secret_santa:
        warnings.append(
            "Secret Santa: item names are hidden in-game; advice uses exported data."
        )
    if quest.block_sell:
        warnings.append(
            "Embargo: items cannot be sold; inventory is refunded after each boss."
        )
    if quest.embargoed_game_classes:
        warnings.append(
            f"Embargo: {len(quest.embargoed_game_classes)} item type(s) excluded from shop pool."
        )
    if not quest.sticker_shop_enabled and not quest.stamp_shop_enabled:
        warnings.append("In The Beginning: only tiles are sold in this shop.")
    elif not quest.sticker_shop_enabled:
        warnings.append("Masochist: sticker slots are hidden — stamps/tiles only.")
    elif not quest.stamp_shop_enabled:
        warnings.append("Antiphilatelist: stamp slots are hidden — stickers/tiles only.")
    if quest.zero_encounter_rewards and shop is not None and shop.angel_investment_available:
        warnings.append(
            "Do Not Pass Go: encounter rewards are $0; angel investment (Future Funds) available."
        )
    elif quest.zero_encounter_rewards:
        warnings.append("Do Not Pass Go: encounter and boss rewards pay $0.")
    return warnings
