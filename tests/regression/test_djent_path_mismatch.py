"""Bat 3×3: aahs (6345) wrongly preferred over aarrghh (8403).

Search found the stronger tour, but finalist ranking used inflated search
rank (111k) over immediate submit score, so F8 suggested aahs. Submitted
djent (8198) beat F8; legal peak is >=8403.
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
from cursed_words_solver.search import WordSearcher

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "round_logs"
    / "20260809_215329_djent_path_mismatch.json"
)
F8_SCORE = 6345
SUBMITTED_SCORE = 8198


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
    reason="djent fixture and game wordlist required",
)
def test_finalists_ordered_by_immediate_score_not_search_rank():
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
    results = searcher.find_best_words(board, loadout, top_n=5)
    assert results
    scores = [int(r.score) for r in results]
    assert scores == sorted(scores, reverse=True), (
        f"finalists not ordered by immediate score: {[(r.word, int(r.score), int(r.rank_score or 0)) for r in results]}"
    )
    assert int(results[0].score) >= SUBMITTED_SCORE, (
        f"best {results[0].word!r} scored {results[0].score}; "
        f"need >= {SUBMITTED_SCORE} (F8 was {F8_SCORE})"
    )
