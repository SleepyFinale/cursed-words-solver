"""Smoke performance baselines from docs/DATA_STRUCTURE_ANALYSIS.md (12s budget)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cursed_words_solver.config import GAME_WORDLIST_PATH
from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
from cursed_words_solver.search import WordSearcher
from tests.regression.test_scoring_mismatches import _run_state_for_replay

_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "mismatches"

# Wall sec and DFS expansions at 12s budget, workers=1 (June 2026 profile).
# Fail when a change regresses more than 20% vs these ceilings.
_BASELINES: dict[str, dict[str, float]] = {
    "20260527_hayley_abacus": {"wall_sec": 13.5, "dfs_expansions": 42_000},
    "20260526_231158": {"wall_sec": 13.0, "dfs_expansions": 85_000},
    "20260526_231923": {"wall_sec": 13.5, "dfs_expansions": 465_000},
}


def _load_fixture(stem: str):
    path = _FIXTURES_DIR / f"{stem}.json"
    if not path.is_file():
        pytest.skip(f"fixture missing: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    run_state = _run_state_for_replay(data)
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    assert board is not None
    return board, loadout


@pytest.fixture(name="game_dict")
def fixture_game_dict():
    if not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024:
        pytest.skip("game wordlist required")
    return WordDictionary(GAME_WORDLIST_PATH)


@pytest.mark.slow
@pytest.mark.parametrize("stem", list(_BASELINES.keys()))
def test_profile_baseline_within_ceiling(stem: str, game_dict) -> None:
    board, loadout = _load_fixture(stem)
    budget = 12.0
    searcher = WordSearcher(
        dictionary=game_dict,
        time_budget=budget,
        search_workers=1,
        wordlist_path=GAME_WORDLIST_PATH,
    )
    searcher.find_best_words(board, loadout=loadout, top_n=3)
    timing = searcher.last_search_timing
    assert timing is not None
    ceiling = _BASELINES[stem]
    assert timing.wall_sec <= ceiling["wall_sec"] * 1.2, (
        f"{stem} wall {timing.wall_sec:.1f}s > {ceiling['wall_sec'] * 1.2:.1f}s"
    )
    assert timing.dfs_expansions <= ceiling["dfs_expansions"] * 1.2, (
        f"{stem} expansions {timing.dfs_expansions} > "
        f"{int(ceiling['dfs_expansions'] * 1.2)}"
    )
