#!/usr/bin/env python3
"""Turn melmod round logs into regression tests.

Round logs from companion >= 1.4 carry a ``capture`` block: the exact game
state before the word was scored, the submission and the game's score. Copying
one into ``tests/fixtures/captures/`` *is* the test: ``tests/engine/
test_capture_fixtures.py`` replays every file there and requires the game's
score and an accepted path.

Examples (repo root):

  python scripts/capture_to_fixture.py ~/.cursed_words_solver/round_logs/20261012_201500_123.json
  python scripts/capture_to_fixture.py --failing              # every local capture the engine mis-scores
  python scripts/capture_to_fixture.py --failing --since 20261012

Older round logs (no ``capture``) are copied to ``tests/fixtures/round_logs/``
with ``--legacy``; regenerate the legacy lists with
``python scripts/engine_replay.py --write-lists``.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CAPTURES = ROOT / "tests" / "fixtures" / "captures"
LEGACY = ROOT / "tests" / "fixtures" / "round_logs"


def slim_capture(data: dict) -> dict:
    """The parts of a round log a capture test needs (drops the legacy run_state)."""
    solver = data.get("solver") if isinstance(data.get("solver"), dict) else {}
    actual = data.get("actual") if isinstance(data.get("actual"), dict) else {}
    return {
        "round_id": data.get("round_id", ""),
        "match_status": data.get("match_status", ""),
        "actual": {"word": actual.get("word", ""), "score": actual.get("score")},
        "solver": {"word": solver.get("word", ""), "predicted_score": solver.get("predicted_score")},
        "capture": data["capture"],
    }


def fixture_name(data: dict, source: Path) -> str:
    word = str((data.get("actual") or {}).get("word") or "")
    word = re.sub(r"[^a-z0-9]+", "_", word.lower())[:24].strip("_")
    rid = str(data.get("round_id") or source.stem)
    return f"{rid}_{word}.json" if word else f"{rid}.json"


def engine_matches(data: dict) -> bool | None:
    """True / False when the engine (mis)scores the capture; None if it cannot replay."""
    from cursed_words_solver.engine import EnginePlan
    from cursed_words_solver.sim.replay import prepare_replay

    prep, _err = prepare_replay(data)
    if prep is None or prep.expected is None:
        return None
    score = EnginePlan.build(prep.board, prep.loadout).score(prep.submission.path, prep.submission.effective_scoring_word).int_score
    return (-score if prep.two_wrongs else score) == prep.expected


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="*", type=Path, help="round log JSON files")
    parser.add_argument("--failing", action="store_true", help="add every local capture the engine mis-scores")
    parser.add_argument("--since", help="with --failing: only round logs named YYYYMMDD... on or after this")
    parser.add_argument("--legacy", action="store_true", help="copy round logs without a capture to tests/fixtures/round_logs/")
    parser.add_argument("--force", action="store_true", help="overwrite existing fixtures")
    args = parser.parse_args(argv)

    files = list(args.files)
    if args.failing:
        from cursed_words_solver.config import ROUND_LOG_DIR

        files += sorted(p for p in ROUND_LOG_DIR.glob("2*.json") if not args.since or p.name[:8] >= args.since)
    if not files:
        parser.error("give round log files or --failing")

    added = 0
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"skip {path.name}: {exc}")
            continue
        has_capture = isinstance(data.get("capture"), dict) and isinstance(data["capture"].get("pre_submit"), dict)
        if args.failing:
            if not has_capture or engine_matches(data) is not False:
                continue
        if has_capture:
            dest = CAPTURES / fixture_name(data, path)
            payload = json.dumps(slim_capture(data), indent=1)
        elif args.legacy:
            dest = LEGACY / path.name
            payload = None
        else:
            print(f"skip {path.name}: no capture block (older companion); use --legacy to copy it as a legacy fixture")
            continue
        if dest.exists() and not args.force:
            print(f"exists {dest.relative_to(ROOT)}")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        if payload is None:
            shutil.copyfile(path, dest)
        else:
            dest.write_text(payload, encoding="utf-8")
        status = engine_matches(data)
        note = {True: "engine matches the game", False: "ENGINE MISMATCH (test fails until fixed)", None: "not replayable"}[status]
        print(f"added {dest.relative_to(ROOT)} -- {note}")
        added += 1
    print(f"{added} fixture(s) added.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
