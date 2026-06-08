"""Resolve AdviceData into buy/freeze/sell/upgrade/restock/leave actions."""

from __future__ import annotations

from cursed_words_solver.game_shop.types import (
    AdviceData,
    BUILD_TAG_LABELS,
    FUNCTION_LABELS,
    GameShopItem,
    ItemFunction,
    ItemTag,
    ShopAdviceContext,
)
from cursed_words_solver.game_shop.types import player_should_restock


def resolve_advice_actions(
    advice: AdviceData,
    ctx: ShopAdviceContext,
    *,
    free_item_active: bool,
) -> AdviceData:
    """Apply affordability, slot-full, and upgrade rules (port of AdviceData.GetQuip)."""
    if advice.specific_reason and (
        advice.should_buy or advice.should_freeze
    ):
        return advice

    if advice.recommended_tiles:
        affordable = [
            t for t in advice.recommended_tiles if t.price <= ctx.money and not t.sold
        ]
        if affordable:
            advice.recommended_tiles = affordable
            advice.should_buy = True
        return advice

    if not advice.recommended_items:
        if player_should_restock(ctx.money, ctx.restock_cost) and not free_item_active:
            advice.should_restock = True
            advice.should_leave = False
        elif not free_item_active:
            advice.should_restock = False
            advice.should_leave = True
        return advice

    affordable = [i for i in advice.recommended_items if i.price <= ctx.money]
    if affordable:
        advice.recommended_items = affordable
        advice.should_buy = True
    else:
        advice.should_freeze = True

    inventory_ids = {(i.id or "").lower() for i in ctx.inventory}

    if ctx.sticker_count >= 5 and ctx.stamp_count >= 5:
        advice.should_sell = True
    elif ctx.sticker_count >= 5:
        non_stickers = [i for i in advice.recommended_items if i.slot != "sticker"]
        if non_stickers:
            advice.recommended_items = non_stickers
        else:
            advice.should_sell = True
    elif ctx.stamp_count >= 5:
        non_stamps = [i for i in advice.recommended_items if i.slot != "stamp"]
        if non_stamps:
            advice.recommended_items = non_stamps
        else:
            advice.should_sell = True

    owned_matches = [
        i
        for i in advice.recommended_items
        if (i.id or "").lower() in inventory_ids
    ]
    if owned_matches:
        advice.recommended_items = owned_matches
        advice.should_upgrade = True
        advice.should_sell = False

    return advice


def advice_summary(
    advice: AdviceData,
    *,
    free_item_active: bool,
    money: int | None = None,
) -> str:
    if advice.specific_reason:
        return advice.specific_reason

    build_label = BUILD_TAG_LABELS.get(advice.build, advice.build.value)
    func_label = FUNCTION_LABELS.get(
        advice.function_fulfilled, advice.function_fulfilled.value
    )

    if advice.recommended_tiles and advice.should_buy:
        tile = advice.recommended_tiles[0]
        desc = _tile_description(tile)
        return f"Buy {desc} tile for {build_label} build"

    if advice.recommended_items:
        names = ", ".join(i.name for i in advice.recommended_items[:2])
        if advice.should_freeze and advice.should_upgrade:
            action = "Freeze to upgrade"
        elif advice.should_freeze:
            action = "Freeze"
        elif advice.should_upgrade:
            action = "Upgrade"
        elif advice.should_buy:
            action = "Buy"
        elif advice.should_sell:
            action = "Sell then buy"
        else:
            action = "Consider"
        suffix = f" ({build_label} {func_label})"
        if advice.is_generic:
            suffix = " (works in any build)"
        summary = f"{action}: {names}{suffix}"
        if advice.should_freeze and money is not None:
            top = advice.recommended_items[0]
            summary += f" (${top.price}, you have ${money})"
        return summary

    if advice.should_restock:
        return "Restock the shop — nothing useful right now"
    if advice.should_leave:
        if free_item_active:
            return "Take the free item if you want it, otherwise leave"
        return f"Leave shop — no good {build_label} {func_label} offers"
    if advice.build == ItemTag.NO_BUILD:
        return "No clear build direction — browse or leave"
    return f"Looking for {build_label} {func_label}"


def _tile_description(tile: object) -> str:
    color = getattr(tile, "color", "") or "colourless"
    curse = getattr(tile, "curse", "") or "letter"
    letter = getattr(tile, "letter", "") or "?"
    if curse not in {"", "letter", "colorless"}:
        return f"{color} {curse}"
    if letter and letter != "?":
        return f"{color} {letter.upper()}"
    return color
