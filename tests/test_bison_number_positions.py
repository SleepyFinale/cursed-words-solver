"""Bison high-number tiles: position locks above 8 and multi-digit faces (10–17)."""

from __future__ import annotations

from pathlib import Path

import pytest

from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.models import Board, CurseType, Tile, TileColor
from cursed_words_solver.rules.stamp_behaviors import stamp_search_flags
from cursed_words_solver.loadout import Loadout
from cursed_words_solver.search import (
    PathValidator,
    _max_number_face_on_board,
    _tile_digit_face_matches,
    number_position_valid,
)


def _letter(r: int, c: int, ch: str) -> Tile:
    return Tile(
        row=r,
        col=c,
        char=ch,
        letter=ch.upper(),
        base_score=1.0,
        color=TileColor.COLORLESS,
        curse=CurseType.LETTER,
    )


def _number(r: int, c: int, face: int) -> Tile:
    s = str(face)
    return Tile(
        row=r,
        col=c,
        char=s,
        letter=s,
        base_score=float(face),
        color=TileColor.COLORLESS,
        curse=CurseType.NUMBER,
        number_value=face,
    )


def _empty_board() -> Board:
    return Board(
        tiles=[
            [_letter(r, c, "a") for c in range(5)]
            for r in range(5)
        ]
    )


def _path_indices(count: int) -> list[int]:
    """Snake path of `count` tiles across the 5×5 grid (4-connected)."""
    rows: list[list[int]] = []
    for r in range(5):
        if r % 2 == 0:
            rows.append([r * 5 + c for c in range(5)])
        else:
            rows.append([r * 5 + c for c in range(4, -1, -1)])
    flat: list[int] = []
    for row in rows:
        flat.extend(row)
    return flat[:count]


def _wordlist(tmp_path: Path, *words: str) -> Path:
    p = tmp_path / "words.txt"
    p.write_text("\n".join(words), encoding="utf-8")
    return p


def test_number_position_valid_accepts_nine_at_ninth_tile():
    tile = _number(0, 0, 9)
    assert number_position_valid(tile, 8, flags=0)
    assert not number_position_valid(tile, 7, flags=0)


def test_tile_digit_face_matches_multi_digit():
    tile = _number(0, 0, 10)
    assert _tile_digit_face_matches("10", tile, 0)
    assert not _tile_digit_face_matches("1", tile, 0)
    assert _tile_digit_face_matches("9", _number(0, 0, 9), 0)


def test_max_number_face_on_board():
    board = _empty_board()
    board.tiles[0][0] = _number(0, 0, 9)
    board.tiles[0][1] = _number(0, 1, 12)
    assert _max_number_face_on_board(board) == 12


def test_word_ok_ten_tile_path_with_face_ten(tmp_path: Path):
    """10-tile path: number 10 at position 10 consumes two-char face in word string."""
    wl = _wordlist(tmp_path, "abcdefghij")
    d = WordDictionary(wl)
    board = _empty_board()
    path = _path_indices(10)
    for i, idx in enumerate(path[:-1]):
        r, c = divmod(idx, 5)
        board.tiles[r][c] = _letter(r, c, chr(ord("a") + i))
    r, c = divmod(path[-1], 5)
    board.tiles[r][c] = _number(r, c, 10)
    word = "abcdefghi10"
    flags = stamp_search_flags(Loadout())
    v = PathValidator(d, min_len=1)
    assert v.word_ok(board, path, word, flags)


def test_word_ok_rejects_ten_tile_at_wrong_position(tmp_path: Path):
    wl = _wordlist(tmp_path, "abcdefghij")
    d = WordDictionary(wl)
    board = _empty_board()
    path = _path_indices(10)
    for i, idx in enumerate(path[:-2]):
        r, c = divmod(idx, 5)
        board.tiles[r][c] = _letter(r, c, chr(ord("a") + i))
    r, c = divmod(path[-2], 5)
    board.tiles[r][c] = _number(r, c, 10)
    r, c = divmod(path[-1], 5)
    board.tiles[r][c] = _letter(r, c, "j")
    word = "abcdefghj10"
    flags = stamp_search_flags(Loadout())
    v = PathValidator(d, min_len=1)
    assert not v.word_ok(board, path, word, flags)


def test_word_ok_seventeen_tile_path_with_face_seventeen(tmp_path: Path):
    wl = _wordlist(tmp_path, "abcdefghijklmnopq")
    d = WordDictionary(wl)
    board = _empty_board()
    path = _path_indices(17)
    for i, idx in enumerate(path[:-1]):
        r, c = divmod(idx, 5)
        ch = chr(ord("a") + i)
        board.tiles[r][c] = _letter(r, c, ch)
    r, c = divmod(path[-1], 5)
    board.tiles[r][c] = _number(r, c, 17)
    word = "abcdefghijklmnop17"
    flags = stamp_search_flags(Loadout())
    v = PathValidator(d, min_len=1)
    assert v.word_ok(board, path, word, flags)


def test_word_ok_nine_tile_path_single_digit_nine(tmp_path: Path):
    wl = _wordlist(tmp_path, "abcdefghi")
    d = WordDictionary(wl)
    board = _empty_board()
    path = _path_indices(9)
    for i, idx in enumerate(path[:-1]):
        r, c = divmod(idx, 5)
        board.tiles[r][c] = _letter(r, c, chr(ord("a") + i))
    r, c = divmod(path[-1], 5)
    board.tiles[r][c] = _number(r, c, 9)
    word = "abcdefgh9"
    flags = stamp_search_flags(Loadout())
    v = PathValidator(d, min_len=1)
    assert v.word_ok(board, path, word, flags)
    assert not number_position_valid(
        board.get_by_index(path[-1]), 7, flags=flags, segment=word
    )
