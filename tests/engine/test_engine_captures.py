"""Real game captures the scoring engine must reproduce exactly.

Each listed fixture is a melmod capture (mismatch or round log) whose final score
came from the game itself. ``engine_exact_captures.txt`` lists the ones the engine
matches today; a regression on any of them fails here. Regenerate the list when
engine fixes make more captures pass (see docs/game-research/engine.md).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cursed_words_solver.engine import EnginePlan
from cursed_words_solver.sim.replay import prepare_replay

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
LIST = Path(__file__).with_name("engine_exact_captures.txt")


def _cases() -> list[str]:
    return [
        line.strip()
        for line in LIST.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]


def _load(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if "run_state_snapshot" in data and "run_state" not in data:
        data = dict(data)
        data["run_state"] = data["run_state_snapshot"]
        data["actual"] = {
            "word": data.get("word", ""),
            "path": data.get("path", []),
            "score": data["actual_score"],
        }
    return data


@pytest.mark.parametrize("rel", _cases())
def test_engine_matches_game_score(rel: str) -> None:
    prep, err = prepare_replay(_load(FIXTURES / rel))
    assert prep is not None, err
    plan = EnginePlan.build(prep.board, prep.loadout)
    score = plan.score(prep.submission.path, prep.submission.effective_scoring_word).int_score
    if prep.two_wrongs:
        score = -score
    assert score == prep.expected
