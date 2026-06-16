"""Regression: number-tile words, short digit passes, position-locked NUMBER tiles."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cursed_words_solver.config import GAME_WORDLIST_PATH
from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.stamp_behaviors import stamp_search_flags
from cursed_words_solver.search import (
    PathValidator,
    WordSearcher,
    format_microscope_position_hint,
    is_numeric_wildcard,
    microscope_position_uses,
    physical_word_for_path,
)
from cursed_words_solver.search_parallel import shutdown_search_pool, warmup_search_pool
from cursed_words_solver.suggestion import dictionary_word_for_path

FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "boards"
    / "20260527_1e34n5d7.json"
)
HAYLEY_FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "boards"
    / "20260527_hayley_abacus.json"
)
HYENA_FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "boards"
    / "20260527_hyena_senora.json"
)
ABET5JP_FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "boards"
    / "20260606_abet5jp.json"
)
PEPONIDA_PATH = [0, 6, 2, 1, 5, 10, 16, 21]
ABET5JP_PATH = [22, 23, 18, 13, 8, 4, 9]
ABLATING_PATH = [1, 0, 5, 11, 6, 12, 18, 22]
SENORA_PATH = [11, 15, 16, 22, 23, 24]


@pytest.fixture(autouse=True)
def _reset_search_pool():
    yield
    shutdown_search_pool(wait=True)


def _board_and_loadout(fixture: Path = FIXTURE):
    if not fixture.exists():
        pytest.skip(f"board fixture required: {fixture.name}")
    data = json.loads(fixture.read_text(encoding="utf-8"))
    run_state = data["run_state"]
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    assert board is not None
    return board, loadout


def _assert_top_results_valid(board, loadout, results, validator, flags) -> None:
    assert results
    for r in results[:3]:
        assert validator.word_ok(board, r.path, r.word, flags), (
            f"invalid suggestion: {r.word!r} path={r.path}"
        )


@pytest.mark.skipif(
    not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024,
    reason="game wordlist required",
)
def test_single_tile_one_valid():
    board, loadout = _board_and_loadout()
    d = WordDictionary(GAME_WORDLIST_PATH)
    flags = stamp_search_flags(loadout)
    v = PathValidator(d, min_len=1)
    assert v.word_ok(board, [0], "1", flags)


@pytest.mark.skipif(
    not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024,
    reason="game wordlist required",
)
def test_peponida_path_valid_with_microscope():
    """Microscope base_score alternates align peponida on the 1e34 board (e.g. 5-tile base 6 at pos 6)."""
    board, loadout = _board_and_loadout()
    d = WordDictionary(GAME_WORDLIST_PATH)
    flags = stamp_search_flags(loadout)
    assert flags.microscope_base_score
    v = PathValidator(d, min_len=1)
    assert v.word_ok(board, PEPONIDA_PATH, "peponida", flags)
    uses = microscope_position_uses(
        board, PEPONIDA_PATH, "peponida", flags=flags
    )
    assert uses
    assert any(u["mode"] == "alternate_number_position" for u in uses)
    hint = format_microscope_position_hint(uses)
    assert hint.startswith("Microscope:")
    assert "base_score 6" in hint


def test_peponida_path_rejects_without_microscope():
    from dataclasses import replace

    board, loadout = _board_and_loadout()
    stamps = [
        s
        for s in loadout.stamps
        if (s.id or "").lower().replace(" ", "_") != "microscope"
    ]
    loadout_no_micro = replace(loadout, stamps=stamps)
    flags = stamp_search_flags(loadout_no_micro)
    assert not flags.microscope_base_score
    d = WordDictionary(GAME_WORDLIST_PATH)
    v = PathValidator(d, min_len=1)
    assert not v.word_ok(board, PEPONIDA_PATH, "peponida", flags)


@pytest.mark.skipif(
    not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024,
    reason="game wordlist required",
)
def test_dictionary_align_peponida_from_physical():
    board, loadout = _board_and_loadout()
    d = WordDictionary(GAME_WORDLIST_PATH)
    pipe = ScoringPipeline()
    flags = stamp_search_flags(loadout)
    phys = physical_word_for_path(board, PEPONIDA_PATH, flags=flags)
    assert phys == "1e34n5d7"
    assert d.contains("peponida")
    v = PathValidator(d, min_len=1)
    aligned = dictionary_word_for_path(
        board, PEPONIDA_PATH, phys, loadout, d, min_len=1, pipeline=pipe
    )
    if aligned is not None:
        assert v.word_ok(board, PEPONIDA_PATH, aligned, flags)


@pytest.mark.skipif(
    not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024,
    reason="game wordlist required",
)
@pytest.mark.slow
def test_1e34_board_serial_search_finds_words():
    board, loadout = _board_and_loadout()
    d = WordDictionary(GAME_WORDLIST_PATH)
    searcher = WordSearcher(
        dictionary=d,
        min_len=1,
        max_len=25,
        time_budget=25.0,
        wordlist_path=GAME_WORDLIST_PATH,
        search_workers=1,
    )
    results = searcher.find_best_words(board, loadout, top_n=5)
    flags = stamp_search_flags(loadout)
    v = PathValidator(d, min_len=1)
    _assert_top_results_valid(board, loadout, results, v, flags)


@pytest.mark.skipif(
    not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024,
    reason="game wordlist required",
)
@pytest.mark.slow
def test_1e34_board_parallel_search_finds_words():
    board, loadout = _board_and_loadout()
    d = WordDictionary(GAME_WORDLIST_PATH)
    warmup_search_pool(GAME_WORDLIST_PATH, 2)
    searcher = WordSearcher(
        dictionary=d,
        min_len=1,
        max_len=25,
        time_budget=25.0,
        wordlist_path=GAME_WORDLIST_PATH,
        search_workers=2,
    )
    results = searcher.find_best_words(board, loadout, top_n=5)
    flags = stamp_search_flags(loadout)
    v = PathValidator(d, min_len=1)
    _assert_top_results_valid(board, loadout, results, v, flags)
    timing = searcher.last_search_timing
    assert timing is not None


@pytest.mark.skipif(
    not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024,
    reason="game wordlist required",
)
def test_seed_finds_single_number_tile():
    board, loadout = _board_and_loadout()
    d = WordDictionary(GAME_WORDLIST_PATH)
    from cursed_words_solver.search import _CandidateHeap

    searcher = WordSearcher(
        dictionary=d,
        min_len=1,
        max_len=25,
        wordlist_path=GAME_WORDLIST_PATH,
        search_workers=1,
    )
    mini = _CandidateHeap(10)
    searcher._seed_single_number_tile_words(board, loadout, mini)
    words = {w for _s, w, _p in mini.best_sorted()}
    assert "1" in words


@pytest.mark.skipif(
    not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024,
    reason="game wordlist required",
)
def test_abet5jp_path_rejects_abettor_dictionary_resolve():
    """Letter tiles J/P must match; number tile 5 is wildcard at position 5 only."""
    board, loadout = _board_and_loadout(ABET5JP_FIXTURE)
    d = WordDictionary(GAME_WORDLIST_PATH)
    flags = stamp_search_flags(loadout)
    v = PathValidator(d, min_len=1)
    phys = physical_word_for_path(board, ABET5JP_PATH, flags=flags)
    assert phys == "abet5jp"
    assert not v.word_ok(board, ABET5JP_PATH, "abettor", flags)
    aligned = dictionary_word_for_path(
        board,
        ABET5JP_PATH,
        phys,
        loadout,
        d,
        min_len=1,
        pipeline=ScoringPipeline(),
    )
    assert aligned != "abettor"


@pytest.mark.skipif(
    not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024,
    reason="game wordlist required",
)
def test_ablating_path_rejected_on_hayley_board():
    board, loadout = _board_and_loadout(HAYLEY_FIXTURE)
    d = WordDictionary(GAME_WORDLIST_PATH)
    flags = stamp_search_flags(loadout)
    v = PathValidator(d, min_len=1)
    assert not v.word_ok(board, ABLATING_PATH, "ablating", flags)
    phys = physical_word_for_path(board, ABLATING_PATH, flags=flags)
    assert phys == "47786458"
    assert not v.word_ok(board, ABLATING_PATH, phys, flags)


@pytest.mark.skipif(
    not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024,
    reason="game wordlist required",
)
def test_single_tile_one_valid_hayley_board():
    board, loadout = _board_and_loadout(HAYLEY_FIXTURE)
    d = WordDictionary(GAME_WORDLIST_PATH)
    flags = stamp_search_flags(loadout)
    v = PathValidator(d, min_len=1)
    assert v.word_ok(board, [20], "1", flags)


@pytest.mark.skipif(
    not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024,
    reason="game wordlist required",
)
@pytest.mark.slow
def test_hayley_board_serial_search_top_valid():
    board, loadout = _board_and_loadout(HAYLEY_FIXTURE)
    d = WordDictionary(GAME_WORDLIST_PATH)
    flags = stamp_search_flags(loadout)
    v = PathValidator(d, min_len=1)
    searcher = WordSearcher(
        dictionary=d,
        min_len=1,
        max_len=25,
        time_budget=20.0,
        wordlist_path=GAME_WORDLIST_PATH,
        search_workers=1,
    )
    results = searcher.find_best_words(board, loadout, top_n=5)
    _assert_top_results_valid(board, loadout, results, v, flags)
    assert "ablating" not in {r.word for r in results}


@pytest.mark.skipif(
    not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024,
    reason="game wordlist required",
)
@pytest.mark.slow
def test_hayley_board_parallel_search_top_valid():
    board, loadout = _board_and_loadout(HAYLEY_FIXTURE)
    d = WordDictionary(GAME_WORDLIST_PATH)
    flags = stamp_search_flags(loadout)
    v = PathValidator(d, min_len=1)
    warmup_search_pool(GAME_WORDLIST_PATH, 2)
    searcher = WordSearcher(
        dictionary=d,
        min_len=1,
        max_len=25,
        time_budget=20.0,
        wordlist_path=GAME_WORDLIST_PATH,
        search_workers=2,
    )
    results = searcher.find_best_words(board, loadout, top_n=5)
    _assert_top_results_valid(board, loadout, results, v, flags)
    assert "ablating" not in {r.word for r in results}


@pytest.mark.skipif(
    not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024,
    reason="game wordlist required",
)
def test_senora_path_rejects_misaligned_dictionary_word_hyena_board():
    """Path is ieno46; senora swaps I→S and uses number slots for R/A — invalid."""
    board, loadout = _board_and_loadout(HYENA_FIXTURE)
    d = WordDictionary(GAME_WORDLIST_PATH)
    flags = stamp_search_flags(loadout)
    v = PathValidator(d, min_len=1)
    phys = physical_word_for_path(board, SENORA_PATH, flags=flags)
    assert phys == "ieno46"
    assert not v.word_ok(board, SENORA_PATH, "senora", flags)


@pytest.mark.skipif(
    not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024,
    reason="game wordlist required",
)
@pytest.mark.slow
def test_hyena_board_serial_beats_single_tile_one():
    board, loadout = _board_and_loadout(HYENA_FIXTURE)
    d = WordDictionary(GAME_WORDLIST_PATH)
    flags = stamp_search_flags(loadout)
    v = PathValidator(d, min_len=1)
    searcher = WordSearcher(
        dictionary=d,
        min_len=1,
        max_len=25,
        time_budget=25.0,
        wordlist_path=GAME_WORDLIST_PATH,
        search_workers=1,
    )
    results = searcher.find_best_words(board, loadout, top_n=5)
    assert results
    _assert_top_results_valid(board, loadout, results, v, flags)
    top = results[0]
    assert top.score > 100
    assert top.word != "1"
    assert len(top.path) > 1


POW_FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "mismatches"
    / "20260615_181233_pow.json"
)
POW_PATH = [12, 7, 11]


def _board_and_loadout_from_mismatch(fixture: Path):
    if not fixture.exists():
        pytest.skip(f"fixture required: {fixture.name}")
    data = json.loads(fixture.read_text(encoding="utf-8"))
    from tests.regression.test_scoring_mismatches import _run_state_for_replay

    run_state = _run_state_for_replay(data)
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    assert board is not None and loadout is not None
    return board, loadout, data


@pytest.mark.skipif(
    not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024,
    reason="game wordlist required",
)
def test_multidigit_number_face_dictionary_resolve_pow():
    """Face '11' inflates search form to 1123; resolve still finds letter words."""
    board, loadout, _data = _board_and_loadout_from_mismatch(POW_FIXTURE)
    d = WordDictionary(GAME_WORDLIST_PATH)
    flags = stamp_search_flags(loadout)
    v = PathValidator(d, min_len=1)
    assert v.word_ok(board, POW_PATH, "pow", flags)
    valid = dictionary_word_for_path(
        board,
        POW_PATH,
        "1123",
        loadout,
        d,
        min_len=1,
        pipeline=ScoringPipeline(),
    )
    assert valid is not None
    assert v.word_ok(board, POW_PATH, valid, flags)


@pytest.mark.skipif(
    not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024,
    reason="game wordlist required",
)
def test_pow_path_rank_beats_single_tile_one():
    """Regression: 3-tile letter word through multi-digit face beats lone '1'."""
    board, loadout, _data = _board_and_loadout_from_mismatch(POW_FIXTURE)
    d = WordDictionary(GAME_WORDLIST_PATH)
    searcher = WordSearcher(
        dictionary=d,
        min_len=1,
        max_len=25,
        time_budget=10.0,
        wordlist_path=GAME_WORDLIST_PATH,
        search_workers=1,
    )
    pow_rank = searcher._rank_score_for_candidate(board, POW_PATH, "1123", loadout)
    one_rank = searcher._rank_score_for_candidate(board, [15], "1", loadout)
    assert pow_rank is not None and one_rank is not None
    assert pow_rank > one_rank
    assert pow_rank > 251


@pytest.mark.skipif(
    not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024,
    reason="game wordlist required",
)
@pytest.mark.slow
def test_hyena_board_parallel_beats_single_tile_one():
    board, loadout = _board_and_loadout(HYENA_FIXTURE)
    d = WordDictionary(GAME_WORDLIST_PATH)
    flags = stamp_search_flags(loadout)
    v = PathValidator(d, min_len=1)
    warmup_search_pool(GAME_WORDLIST_PATH, 2)
    searcher = WordSearcher(
        dictionary=d,
        min_len=1,
        max_len=25,
        time_budget=25.0,
        wordlist_path=GAME_WORDLIST_PATH,
        search_workers=2,
    )
    results = searcher.find_best_words(board, loadout, top_n=5)
    assert results
    timing = searcher.last_search_timing
    assert timing is not None
    assert timing.parallel_serial_fallback or timing.letter_dfs_added > 0
    _assert_top_results_valid(board, loadout, results, v, flags)
    top = results[0]
    assert top.score > 100
    assert top.word != "1"
    assert len(top.path) > 1


AAHING_FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "mismatches"
    / "20260615_aahing_invalid.json"
)
AAHING_PATH = [4, 9, 14, 18, 12, 6]


@pytest.mark.skipif(
    not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024,
    reason="game wordlist required",
)
@pytest.mark.skipif(not AAHING_FIXTURE.exists(), reason="fixture required")
def test_aahing_path_rejected_on_advent_calendar_board():
    """Only one numeric wildcard (tile 3 at pos 2); game rejects aahing."""
    board, loadout, _data = _board_and_loadout_from_mismatch(AAHING_FIXTURE)
    d = WordDictionary(GAME_WORDLIST_PATH)
    flags = stamp_search_flags(loadout)
    v = PathValidator(d, min_len=3)
    phys = physical_word_for_path(board, AAHING_PATH, flags=flags)
    assert phys == "1820317214"
    assert not v.word_ok(board, AAHING_PATH, "aahing", flags)
    assert is_numeric_wildcard(
        board.get_by_index(AAHING_PATH[2]), 2, flags=flags, segment="aahing"
    )


@pytest.mark.skipif(
    not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024,
    reason="game wordlist required",
)
@pytest.mark.skipif(not AAHING_FIXTURE.exists(), reason="fixture required")
@pytest.mark.slow
def test_aahing_board_search_does_not_suggest_invalid_word():
    board, loadout, _data = _board_and_loadout_from_mismatch(AAHING_FIXTURE)
    d = WordDictionary(GAME_WORDLIST_PATH)
    flags = stamp_search_flags(loadout)
    v = PathValidator(d, min_len=3)
    searcher = WordSearcher(
        dictionary=d,
        min_len=3,
        max_len=25,
        time_budget=15.0,
        wordlist_path=GAME_WORDLIST_PATH,
        search_workers=1,
    )
    results = searcher.find_best_words(board, loadout, top_n=5)
    _assert_top_results_valid(board, loadout, results, v, flags)
    assert "aahing" not in {r.word for r in results}
    for r in results:
        if r.path == AAHING_PATH:
            resolved = dictionary_word_for_path(
                board,
                r.path,
                r.word,
                loadout,
                d,
                min_len=3,
                pipeline=ScoringPipeline(),
            )
            if resolved:
                assert v.word_ok(board, r.path, resolved, flags)
