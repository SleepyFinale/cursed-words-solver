"""Validation helpers for melmod run_state export diagnostics."""

from __future__ import annotations

from cursed_words_solver.loadout import (
    Loadout,
    LoadoutItem,
    export_diagnostics_from_run_state,
    validate_run_state_for_scoring,
)


def test_export_diagnostics_from_run_state():
    raw = {
        "export_diagnostics": {
            "missing_keys": ["snapshot_copy_slug"],
            "companion_version": "1.2.0",
        }
    }
    diag = export_diagnostics_from_run_state(raw)
    assert diag["companion_version"] == "1.2.0"
    assert "snapshot_copy_slug" in diag["missing_keys"]


def test_validate_snapshot_missing_copy_slug():
    loadout = Loadout(
        character="Nat-H4",
        stickers=[LoadoutItem(id="snapshot", name="Snapshot", level=1, kind="sticker")],
        stamps=[],
        extras={"pin_effect": "random_access_memory"},
    )
    warnings = validate_run_state_for_scoring(loadout)
    assert any("snapshot_copy_slug" in w for w in warnings)


def test_validate_snapshot_ok_when_slug_present():
    loadout = Loadout(
        character="Nat-H4",
        stickers=[LoadoutItem(id="snapshot", name="Snapshot", level=1, kind="sticker")],
        stamps=[],
        extras={
            "snapshot_copy_slug": "dusty_coffin",
            "snapshot_copy_export_note": "ok",
        },
    )
    warnings = validate_run_state_for_scoring(loadout)
    assert not any("snapshot_copy_slug" in w for w in warnings)


def test_validate_merges_melmod_missing_keys():
    loadout = Loadout(character="X", stickers=[], stamps=[], extras={})
    raw = {"export_diagnostics": {"missing_keys": ["grid_number"]}}
    warnings = validate_run_state_for_scoring(loadout, raw=raw)
    assert any("grid_number" in w for w in warnings)
