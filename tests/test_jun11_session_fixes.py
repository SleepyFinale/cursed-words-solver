"""Unit tests for Jun 11 session scoring fixes (Dusty Coffin, Down Under)."""

from __future__ import annotations

import json
from pathlib import Path


from cursed_words_solver.loadout import encounter_implies_active_boss, encounter_missing_boss_should_warn, parse_run_state

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "mismatches"


def test_encounter_first_does_not_warn_missing_boss():
    data = json.loads((FIXTURES / "20260611_001830.json").read_text(encoding="utf-8"))
    loadout = parse_run_state(data["run_state_snapshot"])
    assert not encounter_implies_active_boss(loadout)
    assert not encounter_missing_boss_should_warn(loadout)


def test_boss_node_with_boss_id_does_not_warn():
    data = json.loads((FIXTURES / "20260610_235237.json").read_text(encoding="utf-8"))
    loadout = parse_run_state(data["run_state_snapshot"])
    assert encounter_implies_active_boss(loadout)
    assert not encounter_missing_boss_should_warn(loadout)


