"""Integrate V(state) into candidate ranking: immediate + λ·V(next)."""

from __future__ import annotations

from cursed_words_solver.models import WordResult
from cursed_words_solver.sim.encounter_engine import EncounterEngine
from cursed_words_solver.sim.ml.value_model import ValueModel
from cursed_words_solver.sim.rng import SimRNG
from cursed_words_solver.sim.search.base import submission_from_word_result
from cursed_words_solver.sim.state import RunState


def rank_with_value_model(
    state: RunState,
    candidates: list[WordResult],
    value_model: ValueModel,
    *,
    lam: float = 0.4,
    advance_grid: bool = False,
) -> list[tuple[WordResult, float]]:
    """Rank pool: immediate_score + λ·V(next_state)."""
    engine = EncounterEngine()
    ranked: list[tuple[WordResult, float]] = []

    for wr in candidates:
        immediate = float(wr.rank_score or wr.score)
        submission = submission_from_word_result(wr)
        rng = SimRNG.from_run_seed(state.run_seed, step_index=state.step_index)
        step = engine.step(state, submission, rng, advance_grid=advance_grid)
        future_v = value_model.predict(step.state)
        rank = immediate + lam * future_v
        ranked.append((wr, rank))

    ranked.sort(key=lambda x: x[1], reverse=True)
    return ranked
