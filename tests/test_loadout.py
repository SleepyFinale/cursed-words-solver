import json
from pathlib import Path

from cursed_words_solver.loadout import (
    format_loadout_summary,
    load_run_state,
    loadout_to_dict,
    neapolitan_extras_stale_warning,
    parse_run_state,
    save_loadout,
    steak_extras_stale_warning,
    validate_run_state_for_scoring,
)
from cursed_words_solver.models import Loadout, LoadoutItem

MELMOD_EXAMPLE = {
    "character": "Beans",
    "pin_branch": "left",
    "money": 42,
    "stickers": [
        {"id": "sticky_plaster", "name": "Sticky Plaster", "level": 2},
        {"id": "tombstone", "name": "Tombstone", "level": 1},
    ],
    "stamps": [{"id": "newspaper", "name": "Newspaper"}],
    "boss_id": "mole",
    "boss_name": "Mole",
    "boss_effect": "",
    "extras": {"pin_effect": "beans"},
}


def test_parse_run_state(tmp_path):
    data = {
        "character": "Test",
        "money": 10,
        "stickers": [{"id": "a", "name": "A", "level": 2}],
        "stamps": [{"id": "b", "name": "B"}],
        "boss_id": "mole",
    }
    path = tmp_path / "run_state.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    lo = load_run_state(path)
    assert lo is not None
    assert lo.character == "Test"
    assert lo.money == 10
    assert len(lo.stickers) == 1
    assert lo.stickers[0].level == 2


def test_parse_run_state_direct():
    lo = parse_run_state({"stickers": [], "stamps": []})
    assert lo.stickers == []


def test_parse_melmod_full_shape():
    lo = parse_run_state(MELMOD_EXAMPLE)
    assert lo.character == "Beans"
    assert lo.pin_branch == "left"
    assert lo.boss_name == "Mole"
    assert lo.extras["pin_effect"] == "beans"
    assert len(lo.stickers) == 2
    assert lo.stickers[0].id == "sticky_plaster"


def test_loadout_roundtrip_preserves_all_fields(tmp_path):
    lo = parse_run_state(MELMOD_EXAMPLE)
    lo.stickers = [
        LoadoutItem(id="red_rider", name="Red Rider", level=3, kind="sticker")
    ]
    path = tmp_path / "run_state.json"
    save_loadout(lo, path)

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["pin_branch"] == "left"
    assert data["boss_name"] == "Mole"
    assert data["boss_effect"] == ""
    assert data["extras"]["pin_effect"] == "beans"
    assert data["stickers"][0]["id"] == "red_rider"

    reloaded = load_run_state(path)
    assert reloaded is not None
    assert reloaded.pin_branch == "left"
    assert reloaded.boss_name == "Mole"
    assert reloaded.extras == lo.extras


def test_format_loadout_summary_boss_name_and_internal_id():
    lo = parse_run_state(
        {
            "character": "Nina Nix",
            "boss_id": "bossdino",
            "boss_name": "Cretaceous Meg",
            "stickers": [],
            "stamps": [],
        }
    )
    assert "boss=bossdino" in format_loadout_summary(lo)
    assert "Cretaceous Meg" not in format_loadout_summary(lo)


def test_format_loadout_summary_bosssmallgrid_shows_id_only():
    lo = parse_run_state(
        {
            "character": "Nina Nix",
            "boss_id": "bosssmallgrid",
            "boss_name": "4x4 Grid",
            "stickers": [],
            "stamps": [],
        }
    )
    summary = format_loadout_summary(lo)
    assert "boss=bosssmallgrid" in summary
    assert "4x4 Grid" not in summary


def test_format_loadout_summary_boss_id_only_when_name_matches_slug():
    lo = parse_run_state(
        {
            "character": "Test",
            "boss_id": "wolf",
            "boss_name": "Wolf",
            "stickers": [],
            "stamps": [],
        }
    )
    assert "boss=Wolf" in format_loadout_summary(lo)
    assert "(wolf)" not in format_loadout_summary(lo)


def test_loadout_to_dict_matches_melmod_keys():
    lo = parse_run_state(MELMOD_EXAMPLE)
    data = loadout_to_dict(lo)
    assert set(data.keys()) >= {
        "character",
        "pin_branch",
        "money",
        "stickers",
        "stamps",
        "boss_id",
        "boss_name",
        "boss_effect",
        "extras",
    }


def test_neapolitan_warning_uses_cached_baseline_message():
    lo = Loadout(
        stamps=[LoadoutItem(id="neapolitan", name="Neapolitan", kind="stamp")],
        extras={"neapolitan_percent_last_known": "125"},
    )
    warning = neapolitan_extras_stale_warning(lo)
    assert warning is not None
    assert "125%" in warning
    assert "cached baseline" in warning


def test_neapolitan_warning_default_when_no_percent_available():
    lo = Loadout(
        stamps=[LoadoutItem(id="neapolitan", name="Neapolitan", kind="stamp")],
        extras={},
    )
    warning = neapolitan_extras_stale_warning(lo)
    assert warning is not None
    assert "defaulting to 100%" in warning


def test_steak_warning_when_percent_and_count_missing():
    lo = Loadout(
        stamps=[LoadoutItem(id="steak", name="Steak", kind="stamp")],
        extras={},
    )
    warning = steak_extras_stale_warning(lo)
    assert warning is not None
    assert "steak_word_bonus_percent" in warning


def test_steak_warning_none_when_percent_exported():
    lo = Loadout(
        stamps=[LoadoutItem(id="steak", name="Steak", kind="stamp")],
        extras={"steak_word_bonus_percent": "250"},
    )
    assert steak_extras_stale_warning(lo) is None


def test_validate_run_state_steak_missing_percent():
    lo = Loadout(
        stamps=[LoadoutItem(id="steak", name="Steak", kind="stamp")],
        extras={},
    )
    warnings = validate_run_state_for_scoring(lo)
    assert any("steak_word_bonus_percent" in w for w in warnings)


def test_parse_run_state_normalizes_boss_modifiers_json_string():
    lo = parse_run_state(
        {
            "boss_id": "salamander",
            "extras": {"boss_modifiers": '["badger","mole","salamander","mole"]'},
            "stickers": [],
            "stamps": [],
        }
    )
    assert lo.extras["boss_modifiers"] == ["badger", "mole", "salamander"]


def test_parse_run_state_normalizes_michael_min_word_length():
    lo = parse_run_state(
        {
            "boss_id": "michael",
            "extras": {"michael_min_word_length": "25"},
            "stickers": [],
            "stamps": [],
        }
    )
    assert lo.extras["michael_min_word_length"] == 25


def test_read_run_state_json_retries_during_atomic_replace(tmp_path, monkeypatch):
    import threading

    from cursed_words_solver.loadout import _read_run_state_json

    path = tmp_path / "run_state.json"
    payload = {"character": "Test", "board": {"tiles": [{}] * 25}}
    path.write_text(json.dumps(payload), encoding="utf-8")

    stop = threading.Event()

    def hammer_replace() -> None:
        while not stop.is_set():
            temp = path.with_suffix(".json.tmp")
            temp.write_text("{", encoding="utf-8")
            if path.exists():
                temp.replace(path)
            else:
                temp.rename(path)
            time.sleep(0.005)

    import time

    t = threading.Thread(target=hammer_replace, daemon=True)
    t.start()
    try:
        data = _read_run_state_json(path, retries=20, delay_sec=0.01)
    finally:
        stop.set()
        t.join(timeout=1.0)
        path.write_text(json.dumps(payload), encoding="utf-8")

    assert data is not None
    assert data["character"] == "Test"
