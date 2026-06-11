"""Seeded RNG with isolated substreams for simulator transitions."""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass


@dataclass(frozen=True)
class SimRNG:
    """Root seed → deterministic substreams (scatter, boss_grid, capybara, …)."""

    root_seed: int
    step_index: int = 0

    def substream(self, name: str, *, material: str = "") -> random.Random:
        """Named substream; does not advance other streams."""
        payload = f"{self.root_seed}|{name}|{self.step_index}|{material}"
        digest = hashlib.sha256(payload.encode()).hexdigest()
        return random.Random(int(digest[:16], 16))

    def with_step(self, step_index: int) -> SimRNG:
        return SimRNG(root_seed=self.root_seed, step_index=step_index)

    @classmethod
    def from_run_seed(cls, run_seed: str | int | None, *, step_index: int = 0) -> SimRNG:
        if run_seed is None or run_seed == "":
            return cls(root_seed=0, step_index=step_index)
        if isinstance(run_seed, int):
            return cls(root_seed=run_seed & 0xFFFFFFFFFFFFFFFF, step_index=step_index)
        digest = hashlib.sha256(str(run_seed).encode()).hexdigest()
        return cls(root_seed=int(digest[:16], 16), step_index=step_index)
