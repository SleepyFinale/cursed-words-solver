"""Aug 2026 companion path-miss regressions (Rodman purple + Nat-H4)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cursed_words_solver.config import GAME_WORDLIST_PATH
from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
from cursed_words_solver.rules.boss_effects import boss_word_constraints
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.search import WordSearcher, path_movement_ok
from cursed_words_solver.suggestion import path_is_submittable
from cursed_words_solver.ui.board_geometry import path_from_melmod_indices
from tests.regression.test_path_mismatch_round_log import _f8_run_state_from_round_log

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "round_logs"

# Exact submit-score parity after purple-as-red + cherry_pie scatter tier fixes.
SCORE_PARITY_FIXTURES = [
    "20260801_230807_687_woenesses_path_extension.json",
    "20260802_004854_898_whens_path_extension.json",
    "20260802_004442_341_abubble_path_extension.json",
    "20260801_230242_898_hostesses_path_mismatch.json",
    "20260801_225012_112_sheernesses_path_extension.json",
    "20260801_225721_921_sawflies_path_mismatch.json",
    "20260801_212410_957_fablemongering_path_mismatch.json",
]

# Rodman purple boards where ranking/extension now reaches near-submit.
RODMAN_SEARCH_FIXTURES = [
    "20260801_230807_687_woenesses_path_extension.json",
    "20260802_004854_898_whens_path_extension.json",
    "20260801_230242_898_hostesses_path_mismatch.json",
    "20260801_225012_112_sheernesses_path_extension.json",
    "20260801_225721_921_sawflies_path_mismatch.json",
]


def _paths(names: list[str]) -> list[Path]:
    return [p for name in names if (p := FIXTURES / name).is_file()]


@pytest.mark.parametrize(
    "fixture_path",
    _paths(SCORE_PARITY_FIXTURES),
    ids=lambda p: p.stem.rsplit("_", 2)[0],
)
def test_aug_path_miss_submitted_path_scores_and_is_legal(fixture_path: Path):
    if not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024:
        pytest.skip("game wordlist required")
    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    run_state = _f8_run_state_from_round_log(data)
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    assert board is not None and loadout is not None
    actual = data["actual"]
    word = str(actual["word"])
    path = path_from_melmod_indices(board, actual["path"])
    score, _ = ScoringPipeline().score(board, path, word, loadout)
    assert int(score) == int(actual["score"])
    dictionary = WordDictionary(GAME_WORDLIST_PATH)
    assert path_movement_ok(board, path, loadout=loadout)
    assert path_is_submittable(board, path, word, loadout, dictionary)


@pytest.mark.parametrize(
    "fixture_path",
    _paths(RODMAN_SEARCH_FIXTURES),
    ids=lambda p: p.stem.rsplit("_", 2)[0],
)
def test_aug_rodman_search_beats_logged_f8(fixture_path: Path):
    """Rodman purple boards: purple-as-red ranking should reach near-submit."""
    if not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024:
        pytest.skip("game wordlist required")
    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    run_state = _f8_run_state_from_round_log(data)
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    assert board is not None and loadout is not None
    submitted = int((data.get("actual") or {}).get("score") or 0)
    solver = data.get("solver") or {}
    f8_word = str(solver.get("word") or "")
    f8_path = path_from_melmod_indices(board, solver.get("path") or [])
    f8_now, _ = ScoringPipeline().score(board, f8_path, f8_word, loadout)
    rules = ScoringPipeline().rules
    constraints = boss_word_constraints(loadout, rules, default_max_len=25)
    searcher = WordSearcher(
        dictionary=WordDictionary(GAME_WORDLIST_PATH),
        min_len=constraints.min_len,
        max_len=constraints.max_len,
        search_workers=8,
        time_budget=45.0,
    )
    results = searcher.find_best_words(board, loadout, top_n=5)
    assert results, f"search should find words on {fixture_path.stem}"
    top = int(results[0].score)
    assert top >= int(f8_now)
    assert top >= min(submitted, int(submitted * 0.85))
