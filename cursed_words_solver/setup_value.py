"""Encounter setup value for search ranking (Birthday Cake, Bicycle, rack bonuses)."""

from __future__ import annotations

from dataclasses import dataclass, field

from cursed_words_solver.models import Board, Loadout
from cursed_words_solver.rules.rule_lookup import (
    get_pin_scoring_rule,
    resolve_rule_id,
)
from cursed_words_solver.rules.scoring_conditions import (
    bicycle_word_per_card,
    consumable_count_on_path,
    birthday_cake_improve_for_path,
    suited_tiles_on_path_count,
    sticker_rule_float,
    sticker_rule_int,
)
from cursed_words_solver.rules.rule_lookup import rules_catalog
from cursed_words_solver.stamp_improve_words import (
    stamp_improve_match,
)

_SETUP_STICKER_IDS = frozenset(
    {
        "birthday_cake",
        "hi_vis_jacket",
        "michaels_book",
        "michael_book",
        "red_rider",
    }
)
_SETUP_STAMP_IDS = frozenset(
    {
        "tile_ninja",
        "flashy_fountain_pen",
        "bar_chart",
        "book_of_openings",
    }
)
_BICYCLE_PIN_EFFECTS = frozenset({"bicycle", "bones_the_dog", "bones"})


@dataclass
class SetupDelta:
    birthday_cake_bonus: int = 0
    bicycle_word_score_bonus: int = 0
    consumable_rack_count: int = 0
    tile_ninja_bonus: float = 0.0
    red_tiles_used_encounter: int = 0
    stamp_improves: dict[str, str] = field(default_factory=dict)

def _sticker_level(loadout: Loadout, sticker_id: str) -> int:
    sid = sticker_id.lower()
    for item in loadout.stickers:
        if (item.id or "").lower() == sid:
            return max(1, item.level)
    return 1


def grids_remaining_from_loadout(loadout: Loadout) -> int:
    extras = loadout.extras or {}
    for key in ("grids_remaining", "GridsRemaining"):
        try:
            return max(1, int(extras.get(key, 1)))
        except (TypeError, ValueError):
            continue
    return 1


def project_setup_delta(
    board: Board,
    path: list[int],
    word: str,
    loadout: Loadout,
    *,
    rules: dict | None = None,
) -> SetupDelta:
    """Post-submit accumulator changes from this word (not immediate score)."""
    delta = SetupDelta()
    rules = rules or rules_catalog()

    for item in loadout.stickers:
        sid = (item.id or "").lower()
        if sid == "birthday_cake" or "birthday" in (item.name or "").lower():
            sticker_rules = rules.get("stickers", {})
            rule = sticker_rules.get("birthday_cake") or {}
            level = _sticker_level(loadout, "birthday_cake")
            delta.birthday_cake_bonus = birthday_cake_improve_for_path(
                board, path, level, {**rule, "base": rule.get("base", 1), "upgrade": rule.get("upgrade", 1)}, word
            )

        elif sid == "hi_vis_jacket":
            if consumable_count_on_path(board, path) > 0:
                sticker_rules = rules.get("stickers", {})
                rule = sticker_rules.get("hi_vis_jacket") or {}
                step = int(sticker_rule_float(_sticker_level(loadout, sid), rule) * 5) or 1
                delta.consumable_rack_count = step

        elif sid in ("michael_book", "michaels_book"):
            sticker_rules = rules.get("stickers", {})
            rule = sticker_rules.get(sid) or sticker_rules.get("michael_book") or {}
            delta.birthday_cake_bonus = max(
                delta.birthday_cake_bonus,
                sticker_rule_int(_sticker_level(loadout, sid), rule),
            )

    pin_effect = str((loadout.extras or {}).get("pin_effect", "") or "").lower()
    if pin_effect in _BICYCLE_PIN_EFFECTS:
        canonical = resolve_rule_id(rules, "pins", pin_effect, "") or "bones_the_dog"
        rule = get_pin_scoring_rule(rules, canonical)
        if rule:
            per_card = bicycle_word_per_card(loadout, rule)
            suited = suited_tiles_on_path_count(board, path)
            if suited <= 0:
                from cursed_words_solver.rules.scoring_conditions import (
                    bicycle_suited_on_path_from_extras,
                )

                suited = bicycle_suited_on_path_from_extras(loadout)
            delta.bicycle_word_score_bonus = per_card * suited

    for item in loadout.stickers:
        sid = (item.id or "").lower()
        if sid == "red_rider":
            reds = sum(
                1
                for idx in path
                if board.get_by_index(idx).color.value == "red"
            )
            if reds:
                delta.red_tiles_used_encounter = reds

    consumables_on_path = consumable_count_on_path(board, path)
    if consumables_on_path > 0:
        for item in loadout.stamps:
            if (item.id or "").lower() == "tile_ninja":
                delta.tile_ninja_bonus = 0.02 * consumables_on_path
                break

    for slug, token in stamp_improve_match(loadout, word):
        delta.stamp_improves[slug] = token

    return delta


