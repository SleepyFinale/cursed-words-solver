"""Encounter setup value for search ranking (Birthday Cake, Bicycle, rack bonuses)."""

from __future__ import annotations

from dataclasses import dataclass

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
from cursed_words_solver.rules.pipeline import ScoringPipeline

_SETUP_STICKER_IDS = frozenset(
    {
        "birthday_cake",
        "hi_vis_jacket",
        "tile_ninja",
        "michaels_book",
        "michael_book",
        "red_rider",
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

    def total_future_points(self, grids_remaining: int, *, discount: float = 0.85) -> float:
        """Heuristic NPV of accumulator gains over remaining encounter grids."""
        g = max(1, grids_remaining)
        d = discount
        total = 0.0
        if self.birthday_cake_bonus:
            total += self.birthday_cake_bonus * g * (d ** 0)
        if self.bicycle_word_score_bonus:
            total += self.bicycle_word_score_bonus * g * (d ** 0)
        if self.consumable_rack_count:
            uses = min(g, 3)
            total += self.consumable_rack_count * uses * 40.0 * (d ** 1)
        if self.tile_ninja_bonus:
            uses = min(g, 3)
            total += self.tile_ninja_bonus * 500.0 * uses * (d ** 1)
        if self.red_tiles_used_encounter:
            total += self.red_tiles_used_encounter * g * 15.0 * (d ** 1)
        return total


def _sticker_level(loadout: Loadout, sticker_id: str) -> int:
    sid = sticker_id.lower()
    for item in loadout.stickers:
        if (item.id or "").lower() == sid:
            return max(1, item.level)
    return 1


def _has_setup_mechanics(loadout: Loadout) -> bool:
    pin = str((loadout.extras or {}).get("pin_effect", "") or "").lower()
    if pin in _BICYCLE_PIN_EFFECTS:
        return True
    for item in loadout.stickers:
        if (item.id or "").lower() in _SETUP_STICKER_IDS:
            return True
        if "birthday" in (item.name or "").lower():
            return True
    return False


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
    rules = rules or ScoringPipeline().rules

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

        elif sid == "tile_ninja":
            if consumable_count_on_path(board, path) > 0:
                delta.tile_ninja_bonus = 0.02

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

    return delta


def setup_future_value(
    delta: SetupDelta,
    loadout: Loadout,
    *,
    grids_remaining: int | None = None,
    discount: float = 0.85,
) -> float:
    g = grids_remaining if grids_remaining is not None else grids_remaining_from_loadout(loadout)
    return delta.total_future_points(g, discount=discount)


def rank_score_for_word(
    board: Board,
    path: list[int],
    word: str,
    loadout: Loadout,
    immediate_score: float,
    *,
    setup_weight: float = 0.4,
    setup_discount: float = 0.85,
    rules: dict | None = None,
) -> tuple[float, float]:
    """Return (rank_score, setup_bonus)."""
    if setup_weight <= 0 or not _has_setup_mechanics(loadout):
        return immediate_score, 0.0
    delta = project_setup_delta(board, path, word, loadout, rules=rules)
    setup_pts = setup_future_value(
        delta, loadout, discount=setup_discount
    )
    bonus = setup_weight * setup_pts
    return immediate_score + bonus, bonus


def derive_setup_ranking_winner(
    immediate_a: float,
    immediate_b: float,
    rank_a: float,
    rank_b: float,
) -> str:
    """Return 'setup' when rank order differs from immediate order."""
    if rank_a > rank_b and immediate_a < immediate_b:
        return "setup"
    if rank_b > rank_a and immediate_b < immediate_a:
        return "setup"
    return "immediate"


def format_setup_bonus_summary(setup_bonus: float, delta: SetupDelta) -> str:
    if setup_bonus <= 0:
        return ""
    parts: list[str] = []
    if delta.birthday_cake_bonus:
        parts.append(f"Birthday +{delta.birthday_cake_bonus}")
    if delta.bicycle_word_score_bonus:
        parts.append(f"Bicycle +{delta.bicycle_word_score_bonus}")
    if delta.consumable_rack_count:
        parts.append(f"Rack +{delta.consumable_rack_count}")
    if delta.tile_ninja_bonus:
        parts.append(f"Ninja +{delta.tile_ninja_bonus:.2f}")
    if delta.red_tiles_used_encounter:
        parts.append(f"Red +{delta.red_tiles_used_encounter}")
    detail = ", ".join(parts) if parts else "setup"
    return f"+{setup_bonus:,.0f} setup ({detail})"
