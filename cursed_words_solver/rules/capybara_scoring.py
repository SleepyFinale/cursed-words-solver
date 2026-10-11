"""Capybara non-deterministic scoring: permutation EV and min/max range."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from cursed_words_solver.models import Loadout
from cursed_words_solver.rules.boss_effects import boss_is_cursed, get_active_boss_rules
from cursed_words_solver.rules.scoring_order import (
    capybara_shuffles_loadout,
)

if TYPE_CHECKING:
    pass

MAX_EXHAUSTIVE_PERMS = 720
MAX_EXHAUSTIVE_ITEM_COUNT = 6
SAMPLED_PERM_COUNT = 256


@dataclass(frozen=True)
class CapybaraScope:
    shuffles_stickers: bool
    shuffles_stamps: bool


@dataclass(frozen=True)
class CapybaraScoreStats:
    ev: float
    min_score: float
    max_score: float
    perm_count: int
    exhaustive: bool
    best_loadout: Loadout | None = None
    best_score: float | None = None


def capybara_shuffle_scope(loadout: Loadout | None, rules: dict) -> CapybaraScope:
    """Which inventory arrays the game randomizes before scoring."""
    if not loadout or not capybara_shuffles_loadout(loadout, rules):
        return CapybaraScope(False, False)
    for _key, boss in get_active_boss_rules(rules, loadout):
        if boss and boss.get("type") == "shuffle_loadout_order":
            return CapybaraScope(True, boss_is_cursed(loadout))
    return CapybaraScope(True, False)


def capybara_active_warning(loadout: Loadout | None, rules: dict) -> str | None:
    scope = capybara_shuffle_scope(loadout, rules)
    if not scope.shuffles_stickers:
        return None
    if scope.shuffles_stamps:
        return (
            "Capybara active — sticker and stamp order randomized, "
            "score estimate may be off"
        )
    return "Capybara active — sticker order randomized, score estimate may be off"


def capybara_sampling_warning(exhaustive: bool, perm_count: int) -> str | None:
    if exhaustive:
        return None
    return (
        f"Capybara permutations sampled ({perm_count} of "
        f"{SAMPLED_PERM_COUNT}) — score range is approximate"
    )


def capybara_perm_count(loadout: Loadout, scope: CapybaraScope) -> int:
    if scope.shuffles_stickers and len(loadout.stickers) > 1:
        sticker_n = math.factorial(len(loadout.stickers))
    else:
        sticker_n = 1
    if scope.shuffles_stamps and len(loadout.stamps) > 1:
        stamp_n = math.factorial(len(loadout.stamps))
    else:
        stamp_n = 1
    return sticker_n * stamp_n
