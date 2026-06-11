"""EncounterEngine — orchestrates submit → reward → effects → grid advance."""

from __future__ import annotations

from dataclasses import dataclass

from cursed_words_solver.sim.effect_engine import EffectEngine
from cursed_words_solver.sim.reward_engine import RewardEngine, RewardResult
from cursed_words_solver.sim.rng import SimRNG
from cursed_words_solver.sim.state import RunState
from cursed_words_solver.sim.submission import Submission


@dataclass
class StepResult:
    state: RunState
    reward: RewardResult
    submission: Submission


class EncounterEngine:
    """One encounter step: submit → RewardEngine → EffectEngine."""

    def __init__(
        self,
        reward_engine: RewardEngine | None = None,
        effect_engine: EffectEngine | None = None,
    ) -> None:
        self.reward_engine = reward_engine or RewardEngine()
        self.effect_engine = effect_engine or EffectEngine()

    def step(
        self,
        state: RunState,
        submission: Submission,
        rng: SimRNG | None = None,
        *,
        advance_grid: bool = True,
    ) -> StepResult:
        rng = rng or SimRNG.from_run_seed(state.run_seed, step_index=state.step_index)
        reward = self.reward_engine.score(state, submission)
        next_state = self.effect_engine.apply(
            state,
            submission,
            reward,
            rng,
            advance_grid=advance_grid,
        )
        return StepResult(state=next_state, reward=reward, submission=submission)
