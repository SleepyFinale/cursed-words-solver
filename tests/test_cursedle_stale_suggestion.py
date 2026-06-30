"""Cursedle suggestion persistence, stale poll, and overlay rack suppression."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cursed_words_solver.config import AppConfig, Region
from cursed_words_solver.cursedle_solver import CursedleAdvice, save_cursedle_suggestion
from cursed_words_solver.fingerprints import (
    board_fingerprint_tiles_only_from_fp,
    fingerprints_from_run_state,
)
from cursed_words_solver.models import Board, CurseType, Loadout, Tile, TileColor
from cursed_words_solver.suggestion import poll_invalidate_last_suggestion
from cursed_words_solver.ui.layout import resolve_overlay_regions


def _tile(row: int, col: int, letter: str) -> Tile:
    return Tile(
        row=row,
        col=col,
        char=letter.lower(),
        letter=letter,
        base_score=1.0,
        color=TileColor.COLORLESS,
        curse=CurseType.LETTER,
    )


def _board_6x6(letters: list[str]) -> Board:
    tiles = [
        [_tile(r, c, letters[r * 6 + c]) for c in range(6)]
        for r in range(6)
    ]
    return Board(tiles=tiles, rows=6, cols=6)


def _cursedle_run_state(*, guesses: str = "[]") -> dict:
    return {
        "character": "",
        "money": 0,
        "stickers": [],
        "stamps": [],
        "boss": {},
        "board": {
            "money": 0,
            "rows": 6,
            "cols": 6,
            "tiles": [
                {
                    "row": 0,
                    "col": 0,
                    "letter": "A",
                    "curse": "letter",
                    "color": "colorless",
                }
            ],
        },
        "extras": {
            "encounter_mode": "cursedle",
            "cursedle_guesses": guesses,
            "cursedle_guesses_used": "0",
            "cursedle_guesses_remaining": "5",
        },
    }


def _ui_layout_run_state() -> dict:
    state = _cursedle_run_state()
    state["ui_layout"] = {
        "board": {
            "x": 100,
            "y": 200,
            "width": 700,
            "height": 700,
            "cells": [{"row": 0, "col": 0, "index": 0, "x": 170, "y": 270}],
        },
        "consumable_rack": {
            "x": 1908,
            "y": 422,
            "width": 245,
            "height": 106,
            "rack_slots": [
                {"rack_index": i, "x": 1920 + i * 50, "y": 450}
                for i in range(5)
            ],
        },
    }
    return state


@pytest.fixture
def suggestion_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "last_suggestion.json"
    monkeypatch.setattr(
        "cursed_words_solver.config.LAST_SUGGESTION_PATH",
        path,
    )
    monkeypatch.setattr(
        "cursed_words_solver.suggestion.LAST_SUGGESTION_PATH",
        path,
    )
    monkeypatch.setattr(
        "cursed_words_solver.cursedle_solver.LAST_SUGGESTION_PATH",
        path,
    )
    return path


def test_save_cursedle_fingerprints_match_run_state(
    suggestion_path: Path,
) -> None:
    run_state = _cursedle_run_state()
    board = _board_6x6(["A"] * 36)
    loadout = Loadout(extras=run_state["extras"])
    advice = CursedleAdvice(
        word="AAAA",
        path=[0, 1, 2, 3],
        candidates=10,
        guesses_used=0,
        guesses_remaining=5,
        reason="probe",
        warnings=[],
    )
    expected_board_fp, expected_loadout_fp = fingerprints_from_run_state(run_state)

    save_cursedle_suggestion(
        board=board,
        loadout=loadout,
        advice=advice,
        run_state_snapshot=run_state,
    )

    saved = json.loads(suggestion_path.read_text(encoding="utf-8"))
    assert saved["board_fingerprint"] == expected_board_fp
    assert saved["loadout_fingerprint"] == expected_loadout_fp
    assert saved["mode"] == "cursedle"


def test_poll_stable_after_cursedle_save(suggestion_path: Path) -> None:
    run_state = _cursedle_run_state()
    board = _board_6x6(["A"] * 36)
    loadout = Loadout(extras=run_state["extras"])
    advice = CursedleAdvice(
        word="AAAA",
        path=[0, 1, 2, 3],
        candidates=10,
        guesses_used=0,
        guesses_remaining=5,
        reason="probe",
        warnings=[],
    )
    save_cursedle_suggestion(
        board=board,
        loadout=loadout,
        advice=advice,
        run_state_snapshot=run_state,
    )
    board_fp, loadout_fp = fingerprints_from_run_state(run_state)

    reason = poll_invalidate_last_suggestion(
        run_state["extras"],
        current_board_fp=board_fp,
        current_loadout_fp=loadout_fp,
    )
    assert reason is None


def test_poll_ignores_loadout_drift_for_cursedle(suggestion_path: Path) -> None:
    run_state = _cursedle_run_state()
    board = _board_6x6(["A"] * 36)
    loadout = Loadout(extras=run_state["extras"])
    advice = CursedleAdvice(
        word="AAAA",
        path=[0, 1, 2, 3],
        candidates=10,
        guesses_used=0,
        guesses_remaining=5,
        reason="probe",
        warnings=[],
    )
    save_cursedle_suggestion(
        board=board,
        loadout=loadout,
        advice=advice,
        run_state_snapshot=run_state,
    )
    board_fp, _ = fingerprints_from_run_state(run_state)

    reason = poll_invalidate_last_suggestion(
        run_state["extras"],
        current_board_fp=board_fp,
        current_loadout_fp="different|loadout|fingerprint",
    )
    assert reason is None


def test_poll_clears_cursedle_after_guess_history_changes(
    suggestion_path: Path,
) -> None:
    run_state = _cursedle_run_state()
    board = _board_6x6(["A"] * 36)
    loadout = Loadout(extras=run_state["extras"])
    advice = CursedleAdvice(
        word="AAAA",
        path=[0, 1, 2, 3],
        candidates=10,
        guesses_used=0,
        guesses_remaining=5,
        reason="probe",
        warnings=[],
    )
    save_cursedle_suggestion(
        board=board,
        loadout=loadout,
        advice=advice,
        run_state_snapshot=run_state,
    )

    after_guess = _cursedle_run_state(
        guesses=json.dumps(
            [
                {
                    "path": [0, 1, 2, 3],
                    "tiles": [
                        {"feedback": "green"},
                        {"feedback": "yellow"},
                        {"feedback": "red"},
                        {"feedback": "grey"},
                    ],
                }
            ]
        )
    )
    board_fp, loadout_fp = fingerprints_from_run_state(after_guess)

    reason = poll_invalidate_last_suggestion(
        after_guess["extras"],
        current_board_fp=board_fp,
        current_loadout_fp=loadout_fp,
    )
    assert reason is not None
    assert not suggestion_path.exists()


def test_poll_stable_when_only_cursedle_guess_suffix_changes(
    suggestion_path: Path,
) -> None:
    run_state = _cursedle_run_state()
    board = _board_6x6(["A"] * 36)
    loadout = Loadout(extras=run_state["extras"])
    advice = CursedleAdvice(
        word="AAAA",
        path=[0, 1, 2, 3],
        candidates=10,
        guesses_used=0,
        guesses_remaining=5,
        reason="probe",
        warnings=[],
    )
    save_cursedle_suggestion(
        board=board,
        loadout=loadout,
        advice=advice,
        run_state_snapshot=run_state,
    )
    saved = json.loads(suggestion_path.read_text(encoding="utf-8"))
    tiles_fp = board_fingerprint_tiles_only_from_fp(saved["board_fingerprint"])
    drift_fp = f"{tiles_fp}|0|0:green"

    reason = poll_invalidate_last_suggestion(
        run_state["extras"],
        current_board_fp=drift_fp,
        current_loadout_fp=saved["loadout_fingerprint"],
    )
    assert reason is None
    assert suggestion_path.exists()


def test_resolve_overlay_strips_rack_for_cursedle() -> None:
    run_state = _ui_layout_run_state()
    config = AppConfig(
        board_region=Region(1, 2, 3, 4),
        rack_region=Region(5, 6, 7, 8),
    )
    regions = resolve_overlay_regions(run_state, config)
    assert regions.board.is_valid()
    assert not regions.rack.is_valid()
    assert regions.rack_slot_centers is None
    assert not regions.rack_slot_corrected
    assert not regions.rack_layout_collapsed
