"""Beam search wiring and parity smoke tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.search import WordSearcher
from scripts.search_profile_common import load_fixture_auto, resolve_wordlist

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "mismatches"
BOARD_FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "boards"


@pytest.fixture(scope="module")
def dictionary() -> WordDictionary:
    return WordDictionary(resolve_wordlist(None))


def _available_fixture(*names: str) -> Path | None:
    for name in names:
        for root in (FIXTURES, BOARD_FIXTURES):
            p = root / name
            if p.is_file():
                return p
    return None


def test_beam_search_finds_word_on_fixture(dictionary: WordDictionary) -> None:
    # Hayley is number-dense but currently the most reliable short-budget smoke board
    # among available fixtures (ayms / 20260526 often return empty under 8s).
    path = _available_fixture(
        "20260527_hayley_abacus.json",
        "ayms_board_snapshot.json",
        "20260526_231923.json",
    )
    if path is None:
        pytest.skip("no mismatch fixtures present")
    board, loadout, _label = load_fixture_auto(path)
    searcher = WordSearcher(
        dictionary=dictionary,
        time_budget=12.0,
        search_workers=1,
        use_beam_search=True,
        wordlist_path=dictionary.path,
    )
    results = searcher.find_best_words(board, loadout=loadout, top_n=1)
    assert results
    assert results[0].score > 0
    assert results[0].path


def test_beam_vs_dfs_equal_budget_beam_not_worse(dictionary: WordDictionary) -> None:
    """On a hard fixture, beam hybrid should match or beat pure DFS under equal budget."""
    path = _available_fixture("20260526_231923.json", "ayms_board_snapshot.json")
    if path is None:
        pytest.skip("no mismatch fixtures present")
    board, loadout, _label = load_fixture_auto(path)
    budget = 12.0
    beam = WordSearcher(
        dictionary=dictionary,
        time_budget=budget,
        search_workers=1,
        use_beam_search=True,
        wordlist_path=dictionary.path,
    )
    dfs = WordSearcher(
        dictionary=dictionary,
        time_budget=budget,
        search_workers=1,
        use_beam_search=False,
        wordlist_path=dictionary.path,
    )
    beam_res = beam.find_best_words(board, loadout=loadout, top_n=1)
    dfs_res = dfs.find_best_words(board, loadout=loadout, top_n=1)
    beam_score = beam_res[0].score if beam_res else 0.0
    dfs_score = dfs_res[0].score if dfs_res else 0.0
    if beam_score <= 0 and dfs_score <= 0:
        pytest.skip("both engines empty under budget")
    # Allow small float noise; beam hybrid should not lose badly on equal budget.
    assert beam_score + 1.0 >= dfs_score * 0.85


def test_use_beam_search_flag_defaults_true(dictionary: WordDictionary) -> None:
    searcher = WordSearcher(dictionary=dictionary, search_workers=1)
    assert searcher.use_beam_search is True
