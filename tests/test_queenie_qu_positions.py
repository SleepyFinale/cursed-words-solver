"""Queenie Q→QU: one tile, two word characters; char offset vs tile ordinal."""

from __future__ import annotations

from pathlib import Path

from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.loadout import Loadout
from cursed_words_solver.models import Board, CurseType, LoadoutItem, Tile, TileColor
from cursed_words_solver.rules.stamp_behaviors import stamp_search_flags
from cursed_words_solver.search import PathValidator, WordSearcher, search_word_from_path


def _letter(r: int, c: int, ch: str, *, score: float = 1.0) -> Tile:
    return Tile(
        row=r,
        col=c,
        char=ch,
        letter=ch.upper(),
        base_score=score,
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


def _queenie_loadout() -> Loadout:
    return Loadout(stamps=[LoadoutItem(id="queenie", name="Queenie", level=1, kind="stamp")])


def _queenie_flags() -> int:
    return stamp_search_flags(_queenie_loadout())


def _wordlist(tmp_path: Path, *words: str) -> Path:
    p = tmp_path / "words.txt"
    p.write_text("\n".join(words), encoding="utf-8")
    return p


def test_search_word_from_path_queen():
    board = _empty_board()
    path = [0, 1, 2, 3]
    for i, idx in enumerate(path):
        r, c = divmod(idx, 5)
        board.tiles[r][c] = _letter(r, c, "QEEN"[i])
    flags = _queenie_flags()
    assert search_word_from_path(board, path, flags=flags) == "queen"


def test_word_ok_accepts_queen(tmp_path: Path):
    wl = _wordlist(tmp_path, "queen")
    d = WordDictionary(wl)
    board = _empty_board()
    path = [0, 1, 2, 3]
    for i, idx in enumerate(path):
        r, c = divmod(idx, 5)
        board.tiles[r][c] = _letter(r, c, "QEEN"[i])
    flags = _queenie_flags()
    v = PathValidator(d, min_len=4)
    assert v.word_ok(board, path, "queen", flags)


def test_word_ok_qu_then_number_at_third_tile(tmp_path: Path):
    """Number positions count tiles (Queenie's qu is one tile)."""
    wl = _wordlist(tmp_path, "qan")
    d = WordDictionary(wl)
    board = _empty_board()
    path = [0, 1, 2]
    board.tiles[0][0] = _letter(0, 0, "Q")
    board.tiles[0][1] = _letter(0, 1, "A")
    board.tiles[0][2] = _number(0, 2, 3)
    flags = _queenie_flags()
    # The number is a wildcard at its 1-based tile position (3), so Q-A-3 spells "qan".
    assert PathValidator(d, min_len=3).word_ok(board, path, "qan", flags)
    # IsWordLengthValid counts tiles, not letters: three tiles never meet a 4 minimum.
    assert not PathValidator(d, min_len=4).word_ok(board, path, "qan", flags)


def test_word_searcher_finds_quit_with_queenie(tmp_path: Path):
    wl = _wordlist(tmp_path, "quit", "quip", "quilt")
    d = WordDictionary(wl)
    board = _empty_board()
    board.tiles[0][0] = _letter(0, 0, "Q", score=10.0)
    board.tiles[0][1] = _letter(0, 1, "I")
    board.tiles[0][2] = _letter(0, 2, "T")
    loadout = _queenie_loadout()
    searcher = WordSearcher(dictionary=d, min_len=3, max_len=5, time_budget=3.0)
    results = searcher.find_best_words(board, loadout, top_n=10)
    quit_hit = next((r for r in results if r.word == "quit"), None)
    assert quit_hit is not None
    assert quit_hit.path == [0, 1, 2]
