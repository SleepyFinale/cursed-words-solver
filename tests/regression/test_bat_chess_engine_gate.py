"""Chess boards: F8 gate and legacy fallback must follow the engine's game movement.

Melmod: suggestion abigails [12, 11, 17, 21, 15, 22, 20, 16] (storage) scored 336
and was submitted as turgidly for 336, but the capture was blocked with
invalid_path_movement. The legacy neighbor rules / word matcher / pipeline replay
(92 pts) disagreed with the engine port that produced the suggestion.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cursed_words_solver.config import GAME_WORDLIST_PATH
from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.engine.solver import engine_path_score
from cursed_words_solver.sim.replay import prepare_replay
from cursed_words_solver.suggestion import (
    suggestion_path_movement_ok,
    suggestion_path_submittable,
)

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "round_logs"
    / "20261010_215626_bat_chess_abigails_blocked.json"
)


def _prepared():
    prep, why = prepare_replay(json.loads(FIXTURE.read_text(encoding="utf-8")))
    assert prep is not None, why
    return prep


def test_engine_movement_and_score_accept_submitted_path():
    prep = _prepared()
    path = prep.submission.path
    assert suggestion_path_movement_ok(prep.board, path, prep.loadout)
    assert engine_path_score(prep.board, path, "abigails", prep.loadout) == 336


@pytest.mark.skipif(not GAME_WORDLIST_PATH.exists(), reason="game wordlist required")
def test_engine_submittable_accepts_submitted_path():
    prep = _prepared()
    assert suggestion_path_submittable(
        prep.board,
        prep.submission.path,
        "abigails",
        prep.loadout,
        WordDictionary(GAME_WORDLIST_PATH),
    )


FULL_MOON_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "run_state_full_moon_chess_batavias.json"
)
# Old legacy-fallback suggestion (storage indices): king 10 -> A 5 is not a game move —
# with Full Moon equipped, a chess tile only reaches same-piece tiles (GetValidNextTiles
# skips chess moves once Full Moon targets exist).
BATAVIAS_PATH = [13, 4, 0, 18, 15, 10, 5, 11]


def test_full_moon_chess_tile_only_reaches_same_piece():
    from cursed_words_solver.loadout import (
        parse_board_from_run_state,
        parse_run_state,
        prepare_run_state_dict_for_scoring,
    )

    rs = prepare_run_state_dict_for_scoring(
        json.loads(FULL_MOON_FIXTURE.read_text(encoding="utf-8"))
    )
    board = parse_board_from_run_state(rs)
    loadout = parse_run_state(rs)
    assert not suggestion_path_movement_ok(board, BATAVIAS_PATH, loadout)


CAPYBARA_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "round_logs"
    / "20261011_001530_capybara_embed_replay.json"
)


def test_capybara_embed_replay_uses_expected_score():
    """Capybara shuffles item order at submit: the F8 prediction is the mean over
    every order (759, range 680-838; game rolled 838), so the embed replay must
    use the same mean or it always reports embed_replay_mismatch."""
    prep, why = prepare_replay(json.loads(CAPYBARA_FIXTURE.read_text(encoding="utf-8")))
    assert prep is not None, why
    assert engine_path_score(prep.board, prep.submission.path, "advantageable", prep.loadout) == 759


def test_capybara_range_covers_every_order():
    from cursed_words_solver.engine.calc import EnginePlan
    from cursed_words_solver.engine.solver import _capybara_mode, capybara_score_range

    prep, why = prepare_replay(json.loads(CAPYBARA_FIXTURE.read_text(encoding="utf-8")))
    assert prep is not None, why
    plan = EnginePlan.build(prep.board, prep.loadout)
    ev, lo, hi, n, exhaustive = capybara_score_range(
        plan, prep.submission.path, "advantageable", _capybara_mode(prep.loadout)
    )
    assert (lo, hi, n, exhaustive) == (680, 838, 14400, True)
