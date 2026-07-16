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


def test_f8_embed_replay_placed_red_currency_consumable_mahjong() -> None:
    """Placed red currency must use GetValue packet (1), not zero — Mahjong ×2 → +2.

    Regression: possesses predicted 14 vs embed replay 16 when rack source zeroed
    currency and skipped color while melmod re-parse used base_score=1.
    """
    from cursed_words_solver.models import Board, CurseType, Tile, TileColor

    pipeline = ScoringPipeline()
    from cursed_words_solver.f8_snapshot import F8Snapshot

    def _letter(row: int, col: int, ch: str, *, base: float = 1.0) -> Tile:
        return Tile(
            row=row,
            col=col,
            char=ch,
            letter=ch,
            base_score=base,
            color=TileColor.COLORLESS,
            curse=CurseType.LETTER,
            metadata={"source": "melmod"},
        )

    # Path "cat" on indices 0,1,2 with placed red ₱ as the 'c' (was_consumable).
    currency = Tile(
        row=0,
        col=0,
        char="₱",
        letter="P",
        base_score=1.0,
        color=TileColor.RED,
        curse=CurseType.CURRENCY,
        metadata={
            "source": "consumable_rack",
            "was_consumable": True,
            "consumable": True,
        },
    )
    tiles = [
        [currency, _letter(0, 1, "a"), _letter(0, 2, "t"), _letter(0, 3, "x"), _letter(0, 4, "x")],
        [_letter(1, c, "x") for c in range(5)],
        [_letter(2, c, "x") for c in range(5)],
        [_letter(3, c, "x") for c in range(5)],
        [_letter(4, c, "x") for c in range(5)],
    ]
    board = Board(tiles=tiles, money=5)
    run_state = {
        "character": "Sandy Saguaro",
        "money": 5,
        "stickers": [],
        "stamps": [],
        "extras": {
            "pin_effect": "mahjong_red_dragon",
        },
        "board": board_to_run_state_board(board),
    }
    loadout = parse_run_state(prepare_run_state_dict_for_scoring(run_state))
    path = [0, 1, 2]
    word = "pat"

    predicted, detail = pipeline.score(board, path, word, loadout)
    # Currency init 1 × Mahjong 2 = 2; a=1; t=1 → 4
    assert int(predicted) == 4
    effects = (detail.get("pipeline") or detail).get("effects") or detail.get("effects") or []
    assert any("consumable" in str(e).lower() for e in effects)

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
    replay_score = f8_embed_replay_score(
        embed,
        path=path,
        word=word,
        loadout=loadout,
        pipeline=pipeline,
    )
    assert replay_score is not None
    assert int(replay_score) == int(predicted)
