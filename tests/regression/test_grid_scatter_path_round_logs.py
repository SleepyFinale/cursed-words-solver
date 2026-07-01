"""Regression replay for Nina grid-scatter on-path/off-path round logs (2026-07-01)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.regression.test_path_mismatch_round_log import (
    _round_log_to_replay,
    _score_submitted,
)
from tests.regression.test_scoring_mismatches import (
    _run_state_for_replay,
    _replay_path,
)
from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.config import GAME_WORDLIST_PATH, AppConfig
from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.search import WordSearcher
from cursed_words_solver.rules.boss_effects import boss_word_constraints

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "round_logs"

CASES = [
    ("20260701_001007_816", "hiatus", 5022),
    ("20260701_001229_976", "airth", 1557),
    ("20260701_001506_903", "nedette", 205),
    ("20260701_001538_633", "leggiero", 3027),
    ("20260701_001740_816", "birlings", 4338),
    ("20260701_001813_328", "garrans", 2883),
    ("20260701_001847_480", "weenier", 4176),
]

HIATUS_OFF_PATH_SCORE = 3489


@pytest.mark.parametrize("stem,word,expected", CASES, ids=[c[0] for c in CASES])
def test_grid_scatter_round_log_replay(stem: str, word: str, expected: int) -> None:
    path = FIXTURE_DIR / f"{stem}.json"
    if not path.exists():
        pytest.skip(f"fixture required: {path.name}")
    data = json.loads(path.read_text(encoding="utf-8"))
    replay = _round_log_to_replay(data)
    assert replay["word"] == word
    score = _score_submitted(replay)
    # airth/leggiero/garrans: melmod path conversion can differ by ≤18 on init tiles.
    if stem in ("20260701_001229_976", "20260701_001538_633", "20260701_001813_328"):
        assert abs(score - expected) <= 18, f"{word}: {score} vs {expected}"
    else:
        assert score == expected


def test_hiatus_off_path_tombstone_still_3489() -> None:
    """Off-path tombstone route must not regress after on-path tombstone fix."""
    path = FIXTURE_DIR / "20260701_001007_816.json"
    if not path.exists():
        pytest.skip("hiatus fixture required")
    data = json.loads(path.read_text(encoding="utf-8"))
    replay = _run_state_for_replay(_round_log_to_replay(data))
    board = parse_board_from_run_state(replay)
    loadout = parse_run_state(replay)
    assert board is not None and loadout is not None
    solver_path = (data.get("solver") or {}).get("path")
    assert solver_path
    off_path = _replay_path(board, solver_path)
    score, _ = ScoringPipeline().score(board, off_path, "hiatus", loadout)
    assert int(score) == HIATUS_OFF_PATH_SCORE


@pytest.mark.skipif(
    not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024,
    reason="game wordlist required",
)
def test_hiatus_search_finds_tombstone_ending() -> None:
    path = FIXTURE_DIR / "20260701_001007_816.json"
    if not path.exists():
        pytest.skip("hiatus fixture required")
    data = json.loads(path.read_text(encoding="utf-8"))
    run_state = _run_state_for_replay(_round_log_to_replay(data))
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    assert board is not None and loadout is not None
    rules = ScoringPipeline().rules
    constraints = boss_word_constraints(loadout, rules)
    cfg = AppConfig.load()
    searcher = WordSearcher(
        dictionary=WordDictionary(GAME_WORDLIST_PATH),
        min_len=constraints.min_len,
        max_len=constraints.max_len,
        search_workers=8,
        time_budget=45.0,
    )
    searcher.setup_weight = cfg.setup_weight
    searcher.mult_search_weight = cfg.mult_search_weight
    results = searcher.find_best_words(board, loadout, top_n=3)
    assert results
    assert int(results[0].score) >= 5000
