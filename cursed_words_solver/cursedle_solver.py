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
from cursed_words_solver.models import Board, Loadout
from cursed_words_solver.rules.scoring_conditions import is_poker_card_tile
from cursed_words_solver.rules.stamp_behaviors import FLAG_CARD_SUIT_FIRST_LETTER
from cursed_words_solver.search import (
    neighbors_mask,
    path_movement_ok,
    physical_word_for_path,
    search_word_from_path,
)
from cursed_words_solver.suggestion import SOLVER_VERSION, _next_f8_sequence
from cursed_words_solver.config import LAST_SUGGESTION_PATH
from cursed_words_solver.ui.board_geometry import path_from_melmod_indices, path_to_melmod_indices

from datetime import datetime, timezone

CURSEDLE_SOLUTION_MIN_LEN = 4
CURSEDLE_SOLUTION_MAX_LEN = 6
CURSEDLE_PROBE_MIN_LEN = 3
CURSEDLE_SOLUTION_COMMIT_THRESHOLD = 3
CURSEDLE_DICT_FILTER_MAX_CANDIDATES = 10_000

# Backward-compatible aliases for solution-length filtering.
CURSEDLE_MIN_LEN = CURSEDLE_SOLUTION_MIN_LEN
CURSEDLE_MAX_LEN = CURSEDLE_SOLUTION_MAX_LEN

Feedback = str  # green | yellow | red | grey

_MAX_ENTROPY_CANDIDATES = 2000
_FULL_POOL_CANDIDATE_LIMIT = 5000
_MAX_PROBE_PATHS_COLLECTED = 800
_MAX_PROBE_WORDS = 400
_MAX_PROBE_PATHS_COLLECTED_RELAXED = 800
_MAX_PROBE_WORDS_RELAXED = 400
_MAX_TILE_OVERLAP_FRACTION = 0.5


@dataclass(frozen=True)
class CursedleGuess:
    path: list[int]
    feedback: list[Feedback]
    storage_coords: tuple[tuple[int, int], ...] = ()


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
        storage_coords: list[tuple[int, int]] = []
        tiles = row.get("tiles")
        if isinstance(tiles, list) and tiles:
            cols_guess = max(
                (int(t.get("col", 0)) + 1 for t in tiles if isinstance(t, dict)),
                default=6,
            )
            for tile in tiles:
                if not isinstance(tile, dict):
                    feedback.append("grey")
                    continue
                fb = str(tile.get("feedback", "grey") or "grey").strip().lower()
                feedback.append(fb if fb else "grey")
                try:
                    tile_row = int(tile.get("row"))
                    tile_col = int(tile.get("col"))
                except (TypeError, ValueError):
                    storage_coords = []
                    break
                # Legacy exports used Unity y (bottom=0) as row with melmod index.
                try:
                    tile_index = int(tile.get("index"))
                except (TypeError, ValueError):
                    tile_index = None
                unity_idx = tile_row * cols_guess + tile_col
                if (
                    tile_index is not None
                    and tile_index == unity_idx
                    and tile_row < cols_guess // 2
                ):
                    tile_row = cols_guess - 1 - tile_row
                storage_coords.append((tile_row, tile_col))
        elif len(path) > 0:
            feedback = ["grey"] * len(path)
        if path and len(feedback) == len(path):
            coords: tuple[tuple[int, int], ...] = ()
            if len(storage_coords) == len(path):
                coords = tuple(storage_coords)
            out.append(CursedleGuess(path=path, feedback=feedback, storage_coords=coords))
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
    guess_path = _guess_storage_path(board, guess.path, guess)
    for i, (tile_idx, fb) in enumerate(zip(guess_path, guess.feedback)):
        expected = _expected_feedback(board, solution_path, guess_path, i, tile_idx)
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


def _primary_cursedle_flags(board: Board) -> int:
    """Search flags for fairy-grid theme tiles (e.g. Card Shark suit letters)."""
    for idx in range(board.cell_count):
        if not board.is_active_index(idx):
            continue
        if is_poker_card_tile(board.get_by_index(idx)):
            return FLAG_CARD_SUIT_FIRST_LETTER
    return 0


def _path_dictionary_word(
    board: Board,
    path: list[int],
    dictionary: WordDictionary,
    *,
    flags: int | None = None,
) -> str | None:
    if not path_movement_ok(board, path):
        return None
    if flags is None:
        flags = _primary_cursedle_flags(board)
    word = search_word_from_path(board, path, flags=flags)
    if not word or "?" in word:
        return None
    if dictionary.contains(word):
        return word
    return None


def _path_dictionary_word_any_resolution(
    board: Board,
    path: list[int],
    dictionary: WordDictionary,
) -> str | None:
    for flags in (0, _primary_cursedle_flags(board)):
        word = _path_dictionary_word(board, path, dictionary, flags=flags)
        if word:
            return word
    phys = physical_word_for_path(board, path, flags=_primary_cursedle_flags(board))
    if phys and "?" not in phys and dictionary.contains(phys.lower()):
        return phys.lower()
    return None


def _is_valid_cursedle_solution_path(
    board: Board,
    path: list[int],
    dictionary: WordDictionary,
) -> bool:
    if not (CURSEDLE_SOLUTION_MIN_LEN <= len(path) <= CURSEDLE_SOLUTION_MAX_LEN):
        return False
    return _path_dictionary_word_any_resolution(board, path, dictionary) is not None


def _narrow_candidates_to_dictionary(
    board: Board,
    candidates: list[list[int]],
    dictionary: WordDictionary,
) -> list[list[int]]:
    """Drop paths that cannot spell a valid solution word."""
    return [
        path
        for path in candidates
        if _is_valid_cursedle_solution_path(board, path, dictionary)
    ]


def _guess_storage_path(
    board: Board,
    guess_path: list[int],
    guess: CursedleGuess | None = None,
) -> list[int]:
    path = list(guess_path)
    if guess is not None and guess.storage_coords:
        storage_from_tiles = [
            board.index_at(row, col) for row, col in guess.storage_coords
        ]
        if tuple(path) == tuple(storage_from_tiles):
            return storage_from_tiles
    return path_from_melmod_indices(board, path)


def _paths_share_prefix_walk(a: list[int], b: list[int]) -> bool:
    """True when one path is a strict prefix of the other (same tile order)."""
    if not a or not b:
        return False
    shorter, longer = (a, b) if len(a) < len(b) else (b, a)
    if len(shorter) >= len(longer):
        return False
    return longer[: len(shorter)] == shorter


def _word_from_path(
    board: Board,
    path: list[int],
    dictionary: WordDictionary,
) -> str | None:
    word = _path_dictionary_word_any_resolution(board, path, dictionary)
    if word:
        return word.lower()
    raw = search_word_from_path(board, path, flags=_primary_cursedle_flags(board))
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
    return {
        tuple(_guess_storage_path(board, g.path, g))
        for g in guesses
    }


def _guessed_melmod_path_keys(
    board: Board,
    guesses: list[CursedleGuess],
) -> set[tuple[int, ...]]:
    keys: set[tuple[int, ...]] = set()
    for guess in guesses:
        storage = _guess_storage_path(board, guess.path, guess)
        keys.add(tuple(path_to_melmod_indices(board, storage)))
        raw = tuple(guess.path)
        if raw != tuple(storage):
            keys.add(raw)
    return keys


def _raw_word_from_path(board: Board, path: list[int]) -> str | None:
    flags = _primary_cursedle_flags(board)
    raw = search_word_from_path(board, path, flags=flags)
    if not raw:
        raw = physical_word_for_path(board, path, flags=flags)
    if not raw:
        return None
    raw = raw.lower()
    if "?" in raw:
        return None
    if len(raw) >= CURSEDLE_PROBE_MIN_LEN:
        return raw
    return None


def _guessed_words(
    board: Board,
    guesses: list[CursedleGuess],
    dictionary: WordDictionary,
) -> set[str]:
    words: set[str] = set()
    flags = _primary_cursedle_flags(board)
    for guess in guesses:
        path = _guess_storage_path(board, guess.path, guess)
        word = _word_from_path(board, path, dictionary)
        if word:
            words.add(word)
        raw = _raw_word_from_path(board, path)
        if raw:
            words.add(raw)
        phys = physical_word_for_path(board, path, flags=flags)
        if phys and "?" not in phys:
            words.add(phys.lower())
    return words


def _tested_tile_indices(board: Board, guesses: list[CursedleGuess]) -> set[int]:
    tested: set[int] = set()
    for guess in guesses:
        tested.update(_guess_storage_path(board, guess.path, guess))
    return tested


def _path_tile_overlap_fraction(path: list[int], tested: set[int]) -> float:
    if not path:
        return 0.0
    overlap = sum(1 for tile in path if tile in tested)
    return overlap / len(path)


def _path_tile_novelty(path: list[int], tested: set[int]) -> float:
    return 1.0 - _path_tile_overlap_fraction(path, tested)


def _common_prefix_length(a: str, b: str) -> int:
    count = 0
    for ca, cb in zip(a, b):
        if ca != cb:
            break
        count += 1
    return count


def _is_near_duplicate_word(word: str, excluded: set[str]) -> bool:
    key = word.lower()
    for prior in excluded:
        if key == prior:
            return True
        shorter, longer = (key, prior) if len(key) <= len(prior) else (prior, key)
        if shorter and longer.startswith(shorter) and len(longer) - len(shorter) <= 2:
            return True
        min_len = min(len(key), len(prior))
        if (
            min_len >= 3
            and abs(len(key) - len(prior)) <= 1
            and _common_prefix_length(key, prior) >= min_len - 1
        ):
            return True
    return False


def _load_inflight_suggestion_word(
    tiles_only_fp: str,
    guesses_used: int,
) -> set[str]:
    """Unread suggestion word for the same board when no new guess was submitted."""
    if not LAST_SUGGESTION_PATH.exists():
        return set()
    try:
        data = json.loads(LAST_SUGGESTION_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return set()
    if not isinstance(data, dict) or str(data.get("mode") or "").lower() != "cursedle":
        return set()
    saved_tiles = board_fingerprint_tiles_only_from_fp(
        str(data.get("board_fingerprint") or "")
    )
    if saved_tiles != (tiles_only_fp or "").strip():
        return set()
    snapshot = data.get("run_state_snapshot")
    embed_extras: dict[str, Any] = {}
    if isinstance(snapshot, dict):
        raw_extras = snapshot.get("extras")
        if isinstance(raw_extras, dict):
            embed_extras = raw_extras
    try:
        saved_used = int(str(embed_extras.get("cursedle_guesses_used") or "0"))
    except (TypeError, ValueError):
        saved_used = len(parse_cursedle_guesses(embed_extras))
    if saved_used != guesses_used:
        return set()
    word = str(data.get("word") or "").strip().lower()
    return {word} if word else set()


def _probe_excluded_words(
    board: Board,
    guesses: list[CursedleGuess],
    dictionary: WordDictionary,
    *,
    tiles_only_fp: str,
    guesses_used: int,
) -> set[str]:
    excluded = _guessed_words(board, guesses, dictionary)
    excluded |= _load_inflight_suggestion_word(tiles_only_fp, guesses_used)
    return excluded


def _path_not_already_guessed(
    board: Board,
    path: list[int],
    *,
    guessed_paths: set[tuple[int, ...]],
    guessed_melmod_paths: set[tuple[int, ...]],
    excluded_words: set[str],
    dictionary: WordDictionary,
) -> bool:
    path_tuple = tuple(path)
    if path_tuple in guessed_paths:
        return False
    for guessed in guessed_paths:
        if _paths_share_prefix_walk(path, list(guessed)):
            return False
    melmod_path = tuple(path_to_melmod_indices(board, path))
    if melmod_path in guessed_melmod_paths:
        return False
    for guessed in guessed_melmod_paths:
        if _paths_share_prefix_walk(list(melmod_path), list(guessed)):
            return False
    word = _path_dictionary_word_any_resolution(board, path, dictionary)
    if word and _is_near_duplicate_word(word, excluded_words):
        return False
    if word and word.lower() in excluded_words:
        return False
    raw = search_word_from_path(board, path, flags=_primary_cursedle_flags(board))
    if raw:
        raw = raw.lower()
        if raw in excluded_words or _is_near_duplicate_word(raw, excluded_words):
            return False
    return True


def _feedback_bucket_for_probe(
    board: Board,
    solution_path: list[int],
    probe_path: list[int],
) -> tuple[str, ...]:
    return tuple(
        _expected_feedback(board, solution_path, probe_path, i, tile)
        for i, tile in enumerate(probe_path)
    )


def _entropy_candidate_pool(candidates: list[list[int]]) -> list[list[int]]:
    if len(candidates) <= _FULL_POOL_CANDIDATE_LIMIT:
        return candidates
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
        word = _path_dictionary_word_any_resolution(board, path, dictionary)
        if word:
            scored.append((word, path))
    if not scored:
        return None
    scored.sort(key=lambda row: (-len(row[0]), row[0]))
    word, path = scored[0]
    return path, word


def _pick_best_raw_candidate(
    board: Board,
    candidates: list[list[int]],
) -> tuple[list[int], str] | None:
    scored: list[tuple[str, list[int]]] = []
    for path in candidates:
        if not path_movement_ok(board, path):
            continue
        raw = _raw_word_from_path(board, path)
        if raw:
            scored.append((raw, path))
    if not scored:
        return None
    scored.sort(key=lambda row: (-len(row[0]), row[0]))
    word, path = scored[0]
    return path, word


def _pick_final_guess(
    board: Board,
    candidates: list[list[int]],
    dictionary: WordDictionary,
    guesses: list[CursedleGuess],
    *,
    tiles_only_fp: str = "",
    guesses_used: int = 0,
) -> tuple[list[int], str] | None:
    pick = _pick_solution_path(board, candidates, dictionary)
    if pick is not None:
        return pick
    pick = _pick_best_raw_candidate(board, candidates)
    if pick is not None:
        return pick
    pick = _pick_probe_path(
        board,
        candidates,
        dictionary,
        guesses,
        tiles_only_fp=tiles_only_fp,
        guesses_used=guesses_used,
    )
    if pick is not None:
        return pick
    if candidates:
        path = candidates[0]
        word = _raw_word_from_path(board, path) or physical_word_for_path(
            board, path, flags=_primary_cursedle_flags(board)
        )
        if word:
            return path, word.lower()
        return path, "?"
    return None


def _probe_limits(candidate_count: int) -> tuple[int, int]:
    if candidate_count < _FULL_POOL_CANDIDATE_LIMIT:
        return _MAX_PROBE_PATHS_COLLECTED_RELAXED, _MAX_PROBE_WORDS_RELAXED
    return _MAX_PROBE_PATHS_COLLECTED, _MAX_PROBE_WORDS


def _enumerate_dictionary_probe_paths(
    board: Board,
    dictionary: WordDictionary,
    *,
    max_collected: int = _MAX_PROBE_PATHS_COLLECTED,
) -> list[tuple[str, list[int]]]:
    """Dictionary-valid paths for probe guesses (any length, not just 4-6)."""
    max_len = board.cell_count
    graph_ctx = build_board_graph_context(board)
    n = board.cell_count
    flags = _primary_cursedle_flags(board)
    by_word: dict[str, list[int]] = {}

    def record(path: list[int], word: str) -> None:
        key = word.lower()
        previous = by_word.get(key)
        if previous is None or len(path) > len(previous):
            by_word[key] = list(path)

    def dfs(cell: int, path: list[int], visited: int) -> None:
        if len(by_word) >= max_collected:
            return
        if not path_movement_ok(board, path):
            return
        partial = search_word_from_path(board, path, flags=flags)
        if not partial or "?" in partial or not dictionary.has_prefix(partial):
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
    return options[:max_collected]


def _filter_probe_word_pairs(
    board: Board,
    dictionary: WordDictionary,
    guesses: list[CursedleGuess],
    pairs: list[tuple[str, list[int]]],
    *,
    tiles_only_fp: str,
    guesses_used: int,
) -> list[tuple[str, list[int]]]:
    guessed_paths = _guessed_path_keys(board, guesses)
    guessed_melmod_paths = _guessed_melmod_path_keys(board, guesses)
    excluded_words = _probe_excluded_words(
        board,
        guesses,
        dictionary,
        tiles_only_fp=tiles_only_fp,
        guesses_used=guesses_used,
    )
    tested = _tested_tile_indices(board, guesses)
    filtered: list[tuple[str, list[int]]] = []
    for word, path in pairs:
        if not _path_not_already_guessed(
            board,
            path,
            guessed_paths=guessed_paths,
            guessed_melmod_paths=guessed_melmod_paths,
            excluded_words=excluded_words,
            dictionary=dictionary,
        ):
            continue
        if _is_near_duplicate_word(word, excluded_words):
            continue
        filtered.append((word, path))

    return [
        pair
        for pair in filtered
        if _path_tile_overlap_fraction(pair[1], tested) <= _MAX_TILE_OVERLAP_FRACTION
    ]


def _probe_word_options(
    board: Board,
    dictionary: WordDictionary,
    guesses: list[CursedleGuess],
    *,
    tiles_only_fp: str = "",
    guesses_used: int = 0,
    candidate_count: int = 0,
) -> list[tuple[str, list[int]]]:
    """Dictionary probe words on the board, excluding prior guesses and in-flight F8 pick."""
    max_collected, max_words = _probe_limits(candidate_count)
    pairs = _enumerate_dictionary_probe_paths(
        board, dictionary, max_collected=max_collected
    )
    options = _filter_probe_word_pairs(
        board,
        dictionary,
        guesses,
        pairs,
        tiles_only_fp=tiles_only_fp,
        guesses_used=guesses_used,
    )
    return options[:max_words]


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
    guesses_used: int = 0,
) -> tuple[list[int], str] | None:
    candidate_count = len(candidates)
    guessed_paths = _guessed_path_keys(board, guesses)
    guessed_melmod_paths = _guessed_melmod_path_keys(board, guesses)
    excluded_words = _probe_excluded_words(
        board,
        guesses,
        dictionary,
        tiles_only_fp=tiles_only_fp,
        guesses_used=guesses_used,
    )
    tested = _tested_tile_indices(board, guesses)

    probe_options: list[tuple[float, float, float, int, str, list[int]]] = []
    for word, path in _probe_word_options(
        board,
        dictionary,
        guesses,
        tiles_only_fp=tiles_only_fp,
        guesses_used=guesses_used,
        candidate_count=candidate_count,
    ):
        entropy = _probe_entropy_score(board, path, candidates)
        novelty = _path_tile_novelty(path, tested)
        overlap = _path_tile_overlap_fraction(path, tested)
        probe_options.append(
            (entropy, novelty, -overlap, -len(path), word, path)
        )

    if probe_options:
        probe_options.sort(key=lambda row: (-row[0], -row[1], -row[2], row[3], row[4]))
        _, _, _, _, word, path = probe_options[0]
        return path, word

    max_collected, _ = _probe_limits(candidate_count)
    for _word, path in _enumerate_dictionary_probe_paths(
        board, dictionary, max_collected=max_collected
    ):
        if _path_not_already_guessed(
            board,
            path,
            guessed_paths=guessed_paths,
            guessed_melmod_paths=guessed_melmod_paths,
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

    feedback_candidates = filter_candidates(board, guesses)
    if len(feedback_candidates) <= CURSEDLE_DICT_FILTER_MAX_CANDIDATES:
        candidates = _narrow_candidates_to_dictionary(
            board, feedback_candidates, dictionary
        )
    else:
        candidates = feedback_candidates

    if on_progress:
        on_progress(f"{len(candidates)} valid word(s) match feedback")

    tiles_only_fp = board_fingerprint(board)

    pick: tuple[list[int], str] | None = None
    reason = ""
    if len(candidates) == 1:
        pick = _pick_final_guess(
            board,
            candidates,
            dictionary,
            guesses,
            tiles_only_fp=tiles_only_fp,
            guesses_used=guesses_used,
        )
        reason = "Unique solution path from feedback"
    elif len(candidates) > 1:
        if guesses_remaining == 1:
            pick = _pick_final_guess(
                board,
                candidates,
                dictionary,
                guesses,
                tiles_only_fp=tiles_only_fp,
                guesses_used=guesses_used,
            )
            reason = (
                f"Final guess; best match among {len(candidates)} candidates"
            )
        elif len(candidates) <= CURSEDLE_SOLUTION_COMMIT_THRESHOLD:
            pick = _pick_final_guess(
                board,
                candidates,
                dictionary,
                guesses,
                tiles_only_fp=tiles_only_fp,
                guesses_used=guesses_used,
            )
            reason = (
                f"Narrowed to {len(candidates)} candidates; committing to solution"
            )
        else:
            if on_progress:
                on_progress("Collecting probe words…")
            pick = _pick_probe_path(
                board,
                candidates,
                dictionary,
                guesses,
                tiles_only_fp=tiles_only_fp,
                guesses_used=guesses_used,
            )
            if pick is not None:
                reason = _probe_reason(pick[1], len(candidates))
    else:
        warnings.append("No paths satisfy guess feedback — check export/history.")
        if on_progress:
            on_progress("Collecting probe words…")
        pick = _pick_probe_path(
            board,
            [],
            dictionary,
            guesses,
            tiles_only_fp=tiles_only_fp,
            guesses_used=guesses_used,
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
    if word == "?" or "?" in word:
        warnings.append("Suggested path may not spell a clean dictionary word.")
    elif not dictionary.contains(word.lower()):
        warnings.append("Suggested word is not in the game dictionary.")

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
