"""Dusty Coffin path-void exclusion + Yellow Glasses ITEM skip (Nat-H4 faraways)."""

import json
from pathlib import Path

from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.scoring_conditions import (
    dusty_coffin_void_units,
    has_consecutive_double_letter_on_path,
)

FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "mismatches"
    / "20260530_173834.json"
)


def test_faraways_robo_eel_score_with_steak():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    run_state = dict(data["run_state_snapshot"])
    from tests.regression.test_scoring_mismatches import _adjust_steak_percent_extras

    _adjust_steak_percent_extras(run_state, data)
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    pipeline = ScoringPipeline()
    score, _ = pipeline.score(board, data["path"], data["word"], loadout)
    assert int(score) == int(data["actual_score"]) == 54


def test_faraways_dusty_void_units_zero_when_only_void_on_path():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    board = parse_board_from_run_state(data["run_state_snapshot"])
    loadout = parse_run_state(data["run_state_snapshot"])
    path = data["path"]
    word = data["word"]
    assert (
        dusty_coffin_void_units(
            board,
            word,
            loadout,
            applying_sticker_id="dusty_coffin",
            path=path,
        )
        == 0
    )


def test_faraways_yellow_glasses_no_double_from_sticker_path_tiles():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    board = parse_board_from_run_state(data["run_state_snapshot"])
    path = data["path"]
    word = data["word"]
    assert not has_consecutive_double_letter_on_path(board, path, word)
