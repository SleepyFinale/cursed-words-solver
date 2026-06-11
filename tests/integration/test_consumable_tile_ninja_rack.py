"""Consumable rack + Tile Ninja integration (Sandy Saguaro encounter)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cursed_words_solver.consumable_placement import (
    _result_rank_score,
    consumable_investment_active,
    consumable_rack_tiles,
    rack_placement_search_active,
    remaining_rack_tiles,
    search_consumable_score_boost,
)
from cursed_words_solver.config import GAME_WORDLIST_PATH
from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.loadout import (
    parse_board_from_run_state,
    parse_run_state,
    prepare_run_state_dict_for_scoring,
)
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.scoring_conditions import placed_consumable_indices
from cursed_words_solver.search import WordSearcher

_FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "sandy_tile_ninja_rack.json"
)


def _load_fixture() -> dict:
    if not _FIXTURE.exists():
        pytest.skip("sandy_tile_ninja_rack.json fixture required")
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def test_sandy_rack_currency_tiles_map_to_letters():
    data = _load_fixture()
    loadout = parse_run_state(data)
    assert loadout is not None
    rack = consumable_rack_tiles(loadout)
    assert len(rack) == 5
    letters = {tile.letter for tile in rack}
    assert letters == {"G", "C", "U", "Y", "E"}


def test_sandy_rack_investment_and_placement_search_active():
    data = _load_fixture()
    loadout = parse_run_state(data)
    board = parse_board_from_run_state(data)
    assert loadout is not None
    assert board is not None
    rules = ScoringPipeline().rules
    assert consumable_investment_active(loadout)
    assert rack_placement_search_active(loadout, board, rules)
    assert len(remaining_rack_tiles(loadout, board)) == 5


@pytest.mark.skipif(
    not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024,
    reason="game wordlist required",
)
def test_sandy_rack_consumable_boost_can_place_currency_tile():
    data = _load_fixture()
    loadout = parse_run_state(data)
    board = parse_board_from_run_state(data)
    assert loadout is not None
    assert board is not None
    rules = ScoringPipeline().rules
    d = WordDictionary(GAME_WORDLIST_PATH)
    searcher = WordSearcher(
        dictionary=d,
        min_len=3,
        max_len=15,
        time_budget=4.0,
        setup_weight=0.4,
    )
    baseline = searcher.find_best_words(board, loadout=loadout, top_n=1)
    assert baseline
    rack = remaining_rack_tiles(loadout, board)
    sim_board, records, boost = search_consumable_score_boost(
        searcher,
        board,
        loadout,
        rack,
        baseline_score=baseline[0].score,
        baseline_rank_score=baseline[0].rank_score or baseline[0].score,
        time_budget=4.0,
        top_n=3,
        rules=rules,
    )
    if not boost:
        pytest.skip("no consumable placement beat baseline on this fixture")
    assert records
    placed = {rec.letter for rec in records}
    assert placed.issubset({"G", "C", "U", "Y", "E"})
    assert len(placed_consumable_indices(sim_board)) == len(records)


_GRID11_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "mismatches"
    / "20260610_191326.json"
)


@pytest.mark.skipif(
    not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024,
    reason="game wordlist required",
)
def test_grid11_consumable_boost_beats_plain_sequoia():
    """Grid 11 Sandy rack (number + currency) should adopt a placement when rank improves."""
    if not _GRID11_FIXTURE.is_file():
        pytest.skip("fixture 20260610_191326 not installed")
    data = json.loads(_GRID11_FIXTURE.read_text(encoding="utf-8"))
    run_state = prepare_run_state_dict_for_scoring(data["run_state_snapshot"])
    loadout = parse_run_state(run_state)
    board = parse_board_from_run_state(run_state)
    assert loadout is not None
    assert board is not None
    rules = ScoringPipeline().rules
    d = WordDictionary(GAME_WORDLIST_PATH)
    searcher = WordSearcher(
        dictionary=d,
        min_len=3,
        max_len=25,
        time_budget=10.0,
        setup_weight=0.4,
        search_workers=1,
    )
    baseline = searcher.find_best_words(board, loadout=loadout, top_n=1)
    assert baseline
    baseline_rank = _result_rank_score(baseline[0])
    rack = remaining_rack_tiles(loadout, board)
    assert len(rack) == 5
    sim_board, records, boost = search_consumable_score_boost(
        searcher,
        board,
        loadout,
        rack,
        baseline_score=baseline[0].score,
        baseline_rank_score=baseline_rank,
        time_budget=10.0,
        top_n=3,
        rules=rules,
    )
    assert boost
    assert records
    assert _result_rank_score(boost[0]) > baseline_rank
    assert len(placed_consumable_indices(sim_board)) == len(records)
