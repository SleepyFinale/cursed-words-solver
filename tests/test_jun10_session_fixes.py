"""Unit tests for Jun 10 session scoring fixes (Bento, Tombstone, Down Under)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.scoring_conditions import (
    explain_sticker_condition,
    grid_path_sticker_level,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "mismatches"


def test_bento_not_uses_dictionary_first_letter():
    data = json.loads((FIXTURES / "20260610_235307.json").read_text(encoding="utf-8"))
    board = parse_board_from_run_state(data["run_state_snapshot"])
    loadout = parse_run_state(data["run_state_snapshot"])
    assert board is not None
    met, detail = explain_sticker_condition(
        "word_starts_same_as_previous",
        board,
        data["path"],
        data["word"],
        loadout,
        applying_sticker_id="bento_box",
    )
    assert not met
    assert "not" in detail or "'n'" in detail


def test_bento_caskier_uses_dictionary_first_letter():
    data = json.loads((FIXTURES / "20260610_235822.json").read_text(encoding="utf-8"))
    board = parse_board_from_run_state(data["run_state_snapshot"])
    loadout = parse_run_state(data["run_state_snapshot"])
    assert board is not None
    met, _ = explain_sticker_condition(
        "word_starts_same_as_previous",
        board,
        data["path"],
        data["word"],
        loadout,
        applying_sticker_id="bento_box",
    )
    assert not met


def test_tombstone_grid_path_merges_equipped_under_floor_mod():
    data = json.loads((FIXTURES / "20260610_235200.json").read_text(encoding="utf-8"))
    board = parse_board_from_run_state(data["run_state_snapshot"])
    loadout = parse_run_state(data["run_state_snapshot"])
    assert board is not None and loadout is not None
    path = data["path"]
    grid_idx = next(
        i
        for i, idx in enumerate(path)
        if str((board.get_by_index(idx).metadata or {}).get("scattered_item_id") or "")
        == "tombstone"
    )
    level = grid_path_sticker_level(
        loadout,
        "tombstone",
        board=board,
        path=path,
        path_tile_index=grid_idx,
    )
    assert level >= 3


def test_down_under_uses_grid_scattered_items_level():
    data = json.loads((FIXTURES / "20260610_231902.json").read_text(encoding="utf-8"))
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
    assert level == 1


@pytest.mark.parametrize(
    "stem",
    [
        "20260610_231902",
        "20260610_232947",
        "20260610_235035",
        "20260610_235200",
        "20260610_235237",
        "20260610_235307",
    ],
)
def test_jun10_replay_without_bento_overpredict(stem: str) -> None:
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
