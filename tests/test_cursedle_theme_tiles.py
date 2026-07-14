"""Cursedle theme-tile dictionary resolution (Card Shark, etc.).

Card Shark suit letters follow game Tile.IsDisplayingAsVariableLetter:
enabled only when CardShark is in player items for the submission (inventory
or a scattered CardShark on the selected path). Fairy Grid places a live
card_shark ITEM — cards alone on the board do not enable suit letters.
"""

from __future__ import annotations

from cursed_words_solver.cursedle_solver import (
    _path_dictionary_word_any_resolution,
    _primary_cursedle_flags,
)
from cursed_words_solver.models import Board, CurseType, Tile, TileColor


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


def _card_shark_item(row: int, col: int, letter: str = "A") -> Tile:
    """Scattered CardShark overlaid on a letter cell (Fairy Grid style)."""
    return Tile(
        row=row,
        col=col,
        char=letter.lower(),
        letter=letter,
        base_score=1.0,
        color=TileColor.COLORLESS,
        curse=CurseType.ITEM,
        metadata={"scattered_item_id": "card_shark", "scattered_item_level": 1},
    )


def test_primary_flags_do_not_enable_card_suit_from_poker_cards_alone() -> None:
    tiles = [
        [_card_tile(0, 0, "K", "hearts"), _letter_tile(0, 1, "I"), _letter_tile(0, 2, "N"), _letter_tile(0, 3, "G")]
        + [_letter_tile(0, c, "A") for c in range(4, 6)],
        *[[_letter_tile(r, c, "A") for c in range(6)] for r in range(1, 6)],
    ]
    board = Board(tiles=tiles, rows=6, cols=6)
    assert _primary_cursedle_flags(board) == 0
    dictionary = _FakeDictionary({"hing", "king"})
    # Without card_shark on the path, K♥ stays face K — not suit H.
    assert _path_dictionary_word_any_resolution(board, [0, 1, 2, 3], dictionary) == "king"


def test_card_shark_on_path_enables_suit_letters() -> None:
    # Shark overlaid on the I of hing; K♥ resolves to H only because shark is on path.
    tiles = [
        [
            _card_tile(0, 0, "K", "hearts"),
            _card_shark_item(0, 1, "I"),
            _letter_tile(0, 2, "N"),
            _letter_tile(0, 3, "G"),
        ]
        + [_letter_tile(0, c, "A") for c in range(4, 6)],
        *[[_letter_tile(r, c, "A") for c in range(6)] for r in range(1, 6)],
    ]
    board = Board(tiles=tiles, rows=6, cols=6)
    assert _primary_cursedle_flags(board) == 0
    # Face-only spells "king"; only suit remapping (shark on path) yields "hing".
    dictionary = _FakeDictionary({"hing"})
    word = _path_dictionary_word_any_resolution(board, [0, 1, 2, 3], dictionary)
    assert word == "hing"
