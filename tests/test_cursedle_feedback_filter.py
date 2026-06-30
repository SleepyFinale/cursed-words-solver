"""Cursedle feedback constraint filtering."""

from __future__ import annotations

from cursed_words_solver.cursedle_solver import (
    CursedleGuess,
    filter_candidates,
    solution_matches_guess,
)
from cursed_words_solver.loadout import parse_board_from_run_state
from cursed_words_solver.models import Board, CurseType, Tile, TileColor
from cursed_words_solver.ui.board_geometry import path_to_melmod_indices


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
    assert len(letters) == 36
    tiles = [
        [_tile(r, c, letters[r * 6 + c]) for c in range(6)]
        for r in range(6)
    ]
    return Board(tiles=tiles, rows=6, cols=6)


def test_green_feedback_pins_solution_index() -> None:
    board = _board_6x6(["A"] * 36)
    solution = [0, 1, 2, 3]
    melmod = path_to_melmod_indices(board, solution)
    guess = CursedleGuess(path=melmod, feedback=["green"] * 4)
    assert solution_matches_guess(board, solution, guess)

    wrong_order = CursedleGuess(
        path=[melmod[1], melmod[0], melmod[2], melmod[3]],
        feedback=["yellow", "yellow", "green", "green"],
    )
    assert solution_matches_guess(board, solution, wrong_order)
    assert not solution_matches_guess(board, [1, 0, 2, 3], guess)


def test_grey_and_red_adjacency() -> None:
    board = _board_6x6(["A"] * 36)
    solution = [0, 1, 2, 3]
    # index 7 is adjacent to 1 (row0col1); index 35 is far corner
    guess = CursedleGuess(
        path=path_to_melmod_indices(board, [7, 35]),
        feedback=["red", "grey"],
    )
    assert solution_matches_guess(board, solution, guess)
    assert not solution_matches_guess(
        board,
        solution,
        CursedleGuess(
            path=path_to_melmod_indices(board, [7, 35]),
            feedback=["grey", "grey"],
        ),
    )


def test_filter_narrows_to_solution_length() -> None:
    board = _board_6x6(["A"] * 36)
    solution = [0, 6, 12, 18]
    guesses = [
        CursedleGuess(
            path=path_to_melmod_indices(board, solution),
            feedback=["green", "green", "green", "green"],
        )
    ]
    candidates = filter_candidates(board, guesses, min_len=4, max_len=6)
    assert solution in candidates
    assert all(path[0] == 0 and path[1] == 6 for path in candidates if len(path) >= 2)


def test_parse_cursedle_board_export() -> None:
    payload = {
        "board": {
            "rows": 6,
            "cols": 6,
            "tiles": [
                {
                    "row": r,
                    "col": c,
                    "char": "a",
                    "letter": "A",
                    "active": True,
                    "curse": "letter",
                    "color": "colorless",
                }
                for r in range(6)
                for c in range(6)
            ],
        },
        "extras": {
            "encounter_mode": "cursedle",
            "cursedle_guesses_used": "0",
            "cursedle_guesses_remaining": "5",
            "cursedle_guesses": "[]",
        },
    }
    board = parse_board_from_run_state(payload)
    assert board is not None
    assert board.cell_count == 36
