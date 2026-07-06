"""Cursedle Hungry Snake scattered-item overlay on solution letters."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cursed_words_solver.cursedle_solver import (
    _cursedle_path_movement_ok,
    _cursedle_word_from_path,
    _narrow_candidates_to_dictionary,
    _path_dictionary_word_any_resolution,
    _pick_final_guess,
    enumerate_candidate_paths,
    filter_candidates,
    parse_cursedle_guesses,
    run_cursedle_solver,
)
from cursed_words_solver.search import path_movement_ok
from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
from cursed_words_solver.models import Board, CurseType, Loadout, Tile, TileColor
LIVE_RUN_STATE = Path.home() / ".cursed_words_solver" / "run_state.json"

CHAO_SNAKE_PATH = [32, 27, 34, 35]
CHAO_DECOY_PATH = [32, 27, 34, 33]
CHANT_EXT_PATH = [32, 27, 34, 35, 28]
CHAOS_SNAKE_PATH = [32, 27, 34, 35, 30]

ANTHIMERIA_SECO_GUESSES_JSON = json.dumps(
    [
        {
            "path": [16, 17, 10, 9, 8, 15, 21, 28, 33, 26],
            "tiles": [
                {"row": 3, "col": 4, "index": 16, "feedback": "red"},
                {"row": 3, "col": 5, "index": 17, "feedback": "grey"},
                {"row": 4, "col": 4, "index": 10, "feedback": "red"},
                {"row": 4, "col": 3, "index": 9, "feedback": "yellow"},
                {"row": 4, "col": 2, "index": 8, "feedback": "red"},
                {"row": 3, "col": 3, "index": 15, "feedback": "red"},
                {"row": 2, "col": 3, "index": 21, "feedback": "grey"},
                {"row": 1, "col": 4, "index": 28, "feedback": "grey"},
                {"row": 0, "col": 3, "index": 33, "feedback": "grey"},
                {"row": 1, "col": 2, "index": 26, "feedback": "grey"},
            ],
        },
        {
            "path": [0, 1, 2, 3],
            "tiles": [
                {"row": 5, "col": 0, "index": 0, "feedback": "yellow"},
                {"row": 5, "col": 1, "index": 1, "feedback": "red"},
                {"row": 5, "col": 2, "index": 2, "feedback": "yellow"},
                {"row": 5, "col": 3, "index": 3, "feedback": "red"},
            ],
        },
    ]
)

HUNGRY_SNAKE_GUESSES_JSON = json.dumps(
    [
        {
            "path": [16, 17, 10, 9, 8, 15, 21, 28, 33, 26],
            "tiles": [
                {"row": 3, "col": 4, "index": 16, "feedback": "red"},
                {"row": 3, "col": 5, "index": 17, "feedback": "grey"},
                {"row": 4, "col": 4, "index": 10, "feedback": "red"},
                {"row": 4, "col": 3, "index": 9, "feedback": "yellow"},
                {"row": 4, "col": 2, "index": 8, "feedback": "red"},
                {"row": 3, "col": 3, "index": 15, "feedback": "red"},
                {"row": 2, "col": 3, "index": 21, "feedback": "grey"},
                {"row": 1, "col": 4, "index": 28, "feedback": "grey"},
                {"row": 0, "col": 3, "index": 33, "feedback": "grey"},
                {"row": 1, "col": 2, "index": 26, "feedback": "grey"},
            ],
        },
        {
            "path": [2, 9, 4, 5],
            "tiles": [
                {"row": 5, "col": 2, "index": 2, "feedback": "green"},
                {"row": 4, "col": 3, "index": 9, "feedback": "green"},
                {"row": 5, "col": 4, "index": 4, "feedback": "green"},
                {"row": 5, "col": 5, "index": 5, "feedback": "green"},
            ],
        },
    ]
)


class _FakeDictionary:
    def __init__(self, words: set[str]) -> None:
        self._words = {w.lower() for w in words}

    def contains(self, word: str) -> bool:
        return word.lower() in self._words

    def enumerate_pattern_matches(
        self,
        pattern: str,
        *,
        limit: int | None = None,
        deadline_check=None,
    ) -> list[str]:
        results: list[str] = []
        for word in sorted(self._words):
            if len(word) != len(pattern):
                continue
            if all(p == "?" or p == c for p, c in zip(pattern, word)):
                results.append(word)
                if limit is not None and len(results) >= limit:
                    break
        return results


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


def _snake_item_tile(row: int, col: int, letter: str) -> Tile:
    return Tile(
        row=row,
        col=col,
        char="🐍",
        letter=letter,
        base_score=0.0,
        color=TileColor.COLORLESS,
        curse=CurseType.ITEM,
        metadata={"scattered_item_id": "hungry_snake", "scattered_item_level": 1},
    )


def _alpha_item_tile(row: int, col: int, letter: str) -> Tile:
    return Tile(
        row=row,
        col=col,
        char=letter.lower(),
        letter=letter,
        base_score=0.0,
        color=TileColor.COLORLESS,
        curse=CurseType.ITEM,
        metadata={"scattered_item_id": "card_shark"},
    )


def _hungry_snake_board() -> Board:
    tiles = [[_letter_tile(r, c, "A") for c in range(6)] for r in range(6)]
    tiles[5][2] = _letter_tile(5, 2, "C")
    tiles[4][3] = _letter_tile(4, 3, "H")
    tiles[5][4] = _letter_tile(5, 4, "A")
    tiles[5][3] = _letter_tile(5, 3, "O")
    tiles[5][5] = _snake_item_tile(5, 5, "O")
    tiles[4][5] = _letter_tile(4, 5, "Y")
    tiles[4][4] = _letter_tile(4, 4, "T")
    return Board(tiles=tiles, rows=6, cols=6)


def _chaos_board() -> Board:
    """Bottom-row Hungry Snake layout with CHAOS wrap (S at col 0, snake at col 5)."""
    tiles = [[_letter_tile(r, c, "X") for c in range(6)] for r in range(6)]
    tiles[5][0] = _letter_tile(5, 0, "S")
    tiles[5][1] = _letter_tile(5, 1, "E")
    tiles[5][2] = _letter_tile(5, 2, "C")
    tiles[5][3] = _letter_tile(5, 3, "O")
    tiles[5][4] = _letter_tile(5, 4, "A")
    tiles[5][5] = _snake_item_tile(5, 5, "O")
    tiles[4][3] = _letter_tile(4, 3, "H")
    tiles[4][1] = _letter_tile(4, 1, "B")
    return Board(tiles=tiles, rows=6, cols=6)


def test_chaos_path_requires_snake_wrap_for_movement() -> None:
    board = _chaos_board()
    assert not path_movement_ok(board, CHAOS_SNAKE_PATH)
    assert _cursedle_path_movement_ok(board, CHAOS_SNAKE_PATH)


def test_chaos_path_enumerated_with_snake_wrap() -> None:
    board = _chaos_board()
    paths = enumerate_candidate_paths(board, min_len=5, max_len=5)
    assert CHAOS_SNAKE_PATH in paths


def test_chaos_path_resolves_to_dictionary_word() -> None:
    board = _chaos_board()
    dictionary = WordDictionary()
    assert _cursedle_word_from_path(board, CHAOS_SNAKE_PATH) == "cha?s"
    word = _path_dictionary_word_any_resolution(board, CHAOS_SNAKE_PATH, dictionary)
    assert word == "chaos"


@pytest.mark.skipif(not LIVE_RUN_STATE.exists(), reason="live run_state.json not present")
def test_run_cursedle_solver_finds_chaos_after_anthimeria_seco() -> None:
    payload = json.loads(LIVE_RUN_STATE.read_text(encoding="utf-8"))
    board = parse_board_from_run_state(payload)
    loadout = Loadout(
        extras={
            "encounter_mode": "cursedle",
            "cursedle_guesses_used": "2",
            "cursedle_guesses_remaining": "3",
            "cursedle_guesses": ANTHIMERIA_SECO_GUESSES_JSON,
        }
    )
    dictionary = WordDictionary()
    advice = run_cursedle_solver(board, loadout, dictionary)
    assert advice.word.lower() == "chaos"
    assert advice.path == CHAOS_SNAKE_PATH
    assert advice.candidates >= 1


def test_cursedle_word_from_path_chess_tile_is_wildcard() -> None:
    board = _hungry_snake_board()
    board.tiles[4][3] = Tile(
        row=4,
        col=3,
        char="n",
        letter="N",
        base_score=1.0,
        color=TileColor.COLORLESS,
        curse=CurseType.CHESS_KNIGHT,
    )
    assert _cursedle_word_from_path(board, [32, 27, 34, 35]) == "c?a?"


def test_cursedle_word_from_path_emoji_snake_is_wildcard() -> None:
    board = _hungry_snake_board()
    assert _cursedle_word_from_path(board, CHAO_SNAKE_PATH) == "cha?"
    assert _cursedle_word_from_path(board, CHAO_DECOY_PATH) == "chao"


def test_cursedle_word_from_path_alpha_item_face_uses_letter() -> None:
    board = _hungry_snake_board()
    board.tiles[5][5] = _alpha_item_tile(5, 5, "O")
    assert _cursedle_word_from_path(board, CHAO_SNAKE_PATH) == "chao"


def test_path_dictionary_word_any_resolution_snake_emoji_pattern() -> None:
    board = _hungry_snake_board()
    dictionary = _FakeDictionary({"chao", "chay"})
    word = _path_dictionary_word_any_resolution(board, CHAO_SNAKE_PATH, dictionary)
    assert word == "chao"


def test_path_dictionary_word_five_tile_extension() -> None:
    board = _hungry_snake_board()
    dictionary = _FakeDictionary({"chant", "chao"})
    word = _path_dictionary_word_any_resolution(board, CHANT_EXT_PATH, dictionary)
    assert word == "chant"


def test_pattern_fallback_when_item_has_no_letter() -> None:
    board = _hungry_snake_board()
    board.tiles[5][5] = Tile(
        row=5,
        col=5,
        char="?",
        letter="",
        base_score=0.0,
        color=TileColor.COLORLESS,
        curse=CurseType.ITEM,
        metadata={"scattered_item_id": "hungry_snake"},
    )
    dictionary = _FakeDictionary({"chao", "chay"})
    word = _path_dictionary_word_any_resolution(board, CHAO_SNAKE_PATH, dictionary)
    assert word in {"chao", "chay"}


def test_pick_final_guess_does_not_repeat_all_green_chao() -> None:
    if not LIVE_RUN_STATE.exists():
        pytest.skip("live run_state.json not present")
    payload = json.loads(LIVE_RUN_STATE.read_text(encoding="utf-8"))
    board = parse_board_from_run_state(payload)
    guesses = parse_cursedle_guesses({"cursedle_guesses": HUNGRY_SNAKE_GUESSES_JSON})
    dictionary = WordDictionary()
    feedback = filter_candidates(board, guesses)
    narrowed = _narrow_candidates_to_dictionary(board, feedback, dictionary)
    pick = _pick_final_guess(board, narrowed, dictionary, guesses)
    assert pick is not None
    path, word = pick
    assert path != CHAO_SNAKE_PATH
    assert word.lower() != "chao"


@pytest.mark.skipif(not LIVE_RUN_STATE.exists(), reason="live run_state.json not present")
def test_run_cursedle_solver_does_not_repeat_chao_after_all_green() -> None:
    payload = json.loads(LIVE_RUN_STATE.read_text(encoding="utf-8"))
    board = parse_board_from_run_state(payload)
    loadout = Loadout(
        extras={
            "encounter_mode": "cursedle",
            "cursedle_guesses_used": "2",
            "cursedle_guesses_remaining": "3",
            "cursedle_guesses": HUNGRY_SNAKE_GUESSES_JSON,
        }
    )
    dictionary = WordDictionary()
    advice = run_cursedle_solver(board, loadout, dictionary)
    assert advice.path != CHAO_SNAKE_PATH
    assert advice.word.lower() != "chao"


def test_run_cursedle_solver_prefers_longer_extension_after_all_green_prefix() -> None:
    if not LIVE_RUN_STATE.exists():
        pytest.skip("live run_state.json not present")
    payload = json.loads(LIVE_RUN_STATE.read_text(encoding="utf-8"))
    board = parse_board_from_run_state(payload)
    loadout = Loadout(
        extras={
            "encounter_mode": "cursedle",
            "cursedle_guesses_used": "2",
            "cursedle_guesses_remaining": "3",
            "cursedle_guesses": HUNGRY_SNAKE_GUESSES_JSON,
        }
    )
    dictionary = WordDictionary()
    advice = run_cursedle_solver(board, loadout, dictionary)
    if advice.path == CHANT_EXT_PATH:
        assert advice.word.lower() == "chant"
    else:
        assert len(advice.path) > len(CHAO_SNAKE_PATH) or advice.word.lower() != "chao"
