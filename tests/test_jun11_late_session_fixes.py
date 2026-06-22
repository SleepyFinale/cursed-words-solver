"""Unit tests for Jun 11 late-session scoring fixes (Deep Sea, Dusty, void currency init)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cursed_words_solver.loadout import (
    parse_board_from_run_state,
    parse_run_state,
    prepare_run_state_dict_for_scoring,
)
from cursed_words_solver.models import Loadout
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.scoring_conditions import (
    dusty_coffin_void_units,
    explain_sticker_condition,
    grid_path_sticker_level,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "mismatches"


def test_lucky_scarf_grid3_scatter_uses_encounter_tier_two():
    """Grid 3 normal encounters: scattered Lucky Scarf scores at L2 (×3), not L1 (×2)."""
    loadout = Loadout(extras={"grid_number": "3"})
    assert grid_path_sticker_level(loadout, "lucky_scarf") == 2
    loadout_g1 = Loadout(extras={"grid_number": "1"})
    assert grid_path_sticker_level(loadout_g1, "lucky_scarf") == 1


def test_deep_sea_horror_non_boss_uses_max_equipped_level():
    """sagene: grid scatter L1 but equipped L3 → −30/tile on path voids."""
    data = json.loads((FIXTURES / "20260611_004335.json").read_text(encoding="utf-8"))
    board = parse_board_from_run_state(data["run_state_snapshot"])
    loadout = parse_run_state(data["run_state_snapshot"])
    assert board is not None and loadout is not None
    path = data["path"]
    grid_idx = next(
        i
        for i, idx in enumerate(path)
        if str((board.get_by_index(idx).metadata or {}).get("scattered_item_id") or "")
        == "deep_sea_horror"
    )
    level = grid_path_sticker_level(
        loadout,
        "deep_sea_horror",
        board=board,
        path=path,
        path_tile_index=grid_idx,
    )
    assert level == 3


def test_dusty_void_units_stiflings_fourteen():
    """stiflings: void currency F in word on path → off-path 14 only."""
    data = json.loads((FIXTURES / "20260611_004114.json").read_text(encoding="utf-8"))
    run_state = prepare_run_state_dict_for_scoring(data["run_state_snapshot"])
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    n = dusty_coffin_void_units(
        board,
        data["word"],
        loadout,
        applying_sticker_id="dusty_coffin",
        path=data["path"],
    )
    assert n == 14


def test_bento_skipped_when_path_first_letter_differs_from_word():
    """sagene path starts with T; dictionary starts with s — Bento does not apply."""
    data = json.loads((FIXTURES / "20260611_004335.json").read_text(encoding="utf-8"))
    board = parse_board_from_run_state(data["run_state_snapshot"])
    loadout = parse_run_state(data["run_state_snapshot"])
    met, detail = explain_sticker_condition(
        "word_starts_same_as_previous",
        board,
        data["path"],
        data["word"],
        loadout,
        applying_sticker_id="bento_box",
    )
    assert not met
    assert "path starts" in detail or "previous" in detail


@pytest.mark.parametrize(
    "stem",
    [
        "20260611_004000",
        "20260611_004114",
        "20260611_004335",
    ],
)
def test_jun11_late_mismatch_replay(stem: str) -> None:
    from tests.regression.test_scoring_mismatches import (
        _adjust_bento_previous_word_extras,
        _adjust_movie_camera_telescope_extras,
        _adjust_previous_word_letter_extras,
        _adjust_rare_item_count_extras,
        _adjust_scattered_item_level_from_trace,
        _adjust_void_penalty_from_trace,
        _bank_money_for_replay,
        _run_state_for_replay,
    )

    case_path = FIXTURES / f"{stem}.json"
    data = json.loads(case_path.read_text(encoding="utf-8"))
    run_state = _run_state_for_replay(data)
    assert run_state
    path = data["path"]
    word = data["word"]
    expected = int(data["actual_score"])

    _adjust_previous_word_letter_extras(run_state, data)
    _adjust_bento_previous_word_extras(run_state, data)
    _adjust_rare_item_count_extras(run_state, data)

    board = parse_board_from_run_state(run_state)
    _adjust_movie_camera_telescope_extras(run_state, data, board, path)
    board = parse_board_from_run_state(run_state)
    _adjust_void_penalty_from_trace(run_state, data, board, path)
    _adjust_scattered_item_level_from_trace(run_state, data, board, path)

    loadout = parse_run_state(run_state)
    replay_money = _bank_money_for_replay(data, board, path, loadout)
    if replay_money is not None:
        board.money = max(board.money, replay_money)
        loadout.money = max(loadout.money, replay_money)

    score, _ = ScoringPipeline().score(board, path, word, loadout)
    assert int(score) == expected
