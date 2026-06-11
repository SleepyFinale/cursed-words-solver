"""Stage 5 full-run smoke test."""

from __future__ import annotations

from cursed_words_solver.models import Board, Loadout, Tile, TileColor, CurseType
from cursed_words_solver.sim.run import FullRunSimulator, RunPhase
from cursed_words_solver.sim.state import RunState


def _board() -> Board:
    tiles = [
        [
            Tile(row=r, col=c, char="a", letter="A", base_score=10, color=TileColor.SHINY, curse=CurseType.LETTER)
            for c in range(5)
        ]
        for r in range(5)
    ]
    return Board(tiles=tiles)


def test_full_run_simulator_smoke():
    loadout = Loadout(
        money=10,
        extras={
            "encounter_remaining_target": "50",
            "grids_remaining": "1",
        },
    )
    state = RunState(board=_board(), loadout=loadout, run_seed=1)
    sim = FullRunSimulator(max_encounters=1)
    result = sim.simulate_run(state, seed=1)
    assert result.areas_cleared >= 0
    assert RunPhase.DONE.value in result.phases or "encounter" in result.phases

