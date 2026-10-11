"""Every melmod capture in tests/fixtures/captures/ replays to the game's score.

A capture holds the exact pre-submit game state (``game_state/1``), what was
submitted and the score the game gave it, so the test is just: engine score ==
game score, and the engine accepts the submitted path. Add one with
``python scripts/capture_to_fixture.py <round_log.json>``; no list to update.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cursed_words_solver.engine import EnginePlan
from cursed_words_solver.engine.search import ExactSearch
from cursed_words_solver.engine.solver import _moves_ok
from cursed_words_solver.engine.trie import CsrTrie
from cursed_words_solver.sim.replay import prepare_replay

CAPTURES = Path(__file__).resolve().parents[1] / "fixtures" / "captures"


def _cases() -> list[str]:
    return sorted(p.name for p in CAPTURES.glob("*.json"))


@pytest.mark.parametrize("name", _cases())
def test_capture_replays_to_game_score(name: str) -> None:
    data = json.loads((CAPTURES / name).read_text(encoding="utf-8"))
    prep, err = prepare_replay(data)
    assert prep is not None, err
    plan = EnginePlan.build(prep.board, prep.loadout)
    word = prep.submission.effective_scoring_word
    score = plan.score(prep.submission.path, word).int_score
    if prep.two_wrongs:
        score = -score
    assert score == prep.expected

    search = ExactSearch(plan, CsrTrie.from_words(word.split()))
    path = tuple(prep.submission.path)
    assert _moves_ok(search, path), "illegal movement"
    assert search.valid_word(path) is not None, f"engine cannot spell {word!r} on this path"
