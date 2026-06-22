"""Search regression: mihrabs extension beats short ??h? prefix (20260527 Octacles)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cursed_words_solver.config import GAME_WORDLIST_PATH
from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.stamp_behaviors import stamp_search_flags
from cursed_words_solver.search import WordSearcher, resolve_letter

FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "mismatches"
    / "20260527_022243_mihrabs.json"
)
MIHRABS_PATH = [24, 18, 7, 13, 12, 11, 10]
SHORT_PATH = [24, 18, 7, 13]


@pytest.fixture
def mihrabs_board_loadout():
    if not FIXTURE.exists():
        pytest.skip("fixture missing")
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    board = parse_board_from_run_state(data["run_state_snapshot"])
    assert board is not None
    loadout = parse_run_state(data["run_state_snapshot"])
    return board, loadout, data


def test_mihrabs_fixture_scores_60(mihrabs_board_loadout):
    board, loadout, data = mihrabs_board_loadout
    flags = stamp_search_flags(loadout)
    scoring_word = "".join(
        resolve_letter(board.get_by_index(idx), j, flags=flags)
        for j, idx in enumerate(MIHRABS_PATH)
    ).lower()
    score = ScoringPipeline().score_total_only(
        board, MIHRABS_PATH, scoring_word, loadout
    )
    assert int(score) == int(data["actual_score"])


def test_short_prefix_fixture_scores_54(mihrabs_board_loadout):
    board, loadout, data = mihrabs_board_loadout
    short_word = "??h?"
    score = ScoringPipeline().score_total_only(
        board, SHORT_PATH, short_word, loadout
    )
    assert int(score) == int(data["short_score"])


@pytest.mark.slow
def test_search_finds_mihrabs_over_short_prefix(mihrabs_board_loadout):
    board, loadout, data = mihrabs_board_loadout
    if not GAME_WORDLIST_PATH.exists():
        pytest.skip("game wordlist not installed")
    ws = WordSearcher(
        dictionary=WordDictionary(GAME_WORDLIST_PATH),
        min_len=1,
        max_len=25,
        time_budget=60.0,
        search_workers=1,
    )
    results = ws.find_best_words(board, loadout, top_n=3)
    assert results
    top = results[0]
    assert int(top.score) >= int(data["actual_score"])
    assert int(top.score) > int(data["short_score"])
    assert ws.last_search_timing is not None
    assert ws.last_search_timing.extend_sec > 0.0
