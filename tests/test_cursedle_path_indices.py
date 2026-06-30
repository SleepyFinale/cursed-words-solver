"""Cursedle melmod vs storage path index conversion and probe dedup."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from cursed_words_solver.config import GAME_WORDLIST_PATH
from cursed_words_solver.cursedle_solver import (
    CursedleGuess,
    _guess_storage_path,
    _guessed_words,
    _is_valid_cursedle_solution_path,
    _narrow_candidates_to_dictionary,
    _pick_probe_path,
    filter_candidates,
    parse_cursedle_guesses,
    run_cursedle_solver,
)
from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.loadout import parse_board_from_run_state
from cursed_words_solver.models import Board, CurseType, Loadout, Tile, TileColor
from cursed_words_solver.ui.board_geometry import (
    path_from_melmod_indices,
    path_to_melmod_indices,
)

FOYERS_MELMOD_PATH = [4, 11, 17, 10, 3, 8]
FOYERS_STORAGE_PATH = [34, 29, 23, 28, 33, 26]
FOYER_STORAGE_PATH = FOYERS_STORAGE_PATH[:5]

LIVE_RUN_STATE = Path.home() / ".cursed_words_solver" / "run_state.json"

# Legacy melmod export: Unity bottom-origin row/col with index=row*cols+col
LIVE_UNITY_TILES = [
    {"row": 0, "col": 4, "index": 4, "feedback": "grey"},
    {"row": 1, "col": 5, "index": 11, "feedback": "red"},
    {"row": 2, "col": 5, "index": 17, "feedback": "yellow"},
    {"row": 1, "col": 4, "index": 10, "feedback": "red"},
    {"row": 0, "col": 3, "index": 3, "feedback": "grey"},
    {"row": 1, "col": 2, "index": 8, "feedback": "grey"},
]

# Broken export: storage indices in path/index (CoordsToSolverIndex on Unity coords)
STORAGE_PATH_EXPORT_TILES = [
    {"row": 5, "col": 4, "index": 34, "feedback": "grey"},
    {"row": 4, "col": 5, "index": 29, "feedback": "red"},
    {"row": 3, "col": 5, "index": 23, "feedback": "yellow"},
    {"row": 4, "col": 4, "index": 28, "feedback": "red"},
    {"row": 5, "col": 3, "index": 33, "feedback": "grey"},
    {"row": 4, "col": 2, "index": 26, "feedback": "grey"},
]

# Correct export: melmod path + storage top_first tile rows
CORRECT_EXPORT_TILES = [
    {"row": 5, "col": 4, "index": 4, "feedback": "grey"},
    {"row": 4, "col": 5, "index": 11, "feedback": "red"},
    {"row": 3, "col": 5, "index": 17, "feedback": "yellow"},
    {"row": 4, "col": 4, "index": 10, "feedback": "red"},
    {"row": 5, "col": 3, "index": 3, "feedback": "grey"},
    {"row": 4, "col": 2, "index": 8, "feedback": "grey"},
]


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


def _foyers_board() -> Board:
    letters = ["A"] * 36
    for idx, ch in zip(FOYERS_STORAGE_PATH, "FOYERS"):
        row, col = divmod(idx, 6)
        letters[row * 6 + col] = ch
    return _board_6x6(letters)


def _live_foyers_board() -> Board | None:
    if not LIVE_RUN_STATE.exists():
        return None
    payload = json.loads(LIVE_RUN_STATE.read_text(encoding="utf-8"))
    return parse_board_from_run_state(payload)


def test_melmod_path_converts_to_storage_on_full_6x6() -> None:
    board = _live_foyers_board() or _foyers_board()
    storage = path_from_melmod_indices(board, FOYERS_MELMOD_PATH)
    assert storage == FOYERS_STORAGE_PATH


def test_storage_path_round_trips_through_melmod() -> None:
    board = _foyers_board()
    melmod = path_to_melmod_indices(board, FOYERS_STORAGE_PATH)
    assert melmod == FOYERS_MELMOD_PATH
    assert path_from_melmod_indices(board, melmod) == FOYERS_STORAGE_PATH
    assert path_to_melmod_indices(board, path_from_melmod_indices(board, melmod)) == melmod


def test_guess_storage_path_ignores_unity_tile_rows() -> None:
    board = _foyers_board()
    extras = {
        "cursedle_guesses": json.dumps(
            [{"path": FOYERS_MELMOD_PATH, "tiles": LIVE_UNITY_TILES}]
        )
    }
    guess = parse_cursedle_guesses(extras)[0]
    assert _guess_storage_path(board, guess.path, guess) == FOYERS_STORAGE_PATH


def test_parse_legacy_unity_rows_convert_to_storage_coords() -> None:
    board = _foyers_board()
    extras = {
        "cursedle_guesses": json.dumps(
            [{"path": FOYERS_MELMOD_PATH, "tiles": LIVE_UNITY_TILES}]
        )
    }
    guesses = parse_cursedle_guesses(extras)
    assert len(guesses) == 1
    storage_from_coords = [
        board.index_at(row, col) for row, col in guesses[0].storage_coords
    ]
    assert storage_from_coords == FOYERS_STORAGE_PATH


def test_parse_storage_rows_not_flipped_when_index_matches() -> None:
    extras = {
        "cursedle_guesses": json.dumps(
            [{"path": FOYERS_STORAGE_PATH, "tiles": STORAGE_PATH_EXPORT_TILES}]
        )
    }
    guesses = parse_cursedle_guesses(extras)
    assert guesses[0].storage_coords[0] == (5, 4)


def test_guess_storage_path_accepts_storage_path_export() -> None:
    board = _foyers_board()
    guess = CursedleGuess(
        path=FOYERS_STORAGE_PATH,
        feedback=["grey"] * len(FOYERS_STORAGE_PATH),
        storage_coords=tuple((t["row"], t["col"]) for t in STORAGE_PATH_EXPORT_TILES),
    )
    assert _guess_storage_path(board, guess.path, guess) == FOYERS_STORAGE_PATH


def test_guess_storage_path_melmod_export_with_storage_tile_rows() -> None:
    board = _foyers_board()
    guess = CursedleGuess(
        path=FOYERS_MELMOD_PATH,
        feedback=["grey"] * len(FOYERS_MELMOD_PATH),
        storage_coords=tuple((t["row"], t["col"]) for t in CORRECT_EXPORT_TILES),
    )
    assert _guess_storage_path(board, guess.path, guess) == FOYERS_STORAGE_PATH


def test_guessed_words_from_storage_path_export() -> None:
    board = _foyers_board()

    class _FakeDictionary:
        def contains(self, word: str) -> bool:
            return word.lower() in {"foyers", "foyer"}

    guesses = parse_cursedle_guesses(
        {
            "cursedle_guesses": json.dumps(
                [{"path": FOYERS_STORAGE_PATH, "tiles": STORAGE_PATH_EXPORT_TILES}]
            )
        }
    )
    words = _guessed_words(board, guesses, _FakeDictionary())
    assert "foyers" in words


def test_guessed_words_includes_foyers_from_live_shaped_guess() -> None:
    board = _foyers_board()

    class _FakeDictionary:
        def contains(self, word: str) -> bool:
            return word.lower() in {"foyers", "foyer"}

    extras = {
        "cursedle_guesses": json.dumps(
            [{"path": FOYERS_MELMOD_PATH, "tiles": LIVE_UNITY_TILES}]
        )
    }
    guesses = parse_cursedle_guesses(extras)
    words = _guessed_words(board, guesses, _FakeDictionary())
    assert "foyers" in words


class _FakeDictionary:
    def __init__(self, words: set[str]) -> None:
        self._words = {w.lower() for w in words}

    def contains(self, word: str) -> bool:
        return word.lower() in self._words

    def has_prefix(self, prefix: str) -> bool:
        stem = prefix.lower()
        return any(word.startswith(stem) for word in self._words)

    def is_valid_word(self, word: str, min_len: int = 3) -> bool:
        key = word.lower()
        return len(key) >= min_len and key in self._words


@patch("cursed_words_solver.cursedle_solver._enumerate_dictionary_probe_paths")
def test_pick_probe_skips_foyers_after_melmod_guess(mock_enum) -> None:
    board = _foyers_board()
    dictionary = _FakeDictionary({"foyers", "foyer", "zzzzzz"})
    mock_enum.return_value = [
        ("foyers", FOYERS_STORAGE_PATH),
        ("foyer", FOYER_STORAGE_PATH),
        ("zzzzzz", [12, 13, 14, 15, 16, 17]),
    ]
    guesses = parse_cursedle_guesses(
        {"cursedle_guesses": json.dumps(
            [{"path": FOYERS_MELMOD_PATH, "tiles": LIVE_UNITY_TILES}]
        )}
    )
    candidates = [
        FOYERS_STORAGE_PATH,
        FOYER_STORAGE_PATH,
        [12, 13, 14, 15, 16, 17],
    ]
    picked = _pick_probe_path(board, candidates, dictionary, guesses)
    assert picked is not None
    _path, word = picked
    assert word.lower() == "zzzzzz"


@patch("cursed_words_solver.cursedle_solver._enumerate_dictionary_probe_paths")
def test_pick_probe_skips_foyers_after_storage_path_export(mock_enum) -> None:
    board = _foyers_board()
    dictionary = _FakeDictionary({"foyers", "foyer", "zzzzzz"})
    mock_enum.return_value = [
        ("foyers", FOYERS_STORAGE_PATH),
        ("zzzzzz", [12, 13, 14, 15, 16, 17]),
    ]
    guesses = parse_cursedle_guesses(
        {
            "cursedle_guesses": json.dumps(
                [{"path": FOYERS_STORAGE_PATH, "tiles": STORAGE_PATH_EXPORT_TILES}]
            )
        }
    )
    picked = _pick_probe_path(
        board,
        [FOYERS_STORAGE_PATH, [12, 13, 14, 15, 16, 17]],
        dictionary,
        guesses,
    )
    assert picked is not None
    _path, word = picked
    assert word.lower() == "zzzzzz"


@patch("cursed_words_solver.cursedle_solver._enumerate_dictionary_probe_paths")
def test_pick_probe_skips_foyer_prefix_after_foyers(mock_enum) -> None:
    board = _foyers_board()
    dictionary = _FakeDictionary({"foyers", "foyer", "zzzzzz"})
    mock_enum.return_value = [
        ("foyer", FOYER_STORAGE_PATH),
        ("zzzzzz", [12, 13, 14, 15, 16, 17]),
    ]
    guesses = [
        CursedleGuess(
            path=FOYERS_MELMOD_PATH,
            feedback=["grey"] * len(FOYERS_MELMOD_PATH),
        )
    ]
    picked = _pick_probe_path(
        board,
        [FOYER_STORAGE_PATH, [12, 13, 14, 15, 16, 17]],
        dictionary,
        guesses,
    )
    assert picked is not None
    _path, word = picked
    assert word.lower() == "zzzzzz"


SHADY_CURSEDLE_PATH = [35, 29, 23, 22, 27]
SHADY_STORAGE_PROBE = [5, 11, 17, 16, 9]
SHADY_STORAGE_SOLUTION = [5, 11, 17, 16, 23]

SHADY_MELMOD_EXPORT_TILES = [
    {"row": 0, "col": 5, "index": 35, "feedback": "green"},
    {"row": 1, "col": 5, "index": 29, "feedback": "green"},
    {"row": 2, "col": 5, "index": 23, "feedback": "green"},
    {"row": 2, "col": 4, "index": 22, "feedback": "green"},
    {"row": 1, "col": 3, "index": 27, "feedback": "red"},
]

UPSTREAM_CURSEDLE_PATH = [16, 21, 15, 14, 7, 13, 18, 12]
UPSTREAM_MELMOD_EXPORT_TILES = [
    {"row": 3, "col": 4, "index": 16, "feedback": "red"},
    {"row": 2, "col": 3, "index": 21, "feedback": "red"},
    {"row": 3, "col": 3, "index": 15, "feedback": "red"},
    {"row": 3, "col": 2, "index": 14, "feedback": "grey"},
    {"row": 4, "col": 1, "index": 7, "feedback": "grey"},
    {"row": 3, "col": 1, "index": 13, "feedback": "grey"},
    {"row": 2, "col": 0, "index": 18, "feedback": "grey"},
    {"row": 3, "col": 0, "index": 12, "feedback": "grey"},
]


def _shady_puzzle_board() -> Board:
    if LIVE_RUN_STATE.exists():
        payload = json.loads(LIVE_RUN_STATE.read_text(encoding="utf-8"))
        board = parse_board_from_run_state(payload)
        if board is not None:
            return board
    letters = list("UHYE?S" + "PE?YQH" + "AAYPDA" + "METSUY" + "TRSOEO" + "OEMRFY")
    letters[8] = "?"
    letters[22] = "?"
    return _board_6x6(letters)


def test_parse_shady_melmod_export_preserves_storage_row() -> None:
    extras = {
        "cursedle_guesses": json.dumps(
            [{"path": SHADY_CURSEDLE_PATH, "tiles": SHADY_MELMOD_EXPORT_TILES}]
        )
    }
    guesses = parse_cursedle_guesses(extras)
    assert guesses[0].storage_coords[0] == (0, 5)


def test_guess_storage_path_shady_cursedle_export() -> None:
    board = _shady_puzzle_board()
    guess = parse_cursedle_guesses(
        {
            "cursedle_guesses": json.dumps(
                [{"path": SHADY_CURSEDLE_PATH, "tiles": SHADY_MELMOD_EXPORT_TILES}]
            )
        }
    )[0]
    assert _guess_storage_path(board, guess.path, guess) == SHADY_STORAGE_PROBE


def test_filter_candidates_includes_shady_with_y_at_23() -> None:
    board = _shady_puzzle_board()
    extras = {
        "cursedle_guesses": json.dumps(
            [
                {"path": UPSTREAM_CURSEDLE_PATH, "tiles": UPSTREAM_MELMOD_EXPORT_TILES},
                {"path": SHADY_CURSEDLE_PATH, "tiles": SHADY_MELMOD_EXPORT_TILES},
            ]
        )
    }
    guesses = parse_cursedle_guesses(extras)
    candidates = filter_candidates(board, guesses, min_len=5, max_len=5)
    assert candidates, "feedback filter must leave solution candidates"
    assert SHADY_STORAGE_SOLUTION in candidates


SHADY_NONWORD_PATH = [5, 11, 17, 16, 10]


def _shady_game_dictionary() -> WordDictionary:
    return WordDictionary(GAME_WORDLIST_PATH)


def test_is_valid_cursedle_solution_path_shady_board() -> None:
    board = _shady_puzzle_board()
    dictionary = _shady_game_dictionary()
    assert _is_valid_cursedle_solution_path(
        board, SHADY_STORAGE_SOLUTION, dictionary
    )
    assert not _is_valid_cursedle_solution_path(
        board, SHADY_NONWORD_PATH, dictionary
    )


def test_narrow_candidates_to_dictionary_shady_only() -> None:
    board = _shady_puzzle_board()
    dictionary = _shady_game_dictionary()
    extras = {
        "cursedle_guesses": json.dumps(
            [
                {"path": UPSTREAM_CURSEDLE_PATH, "tiles": UPSTREAM_MELMOD_EXPORT_TILES},
                {"path": SHADY_CURSEDLE_PATH, "tiles": SHADY_MELMOD_EXPORT_TILES},
            ]
        )
    }
    guesses = parse_cursedle_guesses(extras)
    feedback = filter_candidates(board, guesses, min_len=5, max_len=6)
    assert len(feedback) > 1
    narrowed = _narrow_candidates_to_dictionary(board, feedback, dictionary)
    assert narrowed == [SHADY_STORAGE_SOLUTION]
    assert SHADY_NONWORD_PATH not in narrowed


def test_run_cursedle_solver_commits_shady_after_upstream_shady() -> None:
    board = _shady_puzzle_board()
    dictionary = _shady_game_dictionary()
    loadout = Loadout(
        extras={
            "encounter_mode": "cursedle",
            "cursedle_guesses": json.dumps(
                [
                    {
                        "path": UPSTREAM_CURSEDLE_PATH,
                        "tiles": UPSTREAM_MELMOD_EXPORT_TILES,
                    },
                    {
                        "path": SHADY_CURSEDLE_PATH,
                        "tiles": SHADY_MELMOD_EXPORT_TILES,
                    },
                ]
            ),
            "cursedle_guesses_used": "2",
            "cursedle_guesses_remaining": "3",
        }
    )
    advice = run_cursedle_solver(board, loadout, dictionary)
    assert advice.word.lower() == "shady"
    assert advice.path == SHADY_STORAGE_SOLUTION
    assert advice.candidates == 2  # shad (len 4) and shady (len 5)
    assert "committing" in advice.reason.lower()
    assert "foyers" not in advice.word.lower()
