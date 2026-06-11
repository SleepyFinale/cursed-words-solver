"""AlphaZero-style self-play loop (π + V + MCTS)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from cursed_words_solver.sim.ml.policy_model import PolicyModel
from cursed_words_solver.sim.ml.value_model import ValueModel
from cursed_words_solver.sim.search.mcts import mcts_select_encounter
from cursed_words_solver.sim.search.rollout_value import RolloutValueFn
from cursed_words_solver.sim.state import RunState


@dataclass
class SelfPlayRecord:
    state: RunState
    visit_distribution: list[int]
    outcome: float


@dataclass
class AlphaZeroTrainer:
    value_model: ValueModel = field(default_factory=ValueModel)
    policy_model: PolicyModel = field(default_factory=PolicyModel)
    pool_size: int = 100

    def play_episode(
        self,
        state: RunState,
        *,
        budget_sec: float = 10.0,
        mcts_iterations: int = 50,
    ) -> SelfPlayRecord:
        priors = self.policy_model.priors(state, self.pool_size)
        fast_value = RolloutValueFn(pool_size=20, rollout_time_budget=1.0)

        result = mcts_select_encounter(
            state,
            pool_size=self.pool_size,
            iterations=mcts_iterations,
            budget_sec=budget_sec,
            policy_priors=priors,
            value_fn=fast_value,
        )

        outcome = fast_value(state, budget_sec=1.0)
        visits = result.visits or [0]
        return SelfPlayRecord(
            state=state.clone(),
            visit_distribution=visits,
            outcome=outcome,
        )

    def train_step(self, records: list[SelfPlayRecord], *, lr: float = 0.01) -> None:
        xs = []
        ys = []
        for rec in records:
            xs.append(self.value_model.encoder.encode(rec.state))
            ys.append(rec.outcome)
            self.policy_model.fit_visit_distribution(rec.state, rec.visit_distribution, lr=lr)

        if xs:
            import numpy as np

            self.value_model.fit(np.stack(xs), np.array(ys, dtype=np.float64))

    def run_self_play(
        self,
        initial_states: list[RunState],
        *,
        episodes: int = 10,
        budget_sec: float = 5.0,
    ) -> list[SelfPlayRecord]:
        records: list[SelfPlayRecord] = []
        deadline = time.perf_counter() + budget_sec * episodes
        for i in range(episodes):
            if time.perf_counter() >= deadline:
                break
            state = initial_states[i % len(initial_states)]
            records.append(self.play_episode(state, budget_sec=budget_sec / max(1, episodes)))
        if records:
            self.train_step(records)
        return records
