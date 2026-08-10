"""Wolf Stage 3 path_mismatch: chess-only capture paths must beat item-start F8.

Melmod: submitted xis (queen→knight→jack) 156 pts vs F8 brr (jack→rook→rook) 139.
Root cause: mult_aware_lower_bound prune skipped ITEM paths but still discarded
stronger chess-only paths (queen→rook→rook ~175) once the heap was full of item
routes — base×mult LB ignores amulet/take scoring on chess faces.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from cursed_words_solver.config import GAME_WORDLIST_PATH
from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.fast_rank import (
    mult_aware_lower_bound,
    path_underbounded_by_tile_mult_lb,
)
from cursed_words_solver.loadout import (
    parse_board_from_run_state,
    parse_run_state,
    prepare_run_state_dict_for_scoring,
)
from cursed_words_solver.rules.boss_effects import boss_word_constraints
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.quest_scoring import prune_cannot_beat_heap
from cursed_words_solver.search import WordSearcher, _CandidateHeap
from cursed_words_solver.ui.board_geometry import path_from_melmod_indices

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "round_logs"
    / "20260809_164104_wolf_xis_path_mismatch.json"
)
F8_SCORE = 139
SUBMITTED_SCORE = 156
# Queen → red rook → blue rook (stronger than submitted xis on this board).
QUEEN_ROOK_ROOK = [9, 19, 17]


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
    reason="wolf xis fixture and game wordlist required",
)
def test_chess_path_not_pruned_after_item_heap_fill():
    """Item-filled heap must not mult-prune a higher chess-only capture path."""
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    run_state = _f8_run_state_from_round_log(data)
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    assert board is not None and loadout is not None

    pipeline = ScoringPipeline()
    assert path_underbounded_by_tile_mult_lb(board, QUEEN_ROOK_ROOK)
    lb = mult_aware_lower_bound(board, QUEEN_ROOK_ROOK, loadout, pipeline.rules)
    # LB is far below real score — prune would fire without the chess exemption.
    assert prune_cannot_beat_heap(lb, float(F8_SCORE) + 40.0, loadout)

    searcher = WordSearcher(
        dictionary=WordDictionary(GAME_WORDLIST_PATH),
        min_len=3,
        max_len=3,
        time_budget=8.0,
        search_workers=1,
    )
    # Warm solve context / caches.
    _ = searcher.find_best_words(board, loadout, top_n=1)

    heap = _CandidateHeap(32)
    item_path = path_from_melmod_indices(board, data["solver"]["path"])
    heap.consider(181.76, "???", item_path, immediate=float(F8_SCORE))
    while len(heap) < 32:
        heap.consider(181.76, "???", item_path, immediate=float(F8_SCORE))

    rank = searcher._rank_score_for_candidate(
        board,
        QUEEN_ROOK_ROOK,
        "???",
        loadout,
        prune_heap=heap,
    )
    assert rank is not None
    assert rank > 181.76


@pytest.mark.skipif(
    not FIXTURE.exists() or not GAME_WORDLIST_PATH.exists(),
    reason="wolf xis fixture and game wordlist required",
)
def test_wolf_l3_search_beats_submitted_xis():
    """Full F8 search on Wolf max-len 3 must beat the weak jack-start suggestion."""
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    run_state = _f8_run_state_from_round_log(data)
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    assert board is not None and loadout is not None

    pipeline = ScoringPipeline()
    constraints = boss_word_constraints(loadout, pipeline.rules, default_max_len=25)
    # Live F8 used exact length 3 (Wolf stage max); encounter min may be lower.
    assert constraints.max_len >= 3

    searcher = WordSearcher(
        dictionary=WordDictionary(GAME_WORDLIST_PATH),
        min_len=3,
        max_len=3,
        time_budget=45.0,
        search_workers=1,
    )
    results = searcher.find_best_words(board, loadout, top_n=3)
    assert results
    best = results[0]
    assert int(best.score) >= SUBMITTED_SCORE, (
        f"best {best.word!r} {list(best.path)} scored {best.score}; "
        f"need >= submitted {SUBMITTED_SCORE} (F8 was {F8_SCORE})"
    )
