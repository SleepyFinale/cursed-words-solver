"""Replay submitted paths from melmod path_mismatch round logs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
from cursed_words_solver.config import GAME_WORDLIST_PATH
from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.rules.boss_effects import boss_word_constraints
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.stamp_behaviors import stamp_search_flags_mask
from cursed_words_solver.search import PathValidator, WordSearcher, path_movement_ok
from tests.regression.test_scoring_mismatches import (
    _adjust_mutating_dna_extras,
    _run_state_for_replay,
)

ROUND_LOG_FIXTURES = sorted(
    (Path(__file__).resolve().parents[1] / "fixtures" / "round_logs").glob(
        "*_path_mismatch.json"
    )
)
FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "mismatches"
    / "20260615_181233_pow.json"
)
SPOOFERY_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "mismatches"
    / "20260615_193555_spoofery.json"
)
SPOOFERY_PATH = [17, 12, 13, 22, 23, 24, 18, 14]
ODYLE_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "mismatches"
    / "20260621_193445_odyle.json"
)
ODYLE_PATH = [11, 17, 22, 23, 24]
VOTELESS_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "mismatches"
    / "20260621_201821_voteless.json"
)
VOTELESS_PATH = [8, 13, 17, 22, 16, 11, 5, 0]
AARDVARK_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "mismatches"
    / "20260621_211210_aardvark.json"
)
AARDVARK_PATH = [19, 14, 13, 17, 22, 23, 24, 18]


def _voteless_board_and_loadout():
    if not VOTELESS_FIXTURE.exists():
        pytest.skip("voteless fixture required")
    data = json.loads(VOTELESS_FIXTURE.read_text(encoding="utf-8"))
    run_state = _run_state_for_replay(data)
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    assert board is not None and loadout is not None
    return data, board, loadout


def _round_log_to_replay(data: dict) -> dict:
    """Normalize melmod round-log JSON into mismatch-replay shape."""
    solver = data.get("solver") or {}
    actual = data.get("actual") or {}
    return {
        "word": actual.get("word"),
        "path": actual.get("path"),
        "actual_score": actual.get("score"),
        "predicted_score": solver.get("predicted_score"),
        "board_fingerprint": solver.get("board_fingerprint"),
        "loadout_fingerprint": solver.get("loadout_fingerprint"),
        "run_state_snapshot": data.get("run_state"),
        "actual_trace": actual.get("trace"),
        "match_status": data.get("match_status"),
    }


def _score_submitted(data: dict) -> int:
    replay = _run_state_for_replay(data)
    board = parse_board_from_run_state(replay)
    assert board is not None
    loadout = parse_run_state(replay)
    assert loadout is not None
    path = data["path"]
    from cursed_words_solver.ui.board_geometry import path_from_melmod_indices

    path = path_from_melmod_indices(board, path)
    word = data["word"]
    _adjust_mutating_dna_extras(replay, data, board, path)
    loadout = parse_run_state(replay)
    score, _ = ScoringPipeline().score(board, path, word, loadout)
    return int(score)


@pytest.mark.skipif(not FIXTURE.exists(), reason="pow fixture required")
def test_pow_fixture_replay_submitted_path():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    score = _score_submitted(data)
    assert data["actual_score"] == 610
    assert score > int(data.get("predicted_score", 251) or 251)
    assert 608 <= score <= 616


@pytest.mark.skipif(not SPOOFERY_FIXTURE.exists(), reason="spoofery fixture required")
def test_spoofery_fixture_replay_submitted_path():
    data = json.loads(SPOOFERY_FIXTURE.read_text(encoding="utf-8"))
    score = _score_submitted(data)
    assert data["actual_score"] == 36
    assert score == 36


@pytest.mark.skipif(not SPOOFERY_FIXTURE.exists(), reason="spoofery fixture required")
def test_spoofery_search_finds_best_path():
    data = json.loads(SPOOFERY_FIXTURE.read_text(encoding="utf-8"))
    run_state = _run_state_for_replay(data)
    board = parse_board_from_run_state(run_state)
    assert board is not None
    loadout = parse_run_state(run_state)
    assert loadout is not None
    searcher = WordSearcher(
        dictionary=WordDictionary(GAME_WORDLIST_PATH),
        search_workers=8,
        time_budget=60.0,
    )
    results = searcher.find_best_words(board, loadout, top_n=5)
    assert results
    best = results[0]
    assert int(best.score) >= 36
    assert best.path == SPOOFERY_PATH
    validator = PathValidator(WordDictionary(GAME_WORDLIST_PATH))
    validator.quest_loadout = loadout
    flags = stamp_search_flags_mask(loadout)
    assert validator.word_ok(board, best.path, "spoofery", flags)


@pytest.mark.parametrize("round_log_path", ROUND_LOG_FIXTURES, ids=lambda p: p.stem)
def test_round_log_path_mismatch_replay_submitted_path(round_log_path: Path):
    data = json.loads(round_log_path.read_text(encoding="utf-8"))
    assert data.get("match_status") in ("path_mismatch", "path_extension")
    replay = _round_log_to_replay(data)
    score = _score_submitted(replay)
    f8_score = int((data.get("solver") or {}).get("predicted_score", 0))
    assert score > f8_score
    if "pow" in round_log_path.stem:
        assert replay["word"] == "pow"
        assert replay["path"] == [12, 7, 11]
        assert replay["actual_score"] == 610
        assert 608 <= score <= 616


@pytest.mark.skipif(not ODYLE_FIXTURE.exists(), reason="odyle fixture required")
def test_odyle_fixture_replay_submitted_path():
    data = json.loads(ODYLE_FIXTURE.read_text(encoding="utf-8"))
    replay = _round_log_to_replay(data)
    score = _score_submitted(replay)
    assert replay["path"] == ODYLE_PATH
    assert replay["word"] == "odyle"
    assert replay["actual_score"] == 1790
    assert score >= 1740


@pytest.mark.skipif(not ODYLE_FIXTURE.exists(), reason="odyle fixture required")
def test_odyle_search_finds_submitted_path():
    data = json.loads(ODYLE_FIXTURE.read_text(encoding="utf-8"))
    run_state = _run_state_for_replay(_round_log_to_replay(data))
    board = parse_board_from_run_state(run_state)
    assert board is not None
    loadout = parse_run_state(run_state)
    assert loadout is not None
    searcher = WordSearcher(
        dictionary=WordDictionary(GAME_WORDLIST_PATH),
        search_workers=8,
        time_budget=30.0,
    )
    results = searcher.find_best_words(board, loadout, top_n=3)
    assert results
    best = results[0]
    f8_score = int((data.get("solver") or {}).get("predicted_score", 0))
    assert int(best.score) >= 1700
    assert int(best.score) > f8_score
    assert 17 in best.path and 22 in best.path


@pytest.mark.skipif(not VOTELESS_FIXTURE.exists(), reason="voteless fixture required")
def test_voteless_submitted_path_scores():
    data = json.loads(VOTELESS_FIXTURE.read_text(encoding="utf-8"))
    score = _score_submitted(data)
    assert data["path"] == VOTELESS_PATH
    assert data["word"] == "voteless"
    assert data["actual_score"] == 1536
    assert score >= 1480


@pytest.mark.skipif(not VOTELESS_FIXTURE.exists(), reason="voteless fixture required")
def test_voteless_path_movement_ok():
    _data, board, loadout = _voteless_board_and_loadout()
    flags = stamp_search_flags_mask(loadout)
    assert path_movement_ok(board, VOTELESS_PATH, flags=flags)


@pytest.mark.skipif(not VOTELESS_FIXTURE.exists(), reason="voteless fixture required")
def test_voteless_path_word_ok():
    _data, board, loadout = _voteless_board_and_loadout()
    rules = ScoringPipeline().rules
    constraints = boss_word_constraints(loadout, rules, default_max_len=25)
    validator = PathValidator(WordDictionary(GAME_WORDLIST_PATH), min_len=constraints.min_len)
    validator.quest_loadout = loadout
    flags = stamp_search_flags_mask(loadout)
    assert validator.word_ok(board, VOTELESS_PATH, "voteless", flags)


@pytest.mark.skipif(not VOTELESS_FIXTURE.exists(), reason="voteless fixture required")
def test_voteless_search_finds_words():
    _data, board, loadout = _voteless_board_and_loadout()
    rules = ScoringPipeline().rules
    constraints = boss_word_constraints(loadout, rules, default_max_len=25)
    searcher = WordSearcher(
        dictionary=WordDictionary(GAME_WORDLIST_PATH),
        min_len=constraints.min_len,
        max_len=constraints.max_len,
        search_workers=8,
        time_budget=60.0,
    )
    results = searcher.find_best_words(board, loadout, top_n=5)
    assert results, "search must find at least one valid word on Cobra grid-2 board"
    assert int(results[0].score) > 0


def _aardvark_board_and_loadout():
    if not AARDVARK_FIXTURE.exists():
        pytest.skip("aardvark fixture required")
    data = json.loads(AARDVARK_FIXTURE.read_text(encoding="utf-8"))
    run_state = data.get("run_state_snapshot") or {}
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    assert board is not None and loadout is not None
    return data, board, loadout


@pytest.mark.skipif(not AARDVARK_FIXTURE.exists(), reason="aardvark fixture required")
def test_aardvark_alignment_pattern_uses_face_letters():
    from cursed_words_solver.rules.stamp_behaviors import stamp_search_flags
    from cursed_words_solver.suggestion import _alignment_pattern_for_path

    _data, board, loadout = _aardvark_board_and_loadout()
    flags = stamp_search_flags(loadout)
    pattern = _alignment_pattern_for_path(board, AARDVARK_PATH, flags)
    assert pattern == "?svwygd?"
    assert pattern != "?" * len(AARDVARK_PATH)


@pytest.mark.skipif(not AARDVARK_FIXTURE.exists(), reason="aardvark fixture required")
def test_aardvark_path_has_no_game_dictionary_word():
    from cursed_words_solver.suggestion import (
        _valid_dictionary_words_for_path,
        effective_scoring_word,
        game_word_for_path,
    )

    _data, board, loadout = _aardvark_board_and_loadout()
    if not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024:
        pytest.skip("game wordlist required")
    dictionary = WordDictionary(GAME_WORDLIST_PATH)
    valid = _valid_dictionary_words_for_path(
        board,
        AARDVARK_PATH,
        "?svwygd?",
        loadout,
        dictionary,
    )
    assert valid == []
    assert game_word_for_path(
        board, AARDVARK_PATH, "?svwygd?", loadout, dictionary
    ) != "aardvark"
    assert effective_scoring_word(
        board, AARDVARK_PATH, "?svwygd?", loadout, dictionary
    ) != "aardvark"


@pytest.mark.skipif(not AARDVARK_FIXTURE.exists(), reason="aardvark fixture required")
def test_aardvark_search_finds_valid_words():
    from cursed_words_solver.search import word_assignable_on_path

    _data, board, loadout = _aardvark_board_and_loadout()
    if not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024:
        pytest.skip("game wordlist required")
    rules = ScoringPipeline().rules
    constraints = boss_word_constraints(loadout, rules, default_max_len=25)
    flags = stamp_search_flags_mask(loadout)
    searcher = WordSearcher(
        dictionary=WordDictionary(GAME_WORDLIST_PATH),
        min_len=constraints.min_len,
        max_len=constraints.max_len,
        search_workers=8,
        time_budget=60.0,
    )
    results = searcher.find_best_words(board, loadout, top_n=10)
    assert results, "search must find valid words on TFUR chess board"
    top = results[0]
    displayed = (top.dictionary_word or top.word).lower()
    assert displayed != "aardvark"
    assert word_assignable_on_path(board, top.path, displayed, flags=flags)


@pytest.mark.skipif(not AARDVARK_FIXTURE.exists(), reason="aardvark fixture required")
def test_aardvark_search_does_not_suggest_invalid_path():
    _data, board, loadout = _aardvark_board_and_loadout()
    if not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024:
        pytest.skip("game wordlist required")
    rules = ScoringPipeline().rules
    constraints = boss_word_constraints(loadout, rules, default_max_len=25)
    searcher = WordSearcher(
        dictionary=WordDictionary(GAME_WORDLIST_PATH),
        min_len=constraints.min_len,
        max_len=constraints.max_len,
        search_workers=8,
        time_budget=60.0,
    )
    results = searcher.find_best_words(board, loadout, top_n=10)
    for result in results:
        if result.path != AARDVARK_PATH:
            continue
        displayed = (result.dictionary_word or result.word).lower()
        assert displayed != "aardvark"


BAILEE_6X6_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "round_logs"
    / "20260623_105541_bailee_6x6.json"
)


def _coords_to_solver_index(col: int, display_row: int, cols: int) -> int:
    """Mirror melmod SuggestionMatcher.CoordsToSolverIndex."""
    if cols <= 0:
        cols = 5
    return (cols - 1 - display_row) * cols + col


@pytest.mark.skipif(not BAILEE_6X6_FIXTURE.exists(), reason="bailee 6x6 fixture required")
def test_bailee_6x6_submit_path_needs_board_cols_not_five():
    """False path_mismatch: 5-wide indexing collapses distinct 6x6 tiles."""
    data = json.loads(BAILEE_6X6_FIXTURE.read_text(encoding="utf-8"))
    f8_path = data["solver"]["path"]
    wrong_path = data["actual"]["path"]
    assert f8_path == [12, 23, 24, 35, 30, 29]
    assert wrong_path == [5, 15, 15, 25, 20, 20]

    # Game coords (x=col, y=display_row) for each tile on the F8 path.
    bailee_coords = [(0, 3), (5, 2), (0, 1), (5, 0), (0, 0), (5, 1)]
    indexed_6 = [_coords_to_solver_index(c, r, 6) for c, r in bailee_coords]
    indexed_5 = [_coords_to_solver_index(c, r, 5) for c, r in bailee_coords]

    assert indexed_6 == f8_path
    assert indexed_5 == wrong_path
    assert len(set(indexed_5)) < len(indexed_5)


PREASSURE_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "round_logs"
    / "20260623_140715_preassure_path_mismatch.json"
)
PREASSURE_MELMOD_PATH = [7, 3, 6, 8, 0, 5, 4, 1, 2]
UREASES_STORAGE_PATH = [21, 15, 20, 22, 10, 17, 16]
UREASES_MELMOD_PATH = [7, 3, 6, 8, 0, 5, 4]


def _preassure_board_and_loadout():
    if not PREASSURE_FIXTURE.exists():
        pytest.skip("preassure fixture required")
    data = json.loads(PREASSURE_FIXTURE.read_text(encoding="utf-8"))
    run_state = _run_state_for_replay(_round_log_to_replay(data))
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    assert board is not None and loadout is not None
    return data, board, loadout


@pytest.mark.skipif(not PREASSURE_FIXTURE.exists(), reason="preassure fixture required")
def test_preassure_replay_submitted_path():
    data, board, _loadout = _preassure_board_and_loadout()
    from cursed_words_solver.ui.board_geometry import path_from_melmod_indices

    replay = _round_log_to_replay(data)
    score = _score_submitted(replay)
    assert replay["word"] == "preassure"
    assert path_from_melmod_indices(board, replay["path"]) == path_from_melmod_indices(
        board, PREASSURE_MELMOD_PATH
    )
    assert int(replay["actual_score"]) == 1502
    assert score >= 850


@pytest.mark.skipif(not PREASSURE_FIXTURE.exists(), reason="preassure fixture required")
def test_preassure_search_finds_submitted_path():
    from cursed_words_solver.ui.board_geometry import path_from_melmod_indices

    data, board, loadout = _preassure_board_and_loadout()
    rules = ScoringPipeline().rules
    constraints = boss_word_constraints(loadout, rules, default_max_len=25)
    searcher = WordSearcher(
        dictionary=WordDictionary(GAME_WORDLIST_PATH),
        min_len=constraints.min_len,
        max_len=constraints.max_len,
        search_workers=8,
        time_budget=60.0,
    )
    results = searcher.find_best_words(board, loadout, top_n=5)
    assert results
    best = results[0]
    f8_score = int((data.get("solver") or {}).get("predicted_score", 0))
    assert len(best.path) == 9
    assert int(best.score) >= 850
    assert int(best.score) > f8_score
    expected_storage = path_from_melmod_indices(board, PREASSURE_MELMOD_PATH)
    assert sorted(best.path) == sorted(expected_storage)


@pytest.mark.skipif(not PREASSURE_FIXTURE.exists(), reason="preassure fixture required")
def test_bat_3x3_path_export_matches_melmod_cols():
    from cursed_words_solver.ui.board_geometry import path_to_melmod_indices

    _data, board, _loadout = _preassure_board_and_loadout()
    assert path_to_melmod_indices(board, UREASES_STORAGE_PATH) == UREASES_MELMOD_PATH
    assert path_to_melmod_indices(board, UREASES_STORAGE_PATH) != [
        1,
        3,
        0,
        2,
        6,
        5,
        4,
    ]
    assert PREASSURE_MELMOD_PATH != UREASES_MELMOD_PATH
