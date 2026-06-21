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
