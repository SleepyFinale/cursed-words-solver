"""Cursedle Sluggish Zombie theme: z_as_s on path must resolve for dictionary checks."""

from __future__ import annotations

import json
from pathlib import Path

from cursed_words_solver.cursedle_solver import (
    _path_dictionary_word_any_resolution,
    filter_candidates,
    run_cursedle_solver,
)
from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.loadout import parse_board_from_run_state
from cursed_words_solver.models import Board, CurseType, Loadout, Tile, TileColor

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "cursedle" / "20260707_zombie_senate.json"

SENATE_PATH = [33, 32, 31, 26, 21, 22]

AUBRIETAS_NERITE_GUESSES_JSON = json.dumps(
    [
        {
            "path": [12, 18, 25, 26, 21, 16, 15, 10, 5],
            "tiles": [
                {"row": 3, "col": 0, "index": 12, "feedback": "grey"},
                {"row": 2, "col": 0, "index": 18, "feedback": "grey"},
                {"row": 1, "col": 1, "index": 25, "feedback": "grey"},
                {"row": 1, "col": 2, "index": 26, "feedback": "grey"},
                {"row": 2, "col": 3, "index": 21, "feedback": "red"},
                {"row": 3, "col": 4, "index": 16, "feedback": "green"},
                {"row": 3, "col": 3, "index": 15, "feedback": "yellow"},
                {"row": 4, "col": 4, "index": 10, "feedback": "red"},
                {"row": 5, "col": 5, "index": 5, "feedback": "grey"},
            ],
        },
        {
            "path": [1, 2, 9, 8, 15, 16],
            "tiles": [
                {"row": 5, "col": 1, "index": 1, "feedback": "yellow"},
                {"row": 5, "col": 2, "index": 2, "feedback": "green"},
                {"row": 4, "col": 3, "index": 9, "feedback": "red"},
                {"row": 4, "col": 2, "index": 8, "feedback": "green"},
                {"row": 3, "col": 3, "index": 15, "feedback": "green"},
                {"row": 3, "col": 4, "index": 16, "feedback": "green"},
            ],
        },
    ]
)

_GRID_ROWS = [
    "RZVNLB",
    "EBRZCA",
    "UNDIOO",
    "ACSTEE",
    "YM?RAW",
    "YNEZTS",
]


def _letter_tile(row: int, col: int, letter: str) -> Tile:
    return Tile(
        row=row,
        col=col,
        char=letter.lower(),
        letter=letter,
        base_score=1.0,
        color=TileColor.COLORLESS,
        curse=CurseType.LETTER,
    )


def _zombie_item_tile(row: int, col: int, letter: str) -> Tile:
    return Tile(
        row=row,
        col=col,
        char="🧟",
        letter=letter,
        base_score=0.0,
        color=TileColor.COLORLESS,
        curse=CurseType.ITEM,
        metadata={"scattered_item_id": "sluggish_zombie", "scattered_item_level": 1},
    )


def _zombie_senate_board() -> Board:
    tiles: list[list[Tile]] = []
    for row, letters in enumerate(_GRID_ROWS):
        row_tiles: list[Tile] = []
        for col, ch in enumerate(letters):
            if ch == "?":
                row_tiles.append(_zombie_item_tile(row, col, "A"))
            else:
                row_tiles.append(_letter_tile(row, col, ch))
        tiles.append(row_tiles)
    return Board(tiles=tiles, rows=6, cols=6)


def _loadout_from_guesses() -> Loadout:
    return Loadout(
        extras={
            "encounter_mode": "cursedle",
            "cursedle_active": "true",
            "cursedle_guesses_used": "2",
            "cursedle_guesses_remaining": "3",
            "cursedle_guesses": AUBRIETAS_NERITE_GUESSES_JSON,
            "grid_scattered_items": json.dumps(
                [{"row": 4, "col": 2, "id": "sluggish_zombie", "level": 1}]
            ),
        }
    )


def _board_and_loadout() -> tuple[Board, Loadout]:
    if FIXTURE.exists():
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        board = parse_board_from_run_state(payload)
        extras = payload.get("extras", {})
        loadout = Loadout(
            extras={
                "encounter_mode": "cursedle",
                "cursedle_active": "true",
                "cursedle_guesses_used": extras.get("cursedle_guesses_used", "2"),
                "cursedle_guesses_remaining": extras.get("cursedle_guesses_remaining", "3"),
                "cursedle_guesses": extras.get("cursedle_guesses", AUBRIETAS_NERITE_GUESSES_JSON),
                "grid_scattered_items": extras.get(
                    "grid_scattered_items",
                    json.dumps(
                        [{"row": 4, "col": 2, "id": "sluggish_zombie", "level": 1}]
                    ),
                ),
            }
        )
        return board, loadout
    return _zombie_senate_board(), _loadout_from_guesses()


def test_zombie_senate_path_resolves_with_path_flags() -> None:
    board = _zombie_senate_board()
    dictionary = WordDictionary()
    word = _path_dictionary_word_any_resolution(board, SENATE_PATH, dictionary)
    assert word == "senate"


def test_filter_candidates_unique_senate_path() -> None:
    board, loadout = _board_and_loadout()
    from cursed_words_solver.cursedle_solver import parse_cursedle_guesses

    paths = filter_candidates(board, parse_cursedle_guesses(loadout.extras))
    assert paths == [SENATE_PATH]


def test_run_cursedle_solver_suggests_senate() -> None:
    board, loadout = _board_and_loadout()
    dictionary = WordDictionary()
    advice = run_cursedle_solver(board, loadout, dictionary)
    assert advice.word.lower() == "senate"
    assert advice.path == SENATE_PATH
    assert advice.candidates >= 1
