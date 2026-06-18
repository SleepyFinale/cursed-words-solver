#!/usr/bin/env python3
"""Compare solver predicted_trace vs melmod actual_trace.

Single-file mode:
  python scripts/compare_trace.py tests/fixtures/mismatches/20260526_150342.json

Batch mode:
  python scripts/compare_trace.py --glob "tests/fixtures/mismatches/*.json"
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.trace_compare import compare_traces


def _replay_mismatch(data: dict) -> tuple[int, list[dict]]:
    """Apply regression replay adjustments (Nat-H4 / trace inference) before scoring."""
    from tests.regression.test_scoring_mismatches import (
        _adjust_bento_previous_word_extras,
        _adjust_nat_h4_session_extras,
        _adjust_neapolitan_percent_extras,
        _adjust_previous_word_letter_extras,
        _adjust_rare_item_count_extras,
        _adjust_scattered_item_level_from_trace,
        _adjust_snapshot_copy_from_trace,
        _adjust_steak_percent_extras,
        _adjust_tile_ninja_bonus_from_trace,
        _adjust_void_penalty_from_trace,
        _run_state_for_replay,
    )

    run_state = _run_state_for_replay(data)
    if not run_state:
        raise ValueError("missing run_state_snapshot")
    word = data.get("word") or ""
    path = data.get("path") or []
    case_stem = Path(str(data.get("_source_path", "unknown"))).stem
    for fn in (
        _adjust_previous_word_letter_extras,
        _adjust_bento_previous_word_extras,
        _adjust_neapolitan_percent_extras,
        _adjust_rare_item_count_extras,
        _adjust_steak_percent_extras,
        _adjust_tile_ninja_bonus_from_trace,
    ):
        fn(run_state, data)
    board = parse_board_from_run_state(run_state)
    _adjust_void_penalty_from_trace(run_state, data, board, path)
    _adjust_scattered_item_level_from_trace(run_state, data, board, path)
    _adjust_nat_h4_session_extras(run_state, data, case_stem)
    _adjust_snapshot_copy_from_trace(
        run_state, data, board, path, word, case_stem=case_stem
    )
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    pipe = ScoringPipeline()
    pred_score, _, pred_trace = pipe.score_with_trace(board, path, word, loadout)
    return int(pred_score), pred_trace


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _pred_step_id(step: dict) -> str:
    return str(step.get("rule_id") or step.get("item_id") or step.get("phase") or "")


def _actual_step_id(step: dict) -> str:
    return str(step.get("item_id") or step.get("item_name") or f"step_{step.get('step_index','')}").lower()


def _pred_word_bonus(step: dict) -> int:
    return int(step.get("word_score", 0))


def _actual_word_bonus(step: dict) -> int:
    return int(step.get("word_bonus", 0) or 0)


@dataclass
class DiffResult:
    stem: str
    predicted_score: int
    actual_score: int
    delta: int
    first_diff: str
    hypothesis: str = ""


def _first_trace_diff(pred_trace: list[dict], actual_trace: list[dict]) -> tuple[str, str]:
    diff = compare_traces(pred_trace, actual_trace)
    if diff.has_divergence:
        return diff.summary, diff.hypothesis
    return "none", ""


def _compare_file(path: Path, *, replay: bool = False) -> DiffResult:
    data = _load(path)
    data["_source_path"] = str(path)
    if replay:
        pred_score, pred_trace = _replay_mismatch(data)
    else:
        run_state = data.get("run_state_snapshot") or data.get("run_state") or {}
        board = parse_board_from_run_state(run_state)
        if board is None:
            raise ValueError(f"{path.name}: missing board in snapshot")
        loadout = parse_run_state(run_state)
        extras = data.get("extras_snapshot") or {}
        if isinstance(extras, dict):
            loadout.extras.update(extras)

        path_idxs = data.get("path") or []
        word = data.get("word") or ""
        pipe = ScoringPipeline()
        pred_score, _, pred_trace = pipe.score_with_trace(board, path_idxs, word, loadout)
        pred_score = int(pred_score)
    actual_trace = data.get("actual_trace") or []
    actual_score = int(data.get("actual_score") or 0)
    first_diff, hypothesis = _first_trace_diff(pred_trace, actual_trace)

    return DiffResult(
        stem=path.stem,
        predicted_score=int(pred_score),
        actual_score=actual_score,
        delta=int(pred_score) - actual_score,
        first_diff=first_diff,
        hypothesis=hypothesis,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("mismatch_json", type=Path, nargs="?")
    ap.add_argument("--glob", dest="glob_pattern", default="")
    ap.add_argument(
        "--replay",
        action="store_true",
        help="apply regression replay adjustments (void/dusty/Nat-H4 extras)",
    )
    args = ap.parse_args()

    files: list[Path] = []
    if args.glob_pattern:
        files = sorted(ROOT.glob(args.glob_pattern))
    elif args.mismatch_json:
        files = [args.mismatch_json]
    else:
        ap.error("provide mismatch_json or --glob")

    failures = 0
    for f in files:
        try:
            r = _compare_file(f, replay=args.replay)
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"{f.name}: ERROR {exc}")
            continue
        line = (
            f"{r.stem}: pred={r.predicted_score} actual={r.actual_score} "
            f"delta={r.delta} first_diff={r.first_diff}"
        )
        if r.hypothesis:
            line += f" hypothesis={r.hypothesis}"
        print(line)
        if r.delta != 0:
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
