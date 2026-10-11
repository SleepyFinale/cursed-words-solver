"""Tests for accumulator improve stamps (Flashy Fountain Pen, Bar Chart, Book of Openings)."""

from __future__ import annotations

from pathlib import Path

import pytest

from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.models import Board, CurseType, Loadout, LoadoutItem, Tile, TileColor
from cursed_words_solver.search import PathValidator, WordSearcher
from cursed_words_solver.stamp_improve_words import BAR_CHART, BOOK_OF_OPENINGS, FLASHY_FOUNTAIN_PEN


def _make_wordlist(tmp_path: Path, words: list[str]) -> Path:
    p = tmp_path / "words.txt"
    p.write_text("\n".join(words) + "\n", encoding="utf-8")
    return p


def _letter(
    row: int,
    col: int,
    ch: str,
    *,
    score: float = 1.0,
    color: TileColor = TileColor.COLORLESS,
) -> Tile:
    return Tile(
        row=row,
        col=col,
        char=ch,
        letter=ch.upper(),
        base_score=score,
        color=color,
        curse=CurseType.LETTER,
    )


def _board_spelling(word: str) -> Board:
    """Place word on board in row-major order from (0,0)."""
    grid = [[_letter(r, c, "Q") for c in range(5)] for r in range(5)]
    idx = 0
    for r in range(5):
        for c in range(5):
            if idx >= len(word):
                return Board(tiles=grid, money=0)
            grid[r][c] = _letter(r, c, word[idx])
            idx += 1
    return Board(tiles=grid, money=0)


def _path_for_word(word: str) -> list[int]:
    return list(range(len(word)))


@pytest.mark.parametrize(
    ("stamp_id", "word"),
    [
        (FLASHY_FOUNTAIN_PEN, "red"),
        (FLASHY_FOUNTAIN_PEN, "shiny"),
        (BAR_CHART, "seven"),
        (BOOK_OF_OPENINGS, "queen"),
    ],
)
def test_improve_word_valid_with_stamp(tmp_path, stamp_id: str, word: str) -> None:
    wl = _make_wordlist(tmp_path, ["cat", "dog"])
    d = WordDictionary(wl)
    loadout = Loadout(
        stamps=[LoadoutItem(id=stamp_id, name=stamp_id, kind="stamp")],
    )
    validator = PathValidator(d, min_len=3)
    validator.quest_loadout = loadout  # accumulator words come from the equipped stamp
    board = _board_spelling(word)
    path = _path_for_word(word)
    assert validator.word_ok(board, path, word, 0)


@pytest.mark.parametrize(
    ("stamp_id", "word"),
    [
        (FLASHY_FOUNTAIN_PEN, "red"),
        (BAR_CHART, "seven"),
        (BOOK_OF_OPENINGS, "queen"),
    ],
)
def test_improve_word_rejected_without_stamp(tmp_path, stamp_id: str, word: str) -> None:
    wl = _make_wordlist(tmp_path, ["cat", "dog"])
    d = WordDictionary(wl)
    validator = PathValidator(d, min_len=3)
    board = _board_spelling(word)
    path = _path_for_word(word)
    assert not validator.word_ok(board, path, word, 0)


def test_twentyone_accepted_as_bar_chart_improve_word(tmp_path) -> None:
    wl = _make_wordlist(tmp_path, ["cat"])
    d = WordDictionary(wl)
    loadout = Loadout(
        stamps=[LoadoutItem(id=BAR_CHART, name="Bar", kind="stamp")],
    )
    validator = PathValidator(d, min_len=3)
    validator.quest_loadout = loadout
    # Snake along rows 0-1 so every step is adjacent: t w e n t / y o n e (reversed).
    board = _board_spelling("twent" + "Qenoy")
    path = [0, 1, 2, 3, 4, 9, 8, 7, 6]
    assert [board.get_by_index(i).char for i in path] == list("twentyone")
    assert validator.word_ok(board, path, "twentyone", 0)


def test_searcher_seeds_improve_word(tmp_path) -> None:
    wl = _make_wordlist(tmp_path, ["cat"])
    d = WordDictionary(wl)
    board = _board_spelling("red")
    loadout = Loadout(
        stamps=[LoadoutItem(id=FLASHY_FOUNTAIN_PEN, name="Pen", kind="stamp")],
        extras={"grids_remaining": "2"},
    )
    searcher = WordSearcher(
        dictionary=d,
        min_len=3,
        max_len=5,
        time_budget=1.0,
    )
    results = searcher.find_best_words(board, loadout=loadout, top_n=5)
    words = {r.word for r in results}
    assert "red" in words
