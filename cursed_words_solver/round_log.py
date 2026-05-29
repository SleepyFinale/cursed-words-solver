"""Helpers for melmod per-round JSON logs."""

from __future__ import annotations

from typing import Any

MATCH_STATUSES = frozenset(
    {
        "score_match",
        "score_mismatch",
        "path_mismatch",
        "path_extension",
        "no_suggestion",
    }
)


def derive_match_status(
    *,
    solver_available: bool,
    path_matches: bool,
    path_prefix_extension: bool = False,
    board_matches: bool = True,
    predicted_score: int,
    actual_score: int,
) -> str:
    """Mirror RoundLogExporter.ResolveMatchStatus for tests."""
    if not solver_available:
        return "no_suggestion"
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
