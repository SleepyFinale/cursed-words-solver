"""Regression tests for Beans/Michael session fixes (2026-06-25)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cursed_words_solver.loadout import (
    _fresh_encounter_grid_one,
    green_poison_from_historic_words,
)
from cursed_words_solver.suggestion import (
    f8_historic_would_fail_submit_projection,
    f8_should_block_save,
)


def test_fresh_encounter_grid_one_false_when_spc_positive() -> None:
    extras = {
        "grid_number": "1",
        "encounter_total_target": "61126",
        "encounter_remaining_target": "61126",
        "encounter_score_earned": "0",
        "scoring_previous_words_count": "3",
    }
    assert not _fresh_encounter_grid_one(extras)


def test_green_poison_applies_when_spc_positive_despite_earned_zero() -> None:
    extras = {
        "grid_number": "1",
        "encounter_total_target": "61126",
        "encounter_remaining_target": "61126",
        "encounter_score_earned": "0",
        "scoring_previous_words_count": "3",
        "encounter_historic_source": "live",
        "historic_words": json.dumps(
            [
                {"word": "a", "score": 3218, "green_tile_count": 1},
                {"word": "b", "score": 79347, "green_tile_count": 1},
            ]
        ),
    }
    poison = green_poison_from_historic_words(extras)
    assert poison == 322 + 7935


def test_f8_historic_would_fail_on_empty_embed_with_projected_historic() -> None:
    embed = {"historic_words": "", "scoring_previous_words_count": "0"}
    projected = {
        "historic_words": json.dumps([{"word": "x", "score": 100}]),
        "scoring_previous_words_count": "1",
    }
    note = f8_historic_would_fail_submit_projection(
        embed, projected_extras=projected
    )
    assert note is not None
    assert "empty historic" in note


def test_f8_should_block_save_on_empty_embed_historic_lag() -> None:
    embed = {"historic_words": "[]", "scoring_previous_words_count": "0"}
    projected = {
        "historic_words": json.dumps([{"word": "x", "score": 100}]),
        "scoring_previous_words_count": "1",
        "grid_number": "2",
    }
    blocked, reason = f8_should_block_save(
        f8_extras=embed,
        submit_projected_extras=projected,
        gather_succeeded=True,
    )
    assert blocked
    assert reason == "submit_projection_mismatch"


def test_stale_f8_round_log_would_block_save() -> None:
    path = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "round_logs"
        / "20260625_143117_478.json"
    )
    if not path.exists():
        pytest.skip("promote stale F8 round log fixture first")
    data = json.loads(path.read_text(encoding="utf-8"))
    diff = data.get("extras_diff") or {}
    embed_extras: dict = {"scoring_previous_words_count": "0", "historic_words": ""}
    for key, entry in diff.items():
        if isinstance(entry, dict) and "f8" in entry:
            embed_extras[key] = entry.get("f8", "")
    projected_extras: dict = {}
    for key, entry in diff.items():
        if isinstance(entry, dict) and "submit" in entry:
            projected_extras[key] = entry.get("submit", "")
    blocked, reason = f8_should_block_save(
        f8_extras=embed_extras,
        submit_projected_extras=projected_extras,
        gather_succeeded=True,
    )
    assert blocked
    assert reason == "submit_projection_mismatch"
