"""Simulate shop purchases, sells, and rerolls via word search."""

from __future__ import annotations

import copy
import random
import time
from dataclasses import dataclass, field
from pathlib import Path

from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.models import (
    ActionRecommendation,
    Board,
    Loadout,
    LoadoutItem,
    RankedAction,
    SellCandidate,
    ShopOffer,
    ShopState,
)
from cursed_words_solver.rules.boss_effects import boss_word_constraints
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.setup_value import grids_remaining_from_loadout
from cursed_words_solver.search import WordSearcher
from cursed_words_solver.shop_economy import (
    can_add_offer,
    effective_purchase_price,
    free_item_applies,
    is_upgrade_offer,
    money_to_word_equiv,
    net_sell_proceeds,
    restock_cost,
)
from cursed_words_solver.shop_item_value import (
    catalog_lift_for_offer,
    catalog_lift_for_owned_item,
    merge_search_and_catalog_lift,
)
from cursed_words_solver.shop_reserve import ShopRunContext


@dataclass
class SimulationConfig:
    budget_sec: float = 1.0
    max_boards: int = 2
    setup_weight: float = 0.4
    setup_discount: float = 0.85
    word_per_dollar: float = 50.0
    monte_carlo_samples: int = 8
    grids_discount: float = 0.85
    total_budget_sec: float = 20.0
    search_workers: int = 1
    shop_reserve_per_future_shop: int = 0
    shop_marginal_net_per_remaining_shop: float = 15.0


@dataclass
class SimulationContext:
    """Shared state for one shop-advisor run: cache, deadline, baseline."""

    boards: list[Board]
    dictionary: WordDictionary
    config: SimulationConfig
    deadline: float | None = None
    baseline_value: float | None = None
    budget_exhausted: bool = False
    search_count: int = 0
    _score_cache: dict[tuple, float] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        boards: list[Board],
        dictionary: WordDictionary,
        config: SimulationConfig,
    ) -> SimulationContext:
        deadline = None
        if config.total_budget_sec > 0:
            deadline = time.monotonic() + config.total_budget_sec
        return cls(
            boards=boards,
            dictionary=dictionary,
            config=config,
            deadline=deadline,
        )

    def remaining_sec(self) -> float:
        if self.deadline is None:
            return float("inf")
        return max(0.0, self.deadline - time.monotonic())

    def is_expired(self) -> bool:
        if self.deadline is None:
            return False
        if time.monotonic() >= self.deadline:
            self.budget_exhausted = True
            return True
        return False

    def effective_budget_sec(self) -> float:
        base = self.config.budget_sec
        if self.deadline is None:
            return base
        remaining = self.remaining_sec()
        if remaining <= 0:
            return 0.0
        n_boards = max(1, len(self.boards))
        dynamic = remaining / n_boards
        return min(base, max(0.1, dynamic))


def _loadout_key(loadout: Loadout) -> tuple:
    stickers = tuple((s.id, s.level) for s in loadout.stickers)
    stamps = tuple((s.id, s.level) for s in loadout.stamps)
    extras = loadout.extras or {}
    foil = tuple(sorted(str(x).lower() for x in (extras.get("foil_sticker_ids") or [])))
    pin = (extras.get("pin_effect"), extras.get("pin_branch"))
    return (stickers, stamps, foil, pin)


def _clone_loadout(loadout: Loadout) -> Loadout:
    return copy.deepcopy(loadout)


def _apply_purchase(loadout: Loadout, offer: ShopOffer) -> Loadout:
    if offer.slot == "sticker" and is_upgrade_offer(offer, loadout):
        lo = _clone_loadout(loadout)
        oid = (offer.id or "").lower()
        for sticker in lo.stickers:
            if (sticker.id or "").lower() == oid:
                sticker.level = max(sticker.level, max(1, offer.level or 1))
                break
        if offer.foil:
            lo = _foil_sticker(lo, offer.id)
        return lo

    lo = _clone_loadout(loadout)
    item = LoadoutItem(
        id=offer.id,
        name=offer.name,
        level=offer.level,
        kind="stamp" if offer.slot == "stamp" else "sticker",
    )
    if offer.slot == "stamp":
        lo.stamps.append(item)
    elif offer.slot == "sticker":
        lo.stickers.append(item)
    return lo


def _add_item(loadout: Loadout, offer: ShopOffer) -> Loadout:
    return _apply_purchase(loadout, offer)


def _remove_item(loadout: Loadout, candidate: SellCandidate) -> Loadout:
    lo = _clone_loadout(loadout)
    if candidate.kind == "stamp" and 0 <= candidate.slot < len(lo.stamps):
        lo.stamps.pop(candidate.slot)
    elif candidate.kind == "sticker" and 0 <= candidate.slot < len(lo.stickers):
        lo.stickers.pop(candidate.slot)
    return lo


def _upgrade_hippo(loadout: Loadout) -> Loadout:
    lo = _clone_loadout(loadout)
    for sticker in lo.stickers:
        if (sticker.id or "").lower() in {"hungry_hippo", "hippo"}:
            sticker.level = max(1, sticker.level) + 1
            return lo
    return lo


def _foil_sticker(loadout: Loadout, sticker_id: str) -> Loadout:
    lo = _clone_loadout(loadout)
    sid = sticker_id.lower()
    for sticker in lo.stickers:
        if (sticker.id or "").lower() == sid:
            extras = dict(lo.extras or {})
            foil_ids = list(extras.get("foil_sticker_ids") or [])
            if sid not in foil_ids:
                foil_ids.append(sid)
            extras["foil_sticker_ids"] = foil_ids
            lo.extras = extras
            return lo
    return lo


def _wordlist_path(dictionary: WordDictionary) -> Path | None:
    path = getattr(dictionary, "path", None)
    return path if isinstance(path, Path) else None


def _best_score_on_board(
    ctx: SimulationContext,
    board_idx: int,
    board: Board,
    loadout: Loadout,
) -> float:
    if ctx.is_expired():
        return 0.0
    cache_key = (_loadout_key(loadout), board_idx)
    cached = ctx._score_cache.get(cache_key)
    if cached is not None:
        return cached

    budget_sec = ctx.effective_budget_sec()
    if budget_sec <= 0:
        ctx.budget_exhausted = True
        return 0.0

    rules = ScoringPipeline().rules
    constraints = boss_word_constraints(loadout, rules)
    if constraints.blocked:
        ctx._score_cache[cache_key] = 0.0
        return 0.0

    ctx.search_count += 1
    config = ctx.config
    searcher = WordSearcher(
        dictionary=ctx.dictionary,
        min_len=constraints.min_len,
        max_len=constraints.max_len,
        time_budget=budget_sec,
        setup_weight=config.setup_weight,
        setup_discount=config.setup_discount,
        search_workers=max(1, int(config.search_workers)),
        wordlist_path=_wordlist_path(ctx.dictionary),
    )
    results = searcher.find_best_words(board, loadout, top_n=1)
    if not results:
        ctx._score_cache[cache_key] = 0.0
        return 0.0
    top = results[0]
    score = top.rank_score if top.rank_score else top.score
    ctx._score_cache[cache_key] = score
    return score


def _horizon_weight(loadout: Loadout, config: SimulationConfig) -> float:
    grids = grids_remaining_from_loadout(loadout)
    return sum(config.grids_discount ** i for i in range(max(1, grids)))


def evaluate_loadout_value(ctx: SimulationContext, loadout: Loadout) -> float:
    boards = ctx.boards
    if not boards:
        return 0.0
    if ctx.is_expired():
        return 0.0
    horizon = _horizon_weight(loadout, ctx.config)
    total = 0.0
    for idx, board in enumerate(boards):
        total += _best_score_on_board(ctx, idx, board, loadout)
    return total * horizon / len(boards)


def _baseline_value(ctx: SimulationContext, loadout: Loadout) -> float:
    if ctx.baseline_value is not None:
        return ctx.baseline_value
    ctx.baseline_value = evaluate_loadout_value(ctx, loadout)
    return ctx.baseline_value


def _legacy_context(
    boards: list[Board],
    dictionary: WordDictionary,
    config: SimulationConfig,
) -> SimulationContext:
    return SimulationContext.create(boards, dictionary, config)


def evaluate_purchase(
    offer: ShopOffer,
    loadout: Loadout,
    shop: ShopState | None,
    boards: list[Board],
    dictionary: WordDictionary,
    *,
    config: SimulationConfig,
    use_free: bool = False,
    ctx: SimulationContext | None = None,
    baseline: float | None = None,
) -> tuple[float, float, str]:
    if offer.sold or not can_add_offer(offer, loadout):
        return 0.0, 0.0, ""
    if ctx is None:
        ctx = _legacy_context(boards, dictionary, config)
    if ctx.is_expired():
        return 0.0, 0.0, ""

    price = effective_purchase_price(offer, loadout, shop, use_free_item=use_free)
    base = baseline if baseline is not None else _baseline_value(ctx, loadout)
    if offer.hippo_eligible and shop and shop.hungry_hippo_equipped:
        hypothetical = _upgrade_hippo(loadout)
    else:
        hypothetical = _add_item(loadout, offer)
    new_value = evaluate_loadout_value(ctx, hypothetical)
    search_lift = new_value - base
    cat_lift, cat_kind = catalog_lift_for_offer(
        offer,
        loadout,
        ctx.boards,
        grids_discount=config.grids_discount,
    )
    lift, reason = merge_search_and_catalog_lift(
        search_lift,
        cat_lift,
        catalog_kind=cat_kind,
        max_boards=len(ctx.boards) or config.max_boards,
    )
    net = lift - money_to_word_equiv(price, word_per_dollar=config.word_per_dollar)
    return lift, net, reason


def evaluate_sell(
    candidate: SellCandidate,
    loadout: Loadout,
    boards: list[Board],
    dictionary: WordDictionary,
    *,
    config: SimulationConfig,
    ctx: SimulationContext | None = None,
    baseline: float | None = None,
) -> tuple[float, float, str]:
    if ctx is None:
        ctx = _legacy_context(boards, dictionary, config)
    if ctx.is_expired():
        return 0.0, 0.0, ""

    base = baseline if baseline is not None else _baseline_value(ctx, loadout)
    hypothetical = _remove_item(loadout, candidate)
    new_value = evaluate_loadout_value(ctx, hypothetical)
    search_loss = base - new_value
    cat_cost, cat_kind = catalog_lift_for_owned_item(
        candidate,
        loadout,
        ctx.boards,
        grids_discount=config.grids_discount,
    )
    loss = max(search_loss, cat_cost) if cat_cost > 0 else search_loss
    cash = net_sell_proceeds(candidate, loadout)
    net = money_to_word_equiv(cash, word_per_dollar=config.word_per_dollar) - loss
    reason = f"Frees slot, ${cash:+d}" if cash else "Frees slot"
    if cat_cost > search_loss + 1.0:
        reason += f" (−{loss:,.0f} WORD {cat_kind or 'value'} kept)"
    return -loss, net, reason


def evaluate_sell_swaps(
    loadout: Loadout,
    shop: ShopState | None,
    sell_candidates: list[SellCandidate],
    purchase_offers: list[ShopOffer],
    boards: list[Board],
    dictionary: WordDictionary,
    *,
    config: SimulationConfig,
    ctx: SimulationContext | None = None,
    baseline: float | None = None,
    use_free: bool = False,
    margin_word: float = 50.0,
) -> list[RankedAction]:
    """Rank sell→buy swaps by integrated net vs keeping the sold item."""
    if ctx is None:
        ctx = _legacy_context(boards, dictionary, config)
    if ctx.is_expired() or not sell_candidates or not purchase_offers:
        return []

    keep_value = baseline if baseline is not None else _baseline_value(ctx, loadout)
    swaps: list[RankedAction] = []

    for candidate in sell_candidates:
        if ctx.is_expired():
            break
        cash = net_sell_proceeds(candidate, loadout)
        hypo = _remove_item(loadout, candidate)
        money_after = loadout.money + cash

        for offer in purchase_offers:
            if ctx.is_expired():
                break
            if offer.sold or not can_add_offer(offer, hypo):
                continue
            price = effective_purchase_price(
                offer, hypo, shop, use_free_item=use_free
            )
            if money_after < price:
                continue

            bought = _add_item(hypo, offer)
            after_value = evaluate_loadout_value(ctx, bought)
            swap_lift = after_value - keep_value
            if abs(swap_lift) < 1.0:
                sold_cat, _ = catalog_lift_for_owned_item(
                    candidate,
                    loadout,
                    ctx.boards,
                    grids_discount=config.grids_discount,
                )
                bought_cat, cat_kind = catalog_lift_for_offer(
                    offer,
                    hypo,
                    ctx.boards,
                    grids_discount=config.grids_discount,
                )
                swap_lift = bought_cat - sold_cat
                catalog_note = cat_kind
            else:
                catalog_note = ""
            swap_net = swap_lift
            if swap_net <= margin_word:
                continue

            buy_label = offer.name
            if offer.slot == "tile" and offer.letter:
                buy_label = f"{offer.color or 'tile'} {offer.letter}"
            money_note = f"${cash}−${price}" if cash or price else ""
            if catalog_note:
                reason = f"swap {money_note}, {swap_lift:+,.0f} WORD ({catalog_note})"
            else:
                reason = f"swap {money_note}, {swap_lift:+,.0f} WORD lift"
            swaps.append(
                RankedAction(
                    action="sell_swap",
                    label=f"Sell {candidate.name} → Buy {buy_label}",
                    net_value=swap_net,
                    score_lift=swap_lift,
                    money_delta=cash - price,
                    reason=reason,
                    offer_index=offer.index,
                    sell_slot=candidate.slot,
                    kind=candidate.kind,
                )
            )

    swaps.sort(key=lambda a: a.net_value, reverse=True)
    return swaps


def evaluate_restock_ev(
    loadout: Loadout,
    shop: ShopState | None,
    boards: list[Board],
    dictionary: WordDictionary,
    *,
    config: SimulationConfig,
    catalog_stamps: list[str] | None = None,
    ctx: SimulationContext | None = None,
    buy_nets: dict[int, float] | None = None,
    baseline: float | None = None,
    run_ctx: ShopRunContext | None = None,
) -> ActionRecommendation:
    if ctx is None:
        ctx = _legacy_context(boards, dictionary, config)

    cost = restock_cost(loadout, shop)
    cost_words = money_to_word_equiv(cost, word_per_dollar=config.word_per_dollar)
    if run_ctx is not None and run_ctx.money_reserve > 0:
        reserve = run_ctx.money_reserve
        if loadout.money - cost < reserve:
            return ActionRecommendation(
                action="no",
                label="Skip restock",
                net_value=-cost_words,
                reason=(
                    f"Restock would leave ${loadout.money - cost} "
                    f"< ${reserve} reserve for later shops"
                ),
            )
    baseline_best = 0.0
    if buy_nets:
        baseline_best = max(buy_nets.values(), default=0.0)
    elif shop:
        free = free_item_applies(shop, loadout)
        base = baseline if baseline is not None else _baseline_value(ctx, loadout)
        for offer in shop.offers:
            if offer.sold:
                continue
            _lift, net, _reason = evaluate_purchase(
                offer,
                loadout,
                shop,
                boards,
                dictionary,
                config=config,
                use_free=free,
                ctx=ctx,
                baseline=base,
            )
            baseline_best = max(baseline_best, net)

    if baseline_best > cost_words * 0.5:
        return ActionRecommendation(
            action="skip",
            label="Skip restock",
            net_value=baseline_best,
            reason=f"Current offers already strong (+{baseline_best:,.0f} WORD net)",
        )

    if ctx.is_expired():
        return ActionRecommendation(
            action="no",
            label="Skip restock",
            net_value=0.0,
            reason="Shop simulation budget exhausted",
        )

    samples = max(5, config.monte_carlo_samples)
    est_per_sample = max(
        0.5,
        config.budget_sec * max(1, len(ctx.boards)) * 2,
    )
    if ctx.deadline is not None:
        max_samples = int(ctx.remaining_sec() / est_per_sample)
        samples = min(samples, max(1, max_samples))

    rng = random.Random(42)
    stamp_pool = catalog_stamps or ["newspaper", "genie", "fried_shrimp", "wheel", "eraser"]
    ev_total = 0.0
    sample_count = 0
    base = baseline if baseline is not None else _baseline_value(ctx, loadout)
    for _ in range(samples):
        if ctx.is_expired():
            break
        offer = ShopOffer(
            slot="stamp",
            index=0,
            id=rng.choice(stamp_pool),
            name=rng.choice(stamp_pool).replace("_", " ").title(),
            price=rng.randint(8, 25),
        )
        _lift, net, _reason = evaluate_purchase(
            offer,
            loadout,
            shop,
            boards,
            dictionary,
            config=config,
            ctx=ctx,
            baseline=base,
        )
        ev_total += net
        sample_count += 1

    if sample_count == 0:
        return ActionRecommendation(
            action="no",
            label="Skip restock",
            net_value=0.0,
            reason="Shop simulation budget exhausted",
        )

    ev = ev_total / sample_count
    net_ev = ev - cost_words
    if net_ev > 0:
        return ActionRecommendation(
            action="yes",
            label="Restock",
            net_value=net_ev,
            reason=f"E[+{ev:,.0f}] WORD − ${cost} restock",
        )
    return ActionRecommendation(
        action="no",
        label="Skip restock",
        net_value=net_ev,
        reason=f"Restock EV {ev:,.0f} WORD < cost {cost_words:,.0f}",
    )


def evaluate_special_actions(
    loadout: Loadout,
    shop: ShopState | None,
    boards: list[Board],
    dictionary: WordDictionary,
    *,
    config: SimulationConfig,
    ctx: SimulationContext | None = None,
    baseline: float | None = None,
    buy_nets: dict[int, float] | None = None,
) -> list[RankedAction]:
    if ctx is None:
        ctx = _legacy_context(boards, dictionary, config)
    if ctx.is_expired():
        return []

    actions: list[RankedAction] = []
    has_needle = any((s.id or "").lower() == "sewing_needle" for s in loadout.stamps)
    has_unicorn = any((s.id or "").lower() == "unicorn" for s in loadout.stamps)
    base = baseline if baseline is not None else _baseline_value(ctx, loadout)

    if has_unicorn:
        for sticker in loadout.stickers:
            if ctx.is_expired():
                break
            if (sticker.id or "").lower() in {"unicorn", "sewing_needle"}:
                continue
            hypo = _foil_sticker(loadout, sticker.id)
            new_val = evaluate_loadout_value(ctx, hypo)
            lift = new_val - base
            if lift > 0:
                actions.append(
                    RankedAction(
                        action="foil",
                        label=f"Foil {sticker.name}",
                        net_value=lift,
                        score_lift=lift,
                        reason="Unicorn foil upgrade",
                        kind="sticker",
                    )
                )

    if has_needle and len(loadout.stickers) >= 2:
        best_lift = 0.0
        best_pair = ("", "")
        stickers = loadout.stickers[:5]
        for i, a in enumerate(stickers):
            if ctx.is_expired():
                break
            for b in stickers[i + 1 :]:
                hypo = _clone_loadout(loadout)
                hypo.stickers = [s for s in hypo.stickers if s.id not in {a.id, b.id}]
                new_val = evaluate_loadout_value(ctx, hypo)
                lift = new_val - base
                if lift > best_lift:
                    best_lift = lift
                    best_pair = (a.name, b.name)
        if best_lift > 0:
            actions.append(
                RankedAction(
                    action="stitch",
                    label=f"Stitch {best_pair[0]} + {best_pair[1]}",
                    net_value=best_lift,
                    score_lift=best_lift,
                    reason="Sewing Needle merge",
                    kind="sticker",
                )
            )

    if shop and shop.hungry_hippo_equipped:
        for offer in shop.offers:
            if ctx.is_expired():
                break
            if not offer.hippo_eligible or offer.sold:
                continue
            if buy_nets is not None and offer.index in buy_nets:
                net = buy_nets[offer.index]
                lift = net + money_to_word_equiv(
                    offer.price, word_per_dollar=config.word_per_dollar
                )
            else:
                lift, net, _reason = evaluate_purchase(
                    offer,
                    loadout,
                    shop,
                    boards,
                    dictionary,
                    config=config,
                    ctx=ctx,
                    baseline=base,
                )
            if net > 0:
                actions.append(
                    RankedAction(
                        action="hippo_eat",
                        label=f"Feed Hippo ({offer.name})",
                        net_value=net,
                        score_lift=lift,
                        money_delta=-offer.price,
                        reason="Hungry Hippo upgrade instead of buy",
                        offer_index=offer.index,
                        kind=offer.slot,
                    )
                )

    actions.sort(key=lambda a: a.net_value, reverse=True)
    return actions
