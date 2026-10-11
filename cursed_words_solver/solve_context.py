"""Immutable per-solve loadout flags (computed once at find_best_words entry)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cursed_words_solver.rules.boss_effects import (
    BossContext,
)
from cursed_words_solver.rules.quest_effects import (
    QuestConstraints,
)
from cursed_words_solver.rules.boss_scoring import EARLY_BOSS_TYPES
from cursed_words_solver.rules.scoring_order import (
    ScoringItemRef,
)
from cursed_words_solver.rules.stamp_behaviors import (
    SearchFlagsMask,
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
        "hyena_blocked",
        "boss_word_min_length",
        "",
    }
)


def _sticker_level(item) -> int:
    return max(1, int(item.level or 1))


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
    interleaved_sticker_order: bool = False
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
    quest_ctx: QuestConstraints = QuestConstraints()
    green_poison_total: float = 0.0


