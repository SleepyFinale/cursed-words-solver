"""Stamp/sticker orchestration: Frankenstein stitch, Overhand replay."""

from __future__ import annotations

from typing import Any, Callable

from cursed_words_solver.models import Board, Loadout, LoadoutItem
from cursed_words_solver.rules.rule_lookup import get_rule, resolve_rule_id, slugify_name
from cursed_words_solver.rules.scoring_conditions import (
    human_hands_favourite_sticker_effective_level,
)

ORCHESTRATION_STICKER_TYPES = frozenset({"frankenstein_stitch", "overhand_replay"})
SKIP_APPLY_TYPES = frozenset(
    {
        "unmodeled",
        "custom",
        "scatter_start_grid",
        "scatter_start_encounter",
        "reverse_scoring_order",
        "shuffle_loadout_order",
        "frankenstein_stitch",
        "overhand_replay",
    }
)
# Types skipped in pipeline loops except orchestration handlers.
PIPELINE_SKIP_TYPES = SKIP_APPLY_TYPES - ORCHESTRATION_STICKER_TYPES


def _trace(
    state: dict[str, Any],
    *,
    phase: str,
    rule_id: str,
    game_class: str = "",
    detail: str = "",
    orchestration: str = "",
) -> None:
    trace = state.get("_trace")
    if trace is None:
        return
    entry: dict[str, Any] = {
        "phase": phase,
        "rule_id": rule_id,
        "detail": detail or rule_id,
    }
    if game_class:
        entry["game_class"] = game_class
    if orchestration:
        entry["orchestration"] = orchestration
    trace.append(entry)


def stitched_sticker_ids(loadout: Loadout) -> list[str]:
    raw = (loadout.extras or {}).get("stitched_sticker_ids")
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    if isinstance(raw, str) and raw.strip():
        import json

        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(x).strip() for x in parsed if str(x).strip()]
        except json.JSONDecodeError:
            return [s.strip() for s in raw.split(",") if s.strip()]
    return []


def overhand_level(loadout: Loadout, rules: dict[str, Any]) -> int:
    extras = loadout.extras or {}
    for key in ("overhand_level", "overhand_variable"):
        if key in extras:
            try:
                return max(0, int(extras[key]))
            except (TypeError, ValueError):
                pass
    for sticker in loadout.stickers:
        _key, rule = get_rule(rules, "stickers", sticker.id, sticker.name)
        if rule and rule.get("type") == "overhand_replay":
            try:
                return max(0, int(sticker.level))
            except (TypeError, ValueError):
                return 1
    return 0


def overhand_at_slot(loadout: Loadout, rules: dict[str, Any], slot: int) -> bool:
    if slot < 0 or slot >= len(loadout.stickers):
        return False
    sticker = loadout.stickers[slot]
    _key, rule = get_rule(rules, "stickers", sticker.id, sticker.name)
    return bool(rule and rule.get("type") == "overhand_replay")


def apply_frankenstein_stitch(
    *,
    rules: dict[str, Any],
    loadout: Loadout,
    state: dict[str, Any],
    board: Board,
    path: list[int],
    apply_rule: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    """Replay each stitched sticker rule (game: Frankenstein.StitchedItems)."""
    for sticker_id in stitched_sticker_ids(loadout):
        _key, rule = get_rule(rules, "stickers", sticker_id, sticker_id)
        if not rule or rule.get("type") in PIPELINE_SKIP_TYPES:
            continue
        level = 1
        for sticker in loadout.stickers:
            if sticker.id == sticker_id or sticker.name == sticker_id:
                level = sticker.level
                break
        state = apply_rule(
            rule,
            state,
            board,
            path,
            loadout,
            level,
            applying_sticker_id=sticker_id,
        )
        state["effects"].append(f"Frankenstein: {sticker_id}")
        _trace(
            state,
            phase="sticker",
            rule_id=sticker_id,
            game_class="Frankenstein",
            orchestration="frankenstein",
            detail=f"stitched {sticker_id}",
        )
    return state


def apply_overhand_replays_for_slot(
    *,
    rules: dict[str, Any],
    loadout: Loadout,
    state: dict[str, Any],
    board: Board,
    path: list[int],
    slot: int,
    apply_rule: Callable[..., dict[str, Any]],
    bucket: str,
    item: LoadoutItem,
    level: int,
) -> dict[str, Any]:
    """Extra applications when Stickers[slot] is Overhand (game: IsOverhandTarget)."""
    if not overhand_at_slot(loadout, rules, slot):
        return state
    _key, rule = get_rule(rules, bucket, item.id, item.name)
    if not rule or rule.get("type") in PIPELINE_SKIP_TYPES:
        return state
    extra = overhand_level(loadout, rules)
    for _ in range(extra):
        state = apply_rule(
            rule,
            state,
            board,
            path,
            loadout,
            level,
            applying_sticker_id=item.id or item.name,
        )
    if extra:
        state["effects"].append(f"Overhand: ×{extra} replay slot {slot}")
        _trace(
            state,
            phase=bucket.rstrip("s"),
            rule_id=item.id or item.name,
            game_class="Overhand",
            orchestration="overhand",
            detail=f"×{extra} at slot {slot}",
        )
    return state


def apply_snapshot_copy_sticker(
    *,
    rules: dict[str, Any],
    loadout: Loadout,
    state: dict[str, Any],
    board: Board,
    path: list[int],
    sticker: LoadoutItem,
    apply_rule: Callable[..., dict[str, Any]],
    multiply_only: bool,
) -> dict[str, Any]:
    """Equipped Snapshot applies the copied grid sticker's scoring rule at submit."""
    from cursed_words_solver.rules.scoring_conditions import (
        snapshot_copy_level,
        snapshot_copy_slug,
    )

    if slugify_name(sticker.id or sticker.name) != "snapshot":
        return state
    copy_slug = snapshot_copy_slug(loadout)
    if not copy_slug:
        return state
    _key, copy_rule = get_rule(rules, "stickers", copy_slug, copy_slug)
    if not copy_rule or copy_rule.get("type") in PIPELINE_SKIP_TYPES:
        return state
    is_multiply = copy_rule.get("type") == "multiply_word_scaled"
    if multiply_only != is_multiply:
        return state
    copy_grid_level = snapshot_copy_level(loadout, sticker.level)
    level = max(copy_grid_level, max(1, sticker.level))
    state["_snapshot_proxy"] = True
    state = apply_rule(
        copy_rule,
        state,
        board,
        path,
        loadout,
        level,
        applying_sticker_id="snapshot",
    )
    state.pop("_snapshot_proxy", None)
    _trace(
        state,
        phase="rule",
        rule_id="snapshot",
        detail=f"copy:{copy_slug}",
    )
    return state


def apply_sticker_with_orchestration(
    *,
    rules: dict[str, Any],
    loadout: Loadout,
    state: dict[str, Any],
    board: Board,
    path: list[int],
    sticker: LoadoutItem,
    slot: int,
    apply_rule: Callable[..., dict[str, Any]],
    multiply_only: bool = False,
) -> dict[str, Any]:
    _key, rule = get_rule(rules, "stickers", sticker.id, sticker.name)
    if not rule:
        return state
    if slugify_name(sticker.id or sticker.name) == "snapshot":
        return apply_snapshot_copy_sticker(
            rules=rules,
            loadout=loadout,
            state=state,
            board=board,
            path=path,
            sticker=sticker,
            apply_rule=apply_rule,
            multiply_only=multiply_only,
        )
    if rule.get("type") == "frankenstein_stitch":
        return apply_frankenstein_stitch(
            rules=rules,
            loadout=loadout,
            state=state,
            board=board,
            path=path,
            apply_rule=apply_rule,
        )
    if rule.get("type") in ORCHESTRATION_STICKER_TYPES:
        return state
    if rule.get("type") in PIPELINE_SKIP_TYPES:
        return state
    eff_level = human_hands_favourite_sticker_effective_level(
        sticker.level,
        sticker.id,
        sticker.name,
        loadout,
    )
    if slugify_name(sticker.id or sticker.name) == "tombstone":
        from cursed_words_solver.rules.scoring_conditions import (
            tombstone_inventory_scoring_level,
        )

        eff_level = tombstone_inventory_scoring_level(
            sticker, loadout, board, base_level=eff_level
        )
    state = apply_rule(
        rule,
        state,
        board,
        path,
        loadout,
        eff_level,
        applying_sticker_id=sticker.id or sticker.name,
    )
    return apply_overhand_replays_for_slot(
        rules=rules,
        loadout=loadout,
        state=state,
        board=board,
        path=path,
        slot=slot,
        apply_rule=apply_rule,
        bucket="stickers",
        item=sticker,
        level=eff_level,
    )


def apply_stamp_with_orchestration(
    *,
    rules: dict[str, Any],
    loadout: Loadout,
    state: dict[str, Any],
    board: Board,
    path: list[int],
    stamp: LoadoutItem,
    slot: int,
    apply_rule: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    _key, rule = get_rule(rules, "stamps", stamp.id, stamp.name)
    if not rule or rule.get("type") in PIPELINE_SKIP_TYPES:
        return state
    state = apply_rule(
        rule,
        state,
        board,
        path,
        loadout,
        1,
        applying_sticker_id=stamp.id or stamp.name,
    )
    return apply_overhand_replays_for_slot(
        rules=rules,
        loadout=loadout,
        state=state,
        board=board,
        path=path,
        slot=slot,
        apply_rule=apply_rule,
        bucket="stamps",
        item=stamp,
        level=1,
    )


def loadout_has_frankenstein(loadout: Loadout | None, rules: dict[str, Any]) -> bool:
    if not loadout:
        return False
    for sticker in loadout.stickers:
        _key, rule = get_rule(rules, "stickers", sticker.id, sticker.name)
        if rule and rule.get("type") == "frankenstein_stitch":
            return True
    return resolve_rule_id(rules, "stickers", "frankenstein", "") is not None
