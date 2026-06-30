"""Cursedle (daily fairy trial) constraint solver — live board + guess feedback only."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, Callable

from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.fingerprints import (
    board_fingerprint,
    board_fingerprint_tiles_only_from_fp,
    fingerprints_from_run_state,
)
from cursed_words_solver.graph_bitboard import build_board_graph_context
from cursed_words_solver.models import Board, Loadout, WordResult
from cursed_words_solver.search import (
    neighbors_mask,
    path_movement_ok,
    search_word_from_path,
)
from cursed_words_solver.suggestion import SOLVER_VERSION, _next_f8_sequence
from cursed_words_solver.config import CURSEDLE_SESSION_PATH, LAST_SUGGESTION_PATH
from cursed_words_solver.ui.board_geometry import path_from_melmod_indices, path_to_melmod_indices

from datetime import datetime, timezone

CURSEDLE_SOLUTION_MIN_LEN = 4
CURSEDLE_SOLUTION_MAX_LEN = 6
CURSEDLE_PROBE_MIN_LEN = 3

# Backward-compatible aliases for solution-length filtering.
CURSEDLE_MIN_LEN = CURSEDLE_SOLUTION_MIN_LEN
CURSEDLE_MAX_LEN = CURSEDLE_SOLUTION_MAX_LEN

Feedback = str  # green | yellow | red | grey


@dataclass(frozen=True)
class CursedleGuess:
    path: list[int]
    feedback: list[Feedback]


@dataclass
class CursedleAdvice:
    word: str
    path: list[int]
    candidates: int
    guesses_used: int
    guesses_remaining: int
    reason: str
    warnings: list[str]


def cursedle_active(loadout: Loadout) -> bool:
    extras = loadout.extras if isinstance(loadout.extras, dict) else {}
    mode = str(extras.get("encounter_mode", "") or "").strip().lower()
    if mode == "cursedle":
        return True
    return str(extras.get("cursedle_active", "") or "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def parse_cursedle_guesses(extras: dict[str, Any]) -> list[CursedleGuess]:
    raw = extras.get("cursedle_guesses")
    rows: list[Any]
    if isinstance(raw, list):
        rows = raw
    elif isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            rows = parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            rows = []
    else:
        rows = []

    out: list[CursedleGuess] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        path_raw = row.get("path")
        if not isinstance(path_raw, list):
            path_raw = []
        path = [int(x) for x in path_raw]
        feedback: list[Feedback] = []
        tiles = row.get("tiles")
        if isinstance(tiles, list) and tiles:
            for tile in tiles:
                if not isinstance(tile, dict):
                    feedback.append("grey")
                    continue
                fb = str(tile.get("feedback", "grey") or "grey").strip().lower()
                feedback.append(fb if fb else "grey")
        elif len(path) > 0:
            feedback = ["grey"] * len(path)
        if path and len(feedback) == len(path):
            out.append(CursedleGuess(path=path, feedback=feedback))
    return out


def cursedle_guess_fingerprint(extras: dict[str, Any]) -> str:
    """Stable suffix for loadout fingerprint when Cursedle is active."""
    guesses = parse_cursedle_guesses(extras)
    parts: list[str] = [str(len(guesses))]
    for guess in guesses:
        seg: list[str] = []
        for idx, fb in zip(guess.path, guess.feedback):
            seg.append(f"{idx}:{fb}")
        parts.append(",".join(seg))
    return "|".join(parts)


def _coord_at(board: Board, index: int) -> tuple[int, int]:
    return board.coords_at(index)


def _are_adjacent(board: Board, a: int, b: int) -> bool:
    ra, ca = _coord_at(board, a)
    rb, cb = _coord_at(board, b)
    if (ra, ca) == (rb, cb):
        return False
    return abs(ra - rb) <= 1 and abs(ca - cb) <= 1


def _expected_feedback(
    board: Board,
    solution_path: list[int],
    guess_path: list[int],
    guess_index: int,
    guess_tile: int,
) -> Feedback:
    sol_coords = [_coord_at(board, i) for i in solution_path]
    g_coord = _coord_at(board, guess_tile)
    if g_coord in sol_coords:
        pos = sol_coords.index(g_coord)
        return "green" if pos == guess_index else "yellow"
    if any(_are_adjacent(board, guess_tile, s) for s in solution_path):
        return "red"
    return "grey"


def solution_matches_guess(
    board: Board,
    solution_path: list[int],
    guess: CursedleGuess,
) -> bool:
    if len(guess.path) != len(guess.feedback):
        return False
    for i, (tile_idx, fb) in enumerate(zip(guess.path, guess.feedback)):
        expected = _expected_feedback(board, solution_path, guess.path, i, tile_idx)
        if expected != fb:
            return False
    return True


def solution_matches_all_guesses(
    board: Board,
    solution_path: list[int],
    guesses: list[CursedleGuess],
) -> bool:
    return all(solution_matches_guess(board, solution_path, g) for g in guesses)


def enumerate_candidate_paths(
    board: Board,
    *,
    min_len: int = CURSEDLE_SOLUTION_MIN_LEN,
    max_len: int = CURSEDLE_SOLUTION_MAX_LEN,
) -> list[list[int]]:
    graph_ctx = build_board_graph_context(board)
    n = board.cell_count
    paths: list[list[int]] = []
    for start in range(n):
        if not board.is_active_index(start):
            continue
        stack: list[tuple[int, list[int], int]] = [(start, [start], 1 << start)]
        while stack:
            cell, path, visited = stack.pop()
            if len(path) >= min_len:
                paths.append(list(path))
            if len(path) >= max_len:
                continue
            mask = neighbors_mask(
                board,
                visited,
                cell_id=cell,
                flags=0,
                graph_ctx=graph_ctx,
            )
            bit = 0
            while bit < n:
                if mask & (1 << bit):
                    if board.is_active_index(bit) and not (visited & (1 << bit)):
                        stack.append(
                            (bit, path + [bit], visited | (1 << bit))
                        )
                bit += 1
    return paths


def filter_candidates(
    board: Board,
    guesses: list[CursedleGuess],
    *,
    min_len: int = CURSEDLE_SOLUTION_MIN_LEN,
    max_len: int = CURSEDLE_SOLUTION_MAX_LEN,
) -> list[list[int]]:
    candidates = enumerate_candidate_paths(board, min_len=min_len, max_len=max_len)
    if not guesses:
        return candidates
    return [
        path
        for path in candidates
        if solution_matches_all_guesses(board, path, guesses)
    ]


def _path_dictionary_word(board: Board, path: list[int], dictionary: WordDictionary) -> str | None:
    if not path_movement_ok(board, path):
        return None
    word = search_word_from_path(board, path)
    if not word:
        return None
    if dictionary.contains(word):
        return word
    return None


def _guess_storage_path(board: Board, guess_path: list[int]) -> list[int]:
    return path_from_melmod_indices(board, list(guess_path))


def _word_from_path(
    board: Board,
    path: list[int],
    dictionary: WordDictionary,
) -> str | None:
    word = _path_dictionary_word(board, path, dictionary)
    if word:
        return word.lower()
    raw = search_word_from_path(board, path)
    if not raw:
        return None
    raw = raw.lower()
    if dictionary.contains(raw) or len(raw) >= CURSEDLE_PROBE_MIN_LEN:
        return raw
    return None


def _guessed_path_keys(
    board: Board,
    guesses: list[CursedleGuess],
) -> set[tuple[int, ...]]:
    return {tuple(_guess_storage_path(board, g.path)) for g in guesses}


def _raw_word_from_path(board: Board, path: list[int]) -> str | None:
    raw = search_word_from_path(board, path)
    if not raw:
        return None
    raw = raw.lower()
    if len(raw) >= CURSEDLE_PROBE_MIN_LEN:
        return raw
    return None


def _guessed_words(
    board: Board,
    guesses: list[CursedleGuess],
    dictionary: WordDictionary,
) -> set[str]:
    words: set[str] = set()
    for guess in guesses:
        path = _guess_storage_path(board, guess.path)
        word = _word_from_path(board, path, dictionary)
        if word:
            words.add(word)
            continue
        raw = _raw_word_from_path(board, path)
        if raw:
            words.add(raw)
    return words


def _read_cursedle_session() -> dict[str, Any]:
    if not CURSEDLE_SESSION_PATH.exists():
        return {}
    try:
        data = json.loads(CURSEDLE_SESSION_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_cursedle_session(data: dict[str, Any]) -> None:
    CURSEDLE_SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
    CURSEDLE_SESSION_PATH.write_text(
        json.dumps(data, indent=2) + "\n",
        encoding="utf-8",
    )


def _session_prior_words_list(tiles_only_fp: str) -> list[str]:
    key = (tiles_only_fp or "").strip()
    if not key:
        return []
    session = _read_cursedle_session()
    entry = session.get(key)
    if not isinstance(entry, dict):
        return []
    raw_prior = entry.get("prior_words")
    if not isinstance(raw_prior, list):
        return []
    prior: list[str] = []
    for item in raw_prior:
        word = str(item or "").strip().lower()
        if word and word not in prior:
            prior.append(word)
    return prior


def _load_prior_suggested_words_from_last_suggestion(tiles_only_fp: str) -> list[str]:
    if not LAST_SUGGESTION_PATH.exists():
        return []
    try:
        data = json.loads(LAST_SUGGESTION_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, dict) or str(data.get("mode") or "").lower() != "cursedle":
        return []
    saved_tiles = board_fingerprint_tiles_only_from_fp(
        str(data.get("board_fingerprint") or "")
    )
    if saved_tiles != (tiles_only_fp or "").strip():
        return []
    prior: list[str] = []
    raw_prior = data.get("cursedle_prior_words")
    if isinstance(raw_prior, list):
        for item in raw_prior:
            word = str(item or "").strip().lower()
            if word and word not in prior:
                prior.append(word)
    last_word = str(data.get("word") or "").strip().lower()
    if last_word and last_word not in prior:
        prior.append(last_word)
    return prior


def _load_prior_suggested_words(tiles_only_fp: str) -> set[str]:
    merged: list[str] = list(_session_prior_words_list(tiles_only_fp))
    for word in _load_prior_suggested_words_from_last_suggestion(tiles_only_fp):
        if word not in merged:
            merged.append(word)
    return set(merged)


def _probe_excluded_words(
    board: Board,
    guesses: list[CursedleGuess],
    dictionary: WordDictionary,
    *,
    tiles_only_fp: str,
) -> set[str]:
    excluded = _guessed_words(board, guesses, dictionary)
    excluded |= _load_prior_suggested_words(tiles_only_fp)
    return excluded


def _path_not_already_guessed(
    board: Board,
    path: list[int],
    *,
    guessed_paths: set[tuple[int, ...]],
    excluded_words: set[str],
    dictionary: WordDictionary,
) -> bool:
    if tuple(path) in guessed_paths:
        return False
    word = _path_dictionary_word(board, path, dictionary)
    if word and word.lower() in excluded_words:
        return False
    raw = search_word_from_path(board, path)
    if raw and raw.lower() in excluded_words:
        return False
    return True


def _merge_cursedle_prior_words(
    *,
    tiles_only_fp: str,
    new_word: str,
) -> list[str]:
    merged: list[str] = list(_session_prior_words_list(tiles_only_fp))
    for word in _load_prior_suggested_words_from_last_suggestion(tiles_only_fp):
        if word not in merged:
            merged.append(word)
    normalized = (new_word or "").strip().lower()
    if normalized and normalized not in merged:
        merged.append(normalized)
    key = (tiles_only_fp or "").strip()
    if key:
        session = _read_cursedle_session()
        session[key] = {"prior_words": merged}
        _write_cursedle_session(session)
    return merged


def _feedback_bucket_for_probe(
    board: Board,
    solution_path: list[int],
    probe_path: list[int],
) -> tuple[str, ...]:
    return tuple(
        _expected_feedback(board, solution_path, probe_path, i, tile)
        for i, tile in enumerate(probe_path)
    )


_MAX_ENTROPY_CANDIDATES = 2000


def _entropy_candidate_pool(candidates: list[list[int]]) -> list[list[int]]:
    if len(candidates) <= _MAX_ENTROPY_CANDIDATES:
        return candidates
    stride = max(1, len(candidates) // _MAX_ENTROPY_CANDIDATES)
    return candidates[::stride][:_MAX_ENTROPY_CANDIDATES]


def _probe_entropy_score(
    board: Board,
    probe_path: list[int],
    candidates: list[list[int]],
) -> float:
    pool = _entropy_candidate_pool(candidates)
    buckets: dict[tuple[str, ...], int] = {}
    for solution in pool:
        key = _feedback_bucket_for_probe(board, solution, probe_path)
        buckets[key] = buckets.get(key, 0) + 1
    total = len(pool)
    if total <= 1:
        return 0.0
    entropy = 0.0
    for count in buckets.values():
        probability = count / total
        entropy -= probability * math.log2(probability)
    return entropy


def _pick_solution_path(
    board: Board,
    candidates: list[list[int]],
    dictionary: WordDictionary,
) -> tuple[list[int], str] | None:
    scored: list[tuple[str, list[int]]] = []
    for path in candidates:
        word = _path_dictionary_word(board, path, dictionary)
        if word:
            scored.append((word, path))
    if not scored:
        return None
    scored.sort(key=lambda row: (-len(row[0]), row[0]))
    word, path = scored[0]
    return path, word


_MAX_PROBE_PATHS_COLLECTED = 800
_MAX_PROBE_WORDS = 400


def _enumerate_dictionary_probe_paths(
    board: Board,
    dictionary: WordDictionary,
) -> list[tuple[str, list[int]]]:
    """Dictionary-valid paths for probe guesses (any length, not just 4-6)."""
    max_len = board.cell_count
    graph_ctx = build_board_graph_context(board)
    n = board.cell_count
    by_word: dict[str, list[int]] = {}

    def record(path: list[int], word: str) -> None:
        key = word.lower()
        previous = by_word.get(key)
        if previous is None or len(path) > len(previous):
            by_word[key] = list(path)

    def dfs(cell: int, path: list[int], visited: int) -> None:
        if len(by_word) >= _MAX_PROBE_PATHS_COLLECTED:
            return
        if not path_movement_ok(board, path):
            return
        partial = search_word_from_path(board, path)
        if not partial or not dictionary.has_prefix(partial):
            return
        if dictionary.is_valid_word(partial, CURSEDLE_PROBE_MIN_LEN):
            record(path, partial)
        if len(path) >= max_len:
            return
        mask = neighbors_mask(
            board,
            visited,
            cell_id=cell,
            flags=0,
            graph_ctx=graph_ctx,
        )
        bit = 0
        while bit < n:
            if mask & (1 << bit):
                if board.is_active_index(bit) and not (visited & (1 << bit)):
                    dfs(bit, path + [bit], visited | (1 << bit))
            bit += 1

    for start in range(n):
        if not board.is_active_index(start):
            continue
        dfs(start, [start], 1 << start)

    options = sorted(by_word.items(), key=lambda row: (-len(row[0]), row[0]))
    return options[:_MAX_PROBE_PATHS_COLLECTED]


def _probe_word_options(
    board: Board,
    dictionary: WordDictionary,
    guesses: list[CursedleGuess],
    *,
    tiles_only_fp: str = "",
) -> list[tuple[str, list[int]]]:
    """Dictionary probe words on the board, excluding prior guesses and F8 picks."""
    guessed_paths = _guessed_path_keys(board, guesses)
    excluded_words = _probe_excluded_words(
        board, guesses, dictionary, tiles_only_fp=tiles_only_fp
    )
    options: list[tuple[str, list[int]]] = []
    for word, path in _enumerate_dictionary_probe_paths(board, dictionary):
        if not _path_not_already_guessed(
            board,
            path,
            guessed_paths=guessed_paths,
            excluded_words=excluded_words,
            dictionary=dictionary,
        ):
            continue
        options.append((word, path))
        if len(options) >= _MAX_PROBE_WORDS:
            break
    return options


def _probe_reason(word: str, solution_candidate_count: int) -> str:
    if len(word) > CURSEDLE_SOLUTION_MAX_LEN:
        return (
            f"Probe ({len(word)} letters) among "
            f"{solution_candidate_count} solution candidates"
        )
    return f"Probe among {solution_candidate_count} solution candidates"


def _pick_probe_path(
    board: Board,
    candidates: list[list[int]],
    dictionary: WordDictionary,
    guesses: list[CursedleGuess],
    *,
    tiles_only_fp: str = "",
) -> tuple[list[int], str] | None:
    guessed_paths = _guessed_path_keys(board, guesses)
    excluded_words = _probe_excluded_words(
        board, guesses, dictionary, tiles_only_fp=tiles_only_fp
    )

    probe_options: list[tuple[float, int, str, list[int]]] = []
    for word, path in _probe_word_options(
        board, dictionary, guesses, tiles_only_fp=tiles_only_fp
    ):
        entropy = _probe_entropy_score(board, path, candidates)
        probe_options.append((entropy, -len(path), word, path))

    if probe_options:
        probe_options.sort(key=lambda row: (-row[0], row[1], row[2]))
        _, _, word, path = probe_options[0]
        return path, word

    for _word, path in _enumerate_dictionary_probe_paths(board, dictionary):
        if _path_not_already_guessed(
            board,
            path,
            guessed_paths=guessed_paths,
            excluded_words=excluded_words,
            dictionary=dictionary,
        ):
            return path, _word

    if candidates:
        return _pick_solution_path(board, candidates, dictionary)
    return None


def run_cursedle_solver(
    board: Board,
    loadout: Loadout,
    dictionary: WordDictionary,
    *,
    on_progress: Callable[[str], None] | None = None,
) -> CursedleAdvice:
    extras = loadout.extras if isinstance(loadout.extras, dict) else {}
    guesses = parse_cursedle_guesses(extras)
    try:
        guesses_used = int(extras.get("cursedle_guesses_used") or 0)
    except (TypeError, ValueError):
        guesses_used = len(guesses)
    try:
        guesses_remaining = int(extras.get("cursedle_guesses_remaining") or 0)
    except (TypeError, ValueError):
        guesses_remaining = max(0, 5 - guesses_used)

    warnings: list[str] = []
    if guesses_used > 0 and len(guesses) < guesses_used:
        warnings.append(
            f"Cursedle guess history incomplete ({len(guesses)}/{guesses_used}) — rebuild melmod."
        )

    if on_progress:
        on_progress("Filtering Cursedle candidates…")

    candidates = filter_candidates(board, guesses)
    unique_lengths = {len(p) for p in candidates}

    if on_progress:
        on_progress(f"{len(candidates)} path(s) match feedback")

    tiles_only_fp = board_fingerprint(board)

    pick: tuple[list[int], str] | None = None
    reason = ""
    if len(candidates) == 1:
        pick = _pick_solution_path(board, candidates, dictionary)
        reason = "Unique solution path from feedback"
    elif len(candidates) > 1:
        if guesses_remaining == 1:
            pick = _pick_solution_path(board, candidates, dictionary)
            reason = (
                f"Final guess; best dictionary match among {len(candidates)} candidates"
            )
        else:
            # Prefer exact-length solutions when narrowed to one length.
            if len(unique_lengths) == 1:
                pick = _pick_solution_path(board, candidates, dictionary)
                reason = (
                    f"Single length ({next(iter(unique_lengths))}); "
                    "best dictionary match"
                )
            if pick is None:
                if on_progress:
                    on_progress("Collecting probe words…")
                pick = _pick_probe_path(
                    board,
                    candidates,
                    dictionary,
                    guesses,
                    tiles_only_fp=tiles_only_fp,
                )
                if pick is not None:
                    reason = _probe_reason(pick[1], len(candidates))
    else:
        warnings.append("No paths satisfy guess feedback — check export/history.")
        if on_progress:
            on_progress("Collecting probe words…")
        pick = _pick_probe_path(
            board, [], dictionary, guesses, tiles_only_fp=tiles_only_fp
        )
        reason = "No consistent solution candidates; suggesting exploratory word"

    if pick is None:
        return CursedleAdvice(
            word="",
            path=[],
            candidates=len(candidates),
            guesses_used=guesses_used,
            guesses_remaining=guesses_remaining,
            reason="No valid dictionary path found",
            warnings=warnings + ["No valid word on board for current constraints."],
        )

    path, word = pick
    return CursedleAdvice(
        word=word,
        path=path,
        candidates=len(candidates),
        guesses_used=guesses_used,
        guesses_remaining=guesses_remaining,
        reason=reason,
        warnings=warnings,
    )


def format_cursedle_advice_text(advice: CursedleAdvice) -> str:
    lines = [
        f"Cursedle: {advice.word.upper() or '(none)'}",
        f"  Guesses used: {advice.guesses_used}, remaining: {advice.guesses_remaining}",
        f"  Candidates: {advice.candidates}",
        f"  {advice.reason}",
    ]
    if advice.path:
        lines.append(f"  Path: {' → '.join(str(i) for i in advice.path)}")
    for warn in advice.warnings:
        lines.append(f"  Warning: {warn}")
    return "\n".join(lines)


def save_cursedle_suggestion(
    *,
    board: Board,
    loadout: Loadout,
    advice: CursedleAdvice,
    run_state_snapshot: dict[str, Any] | None = None,
    export_diagnostics: dict[str, Any] | None = None,
    export_warnings: list[str] | None = None,
    gather_status: dict[str, Any] | None = None,
) -> None:
    if not advice.path or not advice.word:
        return
    if not path_movement_ok(board, advice.path):
        return

    board_fp = ""
    loadout_fp = ""
    if run_state_snapshot is not None:
        board_fp, loadout_fp = fingerprints_from_run_state(run_state_snapshot)

    tiles_only_fp = board_fingerprint(board)

    payload: dict[str, Any] = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "f8_sequence": _next_f8_sequence(),
        "solver_version": SOLVER_VERSION,
        "mode": "cursedle",
        "word": advice.word,
        "scoring_word": advice.word,
        "path": list(path_to_melmod_indices(board, advice.path)),
        "predicted_score": 0,
        "predicted_score_raw": 0,
        "predicted_trace": [],
        "board_fingerprint": board_fp,
        "loadout_fingerprint": loadout_fp,
        "cursedle_candidates": advice.candidates,
        "cursedle_reason": advice.reason,
        "cursedle_prior_words": _merge_cursedle_prior_words(
            tiles_only_fp=tiles_only_fp,
            new_word=advice.word,
        ),
    }
    if run_state_snapshot is not None:
        payload["run_state_snapshot"] = run_state_snapshot
    if export_diagnostics:
        payload["export_diagnostics"] = export_diagnostics
    if export_warnings:
        payload["export_warnings"] = list(export_warnings)
    if gather_status:
        payload["gather_status"] = dict(gather_status)

    LAST_SUGGESTION_PATH.parent.mkdir(parents=True, exist_ok=True)
    LAST_SUGGESTION_PATH.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
