"""Bullseye aims word search at encounter remaining target."""

from __future__ import annotations

from pathlib import Path

from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.models import Board, CurseType, Loadout, Tile, TileColor
from cursed_words_solver.rules.quest_scoring import bullseye_heap_rank
from cursed_words_solver.search import WordSearcher
from tests.helpers.boards import _make_wordlist


def _board_cat_vs_book() -> Board:
    tiles = []
    letters = [
        list("bookx"),
        list("catxx"),
        list("xxxxx"),
        list("xxxxx"),
        list("xxxxx"),
    ]
    for r in range(5):
        row = []
        for c in range(5):
            ch = letters[r][c] if letters[r][c] != "x" else "Q"
            row.append(
                Tile(
                    row=r,
                    col=c,
                    char=ch,
                    letter=ch,
                    base_score=1,
                    color=TileColor.COLORLESS,
                    curse=CurseType.LETTER,
                )
            )
        tiles.append(row)
    return Board(tiles=tiles)


def _bullseye_loadout(remaining: int) -> Loadout:
    return Loadout(
        extras={
            "challenge_game_class": "Bullseye",
            "encounter_remaining_target": str(remaining),
        }
    )


def test_bullseye_heap_rank_prefers_exact_hit() -> None:
    assert bullseye_heap_rank(12.0, 12.0) > bullseye_heap_rank(20.0, 12.0)
    assert bullseye_heap_rank(11.0, 12.0) > bullseye_heap_rank(20.0, 12.0)


def test_bullseye_search_prefers_exact_hit(tmp_path: Path) -> None:
    wl = _make_wordlist(tmp_path)
    d = WordDictionary(wl)
    board = _board_cat_vs_book()
    searcher = WordSearcher(
        dictionary=d,
        min_len=3,
        max_len=5,
        time_budget=3.0,
        search_workers=1,
    )
    normal = searcher.find_best_words(board, Loadout(), top_n=3)
    bullseye = searcher.find_best_words(
        board,
        _bullseye_loadout(3),
        top_n=3,
    )
    assert normal
    assert bullseye
    assert normal[0].word == "book"
    assert int(bullseye[0].score) == 3
    assert int(bullseye[0].score) < int(normal[0].score)


def test_bullseye_search_closest_when_exact_impossible(tmp_path: Path) -> None:
    wl = _make_wordlist(tmp_path)
    d = WordDictionary(wl)
    board = _board_cat_vs_book()
    searcher = WordSearcher(
        dictionary=d,
        min_len=3,
        max_len=5,
        time_budget=3.0,
        search_workers=1,
    )
    bullseye = searcher.find_best_words(
        board,
        _bullseye_loadout(5),
        top_n=3,
    )
    assert bullseye
    assert bullseye[0].word == "book"
    assert int(bullseye[0].score) == 4
