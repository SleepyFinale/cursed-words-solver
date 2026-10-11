"""Cursedle Hungry Snake scattered-item overlay on solution letters."""

from __future__ import annotations

import json


from cursed_words_solver.cursedle_solver import (
    _cursedle_word_from_path,
    _path_dictionary_word_any_resolution,
    enumerate_candidate_paths,
)
from cursed_words_solver.models import Board, CurseType, Tile, TileColor

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
        self.words = sorted(self._words)

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


def test_chaos_path_enumerated_with_snake_wrap() -> None:
    board = _chaos_board()
    paths = enumerate_candidate_paths(board, min_len=5, max_len=5)
    assert CHAOS_SNAKE_PATH in paths


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


