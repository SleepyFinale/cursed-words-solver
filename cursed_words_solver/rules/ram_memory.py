"""Random Access Memory (Nat-H4 pin): pin_memory export, blacklist, search helpers."""

from __future__ import annotations

import json
from typing import Any

from cursed_words_solver.models import Loadout
from cursed_words_solver.rules.rule_lookup import get_rule, is_scoring_rule, slugify_name

# Wiki + decompiled RandomAccessMemory.BlacklistedItemTypes (cannot be drafted into RAM).
RAM_NON_GENERATABLE_SLUGS: frozenset[str] = frozenset(
    {
        "beam_me_up",
        "crystal_ball",
        "dartboard",
        "magic_8_ball",
        "hungry_hippo",
        "lucky_dice",
        "mystery_gift",
        "nest_egg",
        "overhand",
        "sewing_needle",
        "signal_receiver",
        "snapshot",
        "underhand",
        "unicorn",
    }
)

# Effect types skipped when RAM replays ItemsInMemory (orchestration / grid-only / unmodeled).
RAM_BLACKLIST_EFFECT_TYPES: frozenset[str] = frozenset(
    {
        "snapshot",
        "beam_me_up",
        "overhand",
        "overhand_replay",
        "reverse_scoring_order",
        "shuffle_loadout_order",
        "scatter_start_grid",
        "scatter_start_encounter",
        "pin_memory_replay",
        "human_hands_pin",
        "frankenstein_stitch",
        "unmodeled",
    }
)


def pin_memory_entries(loadout: Loadout | None) -> list[dict[str, Any]]:
    """Parsed extras.pin_memory list (melmod JSON), in acquisition order."""
    if loadout is None:
        return []
    raw = (loadout.extras or {}).get("pin_memory")
    if isinstance(raw, str) and raw.strip():
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return []
    if not isinstance(raw, list):
        return []
    return [e for e in raw if isinstance(e, dict)]


def ram_entry_slug(entry: dict[str, Any]) -> str:
    return slugify_name(str(entry.get("id") or entry.get("name") or ""))


def ram_entry_bucket(entry: dict[str, Any]) -> str:
    kind = str(entry.get("kind", "sticker")).lower()
    return "stamps" if kind == "stamp" else "stickers"


def ram_entry_level(entry: dict[str, Any]) -> int:
    try:
        return int(entry.get("level", 1))
    except (TypeError, ValueError):
        return 1


def should_skip_ram_scoring(
    rules: dict[str, Any],
    entry: dict[str, Any],
) -> bool:
    """True when RAM must not replay this item for word scoring (game blacklist + non-scoring)."""
    slug = ram_entry_slug(entry)
    if slug in RAM_NON_GENERATABLE_SLUGS:
        return True
    bucket = ram_entry_bucket(entry)
    item_id = str(entry.get("id", "") or "")
    item_name = str(entry.get("name", "") or "")
    _key, rule = get_rule(rules, bucket, item_id, item_name)
    if not rule:
        return True
    effect_type = str(rule.get("type", "")).lower()
    if effect_type in RAM_BLACKLIST_EFFECT_TYPES:
        return True
    if effect_type == "custom":
        return True
    return not is_scoring_rule(rule)


def ram_has_active_pin(loadout: Loadout | None) -> bool:
    if loadout is None:
        return False
    pin = str((loadout.extras or {}).get("pin_effect", "") or "").strip().lower()
    return pin in ("random_access_memory", "ram", "nat_h4")


def pin_memory_has_birthday_cake(loadout: Loadout | None) -> bool:
    """True when Birthday Cake is stored in RAM pin memory."""
    if not ram_has_active_pin(loadout):
        return False
    for entry in pin_memory_entries(loadout):
        slug = ram_entry_slug(entry)
        if slug == "birthday_cake":
            return True
        if "birthday" in str(entry.get("name", "") or "").lower():
            return True
    return False


def birthday_cake_bonus_from_pin_memory(loadout: Loadout | None) -> int | None:
    """Accumulated word bonus embedded on Birthday Cake in pin_memory export."""
    if not ram_has_active_pin(loadout):
        return None
    for entry in pin_memory_entries(loadout):
        slug = ram_entry_slug(entry)
        name = str(entry.get("name", "") or "").lower()
        if slug != "birthday_cake" and "birthday" not in name:
            continue
        raw = entry.get("birthday_cake_bonus")
        if raw is None:
            return None
        try:
            return max(0, int(raw))
        except (TypeError, ValueError):
            return None
    return None
