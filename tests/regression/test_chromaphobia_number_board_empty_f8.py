"""Regression: Chromaphobia + number tiles must find short colorless letter words.

Round log 20260715_185110_470: F8 returned no_suggestion; player submitted slav
(not always in our wordlist). Beam mode used caps=[max_len] only, so letter DFS
never surfaced short Normal-tile words before wildcard thrash.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cursed_words_solver.config import ensure_wordlist
from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
from cursed_words_solver.rules.boss_effects import boss_word_constraints
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.quest_effects import (
    active_quest_game_class,
    quest_path_allowed,
)
from cursed_words_solver.search import WordSearcher, _number_board_cap_sequence
from cursed_words_solver.ui.board_geometry import path_from_melmod_indices

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "round_logs"
    / "20260715_185110_470.json"
)
SUBMITTED_WORD = "slav"
SUBMITTED_MELMOD_PATH = [20, 21, 22, 23]


@pytest.fixture(scope="module")
def chromaphobia_board_loadout():
    if not FIXTURE.exists():
        pytest.skip("Chromaphobia number-board round-log fixture required")
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    board = parse_board_from_run_state(data["run_state"])
    loadout = parse_run_state(data["run_state"])
    assert board is not None and loadout is not None
    assert active_quest_game_class(loadout) == "Chromaphobia"
    return board, loadout, data


def test_submitted_slav_path_is_quest_allowed(chromaphobia_board_loadout):
    board, loadout, data = chromaphobia_board_loadout
    path = path_from_melmod_indices(board, SUBMITTED_MELMOD_PATH)
    assert data["actual"]["word"] == SUBMITTED_WORD
    assert quest_path_allowed(board, path, loadout=loadout)


def test_beam_find_best_words_finds_colorless_words(chromaphobia_board_loadout):
    board, loadout, _data = chromaphobia_board_loadout
    rules = ScoringPipeline().rules
    constraints = boss_word_constraints(loadout, rules, default_max_len=25)
    dictionary = WordDictionary(ensure_wordlist())
    searcher = WordSearcher(
        dictionary=dictionary,
        min_len=max(3, constraints.min_len),
        max_len=min(25, constraints.max_len),
        time_budget=20.0,
        search_workers=1,
        use_beam_search=True,
    )
    results = searcher.find_best_words(board, loadout, top_n=5)
    assert results, (
        "beam F8 must find at least one colorless Chromaphobia word "
        "on number+wildcard boards"
    )
    timing = searcher.last_search_timing
    assert timing is not None
    assert not timing.number_board_empty_diag
    assert timing.dfs_caps[:6] == tuple(
        _number_board_cap_sequence(searcher.min_len, searcher.max_len)[:6]
    )
    for result in results:
        assert quest_path_allowed(board, list(result.path), loadout=loadout)
