"""Beam search over top-500 candidate pool."""

from __future__ import annotations

import time
from dataclasses import dataclass

from cursed_words_solver.models import WordResult
from cursed_words_solver.sim.encounter_engine import EncounterEngine
from cursed_words_solver.sim.rng import SimRNG
from cursed_words_solver.sim.search.base import submission_from_word_result
from cursed_words_solver.sim.search.candidate_gen import CandidatePool, generate_candidate_pool
from cursed_words_solver.sim.search.rollout_value import RolloutValueFn
from cursed_words_solver.sim.state import RunState
from cursed_words_solver.sim.submission import Submission


@dataclass
class BeamSearchResult:
    best_submission: Submission | None
    best_value: float
    best_word: WordResult | None = None


def beam_search_encounter(
    state: RunState,
    *,
    width: int = 5,
    depth: int | None = None,
    pool_size: int = 500,
    budget_sec: float = 30.0,
    value_fn: RolloutValueFn | None = None,
) -> BeamSearchResult:
    """Beam search within candidate pool at current grid (depth=1 default)."""
    deadline = time.perf_counter() + budget_sec
    value_fn = value_fn or RolloutValueFn()
    engine = EncounterEngine()
    depth = depth if depth is not None else 1

    pool = generate_candidate_pool(
        state,
        pool_size=pool_size,
        time_budget_sec=min(12.0, budget_sec * 0.4),
    )
    if not pool.results:
        return BeamSearchResult(best_submission=None, best_value=float("-inf"))

    candidates = pool.results[:width]
    best_value = float("-inf")
    best_submission: Submission | None = None
    best_word: WordResult | None = None

    for wr in candidates:
        if time.perf_counter() >= deadline:
            break
        submission = submission_from_word_result(wr)
        rng = SimRNG.from_run_seed(state.run_seed, step_index=state.step_index)
        step = engine.step(state, submission, rng, advance_grid=False)
        leaf = step.state
        if depth > 1:
            remaining = deadline - time.perf_counter()
            value = value_fn(leaf, budget_sec=max(0.1, remaining))
        else:
            value = float(wr.rank_score or wr.score)
            if value_fn.objective.value == "margin":
                value += value_fn(leaf, budget_sec=0.5)

        if value > best_value:
            best_value = value
            best_submission = submission
            best_word = wr

    return BeamSearchResult(
        best_submission=best_submission,
        best_value=best_value,
        best_word=best_word,
    )
