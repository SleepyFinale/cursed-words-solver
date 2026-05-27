"""Submit-time boss effects (ApplyBossModifier parity)."""

from __future__ import annotations

from typing import Any, Callable

from cursed_words_solver.models import Board, Loadout
from cursed_words_solver.rules.boss_effects import (
    boss_context,
    boss_rule_applies,
    get_active_boss_rule,
    resolve_boss_scaling,
)

EARLY_BOSS_TYPES = frozenset(
    {
        "boss_tile_penalty",
        "boss_subtract_word_score_money",
        "boss_steal_money",
    }
)


def _floor_modification(loadout: Loadout, ctx, rule: dict) -> int:
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
) -> None:
    """StealsMoney: deduct up to FloorAdjustedModification from step money."""
    if not boss_rule_applies(rule, ctx):
        return
    mod = _floor_modification(loadout, ctx, rule)
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
) -> dict[str, Any]:
    """Early ApplyBossModifier pass (before items when no Hourglass)."""
    key, boss = get_active_boss_rule(rules, loadout)
    if not boss:
        return state
    ctx = boss_context(loadout, rules)
    if not boss_rule_applies(boss, ctx):
        return state
    from cursed_words_solver.rules.boss_effects import boss_scoring_effect_type

    effect = boss_scoring_effect_type(boss)
    rule_id = key or loadout.boss_id or "boss"
    if effect == "boss_steal_money":
        apply_boss_steal_money(state, loadout, boss, ctx)
        if trace_step:
            trace_step(
                state,
                "boss_early",
                rule_id=rule_id,
                detail=state["effects"][-1] if state.get("effects") else "fox steal",
            )
        return state
    if effect in EARLY_BOSS_TYPES:
        state = apply_rule(boss, state, board, path, loadout, 1)
        if trace_step:
            trace_step(state, "boss_early", rule_id=rule_id, detail=effect)
    return state
