"""Validate / explain submitted word paths (``cursed-solver validate-path`` / ``explain``).

Everything is answered by the game-port engine: whether the game accepts the
path, which word it submits, what it scores, and where it ranks among all
words the search finds on that board.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cursed_words_solver.config import resolve_wordlist
from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
from cursed_words_solver.models import Board, Loadout


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
    data = json.loads(source.read_text(encoding="utf-8")) if isinstance(source, Path) else source
    for key in ("run_state", "run_state_snapshot"):
        if isinstance(data.get(key), dict):
            return data[key]
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
    """Check whether ``path`` (storage indices) is playable and what it scores."""
    from cursed_words_solver.engine.solver import engine_path_score, path_search
    from cursed_words_solver.search import search_word_from_path

    report = ValidationReport(path=list(path))
    data = _load_run_state(run_state) if board is None or loadout is None else {}
    board = board if board is not None else parse_board_from_run_state(data)
    loadout = loadout if loadout is not None else parse_run_state(data)
    if board is None:
        report.reject_reasons.append("no_board")
        return report
    if dictionary is None:
        dictionary = WordDictionary(resolve_wordlist("game"))
    search = path_search(board, loadout, dictionary, min_len=min_len)
    tpath = tuple(path)
    report.search_word = search_word_from_path(board, path, loadout=loadout)
    from cursed_words_solver.engine.solver import _moves_ok

    moves = _moves_ok(search, tpath)
    report.quest_allowed = search.path_allowed(tpath)
    word = search.valid_word(tpath) if moves else None
    report.word_ok = word is not None
    report.dictionary_word = word or ""
    report.search_accepted = moves and report.word_ok
    if not moves:
        report.reject_reasons.append("invalid_movement")
    if not report.quest_allowed:
        report.reject_reasons.append("quest_path_not_allowed")
    if moves and not report.word_ok:
        report.reject_reasons.append("no_valid_word")
    if report.accepted:
        report.predicted_score = float(engine_path_score(board, list(path), report.dictionary_word, loadout))
    return report


def path_from_round_log(data: dict[str, Any]) -> list[int] | None:
    """Submitted path from a capture, in storage indices."""
    from cursed_words_solver.sim.replay import prepare_replay

    prep, _err = prepare_replay(data)
    if prep is not None:
        return list(prep.submission.path)
    return None


def format_validation_report(report: ValidationReport) -> str:
    lines = [
        f"path: {report.path}",
        f"face spelling: {report.search_word!r}",
        f"game word: {report.dictionary_word!r}",
        f"quest_allowed: {report.quest_allowed}",
        f"word_ok: {report.word_ok}",
        f"accepted: {report.accepted}",
    ]
    if report.accepted:
        lines.append(f"predicted_score: {report.predicted_score:.0f}")
    if report.reject_reasons:
        lines.append(f"reject_reasons: {', '.join(report.reject_reasons)}")
    return "\n".join(lines)


@dataclass
class ExplainReport:
    """How a submitted path compares with what the solver suggested / can find."""

    validation: ValidationReport
    f8_word: str = ""
    f8_score: float = 0.0
    actual_score: int | None = None
    best_word: str = ""
    best_score: float = 0.0
    submitted_rank: int | None = None
    searched: int = 0
    exhaustive: bool = True
    match_status: str = ""


def explain_submitted_path(
    data: dict[str, Any],
    *,
    dictionary: WordDictionary | None = None,
    top_n: int = 10,
    time_budget: float = 30.0,
) -> ExplainReport | None:
    """Replay a round log / mismatch: validate the submitted path and rank it
    against a fresh engine search on the same (pre-submit) board."""
    from cursed_words_solver.search import WordSearcher
    from cursed_words_solver.sim.replay import prepare_replay

    prep, _err = prepare_replay(data)
    if prep is None:
        return None
    dictionary = dictionary or WordDictionary(resolve_wordlist("game"))
    path = list(prep.submission.path)
    validation = validate_submitted_path(
        prep.run_state, path, dictionary=dictionary, loadout=prep.loadout, board=prep.board
    )
    solver = data.get("solver") or {}
    report = ExplainReport(
        validation=validation,
        f8_word=str(solver.get("word") or ""),
        f8_score=float(solver.get("predicted_score") or 0),
        actual_score=prep.expected,
        match_status=str(data.get("match_status") or ""),
    )
    searcher = WordSearcher(dictionary=dictionary, min_len=1, max_len=25, time_budget=time_budget)
    results = searcher.find_best_words(prep.board, prep.loadout, top_n=max(top_n, 200))
    report.searched = len(results)
    report.exhaustive = bool(searcher.last_exact_info.get("exhaustive", True))
    if results:
        report.best_word = results[0].word
        report.best_score = float(results[0].score)
    for i, result in enumerate(results, 1):
        if list(result.path) == path or result.word == validation.dictionary_word:
            report.submitted_rank = i
            break
    return report


def format_explain_report(report: ExplainReport) -> str:
    lines = [
        f"match_status: {report.match_status or 'n/a'}",
        format_validation_report(report.validation),
    ]
    if report.actual_score is not None:
        lines.append(f"game score: {report.actual_score}")
    lines += [
        "",
        f"F8 suggestion: {report.f8_word!r} ({report.f8_score:.0f})",
        f"best found now: {report.best_word!r} ({report.best_score:.0f})"
        + ("" if report.exhaustive else " [search hit its time limit]"),
    ]
    if report.submitted_rank is not None:
        lines.append(f"submitted word rank: #{report.submitted_rank} of {report.searched}")
    else:
        lines.append(f"submitted word not among the top {report.searched}")
    return "\n".join(lines)


def cli_explain(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Compare a submitted path with the solver's search")
    parser.add_argument("--round-log", type=Path)
    parser.add_argument("--mismatch", type=Path)
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--budget", type=float, default=30.0, help="search seconds")
    args = parser.parse_args(argv)
    if not args.round_log and not args.mismatch:
        parser.error("provide --round-log or --mismatch")
    source = args.round_log or args.mismatch
    data = json.loads(source.read_text(encoding="utf-8"))
    report = explain_submitted_path(data, top_n=args.top_n, time_budget=args.budget)
    if report is None:
        print("Could not explain: missing run_state or path", flush=True)
        return 1
    print(format_explain_report(report), flush=True)
    return 0 if report.validation.accepted else 1


def cli_validate_path(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Validate a word path on a run state")
    parser.add_argument("--round-log", type=Path, help="Round log / mismatch JSON (uses the submitted path)")
    parser.add_argument("--run-state", type=Path, help="run_state.json")
    parser.add_argument("--path", help="Comma-separated storage indices (overrides the round-log path)")
    parser.add_argument("--min-len", type=int, default=1)
    args = parser.parse_args(argv)
    if args.round_log is None and args.run_state is None:
        parser.error("provide --round-log or --run-state")
    path: list[int] | None = None
    if args.path:
        path = [int(x.strip()) for x in args.path.split(",") if x.strip()]
    if args.round_log is not None:
        from cursed_words_solver.sim.replay import prepare_replay

        data = json.loads(args.round_log.read_text(encoding="utf-8"))
        prep, err = prepare_replay(data)
        if prep is None:
            print(f"Cannot replay: {err}", flush=True)
            return 1
        report = validate_submitted_path(
            prep.run_state, path or list(prep.submission.path),
            loadout=prep.loadout, board=prep.board, min_len=args.min_len,
        )
    else:
        if not path:
            print("No path: use --path", flush=True)
            return 1
        report = validate_submitted_path(args.run_state, path, min_len=args.min_len)
    print(format_validation_report(report), flush=True)
    return 0 if report.accepted else 1
