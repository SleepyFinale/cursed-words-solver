"""Footprints sticker — non-adjacent move counting (GridUtilitySingleton.AreAdjacentTiles)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
from cursed_words_solver.models import Board, CurseType, Loadout, LoadoutItem, Tile, TileColor
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.scoring_conditions import (
    _path_step_adjacent,
    non_adjacent_step_count,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "mismatches"

PIANOLIST_PATH = [3, 4, 0, 6, 1, 5, 14, 13, 18]
DEMEANING_PATH = [19, 24, 21, 17, 11, 6, 1, 0, 3]


def _tile(
    row: int,
    col: int,
    ch: str,
    score: int,
    *,
    color=TileColor.COLORLESS,
    curse=CurseType.LETTER,
) -> Tile:
    return Tile(
        row=row,
        col=col,
        char=ch,
        letter=ch,
        base_score=score,
        color=color,
        curse=curse,
        metadata={"source": "melmod"},
    )


def _empty_board() -> Board:
    grid = [[_tile(r, c, "X", 1) for c in range(5)] for r in range(5)]
    return Board(tiles=grid, money=0)


def test_path_step_adjacent_eight_directional() -> None:
    assert _path_step_adjacent(0, 1)
    assert _path_step_adjacent(0, 6)
    assert not _path_step_adjacent(0, 0)
    assert not _path_step_adjacent(0, 2)
    assert not _path_step_adjacent(0, 10)


def test_non_adjacent_step_count_pianolist_and_demeaning() -> None:
    assert non_adjacent_step_count(PIANOLIST_PATH) == 2
    assert non_adjacent_step_count(DEMEANING_PATH) == 2


def test_non_adjacent_step_count_three_skips_triggers_footprints_threshold() -> None:
    assert non_adjacent_step_count([0, 2, 4, 6]) == 3


def test_footprints_positive_on_four_tile_skips() -> None:
    board = _empty_board()
    for idx in (0, 2, 4, 6):
        r, c = divmod(idx, 5)
        board.tiles[r][c] = _tile(r, c, "A", 10)
    path = [0, 2, 4, 6]
    loadout = Loadout(
        stickers=[LoadoutItem(id="footprints", name="Footprints", level=1, kind="sticker")]
    )
    pipeline = ScoringPipeline()
    base, _ = pipeline.score(board, path, "aaaa", Loadout())
    score, bd = pipeline.score(board, path, "aaaa", loadout)
    assert bd["multiplier"] == 2.0
    assert score == base * 2


def _replay_fixture(stem: str) -> tuple[int, str, list[int]]:
    case_path = FIXTURES / f"{stem}.json"
    if not case_path.is_file():
        pytest.skip(f"fixture {stem} not installed")
    data = json.loads(case_path.read_text(encoding="utf-8"))
    run_state = data.get("run_state_snapshot") or data.get("run_state")
    if not run_state:
        pytest.fail(f"{stem}: missing run_state snapshot")
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    score, _ = ScoringPipeline().score(board, data["path"], data["word"], loadout)
    return int(score), data["word"], data["path"]


def test_pianolist_footprints_mismatch_replay_matches_actual() -> None:
    score, word, path = _replay_fixture("20260616_120856")
    assert word == "pianolist"
    assert path == PIANOLIST_PATH
    assert score == 47


def test_demeaning_footprints_mismatch_replay_matches_actual() -> None:
    score, word, path = _replay_fixture("20260616_121049")
    assert word == "demeaning"
    assert path == DEMEANING_PATH
    assert score == 41
