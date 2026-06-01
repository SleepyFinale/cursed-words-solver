"""Snapshot copy level scales Tombstone void-adjacent scoring (Nat-H4 antiquey)."""

import json
from pathlib import Path

from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
from cursed_words_solver.rules.pipeline import ScoringPipeline

FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "mismatches"
    / "20260530_171744.json"
)


def _antiquey_loadout_without_steak(data: dict) -> tuple:
    run_state = data["run_state_snapshot"]
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    loadout.stamps = [s for s in loadout.stamps if s.id != "steak"]
    extras = dict(loadout.extras or {})
    extras.pop("steak_word_bonus_percent", None)
    loadout.extras = extras
    return board, loadout, data["path"], data["word"]


def test_snapshot_l2_copy_tombstone_antiquey_with_steak():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    run_state = data["run_state_snapshot"]
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    pipeline = ScoringPipeline()
    score, _ = pipeline.score(board, data["path"], data["word"], loadout)
    assert int(score) == int(data["actual_score"]) == 156


def test_snapshot_l2_copy_tombstone_tile_sum_before_steak():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    board, loadout, path, word = _antiquey_loadout_without_steak(data)
    pipeline = ScoringPipeline()
    score, _ = pipeline.score(board, path, word, loadout)
    assert score == 78


def test_snapshot_equipped_level_scales_tombstone_copy_on_fixture_board():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    board, loadout, path, word = _antiquey_loadout_without_steak(data)
    for sticker in loadout.stickers:
        if sticker.id == "snapshot":
            sticker.level = 1
    pipeline = ScoringPipeline()
    score_l1, _ = pipeline.score(board, path, word, loadout)
    for sticker in loadout.stickers:
        if sticker.id == "snapshot":
            sticker.level = 2
    score_l2, _ = pipeline.score(board, path, word, loadout)
    assert score_l1 == 58
    assert score_l2 == 78
    assert score_l2 - score_l1 == 20
