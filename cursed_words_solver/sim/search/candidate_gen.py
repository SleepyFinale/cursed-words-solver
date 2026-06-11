"""Top-500 candidate pool from WordSearcher (candidate funnel)."""

from __future__ import annotations

import time
from dataclasses import dataclass

from cursed_words_solver.models import WordResult
from cursed_words_solver.search import WordSearcher
from cursed_words_solver.sim.state import RunState

DEFAULT_POOL_SIZE = 500


@dataclass
class CandidatePool:
    results: list[WordResult]
    generated_sec: float = 0.0

    def __len__(self) -> int:
        return len(self.results)

    def __getitem__(self, index: int) -> WordResult:
        return self.results[index]


def generate_candidate_pool(
    state: RunState,
    *,
    pool_size: int = DEFAULT_POOL_SIZE,
    time_budget_sec: float = 12.0,
    searcher: WordSearcher | None = None,
) -> CandidatePool:
    """Dictionary search → top-N candidates (never neural generation)."""
    t0 = time.perf_counter()
    s = searcher or WordSearcher(time_budget=time_budget_sec)
    s.time_budget = time_budget_sec
    results = s.find_best_words(state.board, state.loadout, top_n=pool_size)
    return CandidatePool(results=list(results), generated_sec=time.perf_counter() - t0)
