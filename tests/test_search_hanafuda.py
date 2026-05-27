"""Search + scoring for multi-joker Hanafuda paths (464 vs 2554 regression)."""

import json
from pathlib import Path

from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.encounter_board import effective_board_for_loadout
from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.scoring_conditions import (
    hanafuda_hand_satisfied,
    unused_cards_on_board,
)
from cursed_words_solver.rules.stamp_behaviors import stamp_search_flags
from cursed_words_solver.search import WordSearcher, physical_word_for_path

_LOCAL_FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "mismatches"
    / "ayms_board_snapshot.json"
)


def _ayms_snapshot() -> dict:
    if _LOCAL_FIXTURE.is_file():
        return json.loads(_LOCAL_FIXTURE.read_text(encoding="utf-8"))
    path = Path.home() / ".cursed_words_solver" / "last_suggestion.json"
    if not path.is_file():
        raise FileNotFoundError("need last_suggestion.json or tests/fixtures/mismatches/ayms_board_snapshot.json")
    return json.loads(path.read_text(encoding="utf-8"))["run_state_snapshot"]


def _board_and_loadout():
    snap = _ayms_snapshot()
    board = parse_board_from_run_state(snap)
    assert board is not None
    loadout = parse_run_state(snap)
    loadout.extras.update(snap.get("extras") or {})
    pipeline = ScoringPipeline()
    board = effective_board_for_loadout(board, loadout, pipeline.rules)
    return board, loadout, pipeline


def test_ayms_path_hanafuda_hand_and_score():
    board, loadout, pipeline = _board_and_loadout()
    path = [21, 22, 23, 17, 18, 19]
    flags = stamp_search_flags(loadout)
    word = physical_word_for_path(board, path, flags=flags)
    assert hanafuda_hand_satisfied(board, path, 2)
    assert unused_cards_on_board(board, path) >= 17
    score, bd = pipeline.score(board, path, word, loadout)
    effects = " ".join(bd["pipeline"]["effects"])
    assert "three_of_a_kind" in effects and "unused" in effects
    assert score == 2554


def test_search_finds_ayms_over_short_edh():
    board, loadout, _ = _board_and_loadout()
    dictionary = WordDictionary()
    searcher = WordSearcher(
        dictionary=dictionary,
        min_len=3,
        max_len=12,
        time_budget=12.0,
        search_workers=1,
        use_fast_rank=False,
    )
    results = searcher.find_best_words(board, loadout, top_n=3)
    assert results
    best = results[0]
    assert best.score >= 2500
    assert hanafuda_hand_satisfied(board, best.path, 2)
    effects = " ".join(best.breakdown["pipeline"]["effects"])
    assert "three_of_a_kind" in effects and "unused" in effects
