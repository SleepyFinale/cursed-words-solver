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

# Meta bosses with no gameplay rules when stacked under Michael.
_META_BOSS_SLUGS = frozenset(
    {
        "michael",
        "ogre",
        "sandy_saguaro",
        "prismatic_bean",
        "human_boy",
        "human_boy_boss",
        "bosshumanboy",
    }
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


def michael_summoned_bosses_defeated(loadout: Loadout) -> bool:
    return _extra_bool(loadout, "michael_summoned_bosses_defeated")


def michael_puzzle_grid_active(loadout: Loadout) -> bool:
    return _extra_bool(loadout, "michael_puzzle_grid")


def _michael_min_word_length_value(loadout: Loadout) -> int:
    extras = loadout.extras if isinstance(loadout.extras, dict) else {}
    michael_min = 0
    for key in ("michael_min_word_length", "michael_phase_min_word_length"):
        if key not in extras:
            continue
        try:
            michael_min = max(michael_min, int(extras.get(key) or 0))
        except (TypeError, ValueError):
            continue
    return michael_min


def _parse_boss_modifier_ids(loadout: Loadout) -> list[str]:
    extras = loadout.extras if isinstance(loadout.extras, dict) else {}
    if "boss_modifiers" not in extras:
        return []
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
        if item and item not in _META_BOSS_SLUGS and item not in out:
            out.append(item)
    return out


def _encounter_min_word_length_value(loadout: Loadout) -> int:
    return _extra_int(loadout, "encounter_min_word_length", 0)


def _encounter_finale_length_pin(
    loadout: Loadout, default_max_len: int
) -> BossConstraints | None:
    """Pin exact board length when encounter exports live min but finale flags lag."""
    encounter_min = _encounter_min_word_length_value(loadout)
    if encounter_min <= 0 or encounter_min < default_max_len:
        return None
    if not _michael_context(loadout):
        return None
    if _michael_probe_summoned_defeated(loadout) is False:
        return None
    if _michael_phase_value(loadout) >= 4 or michael_summoned_bosses_defeated(loadout):
        return BossConstraints(min_len=encounter_min, max_len=encounter_min)
    return None


def _michael_probe_summoned_defeated(loadout: Loadout) -> bool | None:
    """Parse companion probe: summoned_defeated=0 means draft bosses still active."""
    extras = loadout.extras if isinstance(loadout.extras, dict) else {}
    probe = str(extras.get("michael_finale_probe") or "").strip()
    if not probe:
        return None
    for part in probe.split(","):
        piece = part.strip()
        if not piece.startswith("summoned_defeated="):
            continue
        value = piece.split("=", 1)[1].strip()
        if value == "1":
            return True
        if value == "0":
            return False
    return None


def michael_finale_active(loadout: Loadout, *, default_max_len: int = 0) -> bool:
    """Michael phase 4 / wordsmith finale: no stacked draft bosses, 25-tile word."""
    extras = loadout.extras if isinstance(loadout.extras, dict) else {}
    probe_defeated = _michael_probe_summoned_defeated(loadout)
    if probe_defeated is False:
        return False

    if michael_puzzle_grid_active(loadout):
        return True
    if str(extras.get("encounter_mode") or "").strip().lower() == "puzzle":
        return True

    if michael_summoned_bosses_defeated(loadout):
        return True
    if probe_defeated is True:
        return True

    return _michael_finale_fallback_active(loadout, _parse_boss_modifier_ids(loadout))


def _michael_context(loadout: Loadout) -> bool:
    extras = loadout.extras if isinstance(loadout.extras, dict) else {}
    if michael_puzzle_grid_active(loadout):
        return True
    if str(extras.get("encounter_mode") or "").strip().lower() == "puzzle":
        return True
    if _extra_int(loadout, "boss_area_number", 0) >= 6:
        return True
    boss_id = str(loadout.boss_id or "").strip().lower()
    boss_name = str(loadout.boss_name or "").strip().lower()
    if boss_id == "michael" or "michael" in boss_name:
        return True
    if any(k.startswith("michael_") for k in extras):
        return True
    raw_mods = extras.get("boss_modifiers")
    if isinstance(raw_mods, list):
        return any(str(entry or "").strip().lower() == "michael" for entry in raw_mods)
    if isinstance(raw_mods, str):
        try:
            parsed = json.loads(raw_mods)
            if isinstance(parsed, list):
                return any(str(entry or "").strip().lower() == "michael" for entry in parsed)
        except json.JSONDecodeError:
            parts = [p.strip().lower() for p in raw_mods.split(",") if p.strip()]
            return "michael" in parts
    return False


def _michael_phase_value(loadout: Loadout) -> int:
    return _extra_int(loadout, "michael_phase", 0)


def _michael_finale_fallback_active(loadout: Loadout, active_modifiers: list[str]) -> bool:
    if not _michael_context(loadout):
        return False
    if _michael_probe_summoned_defeated(loadout) is False:
        return False
    if not michael_summoned_bosses_defeated(loadout):
        return False
    phase = _michael_phase_value(loadout)
    if phase >= 4:
        return True
    extras = loadout.extras if isinstance(loadout.extras, dict) else {}
    # Michael finale removes copied boss effects; exports can encode this as explicit empty.
    if "boss_modifiers" in extras and not active_modifiers and phase >= 3:
        return True
    return False


def _parse_boss_modifier_floor_mods(loadout: Loadout) -> dict[str, int]:
    extras = loadout.extras if isinstance(loadout.extras, dict) else {}
    raw = extras.get("boss_modifier_floor_mods")
    if raw is None:
        return {}
    parsed: dict[str, Any]
    if isinstance(raw, dict):
        parsed = raw
    elif isinstance(raw, str) and raw.strip():
        try:
            loaded = json.loads(raw)
            parsed = loaded if isinstance(loaded, dict) else {}
        except json.JSONDecodeError:
            return {}
    else:
        return {}
    out: dict[str, int] = {}
    for key, val in parsed.items():
        slug = str(key or "").strip().lower()
        if not slug:
            continue
        try:
            out[slug] = max(0, int(val))
        except (TypeError, ValueError):
            continue
    return out


def floor_mod_for_rule(
    loadout: Loadout,
    rules: dict[str, Any],
    rule_key: str | None,
    rule: dict[str, Any] | None,
) -> int | None:
    """Live FloorAdjustedModification for one stacked boss (Michael drafts)."""
    if not rule_key:
        return None
    key = str(rule_key).strip().lower()
    floor_mods = _parse_boss_modifier_floor_mods(loadout)
    if key in floor_mods:
        return floor_mods[key]
    canonical = resolve_rule_id(rules, "bosses", key, key) or key
    if canonical in floor_mods:
        return floor_mods[canonical]
    return None


def resolve_boss_scaling_for_rule(
    loadout: Loadout,
    rules: dict[str, Any],
    rule_key: str | None,
    rule: dict[str, Any],
    *,
    field: str = "value",
) -> int | float | None:
    """Scaling for one boss rule: per-modifier floor mod, else wiki area table."""
    live = floor_mod_for_rule(loadout, rules, rule_key, rule)
    if live is not None and live > 0 and field == "value":
        return live
    ctx = boss_context(loadout, rules)
    return resolve_boss_scaling(rule, ctx.area, ctx.cursed, field=field)


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
    if michael_finale_active(loadout):
        return []
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
            if item and item not in _META_BOSS_SLUGS and item not in out:
                out.append(item)
        return out
    primary = str(loadout.boss_id or "").strip().lower()
    if primary and primary not in _META_BOSS_SLUGS:
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
    mult = 1.0
    ctx = boss_context(loadout, rules)
    for key, rule in get_active_boss_rules(rules, loadout):
        if not rule or rule.get("type") != "boss_target_score_multiplier":
            continue
        if not boss_rule_applies(rule, ctx):
            continue
        row_mult = resolve_boss_scaling(rule, ctx.area, ctx.cursed, field="multiplier")
        if row_mult is not None and row_mult > 0:
            mult *= float(row_mult)
    return mult if mult > 0 else 1.0


def boss_word_constraints(
    loadout: Loadout, rules: dict[str, Any], *, default_max_len: int = 15
) -> BossConstraints:
    extras = loadout.extras if isinstance(loadout.extras, dict) else {}
    michael_min = _michael_min_word_length_value(loadout)
    encounter_min = _encounter_min_word_length_value(loadout)
    if encounter_min > 0:
        michael_min = max(michael_min, encounter_min)

    if michael_finale_active(loadout, default_max_len=default_max_len):
        candidates = [
            v
            for v in (michael_min, encounter_min, default_max_len)
            if v > 0
        ]
        fin_len = max(candidates) if candidates else default_max_len
        return BossConstraints(
            min_len=fin_len,
            max_len=fin_len,
        )

    pinned = _encounter_finale_length_pin(loadout, default_max_len)
    if pinned is not None:
        return pinned

    if _extra_bool(loadout, "hyena_blocked"):
        return BossConstraints(
            blocked=True,
            block_reason="Hyena: sell a sticker or stamp before submitting",
        )

    ctx = boss_context(loadout, rules)
    active = get_active_boss_rules(rules, loadout)
    min_len = 1
    max_len = default_max_len

    for key, rule in active:
        if not rule:
            continue
        effect_type = rule.get("type", "")
        if effect_type == "boss_word_min_length":
            live = extras.get("cobra_min_length")
            if live is not None and str(key).lower() == "cobra":
                try:
                    min_len = max(min_len, int(live))
                except (TypeError, ValueError):
                    pass
            v = resolve_boss_scaling_for_rule(
                loadout, rules, key, rule, field="min_length"
            )
            if v is not None:
                min_len = max(min_len, max(1, int(v)))
            live_mod = floor_mod_for_rule(loadout, rules, key, rule)
            if live_mod is not None and live_mod > 0:
                min_len = max(min_len, live_mod)
        elif effect_type == "boss_word_max_length":
            live = extras.get("wolf_max_length")
            if live is not None and str(key).lower() == "wolf":
                try:
                    max_len = min(max_len, int(live))
                except (TypeError, ValueError):
                    pass
            v = resolve_boss_scaling_for_rule(
                loadout, rules, key, rule, field="max_length"
            )
            if v is not None:
                max_len = min(max_len, max(1, int(v)))
            live_mod = floor_mod_for_rule(loadout, rules, key, rule)
            if live_mod is not None and live_mod > 0:
                max_len = min(max_len, live_mod)
        elif (key or "").strip().lower() == "cretaceous_meg":
            min_len = max(min_len, 3)

    if not active:
        min_len = 1
        stale_finale_extras = (
            _michael_probe_summoned_defeated(loadout) is False and _michael_context(loadout)
        )
        if michael_min > 0 and not (
            stale_finale_extras and michael_min >= default_max_len
        ):
            min_len = max(min_len, michael_min)
        elif (
            not stale_finale_extras
            and _michael_context(loadout)
            and _michael_phase_value(loadout) >= 3
        ):
            # Defensive fallback: late Michael phases should never drop back to 1-letter words.
            min_len = max(min_len, default_max_len)
        return BossConstraints(min_len=min_len, max_len=default_max_len)

    stale_finale_extras = (
        _michael_probe_summoned_defeated(loadout) is False and _michael_context(loadout)
    )
    if michael_min > 0 and not (
        stale_finale_extras and michael_min >= default_max_len
    ):
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
    effect = str(rule.get("boss_effect_type") or rule.get("type") or "")
    if effect != "custom":
        return effect
    name = str(rule.get("name") or "").strip().lower()
    wiki = str(rule.get("wiki_page") or "").strip().lower()
    if name == "fox" or wiki == "fox":
        return "boss_steal_money"
    return effect


def boss_grid_handler(rule: dict[str, Any] | None) -> str:
    if not rule:
        return ""
    handler = str(rule.get("grid_handler") or "")
    if handler:
        return handler
    name = str(rule.get("name") or "").strip().lower().replace(" ", "_")
    fallback = {
        "mole": "mole_void",
        "axolotl": "axolotl_q",
        "bison": "bison_numbers",
        "yeti_crab": "yeti_colorless",
        "robo-eel": "robo_eel_eat",
        "robo_eel": "robo_eel_eat",
        "bat": "bat_shrink",
        "fox": "fox_grid_steal",
    }
    return fallback.get(name, "")


def boss_rule_applies(rule: dict[str, Any], ctx: BossContext) -> bool:
    """False when wiki marks this area as N/A (e.g. Robo-Monkey area 5)."""
    scaling = rule.get("scaling")
    if not isinstance(scaling, list):
        return True
    for entry in scaling:
        if isinstance(entry, dict) and entry.get("area") == ctx.area:
            return not entry.get("na")
    return False
