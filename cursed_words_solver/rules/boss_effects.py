"""Boss scaling and word constraints (wiki Main Bosses)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from cursed_words_solver.models import Loadout
from cursed_words_solver.rules.rule_lookup import get_rule, resolve_rule_id

_RULES_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "wiki" / "stickers.json"
)
_TAXONOMY_PATH = Path(__file__).resolve().parents[2] / "data" / "game" / "boss_taxonomy.json"


@lru_cache(maxsize=1)
def load_rules_catalog() -> dict[str, Any]:
    if not _RULES_PATH.exists():
        return {"bosses": {}}
    data = json.loads(_RULES_PATH.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {"bosses": {}}


@dataclass(frozen=True)
class BossContext:
    area: int
    cursed: bool
    rule: dict[str, Any] | None
    rule_key: str | None


@dataclass(frozen=True)
class BossConstraints:
    min_len: int = 1
    max_len: int = 15
    blocked: bool = False
    block_reason: str = ""


def _extra_int(loadout: Loadout, key: str, default: int) -> int:
    try:
        return int((loadout.extras or {}).get(key, default))
    except (TypeError, ValueError):
        return default


def _extra_bool(loadout: Loadout, key: str) -> bool:
    val = (loadout.extras or {}).get(key, False)
    return val in (True, "true", "True", "1", 1)


def boss_area_number(loadout: Loadout) -> int:
    area = _extra_int(loadout, "boss_area_number", 1)
    return max(1, min(5, area))


def boss_is_cursed(loadout: Loadout) -> bool:
    return _extra_bool(loadout, "boss_cursed")


def get_active_boss_rule(
    rules: dict[str, Any], loadout: Loadout
) -> tuple[str | None, dict[str, Any] | None]:
    ruleset = get_active_boss_rules(rules, loadout)
    if not ruleset:
        return None, None
    return ruleset[0]


def active_boss_ids(loadout: Loadout) -> list[str]:
    """Current active boss modifier ids for this phase.

    When `extras.boss_modifiers` is present, it is treated as source of truth and can be empty
    (important for Michael phases with no copied effects).
    """
    extras = loadout.extras if isinstance(loadout.extras, dict) else {}
    if "boss_modifiers" in extras:
        raw = extras.get("boss_modifiers")
        rows: list[Any]
        if isinstance(raw, list):
            rows = raw
        elif isinstance(raw, str):
            rows = [s.strip() for s in raw.split(",") if s.strip()]
        else:
            rows = []
        out: list[str] = []
        for entry in rows:
            item = str(entry or "").strip().lower()
            if item and item not in out:
                out.append(item)
        return out
    primary = str(loadout.boss_id or "").strip().lower()
    if primary:
        return [primary]
    return []


def get_active_boss_rules(
    rules: dict[str, Any], loadout: Loadout
) -> list[tuple[str, dict[str, Any]]]:
    extras = loadout.extras if isinstance(loadout.extras, dict) else {}
    ids = active_boss_ids(loadout)
    resolved: list[tuple[str, dict[str, Any]]] = []
    seen: set[str] = set()
    if ids:
        for boss_id in ids:
            key, rule = get_rule(rules, "bosses", boss_id, boss_id)
            if not key or not rule:
                continue
            if key in seen:
                continue
            seen.add(key)
            resolved.append((key, rule))
        return resolved
    if "boss_modifiers" in extras:
        # Explicit empty modifiers means "no copied boss effects this phase".
        return resolved
    if not (loadout.boss_id or loadout.boss_name):
        return resolved
    key, rule = get_rule(rules, "bosses", loadout.boss_id, loadout.boss_name)
    if key and rule and key not in seen:
        resolved.append((key, rule))
    return resolved


def boss_context(loadout: Loadout, rules: dict[str, Any]) -> BossContext:
    key, rule = get_active_boss_rule(rules, loadout)
    return BossContext(
        area=boss_area_number(loadout),
        cursed=boss_is_cursed(loadout),
        rule=rule,
        rule_key=key,
    )


def resolve_boss_scaling(
    rule: dict[str, Any],
    area: int,
    cursed: bool,
    *,
    field: str = "value",
) -> int | float | None:
    """Return scaling field for area (1-5); None if N/A or missing."""
    rows = rule.get("scaling")
    if not isinstance(rows, list):
        return None
    row = None
    for entry in rows:
        if isinstance(entry, dict) and entry.get("area") == area:
            row = entry
            break
    if row is None:
        return None
    if row.get("na"):
        return None
    if cursed:
        if f"cursed_{field}" in row:
            key = f"cursed_{field}"
        elif "cursed" in row:
            key = "cursed"
        else:
            key = field
    else:
        key = field
    if key not in row:
        return None
    val = row[key]
    if isinstance(val, (int, float)):
        return val
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def effective_target_score_multiplier(loadout: Loadout, rules: dict[str, Any]) -> float:
    ctx = boss_context(loadout, rules)
    if not ctx.rule or ctx.rule.get("type") != "boss_target_score_multiplier":
        return 1.0
    mult = resolve_boss_scaling(ctx.rule, ctx.area, ctx.cursed, field="multiplier")
    if mult is None or mult <= 0:
        return 1.0
    return float(mult)


def boss_word_constraints(
    loadout: Loadout, rules: dict[str, Any], *, default_max_len: int = 15
) -> BossConstraints:
    michael_min = 0
    extras = loadout.extras if isinstance(loadout.extras, dict) else {}
    for key in ("michael_min_word_length", "michael_phase_min_word_length"):
        if key not in extras:
            continue
        try:
            michael_min = max(michael_min, int(extras.get(key) or 0))
        except (TypeError, ValueError):
            continue

    if _extra_bool(loadout, "hyena_blocked"):
        return BossConstraints(
            blocked=True,
            block_reason="Hyena: sell a sticker or stamp before submitting",
        )

    ctx = boss_context(loadout, rules)
    if not ctx.rule:
        min_len = 1
        if michael_min > 0:
            min_len = max(min_len, michael_min)
        return BossConstraints(min_len=min_len, max_len=default_max_len)

    effect_type = ctx.rule.get("type", "")
    min_len = 1
    max_len = default_max_len

    if effect_type == "boss_word_min_length":
        v = resolve_boss_scaling(ctx.rule, ctx.area, ctx.cursed, field="min_length")
        if v is not None:
            min_len = max(1, int(v))
    elif effect_type == "boss_word_max_length":
        v = resolve_boss_scaling(ctx.rule, ctx.area, ctx.cursed, field="max_length")
        if v is not None:
            max_len = max(1, int(v))

    # Cretaceous Meg (bossdino alias) uses the standard minimum word length
    # even though the wiki entry is `type="custom"` without explicit constraints.
    if min_len == 1 and (ctx.rule_key or "").strip().lower() == "cretaceous_meg":
        min_len = 3

    if michael_min > 0:
        min_len = max(min_len, michael_min)
    return BossConstraints(min_len=min_len, max_len=max_len)


@lru_cache(maxsize=1)
def load_boss_taxonomy() -> dict[str, Any]:
    if not _TAXONOMY_PATH.is_file():
        return {"bosses": {}}
    return json.loads(_TAXONOMY_PATH.read_text(encoding="utf-8"))


def boss_scoring_effect_type(rule: dict[str, Any] | None) -> str:
    """Resolved scoring handler id (catalog type or boss_effect_type)."""
    if not rule:
        return ""
    return str(rule.get("boss_effect_type") or rule.get("type") or "")


def boss_grid_handler(rule: dict[str, Any] | None) -> str:
    if not rule:
        return ""
    return str(rule.get("grid_handler") or "")


def boss_rule_applies(rule: dict[str, Any], ctx: BossContext) -> bool:
    """False when wiki marks this area as N/A (e.g. Robo-Monkey area 5)."""
    scaling = rule.get("scaling")
    if not isinstance(scaling, list):
        return True
    for entry in scaling:
        if isinstance(entry, dict) and entry.get("area") == ctx.area:
            return not entry.get("na")
    return False
