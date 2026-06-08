"""Shop advice using the in-game ShopRecommendation engine (Python port)."""

from __future__ import annotations

from cursed_words_solver.game_shop.advice_resolve import advice_summary
from cursed_words_solver.game_shop.recommendation import compute_shop_advice
from cursed_words_solver.game_shop.types import BUILD_TAG_LABELS, AdviceData
from cursed_words_solver.models import (
    ActionRecommendation,
    Loadout,
    RankedAction,
    ShopAdvice,
    ShopState,
)


def _primary_action(advice: AdviceData) -> str:
    if advice.should_buy and advice.recommended_tiles:
        return "buy_tile"
    if advice.should_upgrade:
        return "upgrade"
    if advice.should_buy:
        return "buy"
    if advice.should_freeze:
        return "freeze"
    if advice.should_sell:
        return "sell"
    if advice.should_restock:
        return "restock"
    if advice.should_leave:
        return "leave"
    return "browse"


def _action_label(item_name: str, action: str) -> str:
    if action == "upgrade":
        return f"Upgrade {item_name}"
    if action == "freeze":
        return f"Freeze {item_name}"
    if action == "sell":
        return f"Sell → buy {item_name}"
    return f"Buy {item_name}"


def _tile_label(tile: object) -> str:
    color = getattr(tile, "color", "") or "tile"
    letter = getattr(tile, "letter", "") or ""
    curse = getattr(tile, "curse", "") or ""
    if curse not in {"", "letter", "colorless"}:
        return f"{color} {curse} tile"
    if letter and letter != "?":
        return f"{color} {letter.upper()} tile"
    return f"{color} tile"


def advice_data_to_shop_advice(advice: AdviceData, shop: ShopState) -> ShopAdvice:
    action = _primary_action(advice)
    build = BUILD_TAG_LABELS.get(advice.build, advice.build.value)
    function = advice.function_fulfilled.value if advice.function_fulfilled else ""
    reason = advice_summary(advice, free_item_active=advice.is_free_item)
    result = ShopAdvice(
        primary_action=action,
        build=build,
        function=function,
        reason=reason,
    )

    if advice.should_buy and advice.recommended_tiles:
        for tile in advice.recommended_tiles[:3]:
            result.buys.append(
                RankedAction(
                    action="buy_tile",
                    label=_tile_label(tile),
                    net_value=0.0,
                    money_delta=-tile.price,
                    reason=reason,
                    offer_index=tile.index,
                    kind="tile",
                )
            )
    elif advice.recommended_items:
        for item in advice.recommended_items[:3]:
            act = "upgrade" if advice.should_upgrade else (
                "freeze" if advice.should_freeze else "buy"
            )
            result.buys.append(
                RankedAction(
                    action=act,
                    label=_action_label(item.name, act),
                    net_value=0.0,
                    money_delta=-item.price if advice.should_buy else 0,
                    reason=reason,
                    offer_index=item.index,
                    kind=item.slot,
                )
            )
        if advice.should_sell:
            result.sells.append(
                RankedAction(
                    action="sell",
                    label="Sell a slot to make room",
                    net_value=0.0,
                    reason=reason,
                )
            )
    elif advice.should_freeze and advice.recommended_items:
        for item in advice.recommended_items[:3]:
            result.freezes.append(
                RankedAction(
                    action="freeze",
                    label=f"Freeze {item.name}",
                    net_value=0.0,
                    reason=reason,
                    offer_index=item.index,
                    kind=item.slot,
                )
            )

    if advice.should_restock:
        cost = max(0, shop.restock_cost)
        result.restock = ActionRecommendation(
            action="yes",
            label=f"Restock (${cost})",
            reason=reason,
        )
    elif advice.should_leave:
        result.leave_shop = ActionRecommendation(
            action="leave",
            label="Leave shop",
            reason=reason,
        )

    if not advice.recommended_items and not advice.recommended_tiles:
        if advice.should_restock:
            pass
        elif advice.should_leave:
            pass
        elif advice.build.value != "NoBuild":
            result.warnings.append(f"Build focus: {build}")

    return result


def run_shop_advisor(
    loadout: Loadout,
    shop: ShopState,
    sell_candidates: list | None = None,
    dictionary=None,
    *,
    config=None,
    on_progress=None,
) -> ShopAdvice:
    del sell_candidates, dictionary, config
    if on_progress:
        on_progress("Computing game shop advice...")
    advice = compute_shop_advice(loadout, shop)
    return advice_data_to_shop_advice(advice, shop)


def format_shop_advice_text(advice: ShopAdvice) -> str:
    lines: list[str] = ["Shop advice (game build logic):"]
    if advice.reason:
        lines.append(f"  {advice.reason}")

    if advice.leave_shop:
        lines.append(f"  → {advice.leave_shop.label}: {advice.leave_shop.reason}")

    if advice.buys:
        lines.append("  Actions:")
        for item in advice.buys[:3]:
            price = f" (${-item.money_delta})" if item.money_delta else ""
            lines.append(f"    {item.label}{price}")
    elif advice.restock:
        lines.append(f"  → {advice.restock.label}")
    elif advice.leave_shop:
        pass
    else:
        lines.append("  No specific buy — browse or leave")

    if advice.freezes:
        for item in advice.freezes[:2]:
            lines.append(f"    Freeze: {item.label}")

    if advice.restock and advice.buys:
        lines.append(f"  Restock: {advice.restock.label}")

    for warn in advice.warnings:
        lines.append(f"  Note: {warn}")
    return "\n".join(lines)


def format_shop_advice_html(advice: ShopAdvice) -> str:
    parts: list[str] = [
        "<span style='font-size:14px;font-weight:bold;color:#0cf'>"
        "Shop advice</span>"
    ]
    if advice.build:
        parts.append(
            f"<br><span style='font-size:11px;color:#888'>"
            f"Build: {advice.build}</span>"
        )

    if advice.buys:
        top = advice.buys[0]
        price = f" (${-top.money_delta})" if top.money_delta else ""
        parts.append(
            f"<br><span style='font-size:13px;color:#fff;font-weight:bold'>"
            f"{top.label}{price}</span>"
        )
    elif advice.restock:
        parts.append(
            f"<br><span style='font-size:13px;color:#fa0;font-weight:bold'>"
            f"{advice.restock.label}</span>"
        )
    elif advice.leave_shop:
        parts.append(
            f"<br><span style='font-size:13px;color:#fa0;font-weight:bold'>"
            f"{advice.leave_shop.label}</span>"
        )

    if advice.reason:
        parts.append(
            f"<br><span style='font-size:11px;color:#8cf'>"
            f"{advice.reason}</span>"
        )

    if len(advice.buys) > 1:
        alt = ", ".join(b.label for b in advice.buys[1:3])
        parts.append(
            f"<br><span style='font-size:11px;color:#aaa'>Also: {alt}</span>"
        )

    if advice.restock and advice.buys:
        parts.append(
            f"<br><span style='font-size:11px;color:#8cf'>"
            f"Or {advice.restock.label.lower()}</span>"
        )

    for warn in advice.warnings[:2]:
        parts.append(
            f"<br><span style='font-size:11px;color:#fa0'>{warn}</span>"
        )
    return "".join(parts)
