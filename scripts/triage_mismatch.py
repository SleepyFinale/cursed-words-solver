#!/usr/bin/env python3
"""Classify a mismatch or round-log capture for debugging."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cursed_words_solver.triage import triage_capture, triage_file


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("capture_json", type=Path, nargs="?")
    ap.add_argument("--glob", dest="glob_pattern", default="")
    args = ap.parse_args()

    files: list[Path] = []
    if args.glob_pattern:
        files = sorted(ROOT.glob(args.glob_pattern))
    elif args.capture_json:
        files = [args.capture_json]
    else:
        ap.error("provide capture_json or --glob")

    for path in files:
        if path.suffix == ".json":
            result = triage_file(path)
        else:
            ap.error(f"unsupported file: {path}")
            continue
        print(f"{path.name}: {result.category}")
        print(f"  reason: {result.reason}")
        print(f"  next: {result.next_step}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
