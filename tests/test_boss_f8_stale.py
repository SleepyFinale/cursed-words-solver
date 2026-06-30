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
    reconcile_boss_extras_for_f8_embed(embed, allow_disk_reconcile=True)
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
    reconcile_boss_extras_for_f8_embed(embed, allow_disk_reconcile=True)
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


def test_f8_boss_extras_stale_mole_only_not_stale():
    from cursed_words_solver.suggestion import f8_boss_extras_stale

    f8 = {"boss_modifiers": '["mole"]', "boss_modifier_floor_mods": '{"mole":3}'}
    projected = {"boss_modifiers": "[]"}
    assert not f8_boss_extras_stale(f8, projected)


def test_f8_boss_extras_stale_salamander_mismatch():
    from cursed_words_solver.suggestion import f8_boss_extras_stale

    f8 = {"boss_modifiers": '["salamander"]'}
    projected = {"boss_modifiers": "[]"}
    assert f8_boss_extras_stale(f8, projected)


def test_f8_should_block_save_mid_solve_grid_advanced():
    from cursed_words_solver.suggestion import f8_should_block_save

    blocked, reason = f8_should_block_save(
        gather_succeeded=True,
        mid_solve_grid_advanced=True,
    )
    assert blocked
    assert reason == "grid_advanced_during_solve"


def test_f8_should_block_save_boss_extras_stale():
    from cursed_words_solver.suggestion import f8_should_block_save

    blocked, reason = f8_should_block_save(
        gather_succeeded=True,
        f8_extras={"boss_modifiers": '["salamander"]'},
        submit_projected_extras={"boss_modifiers": "[]"},
    )
    assert blocked
    assert reason == "boss_extras_stale"


def test_sanitize_strips_non_scoring_boss_on_michael_finale_boss_node():
    """Michael finale Boss node: empty boss_modifiers → drop reconcile keys from F8 embed."""
    from cursed_words_solver.loadout import (
        BOSS_RECONCILE_EXTRA_KEYS,
        sanitize_run_state_snapshot_for_f8,
    )

    run_state = {
        "boss_id": "michael",
        "boss_name": "Michael",
        "extras": {
            "run_node_type": "Boss",
            "boss_modifiers": "[]",
            "boss_area_number": "6",
            "boss_floor_modification": "3",
            "michael_phase": "4",
            "michael_min_word_length": "25",
            "encounter_min_word_length": "25",
            "michael_finale_probe": "finale=1,michael_boss=1,summoned_defeated=1",
        },
    }
    loadout = Loadout()
    sanitized = sanitize_run_state_snapshot_for_f8(run_state, loadout)
    extras = sanitized.get("extras") or {}
    for key in BOSS_RECONCILE_EXTRA_KEYS:
        assert key not in extras
    assert extras.get("michael_min_word_length") == "25"
    assert sanitized.get("boss_id") == "michael"


def test_michael_finale_round_log_boss_drift_benign_after_sanitize():
    """20260630_001851: F8 embed must not carry boss_area_number that submit clears."""
    from tests.test_stale_suggestion import _has_boss_extras_drift

    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "round_logs"
        / "20260630_001851_michael_finale_stale.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    diff = data["extras_diff"]
    f8_extras = {key: str(entry.get("f8", "") or "") for key, entry in diff.items()}
    submit_extras = {key: str(entry.get("submit", "") or "") for key, entry in diff.items()}

    from cursed_words_solver.loadout import sanitize_run_state_snapshot_for_f8

    run_state = {
        "boss_id": "michael",
        "boss_name": "Michael",
        "extras": dict(f8_extras),
    }
    sanitized = sanitize_run_state_snapshot_for_f8(run_state, Loadout())
    embed_extras = sanitized.get("extras") or {}
    projected = {
        key: str(embed_extras.get(key, "") or "")
        for key in set(embed_extras) | set(submit_extras)
    }
    embed_diff = {
        key: {"f8": projected.get(key, ""), "submit": submit_extras.get(key, "")}
        for key in set(projected) | set(submit_extras)
        if projected.get(key, "") != submit_extras.get(key, "")
    }
    assert not _has_boss_extras_drift(embed_diff, projected, submit_extras)
