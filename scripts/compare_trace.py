#!/usr/bin/env python3
"""Step-by-step engine trace vs the game's trace for captured submits.

Shows the first scoring step where the engine and the game diverge (which
item, tile scores, word bonus), the fastest way to find a scoring bug.

  python scripts/compare_trace.py tests/fixtures/mismatches/20260526_150342.json
  python scripts/compare_trace.py ~/.cursed_words_solver/round_logs/20261012_*.json
  python scripts/compare_trace.py --glob "tests/fixtures/mismatches/*.json" --only-diffs
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cursed_words_solver.engine import EnginePlan  # noqa: E402
from cursed_words_solver.sim.replay import prepare_replay  # noqa: E402
from cursed_words_solver.trace_compare import compare_traces  # noqa: E402


def _load(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if "run_state_snapshot" in data and "run_state" not in data:  # mismatch bundle
        data["run_state"] = data["run_state_snapshot"]
        data["actual"] = {"word": data.get("word", ""), "path": data.get("path", []), "score": data.get("actual_score"), "trace": data.get("actual_trace") or []}
    return data


def compare_file(path: Path) -> tuple[str, bool]:
    data = _load(path)
    prep, err = prepare_replay(data)
    if prep is None:
        return f"{path.name}: cannot replay ({err})", False
    res = EnginePlan.build(prep.board, prep.loadout).score(prep.submission.path, prep.submission.effective_scoring_word)
    score = -res.int_score if prep.two_wrongs else res.int_score
    actual = data.get("actual") or {}
    actual_trace = actual.get("trace") or data.get("actual_trace") or []
    line = f"{path.name}: engine={score} game={prep.expected} delta={score - (prep.expected or 0)}"
    if actual_trace:
        diff = compare_traces(res.trace(), actual_trace)
        line += f" first_diff={diff.summary if diff.has_divergence else 'none'}"
        if diff.has_divergence and diff.hypothesis:
            line += f" hypothesis={diff.hypothesis}"
    return line, score == prep.expected


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", type=Path, nargs="*")
    ap.add_argument("--glob", dest="glob_pattern", default="")
    ap.add_argument("--only-diffs", action="store_true", help="print only captures the engine mis-scores")
    args = ap.parse_args()
    files = list(args.files) + (sorted(ROOT.glob(args.glob_pattern)) if args.glob_pattern else [])
    if not files:
        ap.error("give capture files or --glob")
    failures = 0
    for f in files:
        try:
            line, ok = compare_file(f)
        except Exception as exc:  # noqa: BLE001
            line, ok = f"{f.name}: ERROR {exc}", False
        failures += not ok
        if not ok or not args.only_diffs:
            print(line)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
