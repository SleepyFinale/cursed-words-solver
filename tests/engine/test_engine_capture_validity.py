"""Every captured submission is a path the game accepted: the engine must agree.

For each listed capture, the submitted path must follow ``GetValidNextTiles``
step by step, satisfy the active challenge, and spell the submitted word under
the engine's ``Vocabulary`` rules (wildcards, numbers by position, item letter
substitutions, Honeypot, Michael's finale). The trie holds only the submitted
word(s), so this needs no dictionary and runs on CI.
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

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
LIST = Path(__file__).with_name("engine_valid_captures.txt")


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
        data["actual"] = {"word": data.get("word", ""), "path": data.get("path", []), "score": data.get("actual_score")}
    return data


@pytest.mark.parametrize("rel", _cases())
def test_engine_accepts_captured_submission(rel: str) -> None:
    data = _load(FIXTURES / rel)
    prep, err = prepare_replay(data)
    assert prep is not None, err
    words = str((data.get("actual") or {}).get("word") or "").lower().replace(";", " ").split()
    search = ExactSearch(EnginePlan.build(prep.board, prep.loadout), CsrTrie.from_words(words))
    path = tuple(prep.submission.path)
    assert _moves_ok(search, path), "illegal movement"
    assert search.path_allowed(path), "blocked by the challenge"
    assert search.valid_word(path) is not None, f"engine cannot spell {words} on this path"
