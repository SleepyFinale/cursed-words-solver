"""Search primitives for encounter planning."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from cursed_words_solver.models import WordResult
from cursed_words_solver.sim.state import RunState
from cursed_words_solver.sim.submission import Submission


@dataclass
class SearchNode:
    state: RunState
    submission: Submission | None = None
    value: float = 0.0
    children: list[SearchNode] = field(default_factory=list)


class ValueFn(Protocol):
    def __call__(self, state: RunState, budget_sec: float = 0.0) -> float: ...


def submission_from_word_result(result: WordResult) -> Submission:
    return Submission(
        word=result.display_word(),
        path=list(result.path),
        scoring_word=result.word,
    )


def word_result_key(result: WordResult) -> tuple:
    return (result.word.lower(), tuple(result.path))
