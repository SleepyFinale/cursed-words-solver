"""Queenie Q→QU: one tile, two word characters; char offset vs tile ordinal."""

from __future__ import annotations

from pathlib import Path

from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.loadout import Loadout
from cursed_words_solver.models import Board, CurseType, LoadoutItem, Tile, TileColor
from cursed_words_solver.rules.stamp_behaviors import stamp_search_flags
from cursed_words_solver.search import (
    PathValidator,
    WordSearcher,
    path_letter_tiles_match_word,
    path_word_char_len,
    resolve_letter,
    search_word_from_path,
)


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


def test_resolve_letter_qu_at_char_offset_after_prior_qu():
    """Q→QU is position-independent; char_pos 2 still yields qu."""
    tile = _letter(0, 0, "Q")
    flags = _queenie_flags()
    assert resolve_letter(tile, 0, flags=flags) == "qu"
    assert resolve_letter(tile, 2, flags=flags) == "qu"


def test_search_word_from_path_queen():
    board = _empty_board()
    path = [0, 1, 2, 3]
    for i, idx in enumerate(path):
        r, c = divmod(idx, 5)
        board.tiles[r][c] = _letter(r, c, "QEEN"[i])
    flags = _queenie_flags()
    assert search_word_from_path(board, path, flags=flags) == "queen"


def test_path_word_char_len_after_q_is_two_not_one():
    board = _empty_board()
    board.tiles[0][0] = _letter(0, 0, "Q")
    flags = _queenie_flags()
    assert path_word_char_len(board, [0], flags=flags) == 2
    assert path_word_char_len(board, [0], flags=flags) != len([0])


def test_path_word_char_len_matches_search_word_from_path():
    board = _empty_board()
    path = [0, 1, 2]
    board.tiles[0][0] = _letter(0, 0, "Q")
    board.tiles[0][1] = _letter(0, 1, "I")
    board.tiles[0][2] = _letter(0, 2, "T")
    flags = _queenie_flags()
    word = search_word_from_path(board, path, flags=flags)
    assert path_word_char_len(board, path, flags=flags) == len(word)
    assert word == "quit"


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


def test_path_letter_tiles_rejects_misaligned_qeen():
    board = _empty_board()
    path = [0, 1, 2, 3]
    for i, idx in enumerate(path):
        r, c = divmod(idx, 5)
        board.tiles[r][c] = _letter(r, c, "QEEN"[i])
    flags = _queenie_flags()
    assert not path_letter_tiles_match_word(board, path, "qeen", flags=flags)


def test_word_ok_qu_then_number_at_third_tile(tmp_path: Path):
    """Letters after Q align at char_pos; number lock uses tile ordinal."""
    wl = _wordlist(tmp_path, "qan")
    d = WordDictionary(wl)
    board = _empty_board()
    path = [0, 1, 2]
    board.tiles[0][0] = _letter(0, 0, "Q")
    board.tiles[0][1] = _letter(0, 1, "A")
    board.tiles[0][2] = _number(0, 2, 3)
    flags = _queenie_flags()
    v = PathValidator(d, min_len=4)
    assert v.word_ok(board, path, "qua3", flags)
    assert not v.word_ok(board, path, "qu3a", flags)


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
