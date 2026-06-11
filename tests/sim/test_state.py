"""RunState and Submission tests."""

from __future__ import annotations

import json

from cursed_words_solver.models import Board, Loadout, Tile, TileColor, CurseType
from cursed_words_solver.sim.rng import SimRNG
from cursed_words_solver.sim.state import RunState
from cursed_words_solver.sim.submission import Submission


def _minimal_board() -> Board:
    tiles = [
        [
            Tile(
                row=r,
                col=c,
                char="a",
                letter="A",
                base_score=10,
                color=TileColor.SHINY,
                curse=CurseType.LETTER,
            )
            for c in range(5)
        ]
        for r in range(5)
    ]
    return Board(tiles=tiles)


def test_run_state_canonical_deterministic():
    loadout = Loadout(extras={"encounter_remaining_target": "100", "grids_remaining": "2"})
    state = RunState(board=_minimal_board(), loadout=loadout, run_seed="test-seed")
    a = json.dumps(state.to_canonical_dict(), sort_keys=True)
    b = json.dumps(state.clone().to_canonical_dict(), sort_keys=True)
    assert a == b


def test_rng_substream_isolated():
    a = SimRNG.from_run_seed("seed", step_index=0)
    b = SimRNG.from_run_seed("seed", step_index=0)
    assert a.substream("scatter").random() == b.substream("scatter").random()
    assert a.substream("scatter").random() != a.substream("boss_grid").random()


def test_submission_from_round_log():
    data = {
        "actual": {"word": "cat", "path": [0, 1, 2], "score": 10},
        "submit_method": "EncounterController.SubmitWord",
    }
    sub = Submission.from_round_log(data)
    assert sub is not None
    assert sub.word == "cat"
    assert sub.path == [0, 1, 2]
