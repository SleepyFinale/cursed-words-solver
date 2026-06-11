"""Unit tests for Jun 11 session scoring fixes (Dusty Coffin, Down Under)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cursed_words_solver.loadout import (
    encounter_implies_active_boss,
    encounter_missing_boss_should_warn,
    parse_board_from_run_state,
    parse_run_state,
    prepare_run_state_dict_for_scoring,
)
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.scoring_conditions import (
    dusty_coffin_void_units,
    grid_path_sticker_level,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "mismatches"


def test_encounter_first_does_not_warn_missing_boss():
    data = json.loads((FIXTURES / "20260611_001830.json").read_text(encoding="utf-8"))
    loadout = parse_run_state(data["run_state_snapshot"])
    assert not encounter_implies_active_boss(loadout)
    assert not encounter_missing_boss_should_warn(loadout)


def test_boss_node_with_boss_id_does_not_warn():
    data = json.loads((FIXTURES / "20260610_235237.json").read_text(encoding="utf-8"))
    loadout = parse_run_state(data["run_state_snapshot"])
    assert encounter_implies_active_boss(loadout)
    assert not encounter_missing_boss_should_warn(loadout)


def test_down_under_non_boss_uses_max_equipped_level():
    """borsics: grid scatter L1 but equipped L3 → ×-7 on path."""
    data = json.loads((FIXTURES / "20260611_001830.json").read_text(encoding="utf-8"))
    board = parse_board_from_run_state(data["run_state_snapshot"])
    loadout = parse_run_state(data["run_state_snapshot"])
    assert board is not None and loadout is not None
    path = data["path"]
    grid_idx = next(
        i
        for i, idx in enumerate(path)
        if str((board.get_by_index(idx).metadata or {}).get("scattered_item_id") or "")
        == "down_under"
    )
    level = grid_path_sticker_level(
        loadout,
        "down_under",
        board=board,
        path=path,
        path_tile_index=grid_idx,
    )
    assert level == 3


def test_dusty_void_units_rok_eighteen():
    """rok: 18 void units at L3 (432 word bonus before Ornate)."""
    data = json.loads((FIXTURES / "20260611_002049.json").read_text(encoding="utf-8"))
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
    assert n == 18


def test_dusty_void_units_bethankit_fifteen():
    """bethankit: shiny dusty face + path void numbers/letters."""
    data = json.loads((FIXTURES / "20260611_002223.json").read_text(encoding="utf-8"))
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
    assert n == 15


@pytest.mark.parametrize(
    "stem",
    [
        "20260611_001830",
        "20260611_002049",
        "20260611_002223",
    ],
)
def test_jun11_mismatch_replay(stem: str) -> None:
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
