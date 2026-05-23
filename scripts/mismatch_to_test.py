#!/usr/bin/env python3
"""Generate a pytest regression from a scoring_mismatches/*.json file."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return s or "mismatch"


def _json_as_python_literal(obj: object) -> str:
    """Serialize for embedding in generated pytest source (JSON null → None)."""
    return (
        json.dumps(obj, indent=4)
        .replace("null", "None")
        .replace("true", "True")
        .replace("false", "False")
    )


def generate_test(mismatch_path: Path, *, output: Path | None = None) -> str:
    data = json.loads(mismatch_path.read_text(encoding="utf-8"))
    word = data["word"]
    path = data["path"]
    actual = int(data["actual_score"])
    run_state = data.get("run_state_snapshot")
    if not run_state:
        raise SystemExit(
            "Mismatch file has no run_state_snapshot — re-export after playing "
            "with a solver build that writes last_suggestion.json including snapshot."
        )

    test_name = f"test_mismatch_{_slug(mismatch_path.stem)}"
    body = f'''
def {test_name}():
    """Regression from mismatch {{}}."""
    from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
    from cursed_words_solver.rules.pipeline import ScoringPipeline

    run_state = {_json_as_python_literal(run_state)}
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    pipeline = ScoringPipeline()
    score, _bd = pipeline.score(board, {path!r}, {word!r}, loadout)
    assert int(score) == {actual}
'''
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        header = '"""Auto-generated from scoring mismatch."""\n\n'
        if output.exists():
            existing = output.read_text(encoding="utf-8")
            if test_name in existing:
                print(f"Test {test_name} already in {output}", file=sys.stderr)
                return test_name
            output.write_text(existing + body, encoding="utf-8")
        else:
            output.write_text(header + body.lstrip(), encoding="utf-8")
        print(f"Appended {test_name} to {output}")
    return body


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mismatch_json", type=Path, help="Path to scoring_mismatches/*.json")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=ROOT / "tests" / "test_scoring_mismatches_generated.py",
        help="Append pytest case to this file",
    )
    parser.add_argument(
        "--print",
        action="store_true",
        help="Print test source to stdout instead of writing",
    )
    args = parser.parse_args()
    text = generate_test(args.mismatch_json, output=None if args.print else args.output)
    if args.print:
        print(text)


if __name__ == "__main__":
    main()
