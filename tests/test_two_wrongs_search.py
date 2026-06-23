"""Two Wrongs minimizes raw score during word search."""

from __future__ import annotations

from pathlib import Path

from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.models import Board, CurseType, Loadout, Tile, TileColor
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


def test_two_wrongs_search_prefers_lower_score(tmp_path: Path) -> None:
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
    two_wrongs = searcher.find_best_words(
        board,
        Loadout(extras={"challenge_game_class": "TwoWrongs"}),
        top_n=3,
    )
    assert normal
    assert two_wrongs
    assert normal[0].word == "book"
    assert two_wrongs[0].score <= 3.0
    assert two_wrongs[0].score < normal[0].score
