"""Regressions for 20260708 no-suggestion rounds and dictionary freshness."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cursed_words_solver.config import ensure_wordlist, wordlist_signature
from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
from cursed_words_solver.rules.stamp_behaviors import stamp_search_flags_mask
from cursed_words_solver.search import PathValidator, WordSearcher

ROUND_20260708_NO_SUGGESTION = (
    Path.home() / ".cursed_words_solver" / "round_logs" / "20260708_113415_868.json"
)
ROUND_20260708_PATH_MISMATCH = (
    Path.home() / ".cursed_words_solver" / "round_logs" / "20260708_113716_684.json"
)
GAME_WORDLIST = Path.home() / ".cursed_words_solver" / "game_words.txt"


def test_wordlist_signature_changes_when_file_refreshes(tmp_path: Path):
    words = tmp_path / "game_words.txt"
    words.write_text("cat\ndog\n", encoding="utf-8")
    sig1 = wordlist_signature(words)
    words.write_text("cat\ndog\nshtchis\n", encoding="utf-8")
    sig2 = wordlist_signature(words)
    assert sig1 != sig2


@pytest.mark.skipif(
    not ROUND_20260708_NO_SUGGESTION.exists() or not GAME_WORDLIST.exists(),
    reason="20260708 no-suggestion log and game_words required",
)
def test_20260708_no_suggestion_word_is_in_game_dictionary_and_valid():
    data = json.loads(ROUND_20260708_NO_SUGGESTION.read_text(encoding="utf-8"))
    board = parse_board_from_run_state(data["run_state"])
    loadout = parse_run_state(data["run_state"])
    assert board is not None and loadout is not None
    dictionary = WordDictionary(GAME_WORDLIST)
    submitted_word = (data.get("actual") or {}).get("word", "").lower()
    assert submitted_word == "shtchis"
    assert dictionary.contains(submitted_word)
    validator = PathValidator(dictionary, min_len=7)
    validator.quest_loadout = loadout
    flags = stamp_search_flags_mask(loadout)
    submitted_path = (data.get("actual") or {}).get("path_storage")
    if not submitted_path:
        from cursed_words_solver.ui.board_geometry import path_from_melmod_indices

        submitted_path = path_from_melmod_indices(board, (data.get("actual") or {}).get("path", []))
    assert validator.word_ok(board, submitted_path, submitted_word, flags)


@pytest.mark.skipif(
    not ROUND_20260708_PATH_MISMATCH.exists(),
    reason="20260708 fixture required",
)
def test_searcher_back_to_back_boards_do_not_drift_state():
    round2 = json.loads(ROUND_20260708_PATH_MISMATCH.read_text(encoding="utf-8"))
    board_a = parse_board_from_run_state(round2["run_state"])
    loadout_a = parse_run_state(round2["run_state"])
    assert board_a is not None and loadout_a is not None

    searcher = WordSearcher(
        dictionary=WordDictionary(ensure_wordlist()),
        min_len=7,
        max_len=25,
        time_budget=60.0,
        search_workers=8,
    )
    first_results = searcher.find_best_words(board_a, loadout_a, top_n=5)
    assert first_results
    second_results = searcher.find_best_words(board_a, loadout_a, top_n=3)
    assert second_results
    assert int(second_results[0].score) == int(first_results[0].score)
    assert int(second_results[0].score) >= 246
