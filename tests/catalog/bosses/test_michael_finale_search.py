"""Michael finale (25-tile) search and validation regressions."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cursed_words_solver.config import GAME_WORDLIST_PATH
from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
from cursed_words_solver.rules.boss_effects import (
    boss_word_constraints,
    load_rules_catalog,
    michael_finale_active,
)
from cursed_words_solver.rules.stamp_behaviors import stamp_search_flags_mask
from cursed_words_solver.search import (
    PathValidator,
    WordSearcher,
    path_movement_ok,
    search_word_from_path,
)
from cursed_words_solver.suggestion import dictionary_word_for_path
from cursed_words_solver.ui.board_geometry import path_from_melmod_indices

RULES = load_rules_catalog()
FIXTURE = (
    Path(__file__).resolve().parents[2] / "fixtures" / "michael_finale_beans_grid3.json"
)
KNOWN_PATH = [
    10,
    5,
    0,
    15,
    20,
    21,
    22,
    23,
    24,
    19,
    18,
    14,
    9,
    4,
    3,
    2,
    1,
    7,
    11,
    6,
    12,
    16,
    17,
    13,
    8,
]
KNOWN_WORD = "hypobetalipoproteinaemias"


def _load_fixture() -> tuple:
    if not FIXTURE.is_file():
        pytest.skip(f"fixture not found: {FIXTURE}")
    run_state = json.loads(FIXTURE.read_text(encoding="utf-8"))
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    assert board is not None
    return board, loadout


@pytest.fixture(name="finale_board_loadout")
def fixture_finale_board_loadout():
    return _load_fixture()


def test_boss_constraints_25_25(finale_board_loadout) -> None:
    board, loadout = finale_board_loadout
    assert michael_finale_active(loadout, default_max_len=25)
    c = boss_word_constraints(loadout, RULES, default_max_len=sum(board.active))
    assert c.min_len == 25
    assert c.max_len == 25


def test_known_path_movement_ok(finale_board_loadout) -> None:
    board, loadout = finale_board_loadout
    flags = stamp_search_flags_mask(loadout)
    assert path_movement_ok(board, KNOWN_PATH, flags=flags)


def test_known_path_validates(finale_board_loadout) -> None:
    if not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024:
        pytest.skip("game wordlist required")
    board, loadout = finale_board_loadout
    flags = stamp_search_flags_mask(loadout)
    d = WordDictionary(GAME_WORDLIST_PATH)
    validator = PathValidator(d, min_len=25)
    search_word = search_word_from_path(board, KNOWN_PATH, flags=flags)
    assert len(search_word) >= 25
    assert validator.word_ok(board, KNOWN_PATH, KNOWN_WORD, flags)
    dict_word = dictionary_word_for_path(
        board,
        KNOWN_PATH,
        search_word,
        loadout,
        d,
        min_len=25,
    )
    assert dict_word
    assert len(dict_word) == 25
    assert validator.word_ok(board, KNOWN_PATH, dict_word, flags)


def test_search_finds_25_letter_word(finale_board_loadout) -> None:
    if not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024:
        pytest.skip("game wordlist required")
    board, loadout = finale_board_loadout
    constraints = boss_word_constraints(loadout, RULES, default_max_len=sum(board.active))
    d = WordDictionary(GAME_WORDLIST_PATH)
    searcher = WordSearcher(
        dictionary=d,
        min_len=constraints.min_len,
        max_len=constraints.max_len,
        time_budget=45.0,
        search_workers=4,
        wordlist_path=GAME_WORDLIST_PATH,
    )
    results = searcher.find_best_words(board, loadout=loadout, top_n=3)
    assert results
    assert all(len(r.word) >= 25 for r in results)


@pytest.mark.slow
def test_finale_completion_after_short_budget(finale_board_loadout) -> None:
    if not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024:
        pytest.skip("game wordlist required")
    board, loadout = finale_board_loadout
    constraints = boss_word_constraints(loadout, RULES, default_max_len=sum(board.active))
    d = WordDictionary(GAME_WORDLIST_PATH)
    searcher = WordSearcher(
        dictionary=d,
        min_len=constraints.min_len,
        max_len=constraints.max_len,
        time_budget=0.1,
        search_workers=4,
        wordlist_path=GAME_WORDLIST_PATH,
    )
    results = searcher.find_best_words(
        board,
        loadout=loadout,
        top_n=1,
        run_until_found=True,
    )
    assert results
    assert len(results[0].word) >= 25


def test_michael_fingerprint_matches_melmod_export(finale_board_loadout) -> None:
    _, loadout = finale_board_loadout
    from cursed_words_solver.fingerprints import loadout_fingerprint

    exported = str((loadout.extras or {}).get("loadout_fingerprint") or "")
    assert exported == "Beans|0|||-|:"
    assert loadout_fingerprint(loadout) == exported


CARD_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "michael_finale_20260708_card_grid.json"
)
CARD_KNOWN_PATH_MELMOD = [
    9,
    4,
    3,
    15,
    10,
    20,
    21,
    22,
    23,
    24,
    19,
    14,
    8,
    2,
    1,
    0,
    5,
    6,
    16,
    17,
    11,
    7,
    13,
    18,
    12,
]
CARD_KNOWN_WORD = "alkenylidenecyclopropanes"


def _load_card_fixture() -> tuple:
    if not CARD_FIXTURE.is_file():
        pytest.skip(f"fixture not found: {CARD_FIXTURE}")
    run_state = json.loads(CARD_FIXTURE.read_text(encoding="utf-8"))
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    assert board is not None
    return board, loadout


@pytest.fixture(name="card_finale_board_loadout")
def fixture_card_finale_board_loadout():
    return _load_card_fixture()


def test_20260708_card_grid_known_path_validates(card_finale_board_loadout) -> None:
    if not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024:
        pytest.skip("game wordlist required")
    board, loadout = card_finale_board_loadout
    flags = stamp_search_flags_mask(loadout)
    path = path_from_melmod_indices(board, CARD_KNOWN_PATH_MELMOD)
    d = WordDictionary(GAME_WORDLIST_PATH)
    validator = PathValidator(d, min_len=25)
    assert path_movement_ok(board, path, flags=flags)
    assert validator.word_ok(board, path, CARD_KNOWN_WORD, flags)


def test_20260708_card_grid_search_within_budget(card_finale_board_loadout) -> None:
    if not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024:
        pytest.skip("game wordlist required")
    board, loadout = card_finale_board_loadout
    expected_path = path_from_melmod_indices(board, CARD_KNOWN_PATH_MELMOD)
    constraints = boss_word_constraints(loadout, RULES, default_max_len=sum(board.active))
    d = WordDictionary(GAME_WORDLIST_PATH)
    searcher = WordSearcher(
        dictionary=d,
        min_len=constraints.min_len,
        max_len=constraints.max_len,
        time_budget=15.0,
        search_workers=4,
        wordlist_path=GAME_WORDLIST_PATH,
    )
    results = searcher.find_best_words(board, loadout=loadout, top_n=1)
    assert results
    assert len(results[0].word) >= 25
    assert (
        results[0].path == expected_path
        or results[0].word.lower() == CARD_KNOWN_WORD
    )
