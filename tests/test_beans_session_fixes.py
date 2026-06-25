"""Regression tests for Beans/Michael session fixes (2026-06-25)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cursed_words_solver.loadout import (
    _fresh_encounter_grid_one,
    green_poison_from_historic_words,
)
from cursed_words_solver.suggestion import (
    f8_historic_would_fail_submit_projection,
    f8_should_block_save,
)


def test_fresh_encounter_grid_one_false_when_spc_positive() -> None:
    extras = {
        "grid_number": "1",
        "encounter_total_target": "61126",
        "encounter_remaining_target": "61126",
        "encounter_score_earned": "0",
        "scoring_previous_words_count": "3",
    }
    assert not _fresh_encounter_grid_one(extras)


def test_green_poison_applies_when_spc_positive_despite_earned_zero() -> None:
    extras = {
        "grid_number": "1",
        "encounter_total_target": "61126",
        "encounter_remaining_target": "61126",
        "encounter_score_earned": "0",
        "scoring_previous_words_count": "3",
        "encounter_historic_source": "live",
        "historic_words": json.dumps(
            [
                {"word": "a", "score": 3218, "green_tile_count": 1},
                {"word": "b", "score": 79347, "green_tile_count": 1},
            ]
        ),
    }
    poison = green_poison_from_historic_words(extras)
    assert poison == 322 + 7935


def test_f8_historic_would_fail_on_empty_embed_with_projected_historic() -> None:
    embed = {"historic_words": "", "scoring_previous_words_count": "0"}
    projected = {
        "historic_words": json.dumps([{"word": "x", "score": 100}]),
        "scoring_previous_words_count": "1",
    }
    note = f8_historic_would_fail_submit_projection(
        embed, projected_extras=projected
    )
    assert note is not None
    assert "empty historic" in note


def test_f8_should_block_save_on_empty_embed_historic_lag() -> None:
    """Grid 2 word 1: block when embed is behind live historic (no board reconcile)."""
    embed = {"historic_words": "[]", "scoring_previous_words_count": "0"}
    projected = {
        "historic_words": json.dumps([{"word": "x", "score": 100}]),
        "scoring_previous_words_count": "1",
        "grid_number": "2",
    }
    blocked, reason = f8_should_block_save(
        f8_extras=embed,
        submit_projected_extras=projected,
        gather_succeeded=True,
    )
    assert blocked
    assert reason == "submit_projection_mismatch"


def _rodman_grid1_word2_run_state() -> dict:
    fixture_path = (
        Path(__file__).resolve().parent / "fixtures" / "rodman_grid1_word2_faction.json"
    )
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    tiles = []
    blue = {tuple(cell) for cell in fixture.get("blue_cells", [])}
    for r, row in enumerate(fixture["board_letters"]):
        for c, ch in enumerate(row):
            tiles.append(
                {
                    "row": r,
                    "col": c,
                    "char": ch,
                    "letter": ch.upper(),
                    "base_score": 1.0,
                    "color": "blue" if (r, c) in blue else "colorless",
                    "curse": "letter",
                    "active": True,
                }
            )
    run_state = {
        "character": fixture["character"],
        "money": fixture["money"],
        "stickers": fixture["stickers"],
        "stamps": fixture["stamps"],
        "board": {"tiles": tiles, "money": fixture["money"]},
        "extras": dict(fixture["extras"]),
    }
    return run_state


def test_f8_should_not_block_grid1_word2_path_stale_historic(
    tmp_path, monkeypatch
) -> None:
    """Grid 1 word 2: pruned embed must not false-block on stale export historic."""
    from copy import deepcopy

    from cursed_words_solver.f8_snapshot import (
        embed_f8_snapshot,
        rebuild_snapshot_from_run_state,
    )
    from cursed_words_solver.loadout import (
        RUN_STATE_PATH,
        parse_board_from_run_state,
        project_workflow_extras_for_f8_embed,
        reconcile_encounter_historic_for_scoring,
    )

    run_state = _rodman_grid1_word2_run_state()
    run_state_path = tmp_path / "run_state.json"
    monkeypatch.setattr("cursed_words_solver.loadout.RUN_STATE_PATH", run_state_path)
    run_state_path.write_text(json.dumps(run_state), encoding="utf-8")

    snapshot = rebuild_snapshot_from_run_state(run_state, rules={})
    board = parse_board_from_run_state(run_state)
    assert snapshot.loadout is not None
    assert board is not None

    embedded = embed_f8_snapshot(
        snapshot,
        scoring_loadout=snapshot.loadout,
        fresh_run_state=run_state,
    )
    assert embedded is not None
    f8_extras = embedded.get("extras")
    assert isinstance(f8_extras, dict)

    submit_projected = deepcopy(run_state["extras"])
    reconcile_encounter_historic_for_scoring(submit_projected, board=board)
    project_workflow_extras_for_f8_embed(submit_projected, board=board)

    blocked, reason = f8_should_block_save(
        gather_succeeded=True,
        loadout=snapshot.loadout,
        board=board,
        f8_extras=f8_extras,
        submit_projected_extras=submit_projected,
        scoring_extras=snapshot.loadout.extras,
    )
    assert not blocked
    assert reason is None


def test_stale_f8_round_log_would_block_save() -> None:
    path = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "round_logs"
        / "20260625_143117_478.json"
    )
    if not path.exists():
        pytest.skip("promote stale F8 round log fixture first")
    data = json.loads(path.read_text(encoding="utf-8"))
    diff = data.get("extras_diff") or {}
    embed_extras: dict = {"scoring_previous_words_count": "0", "historic_words": ""}
    for key, entry in diff.items():
        if isinstance(entry, dict) and "f8" in entry:
            embed_extras[key] = entry.get("f8", "")
    projected_extras: dict = {}
    for key, entry in diff.items():
        if isinstance(entry, dict) and "submit" in entry:
            projected_extras[key] = entry.get("submit", "")
    blocked, reason = f8_should_block_save(
        f8_extras=embed_extras,
        submit_projected_extras=projected_extras,
        gather_succeeded=True,
    )
    assert blocked
    assert reason == "submit_projection_mismatch"


def _board_al_path() -> "Board":
    from cursed_words_solver.models import Board, CurseType, Tile, TileColor

    placeholder = Tile(
        row=0,
        col=0,
        char=".",
        letter=".",
        base_score=1,
        color=TileColor.COLORLESS,
        curse=CurseType.LETTER,
    )
    tiles = [[placeholder for _ in range(5)] for _ in range(5)]
    tiles[4][3] = Tile(
        row=4,
        col=3,
        char="a",
        letter="A",
        base_score=1,
        color=TileColor.COLORLESS,
        curse=CurseType.LETTER,
    )
    tiles[4][4] = Tile(
        row=4,
        col=4,
        char="l",
        letter="L",
        base_score=1,
        color=TileColor.COLORLESS,
        curse=CurseType.LETTER,
    )
    return Board(tiles=tiles, money=0, active=[True] * 25)


def test_f8_should_not_block_short_dictionary_word_at_effective_min() -> None:
    """Grid-1 short words: block check must use effective_min, not hardcoded 3."""
    from cursed_words_solver.config import GAME_WORDLIST_PATH
    from cursed_words_solver.dictionary import WordDictionary
    from cursed_words_solver.models import Loadout

    board = _board_al_path()
    loadout = Loadout()
    dictionary = WordDictionary(GAME_WORDLIST_PATH)
    path = [23, 24]

    blocked_short, reason_short = f8_should_block_save(
        gather_succeeded=True,
        loadout=loadout,
        board=board,
        path=path,
        dictionary=dictionary,
        scoring_word="al",
        min_len=1,
    )
    assert not blocked_short
    assert reason_short is None

    blocked_default, reason_default = f8_should_block_save(
        gather_succeeded=True,
        loadout=loadout,
        board=board,
        path=path,
        dictionary=dictionary,
        scoring_word="al",
    )
    assert blocked_default
    assert reason_default == "no_playable_dictionary_word"
