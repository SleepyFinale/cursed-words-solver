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
from cursed_words_solver.engine.scorer import EngineScorer


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

    pipeline = EngineScorer()
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
    pipeline = EngineScorer()
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




def test_f8_embed_replay_placed_consumable_over_game_state_tile() -> None:
    """Regression: RESISTLESSNESS 23488 vs embed replay 5760.

    The simulated R placed over a void E kept the stale raw tile in the
    embed's ``game_state.grid``; re-parsing re-attached it, so the engine
    scored -1 for the R and Lucky Scarf (red first + last) lost its x4.
    """
    from cursed_words_solver.consumable_placement import (
        apply_consumable_placements,
        loadout_after_consumable_placements,
        remaining_rack_tiles,
    )
    from cursed_words_solver.f8_snapshot import F8Snapshot
    from cursed_words_solver.ui.board_geometry import path_from_melmod_indices

    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "round_logs"
        / "resistlessness_placed_consumable_embed_replay.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    run_state = data["run_state"]
    prepared = prepare_run_state_dict_for_scoring(run_state)
    board = parse_board_from_run_state(prepared)
    loadout = parse_run_state(prepared)
    assert board is not None
    rack = remaining_rack_tiles(loadout, board)
    placements = [
        (p["index"], next(t for t in rack if t.letter == p["letter"]))
        for p in data["placements"]
    ]
    search_board = apply_consumable_placements(board, placements)
    score_loadout = loadout_after_consumable_placements(loadout, len(placements))
    path = path_from_melmod_indices(search_board, data["path_melmod"])
    word = data["word"]
    expected = int(data["expected_score"])

    predicted, _ = EngineScorer().score(search_board, path, word, score_loadout)
    assert int(predicted) == expected
    live_game_state = deepcopy(run_state["game_state"])
    snapshot = F8Snapshot(
        run_state=deepcopy(run_state),
        board=board,
        loadout=loadout,
        board_available=True,
    )
    embed = embed_f8_snapshot(
        snapshot,
        scoring_loadout=score_loadout,
        scoring_board=search_board,
        fresh_run_state=run_state,
    )
    assert isinstance(embed, dict)
    replay_score = f8_embed_replay_score(
        embed, path=path, word=word, loadout=score_loadout
    )
    assert replay_score == expected
    # The live export must be left untouched.
    assert run_state["game_state"] == live_game_state


def test_board_round_trip_keeps_value_exact_on_zero_void_letter() -> None:
    """Regression: void S worth 0 replayed as -1 (SEGNI 306 vs embed replay 294).

    Dropping value_exact on embed lets the engine's legacy "every void letter
    zeroed" heuristic rewrite the tile to -(letter value).
    """
    from cursed_words_solver.engine.model import EGrid

    tiles = []
    for row in range(5):
        for col in range(5):
            void = (row, col) == (1, 0)
            tiles.append(
                {
                    "row": row,
                    "col": col,
                    "char": "s" if void else "e",
                    "letter": "S" if void else "E",
                    "base_score": 0.0 if void else 1.0,
                    "color": "void" if void else "colorless",
                    "curse": "letter",
                    "active": True,
                    "value_exact": 0 if void else 1,
                    "value_modifier": 0,
                }
            )
    run_state = {
        "character": "Rodman",
        "stickers": [],
        "stamps": [],
        "extras": {},
        "board": {"source": "melmod", "row_order": "top_first", "rows": 5, "cols": 5, "tiles": tiles},
    }
    board = parse_board_from_run_state(run_state)
    assert board is not None
    embedded = deepcopy(run_state)
    embedded["board"] = board_to_run_state_board(board, source_run_state=run_state)
    void_entry = next(t for t in embedded["board"]["tiles"] if t["color"] == "void")
    assert void_entry["value_exact"] == 0
    replay_board = parse_board_from_run_state(embedded)
    void_values = [t.value for t in EGrid(replay_board).tiles if t.tile_type == "void"]
    assert void_values == [0]


def test_f8_embed_replay_tile_ninja_counter_reaches_game_state() -> None:
    """Regression: AWHETO 2793 vs embed replay 2713.

    Two simulated placements bumped Tile Ninja to 10 in the embed's extras, but
    re-parsing rebuilt ``item_states`` from ``game_state.player`` (still 8).
    """
    from cursed_words_solver.f8_snapshot import F8Snapshot
    from cursed_words_solver.ui.board_geometry import path_from_melmod_indices

    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "round_logs"
        / "awheto_tile_ninja_game_state_embed_replay.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    run_state = data["run_state"]
    prepared = prepare_run_state_dict_for_scoring(deepcopy(run_state))
    board = parse_board_from_run_state(prepared)
    from dataclasses import replace

    parsed = parse_run_state(prepared)
    # The scoring loadout carries the post-placement counter (10) the embed's
    # extras hold; game_state.player still has the live 8.
    loadout = replace(
        parsed,
        extras={**parsed.extras, "item_states": run_state["extras"]["item_states"]},
    )
    assert board is not None
    path = path_from_melmod_indices(board, data["path_melmod"])
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
    ninja = next(
        r for r in embed["game_state"]["player"]["stamps"] if r and r.get("class") == "TileNinja"
    )
    assert ninja["fields"]["ConsumableTilesUsed"] == 10
    replay = f8_embed_replay_score(embed, path=path, word=data["word"], loadout=loadout)
    assert replay == int(data["expected_score"])


def test_live_snapshot_reads_exact_previous_word_like_the_replay() -> None:
    """Regression: TWEENIE 63 vs embed replay 42.

    The previous word started with a currency tile (₩EEPING$). The live F8
    loadout skipped ``game_state``, so the engine fell back to melmod's
    ``previous_word_first_letter`` ("e") and Chips fired; the game (and the
    replay, which applies ``game_state``) gives no Chips.
    """
    from cursed_words_solver.f8_snapshot import F8Snapshot, _build_snapshot_from_run_state
    from cursed_words_solver.rules.rule_lookup import rules_catalog

    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "round_logs"
        / "tweenie_chips_currency_prev_word.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    run_state = data["run_state"]
    live = deepcopy(run_state)
    snapshot = _build_snapshot_from_run_state(run_state, rules=rules_catalog())
    assert run_state == live
    assert snapshot.board is not None and snapshot.loadout is not None
    path = data["path_storage"]
    word = data["word"]
    expected = int(data["expected_score"])

    predicted, _ = EngineScorer().score(snapshot.board, path, word, snapshot.loadout)
    assert int(predicted) == expected
    embed = embed_f8_snapshot(
        F8Snapshot(
            run_state=deepcopy(run_state),
            board=snapshot.board,
            loadout=snapshot.loadout,
            board_available=True,
        ),
        scoring_loadout=snapshot.loadout,
        scoring_board=snapshot.board,
        fresh_run_state=run_state,
    )
    assert isinstance(embed, dict)
    replay = f8_embed_replay_score(embed, path=path, word=word, loadout=snapshot.loadout)
    assert replay == expected
