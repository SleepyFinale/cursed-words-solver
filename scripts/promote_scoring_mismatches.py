#!/usr/bin/env python3
"""Promote live scoring_mismatch captures into regression fixtures and run tests."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_CAPTURE_DIR = Path.home() / ".cursed_words_solver" / "scoring_mismatches"
DEFAULT_FIXTURE_DIR = ROOT / "tests" / "fixtures" / "mismatches"


def _is_score_mismatch(path: Path) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if data.get("match_status") != "score_mismatch":
        return False
    return bool(data.get("run_state_snapshot"))


def promote_captures(
    capture_dir: Path,
    fixture_dir: Path,
    *,
    force: bool = False,
) -> list[Path]:
    """Copy new score_mismatch JSON files into tests/fixtures/mismatches/."""
    fixture_dir.mkdir(parents=True, exist_ok=True)
    promoted: list[Path] = []
    if not capture_dir.is_dir():
        print(f"Capture dir missing: {capture_dir}", file=sys.stderr)
        return promoted

    for src in sorted(capture_dir.glob("*.json")):
        if not _is_score_mismatch(src):
            continue
        dest = fixture_dir / src.name
        if dest.exists() and not force:
            continue
        shutil.copy2(src, dest)
        promoted.append(dest)
        action = "Updated" if dest.exists() else "Promoted"
        print(f"{action} {dest.relative_to(ROOT)}")
    return promoted


def run_regression(
  pytest_args: list[str],
) -> int:
    cmd = [sys.executable, "-m", "pytest", *pytest_args]
    print("Running:", " ".join(cmd))
    return subprocess.call(cmd, cwd=ROOT)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--capture-dir",
        type=Path,
        default=DEFAULT_CAPTURE_DIR,
        help=f"Live mismatch folder (default: {DEFAULT_CAPTURE_DIR})",
    )
    parser.add_argument(
        "-o",
        "--fixture-dir",
        type=Path,
        default=DEFAULT_FIXTURE_DIR,
        help="Regression fixture directory",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite fixtures that already exist",
    )
    parser.add_argument(
        "--june",
        action="store_true",
        help="After promote, run pytest tests/regression/test_scoring_mismatches.py -k 202606",
    )
    parser.add_argument(
        "--pytest-args",
        nargs=argparse.REMAINDER,
        help="Custom pytest args (default: full regression suite)",
    )
    parser.add_argument(
        "--promote-only",
        action="store_true",
        help="Skip pytest even when --june or --pytest-args is set",
    )
    args = parser.parse_args()

    promoted = promote_captures(args.capture_dir, args.fixture_dir, force=args.force)
    if not promoted:
        print("No new score_mismatch captures to promote.")

    if args.promote_only:
        return

    if args.june:
        code = run_regression(
            ["tests/regression/test_scoring_mismatches.py", "-k", "202606", "-q"]
        )
        raise SystemExit(code)

    if args.pytest_args:
        code = run_regression(args.pytest_args)
        raise SystemExit(code)

    if promoted:
        stems = " or ".join(p.stem for p in promoted)
        print(f"Suggested: pytest tests/regression/test_scoring_mismatches.py -k \"{stems}\"")


if __name__ == "__main__":
    main()
