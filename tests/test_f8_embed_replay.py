"""F8 embed must replay the same score as the live scoring board."""

from __future__ import annotations

import json
from copy import deepcopy

from pathlib import Path

from cursed_words_solver.f8_snapshot import embed_f8_snapshot, f8_embed_replay_score
from cursed_words_solver.loadout import (
    align_embed_with_scoring_loadout,
    board_to_run_state_board,
    parse_board_from_run_state,
    parse_run_state,
    prepare_run_state_dict_for_scoring,
)
from cursed_words_solver.rules.pipeline import ScoringPipeline


def test_align_embed_serializes_pin_memory_as_json() -> None:
    """In-memory pin_memory list must become melmod JSON, not Python repr."""
    run_state = {
        "character": "Nat-H4",
        "pin_branch": "left",
        "stickers": [],
        "stamps": [],
        "extras": {
            "pin_effect": "random_access_memory",
            "pin_memory": json.dumps(
                [
                    {
                        "id": "yellow_glasses",
                        "name": "Yellow Glasses",
                        "level": 1,
                        "kind": "sticker",
                    }
                ]
            ),
        },
    }
    loadout = parse_run_state(run_state)
    assert isinstance(loadout.extras.get("pin_memory"), list)
    embed_extras: dict = {"pin_effect": "random_access_memory", "pin_memory": "[]"}
    align_embed_with_scoring_loadout(embed_extras, loadout.extras)
    raw = embed_extras["pin_memory"]
    assert isinstance(raw, str)
    parsed = json.loads(raw)
    assert parsed[0]["id"] == "yellow_glasses"
    assert "'" not in raw


def test_f8_embed_replay_ram_yellow_glasses_tombstone_dilling() -> None:
    """Regression: RAM Yellow Glasses + grid tombstone path (49 vs 33 embed replay)."""
    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "round_logs"
        / "dilling_ram_embed_replay.json"
    )
    if not fixture.is_file():
        import pytest

        pytest.skip("fixture dilling_ram_embed_replay not installed")

    pipeline = ScoringPipeline()
    from cursed_words_solver.f8_snapshot import F8Snapshot

    data = json.loads(fixture.read_text(encoding="utf-8"))
    run_state = data["run_state"]
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(prepare_run_state_dict_for_scoring(run_state))
    path = data["path_storage"]
    word = data["word"]
    expected = int(data["expected_score"])
    assert board is not None

    predicted, _ = pipeline.score(board, path, word, loadout)
    assert int(predicted) == expected
    snapshot = F8Snapshot(
        run_state=deepcopy(run_state),
        board=board,
        loadout=loadout,
        board_available=True,
    )
    embed = embed_f8_snapshot(
        snapshot,
        scoring_loadout=loadout,
        scoring_board=board,
        fresh_run_state=run_state,
    )
    assert isinstance(embed, dict)
    pin_memory = (embed.get("extras") or {}).get("pin_memory")
    assert isinstance(pin_memory, str)
    json.loads(pin_memory)
    replay_score = f8_embed_replay_score(
        embed,
        path=path,
        word=word,
        loadout=loadout,
        pipeline=pipeline,
    )
    assert replay_score is not None
    assert int(replay_score) == expected


def test_f8_embed_replay_matches_scoring_board() -> None:
    pipeline = ScoringPipeline()
    from cursed_words_solver.f8_snapshot import F8Snapshot

    case_path = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "mismatches"
        / "20260630_152914.json"
    )
    if not case_path.is_file():
        import pytest

        pytest.skip("fixture 20260630_152914 not installed")

    import json

    data = json.loads(case_path.read_text(encoding="utf-8"))
    run_state = data["run_state_snapshot"]
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    path = data["path"]
    word = data["word"]
    assert board is not None

    predicted, _ = pipeline.score(board, path, word, loadout)
    snapshot = F8Snapshot(
        run_state=deepcopy(run_state),
        board=board,
        loadout=loadout,
        board_available=True,
    )
    embed = embed_f8_snapshot(
        snapshot,
        scoring_loadout=loadout,
        scoring_board=board,
        fresh_run_state=run_state,
    )
    assert isinstance(embed, dict)
    replay_board = parse_board_from_run_state(embed)
    assert replay_board is not None
    assert board_to_run_state_board(board, source_run_state=run_state)["tiles"]
    replay_score = f8_embed_replay_score(
        embed,
        path=path,
        word=word,
        loadout=loadout,
        pipeline=pipeline,
    )
    assert replay_score is not None
    assert int(replay_score) == int(predicted)
