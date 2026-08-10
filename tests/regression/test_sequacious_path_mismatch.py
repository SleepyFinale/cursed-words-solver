"""Chess+jack dict-resolve miss: aecial (346) vs sequacious (607).

Shared prefix through jack + rooks; F8 took the high-base rook continuation
while the bishop take-chain grows to sequacious / aedicules (+260).
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
    _CandidateHeap,
    _chess_item_dict_resolve_extend_viable,
    search_word_from_path,
)
from cursed_words_solver.rules.stamp_behaviors import stamp_search_flags
from cursed_words_solver.ui.board_geometry import path_from_melmod_indices

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "round_logs"
    / "20260809_170725_sequacious_path_mismatch.json"
)
F8_SCORE = 346
SUBMITTED_SCORE = 607


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
    reason="sequacious fixture and game wordlist required",
)
def test_chess_item_dict_resolve_extend_viable_on_fixture():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    board = parse_board_from_run_state(_f8_run_state_from_round_log(data))
    assert board is not None
    assert _chess_item_dict_resolve_extend_viable(board)


@pytest.mark.skipif(
    not FIXTURE.exists() or not GAME_WORDLIST_PATH.exists(),
    reason="sequacious fixture and game wordlist required",
)
def test_deep_extend_from_aecial_prefix_beats_f8():
    """Shared 5-tile prefix must deep-extend through the bishop take branch."""
    import time

    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    run_state = _f8_run_state_from_round_log(data)
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    assert board is not None and loadout is not None

    long = path_from_melmod_indices(board, data["actual"]["path"])
    prefix = long[:5]
    flags = stamp_search_flags(loadout)
    pipeline = ScoringPipeline()
    submitted = pipeline.score_total_only(
        board, long, data["actual"]["word"], loadout
    )
    assert int(submitted) >= SUBMITTED_SCORE - 50

    searcher = WordSearcher(
        dictionary=WordDictionary(GAME_WORDLIST_PATH),
        min_len=3,
        max_len=25,
        time_budget=8.0,
        search_workers=1,
    )
    # Warm solve context without burning the full F8 budget.
    searcher.time_budget = 3.0
    _ = searcher.find_best_words(board, loadout, top_n=1)
    searcher.time_budget = 8.0

    sw = search_word_from_path(board, prefix, flags=flags)
    ok, word = searcher._accept_path_for_search(board, prefix, sw, loadout, flags)
    assert ok
    rank = searcher._rank_score_for_candidate(board, prefix, word or sw, loadout)
    candidates = _CandidateHeap(80)
    candidates.consider(rank or 0.0, word or sw, prefix)
    searcher._extend_top_candidates(
        board,
        loadout,
        candidates,
        top_paths=40,
        max_rounds=8,
        deadline=time.monotonic() + 12.0,
    )
    best = candidates.best_sorted()
    assert best
    top_score = best[0][0]
    assert top_score >= float(SUBMITTED_SCORE) - 80, (
        f"deep-extend top {best[0][1]!r} {list(best[0][2])} rank={top_score}; "
        f"need near submitted {SUBMITTED_SCORE} (F8 was {F8_SCORE})"
    )
    # Prefer growing past the 6-tile aecial suggestion.
    assert any(len(path) >= 8 for _sc, _w, path in best)


@pytest.mark.skipif(
    not FIXTURE.exists() or not GAME_WORDLIST_PATH.exists(),
    reason="sequacious fixture and game wordlist required",
)
def test_full_search_beats_submitted_sequacious():
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
