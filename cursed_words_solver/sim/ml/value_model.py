"""V(state) — linear value model (numpy, no sklearn required)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from cursed_words_solver.sim.ml.encoder import StateEncoder
from cursed_words_solver.sim.state import RunState


@dataclass
class ValueModel:
    """Predict expected encounter margin from encoded state."""

    encoder: StateEncoder = field(default_factory=StateEncoder)
    weights: np.ndarray | None = None
    bias: float = 0.0

    def _ensure_weights(self) -> np.ndarray:
        if self.weights is None:
            self.weights = np.zeros(self.encoder.feature_dim(), dtype=np.float64)
        return self.weights

    def predict(self, state: RunState, *, candidate_stats: dict | None = None) -> float:
        x = self.encoder.encode(state, candidate_stats=candidate_stats)
        w = self._ensure_weights()
        if w.shape != x.shape:
            w = np.zeros_like(x)
            self.weights = w
        return float(np.dot(w, x) + self.bias)

    def fit(self, xs: np.ndarray, ys: np.ndarray, *, ridge: float = 1e-4) -> None:
        """Ridge regression closed form."""
        if xs.ndim != 2 or len(xs) == 0:
            return
        n, d = xs.shape
        self.weights = np.zeros(d, dtype=np.float64)
        xtx = xs.T @ xs + ridge * np.eye(d)
        xty = xs.T @ ys
        self.weights = np.linalg.solve(xtx, xty)
        self.bias = float(np.mean(ys - xs @ self.weights))

    def save(self, path: Path) -> None:
        path.write_text(
            json.dumps(
                {
                    "weights": self._ensure_weights().tolist(),
                    "bias": self.bias,
                    "feature_dim": self.encoder.feature_dim(),
                }
            ),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: Path) -> ValueModel:
        data = json.loads(path.read_text(encoding="utf-8"))
        model = cls()
        model.weights = np.array(data["weights"], dtype=np.float64)
        model.bias = float(data.get("bias", 0))
        return model
