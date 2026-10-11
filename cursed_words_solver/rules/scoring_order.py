"""Game-accurate scoring item order (EncounterController + ScoreCalculation)."""

from __future__ import annotations

from dataclasses import dataclass

from cursed_words_solver.models import Loadout, LoadoutItem
from cursed_words_solver.rules.rule_lookup import get_rule


@dataclass(frozen=True)
class ScoringItemRef:
    """One entry in the game's combined items list for CalculateOverallScore."""

    kind: str  # grid_path | pin | sticker | stamp
    item: LoadoutItem | None
    rule_id: str
    level: int = 1


def capybara_shuffles_loadout(loadout: Loadout | None, rules: dict) -> bool:
    if not loadout:
        return False
    if str(loadout.extras.get("capybara_shuffle", "") or "").lower() in ("1", "true", "yes"):
        return True
    from cursed_words_solver.rules.boss_effects import get_active_boss_rules

    for _key, boss in get_active_boss_rules(rules, loadout):
        if boss and boss.get("type") == "shuffle_loadout_order":
            return True
    for sticker in loadout.stickers:
        _key, rule = get_rule(rules, "stickers", sticker.id, sticker.name)
        if rule and rule.get("type") == "shuffle_loadout_order":
            return True
    return False


# EncounterController.GetItemsForWordSubmission only adds scattered items on the path.
# Off-path grid Tombstone is not a separate scoring item — void-adjacent scoring comes
# from the equipped Tombstone sticker at full inventory level (cinch: one L3 apply).
# Dusty Coffin is path-scattered or inventory only.
_OFF_PATH_GRID_SCATTER_SLUGS = frozenset()


