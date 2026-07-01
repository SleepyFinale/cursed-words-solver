"""Regression: thowels/TH3W5LS path beats h2se5 on grid-1 number-tile board (f8#1238)."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from cursed_words_solver.config import GAME_WORDLIST_PATH
from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.loadout import (
    parse_board_from_run_state,
    parse_run_state,
    prepare_run_state_dict_for_scoring,
)
from cursed_words_solver.rules.boss_effects import boss_word_constraints
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.search import PathValidator, WordSearcher
from cursed_words_solver.rules.stamp_behaviors import stamp_search_flags_mask
from cursed_words_solver.ui.board_geometry import path_from_melmod_indices, path_to_melmod_indices

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "round_logs"
    / "20260701_120022_thowels_path_mismatch.json"
)
THOWELS_MELMOD_PATH = [7, 8, 14, 19, 18, 17, 23]
F8_SCORE = 78
THOWELS_SCORE = 132


def _f8_board_and_loadout():
    if not FIXTURE.exists():
        pytest.skip("thowels round-log fixture required")
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    rs = copy.deepcopy(data["run_state"])
    ex = rs.setdefault("extras", {})
    diff = data.get("extras_diff") or {}
    for key, entry in diff.items():
        if isinstance(entry, dict) and "f8" in entry and entry["f8"] not in (None, ""):
            ex[key] = entry["f8"]
    ex["historic_words"] = "[]"
    ex["scoring_previous_words_count"] = "0"
    rs = prepare_run_state_dict_for_scoring(rs)
    board = parse_board_from_run_state(rs)
    loadout = parse_run_state(rs)
    assert board is not None and loadout is not None
    return data, board, loadout


@pytest.mark.skipif(not FIXTURE.exists(), reason="thowels fixture required")
def test_thowels_submitted_path_scores():
    data, board, loadout = _f8_board_and_loadout()
    storage_path = path_from_melmod_indices(board, THOWELS_MELMOD_PATH)
    score, _ = ScoringPipeline().score(board, storage_path, "thowels", loadout)
    assert int(score) == THOWELS_SCORE
    rules = ScoringPipeline().rules
    constraints = boss_word_constraints(loadout, rules)
    validator = PathValidator(WordDictionary(GAME_WORDLIST_PATH), min_len=constraints.min_len)
    validator.quest_loadout = loadout
    flags = stamp_search_flags_mask(loadout)
    assert validator.word_ok(board, storage_path, "thowels", flags)


@pytest.mark.skipif(not FIXTURE.exists(), reason="thowels fixture required")
def test_thowels_search_beats_f8_suggestion():
    data, board, loadout = _f8_board_and_loadout()
    rules = ScoringPipeline().rules
    constraints = boss_word_constraints(loadout, rules, default_max_len=25)
    searcher = WordSearcher(
        dictionary=WordDictionary(GAME_WORDLIST_PATH),
        min_len=constraints.min_len,
        max_len=constraints.max_len,
        time_budget=30.0,
    )
    results = searcher.find_best_words(board, loadout, top_n=5)
    assert results, "search must return candidates"
    f8_score = int((data.get("solver") or {}).get("predicted_score", F8_SCORE))
    top_score = int(results[0].score)
    assert top_score > f8_score
    assert top_score >= THOWELS_SCORE
    melmod_top = path_to_melmod_indices(board, results[0].path)
    on_target = [r for r in results if path_to_melmod_indices(board, r.path) == THOWELS_MELMOD_PATH]
    assert on_target, f"expected path {THOWELS_MELMOD_PATH}, top was {results[0].word} @ {melmod_top}"
