"""Item-specific high-priority shop advice overrides (Golden Scales, Young Cardinal)."""

from __future__ import annotations

from cursed_words_solver.game_shop.types import (
    AdviceData,
    BuildData,
    GameShopItem,
    ItemTag,
    ShopAdviceContext,
)


def high_priority_utility_advice(
    shop_item: GameShopItem,
    ctx: ShopAdviceContext,
    builds: list[BuildData],
) -> AdviceData | None:
    slug = (shop_item.id or "").lower()
    if slug == "golden_scales":
        return _golden_scales_advice(shop_item, ctx)
    if slug in {"young_cardinal", "northern_cardinal", "youngcardinal"}:
        return _northern_cardinal_advice(shop_item, ctx, builds)
    return None


def _golden_scales_advice(item: GameShopItem, ctx: ShopAdviceContext) -> AdviceData | None:
    if ctx.sticker_count > 2:
        return None
    advice = AdviceData(
        build=ItemTag.NO_BUILD,
        recommended_items=[item],
        is_generic=True,
    )
    if ctx.money >= item.price:
        advice.should_buy = True
        advice.specific_reason = (
            f"You could grab {item.name} to make cash off empty Sticker slots"
        )
        return advice
    advice.should_freeze = True
    advice.specific_reason = (
        f"{item.name} could be worth freezing for early-game money"
    )
    return advice


def _northern_cardinal_advice(
    item: GameShopItem,
    ctx: ShopAdviceContext,
    builds: list[BuildData],
) -> AdviceData | None:
    if not any(b.build_tag == ItemTag.RED_BUILD for b in builds):
        return None
    advice = AdviceData(
        build=ItemTag.RED_BUILD,
        recommended_items=[item],
        is_generic=False,
    )
    if ctx.money >= item.price:
        advice.should_buy = True
        advice.specific_reason = (
            f"{item.name} is helpful on a RED run"
        )
        return advice
    advice.should_freeze = True
    advice.specific_reason = f"{item.name} could be worth freezing on a RED run"
    return advice
