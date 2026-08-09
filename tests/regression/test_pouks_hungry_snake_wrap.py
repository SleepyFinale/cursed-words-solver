"""Regression: Hungry Snake playable-width wrap + number-path validity.

Round log 20260809_002546_757: 3×2 bat grid with Hungry Snake. F8 suggested
``aah`` (1634) via 4→5→🃏; submitted path 2→1→4→3→🃏 used horizontal wrap
(playable cols 0↔2, not storage 0↔4) and scored ~30600.

Important: the game matches a *dictionary letter word* on number tiles
(``GetStringRepresentation(forWordValidity=true)`` → ``!`` wildcards when
Number Go Up ascending / position-locked). Historic display ``12345`` /
digit-face concatenations are NOT valid submissions — F8 must never suggest
them (see invalid ``1656253`` miss).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cursed_words_solver.config import GAME_WORDLIST_PATH
from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
from cursed_words_solver.rules.stamp_behaviors import stamp_search_flags
from cursed_words_solver.search import PathValidator, path_movement_ok
from cursed_words_solver.suggestion import path_is_submittable
from cursed_words_solver.ui.board_geometry import path_from_melmod_indices
from tests.regression.test_path_mismatch_round_log import _f8_run_state_from_round_log

POUKS_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "round_logs"
    / "20260809_pouks_path_mismatch.json"
)
POUKS_MELMOD_PATH = [5, 2, 3, 0, 1]
POUKS_DIGIT_WORD = "21435"


@pytest.mark.skipif(
    not POUKS_FIXTURE.exists() or not GAME_WORDLIST_PATH.exists(),
    reason="20260809 pouks path-mismatch fixture and game wordlist required",
)
def test_pouks_hungry_snake_wrap_movement():
    """Playable 3-wide grid wraps col 0 ↔ col 2 (not storage col 4)."""
    data = json.loads(POUKS_FIXTURE.read_text(encoding="utf-8"))
    run_state = _f8_run_state_from_round_log(data)
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    assert board is not None and loadout is not None
    assert board.playable_min_col == 0 and board.playable_max_col == 2

    path = path_from_melmod_indices(board, POUKS_MELMOD_PATH)
    flags = stamp_search_flags(loadout)
    assert flags.horizontal_wrap
    assert path_movement_ok(board, path, flags=flags, loadout=loadout)


@pytest.mark.skipif(
    not POUKS_FIXTURE.exists() or not GAME_WORDLIST_PATH.exists(),
    reason="20260809 pouks path-mismatch fixture and game wordlist required",
)
def test_pouks_digit_face_string_not_submittable():
    """Digit concatenations are display/historic faces — not Vocabulary words."""
    data = json.loads(POUKS_FIXTURE.read_text(encoding="utf-8"))
    run_state = _f8_run_state_from_round_log(data)
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    assert board is not None and loadout is not None

    path = path_from_melmod_indices(board, POUKS_MELMOD_PATH)
    flags = stamp_search_flags(loadout)
    dictionary = WordDictionary(GAME_WORDLIST_PATH)
    validator = PathValidator(dictionary, min_len=3)
    assert not validator.word_ok(board, path, POUKS_DIGIT_WORD, flags)
    assert not path_is_submittable(
        board, path, POUKS_DIGIT_WORD, loadout, dictionary, min_len=3
    )


@pytest.mark.skipif(
    not POUKS_FIXTURE.exists() or not GAME_WORDLIST_PATH.exists(),
    reason="20260809 pouks path-mismatch fixture and game wordlist required",
)
def test_digit_only_suggestion_like_1656253_rejected():
    """Pure digit F8 suggestions must fail word_ok (not a Vocabulary word)."""
    dictionary = WordDictionary(GAME_WORDLIST_PATH)
    validator = PathValidator(dictionary, min_len=3)
    from cursed_words_solver.models import Board, CurseType, Tile, TileColor

    def num(r: int, c: int, face: int) -> Tile:
        return Tile(
            row=r,
            col=c,
            char=str(face),
            letter=str(face),
            base_score=float(face),
            curse=CurseType.NUMBER,
            color=TileColor.RED,
            number_value=face,
        )

    faces = [1, 6, 5, 6, 2, 5, 3]
    tiles = [
        [Tile(row=r, col=c, char="", letter="", base_score=0) for c in range(5)]
        for r in range(5)
    ]
    path: list[int] = []
    for i, face in enumerate(faces):
        r, c = divmod(i, 5)
        tiles[r][c] = num(r, c, face)
        path.append(r * 5 + c)
    board = Board(tiles=tiles, money=0)
    word = "".join(str(f) for f in faces)
    assert word == "1656253"
    assert not validator.word_ok(board, path, word, 0)
    assert not dictionary.contains(word)
