"""Cursedle long-word probe suggestions (submissions any length; solution 4-6)."""

from __future__ import annotations

from unittest.mock import patch

from cursed_words_solver.cursedle_solver import (
    CURSEDLE_SOLUTION_MAX_LEN,
    CURSEDLE_SOLUTION_MIN_LEN,
    _enumerate_dictionary_probe_paths,
    _probe_entropy_score,
    filter_candidates,
    run_cursedle_solver,
)
from cursed_words_solver.models import Board, CurseType, Loadout, Tile, TileColor


class _FakeDictionary:
    def __init__(self, words: set[str]) -> None:
        self._words = {w.lower() for w in words}

    def contains(self, word: str) -> bool:
        return word.lower() in self._words

    def has_prefix(self, prefix: str) -> bool:
        stem = prefix.lower()
        return any(word.startswith(stem) for word in self._words)

    def is_valid_word(self, word: str, min_len: int = 3) -> bool:
        key = word.lower()
        return len(key) >= min_len and key in self._words


def _tile(row: int, col: int, letter: str) -> Tile:
    return Tile(
        row=row,
        col=col,
        char=letter.lower(),
        letter=letter,
        base_score=1.0,
        color=TileColor.COLORLESS,
        curse=CurseType.LETTER,
    )


def _board_6x6(letters: list[str]) -> Board:
    tiles = [
        [_tile(r, c, letters[r * 6 + c]) for c in range(6)]
        for r in range(6)
    ]
    return Board(tiles=tiles, rows=6, cols=6)


def _testing_board() -> Board:
    # Path 0→1→2→3→4→5→11 spells TESTING (7 letters; 11 is below 5).
    letters = list("TESTIN" + "AAAAAG" + "AAAAAA" + "AAAAAA" + "AAAAAA" + "AAAAAA")
    return _board_6x6(letters)


def test_solution_filter_stays_four_to_six() -> None:
    board = _board_6x6(["A"] * 36)
    candidates = filter_candidates(board, [])
    assert candidates
    lengths = {len(path) for path in candidates}
    assert min(lengths) >= CURSEDLE_SOLUTION_MIN_LEN
    assert max(lengths) <= CURSEDLE_SOLUTION_MAX_LEN


def test_probe_enumeration_includes_long_word() -> None:
    board = _testing_board()
    dictionary = _FakeDictionary({"testing", "test", "best"})
    found = dict(_enumerate_dictionary_probe_paths(board, dictionary))
    assert "testing" in found
    assert len("testing") > CURSEDLE_SOLUTION_MAX_LEN
    assert found["testing"] == [0, 1, 2, 3, 4, 5, 11]


@patch("cursed_words_solver.cursedle_solver.filter_candidates")
def test_run_cursedle_suggests_long_probe_when_available(mock_filter) -> None:
    mock_filter.return_value = [
        [0, 1, 2, 3],
        [0, 6, 12, 18, 24],
        [5, 11, 17, 23, 29],
    ]
    board = _testing_board()
    dictionary = _FakeDictionary({"testing", "test", "aaaa"})
    loadout = Loadout(
        extras={
            "encounter_mode": "cursedle",
            "cursedle_guesses": "[]",
            "cursedle_guesses_used": "0",
            "cursedle_guesses_remaining": "5",
        }
    )
    advice = run_cursedle_solver(board, loadout, dictionary)
    assert advice.word
    assert len(advice.word) > CURSEDLE_SOLUTION_MAX_LEN
    assert "letters" in advice.reason


def test_longer_probe_can_score_higher_entropy() -> None:
    board = _testing_board()
    dictionary = _FakeDictionary({"testing", "test"})
    candidates = [[0, 1, 2, 3], [0, 6, 12, 18]]
    short_path = [0, 1, 2, 3]
    long_path = [0, 1, 2, 3, 4, 5, 11]
    short_entropy = _probe_entropy_score(board, short_path, candidates)
    long_entropy = _probe_entropy_score(board, long_path, candidates)
    assert long_entropy >= short_entropy
    assert len(long_path) > len(short_path)
