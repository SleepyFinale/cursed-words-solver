"""Stage 3–4 ML smoke tests."""

from __future__ import annotations

import numpy as np

from cursed_words_solver.models import Board, Loadout, Tile, TileColor, CurseType
from cursed_words_solver.sim.ml.alphazero import AlphaZeroTrainer
from cursed_words_solver.sim.ml.encoder import StateEncoder
from cursed_words_solver.sim.ml.policy_model import PolicyModel
from cursed_words_solver.sim.ml.train import TrainingSample, train_value_model
from cursed_words_solver.sim.ml.value_model import ValueModel
from cursed_words_solver.sim.state import RunState


def _state(target: int) -> RunState:
    tiles = [
        [
            Tile(row=r, col=c, char="a", letter="A", base_score=10, color=TileColor.SHINY, curse=CurseType.LETTER)
            for c in range(5)
        ]
        for r in range(5)
    ]
    return RunState(
        board=Board(tiles=tiles),
        loadout=Loadout(extras={"encounter_remaining_target": str(target), "grids_remaining": "2"}),
    )


def test_encoder_fixed_dim():
    enc = StateEncoder()
    vec = enc.encode(_state(100))
    assert vec.shape == (enc.feature_dim(),)


def test_value_model_fit_predict():
    samples = [
        TrainingSample(_state(100), 50.0),
        TrainingSample(_state(200), -20.0),
        TrainingSample(_state(50), 80.0),
    ]
    model = train_value_model(samples)
    pred = model.predict(_state(100))
    assert isinstance(pred, float)


def test_policy_priors_sum_to_one():
    model = PolicyModel(max_candidates=10)
    state = _state(100)
    priors = model.priors(state, pool_size=5)
    assert len(priors) == 5
    assert abs(sum(priors) - 1.0) < 1e-6


def test_alphazero_trainer_smoke():
    trainer = AlphaZeroTrainer(pool_size=5)
    states = [_state(100), _state(200)]
    records = trainer.run_self_play(states, episodes=2, budget_sec=3.0)
    assert isinstance(records, list)
