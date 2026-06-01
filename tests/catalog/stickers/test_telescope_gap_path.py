"""Telescope running-red gap bonus when reds are separated on the word path."""

import json
from pathlib import Path

from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.scoring_conditions import (
    apply_snapshot_phased_session_extras,
    telescope_running_red_count,
)

FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "mismatches"
    / "20260530_175032.json"
)


def test_cellulated_telescope_gap_path_score():
    """Nat-H4: Snapshot L2 copying telescope; reds at path steps 0 and 4."""
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
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
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    board = parse_board_from_run_state(data["run_state_snapshot"])
    loadout = parse_run_state(data["run_state_snapshot"])
    path = data["path"]
    red_indices = [
        i
        for i, idx in enumerate(path)
        if board.get_by_index(idx).color.value == "red"
    ]
    assert red_indices == [0, 4]
    assert telescope_running_red_count(loadout, board, path, red_indices[0]) == 1
    assert telescope_running_red_count(loadout, board, path, red_indices[1]) == 3
