"""Regression: false stale_f8_extras when Tile Ninja counters only in F8 embed."""

from __future__ import annotations

import json
from pathlib import Path

from cursed_words_solver.loadout import reconcile_boss_extras_for_f8_embed


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "round_logs"


def _load_round_log(name: str) -> dict:
    path = FIXTURES / name
    assert path.is_file(), f"missing fixture {path}"
    return json.loads(path.read_text(encoding="utf-8"))


def test_wielder_round_log_was_false_stale_tile_ninja_only():
    data = _load_round_log("20260629_235550_wielder_tile_ninja_stale.json")
    assert data["match_status"] == "stale_f8_extras"
    assert data["solver"]["predicted_score"] == data["actual"]["score"]
    diff = data["extras_diff"]
    assert diff["tile_ninja_consumables_used"]["f8"] == "9"
    assert diff["tile_ninja_consumables_used"]["submit"] in ("", None)
    assert diff["tile_ninja_word_bonus_percent"]["f8"] == "138"
    reason = data["comparison"]["stale_f8_reason"]
    assert "tile_ninja_consumables_used" in reason
    assert "boss_modifiers" not in reason


def test_write_round_log_same_false_stale_pattern():
    data = _load_round_log("20260629_235748_write_tile_ninja_stale.json")
    assert data["match_status"] == "stale_f8_extras"
    assert data["solver"]["predicted_score"] == data["actual"]["score"]
    diff = data["extras_diff"]
    assert diff["tile_ninja_consumables_used"]["f8"] == "12"
    assert diff["tile_ninja_word_bonus_percent"]["f8"] == "144"


def test_reconcile_boss_skips_disk_by_default(tmp_path, monkeypatch):
    from cursed_words_solver.loadout import RUN_STATE_PATH

    run_state_path = tmp_path / "run_state.json"
    monkeypatch.setattr("cursed_words_solver.loadout.RUN_STATE_PATH", run_state_path)
    run_state_path.write_text(
        json.dumps(
            {
                "boss_id": "",
                "extras": {"boss_modifiers": "[]"},
            }
        ),
        encoding="utf-8",
    )
    embed = {
        "boss_id": "fox",
        "extras": {"boss_modifiers": '["fox"]', "boss_area_number": "4"},
    }
    reconcile_boss_extras_for_f8_embed(embed)
    assert embed["extras"]["boss_modifiers"] == '["fox"]'
    assert embed["boss_id"] == "fox"


def test_f8_embed_tile_ninja_counters_from_gather_snapshot():
    """Embed should keep gather-time tile ninja keys without disk refresh."""
    from cursed_words_solver.loadout import sanitize_run_state_snapshot_for_f8
    from cursed_words_solver.models import Loadout, LoadoutItem

    run_state = {
        "character": "Sandy Saguaro",
        "stamps": [{"id": "tile_ninja", "name": "Tile Ninja", "kind": "stamp"}],
        "extras": {
            "tile_ninja_consumables_used": "9",
            "tile_ninja_word_bonus_percent": "138",
            "tile_ninja_bonus": "0.18",
            "tile_ninja_bonus_last_known": "0.18",
        },
    }
    loadout = Loadout(
        stamps=[LoadoutItem(id="tile_ninja", name="Tile Ninja", kind="stamp")],
        extras=dict(run_state["extras"]),
    )
    snap = sanitize_run_state_snapshot_for_f8(run_state, loadout)
    extras = snap["extras"]
    assert extras["tile_ninja_consumables_used"] == "9"
    assert extras["tile_ninja_word_bonus_percent"] == "138"
