#!/usr/bin/env python3
"""Compare predicted_trace vs actual_trace in a melmod mismatch JSON."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
from cursed_words_solver.rules.pipeline import ScoringPipeline


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("mismatch_json", type=Path)
    args = ap.parse_args()
    data = _load(args.mismatch_json)
    run_state = data.get("run_state_snapshot") or data.get("run_state") or {}
    board = parse_board_from_run_state(run_state)
    if board is None:
        print("No board in snapshot", file=sys.stderr)
        return 1
    loadout = parse_run_state(run_state)
    extras = data.get("extras_snapshot") or {}
    if isinstance(extras, dict):
        loadout.extras.update(extras)
    path = data.get("path") or []
    word = data.get("word") or ""
    pipe = ScoringPipeline()
    pred_score, _, pred_trace = pipe.score_with_trace(board, path, word, loadout)
    actual = data.get("actual_trace") or []
    print(f"predicted_score={pred_score} actual_score={data.get('actual_score')} delta={pred_score - float(data.get('actual_score') or 0)}")
    print(f"predicted_trace steps={len(pred_trace)} actual_trace steps={len(actual)}")
    n = min(len(pred_trace), len(actual))
    for i in range(n):
        p = pred_trace[i]
        a = actual[i]
        pid = p.get("rule_id") or p.get("item_id") or p.get("phase")
        aid = a.get("item_id") or a.get("item_name") or ""
        if pid != aid and p.get("phase") != a.get("phase"):
            print(f"  [{i}] pred {p.get('phase')} {pid} != actual {aid}")
    if len(pred_trace) != len(actual):
        print(f"  length mismatch: pred {len(pred_trace)} vs actual {len(actual)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
