"""Snapshot copy level scales Down Under tile_multiply (Nat-H4 nonjury)."""

import json
from pathlib import Path

from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.scoring_conditions import grid_path_sticker_level

FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "mismatches"
    / "20260530_172925.json"
)


def _nonjury_loadout_without_steak(data: dict) -> tuple:
    run_state = data["run_state_snapshot"]
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    loadout.stamps = [s for s in loadout.stamps if s.id != "steak"]
    extras = dict(loadout.extras or {})
    extras.pop("steak_word_bonus_percent", None)
    loadout.extras = extras
    return board, loadout, data["path"], data["word"]


def test_snapshot_l2_copy_down_under_nonjury_with_steak():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    run_state = data["run_state_snapshot"]
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    pipeline = ScoringPipeline()
    score, _ = pipeline.score(board, data["path"], data["word"], loadout)
    assert int(score) == int(data["actual_score"]) == 450


def test_grid_down_under_uses_scattered_level_not_snapshot_level():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    run_state = data["run_state_snapshot"]
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    path = data["path"]
    down_under_path_index = path.index(19)
    assert (
        grid_path_sticker_level(
            loadout,
            "down_under",
            board=board,
            path=path,
            path_tile_index=down_under_path_index,
        )
        == 1
    )


def test_snapshot_equipped_level_scales_down_under_copy_not_grid():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    board, loadout, path, word = _nonjury_loadout_without_steak(data)
    pipeline = ScoringPipeline()
    for sticker in loadout.stickers:
        if sticker.id == "snapshot":
            sticker.level = 1
    score_l1, _ = pipeline.score(board, path, word, loadout)
    for sticker in loadout.stickers:
        if sticker.id == "snapshot":
            sticker.level = 2
    score_l2, _ = pipeline.score(board, path, word, loadout)
    assert score_l1 == 135
    assert score_l2 == 225
    assert score_l2 - score_l1 == 90
