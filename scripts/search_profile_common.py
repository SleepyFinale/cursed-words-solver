"""Shared fixture loading and discovery for search profiling scripts."""

from __future__ import annotations

import json
from pathlib import Path

from cursed_words_solver.config import (
    CONFIG_PATH,
    GAME_WORDLIST_PATH,
    RUN_STATE_PATH,
    ensure_wordlist,
)
from cursed_words_solver.encounter_board import effective_board_for_loadout
from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
from cursed_words_solver.rules.pipeline import ScoringPipeline

ROOT = Path(__file__).resolve().parents[1]
ROUND_LOG_DIR = Path.home() / ".cursed_words_solver" / "round_logs"
ROUND_LOG_INDEX = ROUND_LOG_DIR / "index.jsonl"

PROFILE_SEARCH_DEFAULT_FIXTURES = [
    ROOT / "tests" / "fixtures" / "mismatches" / "20260525_172555.json",
    ROOT / "tests" / "fixtures" / "mismatches" / "ayms_board_snapshot.json",
    ROOT / "tests" / "fixtures" / "mismatches" / "20260526_231923.json",
]


def hit_pct(hits: int, misses: int) -> float:
    total = hits + misses
    return 100.0 * hits / total if total else 0.0


def resolve_wordlist(explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit
    if GAME_WORDLIST_PATH.exists() and GAME_WORDLIST_PATH.stat().st_size > 1024:
        return GAME_WORDLIST_PATH
    return ensure_wordlist()


def default_budget_from_config(fallback: float) -> float:
    if CONFIG_PATH.is_file():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            return float(data.get("search_time_budget_sec", fallback))
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    return fallback


def load_from_mismatch(path: Path) -> tuple:
    from tests.regression.test_scoring_mismatches import _run_state_for_replay

    data = json.loads(path.read_text(encoding="utf-8"))
    run_state = _run_state_for_replay(data)
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    if board is None:
        raise ValueError(f"No board in {path}")
    pipeline = ScoringPipeline()
    board = effective_board_for_loadout(board, loadout, pipeline.rules)
    return board, loadout, path.stem


def load_from_run_state(path: Path) -> tuple:
    data = json.loads(path.read_text(encoding="utf-8"))
    board = parse_board_from_run_state(data)
    loadout = parse_run_state(data)
    if board is None:
        raise ValueError(f"No board in {path}")
    pipeline = ScoringPipeline()
    board = effective_board_for_loadout(board, loadout, pipeline.rules)
    return board, loadout, path.stem


def load_from_round_log(path: Path) -> tuple:
    data = json.loads(path.read_text(encoding="utf-8"))
    run_state = data.get("run_state")
    if not isinstance(run_state, dict):
        raise ValueError("missing run_state")
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    if board is None:
        raise ValueError("no board in run_state")
    pipeline = ScoringPipeline()
    board = effective_board_for_loadout(board, loadout, pipeline.rules)
    status = str(data.get("match_status") or "?")
    rid = str(data.get("round_id") or path.stem)
    label = f"{rid[:17]} ({status})"
    return board, loadout, label


def load_from_nested_run_state(path: Path) -> tuple:
    data = json.loads(path.read_text(encoding="utf-8"))
    run_state = data.get("run_state") or data
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    if board is None:
        raise ValueError(f"No board in {path}")
    pipeline = ScoringPipeline()
    board = effective_board_for_loadout(board, loadout, pipeline.rules)
    return board, loadout, path.stem


def load_fixture_auto(path: Path, *, round_log: bool = False) -> tuple:
    """Return (board, loadout, label) for any supported fixture format."""
    if round_log:
        return load_from_round_log(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    if "run_state_snapshot" in raw:
        return load_from_mismatch(path)
    if isinstance(raw.get("board"), dict) and "tiles" in raw["board"]:
        return load_from_run_state(path)
    if isinstance(raw.get("run_state"), dict):
        if "round_id" in raw or "match_status" in raw:
            return load_from_round_log(path)
        return load_from_nested_run_state(path)
    return load_from_mismatch(path)


def collect_fixture_paths(
    *,
    paths: list[Path],
    count: int,
    mismatches_dir: Path,
    default_fixtures: list[Path] | None = None,
) -> list[Path]:
    if paths:
        return paths
    if count > 0 and mismatches_dir.is_dir():
        all_json = sorted(
            mismatches_dir.glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return all_json[:count]
    fixtures = default_fixtures if default_fixtures is not None else PROFILE_SEARCH_DEFAULT_FIXTURES
    return [p for p in fixtures if p.exists()]


def collect_round_log_paths(
    *,
    mismatches_only: bool,
    max_rounds: int,
    sample_every: int,
) -> list[Path]:
    if not ROUND_LOG_INDEX.is_file():
        raise SystemExit(f"Round log index not found: {ROUND_LOG_INDEX}")
    paths: list[Path] = []
    for line in ROUND_LOG_INDEX.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        status = str(entry.get("match_status") or "")
        if mismatches_only and status != "score_mismatch":
            continue
        file_path = Path(str(entry.get("file") or ""))
        if not file_path.is_file():
            alt = ROUND_LOG_DIR / (entry.get("round_id", "") + ".json")
            if alt.is_file():
                file_path = alt
            else:
                continue
        paths.append(file_path)
    if sample_every > 1:
        paths = paths[::sample_every]
    if max_rounds > 0:
        paths = paths[:max_rounds]
    return paths
