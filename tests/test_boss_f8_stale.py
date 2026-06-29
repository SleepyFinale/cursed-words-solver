"""Boss F8 embed stale reconciliation and scoring authority."""

from __future__ import annotations

import json
from pathlib import Path

from cursed_words_solver.loadout import (
    BOSS_RECONCILE_EXTRA_KEYS,
    reconcile_boss_extras_for_f8_embed,
    reconcile_boss_extras_from_extras_diff,
)
from cursed_words_solver.models import Board, CurseType, Loadout, Tile, TileColor
from cursed_words_solver.rules.boss_effects import active_boss_ids


def _simple_board() -> Board:
    board = Board(tiles=[[None] * 5 for _ in range(5)], money=10)
    for r in range(5):
        for c in range(5):
            board.tiles[r][c] = Tile(
                r,
                c,
                "a",
                "A",
                1,
                color=TileColor.BLUE,
                curse=CurseType.LETTER,
            )
    return board


def test_reconcile_strips_embed_boss_when_fresh_empty(tmp_path, monkeypatch):
    from cursed_words_solver.loadout import RUN_STATE_PATH

    run_state_path = tmp_path / "run_state.json"
    monkeypatch.setattr("cursed_words_solver.loadout.RUN_STATE_PATH", run_state_path)
    run_state_path.write_text(
        json.dumps(
            {
                "boss_id": "",
                "extras": {"boss_modifiers": "[]", "grid_number": "4"},
            }
        ),
        encoding="utf-8",
    )
    embed = {
        "boss_id": "badger",
        "boss_name": "Badger",
        "extras": {
            "boss_modifiers": '["badger"]',
            "boss_cursed": "true",
            "boss_area_number": "5",
            "boss_floor_modification": "2",
            "boss_modifier_floor_mods": '{"badger":2}',
        },
    }
    reconcile_boss_extras_for_f8_embed(embed)
    assert "boss_modifiers" not in embed["extras"]
    assert embed["boss_id"] == ""


def test_reconcile_prefers_fresh_boss_modifiers_when_differ(tmp_path, monkeypatch):
    from cursed_words_solver.loadout import RUN_STATE_PATH

    run_state_path = tmp_path / "run_state.json"
    monkeypatch.setattr("cursed_words_solver.loadout.RUN_STATE_PATH", run_state_path)
    run_state_path.write_text(
        json.dumps(
            {
                "boss_id": "salamander",
                "extras": {
                    "boss_modifiers": '["salamander"]',
                    "boss_area_number": "3",
                },
            }
        ),
        encoding="utf-8",
    )
    embed = {
        "boss_id": "badger",
        "extras": {
            "boss_modifiers": '["badger"]',
            "boss_cursed": "true",
            "boss_area_number": "5",
        },
    }
    reconcile_boss_extras_for_f8_embed(embed)
    assert embed["extras"]["boss_modifiers"] == '["salamander"]'
    assert embed["boss_id"] == "salamander"


def test_reconcile_from_extras_diff_clears_stale_boss_fields():
    extras = {
        "boss_modifiers": '["badger"]',
        "boss_cursed": "true",
        "boss_area_number": "5",
    }
    run_state = {"boss_id": "badger", "boss_name": "Badger"}
    reconcile_boss_extras_from_extras_diff(
        extras,
        {
            "extras_diff": {
                "boss_modifiers": {"f8": '["badger"]', "submit": ""},
            }
        },
        run_state=run_state,
    )
    for key in BOSS_RECONCILE_EXTRA_KEYS:
        assert key not in extras
    assert run_state["boss_id"] == ""


def test_empty_boss_modifiers_disables_scoring_boss_effects():
    """Mirror test_boss_modifiers_source_of_truth: [] means no copied effects."""
    board = _simple_board()
    loadout = Loadout(
        boss_id="salamander",
        extras={"boss_area_number": 1, "boss_modifiers": []},
    )
    assert active_boss_ids(loadout) == []
    from cursed_words_solver.rules.pipeline import ScoringPipeline

    _, bd = ScoringPipeline().score(board, [0, 1, 2], "aaa", loadout)
    assert not any("per tile (boss)" in e for e in bd["pipeline"]["effects"])


def test_badger_only_modifiers_are_encounter_meta_not_scoring_early():
    loadout = Loadout(
        boss_id="badger",
        extras={
            "boss_modifiers": ["badger"],
            "boss_area_number": 5,
            "boss_cursed": True,
        },
    )
    assert active_boss_ids(loadout) == ["badger"]
    from cursed_words_solver.rules.boss_effects import boss_modifier_active

    assert not boss_modifier_active(loadout, "salamander")
