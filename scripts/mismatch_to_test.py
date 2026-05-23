#!/usr/bin/env python3
"""Copy a scoring_mismatches/*.json file into tests/fixtures/mismatches/."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_FIXTURE_DIR = ROOT / "tests" / "fixtures" / "mismatches"


def install_fixture(mismatch_path: Path, *, output_dir: Path | None = None) -> Path:
    data = json.loads(mismatch_path.read_text(encoding="utf-8"))
    if not data.get("run_state_snapshot"):
        raise SystemExit(
            "Mismatch file has no run_state_snapshot — re-export after playing "
            "with a solver build that writes last_suggestion.json including snapshot."
        )

    out_dir = output_dir or DEFAULT_FIXTURE_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"{mismatch_path.stem}.json"
    if dest.exists():
        print(f"Fixture already exists: {dest}", file=sys.stderr)
        return dest

    shutil.copy2(mismatch_path, dest)
    print(f"Wrote {dest}")
    print("Run: pytest tests/regression/ -k", mismatch_path.stem)
    return dest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mismatch_json", type=Path, help="Path to scoring_mismatches/*.json")
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=DEFAULT_FIXTURE_DIR,
        help="Fixture directory (default: tests/fixtures/mismatches/)",
    )
    args = parser.parse_args()
    install_fixture(args.mismatch_json, output_dir=args.output_dir)


if __name__ == "__main__":
    main()
