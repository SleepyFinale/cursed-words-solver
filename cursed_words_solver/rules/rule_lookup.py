"""Resolve sticker/stamp/boss/pin rules by id, alias, or display name."""



from __future__ import annotations



import re

from typing import Any



from cursed_words_solver.models import Loadout, LoadoutItem



SCORING_INACTIVE_TYPES = frozenset({"unmodeled", "custom", ""})



# Pin types that only orchestrate other effects (still count as scoring-active).

PIN_ORCHESTRATION_TYPES = frozenset({"pin_memory_replay", "human_hands_pin"})





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



    candidates: list[str] = []

    if (item_name or "").strip():

        candidates.append(slugify_name(item_name))

    id_raw = (item_id or "").strip().lower()

    if id_raw:

        candidates.append(id_raw)

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


def boss_display_name(loadout: Loadout, rules: dict[str, Any]) -> str:
    """Wiki/catalog boss name for console (e.g. Bat), not prefab labels like 4x4 Grid."""
    _, rule = get_rule(rules, "bosses", loadout.boss_id, loadout.boss_name)
    if rule and rule.get("name"):
        return str(rule["name"])
    return (loadout.boss_name or loadout.boss_id or "").strip()


def is_scoring_rule(rule: dict[str, Any] | None) -> bool:

    if not rule:

        return False

    effect_type = rule.get("type", "")

    if effect_type in PIN_ORCHESTRATION_TYPES:

        return True

    if effect_type in SCORING_INACTIVE_TYPES:

        return False

    if effect_type and effect_type != "unmodeled":

        return True

    branches = rule.get("branches")

    if isinstance(branches, dict):

        return any(

            isinstance(b, dict) and b.get("type") not in SCORING_INACTIVE_TYPES

            for b in branches.values()

        )

    return False





def _pin_has_grid_only_metadata(rule: dict[str, Any]) -> bool:

    """Grid scatter documented but no word-scoring type."""

    effect_type = rule.get("type", "")

    return effect_type in SCORING_INACTIVE_TYPES and bool(

        rule.get("grid_effect") or rule.get("effect_class") == "scatter"

    )





def get_pin_scoring_rule(

    rules: dict[str, Any],

    pin_id: str,

) -> dict[str, Any] | None:

    """Flat pin scoring rule; ignores pin_branch (left/right levels come from extras)."""

    canonical = resolve_rule_id(rules, "pins", pin_id, pin_id) or pin_id.strip().lower()

    pin_rule = rules.get("pins", {}).get(canonical)

    if not isinstance(pin_rule, dict):

        return None

    if is_scoring_rule(pin_rule):

        return pin_rule

    return None





def get_pin_branch_rule(

    rules: dict[str, Any],

    pin_id: str,

    pin_branch: str,

) -> dict[str, Any] | None:

    """Legacy branch-only pins; flat scoring pins use get_pin_scoring_rule instead."""

    canonical = resolve_rule_id(rules, "pins", pin_id, pin_id) or pin_id.strip().lower()

    pin_rule = rules.get("pins", {}).get(canonical)

    if not isinstance(pin_rule, dict):

        return None



    branches = pin_rule.get("branches")

    if isinstance(branches, dict):

        branch = (pin_branch or "").strip().lower()

        if branch in branches:

            sub = branches[branch]

            if isinstance(sub, dict) and sub.get("type") not in SCORING_INACTIVE_TYPES:

                return sub

        if "default" in branches:

            sub = branches["default"]

            if isinstance(sub, dict) and sub.get("type") not in SCORING_INACTIVE_TYPES:

                return sub

        if "" in branches:

            sub = branches[""]

            if isinstance(sub, dict) and sub.get("type") not in SCORING_INACTIVE_TYPES:

                return sub

        return None



    return get_pin_scoring_rule(rules, pin_id)





def _pin_in_catalog(rules: dict[str, Any], pin_effect: str) -> bool:

    pin_key = str(pin_effect).strip().lower()

    if not pin_key:

        return False

    pins = rules.get("pins", {})

    pin_aliases = _alias_map(rules, "pins")

    canonical = pin_aliases.get(pin_key, pin_key)

    return canonical in pins or pin_key in pins





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

    if pin_effect and not _pin_in_catalog(rules, str(pin_effect)):

        missing.append(f"pin:{pin_effect}")



    return missing





def count_catalog_items(rules: dict[str, Any], loadout: Loadout) -> tuple[int, int]:

    """Return (catalog_count, total_count) — item has a wiki key."""

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

    if pin_effect and _pin_in_catalog(rules, str(pin_effect)):

        mapped += 1



    return mapped, total





def count_scoring_items(rules: dict[str, Any], loadout: Loadout) -> tuple[int, int, int]:

    """Return (scoring_active, total, grid_only)."""

    total = len(loadout.stickers) + len(loadout.stamps)

    if loadout.boss_id or loadout.boss_name:

        total += 1

    pin_effect = loadout.extras.get("pin_effect", "")

    if pin_effect:

        total += 1



    scoring = 0

    grid_only = 0



    for sticker in loadout.stickers:

        _key, rule = get_rule(rules, "stickers", sticker.id, sticker.name)

        if rule is None:

            continue

        if rule.get("type") == "custom":

            grid_only += 1

        elif is_scoring_rule(rule):

            scoring += 1



    for stamp in loadout.stamps:

        _key, rule = get_rule(rules, "stamps", stamp.id, stamp.name)

        if rule is None:

            continue

        if rule.get("type") == "custom":

            grid_only += 1

        elif is_scoring_rule(rule):

            scoring += 1



    if loadout.boss_id or loadout.boss_name:

        _key, boss = get_rule(

            rules, "bosses", loadout.boss_id, loadout.boss_name

        )

        if boss:

            if boss.get("type") == "custom":

                grid_only += 1

            elif is_scoring_rule(boss):

                scoring += 1



    if pin_effect:

        _key, pin_rule = get_rule(rules, "pins", str(pin_effect), str(pin_effect))

        if pin_rule:

            if is_scoring_rule(pin_rule):

                scoring += 1

            elif _pin_has_grid_only_metadata(pin_rule):

                grid_only += 1



    return scoring, total, grid_only





def count_mapped_items(rules: dict[str, Any], loadout: Loadout) -> tuple[int, int]:

    """Backward-compatible alias for catalog coverage."""

    return count_catalog_items(rules, loadout)


