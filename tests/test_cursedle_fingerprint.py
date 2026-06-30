"""Cursedle fingerprint stale detection."""

from __future__ import annotations

import json

from cursed_words_solver.cursedle_solver import cursedle_guess_fingerprint
from cursed_words_solver.fingerprints import fingerprints_from_run_state, loadout_fingerprint
from cursed_words_solver.models import Loadout


def test_guess_fingerprint_changes_when_history_grows() -> None:
    base = {"cursedle_guesses": "[]"}
    after = {
        "cursedle_guesses": json.dumps(
            [{"path": [1, 2], "tiles": [{"feedback": "green"}, {"feedback": "red"}]}]
        )
    }
    assert cursedle_guess_fingerprint(base) != cursedle_guess_fingerprint(after)


def test_fingerprints_from_run_state_include_cursedle_guesses() -> None:
    data = {
        "character": "Test",
        "money": 0,
        "board": {"money": 0, "tiles": []},
        "extras": {
            "encounter_mode": "cursedle",
            "cursedle_guesses": json.dumps(
                [{"path": [0], "tiles": [{"feedback": "green"}]}]
            ),
        },
    }
    board_fp, _ = fingerprints_from_run_state(data)
    assert "0:green" in board_fp


def test_loadout_fingerprint_includes_cursedle_suffix() -> None:
    loadout = Loadout(
        extras={
            "encounter_mode": "cursedle",
            "cursedle_guesses": json.dumps(
                [{"path": [3], "tiles": [{"feedback": "yellow"}]}]
            ),
        }
    )
    fp = loadout_fingerprint(loadout)
    assert "3:yellow" in fp
