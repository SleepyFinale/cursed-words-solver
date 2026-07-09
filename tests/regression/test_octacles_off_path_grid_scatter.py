"""Octacles session: off-path grid scatter must not score (2026-07-01)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.scoring_order import encounter_grid_scatter_refs
from tests.regression.test_scoring_mismatches import _replay_path, _run_state_for_replay

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "mismatches"

_OFF_PATH_CASES = [
    ("20260701_133257", "hanafuda", "kaf", 26),
    ("20260701_133409", "cocktail", "japer", 33),
    ("20260701_133959", "newspaper", "feebles", 32),
]

_OFF_PATH_TOMBSTONE_NO_EQUIP = ("20260708_215951", "tombstone", "iotas", 23350)


def _load(stem: str) -> dict:
    path = FIXTURES / f"{stem}.json"
    if not path.is_file():
        pytest.skip(f"fixture required: {path.name}")
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("stem,off_path_slug,word,expected", _OFF_PATH_CASES)
def test_off_path_grid_scatter_refs_exclude_path_only_stickers(
    stem: str, off_path_slug: str, word: str, expected: int
) -> None:
    del word, expected
    data = _load(stem)
    run_state = _run_state_for_replay(data)
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    assert board is not None and loadout is not None
    rules = ScoringPipeline().rules
    refs = encounter_grid_scatter_refs(board, data["path"], rules, loadout)
    assert not any(r.rule_id == off_path_slug for r in refs)


@pytest.mark.parametrize("stem,off_path_slug,word,expected", _OFF_PATH_CASES)
def test_off_path_grid_scatter_replay_matches_actual(
    stem: str, off_path_slug: str, word: str, expected: int
) -> None:
    del off_path_slug
    data = _load(stem)
    run_state = _run_state_for_replay(data)
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    assert board is not None and loadout is not None
    path = _replay_path(board, data["path"])
    score, _ = ScoringPipeline().score(board, path, word, loadout)
    assert int(score) == expected


def test_off_path_tombstone_without_equip_does_not_score() -> None:
    """20260708 iotas: grid Tombstone off path, no equipped Tombstone → no bonus."""
    stem, off_path_slug, word, expected = _OFF_PATH_TOMBSTONE_NO_EQUIP
    data = _load(stem)
    run_state = _run_state_for_replay(data)
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    assert board is not None and loadout is not None
    rules = ScoringPipeline().rules
    refs = encounter_grid_scatter_refs(board, data["path"], rules, loadout)
    assert not any(r.rule_id == off_path_slug for r in refs)
    path = _replay_path(board, data["path"])
    score, _ = ScoringPipeline().score(board, path, word, loadout)
    assert int(score) == expected


def test_off_path_dusty_coffin_without_equip_first_word_still_refs() -> None:
    """ocherous: off-path grid dusty without equip still gets a grid ref on first word."""
    data = _load("20260528_105530")
    run_state = _run_state_for_replay(data)
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    assert board is not None and loadout is not None
    rules = ScoringPipeline().rules
    refs = encounter_grid_scatter_refs(board, data["path"], rules, loadout)
    assert any(r.rule_id == "dusty_coffin" for r in refs)


def test_off_path_dusty_coffin_without_equip_later_grid_skipped() -> None:
    """eath: grid-only dusty must not ref off-path when not equipped after prior words."""
    data = _load("20260610_233142")
    run_state = _run_state_for_replay(data)
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    assert board is not None and loadout is not None
    rules = ScoringPipeline().rules
    refs = encounter_grid_scatter_refs(board, data["path"], rules, loadout)
    assert not any(r.rule_id == "dusty_coffin" for r in refs)
