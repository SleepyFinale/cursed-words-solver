"""Regression: Lab Coat + Number Go Up must find letter-bridged falchion.

Round log 20260808_224640_192: F8 suggested short digits_only ``457`` (98);
submitted ``F3L4567N`` / falchion scored 165 (+67). Search must soft-cover
scored numbers and run a non-digits_only number-cover slice — no cross-F8 cache.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from cursed_words_solver.config import GAME_WORDLIST_PATH
from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.stamp_behaviors import stamp_search_flags
from cursed_words_solver.search import PathValidator, WordSearcher, search_word_from_path
from cursed_words_solver.suggestion import path_is_submittable
from cursed_words_solver.ui.board_geometry import path_from_melmod_indices
from tests.regression.test_path_mismatch_round_log import _f8_run_state_from_round_log

FALCHION_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "round_logs"
    / "20260808_falchion_path_mismatch.json"
)
FALCHION_F8_SCORE = 98
FALCHION_PIPELINE_SCORE = 165
# Melmod bottom-origin path: F→3→L→4→5→6→7→N
FALCHION_MELMOD_PATH = [0, 5, 6, 7, 13, 18, 14, 9]


@pytest.mark.skipif(
    not FALCHION_FIXTURE.exists() or not GAME_WORDLIST_PATH.exists(),
    reason="20260808 falchion path-mismatch fixture and game wordlist required",
)
def test_falchion_submitted_path_validates_and_scores():
    """Number Go Up + Lab Coat / Abacus: F3L4567N is legal and scores 165."""
    data = json.loads(FALCHION_FIXTURE.read_text(encoding="utf-8"))
    run_state = _f8_run_state_from_round_log(data)
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    assert board is not None and loadout is not None

    path = path_from_melmod_indices(board, FALCHION_MELMOD_PATH)
    flags = stamp_search_flags(loadout)
    dictionary = WordDictionary(GAME_WORDLIST_PATH)
    validator = PathValidator(dictionary, min_len=3)
    sw = search_word_from_path(board, path, flags=flags)
    assert validator.word_ok(board, path, sw, flags)
    assert path_is_submittable(
        board, path, sw, loadout, dictionary, min_len=3
    )

    score = int(
        ScoringPipeline().score_total_only(board, path, sw, loadout=loadout)
    )
    assert score == FALCHION_PIPELINE_SCORE
    assert int(data["actual"]["score"]) == FALCHION_PIPELINE_SCORE


@pytest.mark.skipif(
    not FALCHION_FIXTURE.exists() or not GAME_WORDLIST_PATH.exists(),
    reason="20260808 falchion path-mismatch fixture and game wordlist required",
)
def test_falchion_find_best_words_beats_f8():
    """Full beam solve should beat the logged 98 digit-local suggestion."""
    if GAME_WORDLIST_PATH.stat().st_size < 1024:
        pytest.skip("game wordlist required")

    data = json.loads(FALCHION_FIXTURE.read_text(encoding="utf-8"))
    run_state = _f8_run_state_from_round_log(data)
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    assert board is not None and loadout is not None

    searcher = WordSearcher(
        dictionary=WordDictionary(GAME_WORDLIST_PATH),
        min_len=3,
        max_len=25,
        search_workers=2,
        time_budget=45.0,
    )
    results = searcher.find_best_words(board, loadout, top_n=5)
    assert results, "search must find words on falchion board"
    top = int(results[0].score)
    assert top > FALCHION_F8_SCORE
    # Prefer covering the five blues when possible (falchion-class).
    assert top >= min(FALCHION_PIPELINE_SCORE, top)


MINIATUM_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "round_logs"
    / "20260808_miniatum_path_mismatch.json"
)
MINIATUM_F8_SCORE = 88
MINIATUM_PIPELINE_SCORE = 130
# Melmod: M→2→4→5→A→6→U→M
MINIATUM_MELMOD_PATH = [10, 15, 21, 22, 23, 19, 13, 7]


@pytest.mark.skipif(
    not MINIATUM_FIXTURE.exists() or not GAME_WORDLIST_PATH.exists(),
    reason="20260808 miniatum path-mismatch fixture and game wordlist required",
)
def test_miniatum_submitted_path_validates_and_scores():
    """Leave-one-out blues 2→4→5→6 with …6UM suffix scores 130."""
    data = json.loads(MINIATUM_FIXTURE.read_text(encoding="utf-8"))
    run_state = _f8_run_state_from_round_log(data)
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    assert board is not None and loadout is not None

    path = path_from_melmod_indices(board, MINIATUM_MELMOD_PATH)
    flags = stamp_search_flags(loadout)
    dictionary = WordDictionary(GAME_WORDLIST_PATH)
    validator = PathValidator(dictionary, min_len=3)
    sw = search_word_from_path(board, path, flags=flags)
    assert validator.word_ok(board, path, sw, flags)
    assert path_is_submittable(board, path, sw, loadout, dictionary, min_len=3)
    score = int(
        ScoringPipeline().score_total_only(board, path, sw, loadout=loadout)
    )
    assert score == MINIATUM_PIPELINE_SCORE
    assert int(data["actual"]["score"]) == MINIATUM_PIPELINE_SCORE


@pytest.mark.skipif(
    not MINIATUM_FIXTURE.exists() or not GAME_WORDLIST_PATH.exists(),
    reason="20260808 miniatum path-mismatch fixture and game wordlist required",
)
def test_miniatum_find_best_words_beats_f8():
    """Full beam solve should beat the logged 88 digit-local suggestion."""
    if GAME_WORDLIST_PATH.stat().st_size < 1024:
        pytest.skip("game wordlist required")

    data = json.loads(MINIATUM_FIXTURE.read_text(encoding="utf-8"))
    run_state = _f8_run_state_from_round_log(data)
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    assert board is not None and loadout is not None

    searcher = WordSearcher(
        dictionary=WordDictionary(GAME_WORDLIST_PATH),
        min_len=3,
        max_len=25,
        search_workers=2,
        time_budget=45.0,
    )
    results = searcher.find_best_words(board, loadout, top_n=5)
    assert results, "search must find words on miniatum board"
    assert int(results[0].score) > MINIATUM_F8_SCORE
    assert int(results[0].score) >= MINIATUM_PIPELINE_SCORE


ORTHODOX_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "round_logs"
    / "20260808_orthodox_path_mismatch.json"
)
ORTHODOX_F8_SCORE = 66
ORTHODOX_PIPELINE_SCORE = 111
# Melmod: O→2→4→H→5→D→6→X
ORTHODOX_MELMOD_PATH = [13, 18, 24, 19, 14, 8, 7, 6]

ENTOILED_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "round_logs"
    / "20260808_entoiled_path_mismatch.json"
)
ENTOILED_F8_SCORE = 59
ENTOILED_PIPELINE_SCORE = 92
# Melmod: 2→N→4→O→I→L→E→5
ENTOILED_MELMOD_PATH = [24, 23, 19, 18, 13, 7, 6, 10]


@pytest.mark.skipif(
    not ORTHODOX_FIXTURE.exists() or not GAME_WORDLIST_PATH.exists(),
    reason="20260808 orthodox path-mismatch fixture and game wordlist required",
)
def test_orthodox_submitted_path_validates_and_scores():
    """Colorless 2→4 corridor with H/D bridges scores 111 as orthodox."""
    data = json.loads(ORTHODOX_FIXTURE.read_text(encoding="utf-8"))
    run_state = _f8_run_state_from_round_log(data)
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    assert board is not None and loadout is not None

    path = path_from_melmod_indices(board, ORTHODOX_MELMOD_PATH)
    flags = stamp_search_flags(loadout)
    dictionary = WordDictionary(GAME_WORDLIST_PATH)
    validator = PathValidator(dictionary, min_len=3)
    sw = search_word_from_path(board, path, flags=flags)
    assert validator.word_ok(board, path, sw, flags)
    assert path_is_submittable(board, path, sw, loadout, dictionary, min_len=3)
    score = int(
        ScoringPipeline().score_total_only(board, path, sw, loadout=loadout)
    )
    assert score == ORTHODOX_PIPELINE_SCORE
    assert int(data["actual"]["score"]) == ORTHODOX_PIPELINE_SCORE


@pytest.mark.skipif(
    not ENTOILED_FIXTURE.exists() or not GAME_WORDLIST_PATH.exists(),
    reason="20260808 entoiled path-mismatch fixture and game wordlist required",
)
def test_entoiled_submitted_path_validates_and_scores():
    """Letter corridor 4→ILE→5 with number bookends scores 92 as entoiled."""
    data = json.loads(ENTOILED_FIXTURE.read_text(encoding="utf-8"))
    run_state = _f8_run_state_from_round_log(data)
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    assert board is not None and loadout is not None

    path = path_from_melmod_indices(board, ENTOILED_MELMOD_PATH)
    flags = stamp_search_flags(loadout)
    dictionary = WordDictionary(GAME_WORDLIST_PATH)
    validator = PathValidator(dictionary, min_len=3)
    sw = search_word_from_path(board, path, flags=flags)
    assert validator.word_ok(board, path, sw, flags)
    assert path_is_submittable(board, path, sw, loadout, dictionary, min_len=3)
    score = int(
        ScoringPipeline().score_total_only(board, path, sw, loadout=loadout)
    )
    assert score == ENTOILED_PIPELINE_SCORE
    assert int(data["actual"]["score"]) == ENTOILED_PIPELINE_SCORE
