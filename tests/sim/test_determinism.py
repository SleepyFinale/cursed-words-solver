"""Determinism gate: same seed + inputs → same outputs."""

from __future__ import annotations

import json

from cursed_words_solver.models import Board, Loadout, Tile, TileColor, CurseType
from cursed_words_solver.sim.effect_engine import EffectEngine
from cursed_words_solver.sim.encounter_engine import EncounterEngine
from cursed_words_solver.sim.reward_engine import RewardEngine, RewardResult
from cursed_words_solver.sim.rng import SimRNG
from cursed_words_solver.sim.state import RunState
from cursed_words_solver.sim.submission import Submission


def _board() -> Board:
    tiles = [
        [
            Tile(row=r, col=c, char="x", letter="X", base_score=5, color=TileColor.SHINY, curse=CurseType.LETTER)
            for c in range(5)
        ]
        for r in range(5)
    ]
    return Board(tiles=tiles)


def test_encounter_step_deterministic():
    loadout = Loadout(
        stickers=[],
        stamps=[],
        extras={
            "encounter_remaining_target": "500",
            "grids_remaining": "2",
            "grid_number": "1",
        },
    )
    state = RunState(board=_board(), loadout=loadout, run_seed=42)
    sub = Submission(word="xx", path=[0, 1])

    def run_once():
        engine = EncounterEngine()
        rng = SimRNG.from_run_seed(42)
        step = engine.step(state.clone(), sub, rng, advance_grid=False)
        return json.dumps(step.state.to_canonical_dict(), sort_keys=True)

    assert run_once() == run_once()


def test_effect_engine_post_submit_target():
    loadout = Loadout(extras={"encounter_remaining_target": "100", "grids_remaining": "2"})
    state = RunState(board=_board(), loadout=loadout, run_seed=1)
    sub = Submission(word="ab", path=[0, 1])
    reward = RewardResult(score=30, trace=[])
    eff = EffectEngine()
    next_state = eff.apply_post_submit(state, sub, reward)
    assert next_state.encounter_remaining_target == 70
