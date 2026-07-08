"""Regression: letter-word from number-tile start (20260707 Cobra cursed board)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cursed_words_solver.config import ensure_wordlist
from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
from cursed_words_solver.search import WordSearcher
from cursed_words_solver.ui.board_geometry import path_from_melmod_indices

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "round_logs"
    / "20260707_jadeite_board.json"
)
JADEITE_STORAGE_PATH = [22, 17, 13, 18, 19, 14, 9]
JADEITE_MELMOD_PATH = [2, 7, 13, 8, 9, 14, 19]


@pytest.fixture(scope="module")
def jadeite_board_loadout():
    if not FIXTURE.exists():
        pytest.skip("jadeite round-log fixture required")
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    board = parse_board_from_run_state(data["run_state"])
    loadout = parse_run_state(data["run_state"])
    assert board is not None and loadout is not None
    return board, loadout, data


def test_melmod_path_resolves_to_jadeite_faces(jadeite_board_loadout):
    board, _loadout, _data = jadeite_board_loadout
    storage_path = path_from_melmod_indices(board, JADEITE_MELMOD_PATH)
    assert storage_path == JADEITE_STORAGE_PATH
    faces = []
    for idx in storage_path:
        tile = board.get_by_index(idx)
        face = (tile.char if hasattr(tile, "char") else None) or tile.letter
        faces.append(str(face).strip())
    assert faces == ["1", "2", "3", "e", "i", "t", "e"]


def test_find_best_words_finds_jadeite(jadeite_board_loadout):
    board, loadout, _data = jadeite_board_loadout
    dictionary = WordDictionary(ensure_wordlist())
    searcher = WordSearcher(
        dictionary=dictionary,
        min_len=7,
        max_len=7,
        time_budget=120,
        search_workers=1,
    )
    results = searcher.find_best_words(board, loadout, top_n=50)
    words = {r.word for r in results}
    assert "jadeite" in words
    jadeite_hits = [r for r in results if r.word == "jadeite"]
    assert any(list(r.path) == JADEITE_STORAGE_PATH for r in jadeite_hits)
