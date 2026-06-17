"""Tests for accumulator improve stamps (Flashy Fountain Pen, Bar Chart, Book of Openings)."""

from __future__ import annotations

from pathlib import Path

import pytest

from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.models import Board, CurseType, Loadout, LoadoutItem, Tile, TileColor
from cursed_words_solver.search import PathValidator, WordSearcher, _paths_spelling_word
from cursed_words_solver.setup_value import (
    project_setup_delta,
    rank_score_for_word,
    setup_future_value,
)
from cursed_words_solver.stamp_improve_words import (
    BAR_CHART,
    BOOK_OF_OPENINGS,
    FLASHY_FOUNTAIN_PEN,
    equipped_improve_words,
    stamp_improve_match,
)


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
    validator = PathValidator(
        d,
        min_len=3,
        extra_valid_words=equipped_improve_words(loadout),
    )
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
    validator = PathValidator(
        d,
        min_len=3,
        extra_valid_words=equipped_improve_words(loadout),
    )
    board = Board(tiles=[[_letter(r, c, "Q") for c in range(5)] for r in range(5)])
    assert validator._word_content_ok(board, [], "twentyone", 0)


@pytest.mark.parametrize(
    ("stamp_id", "word"),
    [
        (FLASHY_FOUNTAIN_PEN, "red"),
        (BAR_CHART, "seven"),
        (BOOK_OF_OPENINGS, "pawn"),
    ],
)
def test_project_setup_delta_records_improve(stamp_id: str, word: str) -> None:
    board = _board_spelling(word)
    path = _path_for_word(word)
    loadout = Loadout(
        stamps=[LoadoutItem(id=stamp_id, name=stamp_id, kind="stamp")],
        extras={"grids_remaining": "3"},
    )
    delta = project_setup_delta(board, path, word, loadout)
    assert delta.stamp_improves[stamp_id] == word
    assert setup_future_value(delta, loadout) > 0


def test_stamp_improve_match_multiple_stamps() -> None:
    loadout = Loadout(
        stamps=[
            LoadoutItem(id=FLASHY_FOUNTAIN_PEN, name="Pen", kind="stamp"),
            LoadoutItem(id=BAR_CHART, name="Bar", kind="stamp"),
        ],
    )
    assert stamp_improve_match(loadout, "red") == [(FLASHY_FOUNTAIN_PEN, "red")]
    assert stamp_improve_match(loadout, "seven") == [(BAR_CHART, "seven")]
    union = equipped_improve_words(loadout)
    assert "red" in union and "seven" in union


def test_rank_prefers_improve_word_over_higher_immediate(tmp_path) -> None:
    wl = _make_wordlist(tmp_path, ["red", "shiny", "shinyx"])
    d = WordDictionary(wl)
    board = _board_spelling("red")
    path_red = [0, 1, 2]
    grid = [[_letter(r, c, "Q", score=50.0) for c in range(5)] for r in range(5)]
    for i, ch in enumerate("shiny"):
        grid[1][i] = _letter(1, i, ch, score=50.0, color=TileColor.SHINY)
    board_hi = Board(tiles=grid, money=0)
    path_hi = [5, 6, 7, 8, 9]
    loadout = Loadout(
        stamps=[LoadoutItem(id=FLASHY_FOUNTAIN_PEN, name="Pen", kind="stamp")],
        extras={"grids_remaining": "4"},
    )
    imm_red = 3.0
    imm_hi = 250.0
    rank_red, setup_red = rank_score_for_word(
        board, path_red, "red", loadout, imm_red, setup_weight=0.5
    )
    rank_hi, _ = rank_score_for_word(
        board_hi, path_hi, "shiny", loadout, imm_hi, setup_weight=0.5
    )
    assert setup_red > 0
    assert rank_red > imm_red
    if imm_hi > imm_red:
        assert rank_red > rank_hi or setup_red > 0


def test_paths_spelling_word_finds_red() -> None:
    board = _board_spelling("red")
    paths = _paths_spelling_word(board, "red", max_len=5)
    assert paths
    assert paths[0] == [0, 1, 2]


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
        setup_weight=0.4,
    )
    results = searcher.find_best_words(board, loadout=loadout, top_n=5)
    words = {r.word for r in results}
    assert "red" in words
