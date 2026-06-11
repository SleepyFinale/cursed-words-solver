"""MCTS over top-500 candidate indices."""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field

from cursed_words_solver.sim.encounter_engine import EncounterEngine
from cursed_words_solver.sim.rng import SimRNG
from cursed_words_solver.sim.search.base import submission_from_word_result
from cursed_words_solver.sim.search.candidate_gen import generate_candidate_pool
from cursed_words_solver.sim.search.rollout_value import RolloutValueFn
from cursed_words_solver.sim.state import RunState
from cursed_words_solver.sim.submission import Submission


@dataclass
class _MCTSNode:
    state: RunState
    submission: Submission | None = None
    parent: _MCTSNode | None = None
    action_index: int = -1
    visits: int = 0
    value_sum: float = 0.0
    children: list[_MCTSNode] = field(default_factory=list)
    untried: list[int] = field(default_factory=list)

    def uct(self, c_puct: float, prior: float) -> float:
        if self.visits == 0:
            return float("inf")
        parent_visits = self.parent.visits if self.parent else 1
        q = self.value_sum / self.visits
        return q + c_puct * prior * math.sqrt(parent_visits) / (1 + self.visits)


@dataclass
class MCTSResult:
    best_submission: Submission | None
    best_index: int
    visits: list[int] = field(default_factory=list)


def mcts_select_encounter(
    state: RunState,
    *,
    pool_size: int = 500,
    iterations: int = 100,
    budget_sec: float = 30.0,
    c_puct: float = 1.4,
    policy_priors: list[float] | None = None,
    value_fn: RolloutValueFn | None = None,
) -> MCTSResult:
    """MCTS over candidate pool indices (Stage 2 / Stage 4 guided)."""
    deadline = time.perf_counter() + budget_sec
    value_fn = value_fn or RolloutValueFn()
    engine = EncounterEngine()

    pool = generate_candidate_pool(
        state,
        pool_size=pool_size,
        time_budget_sec=min(12.0, budget_sec * 0.35),
    )
    n = len(pool.results)
    if n == 0:
        return MCTSResult(best_submission=None, best_index=-1)

    if policy_priors is None or len(policy_priors) != n:
        policy_priors = [1.0 / n] * n

    root = _MCTSNode(state=state.clone(), untried=list(range(n)))

    for _ in range(iterations):
        if time.perf_counter() >= deadline:
            break

        node = root
        path: list[_MCTSNode] = [node]

        while not node.untried and node.children:
            node = max(
                node.children,
                key=lambda c: c.uct(
                    c_puct,
                    policy_priors[c.action_index] if 0 <= c.action_index < n else 1.0 / n,
                ),
            )
            path.append(node)

        if node.untried and time.perf_counter() < deadline:
            idx = node.untried.pop(random.randrange(len(node.untried)))
            wr = pool.results[idx]
            submission = submission_from_word_result(wr)
            rng = SimRNG.from_run_seed(node.state.run_seed, step_index=node.state.step_index)
            step = engine.step(node.state, submission, rng, advance_grid=False)
            child = _MCTSNode(
                state=step.state,
                submission=submission,
                parent=node,
                action_index=idx,
            )
            node.children.append(child)
            node = child
            path.append(node)

        remaining = max(0.05, deadline - time.perf_counter())
        rollout_value = value_fn(node.state, budget_sec=remaining)

        for n_node in reversed(path):
            n_node.visits += 1
            n_node.value_sum += rollout_value

    if not root.children:
        best_idx = 0
        best_sub = submission_from_word_result(pool.results[0])
    else:
        best_child = max(root.children, key=lambda c: c.visits)
        best_idx = best_child.action_index
        best_sub = best_child.submission

    visits = [0] * n
    for child in root.children:
        if 0 <= child.action_index < n:
            visits[child.action_index] = child.visits

    return MCTSResult(
        best_submission=best_sub,
        best_index=best_idx,
        visits=visits,
    )
