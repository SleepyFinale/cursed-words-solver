"""RewardEngine — wraps ScoringPipeline for submit scoring."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from cursed_words_solver.loadout import prepare_run_state_dict_for_scoring
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.sim.state import RunState
from cursed_words_solver.sim.submission import Submission


@dataclass
class RewardResult:
    score: int
    trace: list[dict[str, Any]]
    breakdown: dict[str, Any] = field(default_factory=dict)
    nondeterministic: bool = False
    score_min: int | None = None
    score_max: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "trace": self.trace,
            "breakdown": self.breakdown,
            "nondeterministic": self.nondeterministic,
            "score_min": self.score_min,
            "score_max": self.score_max,
        }


class RewardEngine:
    """Score a submission via ScoringPipeline (EncounterController → CalculateOverallScore)."""

    def __init__(self, pipeline: ScoringPipeline | None = None) -> None:
        self.pipeline = pipeline or ScoringPipeline()

    def score(self, state: RunState, submission: Submission) -> RewardResult:
        word = submission.effective_scoring_word
        path = list(submission.path)
        loadout = state.loadout

        score, breakdown = self.pipeline.score(
            state.board,
            path,
            word,
            loadout,
        )
        trace = breakdown.get("trace") if isinstance(breakdown, dict) else None
        if not isinstance(trace, list):
            trace = []

        nondeterministic = bool(breakdown.get("nondeterministic")) if isinstance(breakdown, dict) else False
        score_min = breakdown.get("score_min") if isinstance(breakdown, dict) else None
        score_max = breakdown.get("score_max") if isinstance(breakdown, dict) else None

        return RewardResult(
            score=int(score),
            trace=trace,
            breakdown=breakdown if isinstance(breakdown, dict) else {},
            nondeterministic=nondeterministic,
            score_min=int(score_min) if score_min is not None else None,
            score_max=int(score_max) if score_max is not None else None,
        )

    def score_from_run_state_dict(
        self,
        run_state: dict[str, Any],
        submission: Submission,
    ) -> RewardResult:
        """Score using melmod run_state dict (applies prepare_run_state_dict_for_scoring)."""
        from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state

        prepared = prepare_run_state_dict_for_scoring(dict(run_state))
        board = parse_board_from_run_state(prepared)
        if board is None:
            return RewardResult(score=0, trace=[])
        loadout = parse_run_state(prepared)
        state = RunState(board=board, loadout=loadout)
        return self.score(state, submission)
