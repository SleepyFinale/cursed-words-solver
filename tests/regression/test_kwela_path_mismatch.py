"""Bat 3×3 Michael board: aahs (1465) vs kwela (7850).

Shrunk all-chess boards need exhaustive path+dict-resolve scoring for every
length, not only full hamiltonians — peak tours are often active-1 (e.g.
aardvark 8546 on 8 of 9 tiles via white free-move).
"""

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
from cursed_words_solver.search import WordSearcher, _is_shrunk_board, _active_indices

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "round_logs"
    / "20260809_213158_kwela_path_mismatch.json"
)
F8_SCORE = 1465
SUBMITTED_SCORE = 7850


def _f8_run_state_from_round_log(data: dict) -> dict:
    rs = copy.deepcopy(data["run_state"])
    ex = rs.setdefault("extras", {})
    diff = data.get("extras_diff") or {}
    for key, entry in diff.items():
        if isinstance(entry, dict) and "f8" in entry and entry["f8"] not in (None, ""):
            ex[key] = entry["f8"]
    return prepare_run_state_dict_for_scoring(rs)


@pytest.mark.skipif(
    not FIXTURE.exists() or not GAME_WORDLIST_PATH.exists(),
    reason="kwela fixture and game wordlist required",
)
def test_bat_board_is_shrunk_nine_cells():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    board = parse_board_from_run_state(_f8_run_state_from_round_log(data))
    assert board is not None
    assert _is_shrunk_board(board)
    assert len(_active_indices(board)) == 9


@pytest.mark.skipif(
    not FIXTURE.exists() or not GAME_WORDLIST_PATH.exists(),
    reason="kwela fixture and game wordlist required",
)
def test_full_search_beats_submitted_kwela():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    run_state = _f8_run_state_from_round_log(data)
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    assert board is not None and loadout is not None

    searcher = WordSearcher(
        dictionary=WordDictionary(GAME_WORDLIST_PATH),
        min_len=3,
        max_len=9,
        time_budget=45.0,
        search_workers=1,
    )
    results = searcher.find_best_words(board, loadout, top_n=3)
    assert results
    assert int(results[0].score) >= SUBMITTED_SCORE, (
        f"best {results[0].word!r} {list(results[0].path)} scored {results[0].score}; "
        f"need >= {SUBMITTED_SCORE} (F8 was {F8_SCORE})"
    )
