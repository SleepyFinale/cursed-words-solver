"""Evaluate V(state) vs RolloutValueFn oracle."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from cursed_words_solver.sim.ml.train import TrainingSample
from cursed_words_solver.sim.ml.value_model import ValueModel
from cursed_words_solver.sim.search.rollout_value import RolloutValueFn


@dataclass
class ValueEvalReport:
    mae: float
    max_error: float
    n: int

    @property
    def ok(self) -> bool:
        return self.mae < 500.0


def evaluate_value_model(
    model: ValueModel,
    samples: list[TrainingSample],
    *,
    rollout_budget: float = 2.0,
) -> ValueEvalReport:
    oracle = RolloutValueFn()
    errors: list[float] = []
    for sample in samples:
        pred = model.predict(sample.state)
        if sample.label is not None:
            truth = sample.label
        else:
            truth = oracle(sample.state, budget_sec=rollout_budget)
        errors.append(abs(pred - truth))
    if not errors:
        return ValueEvalReport(mae=0.0, max_error=0.0, n=0)
    arr = np.array(errors)
    return ValueEvalReport(mae=float(np.mean(arr)), max_error=float(np.max(arr)), n=len(arr))
