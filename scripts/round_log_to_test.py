#!/usr/bin/env python3
"""Copy a round_logs/*.json file into tests/fixtures/round_logs/."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cursed_words_solver.round_log import validate_round_log

DEFAULT_FIXTURE_DIR = ROOT / "tests" / "fixtures" / "round_logs"


def install_fixture(round_log_path: Path, *, output_dir: Path | None = None) -> Path:
    data = json.loads(round_log_path.read_text(encoding="utf-8"))
    errors = validate_round_log(data)
    if errors:
        raise SystemExit("Round log validation failed:\n  " + "\n  ".join(errors))

    out_dir = output_dir or DEFAULT_FIXTURE_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"{round_log_path.stem}.json"
    if dest.exists():
        print(f"Fixture already exists: {dest}", file=sys.stderr)
        return dest

    shutil.copy2(round_log_path, dest)
    print(f"Wrote {dest}")
    print("Run: pytest tests/integration/test_round_log_schema.py -q")
    return dest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("round_log_json", type=Path, help="Path to round_logs/*.json")
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=DEFAULT_FIXTURE_DIR,
        help="Fixture directory (default: tests/fixtures/round_logs/)",
    )
    args = parser.parse_args()
    install_fixture(args.round_log_json, output_dir=args.output_dir)


if __name__ == "__main__":
    main()
