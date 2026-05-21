"""Resolve sticker/stamp/boss/pin rules by id, alias, or display name."""

from __future__ import annotations

import re
from typing import Any

from cursed_words_solver.models import Loadout, LoadoutItem


def slugify_name(name: str) -> str:
    """Match MelonLoader RunStateExporter.Slugify fallback from display name."""
    raw = (name or "").strip().lower()
    if not raw:
        return "unknown"
    slug = re.sub(r"[^a-z0-9]+", "_", raw).strip("_")
    return slug or "unknown"


def _alias_map(rules: dict[str, Any], bucket: str) -> dict[str, str]:
    aliases = rules.get("aliases", {})
    bucket_aliases = aliases.get(bucket, {})
    if isinstance(bucket_aliases, dict):
        return {str(k).lower(): str(v) for k, v in bucket_aliases.items()}
    return {}


def resolve_rule_id(
    rules: dict[str, Any],
    bucket: str,
    item_id: str,
    item_name: str = "",
) -> str | None:
    """Return canonical rule key if known, else None."""
    catalog = rules.get(bucket, {})
    if not isinstance(catalog, dict):
        return None

    candidates = [
        (item_id or "").strip().lower(),
        slugify_name(item_name),
    ]
    alias_map = _alias_map(rules, bucket)

    for raw in candidates:
        if not raw or raw == "unknown":
            continue
        canonical = alias_map.get(raw, raw)
        if canonical in catalog:
            return canonical

    return None


def get_rule(
    rules: dict[str, Any],
    bucket: str,
    item_id: str,
    item_name: str = "",
) -> tuple[str | None, dict[str, Any] | None]:
    key = resolve_rule_id(rules, bucket, item_id, item_name)
    if key is None:
        return None, None
    rule = rules.get(bucket, {}).get(key)
    if isinstance(rule, dict):
        return key, rule
    return key, None


def get_pin_branch_rule(
    rules: dict[str, Any],
    pin_id: str,
    pin_branch: str,
) -> dict[str, Any] | None:
    canonical = resolve_rule_id(rules, "pins", pin_id, pin_id) or pin_id
    pin_rule = rules.get("pins", {}).get(canonical)
    if not isinstance(pin_rule, dict):
        return None

    branches = pin_rule.get("branches")
    if isinstance(branches, dict):
        branch = (pin_branch or "").strip().lower()
        if branch in branches:
            return branches[branch]
        if "" in branches:
            return branches[""]
        if "default" in branches:
            return branches["default"]
    effect_type = pin_rule.get("type", "")
    if effect_type in ("unmodeled", "custom", ""):
        return None
    return pin_rule


def collect_unmapped_items(
    rules: dict[str, Any],
    loadout: Loadout,
) -> list[str]:
    """Human-readable list of loadout items with no catalog rule."""
    missing: list[str] = []

    for sticker in loadout.stickers:
        if resolve_rule_id(rules, "stickers", sticker.id, sticker.name) is None:
            missing.append(f"sticker:{sticker.id or sticker.name}")

    for stamp in loadout.stamps:
        if resolve_rule_id(rules, "stamps", stamp.id, stamp.name) is None:
            missing.append(f"stamp:{stamp.id or stamp.name}")

    if loadout.boss_id or loadout.boss_name:
        if resolve_rule_id(rules, "bosses", loadout.boss_id, loadout.boss_name) is None:
            missing.append(f"boss:{loadout.boss_id or loadout.boss_name}")

    pin_effect = loadout.extras.get("pin_effect", "")
    if pin_effect:
        pin_key = str(pin_effect).strip().lower()
        pins = rules.get("pins", {})
        pin_aliases = _alias_map(rules, "pins")
        canonical = pin_aliases.get(pin_key, pin_key)
        if canonical not in pins and pin_key not in pins:
            if get_pin_branch_rule(rules, canonical, loadout.pin_branch) is None:
                if get_pin_branch_rule(rules, pin_key, loadout.pin_branch) is None:
                    missing.append(f"pin:{pin_effect}")

    return missing


def count_mapped_items(rules: dict[str, Any], loadout: Loadout) -> tuple[int, int]:
    """Return (mapped_count, total_count) for stickers, stamps, boss, pin."""
    total = len(loadout.stickers) + len(loadout.stamps)
    if loadout.boss_id or loadout.boss_name:
        total += 1
    pin_effect = loadout.extras.get("pin_effect", "")
    if pin_effect:
        total += 1

    mapped = sum(
        1
        for s in loadout.stickers
        if resolve_rule_id(rules, "stickers", s.id, s.name)
    )
    mapped += sum(
        1 for s in loadout.stamps if resolve_rule_id(rules, "stamps", s.id, s.name)
    )
    if loadout.boss_id or loadout.boss_name:
        if resolve_rule_id(rules, "bosses", loadout.boss_id, loadout.boss_name):
            mapped += 1
    if pin_effect:
        pin_key = str(pin_effect).strip().lower()
        pins = rules.get("pins", {})
        pin_aliases = _alias_map(rules, "pins")
        canonical = pin_aliases.get(pin_key, pin_key)
        if canonical in pins or pin_key in pins:
            mapped += 1
        elif get_pin_branch_rule(rules, canonical, loadout.pin_branch):
            mapped += 1

    return mapped, total
