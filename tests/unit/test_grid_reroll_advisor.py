"""Grid reroll advice (encounter only, not shop restock)."""

from __future__ import annotations

from cursed_words_solver.grid_reroll_advisor import (
    estimated_grid_target,
    should_reroll_grid,
)
from cursed_words_solver.models import EncounterGridRerollState, Loadout


def _reroll(**kwargs) -> EncounterGridRerollState:
    defaults = {
        "remaining": 1,
        "cost_per_use": 0,
        "can_reroll": True,
        "wheel_equipped": False,
        "fan_equipped": False,
    }
    defaults.update(kwargs)
    return EncounterGridRerollState(**defaults)


def test_estimated_grid_target_divides_by_grids_remaining():
    loadout = Loadout(
        extras={
            "encounter_remaining_target": "48",
            "grids_remaining": "3",
        }
    )
    assert estimated_grid_target(loadout) == 16.0


def test_should_reroll_when_below_target_gap():
    loadout = Loadout(
        money=10,
        extras={"encounter_remaining_target": "100", "grids_remaining": "2"},
    )
    assert should_reroll_grid(10.0, loadout, _reroll(), gap_ratio=0.3) is True


def test_should_not_reroll_when_score_meets_target():
    loadout = Loadout(
        extras={"encounter_remaining_target": "100", "grids_remaining": "2"},
    )
    assert should_reroll_grid(20.0, loadout, _reroll(), gap_ratio=0.3) is False


def test_should_not_reroll_without_budget():
    loadout = Loadout(
        money=0,
        extras={"encounter_remaining_target": "100", "grids_remaining": "2"},
    )
    assert should_reroll_grid(
        10.0, loadout, _reroll(cost_per_use=1, wheel_equipped=True), gap_ratio=0.3
    ) is False


def test_should_not_reroll_when_cannot_reroll():
    loadout = Loadout(
        extras={"encounter_remaining_target": "100", "grids_remaining": "2"},
    )
    assert should_reroll_grid(
        10.0, loadout, _reroll(can_reroll=False), gap_ratio=0.3
    ) is False


def test_should_not_reroll_without_encounter_target():
    loadout = Loadout(extras={"grids_remaining": "2"})
    assert should_reroll_grid(10.0, loadout, _reroll(), gap_ratio=0.3) is False
