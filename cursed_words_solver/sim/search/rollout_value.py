"""RolloutValueFn — oracle encounter value from simulation."""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum

from cursed_words_solver.sim.encounter_engine import EncounterEngine
from cursed_words_solver.sim.rng import SimRNG
from cursed_words_solver.sim.search.base import submission_from_word_result
from cursed_words_solver.sim.search.candidate_gen import generate_candidate_pool
from cursed_words_solver.sim.state import RunState


class RolloutObjective(str, Enum):
    MARGIN = "margin"
    WIN_PROB = "win_prob"


@dataclass
class RolloutValueFn:
    """Expected encounter strength via greedy rollouts (Stage 2 oracle)."""

    objective: RolloutObjective = RolloutObjective.MARGIN
    pool_size: int = 50
    rollout_time_budget: float = 2.0
    encounter_engine: EncounterEngine | None = None

    def __post_init__(self) -> None:
        if self.encounter_engine is None:
            self.encounter_engine = EncounterEngine()

    def __call__(self, state: RunState, budget_sec: float = 0.0) -> float:
        deadline = time.perf_counter() + budget_sec if budget_sec > 0 else None
        return self.evaluate(state, deadline=deadline)

    def evaluate(
        self,
        state: RunState,
        *,
        deadline: float | None = None,
    ) -> float:
        if state.encounter_won:
            return float(state.encounter_score_earned - max(0, state.encounter_remaining_target))
        if state.encounter_lost:
            return float(-state.encounter_remaining_target)

        remaining_budget = self.rollout_time_budget
        if deadline is not None:
            remaining_budget = min(remaining_budget, max(0.0, deadline - time.perf_counter()))

        sim_state = state.clone()
        total_margin = 0.0
        grids_simulated = 0
        max_grids = max(1, sim_state.grids_remaining + 1)

        while grids_simulated < max_grids:
            if sim_state.encounter_won or sim_state.encounter_lost:
                break
            if deadline is not None and time.perf_counter() >= deadline:
                break

            pool = generate_candidate_pool(
                sim_state,
                pool_size=min(self.pool_size, 20),
                time_budget_sec=min(remaining_budget, 3.0),
            )
            if not pool.results:
                break

            best = pool.results[0]
            submission = submission_from_word_result(best)
            rng = SimRNG.from_run_seed(sim_state.run_seed, step_index=sim_state.step_index)
            step = self.encounter_engine.step(sim_state, submission, rng)
            sim_state = step.state
            grids_simulated += 1

        if sim_state.encounter_won:
            margin = -sim_state.encounter_remaining_target
        elif sim_state.encounter_lost:
            margin = -sim_state.encounter_remaining_target
        else:
            earned = sim_state.encounter_score_earned
            target = sim_state.encounter_remaining_target + earned
            margin = earned - target

        if self.objective == RolloutObjective.WIN_PROB:
            return 1.0 if margin >= 0 else 0.0
        return float(margin)
