"""Submit-time boss effects (ApplyBossModifier parity)."""

from __future__ import annotations

from typing import Any, Callable

from cursed_words_solver.models import Board, Loadout
from cursed_words_solver.rules.boss_effects import (
    BossContext,
    boss_context,
    boss_rule_applies,
    floor_mod_for_rule,
    get_active_boss_rule,
    get_active_boss_rules,
    michael_finale_active,
    resolve_boss_scaling,
    resolve_boss_scaling_for_rule,
)

EARLY_BOSS_TYPES = frozenset(
    {
        "boss_tile_penalty",
        "boss_subtract_word_score_money",
        "boss_steal_money",
    }
)


def _floor_modification(
    loadout: Loadout,
    ctx,
    rule: dict,
    *,
    rule_key: str | None = None,
) -> int:
    if rule_key:
        live = floor_mod_for_rule(loadout, {}, rule_key, rule)
        if live is not None and live > 0:
            return live
    raw = loadout.extras.get("boss_floor_modification")
    if raw is not None:
        try:
            return max(0, int(raw))
        except (TypeError, ValueError):
            pass
    val = resolve_boss_scaling(rule, ctx.area, ctx.cursed)
    if val is not None:
        return max(0, int(val))
    return 0


def apply_boss_steal_money(
    state: dict[str, Any],
    loadout: Loadout,
    rule: dict,
    ctx,
    *,
    rule_key: str | None = None,
) -> None:
    """StealsMoney: deduct up to FloorAdjustedModification from step money."""
    if not boss_rule_applies(rule, ctx):
        return
    mod = _floor_modification(loadout, ctx, rule, rule_key=rule_key)
    if mod <= 0:
        return
    available = max(
        int(state.get("money_bonus", 0)),
        loadout.money,
        0,
    )
    stolen = min(mod, available)
    if stolen <= 0:
        return
    state["money_bonus"] = int(state.get("money_bonus", 0)) - stolen
    loadout.money = max(0, loadout.money - stolen)
    state["effects"].append(f"−${stolen} stolen by boss (Fox)")
    loadout.extras["fox_stolen_this_word"] = str(stolen)


def apply_early_boss_scoring(
    state: dict[str, Any],
    board: Board,
    path: list[int],
    loadout: Loadout,
    rules: dict,
    apply_rule: Callable,
    *,
    trace_step: Callable[..., None] | None = None,
    active_boss_rules: tuple[tuple[str, dict[str, Any] | None], ...] | None = None,
    boss_ctx: BossContext | None = None,
) -> dict[str, Any]:
    """Early ApplyBossModifier pass (before items when no Hourglass)."""
    from cursed_words_solver.rules.boss_effects import boss_scoring_effect_type

    if michael_finale_active(loadout):
        return state

    if active_boss_rules is not None:
        active = list(active_boss_rules)
    else:
        active = get_active_boss_rules(rules, loadout)
        if not active:
            key, boss = get_active_boss_rule(rules, loadout)
            active = [(key or "", boss)] if boss is not None else []
    ctx = boss_ctx if boss_ctx is not None else boss_context(loadout, rules)
    for key, boss in active:
        if not boss:
            continue
        if not boss_rule_applies(boss, ctx):
            continue
        effect = boss_scoring_effect_type(boss)
        rule_id = key or loadout.boss_id or "boss"
        loadout.extras["_scoring_boss_rule_key"] = rule_id
        if effect == "boss_steal_money":
            apply_boss_steal_money(state, loadout, boss, ctx, rule_key=key)
            if trace_step:
                trace_step(
                    state,
                    "boss_early",
                    rule_id=rule_id,
                    detail=state["effects"][-1] if state.get("effects") else "fox steal",
                )
            continue
        if effect in EARLY_BOSS_TYPES:
            state = apply_rule(boss, state, board, path, loadout, 1)
            if trace_step:
                trace_step(state, "boss_early", rule_id=rule_id, detail=effect)
    return state


def apply_hourglass_boss_scoring(
    state: dict[str, Any],
    board: Board,
    path: list[int],
    loadout: Loadout,
    rules: dict,
    apply_rule: Callable,
    *,
    trace_step: Callable[..., None] | None = None,
    active_boss_rules: tuple[tuple[str, dict[str, Any] | None], ...] | None = None,
    boss_ctx: BossContext | None = None,
) -> dict[str, Any]:
    """Hourglass: single reversed ApplyBossModifier pass after items."""
    from cursed_words_solver.rules.boss_effects import boss_scoring_effect_type

    if michael_finale_active(loadout):
        return state

    if active_boss_rules is not None:
        active = list(reversed(active_boss_rules))
    else:
        active = list(reversed(get_active_boss_rules(rules, loadout)))
        if not active:
            key, boss = get_active_boss_rule(rules, loadout)
            active = [(key or "", boss)] if boss is not None else []
    ctx = boss_ctx if boss_ctx is not None else boss_context(loadout, rules)
    for key, boss in active:
        if not boss:
            continue
        if boss.get("type") in ("unmodeled", "custom"):
            continue
        if not boss_rule_applies(boss, ctx):
            continue
        effect = boss_scoring_effect_type(boss)
        rule_id = key or loadout.boss_id or "boss"
        loadout.extras["_scoring_boss_rule_key"] = rule_id
        if effect == "boss_steal_money":
            apply_boss_steal_money(state, loadout, boss, ctx, rule_key=key)
            if trace_step:
                trace_step(
                    state,
                    "boss_late",
                    rule_id=rule_id,
                    detail=state["effects"][-1] if state.get("effects") else "fox steal",
                )
            continue
        if effect in EARLY_BOSS_TYPES:
            state = apply_rule(boss, state, board, path, loadout, 1)
            if trace_step:
                trace_step(state, "boss_late", rule_id=rule_id, detail=effect)
            continue
        state = apply_rule(boss, state, board, path, loadout, 1)
        if trace_step:
            trace_step(
                state,
                "boss_late",
                rule_id=rule_id,
                detail=effect or boss.get("type", ""),
            )
    return state
