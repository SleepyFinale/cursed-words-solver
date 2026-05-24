import json
from pathlib import Path

from cursed_words_solver.loadout import (
    format_loadout_summary,
    load_run_state,
    loadout_to_dict,
    parse_run_state,
    save_loadout,
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
