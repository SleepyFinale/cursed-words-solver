"""EncounterPlanner — unified Stage 2 search entry point."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from cursed_words_solver.sim.search.beam import beam_search_encounter
from cursed_words_solver.sim.search.evolutionary import evolutionary_search_encounter
from cursed_words_solver.sim.search.mcts import mcts_select_encounter
from cursed_words_solver.sim.search.rollout_value import RolloutValueFn
from cursed_words_solver.sim.state import RunState
from cursed_words_solver.sim.submission import Submission


class SearchAlgorithm(str, Enum):
    BEAM = "beam"
    MCTS = "mcts"
    EVOLUTIONARY = "evo"
    GREEDY = "greedy"


@dataclass
class PlanResult:
    submission: Submission | None
    value: float
    algorithm: str


class EncounterPlanner:
    def __init__(
        self,
        *,
        pool_size: int = 500,
        value_fn: RolloutValueFn | None = None,
        policy_priors: list[float] | None = None,
    ) -> None:
        self.pool_size = pool_size
        self.value_fn = value_fn or RolloutValueFn()
        self.policy_priors = policy_priors

    def plan(
        self,
        state: RunState,
        algorithm: SearchAlgorithm | str = SearchAlgorithm.BEAM,
        budget_sec: float = 30.0,
    ) -> PlanResult:
        algo = SearchAlgorithm(algorithm) if isinstance(algorithm, str) else algorithm

        if algo == SearchAlgorithm.BEAM:
            r = beam_search_encounter(
                state,
                pool_size=self.pool_size,
                budget_sec=budget_sec,
                value_fn=self.value_fn,
            )
            return PlanResult(
                submission=r.best_submission,
                value=r.best_value,
                algorithm=algo.value,
            )

        if algo == SearchAlgorithm.MCTS:
            r = mcts_select_encounter(
                state,
                pool_size=self.pool_size,
                budget_sec=budget_sec,
                policy_priors=self.policy_priors,
                value_fn=self.value_fn,
            )
            return PlanResult(
                submission=r.best_submission,
                value=float(max(r.visits) if r.visits else 0),
                algorithm=algo.value,
            )

        if algo == SearchAlgorithm.EVOLUTIONARY:
            r = evolutionary_search_encounter(
                state,
                pool_size=min(self.pool_size, 100),
                budget_sec=budget_sec,
                value_fn=self.value_fn,
            )
            return PlanResult(
                submission=r.best_submission,
                value=r.best_fitness,
                algorithm=algo.value,
            )

        from cursed_words_solver.sim.search.candidate_gen import generate_candidate_pool
        from cursed_words_solver.sim.search.base import submission_from_word_result

        pool = generate_candidate_pool(state, pool_size=self.pool_size, time_budget_sec=budget_sec)
        if not pool.results:
            return PlanResult(submission=None, value=0.0, algorithm="greedy")
        wr = pool.results[0]
        return PlanResult(
            submission=submission_from_word_result(wr),
            value=float(wr.score),
            algorithm="greedy",
        )
