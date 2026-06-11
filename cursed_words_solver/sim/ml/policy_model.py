"""π(state) — softmax over top-500 candidate indices."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from cursed_words_solver.sim.ml.encoder import StateEncoder
from cursed_words_solver.sim.state import RunState


@dataclass
class PolicyModel:
    """Policy priors over fixed candidate pool indices."""

    encoder: StateEncoder = field(default_factory=lambda: StateEncoder(include_candidate_stats=True))
    max_candidates: int = 500
    weights: np.ndarray | None = None

    def _ensure_weights(self) -> np.ndarray:
        d = self.encoder.feature_dim()
        if self.weights is None:
            self.weights = np.zeros((self.max_candidates, d), dtype=np.float64)
        return self.weights

    def priors(
        self,
        state: RunState,
        pool_size: int,
        *,
        candidate_stats: dict | None = None,
        temperature: float = 1.0,
    ) -> list[float]:
        n = min(pool_size, self.max_candidates)
        if n <= 0:
            return []
        x = self.encoder.encode(state, candidate_stats=candidate_stats)
        w = self._ensure_weights()[:n]
        logits = w @ x
        logits = logits - np.max(logits)
        exp = np.exp(logits / max(1e-6, temperature))
        probs = exp / np.sum(exp)
        return [float(p) for p in probs]

    def fit_visit_distribution(
        self,
        state: RunState,
        visits: list[int],
        *,
        lr: float = 0.01,
    ) -> None:
        """One SGD step toward normalized visit counts."""
        n = len(visits)
        if n == 0:
            return
        total = sum(visits)
        if total <= 0:
            return
        target = np.array([v / total for v in visits], dtype=np.float64)
        x = self.encoder.encode(state)
        w = self._ensure_weights()
        for i in range(min(n, self.max_candidates)):
            pred = 1.0 / n
            w[i] += lr * (target[i] - pred) * x

    def save(self, path: Path) -> None:
        path.write_text(
            json.dumps(
                {
                    "weights": self._ensure_weights().tolist(),
                    "max_candidates": self.max_candidates,
                }
            ),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: Path) -> PolicyModel:
        data = json.loads(path.read_text(encoding="utf-8"))
        model = cls(max_candidates=int(data.get("max_candidates", 500)))
        model.weights = np.array(data["weights"], dtype=np.float64)
        return model
