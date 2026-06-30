"""Cursedle export parsing and routing."""

from __future__ import annotations

import json

from cursed_words_solver.cursedle_solver import parse_cursedle_guesses
from cursed_words_solver.f8_snapshot import _cursedle_extras_missing
from cursed_words_solver.loadout import encounter_mode_from_run_state, parse_run_state
from cursed_words_solver.models import Loadout


def test_encounter_mode_cursedle_with_board() -> None:
    data = {
        "board": {"tiles": [{}] * 36},
        "extras": {"encounter_mode": "cursedle"},
    }
    assert encounter_mode_from_run_state(data) == "cursedle"


def test_parse_cursedle_guesses_json() -> None:
    extras = {
        "cursedle_guesses": json.dumps(
            [
                {
                    "path": [0, 1, 2],
                    "tiles": [
                        {"row": 0, "col": 0, "index": 0, "feedback": "green"},
                        {"row": 0, "col": 1, "index": 1, "feedback": "yellow"},
                        {"row": 0, "col": 2, "index": 2, "feedback": "red"},
                    ],
                }
            ]
        )
    }
    guesses = parse_cursedle_guesses(extras)
    assert len(guesses) == 1
    assert guesses[0].path == [0, 1, 2]
    assert guesses[0].feedback == ["green", "yellow", "red"]


def test_gather_gate_satisfied_at_puzzle_start() -> None:
    """Puzzle start: 0 submits, empty history — must not block F8."""
    loadout = Loadout(extras={"encounter_mode": "cursedle"})
    extras = {
        "encounter_mode": "cursedle",
        "cursedle_guesses_used": "0",
        "cursedle_guesses_remaining": "5",
        "cursedle_guesses": "[]",
    }
    missing = _cursedle_extras_missing(loadout, extras)
    assert missing == []


def test_gather_gate_requires_guess_history_when_used() -> None:
    loadout = Loadout(extras={"encounter_mode": "cursedle"})
    extras = {
        "encounter_mode": "cursedle",
        "cursedle_guesses_used": "1",
        "cursedle_guesses_remaining": "4",
        "cursedle_guesses": "[]",
    }
    missing = _cursedle_extras_missing(loadout, extras)
    assert "cursedle_guesses" in missing


def test_gather_gate_satisfied_with_matching_history() -> None:
    loadout = Loadout(extras={"encounter_mode": "cursedle"})
    extras = {
        "encounter_mode": "cursedle",
        "cursedle_guesses_used": "1",
        "cursedle_guesses_remaining": "4",
        "cursedle_guesses": json.dumps([{"path": [0], "tiles": [{"feedback": "grey"}]}]),
    }
    missing = _cursedle_extras_missing(loadout, extras)
    assert "cursedle_guesses" not in missing


def test_cursedle_active_from_run_state() -> None:
    loadout = parse_run_state({"extras": {"encounter_mode": "cursedle"}})
    from cursed_words_solver.rules.boss_effects import cursedle_active

    assert cursedle_active(loadout)
