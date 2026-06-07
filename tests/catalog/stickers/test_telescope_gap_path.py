"""Telescope running-red count: first-word gap bonus and multi-word historic prior."""

import json
from pathlib import Path

from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.scoring_conditions import (
    apply_snapshot_phased_session_extras,
    encounter_red_tiles_before_current_word,
    telescope_running_red_count,
)
from cursed_words_solver.models import TileColor

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "mismatches"
CELLULATED = FIXTURES / "20260530_175032.json"
BASNETS = FIXTURES / "20260607_011541.json"
IMBLAZING = FIXTURES / "20260607_011738.json"
FETOSCOPIC = FIXTURES / "20260607_011836.json"


def _replay_score(fixture_path: Path) -> tuple[int, dict, list[int], object, object]:
    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    run_state = dict(data["run_state_snapshot"])
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    path = data["path"]
    apply_snapshot_phased_session_extras(loadout, board)
    score, _, _ = ScoringPipeline().score_with_trace(
        board, path, data["word"], loadout
    )
    return int(score), data, path, board, loadout


def _red_path_indices(board, path: list[int]) -> list[int]:
    return [
        i
        for i, idx in enumerate(path)
        if board.get_by_index(idx).color == TileColor.RED
    ]


def test_cellulated_telescope_gap_path_score():
    """Nat-H4: Snapshot L2 copying telescope; reds at path steps 0 and 4."""
    data = json.loads(CELLULATED.read_text(encoding="utf-8"))
    run_state = dict(data["run_state_snapshot"])
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    path = data["path"]
    apply_snapshot_phased_session_extras(loadout, board)
    score, _, trace = ScoringPipeline().score_with_trace(
        board, path, data["word"], loadout
    )
    assert int(score) == int(data["actual_score"]) == 80
    tele_steps = [
        s
        for s in (trace or [])
        if isinstance(s, dict)
        and s.get("rule_id") == "telescope"
        and s.get("effect_type") == "red_encounter_tile_bonus"
    ]
    assert tele_steps
    assert int(tele_steps[0]["subtotal"]) == 12


def test_telescope_gap_running_count_on_second_red():
    data = json.loads(CELLULATED.read_text(encoding="utf-8"))
    board = parse_board_from_run_state(data["run_state_snapshot"])
    loadout = parse_run_state(data["run_state_snapshot"])
    path = data["path"]
    red_indices = _red_path_indices(board, path)
    assert red_indices == [0, 4]
    assert telescope_running_red_count(loadout, board, path, red_indices[0]) == 1
    assert telescope_running_red_count(loadout, board, path, red_indices[1]) == 3


def test_basnets_telescope_prior_zero_without_red_tile_count():
    """Word 2: historic without red_tile_count must not use red_tiles_used_encounter."""
    data = json.loads(BASNETS.read_text(encoding="utf-8"))
    board = parse_board_from_run_state(data["run_state_snapshot"])
    loadout = parse_run_state(data["run_state_snapshot"])
    path = data["path"]
    assert encounter_red_tiles_before_current_word(loadout) == 0
    red_indices = _red_path_indices(board, path)
    assert red_indices == [4, 6]
    assert telescope_running_red_count(loadout, board, path, red_indices[0]) == 1
    assert telescope_running_red_count(loadout, board, path, red_indices[1]) == 2


def test_basnets_replay_score():
    score, data, *_ = _replay_score(BASNETS)
    assert score == int(data["actual_score"]) == -4


def test_imblazing_telescope_running_counts():
    data = json.loads(IMBLAZING.read_text(encoding="utf-8"))
    board = parse_board_from_run_state(data["run_state_snapshot"])
    loadout = parse_run_state(data["run_state_snapshot"])
    path = data["path"]
    assert encounter_red_tiles_before_current_word(loadout) == 2
    red_indices = _red_path_indices(board, path)
    assert red_indices == [0, 3]
    assert telescope_running_red_count(loadout, board, path, red_indices[0]) == 3
    assert telescope_running_red_count(loadout, board, path, red_indices[1]) == 4


def test_imblazing_replay_score():
    score, data, *_ = _replay_score(IMBLAZING)
    assert score == int(data["actual_score"]) == 12


def test_fetoscopic_telescope_running_counts():
    data = json.loads(FETOSCOPIC.read_text(encoding="utf-8"))
    board = parse_board_from_run_state(data["run_state_snapshot"])
    loadout = parse_run_state(data["run_state_snapshot"])
    path = data["path"]
    assert encounter_red_tiles_before_current_word(loadout) == 4
    red_indices = _red_path_indices(board, path)
    assert red_indices == [3, 6]
    assert telescope_running_red_count(loadout, board, path, red_indices[0]) == 5
    assert telescope_running_red_count(loadout, board, path, red_indices[1]) == 6


def test_fetoscopic_replay_score():
    score, data, *_ = _replay_score(FETOSCOPIC)
    assert score == int(data["actual_score"]) == 8
