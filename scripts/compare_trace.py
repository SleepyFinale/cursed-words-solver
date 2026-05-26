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


def _first_trace_diff(pred_trace: list[dict], actual_trace: list[dict]) -> str:
    n = min(len(pred_trace), len(actual_trace))
    for i in range(n):
        p = pred_trace[i]
        a = actual_trace[i]
        p_tiles = [int(x) for x in p.get("tile_scores", [])]
        a_tiles = [int(x) for x in a.get("tile_scores", [])]
        if p_tiles != a_tiles:
            return f"[{i}] tile_scores pred={p_tiles} actual={a_tiles}"
        p_id = _pred_step_id(p).lower()
        a_id = _actual_step_id(a).lower()
        if p_id and a_id and p_id != a_id:
            return f"[{i}] step_id pred={p_id} actual={a_id}"
        p_word = _pred_word_bonus(p)
        a_word = _actual_word_bonus(a)
        if a_word and p_word != a_word:
            return f"[{i}] word_bonus pred_word_score={p_word} actual_word_bonus={a_word}"
    if len(pred_trace) != len(actual_trace):
        return f"length mismatch pred={len(pred_trace)} actual={len(actual_trace)}"
    return "none"


def _compare_file(path: Path) -> DiffResult:
    data = _load(path)
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
    actual_trace = data.get("actual_trace") or []
    actual_score = int(data.get("actual_score") or 0)
    first_diff = _first_trace_diff(pred_trace, actual_trace)

    return DiffResult(
        stem=path.stem,
        predicted_score=int(pred_score),
        actual_score=actual_score,
        delta=int(pred_score) - actual_score,
        first_diff=first_diff,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("mismatch_json", type=Path, nargs="?")
    ap.add_argument("--glob", dest="glob_pattern", default="")
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
            r = _compare_file(f)
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"{f.name}: ERROR {exc}")
            continue
        print(
            f"{r.stem}: pred={r.predicted_score} actual={r.actual_score} "
            f"delta={r.delta} first_diff={r.first_diff}"
        )
        if r.delta != 0:
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
