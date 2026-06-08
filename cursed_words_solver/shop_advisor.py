"""Orchestrate shop advice: buys, sells, restock, freeze, and leave shop."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path

from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.models import (
    Loadout,
    RankedAction,
    ShopAdvice,
    ShopOffer,
    ShopState,
)
from cursed_words_solver.representative_boards import select_representative_boards
from cursed_words_solver.shop_boards import (
    prepare_boards_for_shop_sim,
    prepare_loadout_for_shop_sim,
)
from cursed_words_solver.shop_economy import (
    can_add_offer,
    effective_purchase_price,
    free_item_applies,
    money_to_word_equiv,
    net_sell_proceeds,
)
from cursed_words_solver.shop_reserve import (
    build_leave_shop_recommendation,
    build_shop_run_context,
    evaluate_freeze_candidates,
    filter_ranked_buys,
    filter_sell_swaps,
    format_reserve_note,
    purchase_action_label,
    shop_node_warning,
    should_leave_shop,
)
from cursed_words_solver.shop_simulation import (
    SimulationConfig,
    SimulationContext,
    evaluate_loadout_value,
    evaluate_purchase,
    evaluate_restock_ev,
    evaluate_sell,
    evaluate_sell_swaps,
    evaluate_special_actions,
)

_CATALOG_PATH = Path(__file__).resolve().parents[1] / "data" / "wiki" / "stickers.json"
_SWAP_MARGIN_WORD = 50.0


def _catalog_stamp_ids() -> list[str]:
    if not _CATALOG_PATH.is_file():
        return []
    try:
        data = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
        stamps = data.get("stamps") or {}
        return list(stamps.keys())
    except (OSError, json.JSONDecodeError):
        return []


def _owned_item_level(loadout: Loadout, offer: ShopOffer) -> int:
    oid = (offer.id or "").lower()
    if offer.slot == "sticker":
        for item in loadout.stickers:
            if (item.id or "").lower() == oid:
                return max(1, item.level)
    elif offer.slot == "stamp":
        for item in loadout.stamps:
            if (item.id or "").lower() == oid:
                return max(1, item.level)
    return 0


def _is_duplicate_buy(offer: ShopOffer, loadout: Loadout) -> bool:
    """Skip buying another copy unless the shop offer is a higher-level upgrade."""
    if offer.slot not in {"sticker", "stamp"}:
        return False
    owned_level = _owned_item_level(loadout, offer)
    if owned_level <= 0:
        return False
    return max(1, offer.level or 1) <= owned_level


def run_shop_advisor(
    loadout: Loadout,
    shop: ShopState,
    sell_candidates: list,
    dictionary: WordDictionary,
    *,
    config: SimulationConfig | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> ShopAdvice:
    config = config or SimulationConfig()
    advice = ShopAdvice()
    started = time.monotonic()

    def progress(msg: str) -> None:
        if on_progress is not None:
            on_progress(msg)

    loadout = prepare_loadout_for_shop_sim(loadout)
    raw_boards = select_representative_boards(loadout, max_boards=config.max_boards)
    boards = prepare_boards_for_shop_sim(raw_boards) if raw_boards else []
    if not boards:
        advice.warnings.append("No representative boards found for simulation")

    ctx = SimulationContext.create(boards, dictionary, config)
    baseline = evaluate_loadout_value(ctx, loadout) if boards else 0.0
    ctx.baseline_value = baseline

    run_ctx = build_shop_run_context(
        loadout,
        reserve_per_future_shop=config.shop_reserve_per_future_shop,
        marginal_net_per_remaining_shop=config.shop_marginal_net_per_remaining_shop,
        word_per_dollar=config.word_per_dollar,
    )
    node_warn = shop_node_warning(run_ctx)
    if node_warn:
        advice.warnings.append(node_warn)

    use_free = free_item_applies(shop, loadout)
    buy_nets: dict[int, float] = {}
    buy_lifts: dict[int, float] = {}
    buys: list[RankedAction] = []
    offers_by_index = {o.index: o for o in shop.offers}

    eval_offers = [
        o
        for o in shop.offers
        if not o.sold
        and not _is_duplicate_buy(o, loadout)
        and can_add_offer(o, loadout)
    ]
    total_purchases = len(eval_offers)

    for idx, offer in enumerate(eval_offers, start=1):
        if ctx.is_expired():
            advice.warnings.append(
                "Shop simulation budget exhausted — rankings may be incomplete"
            )
            break
        progress(f"Evaluating purchases ({idx}/{total_purchases})...")
        price = effective_purchase_price(offer, loadout, shop, use_free_item=use_free)
        lift, net, reason = evaluate_purchase(
            offer,
            loadout,
            shop,
            boards,
            dictionary,
            config=config,
            use_free=use_free,
            ctx=ctx,
            baseline=baseline,
        )
        buy_nets[offer.index] = net
        buy_lifts[offer.index] = lift
        buys.append(
            RankedAction(
                action="buy",
                label=purchase_action_label(offer, loadout),
                net_value=net,
                score_lift=lift,
                money_delta=-price,
                reason=reason,
                offer_index=offer.index,
                kind=offer.slot,
            )
        )

    buys.sort(key=lambda a: (-a.net_value, -a.money_delta))

    hyena = str((loadout.extras or {}).get("hyena_blocked", "")).lower() in {
        "1",
        "true",
        "yes",
    }

    sells: list[RankedAction] = []
    if hyena:
        total_sells = len(sell_candidates)
        for idx, candidate in enumerate(sell_candidates, start=1):
            if ctx.is_expired():
                if "Shop simulation budget exhausted" not in advice.warnings:
                    advice.warnings.append(
                        "Shop simulation budget exhausted — rankings may be incomplete"
                    )
                break
            progress(f"Evaluating sells ({idx}/{total_sells})...")
            loss, net, reason = evaluate_sell(
                candidate,
                loadout,
                boards,
                dictionary,
                config=config,
                ctx=ctx,
                baseline=baseline,
            )
            cash = net_sell_proceeds(candidate, loadout)
            sells.append(
                RankedAction(
                    action="sell",
                    label=f"Sell {candidate.name}",
                    net_value=net,
                    score_lift=-loss,
                    money_delta=cash,
                    reason=reason,
                    sell_slot=candidate.slot,
                    kind=candidate.kind,
                )
            )
        sells.sort(key=lambda a: a.net_value, reverse=True)
        advice.warnings.append("Hyena: sell required before next submit")
    else:
        swap_offers = [
            o
            for o in shop.offers
            if not o.sold and not _is_duplicate_buy(o, loadout)
        ]
        if sell_candidates:
            progress("Evaluating sell→buy swaps...")
        sells = evaluate_sell_swaps(
            loadout,
            shop,
            sell_candidates,
            swap_offers,
            boards,
            dictionary,
            config=config,
            ctx=ctx,
            baseline=baseline,
            use_free=use_free,
            margin_word=_SWAP_MARGIN_WORD,
        )
        sells = filter_sell_swaps(
            sells,
            loadout,
            shop,
            offers_by_index,
            run_ctx,
            use_free=use_free,
        )
        if sell_candidates and not sells:
            advice.warnings.append(
                "Keeping inventory — no sell→buy swap beats current items"
            )

    advice.sells = sells[:5]

    positive_buys = [b for b in buys if b.net_value > 0]
    if not positive_buys and buys:
        advice.warnings.append(
            "Low-confidence buy rankings — grid effects estimated from fixtures"
        )
        raw_positive: list[RankedAction] = []
    else:
        raw_positive = positive_buys

    approved_buys, blocked_buys = filter_ranked_buys(
        raw_positive,
        loadout,
        shop,
        offers_by_index,
        run_ctx,
        use_free=use_free,
    )
    advice.buys = approved_buys[:5]
    for action in advice.buys:
        idx = action.offer_index if action.offer_index is not None else -1
        offer = offers_by_index.get(idx)
        if offer is None:
            continue
        paid_price = effective_purchase_price(
            offer, loadout, shop, use_free_item=False
        )
        action.money_delta = -paid_price
        action.net_value = action.score_lift - money_to_word_equiv(
            paid_price, word_per_dollar=config.word_per_dollar
        )
    for action in blocked_buys:
        idx = action.offer_index if action.offer_index is not None else -1
        offer = offers_by_index.get(idx)
        if offer is None:
            continue
        paid_price = effective_purchase_price(
            offer, loadout, shop, use_free_item=False
        )
        action.net_value = action.score_lift - money_to_word_equiv(
            paid_price, word_per_dollar=config.word_per_dollar
        )
    if blocked_buys and approved_buys:
        advice.warnings.append(format_reserve_note(run_ctx))

    if not ctx.is_expired():
        progress("Estimating restock EV...")
    advice.restock = evaluate_restock_ev(
        loadout,
        shop,
        boards,
        dictionary,
        config=config,
        catalog_stamps=_catalog_stamp_ids(),
        ctx=ctx,
        buy_nets=buy_nets,
        baseline=baseline,
        run_ctx=run_ctx,
    )

    approved_indices = {b.offer_index for b in advice.buys if b.offer_index is not None}
    advice.freezes = evaluate_freeze_candidates(
        loadout,
        shop,
        eval_offers,
        ctx=run_ctx,
        buy_lifts=buy_lifts,
        buy_nets=buy_nets,
        approved_buy_indices=approved_indices,
        use_free=use_free,
        is_duplicate_buy=_is_duplicate_buy,
    )

    leave, leave_reason = should_leave_shop(
        advice.buys,
        advice.sells,
        advice.restock,
        ctx=run_ctx,
        blocked_buys=blocked_buys,
        freezes=advice.freezes,
    )
    if leave:
        advice.leave_shop = build_leave_shop_recommendation(leave_reason)

    if not ctx.is_expired():
        progress("Checking special actions...")
    advice.special_actions = evaluate_special_actions(
        loadout,
        shop,
        boards,
        dictionary,
        config=config,
        ctx=ctx,
        baseline=baseline,
        buy_nets=buy_nets,
    )

    if ctx.budget_exhausted and "Shop simulation budget exhausted" not in advice.warnings:
        advice.warnings.append(
            "Shop simulation budget exhausted — rankings may be incomplete"
        )

    elapsed = time.monotonic() - started
    progress(f"Shop advice ready in {elapsed:.1f}s")
    return advice


def format_shop_advice_text(advice: ShopAdvice) -> str:
    lines: list[str] = ["Shop advice:"]

    if advice.leave_shop and not advice.buys:
        lines.append(f"  Leave shop: {advice.leave_shop.reason}")

    if advice.buys:
        lines.append("  Buys:")
        for item in advice.buys[:3]:
            price = f" (${-item.money_delta})" if item.money_delta else ""
            lines.append(
                f"    {item.label}{price}: {item.net_value:+,.0f} WORD net ({item.reason})"
            )
    elif not advice.leave_shop:
        lines.append("  Buys: none clearly better than keeping money")

    if advice.freezes:
        lines.append("  Freeze:")
        for item in advice.freezes[:3]:
            lines.append(f"    {item.label}: {item.reason}")

    if advice.sells:
        lines.append("  Sells:")
        for item in advice.sells[:3]:
            lines.append(
                f"    {item.label}: {item.net_value:+,.0f} WORD net ({item.reason})"
            )
    if advice.restock:
        lines.append(
            f"  Restock: {advice.restock.label} ({advice.restock.reason})"
        )
    if advice.special_actions:
        lines.append("  Special:")
        for item in advice.special_actions[:3]:
            lines.append(f"    {item.label}: {item.net_value:+,.0f} WORD")
    for warn in advice.warnings:
        lines.append(f"  Warning: {warn}")
    return "\n".join(lines)


def format_shop_advice_html(advice: ShopAdvice) -> str:
    parts: list[str] = [
        "<span style='font-size:14px;font-weight:bold;color:#0cf'>Shop advice</span>"
    ]

    if advice.leave_shop and not advice.buys:
        parts.append(
            f"<br><span style='font-size:13px;color:#fa0;font-weight:bold'>"
            f"Leave shop</span>"
            f"<br><span style='font-size:11px;color:#ccc'>"
            f"{advice.leave_shop.reason}</span>"
        )
    elif advice.buys:
        top = advice.buys[0]
        price = f" (${-top.money_delta})" if top.money_delta else ""
        detail = top.reason if top.reason else f"{top.net_value:+,.0f} WORD net"
        parts.append(
            f"<br><span style='font-size:13px;color:#fff'>"
            f"{top.label}{price}</span>"
            f"<br><span style='font-size:12px;color:#0f8'>"
            f"{top.net_value:+,.0f} WORD net</span>"
            f"<br><span style='font-size:11px;color:#8cf'>"
            f"{detail}</span>"
        )
    elif advice.warnings:
        parts.append(
            "<br><span style='font-size:12px;color:#aaa'>"
            "No clear buy — keep money</span>"
        )

    if advice.freezes:
        top_freeze = advice.freezes[0]
        parts.append(
            f"<br><span style='font-size:12px;color:#0cf'>"
            f"{top_freeze.label}</span>"
            f"<br><span style='font-size:11px;color:#8cf'>"
            f"{top_freeze.reason}</span>"
        )
        if advice.leave_shop and not advice.buys:
            parts.append(
                "<br><span style='font-size:11px;color:#aaa'>"
                "then leave shop</span>"
            )

    if advice.sells:
        top = advice.sells[0]
        parts.append(
            f"<br><span style='font-size:12px;color:#fa0'>"
            f"{top.label} ({top.net_value:+,.0f})</span>"
        )
    if advice.restock:
        parts.append(
            f"<br><span style='font-size:11px;color:#8cf'>"
            f"Restock: {advice.restock.label}</span>"
        )
    if advice.special_actions:
        sp = advice.special_actions[0]
        parts.append(
            f"<br><span style='font-size:11px;color:#ccf'>"
            f"{sp.label}: {sp.net_value:+,.0f}</span>"
        )
    return "".join(parts)
