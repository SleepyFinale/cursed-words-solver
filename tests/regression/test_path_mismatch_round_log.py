"""Replay submitted paths from melmod path_mismatch round logs."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from cursed_words_solver.loadout import (
    parse_board_from_run_state,
    parse_run_state,
    prepare_run_state_dict_for_scoring,
)
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


def _f8_run_state_from_round_log(data: dict) -> dict:
    """Reconstruct F8-time run state from a melmod round log."""
    rs = copy.deepcopy(data["run_state"])
    ex = rs.setdefault("extras", {})
    diff = data.get("extras_diff") or {}
    ex["scoring_previous_words_count"] = diff.get(
        "scoring_previous_words_count", {}
    ).get("f8", "0")
    ex["historic_words"] = "[]"
    ex["grid_scattered_items"] = diff.get("grid_scattered_items", {}).get("f8", "")
    ex["red_tiles_used_encounter"] = diff.get("red_tiles_used_encounter", {}).get(
        "f8", "0"
    )
    for key in ("sticker_order", "stamp_order"):
        if key in diff:
            ex[key] = diff[key].get("f8", ex.get(key, ""))
    if "loadout_fingerprint" in diff:
        ex["loadout_fingerprint"] = diff["loadout_fingerprint"].get(
            "f8", ex.get("loadout_fingerprint", "")
        )
    return prepare_run_state_dict_for_scoring(rs)


def _f8_run_state_from_extras_diff(data: dict) -> dict:
    """Reconstruct F8-time run state using all f8 values from extras_diff."""
    rs = copy.deepcopy(data["run_state"])
    ex = rs.setdefault("extras", {})
    diff = data.get("extras_diff") or {}
    for key, entry in diff.items():
        if not isinstance(entry, dict) or "f8" not in entry:
            continue
        f8_val = entry["f8"]
        if f8_val in (None, ""):
            continue
        ex[key] = f8_val
    return prepare_run_state_dict_for_scoring(rs)


INTERMEASURED_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "round_logs"
    / "20260625_intermeasured_path_mismatch.json"
)
CENOBITISMS_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "round_logs"
    / "20260625_cenobitisms_path_mismatch.json"
)
ROUND_20260708_PATH_MISMATCH = Path.home() / ".cursed_words_solver" / "round_logs" / "20260708_113716_684.json"
INTERMEASURED_PATH = [20, 17, 11, 5, 0, 1, 6, 12, 8, 4, 9, 13, 18]
INTERMEASURED_WORD = "intermeasured"
INTERMEASURED_F8_SCORE = 10_511

ITEM_HEAVY_SEARCH_FIXTURES = [
    (
        Path(__file__).resolve().parents[1]
        / "fixtures"
        / "round_logs"
        / "20260623_160441_kiddywinks_path_mismatch.json",
        45_000,
        30.0,
    ),
    (
        Path(__file__).resolve().parents[1]
        / "fixtures"
        / "round_logs"
        / "20260623_160736_hootnannie_path_mismatch.json",
        10_000,
        30.0,
    ),
    (
        Path(__file__).resolve().parents[1]
        / "fixtures"
        / "round_logs"
        / "20260623_161202_histidines_path_mismatch.json",
        5_000,
        30.0,
    ),
    (
        INTERMEASURED_FIXTURE,
        13_000,
        90.0,
    ),
    (
        CENOBITISMS_FIXTURE,
        8_500,
        90.0,
    ),
]


@pytest.mark.skipif(
    not ROUND_20260708_PATH_MISMATCH.exists(),
    reason="20260708 path-mismatch round log required",
)
def test_20260708_path_mismatch_search_beats_logged_f8():
    data = json.loads(ROUND_20260708_PATH_MISMATCH.read_text(encoding="utf-8"))
    run_state = _f8_run_state_from_round_log(data)
    board = parse_board_from_run_state(run_state)
    assert board is not None
    loadout = parse_run_state(run_state)
    assert loadout is not None
    rules = ScoringPipeline().rules
    constraints = boss_word_constraints(loadout, rules, default_max_len=25)
    searcher = WordSearcher(
        dictionary=WordDictionary(GAME_WORDLIST_PATH),
        min_len=constraints.min_len,
        max_len=constraints.max_len,
        search_workers=8,
        time_budget=60.0,
    )
    results = searcher.find_best_words(board, loadout, top_n=3)
    assert results, "search should produce suggestions on 20260708 grid-2 board"
    top_score = int(results[0].score)
    f8_score = int((data.get("solver") or {}).get("predicted_score", 0))
    actual_score = int((data.get("actual") or {}).get("score", 0))
    assert top_score >= f8_score
    assert top_score >= actual_score


@pytest.mark.parametrize(
    ("fixture_path", "min_top_score", "time_budget"),
    ITEM_HEAVY_SEARCH_FIXTURES,
    ids=["kiddywinks", "hootnannie", "histidines", "intermeasured", "cenobitisms"],
)
def test_item_heavy_grid_search_beats_f8_suggestion(
    fixture_path: Path, min_top_score: int, time_budget: float
):
    if not fixture_path.exists():
        pytest.skip(f"{fixture_path.name} required")
    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    run_state = _f8_run_state_from_round_log(data)
    board = parse_board_from_run_state(run_state)
    assert board is not None
    loadout = parse_run_state(run_state)
    assert loadout is not None
    rules = ScoringPipeline().rules
    constraints = boss_word_constraints(loadout, rules, default_max_len=25)
    searcher = WordSearcher(
        dictionary=WordDictionary(GAME_WORDLIST_PATH),
        min_len=constraints.min_len,
        max_len=constraints.max_len,
        time_budget=time_budget,
    )
    results = searcher.find_best_words(board, loadout, top_n=3)
    assert results, "search must find high-scoring item-tour paths"
    f8_score = int((data.get("solver") or {}).get("predicted_score", 0))
    top_score = int(results[0].score)
    assert top_score > f8_score
    assert top_score >= min_top_score


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


BEANS_SCATTERED_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "mismatches"
    / "20260625_beans_scattered_item.json"
)
BEANS_SCATTERED_PATH = [16, 10, 15, 20, 2, 8, 4, 9, 14, 13, 12, 18, 23]
BEANS_SCATTERED_WORD = "???o?????d?p?"


def _beans_scattered_board_and_loadout():
    if not BEANS_SCATTERED_FIXTURE.exists():
        pytest.skip("beans scattered-item fixture required")
    data = json.loads(BEANS_SCATTERED_FIXTURE.read_text(encoding="utf-8"))
    run_state = data.get("run_state_snapshot") or {}
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    assert board is not None and loadout is not None
    return data, board, loadout


@pytest.mark.skipif(
    not BEANS_SCATTERED_FIXTURE.exists(), reason="beans scattered-item fixture required"
)
def test_beans_greedy_item_tour_includes_invalid_path():
    import time

    from cursed_words_solver.models import CurseType
    from cursed_words_solver.rules.stamp_behaviors import stamp_search_flags
    from cursed_words_solver.search import (
        _active_indices,
        _greedy_scattered_item_tour_paths,
    )

    _data, board, loadout = _beans_scattered_board_and_loadout()
    flags = stamp_search_flags(loadout)
    item_indices = [
        i
        for i in _active_indices(board)
        if board.get_by_index(i).curse == CurseType.ITEM
    ]
    paths = _greedy_scattered_item_tour_paths(
        board,
        item_indices,
        1,
        25,
        flags=flags,
        deadline=time.monotonic() + 10,
    )
    assert any(p == BEANS_SCATTERED_PATH for p in paths)


@pytest.mark.skipif(
    not BEANS_SCATTERED_FIXTURE.exists(), reason="beans scattered-item fixture required"
)
def test_beans_scattered_path_has_no_game_dictionary_word():
    from cursed_words_solver.suggestion import (
        _valid_dictionary_words_for_path,
        game_word_for_path,
        path_is_submittable,
    )

    _data, board, loadout = _beans_scattered_board_and_loadout()
    if not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024:
        pytest.skip("game wordlist required")
    dictionary = WordDictionary(GAME_WORDLIST_PATH)
    valid = _valid_dictionary_words_for_path(
        board,
        BEANS_SCATTERED_PATH,
        BEANS_SCATTERED_WORD,
        loadout,
        dictionary,
    )
    assert valid == []
    assert not path_is_submittable(
        board,
        BEANS_SCATTERED_PATH,
        BEANS_SCATTERED_WORD,
        loadout,
        dictionary,
    )
    assert "?" in game_word_for_path(
        board,
        BEANS_SCATTERED_PATH,
        BEANS_SCATTERED_WORD,
        loadout,
        dictionary,
    )


@pytest.mark.skipif(
    not BEANS_SCATTERED_FIXTURE.exists(), reason="beans scattered-item fixture required"
)
def test_beans_scattered_path_rejected_by_search_accept():
    from cursed_words_solver.rules.stamp_behaviors import stamp_search_flags
    from cursed_words_solver.search import WordSearcher, search_word_from_path

    _data, board, loadout = _beans_scattered_board_and_loadout()
    if not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024:
        pytest.skip("game wordlist required")
    flags = stamp_search_flags(loadout)
    search_word = search_word_from_path(board, BEANS_SCATTERED_PATH, flags=flags)
    searcher = WordSearcher(
        dictionary=WordDictionary(GAME_WORDLIST_PATH),
        min_len=1,
    )
    searcher.validator.quest_loadout = loadout
    accepted, _ = searcher._accept_path_for_search(
        board,
        BEANS_SCATTERED_PATH,
        search_word,
        loadout,
        flags,
    )
    assert not accepted


@pytest.mark.skipif(
    not BEANS_SCATTERED_FIXTURE.exists(), reason="beans scattered-item fixture required"
)
def test_beans_search_does_not_suggest_invalid_scattered_path():
    from cursed_words_solver.rules.boss_effects import boss_word_constraints
    from cursed_words_solver.search import WordSearcher, word_assignable_on_path
    from cursed_words_solver.suggestion import game_word_for_path
    from cursed_words_solver.rules.stamp_behaviors import stamp_search_flags_mask

    _data, board, loadout = _beans_scattered_board_and_loadout()
    if not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024:
        pytest.skip("game wordlist required")
    dictionary = WordDictionary(GAME_WORDLIST_PATH)
    rules = ScoringPipeline().rules
    constraints = boss_word_constraints(loadout, rules, default_max_len=25)
    flags = stamp_search_flags_mask(loadout)
    searcher = WordSearcher(
        dictionary=dictionary,
        min_len=constraints.min_len,
        max_len=constraints.max_len,
        search_workers=8,
        time_budget=30.0,
    )
    results = searcher.find_best_words(board, loadout, top_n=5)
    assert results, "search must find valid words on beans scattered-item board"
    for result in results:
        if result.path == BEANS_SCATTERED_PATH:
            pytest.fail("search must not return unplayable scattered-item tour path")
        gw = game_word_for_path(
            board, result.path, result.word, loadout, dictionary
        )
        assert gw.isalpha(), f"unplayable suggestion {result.word!r} -> {gw!r}"
        assert word_assignable_on_path(board, result.path, gw, flags=flags)


BAILEE_6X6_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "round_logs"
    / "20260623_105541_bailee_6x6.json"
)


def _coords_to_solver_index(col: int, display_row: int, cols: int) -> int:
    """Top-first storage/display row → melmod index (not Unity GetCoordinates)."""
    if cols <= 0:
        cols = 5
    return (cols - 1 - display_row) * cols + col


def _unity_coords_to_melmod_index(unity_y: int, col: int, cols: int) -> int:
    """Mirror fixed melmod SuggestionMatcher.CoordsToSolverIndex."""
    if cols <= 0:
        cols = 5
    return unity_y * cols + col


def _broken_coords_on_unity_y(unity_y: int, col: int, cols: int) -> int:
    """Pre-v1.2.2 bug: treated Unity bottom-origin y as top-first display row."""
    if cols <= 0:
        cols = 5
    return (cols - 1 - unity_y) * cols + col


def _melmod_index_to_solver_coords(idx: int, cols: int) -> tuple[int, int]:
    unity_y = idx // cols
    col = idx % cols
    return cols - 1 - unity_y, col


def _storage_index_to_solver_coords(idx: int, cols: int) -> tuple[int, int]:
    return idx // cols, idx % cols


NINA_FALSE_MISMATCH_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "round_logs"
    / "20260630_145629_nina_false_encoding.json"
)


@pytest.mark.skipif(
    not NINA_FALSE_MISMATCH_FIXTURE.exists(),
    reason="nina false path mismatch fixture required",
)
def test_nina_false_path_mismatch_same_tiles_different_encoding():
    """v1.2.1 still false-mismatched when user traced F8 overlay on 5×5."""
    data = json.loads(NINA_FALSE_MISMATCH_FIXTURE.read_text(encoding="utf-8"))
    f8_path = data["solver"]["path"]
    wrong_path = data["actual"]["path"]
    assert f8_path == [14, 8, 12, 6, 2]
    assert wrong_path == [14, 18, 12, 16, 22]
    assert f8_path != wrong_path

    cols = 5
    f8_coords = [_melmod_index_to_solver_coords(i, cols) for i in f8_path]
    wrong_coords = [_storage_index_to_solver_coords(i, cols) for i in wrong_path]
    assert f8_coords == wrong_coords

    for f8_idx, wrong_idx in zip(f8_path, wrong_path, strict=True):
        unity_y, col = f8_idx // cols, f8_idx % cols
        assert _unity_coords_to_melmod_index(unity_y, col, cols) == f8_idx
        assert _broken_coords_on_unity_y(unity_y, col, cols) == wrong_idx

    assert data["comparison"]["board_fingerprint_matches_suggestion"] is True
    assert data["comparison"]["path_matches_suggestion"] is False


@pytest.mark.skipif(not BAILEE_6X6_FIXTURE.exists(), reason="bailee 6x6 fixture required")
def test_full_6x6_grid_path_conversion_roundtrip():
    """Full 6x6 boards must convert storage paths for melmod export (not identity)."""
    from cursed_words_solver.loadout import parse_board_from_run_state
    from cursed_words_solver.ui.board_geometry import (
        path_from_melmod_indices,
        path_to_melmod_indices,
    )

    data = json.loads(BAILEE_6X6_FIXTURE.read_text(encoding="utf-8"))
    board = parse_board_from_run_state(data["run_state"])
    assert board is not None
    assert board.rows == 6 and board.cols == 6

    melmod_path = data["solver"]["path"]
    storage_path = path_from_melmod_indices(board, melmod_path)
    assert path_to_melmod_indices(board, storage_path) == melmod_path
    assert storage_path != melmod_path


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


@pytest.mark.skipif(
    not INTERMEASURED_FIXTURE.exists(), reason="intermeasured fixture required"
)
def test_intermeasured_replay_submitted_path():
    data = json.loads(INTERMEASURED_FIXTURE.read_text(encoding="utf-8"))
    replay = _round_log_to_replay(data)
    score = _score_submitted(replay)
    assert replay["word"] == INTERMEASURED_WORD
    assert replay["path"] == INTERMEASURED_PATH
    assert int(replay["actual_score"]) == 13_230
    assert score >= 13_000


@pytest.mark.skipif(
    not INTERMEASURED_FIXTURE.exists(), reason="intermeasured fixture required"
)
def test_intermeasured_search_beats_f8():
    from cursed_words_solver.suggestion import path_is_submittable

    data = json.loads(INTERMEASURED_FIXTURE.read_text(encoding="utf-8"))
    run_state = _f8_run_state_from_round_log(data)
    board = parse_board_from_run_state(run_state)
    assert board is not None
    loadout = parse_run_state(run_state)
    assert loadout is not None
    rules = ScoringPipeline().rules
    constraints = boss_word_constraints(loadout, rules, default_max_len=25)
    dictionary = WordDictionary(GAME_WORDLIST_PATH)
    searcher = WordSearcher(
        dictionary=dictionary,
        min_len=constraints.min_len,
        max_len=constraints.max_len,
        search_workers=8,
        time_budget=90.0,
    )
    results = searcher.find_best_words(board, loadout, top_n=3)
    assert results
    f8_score = INTERMEASURED_F8_SCORE
    top = results[0]
    assert int(top.score) > f8_score
    assert int(top.score) >= 13_000
    assert path_is_submittable(
        board,
        top.path,
        top.word,
        loadout,
        dictionary,
        min_len=constraints.min_len,
    )
    assert any(
        list(r.path) == INTERMEASURED_PATH
        or (r.dictionary_word or r.word).lower() == INTERMEASURED_WORD
        for r in results[:3]
    )


THUYA_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "round_logs"
    / "20260629_thuya_path_mismatch.json"
)
THUYA_PATH = [17, 13, 7, 1, 0]
THUYA_F8_SCORE = 1656


@pytest.mark.skipif(not THUYA_FIXTURE.exists(), reason="thuya fixture required")
def test_thuya_submitted_path_scores():
    data = json.loads(THUYA_FIXTURE.read_text(encoding="utf-8"))
    from cursed_words_solver.debug_path import validate_submitted_path

    rs = prepare_run_state_dict_for_scoring(data["run_state"])
    report = validate_submitted_path(rs, THUYA_PATH)
    assert report.accepted
    assert report.predicted_score >= 6200
    actual = int((data.get("actual") or {}).get("score", 0))
    assert actual == 6300


@pytest.mark.skipif(not THUYA_FIXTURE.exists(), reason="thuya fixture required")
def test_thuya_parallel_search_beats_f8_suggestion():
    if not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024:
        pytest.skip("game wordlist required")
    from cursed_words_solver.config import AppConfig

    data = json.loads(THUYA_FIXTURE.read_text(encoding="utf-8"))
    run_state = _f8_run_state_from_extras_diff(data)
    board = parse_board_from_run_state(run_state)
    assert board is not None
    loadout = parse_run_state(run_state)
    assert loadout is not None
    rules = ScoringPipeline().rules
    constraints = boss_word_constraints(loadout, rules, default_max_len=25)
    cfg = AppConfig.load()
    searcher = WordSearcher(
        dictionary=WordDictionary(GAME_WORDLIST_PATH),
        min_len=constraints.min_len,
        max_len=constraints.max_len,
        search_workers=8,
        time_budget=60.0,
    )
    searcher.setup_weight = cfg.setup_weight
    searcher.mult_search_weight = cfg.mult_search_weight
    results = searcher.find_best_words(board, loadout, top_n=3)
    assert results, "parallel search must find words on thuya board"
    timing = searcher.last_search_timing
    assert timing is not None
    assert timing.parallel_serial_fallback is True
    top_score = int(results[0].score)
    assert top_score > THUYA_F8_SCORE
    assert top_score >= 6000


TREENS_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "round_logs"
    / "20260629_214131_treens_path_mismatch.json"
)
TREENS_PATH = [11, 5, 9, 3, 2, 1]
TREENS_F8_SCORE = 4445

NUMBER_START_ALT_PATH_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "round_logs"
    / "20260708_number_start_path_mismatch.json"
)
DIVOTS_PATH_MISMATCH_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "round_logs"
    / "20260708_divots_path_mismatch.json"
)
AIGRETS_PATH_MISMATCH_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "round_logs"
    / "20260708_aigrets_path_mismatch.json"
)
AIGRETS_F8_SCORE = 38_535
AIGRETS_SUBMITTED_SCORE = 80_780


@pytest.mark.skipif(
    not AIGRETS_PATH_MISMATCH_FIXTURE.exists(),
    reason="20260708 aigrets path-mismatch fixture required",
)
def test_aigrets_submitted_path_replay_score():
    data = json.loads(AIGRETS_PATH_MISMATCH_FIXTURE.read_text(encoding="utf-8"))
    replay = _round_log_to_replay(data)
    score = _score_submitted(replay)
    assert replay["word"] == "aigrets"
    assert score == AIGRETS_SUBMITTED_SCORE


@pytest.mark.skipif(
    not AIGRETS_PATH_MISMATCH_FIXTURE.exists() or not GAME_WORDLIST_PATH.exists(),
    reason="aigrets fixture and game wordlist required",
)
def test_aigrets_f8_run_state_search_beats_f8():
    if GAME_WORDLIST_PATH.stat().st_size < 1024:
        pytest.skip("game wordlist required")
    data = json.loads(AIGRETS_PATH_MISMATCH_FIXTURE.read_text(encoding="utf-8"))
    run_state = _f8_run_state_from_round_log(data)
    board = parse_board_from_run_state(run_state)
    assert board is not None
    loadout = parse_run_state(run_state)
    assert loadout is not None
    rules = ScoringPipeline().rules
    constraints = boss_word_constraints(loadout, rules, default_max_len=25)
    searcher = WordSearcher(
        dictionary=WordDictionary(GAME_WORDLIST_PATH),
        min_len=constraints.min_len,
        max_len=constraints.max_len,
        search_workers=8,
        time_budget=60.0,
    )
    results = searcher.find_best_words(board, loadout, top_n=3)
    assert results, "search should find words on aigrets wildcard+item board"
    top_score = int(results[0].score)
    f8_score = int((data.get("solver") or {}).get("predicted_score", 0))
    assert top_score > f8_score
    assert top_score >= AIGRETS_SUBMITTED_SCORE


@pytest.mark.skipif(
    not AIGRETS_PATH_MISMATCH_FIXTURE.exists() or not GAME_WORDLIST_PATH.exists(),
    reason="aigrets fixture and game wordlist required",
)
def test_dictionary_scoring_word_does_not_cache_timeout():
    if GAME_WORDLIST_PATH.stat().st_size < 1024:
        pytest.skip("game wordlist required")
    import time

    from cursed_words_solver.rules.stamp_behaviors import stamp_search_flags_mask
    from cursed_words_solver.search import search_word_from_path
    from cursed_words_solver.ui.board_geometry import path_from_melmod_indices

    data = json.loads(AIGRETS_PATH_MISMATCH_FIXTURE.read_text(encoding="utf-8"))
    run_state = _f8_run_state_from_round_log(data)
    board = parse_board_from_run_state(run_state)
    assert board is not None
    loadout = parse_run_state(run_state)
    assert loadout is not None
    path = path_from_melmod_indices(board, data["actual"]["path"])
    flags = stamp_search_flags_mask(loadout)
    search_word = search_word_from_path(board, path, flags=flags)
    searcher = WordSearcher(
        dictionary=WordDictionary(GAME_WORDLIST_PATH),
        min_len=3,
        max_len=25,
    )
    searcher.validator.quest_loadout = loadout
    searcher._active_deadline = time.monotonic() + 0.001
    assert searcher._dictionary_scoring_word(
        board, path, search_word, loadout, flags
    ) is None
    assert path not in searcher._dict_valid_words_cache
    searcher._active_deadline = time.monotonic() + 120.0
    resolved = searcher._dictionary_scoring_word(
        board, path, search_word, loadout, flags
    )
    assert resolved
    assert tuple(path) in searcher._dict_valid_words_cache


@pytest.mark.skipif(not TREENS_FIXTURE.exists(), reason="treens fixture required")
def test_treens_submitted_path_beats_f8_suggestion():
    data = json.loads(TREENS_FIXTURE.read_text(encoding="utf-8"))
    replay = _round_log_to_replay(data)
    score = _score_submitted(replay)
    assert replay["path"] == TREENS_PATH
    assert replay["word"] == "treens"
    assert score > TREENS_F8_SCORE
    assert score >= 17_000


@pytest.mark.skipif(not TREENS_FIXTURE.exists(), reason="treens fixture required")
def test_treens_parallel_search_beats_f8_suggestion():
    if not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024:
        pytest.skip("game wordlist required")
    from cursed_words_solver.config import AppConfig

    data = json.loads(TREENS_FIXTURE.read_text(encoding="utf-8"))
    run_state = _f8_run_state_from_extras_diff(data)
    board = parse_board_from_run_state(run_state)
    assert board is not None
    loadout = parse_run_state(run_state)
    assert loadout is not None
    rules = ScoringPipeline().rules
    constraints = boss_word_constraints(loadout, rules, default_max_len=25)
    cfg = AppConfig.load()
    searcher = WordSearcher(
        dictionary=WordDictionary(GAME_WORDLIST_PATH),
        min_len=constraints.min_len,
        max_len=constraints.max_len,
        search_workers=8,
        time_budget=60.0,
    )
    searcher.setup_weight = cfg.setup_weight
    searcher.mult_search_weight = cfg.mult_search_weight
    results = searcher.find_best_words(board, loadout, top_n=3)
    assert results, "parallel search must find words on treens board"
    top_score = int(results[0].score)
    assert top_score > TREENS_F8_SCORE
    assert top_score >= 15_000
    treens_score, _ = ScoringPipeline().score(
        board, TREENS_PATH, "treens", loadout
    )
    assert int(treens_score) > TREENS_F8_SCORE


@pytest.mark.skipif(
    not NUMBER_START_ALT_PATH_FIXTURE.exists(),
    reason="20260708 number-start fixture required",
)
def test_number_start_alternate_path_replay_is_reachable():
    from cursed_words_solver.suggestion import path_is_submittable

    data = json.loads(NUMBER_START_ALT_PATH_FIXTURE.read_text(encoding="utf-8"))
    run_state = prepare_run_state_dict_for_scoring(data["run_state"])
    board = parse_board_from_run_state(run_state)
    assert board is not None
    loadout = parse_run_state(run_state)
    assert loadout is not None
    rules = ScoringPipeline().rules
    constraints = boss_word_constraints(loadout, rules, default_max_len=25)
    dictionary = WordDictionary(GAME_WORDLIST_PATH)
    searcher = WordSearcher(
        dictionary=dictionary,
        min_len=constraints.min_len,
        max_len=constraints.max_len,
        search_workers=8,
        time_budget=60.0,
    )
    results = searcher.find_best_words(board, loadout, top_n=5)
    assert results, "search should produce suggestions on number-start mismatch board"

    top_score = int(results[0].score)
    f8_score = int((data.get("solver") or {}).get("predicted_score", 0))
    submitted_score = int((data.get("actual") or {}).get("score", 0))
    assert top_score > f8_score
    assert top_score >= submitted_score - 200
    assert submitted_score > f8_score
    assert any(r.word and r.word[0].isdigit() for r in results[:5])
    best = results[0]
    assert path_is_submittable(
        board,
        best.path,
        best.word,
        loadout,
        dictionary,
        min_len=constraints.min_len,
    )


@pytest.mark.skipif(
    not DIVOTS_PATH_MISMATCH_FIXTURE.exists(),
    reason="20260708 divots path-mismatch fixture required",
)
def test_divots_number_start_path_mismatch_is_recovered():
    from cursed_words_solver.ui.board_geometry import path_from_melmod_indices

    data = json.loads(DIVOTS_PATH_MISMATCH_FIXTURE.read_text(encoding="utf-8"))
    run_state = prepare_run_state_dict_for_scoring(data["run_state"])
    board = parse_board_from_run_state(run_state)
    assert board is not None
    loadout = parse_run_state(run_state)
    assert loadout is not None
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
    assert results, "search should produce suggestions on divots mismatch board"
    top_score = int(results[0].score)
    f8_score = int((data.get("solver") or {}).get("predicted_score", 0))
    submitted_score = int((data.get("actual") or {}).get("score", 0))
    submitted_storage = path_from_melmod_indices(board, data["actual"]["path"])
    flags = stamp_search_flags_mask(loadout)
    submitted_solver_legal = path_movement_ok(
        board, submitted_storage, flags=flags, loadout=loadout
    )
    assert not submitted_solver_legal
    assert submitted_score > f8_score
    assert top_score > f8_score
    assert top_score >= f8_score + 300


DILUTES_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "round_logs"
    / "20260629_221610_dilutes_no_search.json"
)
DILUTES_PATH = [3, 2, 7, 11, 12, 18, 14]
DILUTES_WORD = "dilutes"


@pytest.mark.skipif(not DILUTES_FIXTURE.exists(), reason="dilutes fixture required")
def test_dilutes_submitted_path_valid_on_f8_board():
    if not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024:
        pytest.skip("game wordlist required")
    data = json.loads(DILUTES_FIXTURE.read_text(encoding="utf-8"))
    run_state = _f8_run_state_from_extras_diff(data)
    board = parse_board_from_run_state(run_state)
    assert board is not None
    loadout = parse_run_state(run_state)
    assert loadout is not None
    assert PathValidator(WordDictionary(GAME_WORDLIST_PATH)).word_ok(
        board, DILUTES_PATH, DILUTES_WORD
    )
    assert path_movement_ok(board, DILUTES_PATH, loadout=loadout)


@pytest.mark.skipif(not DILUTES_FIXTURE.exists(), reason="dilutes fixture required")
def test_dilutes_parallel_search_finds_words_with_cobra_min_len():
    if not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024:
        pytest.skip("game wordlist required")
    from cursed_words_solver.config import AppConfig

    data = json.loads(DILUTES_FIXTURE.read_text(encoding="utf-8"))
    run_state = _f8_run_state_from_extras_diff(data)
    board = parse_board_from_run_state(run_state)
    assert board is not None
    loadout = parse_run_state(run_state)
    assert loadout is not None
    rules = ScoringPipeline().rules
    constraints = boss_word_constraints(loadout, rules, default_max_len=25)
    assert constraints.min_len >= 7
    cfg = AppConfig.load()
    searcher = WordSearcher(
        dictionary=WordDictionary(GAME_WORDLIST_PATH),
        min_len=max(constraints.min_len, 3),
        max_len=min(25, constraints.max_len),
        search_workers=8,
        time_budget=55.0,
    )
    searcher.setup_weight = cfg.setup_weight
    searcher.mult_search_weight = cfg.mult_search_weight
    results = searcher.find_best_words(board, loadout, top_n=3)
    assert results, "parallel search must find words on dilutes board (cobra min len)"
    timing = searcher.last_search_timing
    assert timing is not None
    assert timing.score_calls > 0
    dilutes_score, _ = ScoringPipeline().score(
        board, DILUTES_PATH, DILUTES_WORD, loadout
    )
    assert int(dilutes_score) >= 1500
