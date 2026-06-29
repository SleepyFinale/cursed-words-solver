"""F8 solve cancellation when re-pressed or stale."""

from __future__ import annotations

import time
from pathlib import Path

from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.models import Board, CurseType, Loadout, Tile, TileColor
from cursed_words_solver.search import WordSearcher


def _tiny_board() -> Board:
    board = Board(tiles=[[None] * 5 for _ in range(5)], money=10)
    for r in range(5):
        for c in range(5):
            board.tiles[r][c] = Tile(
                r,
                c,
                "a",
                "A",
                1,
                color=TileColor.BLUE,
                curse=CurseType.LETTER,
            )
    return board


def _wordlist(tmp_path: Path, words: list[str]) -> Path:
    path = tmp_path / "words.txt"
    path.write_text("\n".join(words), encoding="utf-8")
    return path


def test_find_best_words_stops_when_cancel_check_fires(tmp_path):
    wl = _wordlist(tmp_path, ["aaa", "aab", "aba"])
    dictionary = WordDictionary(wl)
    searcher = WordSearcher(
        dictionary=dictionary,
        min_len=3,
        max_len=5,
        time_budget=30.0,
        wordlist_path=wl,
    )
    cancelled = {"flag": False}

    def cancel_check() -> bool:
        return cancelled["flag"]

    board = _tiny_board()
    loadout = Loadout(money=10)
    deadline = time.monotonic() + 30.0
    cancelled["flag"] = True
    results = searcher.find_best_words(
        board,
        loadout=loadout,
        top_n=3,
        deadline=deadline,
        cancel_check=cancel_check,
    )
    assert results == []


def test_time_expired_includes_cancel_check(tmp_path):
    wl = _wordlist(tmp_path, ["aaa"])
    dictionary = WordDictionary(wl)
    searcher = WordSearcher(dictionary=dictionary, min_len=3, max_len=3, time_budget=5.0)
    searcher._cancel_check = lambda: True
    assert searcher._time_expired() is True
