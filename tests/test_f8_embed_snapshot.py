"""Single F8 snapshot embed — workflow extras from melmod game export."""

from __future__ import annotations

import json

from cursed_words_solver.f8_snapshot import F8Snapshot, embed_f8_snapshot
from cursed_words_solver.loadout import merge_loadout_with_board, parse_run_state
from cursed_words_solver.models import Loadout, LoadoutItem


def _number_board_run_state(*, dna_json: str, cake: str = "25") -> dict:
    tiles = []
    for r in range(5):
        for c in range(5):
            tiles.append(
                {
                    "row": r,
                    "col": c,
                    "char": str((r * 5 + c) % 10 + 1),
                    "letter": str((r * 5 + c) % 10 + 1),
                    "base_score": 50,
                    "color": "red",
                    "curse": "number",
                    "active": True,
                }
            )
    return {
        "board": {"tiles": tiles, "money": 10},
        "character": "Hayley Bayles",
        "stickers": [],
        "stamps": [{"id": "mutating_dna", "name": "Mutating DNA", "kind": "stamp"}],
        "extras": {
            "grid_number": "1",
            "scoring_previous_words_count": "2",
            "birthday_cake_bonus": cake,
            "mutating_dna_letter_counts": dna_json,
        },
    }


def test_embed_f8_snapshot_uses_fresh_game_export_not_reconciled_loadout():
    """Embed must reflect melmod run_state, not Python-reconciled loadout.extras."""
    dna = '{"1":10,"2":5,"3":5,"4":1,"5":1}'
    run_state = _number_board_run_state(dna_json=dna)
    loadout = merge_loadout_with_board(parse_run_state(run_state), 10)
    # Reconciled loadout diverges from game export (split-brain scenario).
    loadout.extras["scoring_previous_words_count"] = "0"
    loadout.extras["mutating_dna_letter_counts"] = "{}"

    stale_snapshot = _number_board_run_state(dna_json="{}")
    snapshot = F8Snapshot(
        run_state=stale_snapshot,
        board=None,
        loadout=loadout,
        board_available=True,
    )
    fresh = _number_board_run_state(dna_json=dna)
    embed = embed_f8_snapshot(
        snapshot,
        scoring_loadout=loadout,
        fresh_run_state=fresh,
    )
    assert embed is not None
    assert embed["extras"]["mutating_dna_letter_counts"] == dna
    assert embed["extras"]["scoring_previous_words_count"] == "2"
    assert embed["extras"]["birthday_cake_bonus"] == "25"


def test_embed_f8_snapshot_deep_copies_gather_state():
    run_state = _number_board_run_state(dna_json='{"1":1}')
    loadout = merge_loadout_with_board(parse_run_state(run_state), 10)
    snapshot = F8Snapshot(run_state=run_state, board=None, loadout=loadout)
    embed = embed_f8_snapshot(snapshot, scoring_loadout=loadout)
    assert embed is not None
    embed["extras"]["mutating_dna_letter_counts"] = '{"9":9}'
    assert snapshot.run_state["extras"]["mutating_dna_letter_counts"] == '{"1":1}'


def test_embed_f8_snapshot_aligns_bicycle_from_loadout_fingerprint():
    run_state = {
        "board": {"tiles": [], "money": 5},
        "character": "Bones The Dog",
        "stickers": [],
        "stamps": [],
        "extras": {
            "pin_effect": "bicycle",
            "loadout_fingerprint": "Bones The Dog|5|bicycle:left|106",
            "bicycle_word_score_bonus": "105",
            "cards_submitted": "105",
        },
    }
    loadout = parse_run_state(run_state)
    snapshot = F8Snapshot(run_state=run_state, board=None, loadout=loadout)
    embed = embed_f8_snapshot(snapshot, scoring_loadout=loadout)
    assert embed is not None
    assert embed["extras"]["bicycle_word_score_bonus"] == "106"
    assert embed["extras"]["cards_submitted"] == "106"


def test_mutating_dna_missing_blocks_gather():
    from cursed_words_solver.f8_snapshot import _extras_missing_for_loadout
    from cursed_words_solver.loadout import parse_board_from_run_state

    run_state = _number_board_run_state(dna_json="{}")
    board = parse_board_from_run_state(run_state)
    loadout = Loadout(
        stamps=[LoadoutItem(id="mutating_dna", name="Mutating DNA", kind="stamp")],
        extras=run_state["extras"],
    )
    missing = _extras_missing_for_loadout(loadout, board, run_state["extras"])
    assert "mutating_dna_letter_counts" in missing


def test_mutating_dna_empty_ok_on_first_word():
    from cursed_words_solver.f8_snapshot import _extras_missing_for_loadout
    from cursed_words_solver.loadout import parse_board_from_run_state

    run_state = _number_board_run_state(dna_json="{}")
    run_state["extras"]["scoring_previous_words_count"] = "0"
    board = parse_board_from_run_state(run_state)
    loadout = Loadout(
        stamps=[LoadoutItem(id="mutating_dna", name="Mutating DNA", kind="stamp")],
        extras=run_state["extras"],
    )
    missing = _extras_missing_for_loadout(loadout, board, run_state["extras"])
    assert "mutating_dna_letter_counts" not in missing


def test_round_log_fixture_embed_dna_pattern():
    from pathlib import Path

    path = Path(__file__).parent / "fixtures" / "round_logs" / "20260615_180752_023.json"
    if not path.exists():
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    diff = data.get("extras_diff") or {}
    dna = diff.get("mutating_dna_letter_counts") or {}
    assert dna.get("f8") == "{}"
    assert "1" in str(dna.get("submit", ""))
    trace = (data.get("solver") or {}).get("predicted_trace") or []
    dna_rules = [e for e in trace if e.get("rule_id") == "mutating_dna" and e.get("applied")]
    assert dna_rules, "fixture should show DNA applied in prediction"


def _melmod_board_run_state(*, letter_overrides: dict[tuple[int, int], dict] | None = None) -> dict:
    tiles = []
    for r in range(5):
        for c in range(5):
            entry: dict = {
                "row": r,
                "col": c,
                "char": "A",
                "letter": "A",
                "base_score": 1,
                "color": "colorless",
                "curse": "letter",
                "active": True,
            }
            if letter_overrides and (r, c) in letter_overrides:
                entry.update(letter_overrides[(r, c)])
            tiles.append(entry)
    return {
        "board": {"money": 10, "rows": 5, "cols": 5, "tiles": tiles},
        "character": "Test",
        "money": 10,
        "stickers": [],
        "stamps": [],
        "extras": {"grid_number": "1"},
    }


def test_board_roundtrip_preserves_melmod_fingerprint():
    """Parse → board_to_run_state_board must not drift melmod fingerprint fields."""
    from cursed_words_solver.fingerprints import fingerprints_from_run_state
    from cursed_words_solver.loadout import (
        board_to_run_state_board,
        parse_board_from_run_state,
    )

    run_state = _melmod_board_run_state(
        letter_overrides={
            (4, 3): {
                "char": "🐙",
                "letter": "🐙",
                "curse": "void",
                "color": "void",
                "base_score": -10,
            },
            (2, 2): {
                "char": "?",
                "letter": "?",
                "curse": "wildcard",
                "color": "red",
                "is_joker": True,
            },
            (0, 0): {
                "char": "$",
                "letter": "$",
                "curse": "currency",
                "color": "yellow",
            },
        }
    )
    original_fp, _ = fingerprints_from_run_state(run_state)
    board = parse_board_from_run_state(run_state)
    assert board is not None
    roundtrip = {"board": board_to_run_state_board(board, source_run_state=run_state)}
    roundtrip_fp, _ = fingerprints_from_run_state(roundtrip)
    assert roundtrip_fp == original_fp


def test_save_last_suggestion_uses_melmod_fingerprint_override(tmp_path, monkeypatch):
    from cursed_words_solver.loadout import parse_board_from_run_state
    from cursed_words_solver.models import Loadout, WordResult
    from cursed_words_solver.suggestion import save_last_suggestion

    monkeypatch.setattr(
        "cursed_words_solver.suggestion.LAST_SUGGESTION_PATH",
        tmp_path / "last_suggestion.json",
    )
    run_state = _melmod_board_run_state()
    melmod_fp = "10|4,0:A/letter/colorless;4,1:A/letter/colorless;"
    embed_fp = "10|4,0:Z/letter/colorless;4,1:A/letter/colorless;"
    board = parse_board_from_run_state(run_state)
    assert board is not None
    save_last_suggestion(
        board=board,
        loadout=Loadout(),
        result=WordResult(word="aaa", path=[0, 1, 2], score=1),
        predicted_trace=[],
        run_state_snapshot=run_state,
        melmod_board_fingerprint=melmod_fp,
        melmod_loadout_fingerprint="Test|10|||boss|-|pin:left",
    )
    data = json.loads((tmp_path / "last_suggestion.json").read_text(encoding="utf-8"))
    assert data["board_fingerprint"] == melmod_fp
    assert data["board_fingerprint"] != embed_fp
