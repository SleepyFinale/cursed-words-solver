"""Regression: ascending Number Go Up tour beats short aahs (llama miss).

Round log 20260809_013137_363: F8 suggested ``aahs`` (37248) on 1→2→3→6;
submitted 1→2→3→4→7 scored 50720 as dictionary word ``llama`` (any letter
word on that ascending path scores the same under Lab Coat / Full Battery).

After rejecting pure digit spellings, digits_only must still explore ascending
number tours and resolve them to Vocabulary letters.
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
from cursed_words_solver.search import PathValidator, WordSearcher, path_movement_ok
from cursed_words_solver.suggestion import path_is_submittable
from cursed_words_solver.ui.board_geometry import path_from_melmod_indices
from tests.regression.test_path_mismatch_round_log import _f8_run_state_from_round_log

LLAMA_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "round_logs"
    / "20260809_llama_path_mismatch.json"
)
LLAMA_MELMOD_PATH = [18, 24, 23, 22, 21]
LLAMA_F8_SCORE = 37248
LLAMA_SUBMIT_SCORE = 50720


@pytest.mark.skipif(
    not LLAMA_FIXTURE.exists() or not GAME_WORDLIST_PATH.exists(),
    reason="20260809 llama path-mismatch fixture and game wordlist required",
)
def test_llama_ascending_path_validates_and_scores():
    data = json.loads(LLAMA_FIXTURE.read_text(encoding="utf-8"))
    run_state = _f8_run_state_from_round_log(data)
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    assert board is not None and loadout is not None

    path = path_from_melmod_indices(board, LLAMA_MELMOD_PATH)
    flags = stamp_search_flags(loadout)
    assert path_movement_ok(board, path, flags=flags, loadout=loadout)

    dictionary = WordDictionary(GAME_WORDLIST_PATH)
    validator = PathValidator(dictionary, min_len=3)
    assert validator.word_ok(board, path, "llama", flags)
    assert path_is_submittable(
        board, path, "llama", loadout, dictionary, min_len=3
    )
    assert not path_is_submittable(
        board, path, "12347", loadout, dictionary, min_len=3
    )

    score = int(
        ScoringPipeline().score_total_only(
            board, path, "llama", loadout=loadout
        )
    )
    assert score == LLAMA_SUBMIT_SCORE
    sug = path_from_melmod_indices(board, data["solver"]["path"])
    aahs = int(
        ScoringPipeline().score_total_only(board, sug, "aahs", loadout=loadout)
    )
    assert aahs == LLAMA_F8_SCORE
    assert score > aahs


@pytest.mark.skipif(
    not LLAMA_FIXTURE.exists() or not GAME_WORDLIST_PATH.exists(),
    reason="20260809 llama path-mismatch fixture and game wordlist required",
)
def test_llama_find_best_words_beats_aahs():
    if GAME_WORDLIST_PATH.stat().st_size < 1024:
        pytest.skip("game wordlist required")

    data = json.loads(LLAMA_FIXTURE.read_text(encoding="utf-8"))
    run_state = _f8_run_state_from_round_log(data)
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    assert board is not None and loadout is not None

    searcher = WordSearcher(
        dictionary=WordDictionary(GAME_WORDLIST_PATH),
        min_len=3,
        max_len=25,
        search_workers=1,
        time_budget=35.0,
        use_beam_search=True,
    )
    t0 = time.monotonic()
    results = searcher.find_best_words(board, loadout, top_n=5)
    assert results, "search must return candidates"
    best = results[0]
    assert best.word.isalpha(), f"digit spelling leaked: {best.word!r}"
    assert int(best.score) > LLAMA_F8_SCORE
    assert int(best.score) >= LLAMA_SUBMIT_SCORE - 1
    assert time.monotonic() - t0 < 90.0
