"""Cursedle 6x6 chess bishop leaps + curated fairy solution narrowing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cursed_words_solver.config import GAME_WORDLIST_PATH
from cursed_words_solver.cursedle_solver import (
    _narrow_candidates_to_dictionary,
    _path_solution_resolution,
    _pick_solution_path,
    filter_candidates,
    load_fairy_solution_dictionary,
    parse_cursedle_guesses,
    run_cursedle_solver,
)
from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.graph_bitboard import build_board_graph_context, iter_mask
from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
from cursed_words_solver.models import Board, CurseType, Tile, TileColor
from cursed_words_solver.search import neighbors_mask

FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "cursedle"
    / "20260716_bishop_leap.json"
)
FAIRY_FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "cursedle"
    / "fairy_curated_words.txt"
)

BINGE_PATH = [0, 28, 22, 29, 34]
AINGA_PATH = [0, 35, 34, 29, 22]


def _empty_6x6_with_bishop() -> Board:
    tiles: list[list[Tile]] = []
    for r in range(6):
        row: list[Tile] = []
        for c in range(6):
            if r == 0 and c == 0:
                row.append(
                    Tile(
                        row=r,
                        col=c,
                        char="?",
                        letter="?",
                        base_score=3.0,
                        color=TileColor.COLORLESS,
                        curse=CurseType.CHESS_BISHOP,
                        metadata={"chess_color": "black"},
                    )
                )
            else:
                row.append(
                    Tile(
                        row=r,
                        col=c,
                        char="a",
                        letter="A",
                        base_score=1.0,
                        color=TileColor.COLORLESS,
                        curse=CurseType.LETTER,
                    )
                )
        tiles.append(row)
    return Board(rows=6, cols=6, tiles=tiles)


@pytest.fixture
def fairy_dictionary(monkeypatch: pytest.MonkeyPatch) -> WordDictionary:
    fairy = WordDictionary(FAIRY_FIXTURE, use_trie_cache=False)

    def _load(*, fallback=None):
        return fairy, None

    monkeypatch.setattr(
        "cursed_words_solver.cursedle_solver.load_fairy_solution_dictionary",
        _load,
    )
    return fairy


def test_6x6_bishop_diagonal_neighbors_not_5x5_misindexed() -> None:
    """Bishop at (0,0) on 6x6 must use 6-wide diagonals, not 5x5 ray indices."""
    board = _empty_6x6_with_bishop()
    ctx = build_board_graph_context(board)
    mask = neighbors_mask(board, 0, cell_id=0, flags=0, graph_ctx=ctx)
    nbrs = set(iter_mask(mask))
    # Correct SE diagonal on 6x6: (1,1),(2,2),(3,3),(4,4),(5,5)
    assert board.index_at(1, 1) in nbrs
    assert board.index_at(4, 4) in nbrs
    assert board.index_at(5, 5) in nbrs
    # 5x5 mis-index would treat diagonals as left-column cells (1,0)..(4,0)
    assert board.index_at(1, 0) not in nbrs
    assert board.index_at(2, 0) not in nbrs


def test_bishop_leap_fixture_matches_feedback_and_dictionary(
    fairy_dictionary: WordDictionary,
) -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    board = parse_board_from_run_state(payload)
    assert board is not None
    loadout = parse_run_state(payload)
    guesses = parse_cursedle_guesses(loadout.extras)
    assert len(guesses) == 3

    feedback = filter_candidates(board, guesses)
    assert len(feedback) > 0

    narrowed = _narrow_candidates_to_dictionary(board, feedback, fairy_dictionary)
    assert len(narrowed) >= 1
    assert BINGE_PATH in narrowed or list(BINGE_PATH) in [list(p) for p in narrowed]

    full = WordDictionary(GAME_WORDLIST_PATH)
    advice = run_cursedle_solver(board, loadout, full)
    assert advice.candidates >= 1
    assert advice.word
    assert "No paths satisfy guess feedback" not in (advice.warnings or [])
    assert "No consistent solution candidates" not in (advice.reason or "")


def test_binge_path_preferred_over_ainga_with_curated_dict(
    fairy_dictionary: WordDictionary,
) -> None:
    """Full-dict alphabetical labeling picks ainga; curated + path order picks binge path."""
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    board = parse_board_from_run_state(payload)
    assert board is not None

    binge_res = _path_solution_resolution(board, BINGE_PATH, fairy_dictionary)
    assert binge_res is not None
    assert binge_res[0] in {"binge", "bingo", "bilge", "hinge"}
    assert binge_res[1] >= 1

    # ainga is absent from curated fixture — that path must not resolve as ainga.
    ainga_res = _path_solution_resolution(board, AINGA_PATH, fairy_dictionary)
    if ainga_res is not None:
        assert ainga_res[0] != "ainga"

    feedback = filter_candidates(board, parse_cursedle_guesses(parse_run_state(payload).extras))
    narrowed = _narrow_candidates_to_dictionary(board, feedback, fairy_dictionary)
    picked = _pick_solution_path(board, narrowed, fairy_dictionary)
    assert picked is not None
    path, word = picked
    assert path == BINGE_PATH
    assert word in {"binge", "bingo", "bilge", "hinge"}


def test_run_cursedle_commits_binge_path_on_last_guess(
    fairy_dictionary: WordDictionary,
) -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    board = parse_board_from_run_state(payload)
    assert board is not None
    loadout = parse_run_state(payload)
    # Force final-guess commit among curated survivors.
    loadout.extras["cursedle_guesses_remaining"] = "1"
    loadout.extras["cursedle_guesses_used"] = "4"

    advice = run_cursedle_solver(board, loadout, WordDictionary(GAME_WORDLIST_PATH))
    assert advice.path == BINGE_PATH
    assert advice.word.lower() in {"binge", "bingo", "bilge", "hinge"}
    assert "Final guess" in advice.reason or advice.candidates >= 1


def test_load_fairy_falls_back_with_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "cursed_words_solver.cursedle_solver.fairy_curated_wordlist_available",
        lambda: False,
    )
    fallback = WordDictionary(FAIRY_FIXTURE, use_trie_cache=False)
    d, warn = load_fairy_solution_dictionary(fallback=fallback)
    assert d is fallback
    assert warn is not None
    assert "fairy_curated_words.txt missing" in warn
