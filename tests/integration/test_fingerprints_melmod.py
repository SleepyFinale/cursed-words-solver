"""Fingerprint parity with melmod RunStateExporter."""

import json
from pathlib import Path

from cursed_words_solver.fingerprints import (
    boss_fingerprint_id,
    fingerprints_from_run_state,
    loadout_fingerprint,
)
from cursed_words_solver.loadout import parse_run_state
from cursed_words_solver.models import Loadout


def test_boss_fingerprint_id_empty_is_dash():
    assert boss_fingerprint_id("") == "-"
    assert boss_fingerprint_id("wolf") == "wolf"


def test_loadout_fingerprint_no_boss_uses_dash():
    lo = Loadout(character="Test", money=10, boss_id="")
    fp = loadout_fingerprint(lo)
    assert "|-|" in fp or fp.endswith(":-") or "|-:" in fp
    parts = fp.split("|")
    assert parts[4] == "-"


def test_fingerprints_from_run_state_no_boss_uses_dash():
    data = {
        "character": "Nina Nix",
        "money": 5,
        "stickers": [],
        "stamps": [],
        "boss_id": "",
        "extras": {"pin_effect": "milky_way"},
        "pin_branch": "",
        "board": {"money": 5, "tiles": []},
    }
    _, lo_fp = fingerprints_from_run_state(data)
    parts = lo_fp.split("|")
    assert parts[4] == "-"


def test_fingerprints_from_12ttee_fixture():
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "12ttee_run_state.json"
    if not fixture.exists():
        return
    data = json.loads(fixture.read_text(encoding="utf-8"))
    loadout = parse_run_state(data)
    assert loadout is not None
    _, lo_fp = fingerprints_from_run_state(data)
    assert loadout_fingerprint(loadout) == lo_fp


def test_loadout_fingerprint_bicycle_pin_includes_bonus_suffix() -> None:
    lo = Loadout(
        character="Bones The Dog",
        money=0,
        extras={
            "pin_effect": "bicycle",
            "bicycle_word_score_bonus": "0",
        },
        pin_branch="left",
    )
    assert loadout_fingerprint(lo) == "Bones The Dog|0|||-|bicycle:left|0"


def test_loadout_fingerprint_matches_melmod_bones_round_export() -> None:
    melmod_fp = "Bones The Dog|0|||-|bicycle:left|0"
    lo = Loadout(
        character="Bones The Dog",
        money=0,
        extras={
            "pin_effect": "bicycle",
            "bicycle_word_score_bonus": "0",
            "loadout_fingerprint": melmod_fp,
        },
        pin_branch="left",
    )
    assert loadout_fingerprint(lo) == melmod_fp
    from cursed_words_solver.loadout import loadout_fingerprint_stale_warning

    assert loadout_fingerprint_stale_warning(lo) is None


def test_fingerprints_from_run_state_bicycle_pin_suffix() -> None:
    data = {
        "character": "Bones The Dog",
        "money": 0,
        "stickers": [],
        "stamps": [],
        "boss_id": "",
        "pin_branch": "left",
        "extras": {
            "pin_effect": "bicycle",
            "bicycle_word_score_bonus": "34",
        },
        "board": {"money": 0, "tiles": []},
    }
    _, lo_fp = fingerprints_from_run_state(data)
    assert lo_fp == "Bones The Dog|0|||-|bicycle:left|34"


def test_dictionary_word_for_12ttee_path():
    import pytest

    from cursed_words_solver.config import GAME_WORDLIST_PATH
    from cursed_words_solver.dictionary import WordDictionary
    from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
    from cursed_words_solver.suggestion import dictionary_word_for_path

    if not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024:
        pytest.skip("game wordlist required")

    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "12ttee_run_state.json"
    if not fixture.exists():
        pytest.skip("12ttee_run_state.json fixture required")

    data = json.loads(fixture.read_text(encoding="utf-8"))
    board = parse_board_from_run_state(data)
    loadout = parse_run_state(data)
    d = WordDictionary(GAME_WORDLIST_PATH)
    path = [5, 11, 7, 21, 17, 9]
    got = dictionary_word_for_path(board, path, "12ttee", loadout, d)
    assert got is not None
    assert got.endswith("ttee")
    from cursed_words_solver.rules.stamp_behaviors import stamp_search_flags
    from cursed_words_solver.search import PathValidator

    flags = stamp_search_flags(loadout)
    validator = PathValidator(d, min_len=3)
    assert validator.word_ok(board, path, "settee", flags)
    assert validator.word_ok(board, path, got, flags)
