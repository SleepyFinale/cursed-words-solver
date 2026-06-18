"""Build melmod round-log JSON from mismatch captures for regression tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def mismatch_to_round_log(data: dict[str, Any]) -> dict[str, Any]:
    """Convert a scoring mismatch capture into round-log v1 shape."""
    solver_path = data.get("short_path") or []
    solver_word = data.get("short_word") or data.get("word") or ""
    solver_score = int(data.get("short_score") or data.get("predicted_score") or 0)
    actual_score = int(data.get("actual_score") or 0)
    status = str(data.get("match_status") or "path_extension")
    return {
        "schema_version": 1,
        "exported_at": data.get("exported_at") or "2026-06-18T00:00:00.0000000Z",
        "round_id": f"{data.get('_fixture_stem', 'fixture')}_round",
        "submit_method": "EncounterController.SubmitWord",
        "grid_number": str(
            (data.get("run_state_snapshot") or {}).get("extras", {}).get("grid_number", "1")
        ),
        "match_status": status,
        "solver": {
            "available": True,
            "word": solver_word,
            "scoring_word": solver_word,
            "path": solver_path,
            "predicted_score": solver_score,
            "board_fingerprint": data.get("board_fingerprint", ""),
            "loadout_fingerprint": data.get("loadout_fingerprint", ""),
            "f8_sequence": data.get("f8_sequence", 0),
            "predicted_trace": data.get("predicted_trace") or [],
        },
        "actual": {
            "word": data.get("word"),
            "path": data.get("path"),
            "score": actual_score,
            "trace": data.get("actual_trace") or [],
        },
        "run_state": data.get("run_state_snapshot") or {},
        "consumables": {
            "rack_before": [],
            "rack_after": [],
            "placements_this_round": [],
        },
        "comparison": {
            "score_delta": actual_score - solver_score,
            "path_matches_suggestion": False,
            "capture_active": True,
            "match_status": status,
            "submitted_beat_suggestion": actual_score > solver_score,
        },
    }


def write_round_log_fixture(mismatch_path: Path, out_path: Path) -> None:
    data = json.loads(mismatch_path.read_text(encoding="utf-8"))
    data["_fixture_stem"] = mismatch_path.stem
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(mismatch_to_round_log(data), indent=2),
        encoding="utf-8",
    )
