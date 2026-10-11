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
    result, expected, error = replay_submission(data, engine)
    if error:
        return False, error
    if result.score != expected:
        return False, f"score {result.score} != {expected}"
    return True, "ok"


@dataclass
class PreparedReplay:
    """A captured submit resolved to solver inputs (storage path, F8 extras)."""

    run_state: dict[str, Any]
    board: Any
    loadout: Any
    submission: Submission
    expected: int | None
    two_wrongs: bool


def prepare_replay(data: dict[str, Any]) -> tuple[PreparedReplay | None, str]:
    """Resolve a round log / mismatch capture into (board, loadout, submission)."""
    from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state

    submission = Submission.from_round_log(data)
    if submission is None:
        actual = data.get("actual")
        if not isinstance(actual, dict):
            return None, "no submission"
        word = str(actual.get("word", data.get("word", "")) or "").strip()
        path = actual.get("path", data.get("path"))
        if not word or not isinstance(path, list):
            return None, "no submission"
        submission = Submission(word=word, path=[int(p) for p in path])

    run_state = data.get("run_state") or data.get("run_state_snapshot")
    if not isinstance(run_state, dict):
        return None, "missing run_state"

    # Round logs snapshot extras at submit time, after the word is applied (and
    # with F8-only keys like pin_* dropped); restore the pre-submit F8 values.
    extras_diff = data.get("extras_diff")
    if isinstance(extras_diff, dict) and extras_diff:
        run_state = dict(run_state)
        extras = dict(run_state.get("extras") or {})
        for key, diff in extras_diff.items():
            if isinstance(diff, dict) and diff.get("f8") not in (None, ""):
                extras[key] = diff["f8"]
        run_state["extras"] = extras

    prepared = prepare_run_state_dict_for_scoring(dict(run_state))
    board = parse_board_from_run_state(prepared)
    if board is None or not any(board.is_active_index(i) for i in range(25)):
        return None, "empty board"

    # Captured paths are in melmod index space (bottom-origin since 2026-06-30,
    # compact on Bat-shrunk grids); scoring wants storage indices. Melmod's own
    # ``path_storage`` flipped Bat-shrunk grids upside down, so recompute those.
    actual = data.get("actual")
    storage = actual.get("path_storage") if isinstance(actual, dict) else None
    from cursed_words_solver.ui.board_geometry import _is_shrunk_grid

    if _is_shrunk_grid(board):
        storage = None
    if isinstance(storage, list) and storage:
        submission.path = [int(p) for p in storage]
    else:
        from cursed_words_solver.ui.board_geometry import path_from_melmod_indices

        captured_at = str(data.get("round_id") or data.get("exported_at") or "") or None
        submission.path = path_from_melmod_indices(
            board, submission.path, captured_at=captured_at
        )

    expected = None
    if isinstance(actual, dict) and "score" in actual:
        expected = int(actual["score"])
    elif "actual_score" in data:
        expected = int(data["actual_score"])

    loadout = parse_run_state(prepared)
    _rack_count_at_submit(prepared, loadout, data)
    if "round_id" in data:
        _rewind_post_submit_accumulators(
            prepared, board, loadout, submission, extras_diff, expected
        )

    return (
        PreparedReplay(
            run_state=prepared,
            board=board,
            loadout=loadout,
            submission=submission,
            expected=expected,
            two_wrongs=str(prepared.get("challenge_game_class") or "") == "TwoWrongs",
        ),
        "",
    )


# Accumulator extras -> (item slug, engine state key, export = f(state), state = g(export)).
_ACCUMULATOR_EXTRAS: dict[str, tuple[str, str]] = {
    "bicycle_word_score_bonus": ("bicycle", "bonus"),
    "cards_submitted": ("bicycle", "bonus"),
    "ruler_distance": ("ruler", "distance"),
    "movie_camera_word_score_bonus": ("movie_camera", "bonus"),
    "birthday_cake_bonus": ("birthday_cake", "bonus"),
    "neapolitan_percent": ("neapolitan", "count"),
    "michael_book_bonus": ("michael_s_book", "count"),
}


def _rack_count_at_submit(run_state: dict[str, Any], loadout: Any, data: dict[str, Any]) -> None:
    """Rack size when scoring starts (round logs record it as consumables.rack_before)."""
    extras = loadout.extras
    consumables = data.get("consumables")
    rack_before = consumables.get("rack_before") if isinstance(consumables, dict) else None
    if isinstance(rack_before, list) and "round_id" in data:
        count = len(rack_before)
        extras["consumable_rack_count"] = str(count)
        run_state.setdefault("extras", {})["consumable_rack_count"] = str(count)
        return
    raw = extras.get("consumable_rack_count_at_submit")
    count: int | None = None
    if raw not in (None, ""):
        try:
            count = int(raw)
        except (TypeError, ValueError):
            count = None
    if count is None:
        consumables = data.get("consumables")
        placed = consumables.get("placements_this_round") if isinstance(consumables, dict) else None
        if not isinstance(placed, list) or not placed:
            return
        base = extras.get("consumable_rack_count")
        try:
            before = int(base) if base not in (None, "") else None
        except (TypeError, ValueError):
            before = None
        if before is None:
            rack = extras.get("consumable_rack")
            try:
                rows = json.loads(rack) if isinstance(rack, str) and rack.strip() else rack
            except json.JSONDecodeError:
                rows = None
            if not isinstance(rows, list):
                return
            before = len(rows)
        count = max(0, before - len(placed))
    extras["consumable_rack_count"] = str(count)
    run_state.setdefault("extras", {})["consumable_rack_count"] = str(count)


def _rewind_previous_word(
    run_state: dict[str, Any],
    extras: dict[str, Any],
    submission: Submission,
    diff: dict[str, Any],
    expected_score: int | None = None,
) -> None:
    """Post-submit round logs may already list the current word as the previous one."""
    restored = isinstance(diff.get("previous_word_first_letter"), dict) and diff[
        "previous_word_first_letter"
    ].get("f8") not in (None, "")
    if restored:
        return
    current = str(submission.word or "").strip().lower()
    raw = extras.get("historic_words")
    try:
        rows = json.loads(raw) if isinstance(raw, str) and raw.strip() else (raw or [])
    except json.JSONDecodeError:
        rows = []
    if not isinstance(rows, list):
        rows = []
    historic_restored = isinstance(diff.get("historic_words"), dict) and diff[
        "historic_words"
    ].get("f8") not in (None, "")
    if rows and not historic_restored:
        # Post-submit historic lists the current word last (display glyphs, so
        # match on the F8 word count or the submitted score, not the spelling).
        count_diff = diff.get("scoring_previous_words_count")
        f8_count = None
        if isinstance(count_diff, dict):
            try:
                f8_count = int(count_diff.get("f8"))
            except (TypeError, ValueError):
                f8_count = None
        last = rows[-1] if isinstance(rows[-1], dict) else {}
        if f8_count is not None and 0 <= f8_count < len(rows):
            rows = rows[:f8_count]
        elif str(last.get("word") or "").lower() == current or (
            expected_score is not None and last.get("score") == expected_score
        ):
            rows = rows[:-1]
        extras["historic_words"] = json.dumps(rows)
    prior = [r for r in rows if isinstance(r, dict) and str(r.get("word") or "").strip()]
    if prior:
        letter = str(prior[-1]["word"]).strip()[0].lower()
        if not letter.isalpha():
            letter = ""  # first tile was a glyph (item / currency / number)
    else:
        letter = str(extras.get("previous_word_first_letter") or "").strip().lower()
        if current and letter == current[0]:
            letter = ""
    extras["previous_word_first_letter"] = letter
    run_state.setdefault("extras", {})["previous_word_first_letter"] = letter
    run_state["extras"]["historic_words"] = extras.get("historic_words", "")


def _rewind_post_submit_accumulators(
    run_state: dict[str, Any],
    board: Any,
    loadout: Any,
    submission: Submission,
    extras_diff: Any,
    expected_score: int | None = None,
) -> None:
    """Round logs export extras after the word scored: rewind this word's increments.

    Keys restored from ``extras_diff`` already hold the pre-word F8 value. For the
    rest, score once with the post-submit values and subtract each counter's
    increment (increments never depend on the prior value).
    """
    from cursed_words_solver.engine import EnginePlan

    diff = extras_diff if isinstance(extras_diff, dict) else {}
    extras = loadout.extras
    _rewind_previous_word(run_state, extras, submission, diff, expected_score)
    _rewind_item_states(run_state, board, loadout, submission, diff)
    pending = [
        key
        for key in _ACCUMULATOR_EXTRAS
        if key in extras
        and not (isinstance(diff.get(key), dict) and diff[key].get("f8") not in (None, ""))
    ]
    if not pending:
        return
    plan = EnginePlan.build(board, loadout)
    before = {i.slug: dict(i.state) for i in plan.stickers + plan.stamps + [plan.character_item] if i}
    result = plan.score(submission.path, submission.effective_scoring_word)
    for key in pending:
        slug, field = _ACCUMULATOR_EXTRAS[key]
        if slug not in before or field not in before[slug]:
            continue
        delta = result.final_states.get(slug, {}).get(field, 0) - before[slug][field]
        if not delta:
            continue
        try:
            post = float(extras[key])
        except (TypeError, ValueError):
            continue
        scale = 5 if key == "neapolitan_percent" else (30 if key == "michael_book_bonus" else 1)
        pre = post - delta * scale
        extras[key] = str(int(pre)) if float(pre).is_integer() else str(pre)
        run_state.setdefault("extras", {})[key] = extras[key]


def _rewind_item_states(
    run_state: dict[str, Any],
    board: Any,
    loadout: Any,
    submission: Submission,
    diff: dict[str, Any],
) -> None:
    """Rewind numeric counters in melmod ``item_states`` (exported after the word scored)."""
    from cursed_words_solver.engine import EnginePlan
    from cursed_words_solver.engine.calc import _ITEM_STATE_FIELDS

    extras = loadout.extras
    raw = extras.get("item_states")
    entry = diff.get("item_states")
    if raw in (None, "") or (isinstance(entry, dict) and entry.get("f8") not in (None, "")):
        return
    try:
        states = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return
    if not isinstance(states, dict):
        return
    plan = EnginePlan.build(board, loadout)
    live = [i for i in plan.stickers + plan.stamps + [plan.character_item] if i]
    before = [(i.slug, dict(i.state)) for i in live]
    result = plan.score(submission.path, submission.effective_scoring_word)
    after = result.final_states
    entries = [e for e in list(states.get("stickers") or []) + list(states.get("stamps") or []) + [states.get("pin")] if isinstance(e, dict)]
    changed = False
    for slug, prior in before:
        for e in entries:
            if str(e.get("id") or "").strip().lower().replace("-", "_") != slug:
                continue
            fields = e.get("fields")
            if not isinstance(fields, dict):
                break
            for field, value in list(fields.items()):
                target = _ITEM_STATE_FIELDS.get(field)
                if target is None or isinstance(value, bool) or not isinstance(value, (int, float)):
                    continue
                post = after.get(slug, {}).get(target)
                pre = prior.get(target)
                if isinstance(post, (int, float)) and isinstance(pre, (int, float)) and post != pre:
                    fields[field] = value - (post - pre)
                    changed = True
            break
    if changed:
        extras["item_states"] = json.dumps(states)
        run_state.setdefault("extras", {})["item_states"] = extras["item_states"]


def replay_submission(
    data: dict[str, Any], engine: RewardEngine | None = None
) -> tuple[Any, int | None, str]:
    """Score a captured submit; returns (RewardResult, expected score, error)."""
    engine = engine or RewardEngine()
    prep, error = prepare_replay(data)
    if prep is None:
        return None, None, error
    result = engine.score_from_run_state_dict(prep.run_state, prep.submission)
    if prep.two_wrongs:
        # EncounterController.SubmitWord negates the score; captures record that.
        result.score = -result.score
    if prep.expected is None:
        return result, None, "no expected score"
    return result, prep.expected, ""


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
