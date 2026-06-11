"""Evolutionary search over sequences of pool candidates."""

from __future__ import annotations

import random
import time
from dataclasses import dataclass

from cursed_words_solver.sim.encounter_engine import EncounterEngine
from cursed_words_solver.sim.rng import SimRNG
from cursed_words_solver.sim.search.base import submission_from_word_result
from cursed_words_solver.sim.search.candidate_gen import generate_candidate_pool
from cursed_words_solver.sim.search.rollout_value import RolloutValueFn
from cursed_words_solver.sim.state import RunState
from cursed_words_solver.sim.submission import Submission


@dataclass
class EvolutionaryResult:
    best_submission: Submission | None
    best_fitness: float
    best_indices: list[int] = None  # type: ignore[assignment]


def evolutionary_search_encounter(
    state: RunState,
    *,
    population_size: int = 20,
    generations: int = 10,
    sequence_length: int = 1,
    pool_size: int = 100,
    budget_sec: float = 30.0,
    value_fn: RolloutValueFn | None = None,
) -> EvolutionaryResult:
    """Evolve index sequences within top pool (first gene = current grid choice)."""
    deadline = time.perf_counter() + budget_sec
    value_fn = value_fn or RolloutValueFn()
    engine = EncounterEngine()

    pool = generate_candidate_pool(
        state,
        pool_size=pool_size,
        time_budget_sec=min(10.0, budget_sec * 0.3),
    )
    n = len(pool.results)
    if n == 0:
        return EvolutionaryResult(best_submission=None, best_fitness=float("-inf"), best_indices=[])

    def fitness(indices: list[int]) -> float:
        sim = state.clone()
        rng_base = SimRNG.from_run_seed(sim.run_seed)
        for gene in indices[:sequence_length]:
            if time.perf_counter() >= deadline:
                break
            idx = gene % n
            wr = pool.results[idx]
            sub = submission_from_word_result(wr)
            rng = rng_base.with_step(sim.step_index)
            step = engine.step(sim, sub, rng)
            sim = step.state
            if sim.encounter_won or sim.encounter_lost:
                break
        return value_fn(sim, budget_sec=0.2)

    population = [
        [random.randrange(n) for _ in range(sequence_length)]
        for _ in range(population_size)
    ]
    best_indices = population[0]
    best_fitness = float("-inf")
    best_sub: Submission | None = None

    for _ in range(generations):
        if time.perf_counter() >= deadline:
            break
        scored = [(fitness(ind), ind) for ind in population]
        scored.sort(key=lambda x: x[0], reverse=True)
        if scored[0][0] > best_fitness:
            best_fitness = scored[0][0]
            best_indices = scored[0][1]
            best_sub = submission_from_word_result(pool.results[best_indices[0] % n])

        survivors = [ind for _, ind in scored[: max(2, population_size // 2)]]
        next_pop: list[list[int]] = list(survivors)
        while len(next_pop) < population_size:
            a, b = random.sample(survivors, 2)
            cut = random.randint(1, max(1, sequence_length - 1)) if sequence_length > 1 else 1
            child = a[:cut] + b[cut:]
            if random.random() < 0.2:
                pos = random.randrange(sequence_length)
                child[pos] = random.randrange(n)
            next_pop.append(child)
        population = next_pop

    if best_sub is None and best_indices:
        best_sub = submission_from_word_result(pool.results[best_indices[0] % n])

    return EvolutionaryResult(
        best_submission=best_sub,
        best_fitness=best_fitness,
        best_indices=best_indices,
    )
