"""Shop run context, money reserve, leave-shop, and freeze advice."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

from cursed_words_solver.models import (
    ActionRecommendation,
    Loadout,
    RankedAction,
    ShopOffer,
    ShopState,
)
from cursed_words_solver.rules.boss_effects import boss_area_number
from cursed_words_solver.shop_economy import (
    effective_purchase_price,
    is_upgrade_offer,
    money_to_word_equiv,
    owned_sticker_level,
)
_DEFER_LIFT_MIN = 40.0
_NEXT_SHOP_LABEL = {
    "ShopZero": "ShopOne",
    "ShopOne": "ShopTwo",
    "ShopTwo": "next stage",
}


@dataclass
class ShopRunContext:
    shop_node: str
    area: int
    money: int
    shops_remaining: int
    money_reserve: int
    min_net: float
    shop_node_known: bool
    reserve_per_future_shop: int
    marginal_net_per_remaining_shop: float
    word_per_dollar: float = 50.0

    def defer_lift_min(self, *, upgrade: bool = False) -> float:
        base = _DEFER_LIFT_MIN + max(0, self.area - 1) * 2
        if upgrade:
            return max(10.0, base / 2.0)
        return base

    def marginal_hurdle(self, *, upgrade: bool = False) -> float:
        if self.shops_remaining <= 0:
            return 0.0
        hurdle = self.shops_remaining * self.marginal_net_per_remaining_shop
        if upgrade:
            return max(0.0, math.ceil(hurdle / 2.0))
        return hurdle


def _shops_remaining_from_node(shop_node: str) -> int | None:
    mapping = {
        "ShopZero": 2,
        "ShopOne": 1,
        "ShopTwo": 0,
        "MegShop": 0,
    }
    if shop_node in mapping:
        return mapping[shop_node]
    return None


def build_shop_run_context(
    loadout: Loadout,
    *,
    reserve_per_future_shop: int = 0,
    marginal_net_per_remaining_shop: float = 15.0,
    word_per_dollar: float = 50.0,
) -> ShopRunContext:
    extras = loadout.extras or {}
    shop_node = str(extras.get("shop_node") or "").strip()
    shops_remaining = _shops_remaining_from_node(shop_node)
    shop_node_known = shops_remaining is not None
    if shops_remaining is None:
        shops_remaining = 1

    area = boss_area_number(loadout)
    per_shop = reserve_per_future_shop if reserve_per_future_shop > 0 else 8 + area
    money_reserve = shops_remaining * per_shop
    min_net = (
        0.0
        if shops_remaining <= 0
        else shops_remaining * marginal_net_per_remaining_shop
    )

    return ShopRunContext(
        shop_node=shop_node,
        area=area,
        money=loadout.money,
        shops_remaining=shops_remaining,
        money_reserve=money_reserve,
        min_net=min_net,
        shop_node_known=shop_node_known,
        reserve_per_future_shop=per_shop,
        marginal_net_per_remaining_shop=marginal_net_per_remaining_shop,
        word_per_dollar=word_per_dollar,
    )


def shop_node_warning(ctx: ShopRunContext) -> str | None:
    if ctx.shop_node_known:
        return None
    return "shop_node unknown — conservative money reserve"


def format_reserve_note(ctx: ShopRunContext) -> str:
    if ctx.shops_remaining <= 0:
        return "Last shop this stage — spend freely on clear winners"
    node = ctx.shop_node or "shop"
    return (
        f"Save ~${ctx.money_reserve} for {ctx.shops_remaining} later shop"
        f"{'s' if ctx.shops_remaining != 1 else ''} ({node})"
    )


def passes_marginal(
    net: float,
    ctx: ShopRunContext,
    *,
    upgrade: bool = False,
) -> bool:
    return net > ctx.marginal_hurdle(upgrade=upgrade)


def passes_reserve(
    price: int,
    money: int,
    ctx: ShopRunContext,
    *,
    net: float = 0.0,
    upgrade: bool = False,
    free: bool = False,
) -> bool:
    if free or price <= 0:
        return True
    if money - price >= ctx.money_reserve:
        return True
    if upgrade and ctx.shops_remaining > 0:
        hurdle = ctx.marginal_hurdle(upgrade=True)
        if hurdle > 0 and net >= 2.0 * hurdle:
            return True
    return False


def buy_blocked_reason(
    price: int,
    money: int,
    net: float,
    ctx: ShopRunContext,
    *,
    upgrade: bool = False,
    shop_marked_free: bool = False,
) -> str | None:
    # Shop-slot free items skip cash reserve but still need a strong net early run.
    if shop_marked_free:
        if ctx.shops_remaining > 0 and not passes_marginal(net, ctx, upgrade=upgrade):
            return "marginal"
        return None
    if price > money:
        return "unaffordable"
    if price > 0 and not passes_reserve(
        price, money, ctx, net=net, upgrade=upgrade, free=False
    ):
        return "reserve"
    if not passes_marginal(net, ctx, upgrade=upgrade):
        return "marginal"
    return None


def purchase_action_label(offer: ShopOffer, loadout: Loadout) -> str:
    if offer.slot == "tile" and offer.letter:
        return f"Buy {offer.color or 'tile'} {offer.letter}"
    if is_upgrade_offer(offer, loadout):
        if offer.foil and max(1, offer.level or 1) <= owned_sticker_level(
            loadout, offer.id
        ):
            return f"Foil {offer.name}"
        return f"Upgrade {offer.name} to L{offer.level}"
    return f"Buy {offer.name}"


def freeze_action_label(offer: ShopOffer, loadout: Loadout) -> str:
    if is_upgrade_offer(offer, loadout):
        return f"Freeze {offer.name} L{offer.level} upgrade"
    return f"Freeze {offer.name}"


def _items_cannot_freeze(loadout: Loadout) -> bool:
    if any((s.id or "").lower() == "erupting_volcano" for s in loadout.stickers):
        return True
    return False


def _frozen_slot_capacity(shop: ShopState) -> int:
    frozen = sum(
        1
        for o in shop.offers
        if o.slot in {"sticker", "stamp"} and o.frozen and not o.sold
    )
    return max(0, 6 - frozen)


def _next_shop_label(ctx: ShopRunContext) -> str:
    if ctx.shop_node in _NEXT_SHOP_LABEL:
        return _NEXT_SHOP_LABEL[ctx.shop_node]
    if ctx.shops_remaining == 2:
        return "ShopOne"
    if ctx.shops_remaining == 1:
        return "ShopTwo"
    return "next shop"


def _chart_bonus(loadout: Loadout, ctx: ShopRunContext) -> float:
    if ctx.shops_remaining <= 0:
        return 0.0
    if not any((s.id or "").lower() == "downward_trending_chart" for s in loadout.stamps):
        return 0.0
    return 2.0 * ctx.shops_remaining * ctx.word_per_dollar


def _synergy_bonus(loadout: Loadout) -> float:
    bonus = 0.0
    if any((s.id or "").lower() == "snowman" for s in loadout.stickers):
        bonus += 15.0
    if any((s.id or "").lower() == "shaved_ice" for s in loadout.stamps):
        bonus += 15.0
    return bonus


def evaluate_freeze_candidates(
    loadout: Loadout,
    shop: ShopState,
    offers: list[ShopOffer],
    *,
    ctx: ShopRunContext,
    buy_lifts: dict[int, float],
    buy_nets: dict[int, float],
    approved_buy_indices: set[int],
    use_free: bool,
    is_duplicate_buy: Callable[[ShopOffer, Loadout], bool],
) -> list[RankedAction]:
    if _items_cannot_freeze(loadout):
        return []

    capacity = _frozen_slot_capacity(shop)
    if capacity <= 0:
        return []

    freezes: list[tuple[float, RankedAction]] = []
    chart = _chart_bonus(loadout, ctx)
    synergy = _synergy_bonus(loadout)
    next_shop = _next_shop_label(ctx)

    for offer in offers:
        if offer.slot not in {"sticker", "stamp"}:
            continue
        if offer.sold or offer.frozen:
            continue
        if is_duplicate_buy(offer, loadout):
            continue

        price = effective_purchase_price(offer, loadout, shop, use_free_item=False)
        lift = buy_lifts.get(offer.index, 0.0)
        net = buy_nets.get(offer.index, 0.0)
        upgrade = is_upgrade_offer(offer, loadout)

        if offer.index in approved_buy_indices:
            continue

        blocked = buy_blocked_reason(
            price,
            loadout.money,
            net,
            ctx,
            upgrade=upgrade,
            shop_marked_free=offer.free,
        )
        if blocked is None:
            continue

        if lift < ctx.defer_lift_min(upgrade=upgrade):
            continue

        if ctx.shops_remaining <= 0 and blocked != "unaffordable":
            continue

        freeze_value = lift + chart + synergy
        reason_parts: list[str] = []
        if blocked == "unaffordable":
            reason_parts.append(f"Can't afford ${price}")
        elif blocked == "reserve":
            reason_parts.append(
                f"Good +{lift:,.0f} lift but save ${ctx.money_reserve} reserve"
            )
        else:
            reason_parts.append(f"+{lift:,.0f} lift — not urgent this shop")

        reason_parts.append(f"freeze for {next_shop}")
        if chart > 0:
            reason_parts.append("Downward Trending Chart: $2 cheaper each shop")

        freezes.append(
            (
                freeze_value,
                RankedAction(
                    action="freeze",
                    label=freeze_action_label(offer, loadout),
                    net_value=freeze_value,
                    score_lift=lift,
                    money_delta=0,
                    reason=" — ".join(reason_parts),
                    offer_index=offer.index,
                    kind=offer.slot,
                ),
            )
        )

    freezes.sort(key=lambda pair: pair[0], reverse=True)
    return [action for _score, action in freezes[: min(3, capacity)]]


def filter_ranked_buys(
    buys: list[RankedAction],
    loadout: Loadout,
    shop: ShopState,
    offers_by_index: dict[int, ShopOffer],
    ctx: ShopRunContext,
    *,
    use_free: bool,
) -> tuple[list[RankedAction], list[RankedAction]]:
    approved: list[RankedAction] = []
    blocked: list[RankedAction] = []

    for action in buys:
        idx = action.offer_index if action.offer_index is not None else -1
        offer = offers_by_index.get(idx)
        if offer is None:
            continue
        price = effective_purchase_price(offer, loadout, shop, use_free_item=False)
        upgrade = is_upgrade_offer(offer, loadout)
        paid_net = action.score_lift - money_to_word_equiv(
            price, word_per_dollar=ctx.word_per_dollar
        )
        if buy_blocked_reason(
            price,
            loadout.money,
            paid_net,
            ctx,
            upgrade=upgrade,
            shop_marked_free=offer.free,
        ):
            blocked.append(action)
        else:
            approved.append(action)

    def sort_key(action: RankedAction) -> tuple:
        idx = action.offer_index if action.offer_index is not None else -1
        offer = offers_by_index.get(idx)
        upgrade = bool(offer and is_upgrade_offer(offer, loadout))
        return (-action.net_value, 0 if upgrade else 1)

    approved.sort(key=sort_key)
    return approved, blocked


def filter_sell_swaps(
    sells: list[RankedAction],
    loadout: Loadout,
    shop: ShopState,
    offers_by_index: dict[int, ShopOffer],
    ctx: ShopRunContext,
    *,
    use_free: bool,
) -> list[RankedAction]:
    if ctx.shops_remaining <= 0:
        return sells

    filtered: list[RankedAction] = []
    for action in sells:
        idx = action.offer_index if action.offer_index is not None else -1
        offer = offers_by_index.get(idx)
        if offer is None:
            filtered.append(action)
            continue
        price = effective_purchase_price(offer, loadout, shop, use_free_item=False)
        cash = action.money_delta
        money_after = loadout.money + cash
        if money_after - price >= ctx.money_reserve:
            filtered.append(action)
    return filtered


def should_leave_shop(
    buys: list[RankedAction],
    sells: list[RankedAction],
    restock: ActionRecommendation | None,
    *,
    ctx: ShopRunContext,
    blocked_buys: list[RankedAction] | None = None,
    freezes: list[RankedAction] | None = None,
) -> tuple[bool, str]:
    actionable_buys = bool(buys)
    actionable_sells = any(s.net_value > 0 for s in sells)
    actionable_restock = bool(
        restock and restock.action == "yes" and restock.net_value > 0
    )
    if actionable_buys or actionable_sells or actionable_restock:
        return False, ""

    parts: list[str] = [format_reserve_note(ctx)]
    if blocked_buys:
        best = max(blocked_buys, key=lambda b: b.net_value, default=None)
        if best and best.net_value > 0:
            parts.append(
                f"Best buy {best.net_value:+,.0f} WORD — too marginal or would break reserve"
            )
    if freezes:
        labels = ", ".join(f.label.replace("Freeze ", "") for f in freezes[:2])
        parts.append(f"Freeze {labels} first" if labels else "")
    return True, " — ".join(p for p in parts if p)


def build_leave_shop_recommendation(reason: str) -> ActionRecommendation:
    return ActionRecommendation(
        action="leave",
        label="Leave shop",
        net_value=0.0,
        reason=reason,
    )
