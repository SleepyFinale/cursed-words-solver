"""Non-adjacent all-chess miss: aahs (4252) vs frenne (6066).

Imp + Footprints / Head in the Clouds: letter-trie DFS stops at short
``?`` tours (aahs) while longer geometrically non-adjacent chess chains
(frenne / aardvark-class) dominate score.
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
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.search import (
    WordSearcher,
    _nonadjacent_chess_path_viable,
    _probe_nonadjacent_chess_paths,
)
from cursed_words_solver.ui.board_geometry import path_from_melmod_indices

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "round_logs"
    / "20260809_203528_frenne_path_mismatch.json"
)
F8_SCORE = 4252
SUBMITTED_SCORE = 6066


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
    reason="frenne fixture and game wordlist required",
)
def test_nonadjacent_chess_viable_and_includes_submitted_path():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    board = parse_board_from_run_state(_f8_run_state_from_round_log(data))
    loadout = parse_run_state(_f8_run_state_from_round_log(data))
    assert board is not None and loadout is not None
    assert _nonadjacent_chess_path_viable(board, loadout)
    submitted = path_from_melmod_indices(board, data["actual"]["path"])
    probes = _probe_nonadjacent_chess_paths(board, loadout)
    assert any(list(p) == submitted for p in probes)


@pytest.mark.skipif(
    not FIXTURE.exists() or not GAME_WORDLIST_PATH.exists(),
    reason="frenne fixture and game wordlist required",
)
def test_submitted_frenne_scores_above_f8():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    run_state = _f8_run_state_from_round_log(data)
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    assert board is not None and loadout is not None
    path = path_from_melmod_indices(board, data["actual"]["path"])
    sc = ScoringPipeline().score_total_only(
        board, path, data["actual"]["word"], loadout
    )
    assert int(sc) >= SUBMITTED_SCORE - 50
    assert int(sc) > F8_SCORE


@pytest.mark.skipif(
    not FIXTURE.exists() or not GAME_WORDLIST_PATH.exists(),
    reason="frenne fixture and game wordlist required",
)
def test_full_search_beats_submitted_frenne():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    run_state = _f8_run_state_from_round_log(data)
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    assert board is not None and loadout is not None

    searcher = WordSearcher(
        dictionary=WordDictionary(GAME_WORDLIST_PATH),
        min_len=3,
        max_len=25,
        time_budget=45.0,
        search_workers=1,
    )
    results = searcher.find_best_words(board, loadout, top_n=3)
    assert results
    assert int(results[0].score) >= SUBMITTED_SCORE, (
        f"best {results[0].word!r} {list(results[0].path)} scored {results[0].score}; "
        f"need >= {SUBMITTED_SCORE} (F8 was {F8_SCORE})"
    )
