"""Search regression: YINCE joker-bookend path on 20260527 ALOE board."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cursed_words_solver.config import GAME_WORDLIST_PATH
from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.rule_lookup import get_pin_scoring_rule
from cursed_words_solver.rules.scoring_conditions import (
    rewind_bicycle_pre_word_extras,
    word_starts_ends_different_suit,
)
from cursed_words_solver.search import WordSearcher, _joker_pair_paths

FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "mismatches"
    / "20260527_013139_yince.json"
)
YINCE_PATH = [4, 8, 13, 12, 6]


@pytest.fixture
def yince_board_loadout():
    if not FIXTURE.exists():
        pytest.skip("fixture missing")
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    board = parse_board_from_run_state(data["run_state_snapshot"])
    assert board is not None
    loadout = parse_run_state(data["run_state_snapshot"])
    pipeline = ScoringPipeline()
    rule = get_pin_scoring_rule(pipeline.rules, "bones_the_dog")
    rewind_bicycle_pre_word_extras(loadout, board, YINCE_PATH, rule)
    return board, loadout


def test_yince_path_wrestlers_qualifies(yince_board_loadout):
    board, _loadout = yince_board_loadout
    assert word_starts_ends_different_suit(board, YINCE_PATH)


def test_joker_pair_paths_seed_yince_bridge(yince_board_loadout):
    board, _loadout = yince_board_loadout
    seeded = {tuple(p) for p in _joker_pair_paths(board, 15)}
    assert tuple(YINCE_PATH) in seeded


def test_yince_fixture_scores_8320(yince_board_loadout):
    board, loadout = yince_board_loadout
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    score, _ = ScoringPipeline().score(board, YINCE_PATH, data["word"], loadout)
    assert int(score) == int(data["actual_score"])


@pytest.mark.slow
def test_search_finds_high_scoring_joker_bookend_word(yince_board_loadout):
    board, loadout = yince_board_loadout
    if not GAME_WORDLIST_PATH.exists():
        pytest.skip("game wordlist not installed")
    ws = WordSearcher(
        wordlist_path=GAME_WORDLIST_PATH,
        time_budget=45.0,
        search_workers=1,
    )
    results = ws.find_best_words(board, loadout, top_n=3)
    assert results
    top = results[0]
    assert int(top.score) >= 8000
    assert len(top.path) >= 5
