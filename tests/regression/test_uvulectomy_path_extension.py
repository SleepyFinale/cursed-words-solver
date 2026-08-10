"""Hungry Snake knight wrap miss: aardvark (7200) vs uvulectomy (9150).

F8 stopped on an 8-tile non-adj chess tour; the submitted 10-tile extension
uses a knight L-step that wraps columns (Hungry Snake). ``chess_neighbors_mask``
previously omitted ``horizontal_wrap`` for knights, so the path was illegal
and deep non-adj probes never seeded it.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from cursed_words_solver.config import GAME_WORDLIST_PATH
from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.graph_bitboard import build_board_graph_context
from cursed_words_solver.loadout import (
    parse_board_from_run_state,
    parse_run_state,
    prepare_run_state_dict_for_scoring,
)
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.stamp_behaviors import stamp_search_flags
from cursed_words_solver.search import (
    WordSearcher,
    _nonadjacent_chess_path_viable,
    _probe_nonadjacent_chess_paths,
    neighbors_mask,
)
from cursed_words_solver.suggestion import path_is_submittable
from cursed_words_solver.ui.board_geometry import path_from_melmod_indices

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "round_logs"
    / "20260809_205333_uvulectomy_path_extension.json"
)
F8_SCORE = 7200
SUBMITTED_SCORE = 9150


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
    reason="uvulectomy fixture and game wordlist required",
)
def test_hungry_snake_knight_wrap_reaches_final_tile():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    run_state = _f8_run_state_from_round_log(data)
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    assert board is not None and loadout is not None
    act = path_from_melmod_indices(board, data["actual"]["path"])
    flags = stamp_search_flags(loadout)
    graph = build_board_graph_context(board)
    visited = 0
    for idx in act[:-1]:
        visited |= 1 << idx
    nbr = neighbors_mask(
        board,
        visited,
        cell_id=act[-2],
        flags=flags,
        graph_ctx=graph,
        loadout=loadout,
    )
    assert nbr & (1 << act[-1]), (
        f"knight at {act[-2]} must wrap-reach {act[-1]} with Hungry Snake"
    )
    assert path_is_submittable(
        board, act, data["actual"]["word"], loadout, WordDictionary(GAME_WORDLIST_PATH), min_len=3
    )


@pytest.mark.skipif(
    not FIXTURE.exists() or not GAME_WORDLIST_PATH.exists(),
    reason="uvulectomy fixture and game wordlist required",
)
def test_nonadj_probe_includes_submitted_uvulectomy_path():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    run_state = _f8_run_state_from_round_log(data)
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    assert board is not None and loadout is not None
    assert _nonadjacent_chess_path_viable(board, loadout)
    act = path_from_melmod_indices(board, data["actual"]["path"])
    probes = _probe_nonadjacent_chess_paths(board, loadout, max_depth=10, max_paths=200)
    assert any(list(p) == act for p in probes)
    sc = ScoringPipeline().score_total_only(
        board, act, data["actual"]["word"], loadout
    )
    assert int(sc) == SUBMITTED_SCORE


@pytest.mark.skipif(
    not FIXTURE.exists() or not GAME_WORDLIST_PATH.exists(),
    reason="uvulectomy fixture and game wordlist required",
)
def test_full_search_beats_submitted_uvulectomy():
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
