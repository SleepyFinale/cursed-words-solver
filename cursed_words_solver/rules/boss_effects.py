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
    min_len: int = 3
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
    if not (loadout.boss_id or loadout.boss_name):
        return None, None
    key, rule = get_rule(rules, "bosses", loadout.boss_id, loadout.boss_name)
    if not rule:
        return None, None
    return key, rule


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
    if _extra_bool(loadout, "hyena_blocked"):
        return BossConstraints(
            blocked=True,
            block_reason="Hyena: sell a sticker or stamp before submitting",
        )

    ctx = boss_context(loadout, rules)
    if not ctx.rule:
        return BossConstraints(max_len=default_max_len)

    effect_type = ctx.rule.get("type", "")
    min_len = 3
    max_len = default_max_len

    if effect_type == "boss_word_min_length":
        v = resolve_boss_scaling(ctx.rule, ctx.area, ctx.cursed, field="min_length")
        if v is not None:
            min_len = max(1, int(v))
    elif effect_type == "boss_word_max_length":
        v = resolve_boss_scaling(ctx.rule, ctx.area, ctx.cursed, field="max_length")
        if v is not None:
            max_len = max(1, int(v))

    return BossConstraints(min_len=min_len, max_len=max_len)


def boss_rule_applies(rule: dict[str, Any], ctx: BossContext) -> bool:
    """False when wiki marks this area as N/A (e.g. Robo-Monkey area 5)."""
    scaling = rule.get("scaling")
    if not isinstance(scaling, list):
        return True
    for entry in scaling:
        if isinstance(entry, dict) and entry.get("area") == ctx.area:
            return not entry.get("na")
    return False
