"""Train V(state) from Stage 2 rollout labels."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from cursed_words_solver.sim.ml.encoder import StateEncoder
from cursed_words_solver.sim.ml.value_model import ValueModel
from cursed_words_solver.sim.search.rollout_value import RolloutValueFn
from cursed_words_solver.sim.state import RunState


@dataclass
class TrainingSample:
    state: RunState
    label: float


def labels_from_rollout(
    states: list[RunState],
    *,
    budget_sec: float = 1.0,
) -> list[float]:
    fn = RolloutValueFn()
    return [fn(s, budget_sec=budget_sec) for s in states]


def train_value_model(
    samples: list[TrainingSample],
    *,
    ridge: float = 1e-4,
) -> ValueModel:
    encoder = StateEncoder()
    xs = np.stack([encoder.encode(s.state) for s in samples])
    ys = np.array([s.label for s in samples], dtype=np.float64)
    model = ValueModel(encoder=encoder)
    model.fit(xs, ys, ridge=ridge)
    return model


def export_label_dataset(path: Path, samples: list[TrainingSample]) -> None:
    rows = []
    for s in samples:
        rows.append(
            {
                "label": s.label,
                "extras": dict(s.state.extras),
                "encounter_remaining_target": s.state.encounter_remaining_target,
                "grids_remaining": s.state.grids_remaining,
            }
        )
    path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
