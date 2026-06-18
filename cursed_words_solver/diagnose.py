"""Unified diagnostics for solver artifacts (~/.cursed_words_solver/)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cursed_words_solver.config import (
    AppConfig,
    DEBUG_DIR,
    GAME_WORDLIST_PATH,
    LAST_SUGGESTION_BLOCKED_PATH,
    LAST_SUGGESTION_PATH,
    ROUND_LOG_DIR,
    SCORING_MISMATCHES_DIR,
    describe_wordlist,
    resolve_wordlist,
)
from cursed_words_solver.f8_messages import F8_RETRY_HINT
from cursed_words_solver.triage import triage_capture
from cursed_words_solver.trace_compare import compare_traces


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _latest_file(directory: Path, pattern: str = "*.json") -> Path | None:
    if not directory.is_dir():
        return None
    files = sorted(directory.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def _age_label(iso_ts: str) -> str:
    try:
        created = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except ValueError:
        return "unknown age"
    delta = datetime.now(timezone.utc) - created.astimezone(timezone.utc)
    secs = int(delta.total_seconds())
    if secs < 60:
        return f"{secs}s ago"
    if secs < 3600:
        return f"{secs // 60}m ago"
    return f"{secs // 3600}h ago"


def _action_for_status(status: str, data: dict[str, Any]) -> str:
    triage = triage_capture(data)
    if triage.category != "ok":
        return triage.next_step
    if status == "path_extension":
        short = (data.get("solver") or {}).get("word") or data.get("short_word")
        return (
            f"Solver found prefix {short!r}; run "
            f"`cursed-solver explain --round-log <file>`"
        )
    if status == "path_mismatch":
        return "Search miss — run `cursed-solver explain --round-log <file>`"
    if status == "score_mismatch":
        return "Run `python scripts/compare_trace.py <mismatch> --replay`"
    if status == "suggestion_blocked":
        return f"F8 was blocked — check {LAST_SUGGESTION_BLOCKED_PATH.name}"
    if status == "no_suggestion":
        return f"Press F8 before submit ({F8_RETRY_HINT})"
    return "No action required"


def build_diagnose_report() -> list[str]:
    lines: list[str] = []
    cfg = AppConfig.load()
    lines.append("=== Cursed Words Solver diagnose ===")
    lines.append("")
    lines.append("Environment")
    lines.append(f"  wordlist: {describe_wordlist(resolve_wordlist(cfg.wordlist))}")
    lines.append(f"  game_words: {'yes' if GAME_WORDLIST_PATH.exists() else 'missing'}")
    lines.append(f"  search_budget: {cfg.search_time_budget_sec}s")
    lines.append(f"  setup_weight: {cfg.setup_weight}")
    lines.append(f"  mult_search_weight: {cfg.mult_search_weight}")
    lines.append("")

    suggestion = _read_json(LAST_SUGGESTION_PATH) if LAST_SUGGESTION_PATH.exists() else None
    blocked = (
        _read_json(LAST_SUGGESTION_BLOCKED_PATH)
        if LAST_SUGGESTION_BLOCKED_PATH.exists()
        else None
    )
    lines.append("Last F8")
    if suggestion:
        created = str(suggestion.get("created_at") or "")
        lines.append(
            f"  word: {suggestion.get('word')} "
            f"({suggestion.get('predicted_score')} pts, {_age_label(created)})"
        )
        lines.append(f"  f8_sequence: {suggestion.get('f8_sequence')}")
        diag = suggestion.get("export_diagnostics") or {}
        if isinstance(diag, dict):
            trigger = diag.get("export_trigger")
            ack = diag.get("f8_request_id")
            if trigger or ack:
                lines.append(f"  export_trigger: {trigger}  f8_request_id: {ack}")
        gather = suggestion.get("gather_status") or {}
        if isinstance(gather, dict) and gather:
            lines.append(
                f"  gather: ack={gather.get('f8_export_acked')} "
                f"extras_ready={gather.get('extras_ready')} "
                f"missing={gather.get('gather_missing')}"
            )
        workflow = suggestion.get("workflow_warnings") or []
        export_warn = suggestion.get("export_warnings") or []
        for bucket, label in ((workflow, "workflow"), (export_warn, "export")):
            for warn in bucket[:5]:
                lines.append(f"  {label}_warning: {warn}")
    else:
        lines.append("  (no last_suggestion.json)")
    if blocked:
        lines.append(f"  BLOCKED: {blocked.get('block_reason')}")
    lines.append("")

    round_log_path = _latest_file(ROUND_LOG_DIR)
    lines.append("Latest round log")
    if round_log_path:
        data = _read_json(round_log_path) or {}
        status = str(data.get("match_status") or "")
        solver = data.get("solver") or {}
        actual = data.get("actual") or {}
        comparison = data.get("comparison") or {}
        pred = int(solver.get("predicted_score") or 0)
        actual_score = int(actual.get("score") or 0)
        lines.append(f"  file: {round_log_path.name}")
        lines.append(f"  match_status: {status}")
        lines.append(f"  scores: predicted={pred} actual={actual_score} delta={actual_score - pred}")
        if comparison.get("submitted_beat_suggestion"):
            lines.append("  submitted_beat_suggestion: true")
        lines.append(f"  next: {_action_for_status(status, data)}")
    else:
        lines.append("  (none)")
    lines.append("")

    mismatch_path = _latest_file(SCORING_MISMATCHES_DIR)
    lines.append("Latest mismatch")
    if mismatch_path:
        data = _read_json(mismatch_path) or {}
        data["_source_stem"] = mismatch_path.stem
        pred = int(data.get("predicted_score") or 0)
        actual = int(data.get("actual_score") or 0)
        lines.append(f"  file: {mismatch_path.name}")
        lines.append(f"  word: {data.get('word')} delta={actual - pred}")
        triage = triage_capture(data, stem=mismatch_path.stem)
        lines.append(f"  category: {triage.category} — {triage.reason}")
        pred_trace = data.get("predicted_trace") or []
        actual_trace = data.get("actual_trace") or []
        if pred_trace and actual_trace:
            diff = compare_traces(pred_trace, actual_trace)
            if diff.has_divergence:
                lines.append(f"  trace: {diff.summary}")
                if diff.hypothesis:
                    lines.append(f"  hypothesis: {diff.hypothesis}")
        lines.append(f"  next: {triage.next_step}")
    else:
        lines.append("  (none)")
    lines.append("")

    lines.append("Tools")
    lines.append("  cursed-solver validate-path --round-log <file>")
    lines.append("  cursed-solver explain --round-log <file>")
    lines.append("  python scripts/compare_trace.py <mismatch> --replay")
    lines.append("  python scripts/triage_mismatch.py <mismatch-or-round-log>")
    latest_parse = _latest_file(DEBUG_DIR, "parse_*.json")
    if latest_parse:
        lines.append(f"  latest debug parse: {latest_parse}")
    return lines


def cli_diagnose(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Diagnose solver artifacts and recent captures")
    parser.parse_args(argv)
    for line in build_diagnose_report():
        print(line)
    return 0
