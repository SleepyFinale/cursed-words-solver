"""Validate submitted word paths against run state (debug / round-log reproduction)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cursed_words_solver.config import resolve_wordlist
from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.encounter_board import effective_board_for_loadout
from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
from cursed_words_solver.models import Board, Loadout
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.quest_effects import quest_constraints, quest_path_allowed
from cursed_words_solver.search import WordSearcher, search_word_from_path
from cursed_words_solver.solve_context import build_solve_context
from cursed_words_solver.suggestion import game_word_for_path


@dataclass
class ValidationReport:
    """Outcome of validating a path on a run-state board."""

    path: list[int]
    search_word: str = ""
    dictionary_word: str = ""
    quest_allowed: bool = False
    word_ok: bool = False
    search_accepted: bool = False
    predicted_score: float = 0.0
    reject_reasons: list[str] = field(default_factory=list)

    @property
    def accepted(self) -> bool:
        return self.quest_allowed and self.search_accepted


def _load_run_state(source: dict[str, Any] | Path) -> dict[str, Any]:
    if isinstance(source, Path):
        data = json.loads(source.read_text(encoding="utf-8"))
    else:
        data = source
    if "run_state" in data and isinstance(data["run_state"], dict):
        return data["run_state"]
    if "run_state_snapshot" in data and isinstance(data["run_state_snapshot"], dict):
        return data["run_state_snapshot"]
    return data


def validate_submitted_path(
    run_state: dict[str, Any] | Path,
    path: list[int],
    *,
    dictionary: WordDictionary | None = None,
    loadout: Loadout | None = None,
    board: Board | None = None,
    min_len: int = 1,
) -> ValidationReport:
    """Check whether path is playable and scores on the given run state."""
    data = _load_run_state(run_state)
    report = ValidationReport(path=list(path))
    parsed_board = board if board is not None else parse_board_from_run_state(data)
    parsed_loadout = loadout if loadout is not None else parse_run_state(data)
    if parsed_board is None:
        report.reject_reasons.append("no_board")
        return report
    if dictionary is None:
        dictionary = WordDictionary(resolve_wordlist("game"))
    rules = ScoringPipeline().rules
    board_eff = effective_board_for_loadout(parsed_board, parsed_loadout, rules)
    flags = build_solve_context(parsed_loadout, rules).search_flags
    search_word = search_word_from_path(board_eff, path, flags=flags)
    report.search_word = search_word
    report.dictionary_word = game_word_for_path(
        board_eff,
        path,
        search_word,
        parsed_loadout,
        dictionary,
        min_len=min_len,
    )
    report.quest_allowed = quest_path_allowed(
        board_eff, path, loadout=parsed_loadout
    )
    if not report.quest_allowed:
        center = quest_constraints(parsed_loadout).require_center_index
        if center is not None and center not in path:
            report.reject_reasons.append("up_and_up_center_not_in_path")
        else:
            report.reject_reasons.append("quest_path_not_allowed")

    searcher = WordSearcher(dictionary=dictionary, min_len=min_len)
    searcher.validator.quest_loadout = parsed_loadout
    report.word_ok = searcher.validator.word_ok(
        board_eff, path, report.dictionary_word, flags
    )
    accepted, _ = searcher._accept_path_for_search(
        board_eff,
        path,
        search_word,
        parsed_loadout,
        flags,
    )
    report.search_accepted = accepted
    if not report.word_ok:
        report.reject_reasons.append("word_not_ok")
    if not report.search_accepted:
        report.reject_reasons.append("search_not_accepted")

    if report.search_accepted:
        ctx = build_solve_context(parsed_loadout, rules)
        report.predicted_score = searcher.scoring.score_total_only(
            board_eff,
            path,
            report.dictionary_word,
            parsed_loadout,
            solve_context=ctx,
        )
    return report


def path_from_round_log(data: dict[str, Any]) -> list[int] | None:
    """Extract submitted path from a companion round log."""
    actual = data.get("actual")
    if isinstance(actual, dict):
        raw = actual.get("path")
        if isinstance(raw, list):
            return [int(x) for x in raw]
    return None


def format_validation_report(report: ValidationReport) -> str:
    lines = [
        f"path: {report.path}",
        f"search_word: {report.search_word!r}",
        f"dictionary_word: {report.dictionary_word!r}",
        f"quest_allowed: {report.quest_allowed}",
        f"word_ok: {report.word_ok}",
        f"search_accepted: {report.search_accepted}",
        f"accepted: {report.accepted}",
    ]
    if report.predicted_score:
        lines.append(f"predicted_score: {report.predicted_score:.1f}")
    if report.reject_reasons:
        lines.append(f"reject_reasons: {', '.join(report.reject_reasons)}")
    return "\n".join(lines)


def cli_validate_path(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Validate a word path on a run state")
    parser.add_argument(
        "--round-log",
        type=Path,
        help="Round log JSON (uses actual.path and run_state)",
    )
    parser.add_argument(
        "--run-state",
        type=Path,
        help="run_state.json (or fixture with run_state_snapshot)",
    )
    parser.add_argument(
        "--path",
        help="Comma-separated cell indices (overrides round-log path)",
    )
    parser.add_argument("--min-len", type=int, default=1)
    args = parser.parse_args(argv)

    if args.round_log is None and args.run_state is None:
        parser.error("provide --round-log or --run-state")
    source: dict[str, Any] | Path
    path: list[int] | None = None
    if args.round_log is not None:
        source = args.round_log
        data = json.loads(args.round_log.read_text(encoding="utf-8"))
        path = path_from_round_log(data)
    else:
        source = args.run_state
    if args.path:
        path = [int(x.strip()) for x in args.path.split(",") if x.strip()]
    if not path:
        print("No path: use --path or a round log with actual.path", flush=True)
        return 1
    report = validate_submitted_path(source, path, min_len=args.min_len)
    print(format_validation_report(report), flush=True)
    return 0 if report.accepted else 1
