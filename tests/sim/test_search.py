"""Stage 2 search smoke tests."""

from __future__ import annotations

import pytest

from cursed_words_solver.models import Board, Loadout, Tile, TileColor, CurseType
from cursed_words_solver.sim.search.candidate_gen import DEFAULT_POOL_SIZE
from cursed_words_solver.sim.search.planner import EncounterPlanner, SearchAlgorithm
from cursed_words_solver.sim.search.rollout_value import RolloutValueFn
from cursed_words_solver.sim.state import RunState


def _tiny_board() -> Board:
    tiles = [
        [
            Tile(row=r, col=c, char="a", letter="A", base_score=10, color=TileColor.SHINY, curse=CurseType.LETTER)
            for c in range(5)
        ]
        for r in range(5)
    ]
    return Board(tiles=tiles)


@pytest.mark.slow
def test_planner_greedy_returns_submission():
    loadout = Loadout(extras={"encounter_remaining_target": "200", "grids_remaining": "1"})
    state = RunState(board=_tiny_board(), loadout=loadout, run_seed=0)
    planner = EncounterPlanner(pool_size=10)
    result = planner.plan(state, algorithm=SearchAlgorithm.GREEDY, budget_sec=5.0)
    if result.submission is None:
        pytest.skip("no dictionary/word found in CI environment")
    assert result.submission.word


def test_rollout_value_fn_callable():
    loadout = Loadout(extras={"encounter_remaining_target": "100", "grids_remaining": "1"})
    state = RunState(board=_tiny_board(), loadout=loadout)
    fn = RolloutValueFn(pool_size=5, rollout_time_budget=0.5)
    v = fn(state, budget_sec=1.0)
    assert isinstance(v, float)


def test_default_pool_size_is_500():
    assert DEFAULT_POOL_SIZE == 500
