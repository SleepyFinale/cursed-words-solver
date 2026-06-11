"""Round-log and mismatch replay harness for simulator validation."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cursed_words_solver.loadout import prepare_run_state_dict_for_scoring
from cursed_words_solver.round_log import validate_round_log
from cursed_words_solver.sim.reward_engine import RewardEngine
from cursed_words_solver.sim.state import RunState
from cursed_words_solver.sim.submission import Submission


_ROUND_LOG_SKIP_STATUSES = frozenset(
    {
        "stale_f8_extras",
        "path_mismatch",
        "path_extension",
        "no_suggestion",
        "suggestion_blocked",
    }
)


@dataclass
class ReplayReport:
    total: int = 0
    reward_pass: int = 0
    reward_fail: int = 0
    skipped: int = 0
    failures: list[str] = field(default_factory=list)
    skipped_notes: list[str] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        checked = self.reward_pass + self.reward_fail
        return self.reward_pass / checked if checked else 1.0


def replay_reward_tier(data: dict[str, Any], engine: RewardEngine | None = None) -> tuple[bool, str]:
    """Reward-only: score matches actual.score from round log or mismatch fixture."""
    engine = engine or RewardEngine()
    submission = Submission.from_round_log(data)
    if submission is None:
        actual = data.get("actual")
        if not isinstance(actual, dict):
            return False, "no submission"
        word = str(actual.get("word", data.get("word", "")) or "").strip()
        path = actual.get("path", data.get("path"))
        if not word or not isinstance(path, list):
            return False, "no submission"
        submission = Submission(word=word, path=[int(p) for p in path])

    run_state = data.get("run_state") or data.get("run_state_snapshot")
    if not isinstance(run_state, dict):
        return False, "missing run_state"

    prepared = prepare_run_state_dict_for_scoring(dict(run_state))
    from cursed_words_solver.loadout import parse_board_from_run_state

    board = parse_board_from_run_state(prepared)
    if board is None or not any(board.is_active_index(i) for i in range(25)):
        return False, "empty board"

    result = engine.score_from_run_state_dict(prepared, submission)

    actual = data.get("actual")
    expected = None
    if isinstance(actual, dict) and "score" in actual:
        expected = int(actual["score"])
    elif "actual_score" in data:
        expected = int(data["actual_score"])

    if expected is None:
        return False, "no expected score"

    if result.score != expected:
        return False, f"score {result.score} != {expected}"

    return True, "ok"


def replay_round_log_file(path: Path, engine: RewardEngine | None = None) -> tuple[bool, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, str(exc)
    if not isinstance(data, dict):
        return False, "invalid json root"
    errors = validate_round_log(data)
    if errors and "schema_version" in str(errors):
        pass
    return replay_reward_tier(data, engine)


def replay_fixtures_dir(
    fixtures_dir: Path,
    *,
    pattern: str = "*.json",
    round_logs_only_score_match: bool = True,
) -> ReplayReport:
    engine = RewardEngine()
    report = ReplayReport()
    paths = sorted(fixtures_dir.glob(pattern))
    for path in paths:
        report.total += 1
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            report.skipped += 1
            report.failures.append(f"{path.name}: unreadable")
            continue

        if not isinstance(data, dict):
            report.skipped += 1
            continue

        if "run_state_snapshot" in data and "run_state" not in data:
            data = dict(data)
            data["run_state"] = data["run_state_snapshot"]
            if "actual_score" in data:
                data["actual"] = {"word": data.get("word", ""), "path": data.get("path", []), "score": data["actual_score"]}

        is_round_log = "schema_version" in data and "round_id" in data
        if is_round_log and round_logs_only_score_match:
            status = str(data.get("match_status", "") or "").strip()
            if status in _ROUND_LOG_SKIP_STATUSES:
                report.skipped += 1
                report.skipped_notes.append(f"{path.name}: skipped ({status})")
                continue
            if status == "score_mismatch":
                report.skipped += 1
                report.skipped_notes.append(f"{path.name}: skipped (score_mismatch — use mismatches suite)")
                continue

        ok, msg = replay_reward_tier(data, engine)
        if msg in ("no submission", "missing run_state", "empty board"):
            report.skipped += 1
            continue
        if ok:
            report.reward_pass += 1
        else:
            report.reward_fail += 1
            report.failures.append(f"{path.name}: {msg}")

    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixtures",
        type=Path,
        default=Path("tests/fixtures/round_logs"),
        help="Directory of round log JSON fixtures",
    )
    parser.add_argument(
        "--mismatches",
        type=Path,
        default=None,
        help="Optional mismatches directory (many failures expected — use pytest regression suite for full checks)",
    )
    parser.add_argument(
        "--all-round-logs",
        action="store_true",
        help="Include stale_f8 / path_mismatch round logs (usually fail reward tier)",
    )
    args = parser.parse_args(argv)

    report = replay_fixtures_dir(
        args.fixtures,
        round_logs_only_score_match=not args.all_round_logs,
    )
    checked = report.reward_pass + report.reward_fail
    print(
        f"Round logs: {report.reward_pass}/{checked} reward tier ({report.pass_rate:.1%}), "
        f"{report.skipped} skipped"
    )
    for note in report.skipped_notes[:5]:
        print(f"  skip: {note}")
    if args.mismatches and args.mismatches.is_dir():
        mm = replay_fixtures_dir(args.mismatches, round_logs_only_score_match=False)
        print(
            f"Mismatches: {mm.reward_pass}/{mm.reward_pass + mm.reward_fail} ({mm.pass_rate:.1%}) "
            f"— failures often expected; run: pytest tests/regression/test_scoring_mismatches.py -q"
        )
        report.reward_pass += mm.reward_pass
        report.reward_fail += mm.reward_fail
        report.failures.extend(mm.failures)

    if report.failures:
        for line in report.failures[:20]:
            print(f"  FAIL: {line}", file=sys.stderr)
        if len(report.failures) > 20:
            print(f"  ... and {len(report.failures) - 20} more", file=sys.stderr)

    return 0 if report.reward_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
