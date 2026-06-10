"""Helpers for melmod per-round JSON logs."""

from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any

AUTO_SOLVE_BOARD_WAIT_TIMEOUT_SEC = 10.0

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


def auto_solve_board_ready(
    *,
    snapshot_board_fp: str,
    current_board_fp: str,
    queued_monotonic: float,
    now_monotonic: float | None = None,
    timeout_sec: float = AUTO_SOLVE_BOARD_WAIT_TIMEOUT_SEC,
) -> bool:
    """True when melmod likely exported the post-submit board (or wait timed out)."""
    snap = (snapshot_board_fp or "").strip()
    cur = (current_board_fp or "").strip()
    if snap and cur and cur != snap:
        return True
    if not snap:
        return True
    now = time.monotonic() if now_monotonic is None else now_monotonic
    return (now - queued_monotonic) >= timeout_sec


def parse_round_log_id_time(round_id: str) -> datetime | None:
    """Parse melmod round_id timestamp (local wall clock, naive)."""
    raw = (round_id or "").strip()
    if len(raw) < 15:
        return None
    try:
        return datetime.strptime(raw[:15], "%Y%m%d_%H%M%S")
    except ValueError:
        return None


def round_log_entries_after(
    entries: list[dict[str, Any]],
    not_before: datetime,
) -> list[dict[str, Any]]:
    """Drop index rows older than not_before (guards index truncation re-reads)."""
    kept: list[dict[str, Any]] = []
    for row in entries:
        if not isinstance(row, dict):
            continue
        created = parse_round_log_id_time(str(row.get("round_id", "") or ""))
        if created is None or created >= not_before:
            kept.append(row)
    return kept


def round_log_entries_are_word_submits(entries: list[dict[str, Any]]) -> bool:
    """True when any index row is an in-game word submit (not shop noise)."""
    for row in entries:
        if not isinstance(row, dict):
            continue
        word = str(row.get("submitted_word", "") or "").strip()
        if not word:
            continue
        status = str(row.get("match_status", "") or "").strip()
        if status in MATCH_STATUSES:
            return True
    return False


def _first_letter_of_submitted_word(word: str) -> str | None:
    """First alphabetic character of an in-game submitted word."""
    for ch in (word or "").strip().lower():
        if ch.isalpha():
            return ch
    return None


def last_round_log_submit_word() -> str | None:
    """Last submitted word from round_logs/index.jsonl, or None when unavailable."""
    path = ROUND_LOG_INDEX_PATH
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    last_word: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            row = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        word = str(row.get("submitted_word", "") or "").strip()
        if not word:
            continue
        status = str(row.get("match_status", "") or "").strip()
        if status in MATCH_STATUSES:
            last_word = word
    return last_word


def last_submit_first_letter() -> str | None:
    """First letter of the last in-game word submit (for F8 workflow catchup)."""
    word = last_round_log_submit_word()
    if not word:
        return None
    return _first_letter_of_submitted_word(word)


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
