"""Helpers for melmod per-round JSON logs."""

from __future__ import annotations

import json
from typing import Any

from cursed_words_solver.config import ROUND_LOG_INDEX_PATH

MATCH_STATUSES = frozenset(
    {
        "score_match",
        "score_mismatch",
        "path_mismatch",
        "path_extension",
        "no_suggestion",
        "suggestion_blocked",
        "stale_f8_extras",
    }
)


def round_log_index_size() -> int:
    """Current byte length of the append-only round log index."""
    try:
        return ROUND_LOG_INDEX_PATH.stat().st_size
    except OSError:
        return 0


def poll_round_log_submits(since_offset: int = 0) -> tuple[list[dict[str, Any]], int]:
    """Read new lines from round_logs/index.jsonl since since_offset."""
    path = ROUND_LOG_INDEX_PATH
    if not path.exists():
        return [], since_offset
    try:
        size = path.stat().st_size
    except OSError:
        return [], since_offset
    if size < since_offset:
        since_offset = 0
    if size == since_offset:
        return [], since_offset
    try:
        with path.open("rb") as handle:
            handle.seek(since_offset)
            chunk = handle.read()
    except OSError:
        return [], since_offset
    new_offset = since_offset + len(chunk)
    entries: list[dict[str, Any]] = []
    for line in chunk.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            row = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            entries.append(row)
    return entries, new_offset


def derive_match_status(
    *,
    solver_available: bool,
    path_matches: bool,
    path_prefix_extension: bool = False,
    board_matches: bool = True,
    predicted_score: int,
    actual_score: int,
    capture_blocked: bool = False,
) -> str:
    """Mirror RoundLogExporter.ResolveMatchStatus for tests."""
    if not solver_available:
        return "no_suggestion"
    if capture_blocked:
        return "suggestion_blocked"
    if not board_matches:
        return "path_mismatch"
    if not path_matches:
        if path_prefix_extension:
            return "path_extension"
        return "path_mismatch"
    if predicted_score != actual_score:
        return "score_mismatch"
    return "score_match"


def validate_round_log(data: dict[str, Any]) -> list[str]:
    """Return list of validation errors (empty if OK)."""
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["root must be object"]

    if data.get("schema_version") != 1:
        errors.append("schema_version must be 1")

    status = data.get("match_status")
    if status not in MATCH_STATUSES:
        errors.append(f"invalid match_status: {status!r}")

    for key in ("solver", "actual", "run_state", "consumables", "comparison"):
        if key not in data:
            errors.append(f"missing {key}")

    solver = data.get("solver")
    if isinstance(solver, dict) and solver.get("available"):
        for field in ("word", "path", "predicted_score"):
            if field not in solver:
                errors.append(f"solver missing {field}")

    actual = data.get("actual")
    if isinstance(actual, dict):
        for field in ("word", "path", "score"):
            if field not in actual:
                errors.append(f"actual missing {field}")

    return errors
