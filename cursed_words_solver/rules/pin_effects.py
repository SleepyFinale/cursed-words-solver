"""Pin right-track scoring and RAM orchestration (CharacterItem + UpgradeableComponents)."""

from __future__ import annotations

from typing import Any, Callable

from cursed_words_solver.models import Board, Loadout
from cursed_words_solver.rules.rule_lookup import (
    PIN_ORCHESTRATION_TYPES,
    get_pin_rule,
    get_pin_scoring_rule,
    get_rule,
    resolve_rule_id,
)

# Types skipped when RAM replays ItemsInMemory (see RandomAccessMemory.BlacklistedItemTypes).
RAM_BLACKLIST_TYPES = frozenset(
    {
        "snapshot",
        "beam_me_up",
        "overhand",
        "reverse_scoring_order",
        "shuffle_loadout_order",
        "scatter_start_grid",
        "scatter_start_encounter",
        "unmodeled",
        "custom",
    }
)


def get_pin_tracks(
    rules: dict[str, Any], pin_effect: str
) -> tuple[str | None, dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
    """Return (canonical, full_pin, left_track, right_scoring_rule)."""
    canonical, pin_rule = get_pin_rule(rules, pin_effect)
    if not isinstance(pin_rule, dict):
        return canonical, None, None, None
    left = pin_rule.get("left") if isinstance(pin_rule.get("left"), dict) else None
    right = get_pin_scoring_rule(rules, pin_effect)
    orch = pin_rule.get("orchestration") or ""
    if orch in PIN_ORCHESTRATION_TYPES:
        right = {**pin_rule, "type": orch}
    return canonical, pin_rule, left, right


def apply_pin_memory(
    *,
    rules: dict[str, Any],
    loadout: Loadout,
    state: dict[str, Any],
    board: Board,
    path: list[int],
    apply_rule: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    memory = loadout.extras.get("pin_memory") or []
    if not isinstance(memory, list):
        return state
    for entry in memory:
        if not isinstance(entry, dict):
            continue
        kind = str(entry.get("kind", "sticker")).lower()
        bucket = "stamps" if kind == "stamp" else "stickers"
        item_id = str(entry.get("id", "") or "")
        item_name = str(entry.get("name", "") or "")
        try:
            level = int(entry.get("level", 1))
        except (TypeError, ValueError):
            level = 1
        _key, rule = get_rule(rules, bucket, item_id, item_name)
        if not rule:
            continue
        effect_type = str(rule.get("type", "")).lower()
        if effect_type in RAM_BLACKLIST_TYPES:
            continue
        state = apply_rule(rule, state, board, path, loadout, level)
        state["effects"].append(f"RAM: {item_name or item_id}")
    return state


def apply_pin_word_scoring(
    *,
    rules: dict[str, Any],
    loadout: Loadout,
    pin_effect: str,
    state: dict[str, Any],
    board: Board,
    path: list[int],
    apply_rule: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    """Apply pin right-track (or RAM); Human Hands orchestration runs post-stamps in pipeline."""
    canonical, _pin, _left, right = get_pin_tracks(rules, pin_effect)
    if canonical == "random_access_memory" or (
        right and right.get("type") == "pin_memory_replay"
    ):
        return apply_pin_memory(
            rules=rules,
            loadout=loadout,
            state=state,
            board=board,
            path=path,
            apply_rule=apply_rule,
        )
    if not right or right.get("type") in ("human_hands_pin",):
        return state
    game_class = ""
    if _pin:
        game_class = str(_pin.get("game_class", "") or "")
    state = apply_rule(right, state, board, path, loadout, 1)
    track = "right"
    rule_id = str(right.get("type", pin_effect))
    if state.get("_trace") is not None:
        state["_trace"].append(
            {
                "phase": "pin",
                "track": track,
                "rule_id": rule_id,
                "game_class": game_class,
                "detail": f"pin {canonical or pin_effect}",
            }
        )
    return state


def pin_in_catalog(rules: dict[str, Any], pin_effect: str) -> bool:
    return resolve_rule_id(rules, "pins", pin_effect, pin_effect) is not None
