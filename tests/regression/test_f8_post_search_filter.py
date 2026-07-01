"""Regression: F8 post-search must not drop search-validated wildcard hits."""

from __future__ import annotations

import time

import pytest

from cursed_words_solver.config import GAME_WORDLIST_PATH
from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.models import Board, CurseType, Loadout, Tile
from cursed_words_solver.search import WordSearcher, is_fraction_tile
from cursed_words_solver.suggestion import filter_submittable_results, path_is_submittable


def _tile(
    row: int,
    col: int,
    letter: str,
    base: float,
    *,
    curse: CurseType = CurseType.LETTER,
    char: str | None = None,
    fraction_value: float | None = None,
    metadata: dict | None = None,
) -> Tile:
    meta = dict(metadata or {})
    if curse == CurseType.FRACTION and not meta:
        meta = {"fraction_num": 3, "fraction_den": 5}
    return Tile(
        row=row,
        col=col,
        char=char or letter,
        letter=letter,
        base_score=base,
        curse=curse,
        fraction_value=fraction_value,
        metadata=meta,
    )


def _fraction_ace_board() -> Board:
    """A-C-3/5 row: fraction wildcard at word position 3 (denominator slot)."""
    board = Board(
        tiles=[[_tile(0, c, "x", 1) for c in range(5)] for _ in range(5)],
        money=0,
    )
    board.tiles[0][0] = _tile(0, 0, "A", 1)
    board.tiles[0][1] = _tile(0, 1, "C", 3)
    board.tiles[0][2] = _tile(
        0,
        2,
        "?",
        8,
        curse=CurseType.FRACTION,
        char="3/5",
        fraction_value=0.6,
    )
    return board


@pytest.mark.skipif(
    not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024,
    reason="game wordlist required",
)
def test_filter_without_deadline_keeps_search_validated_wildcard_hits():
    """App must not pass deadline_check here — it falsely drops fraction paths."""
    board = _fraction_ace_board()
    loadout = Loadout(money=0)
    dictionary = WordDictionary(GAME_WORDLIST_PATH)
    searcher = WordSearcher(
        dictionary=dictionary,
        min_len=3,
        max_len=5,
        time_budget=5.0,
    )
    results = searcher.find_best_words(board, loadout=loadout, top_n=5)
    assert results, "search must return fraction-board candidates"

    submittable = [
        r
        for r in results
        if path_is_submittable(
            board,
            r.path,
            r.word,
            loadout,
            dictionary,
            min_len=3,
        )
    ]
    assert submittable, "finalize should only return submittable paths"

    kept = filter_submittable_results(
        board,
        results,
        loadout,
        dictionary,
        min_len=3,
    )
    assert kept, "filter without deadline must keep search-validated hits"

    wildcard_hits = [r for r in results if "?" in r.word.lower()]
    for hit in wildcard_hits:
        assert path_is_submittable(
            board,
            hit.path,
            hit.word,
            loadout,
            dictionary,
            min_len=3,
        )
        expired = filter_submittable_results(
            board,
            [hit],
            loadout,
            dictionary,
            min_len=3,
            deadline_check=lambda: True,
        )
        assert not expired, "deadline-gated re-filter drops unresolved wildcard paths"


@pytest.mark.skipif(
    not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024,
    reason="game wordlist required",
)
def test_expired_deadline_aborts_wildcard_dictionary_resolve():
    """Documents why app.py must not pass deadline_check after search returns."""
    board = _fraction_ace_board()
    loadout = Loadout(money=0)
    dictionary = WordDictionary(GAME_WORDLIST_PATH)
    path = [0, 1, 2]
    assert path_is_submittable(
        board, path, "ac?", loadout, dictionary, min_len=3
    )
    assert not path_is_submittable(
        board,
        path,
        "ac?",
        loadout,
        dictionary,
        min_len=3,
        deadline_check=lambda: True,
    )


def _fraction_only_board() -> Board:
    """Fraction tiles without number tiles (session-1 style)."""
    board = Board(
        tiles=[[_tile(r, c, "a", 1) for c in range(5)] for r in range(5)],
        money=0,
    )
    board.tiles[4][1] = _tile(
        4,
        1,
        "?",
        8,
        curse=CurseType.FRACTION,
        char="¼",
        fraction_value=0.25,
        metadata={"fraction_num": 1, "fraction_den": 4},
    )
    board.tiles[4][2] = _tile(
        4,
        2,
        "?",
        8,
        curse=CurseType.FRACTION,
        char="⅓",
        fraction_value=1 / 3,
        metadata={"fraction_num": 1, "fraction_den": 3},
    )
    return board


@pytest.mark.skipif(
    not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024,
    reason="game wordlist required",
)
def test_fraction_only_board_reserves_post_dfs_time():
    """Fraction-only boards must not give DFS the entire F8 budget."""
    board = _fraction_only_board()
    assert any(is_fraction_tile(t) for t in board.flat)
    assert not any(t.curse == CurseType.NUMBER for t in board.flat)

    budget = 60.0
    searcher = WordSearcher(
        dictionary=WordDictionary(GAME_WORDLIST_PATH),
        min_len=3,
        max_len=25,
        time_budget=budget,
        search_workers=1,
    )
    deadline = time.monotonic() + budget
    searcher.find_best_words(board, Loadout(money=0), top_n=1, deadline=deadline)
    timing = searcher.last_search_timing
    assert timing is not None
    assert timing.main_dfs_slice_sec < budget * 0.92, (
        "fraction-only boards should reserve post-DFS time"
    )
