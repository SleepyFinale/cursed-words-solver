"""F8 embed must replay the same score as the live scoring board."""

from __future__ import annotations

from copy import deepcopy

from pathlib import Path

from cursed_words_solver.f8_snapshot import embed_f8_snapshot, f8_embed_replay_score
from cursed_words_solver.loadout import (
    board_to_run_state_board,
    parse_board_from_run_state,
    parse_run_state,
)
from cursed_words_solver.rules.pipeline import ScoringPipeline


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
