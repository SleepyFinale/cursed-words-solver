"""Classify scoring captures and round logs for debugging."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cursed_words_solver.known_failing import is_known_failing, known_failing_info
from cursed_words_solver.trace_compare import compare_traces


@dataclass(frozen=True)
class TriageResult:
    category: str
    reason: str
    next_step: str


def _has_stale_signals(data: dict[str, Any]) -> bool:
    if data.get("stale_f8_extras"):
        return True
    if str(data.get("match_status") or "") == "stale_f8_extras":
        return True
    comparison = data.get("comparison")
    if isinstance(comparison, dict) and comparison.get("stale_suggestion"):
        return True
    stale_reason = str(data.get("stale_f8_reason") or "").strip()
    return bool(stale_reason)


def _is_path_extension(data: dict[str, Any]) -> bool:
    status = str(data.get("match_status") or "")
    if status == "path_extension":
        return True
    return bool(data.get("short_path") or data.get("short_word"))


def _is_search_miss(data: dict[str, Any]) -> bool:
    status = str(data.get("match_status") or "")
    if status == "path_mismatch":
        return True
    comparison = data.get("comparison")
    if isinstance(comparison, dict) and comparison.get("submitted_beat_suggestion"):
        return True
    predicted = int(data.get("predicted_score") or 0)
    actual = int(data.get("actual_score") or 0)
    solver = data.get("solver") or {}
    if isinstance(solver, dict):
        predicted = int(solver.get("predicted_score") or predicted)
    actual_block = data.get("actual") or {}
    if isinstance(actual_block, dict) and "score" in actual_block:
        actual = int(actual_block.get("score") or actual)
    if actual > predicted and not _has_stale_signals(data):
        short_score = data.get("short_score")
        if short_score is not None and actual > int(short_score):
            return False
        if status not in ("score_mismatch", "path_extension"):
            return True
    return False


def triage_capture(data: dict[str, Any], *, stem: str = "") -> TriageResult:
    """Label a mismatch JSON or round-log-shaped dict."""
    stem = stem or str(data.get("_source_stem") or "")
    if stem and is_known_failing(stem):
        info = known_failing_info(stem)
        return TriageResult(
            category="replay_gap",
            reason=info.reason if info else "listed in known_failing registry",
            next_step="Improve melmod submit-time snapshot or replay adjustments",
        )
    if _is_path_extension(data):
        short_word = data.get("short_word") or (data.get("solver") or {}).get("word")
        return TriageResult(
            category="path_extension",
            reason=f"solver prefix {short_word!r} scored lower than submitted word",
            next_step="Run `cursed-solver explain --round-log <file>` or extend-search regression",
        )
    if _is_search_miss(data):
        return TriageResult(
            category="search_miss",
            reason="submitted path beat F8 suggestion",
            next_step="Run `cursed-solver explain` on the round log; check search/pruning",
        )
    if _has_stale_signals(data):
        return TriageResult(
            category="stale_snapshot",
            reason=str(data.get("stale_f8_reason") or "F8 embed stale vs submit"),
            next_step="Press F8 again on the same grid before submit; check workflow_warnings",
        )
    pred_trace = data.get("predicted_trace") or []
    actual_trace = data.get("actual_trace") or []
    actual_block = data.get("actual") or {}
    if not actual_trace and isinstance(actual_block, dict):
        actual_trace = actual_block.get("trace") or []
    if pred_trace and actual_trace:
        diff = compare_traces(pred_trace, actual_trace)
        if diff.has_divergence:
            return TriageResult(
                category="trace_divergence",
                reason=diff.summary,
                next_step=f"Pipeline bug likely — {diff.hypothesis}; run compare_trace.py --replay",
            )
    predicted = int(data.get("predicted_score") or 0)
    actual = int(data.get("actual_score") or 0)
    if predicted != actual:
        return TriageResult(
            category="trace_divergence",
            reason=f"score delta {predicted - actual}",
            next_step="Run compare_trace.py with --replay on the mismatch fixture",
        )
    return TriageResult(
        category="ok",
        reason="no divergence detected",
        next_step="No action required",
    )


def triage_file(path: Path) -> TriageResult:
    import json

    data = json.loads(path.read_text(encoding="utf-8"))
    data["_source_stem"] = path.stem
    return triage_capture(data, stem=path.stem)
