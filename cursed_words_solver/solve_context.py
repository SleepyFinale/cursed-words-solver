"""Immutable per-solve loadout flags (computed once at find_best_words entry)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cursed_words_solver.models import Loadout
from cursed_words_solver.rules.boss_effects import (
    BossContext,
    boss_context,
    boss_scoring_effect_type,
    get_active_boss_rule,
    get_active_boss_rules,
)
from cursed_words_solver.rules.boss_scoring import EARLY_BOSS_TYPES
from cursed_words_solver.rules.rule_lookup import get_pin_scoring_rule, get_rule, resolve_rule_id
from cursed_words_solver.rules.scoring_conditions import (
    bicycle_word_per_card,
    bicycle_word_score_accumulator,
    shield_blue_base_from_loadout,
    sticker_rule_int,
)
from cursed_words_solver.rules.scoring_order import (
    ScoringItemRef,
    _inventory_item_refs,
    capybara_shuffles_loadout,
    hourglass_reverses_order,
)
from cursed_words_solver.rules.stamp_behaviors import (
    SearchFlagsMask,
    loadout_has_stamp,
    stamp_search_flags_mask,
)

_BICYCLE_PIN_EFFECTS = frozenset({"bicycle", "bones_the_dog", "bones"})
_SETUP_STICKER_IDS = frozenset(
    {
        "birthday_cake",
        "hi_vis_jacket",
        "michaels_book",
        "michael_book",
        "red_rider",
    }
)
_SETUP_STAMP_IDS = frozenset({"tile_ninja"})
_SAFE_BOSS_EFFECTS = frozenset(EARLY_BOSS_TYPES) | frozenset(
    {
        "boss_steal_money",
        "",
    }
)


def hanafuda_sticker_level(loadout: Loadout) -> int:
    """Sticker level for Hanafuda (0 if absent)."""
    for item in loadout.stickers:
        slug = (item.id or item.name or "").strip().lower().replace(" ", "_")
        if slug == "hanafuda":
            return max(1, int(item.level or 1))
    return 0


def _parse_percent_list(raw: str) -> tuple[int, ...] | None:
    percents: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            value = int(part)
        except (TypeError, ValueError):
            return None
        if value > 0:
            percents.append(value)
    return tuple(percents) if percents else None


def _compound_percents_from_loadout(loadout: Loadout | None) -> tuple[int, ...] | None:
    if loadout is None:
        return None
    raw = str(
        (loadout.extras or {}).get("compound_word_percents_on_tile_sum", "")
    ).strip()
    if not raw:
        return None
    return _parse_percent_list(raw)


def _sticker_level(item) -> int:
    return max(1, int(item.level or 1))


def _word_length_bonus_meta(
    loadout: Loadout, rules: dict
) -> tuple[int, int]:
    max_bonus = 0
    min_len = 4
    for bucket, items in (("stickers", loadout.stickers), ("stamps", loadout.stamps)):
        for item in items:
            _key, rule = get_rule(rules, bucket, item.id or "", item.name or "")
            if not rule or rule.get("type") != "word_length_bonus":
                continue
            level = _sticker_level(item)
            max_bonus = max(max_bonus, sticker_rule_int(level, rule))
            min_len = max(min_len, int(rule.get("min_length", 4)))
    return max_bonus, min_len


def _always_add_word_bonus(loadout: Loadout, rules: dict) -> int:
    total = 0
    for bucket, items in (("stickers", loadout.stickers), ("stamps", loadout.stamps)):
        for item in items:
            _key, rule = get_rule(rules, bucket, item.id or "", item.name or "")
            if not rule or rule.get("type") != "add_word_score":
                continue
            if str(rule.get("condition") or "") not in ("always", ""):
                continue
            total += sticker_rule_int(_sticker_level(item), rule)
    return total


def _red_tile_bonus_per_red(loadout: Loadout, rules: dict) -> int:
    best = 0
    for item in loadout.stickers:
        _key, rule = get_rule(rules, "stickers", item.id or "", item.name or "")
        if not rule or rule.get("type") != "red_tile_bonus":
            continue
        best = max(best, sticker_rule_int(_sticker_level(item), rule))
    return best


def _pin_word_bonus_per_tile(loadout: Loadout, rules: dict) -> int:
    pin_effect = str(
        (loadout.extras or {}).get("pin_effect", "")
        or (loadout.extras or {}).get("PinEffect", "")
        or ""
    ).strip().lower()
    if pin_effect not in _BICYCLE_PIN_EFFECTS:
        return 0
    canonical = resolve_rule_id(rules, "pins", pin_effect, "") or "bones_the_dog"
    rule = get_pin_scoring_rule(rules, canonical)
    if not rule or rule.get("type") != "cards_submitted_word_bonus":
        return 0
    return bicycle_word_per_card(loadout, rule)


def _bicycle_word_accumulator(loadout: Loadout, rules: dict) -> int:
    pin_effect = str(
        (loadout.extras or {}).get("pin_effect", "")
        or (loadout.extras or {}).get("PinEffect", "")
        or ""
    ).strip().lower()
    if pin_effect not in _BICYCLE_PIN_EFFECTS:
        return 0
    canonical = resolve_rule_id(rules, "pins", pin_effect, "") or "bones_the_dog"
    rule = get_pin_scoring_rule(rules, canonical)
    if not rule or rule.get("type") != "cards_submitted_word_bonus":
        return 0
    return bicycle_word_score_accumulator(loadout)


def _hanafuda_per_unused(loadout: Loadout, rules: dict) -> int:
    level = hanafuda_sticker_level(loadout)
    if level <= 0:
        return 0
    _key, rule = get_rule(rules, "stickers", "hanafuda", "Hanafuda")
    if not rule or rule.get("type") != "card_hand_word_bonus":
        return 0
    return sticker_rule_int(level, rule)


def _boss_blocks_tier2_screen(loadout: Loadout, rules: dict) -> bool:
    for _key, boss in get_active_boss_rules(rules, loadout):
        if not boss:
            continue
        effect = boss_scoring_effect_type(boss)
        if effect in _SAFE_BOSS_EFFECTS:
            continue
        if effect in EARLY_BOSS_TYPES:
            continue
        return True
    if loadout.boss_effect and str(loadout.boss_effect).strip():
        return True
    return False


def _slot_order(count: int, *, hourglass: bool) -> tuple[int, ...]:
    slots = tuple(range(count))
    return tuple(reversed(slots)) if hourglass else slots


def _grid_tile_multiply_first(extras: dict) -> bool:
    return str(extras.get("grid_tile_multiply_first", "")).lower() in (
        "1",
        "true",
        "yes",
    )


def _tier2_screen_enabled(loadout: Loadout, rules: dict, *, hourglass: bool) -> bool:
    if not loadout.stickers and not loadout.stamps:
        return False
    if hourglass:
        return False
    if _compound_percents_from_loadout(loadout):
        return False
    extras = loadout.extras or {}
    if str(extras.get("compound_word_finalize_at_cocktail", "")).lower() in (
        "1",
        "true",
        "yes",
    ):
        return False
    if _boss_blocks_tier2_screen(loadout, rules):
        return False
    return True


@dataclass(frozen=True)
class SolveContext:
    hourglass_reversed: bool
    shield_blue_base: int | None
    search_flags: SearchFlagsMask
    compound_percents: tuple[int, ...] | None
    active_boss_id: str
    active_boss_rules: tuple[tuple[str, dict[str, Any] | None], ...]
    boss_ctx: BossContext
    inventory_refs: tuple[ScoringItemRef, ...]
    capybara_shuffles: bool
    sticker_slot_order: tuple[int, ...] = ()
    stamp_slot_order: tuple[int, ...] = ()
    grid_tile_multiply_first: bool = False
    microscope_base: bool = False
    hanafuda_level: int = 0
    compound_finalize_at_cocktail: bool = False
    max_word_length_bonus: int = 0
    word_length_min: int = 4
    pin_word_bonus_per_tile: int = 0
    bicycle_word_accumulator: int = 0
    always_add_word_bonus: int = 0
    red_tile_bonus_per_red: int = 0
    hanafuda_per_unused: int = 0
    tier2_screen_enabled: bool = False


def build_solve_context(loadout: Loadout, rules: dict) -> SolveContext:
    extras = loadout.extras or {}
    hourglass = hourglass_reverses_order(loadout, rules)
    max_wl_bonus, wl_min = _word_length_bonus_meta(loadout, rules)
    boss_key, _boss_rule = get_active_boss_rule(rules, loadout)
    active_boss_rules = tuple(get_active_boss_rules(rules, loadout))
    if not active_boss_rules:
        active_boss_rules = (
            ((boss_key or "", _boss_rule),) if _boss_rule is not None else ()
        )
    return SolveContext(
        hourglass_reversed=hourglass,
        shield_blue_base=shield_blue_base_from_loadout(loadout, rules),
        search_flags=stamp_search_flags_mask(loadout),
        compound_percents=_compound_percents_from_loadout(loadout),
        active_boss_id=boss_key or loadout.boss_id or "",
        active_boss_rules=active_boss_rules,
        boss_ctx=boss_context(loadout, rules),
        inventory_refs=tuple(_inventory_item_refs(loadout, rules)),
        capybara_shuffles=capybara_shuffles_loadout(loadout, rules),
        sticker_slot_order=_slot_order(len(loadout.stickers), hourglass=hourglass),
        stamp_slot_order=_slot_order(len(loadout.stamps), hourglass=hourglass),
        grid_tile_multiply_first=_grid_tile_multiply_first(extras),
        microscope_base=loadout_has_stamp(loadout, "microscope"),
        hanafuda_level=hanafuda_sticker_level(loadout),
        compound_finalize_at_cocktail=str(
            extras.get("compound_word_finalize_at_cocktail", "")
        ).lower()
        in ("1", "true", "yes"),
        max_word_length_bonus=max_wl_bonus,
        word_length_min=wl_min,
        pin_word_bonus_per_tile=_pin_word_bonus_per_tile(loadout, rules),
        bicycle_word_accumulator=_bicycle_word_accumulator(loadout, rules),
        always_add_word_bonus=_always_add_word_bonus(loadout, rules),
        red_tile_bonus_per_red=_red_tile_bonus_per_red(loadout, rules),
        hanafuda_per_unused=_hanafuda_per_unused(loadout, rules),
        tier2_screen_enabled=_tier2_screen_enabled(loadout, rules, hourglass=hourglass),
    )


def tier2_setup_blocks_screen(loadout: Loadout) -> bool:
    """True when setup-weighted ranking adds uncaptured future value."""
    for item in loadout.stickers:
        sid = (item.id or "").lower()
        if sid in _SETUP_STICKER_IDS:
            return True
        if "birthday" in (item.name or "").lower():
            return True
    for item in loadout.stamps:
        if (item.id or "").lower() in _SETUP_STAMP_IDS:
            return True
    return False
