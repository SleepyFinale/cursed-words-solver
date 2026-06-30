"""Cursedle theme-tile dictionary resolution (Card Shark, etc.)."""

from __future__ import annotations

from cursed_words_solver.cursedle_solver import (
    _path_dictionary_word_any_resolution,
    _primary_cursedle_flags,
)
from cursed_words_solver.models import Board, CurseType, Tile, TileColor
from cursed_words_solver.rules.stamp_behaviors import FLAG_CARD_SUIT_FIRST_LETTER


class _FakeDictionary:
    def __init__(self, words: set[str]) -> None:
        self._words = {w.lower() for w in words}

    def contains(self, word: str) -> bool:
        return word.lower() in self._words


def _card_tile(row: int, col: int, rank: str, suit: str) -> Tile:
    return Tile(
        row=row,
        col=col,
        char=rank.lower(),
        letter=rank,
        base_score=1.0,
        color=TileColor.COLORLESS,
        curse=CurseType.CARD,
        metadata={"card_suit": suit, "card_rank": rank},
    )


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


def test_primary_flags_enable_card_suit_letters() -> None:
    tiles = [
        [_card_tile(0, 0, "K", "hearts"), _letter_tile(0, 1, "I"), _letter_tile(0, 2, "N"), _letter_tile(0, 3, "G")]
        + [_letter_tile(0, c, "A") for c in range(4, 6)],
        *[[_letter_tile(r, c, "A") for c in range(6)] for r in range(1, 6)],
    ]
    board = Board(tiles=tiles, rows=6, cols=6)
    assert _primary_cursedle_flags(board) == FLAG_CARD_SUIT_FIRST_LETTER
    dictionary = _FakeDictionary({"hing"})
    word = _path_dictionary_word_any_resolution(board, [0, 1, 2, 3], dictionary)
    assert word == "hing"
