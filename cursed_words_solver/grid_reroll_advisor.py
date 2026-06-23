"""Encounter grid reroll advice (distinct from shop restock)."""

from __future__ import annotations

from cursed_words_solver.models import EncounterGridRerollState, Loadout
from cursed_words_solver.rules.quest_scoring import (
    display_score_for_quest,
    effective_submit_score,
    two_wrongs_active,
)
from cursed_words_solver.setup_value import grids_remaining_from_loadout


def estimated_grid_target(loadout: Loadout) -> float | None:
    """Approximate score needed on this grid from encounter remaining target."""
    extras = loadout.extras or {}
    try:
        remaining_target = int(extras.get("encounter_remaining_target", 0))
    except (TypeError, ValueError):
        return None
    if remaining_target <= 0:
        return None
    grids = grids_remaining_from_loadout(loadout)
    return remaining_target / max(1, grids)


def _score_meets_grid_target(
    best_score: float,
    loadout: Loadout,
    grid_target: float,
    *,
    gap_ratio: float,
) -> bool:
    threshold = grid_target * gap_ratio
    if two_wrongs_active(loadout):
        return effective_submit_score(best_score, loadout) >= threshold
    return best_score >= threshold


def should_reroll_grid(
    best_score: float,
    loadout: Loadout,
    reroll: EncounterGridRerollState | None,
    *,
    gap_ratio: float = 0.3,
) -> bool:
    """Recommend grid reroll when score is far below estimated grid target."""
    if reroll is None:
        return False
    if not reroll.can_reroll or reroll.remaining <= 0:
        return False

    grid_target = estimated_grid_target(loadout)
    if grid_target is None or grid_target <= 0:
        return False

    if _score_meets_grid_target(
        best_score, loadout, grid_target, gap_ratio=gap_ratio
    ):
        return False

    cost = reroll.cost_per_use
    if cost > 0 and loadout.money < cost:
        return False

    return True


def format_grid_reroll_reason(
    best_score: float,
    loadout: Loadout,
    *,
    gap_ratio: float = 0.3,
) -> str:
    grid_target = estimated_grid_target(loadout)
    if grid_target is None:
        return "below encounter target"
    if two_wrongs_active(loadout):
        shown = display_score_for_quest(best_score, loadout)
        return (
            f"effective {shown:,.0f} < {gap_ratio:.0%} of grid target "
            f"~{grid_target:,.0f}"
        )
    return (
        f"best {best_score:,.0f} < {gap_ratio:.0%} of grid target ~{grid_target:,.0f}"
    )
