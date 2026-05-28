"""Word search on 5x5 board with curse-aware movement."""

from __future__ import annotations

import heapq
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable

from concurrent.futures import ProcessPoolExecutor

from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.models import (
    CHESS_CURSES,
    CURRENCY_MAP,
    Board,
    CurseType,
    Loadout,
    Tile,
    TileColor,
    WordResult,
    normalize_tile_glyph,
)
from cursed_words_solver.encounter_board import effective_board_for_loadout
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.scoring_conditions import (
    CARD_SUIT_FIRST_LETTER,
    card_suit,
    hanafuda_hand_satisfied,
    is_card_tile,
    is_joker_tile,
    fraction_parts,
    is_fraction_tile,
    is_number_like_tile,
    number_digits_ascending,
    tile_counts_as_color,
    tile_number_value,
    word_starts_ends_different_suit,
)
from cursed_words_solver.rules.fraction_tiles import fraction_position_valid
from cursed_words_solver.fast_rank import (
    fast_rank_lower_bound,
    loadout_allows_fast_rank,
    loadout_allows_mult_prune,
    mult_aware_lower_bound,
)
from cursed_words_solver.mult_search import (
    MultNeighborHints,
    build_mult_neighbor_hints,
    loadout_mult_rules,
    neighbor_mult_priority,
    optimistic_mult_factor,
    search_rank_score,
)
from cursed_words_solver.rules.chess_tiles import (
    chess_neighbors,
    clear_chess_attack_cache,
    identical_chess_piece,
    is_chess_piece,
)
from cursed_words_solver.rules.stamp_behaviors import StampSearchFlags, stamp_search_flags
from cursed_words_solver.setup_value import (
    project_setup_delta,
    rank_score_for_word,
    setup_future_value,
)

# 8 directions
DIRS_8 = [
    (-1, -1), (-1, 0), (-1, 1),
    (0, -1),           (0, 1),
    (1, -1),  (1, 0),  (1, 1),
]

TIME_CHECK_INTERVAL = 256
DEFAULT_CANDIDATE_HEAP_SIZE = 100


@dataclass
class SearchTiming:
    """Phase timings from the last find_best_words call."""

    wall_sec: float = 0.0
    dfs_sec: float = 0.0
    extend_sec: float = 0.0
    chess_sec: float = 0.0
    seed_sec: float = 0.0
    pool_init_sec: float = 0.0
    parallel_workers: int = 1
    score_sec: float = 0.0
    setup_rank_sec: float = 0.0
    mult_rank_sec: float = 0.0
    final_score_sec: float = 0.0
    score_calls: int = 0
    worker_score_calls: int = 0
    parallel_serial_fallback: bool = False
    letter_dfs_added: int = 0
    dfs_expansions: int = 0

    @property
    def score_pct(self) -> float:
        if self.wall_sec <= 0:
            return 0.0
        return 100.0 * self.score_sec / self.wall_sec

    @property
    def explore_pct(self) -> float:
        """Wall time not spent in score_total_only (DFS, extension, seeds, etc.)."""
        if self.wall_sec <= 0:
            return 0.0
        return 100.0 * max(0.0, self.wall_sec - self.score_sec) / self.wall_sec

    def tier2_recommendation(self, *, sticker_count: int = 0) -> str:
        """Heuristic: whether Tier-2 two-phase search is likely worth it."""
        if sticker_count == 0:
            return "skip (no stickers; fast_rank already optimal)"
        if self.wall_sec < 3.0:
            return "skip (budget too small for two-phase overhead)"
        if self.score_pct >= 55.0:
            return "likely yes (scoring dominates; two-phase may help)"
        if self.score_pct >= 40.0:
            return "maybe (scoring is significant; profile more boards)"
        return "unlikely (DFS/expansion dominates; optimize search coverage first)"


def index_of(row: int, col: int) -> int:
    return row * 5 + col


def _visited_has(visited: int | set[int], idx: int) -> bool:
    if isinstance(visited, set):
        return idx in visited
    return bool(visited & (1 << idx))


def _candidate_heap_size(top_n: int, mult_rule_count: int = 0) -> int:
    base = max(top_n * 20, DEFAULT_CANDIDATE_HEAP_SIZE)
    if mult_rule_count >= 2:
        base = int(base * (1 + 0.25 * mult_rule_count))
    return base


class _CandidateHeap:
    """Min-heap of worst candidates; keeps the best K by score."""

    __slots__ = ("_k", "_heap")

    def __init__(self, k: int) -> None:
        self._k = k
        self._heap: list[tuple[float, int, str, tuple[int, ...]]] = []

    def __len__(self) -> int:
        return len(self._heap)

    def consider(self, score: float, word: str, path: list[int]) -> None:
        # Keep best candidates. For equal score, prefer longer words so that
        # late chess/board extensions with the same immediate score don't get
        # evicted by shorter prefixes.
        entry = (score, len(word), word, tuple(path))
        if len(self._heap) < self._k:
            heapq.heappush(self._heap, entry)
        elif entry > self._heap[0]:
            heapq.heapreplace(self._heap, entry)

    def min_rank_score(self) -> float | None:
        """Lowest rank_score among kept candidates, or None if heap not full."""
        if len(self._heap) < self._k:
            return None
        return self._heap[0][0]

    def best_sorted(self) -> list[tuple[float, str, tuple[int, ...]]]:
        out: list[tuple[float, str, tuple[int, ...]]] = []
        for score, _neg_len, word, path in sorted(self._heap, reverse=True):
            out.append((score, word, path))
        out.sort(key=lambda x: (-x[0], -len(x[1]), x[1]))
        return out

    def all_words_max_len(self, max_len: int) -> bool:
        if not self._heap:
            return False
        return all(len(entry[2]) <= max_len for entry in self._heap)


def resolve_letter(
    tile: Tile,
    position: int,
    *,
    flags: StampSearchFlags | None = None,
) -> str:
    """Letter used in word at 0-based position."""
    if tile.curse == CurseType.CURRENCY:
        return tile.letter
    if tile.curse == CurseType.WILDCARD:
        return "?"
    if tile.curse in CHESS_CURSES:
        return tile.letter if tile.letter != "?" else "?"
    if tile.curse == CurseType.NUMBER:
        return tile.letter
    if tile.curse == CurseType.FRACTION:
        return "?"
    if flags and flags.card_suit_first_letter and is_card_tile(tile):
        suit = card_suit(tile)
        if suit and suit in CARD_SUIT_FIRST_LETTER:
            return CARD_SUIT_FIRST_LETTER[suit]
    if (
        flags
        and flags.shiny_as_one
        and position == 0
        and tile.color == TileColor.SHINY
        and tile.curse == CurseType.LETTER
    ):
        return "1"
    ch = (tile.letter or "?").lower()
    if flags:
        if flags.red_as_s and tile.color == TileColor.RED and tile.curse == CurseType.LETTER:
            return "s"
        if flags.red_as_e and tile.color == TileColor.RED and tile.curse == CurseType.LETTER:
            return "e"
        if flags.z_as_s and ch == "z":
            return "s"
        if flags.q_as_qu and ch == "q":
            return "qu"
    return tile.letter.upper() if tile.letter else "?"


def hanafuda_sticker_level(loadout: Loadout) -> int:
    """Sticker level for Hanafuda (0 if absent)."""
    for item in loadout.stickers:
        slug = (item.id or item.name or "").strip().lower().replace(" ", "_")
        if slug == "hanafuda":
            return max(1, int(item.level or 1))
    return 0


def physical_word_for_path(
    board: Board,
    path: list[int],
    *,
    flags: StampSearchFlags | None = None,
) -> str:
    """Word from tile face letters; ignores Card Shark suit-first-letter remapping."""
    phys_flags = flags
    if flags and flags.card_suit_first_letter:
        phys_flags = replace(flags, card_suit_first_letter=False)
    parts: list[str] = []
    for i, idx in enumerate(path):
        parts.append(resolve_letter(board.get_by_index(idx), i, flags=phys_flags))
    return "".join(parts).lower()


ROMAN_BY_NUMBER: dict[int, str] = {1: "i", 5: "v", 10: "x"}


def resolve_letter_options(
    tile: Tile,
    position: int,
    *,
    flags: StampSearchFlags | None = None,
) -> list[str]:
    """Lowercase letter alternatives for search validation."""
    base = resolve_letter(tile, position, flags=flags)
    if base in ("?", "qu") or len(base) != 1:
        return [base.lower() if base != "?" else "?"]
    ch = base.lower()
    if flags and flags.j_as_h_or_y and ch == "j":
        return ["h", "y"]
    if (
        flags
        and flags.red_letter_plus_minus_one
        and tile.color == TileColor.RED
        and tile.curse == CurseType.LETTER
        and ch.isalpha()
    ):
        alts: list[str] = []
        if ch > "a":
            alts.append(chr(ord(ch) - 1))
        alts.append(ch)
        if ch < "z":
            alts.append(chr(ord(ch) + 1))
        return alts
    return [ch]


def _tile_digit_face_matches(
    ch: str,
    tile: Tile,
    stamp_flags: StampSearchFlags | None,
) -> bool:
    if tile.letter == ch:
        return True
    if stamp_flags and stamp_flags.microscope_base_score:
        bp = _microscope_base_as_position(tile)
        if bp is not None and str(bp) == ch:
            return True
    return False


def _microscope_base_as_position(tile: Tile) -> int | None:
    """Whole-number base_score usable as a 1-based word index (Microscope)."""
    bs = tile.base_score
    if bs < 1 - 1e-6:
        return None
    ival = int(round(bs))
    if abs(bs - ival) > 1e-6 or ival < 1:
        return None
    return ival


def tile_number_position_values(
    tile: Tile,
    flags: StampSearchFlags | None,
) -> list[int]:
    """1-based position indices this tile may claim (face number + Microscope base_score)."""
    values: list[int] = []
    if tile.curse == CurseType.NUMBER:
        nv = tile.number_value
        if nv is None and tile.letter.isdigit():
            nv = int(tile.letter)
        if nv is not None and nv >= 1:
            values.append(nv)
    if flags and flags.microscope_base_score:
        bp = _microscope_base_as_position(tile)
        if bp is not None and bp not in values:
            values.append(bp)
    return values


def _position_matches_number_values(
    position: int,
    values: list[int],
    flags: StampSearchFlags | None,
) -> bool:
    if not values:
        return True
    pos = position + 1
    if flags and flags.number_plus_minus_one:
        return any(pos in (v - 1, v, v + 1) and v >= 1 for v in values)
    return any(pos == v for v in values)


def number_position_valid(
    tile: Tile,
    position: int,
    relaxed: bool = False,
    *,
    flags: StampSearchFlags | None = None,
    segment: str | None = None,
) -> bool:
    if (
        flags
        and flags.shiny_as_one
        and position == 0
        and tile.color == TileColor.SHINY
        and tile.curse == CurseType.LETTER
    ):
        return True
    if relaxed or tile.curse != CurseType.NUMBER:
        return True
    if (
        flags
        and flags.number_ascending_free_position
        and segment
        and number_digits_ascending(segment)
    ):
        return True
    if (
        flags
        and flags.number_roman_ivx
        and segment
        and tile.curse == CurseType.NUMBER
        and position < len(segment)
    ):
        nv_roman = tile_number_value(tile)
        if (
            nv_roman in ROMAN_BY_NUMBER
            and segment[position].lower() == ROMAN_BY_NUMBER[nv_roman]
        ):
            return True
    values = tile_number_position_values(tile, flags)
    if not values:
        return True
    return _position_matches_number_values(position, values, flags)


class PathValidator:
    def __init__(
        self,
        dictionary: WordDictionary,
        min_len: int = 3,
        relaxed_numbers: bool = False,
    ) -> None:
        self.dictionary = dictionary
        self.min_len = min_len
        self.relaxed_numbers = relaxed_numbers

    def build_word(self, board: Board, path: list[int], letters: str) -> str:
        return letters.lower()

    def prefix_ok(
        self,
        prefix: str,
        board: Board | None = None,
        path: list[int] | None = None,
        steps_remaining: int = 0,
        stamp_flags: StampSearchFlags | None = None,
    ) -> bool:
        if "?" in prefix:
            return True  # cannot prune wildcards via trie easily
        if any(ch.isdigit() for ch in prefix):
            return True  # number-tile words are not in the letter trie
        if self.dictionary.has_prefix(prefix):
            return True
        if stamp_flags and stamp_flags.word_stitch:
            if self.dictionary.is_valid_word(prefix, self.min_len):
                return True
            for k in range(self.min_len, len(prefix)):
                first, rest = prefix[:k], prefix[k:]
                if self.dictionary.is_valid_word(first, self.min_len) and (
                    not rest or self.dictionary.has_prefix(rest)
                ):
                    return True
        if (
            board is not None
            and path
            and steps_remaining > 0
            and self._may_extend_to_number_word(board, path, steps_remaining)
        ):
            return True
        return False

    def _path_constraints_ok(
        self,
        board: Board,
        path: list[int],
        word: str,
        stamp_flags: StampSearchFlags | None,
    ) -> bool:
        relaxed_fractions = self.relaxed_numbers
        for i, idx in enumerate(path):
            tile = board.get_by_index(idx)
            if not number_position_valid(
                tile,
                i,
                self.relaxed_numbers,
                flags=stamp_flags,
                segment=word,
            ):
                return False
            if not fraction_position_valid(tile, i, relaxed_fractions):
                return False
        return True

    def _word_content_ok(
        self,
        board: Board,
        path: list[int],
        word: str,
        stamp_flags: StampSearchFlags | None,
    ) -> bool:
        if any(ch.isdigit() for ch in word):
            return self._number_word_valid(board, path, word, stamp_flags)
        if "?" in word:
            return self._wildcard_valid(word)
        return self.dictionary.is_valid_word(word, self.min_len)

    def _stitched_word_ok(
        self,
        board: Board,
        path: list[int],
        word: str,
        stamp_flags: StampSearchFlags | None,
    ) -> bool:
        n = len(word)
        for k in range(self.min_len, n - self.min_len + 1):
            w1, w2 = word[:k], word[k:]
            p1, p2 = path[:k], path[k:]
            if (
                self._path_constraints_ok(board, p1, w1, stamp_flags)
                and self._path_constraints_ok(board, p2, w2, stamp_flags)
                and self._word_content_ok(board, p1, w1, stamp_flags)
                and self._word_content_ok(board, p2, w2, stamp_flags)
            ):
                return True
        return False

    def _may_extend_to_number_word(
        self,
        board: Board,
        path: list[int],
        max_steps: int,
        _cache: dict | None = None,
    ) -> bool:
        """Letter prefix not in trie may still reach a NUMBER tile within max_steps."""
        if _cache is not None:
            key = (frozenset(path), max_steps)
            cached = _cache.get(key)
            if cached is not None:
                return cached
        visited = set(path)
        frontier = [path[-1]]
        result = False
        for _ in range(max_steps):
            next_frontier: list[int] = []
            for idx in frontier:
                for nbr in neighbors_from_tile(board, [idx], visited):
                    if nbr in visited:
                        continue
                    tile = board.get_by_index(nbr)
                    if is_number_like_tile(tile):
                        result = True
                        break
                    next_frontier.append(nbr)
                if result:
                    break
            if result or not next_frontier:
                break
            visited.update(next_frontier)
            frontier = next_frontier
        if _cache is not None:
            _cache[key] = result
        return result

    def word_ok(
        self,
        board: Board,
        path: list[int],
        word: str,
        stamp_flags: StampSearchFlags | None = None,
    ) -> bool:
        if len(word) < self.min_len:
            return False
        if self._path_constraints_ok(board, path, word, stamp_flags) and self._word_content_ok(
            board, path, word, stamp_flags
        ):
            return True
        if stamp_flags and stamp_flags.word_stitch:
            return self._stitched_word_ok(board, path, word, stamp_flags)
        return False

    def _number_word_valid(
        self,
        board: Board,
        path: list[int],
        word: str,
        stamp_flags: StampSearchFlags | None = None,
    ) -> bool:
        """Number tiles are position-locked wildcards; validate via dictionary pattern."""
        if len(path) != len(word):
            return False
        pattern_chars: list[str] = []
        for i, idx in enumerate(path):
            tile = board.get_by_index(idx)
            ch = word[i]
            if ch.isdigit():
                if (
                    stamp_flags
                    and stamp_flags.shiny_as_one
                    and tile.color == TileColor.SHINY
                    and tile.curse == CurseType.LETTER
                    and int(ch) == 1
                ):
                    if i + 1 != 1:
                        return False
                    pattern_chars.append("?")
                    continue
                if is_fraction_tile(tile):
                    pattern_chars.append("?")
                    continue
                if tile.curse != CurseType.NUMBER:
                    return False
                digit = int(ch)
                nv = tile_number_value(tile)
                if (
                    stamp_flags
                    and stamp_flags.number_roman_ivx
                    and nv in ROMAN_BY_NUMBER
                    and ch.isalpha()
                    and ch.lower() == ROMAN_BY_NUMBER[nv]
                ):
                    pattern_chars.append("?")
                    continue
                if stamp_flags and stamp_flags.number_plus_minus_one:
                    values = tile_number_position_values(tile, stamp_flags)
                    allowed = {
                        x
                        for v in values
                        if v >= 1
                        for x in (v - 1, v, v + 1)
                    }
                    if digit not in allowed:
                        return False
                elif (
                    stamp_flags
                    and stamp_flags.number_ascending_free_position
                    and number_digits_ascending(word)
                ):
                    pass
                elif not _tile_digit_face_matches(ch, tile, stamp_flags):
                    return False
                pattern_chars.append("?")
            else:
                if is_fraction_tile(tile):
                    pattern_chars.append("?")
                    continue
                if tile.curse == CurseType.NUMBER:
                    if (
                        stamp_flags
                        and stamp_flags.number_roman_ivx
                        and ch.isalpha()
                    ):
                        nv = tile_number_value(tile)
                        if nv in ROMAN_BY_NUMBER and ch.lower() == ROMAN_BY_NUMBER[nv]:
                            pattern_chars.append("?")
                            continue
                    if ch.isalpha():
                        pattern_chars.append("?")
                        continue
                    return False
                pattern_chars.append(ch)
        pattern = "".join(pattern_chars)
        if pattern and all(ch == "?" for ch in pattern):
            if word.isdigit():
                return True
            if any(ch.isdigit() for ch in word) and any(ch.isalpha() for ch in word):
                number_tiles = sum(
                    1
                    for idx in path
                    if is_number_like_tile(board.get_by_index(idx))
                )
                if number_tiles >= 2:
                    return True
            return self.dictionary.contains(word.lower())
        return self._wildcard_valid(pattern)

    def _wildcard_valid(self, pattern: str) -> bool:
        return self._wildcard_dfs(pattern, 0)

    def _wildcard_dfs(self, pattern: str, pos: int) -> bool:
        if pos == len(pattern):
            return self.dictionary.contains(pattern)
        if pattern[pos] == "?":
            for ch in "abcdefghijklmnopqrstuvwxyz":
                trial = pattern[:pos] + ch + pattern[pos + 1 :]
                if self.dictionary.has_prefix(trial[: pos + 1]):
                    if self._wildcard_dfs(trial, pos + 1):
                        return True
            return False
        if not self.dictionary.has_prefix(pattern[: pos + 1]):
            return False
        return self._wildcard_dfs(pattern, pos + 1)


def _active_indices(board: Board) -> list[int]:
    return [i for i in range(25) if board.is_active_index(i)]


def _legal_word_start_indices(board: Board) -> list[int]:
    """Active tiles that may start a word (fractions only when 1-based pos 1 is legal)."""
    out: list[int] = []
    for i in _active_indices(board):
        tile = board.get_by_index(i)
        if is_fraction_tile(tile) and not fraction_position_valid(tile, 0, relaxed=False):
            continue
        out.append(i)
    return out


def neighbors_standard(
    board: Board,
    path: list[int],
    visited: int | set[int],
    *,
    flags: StampSearchFlags | None = None,
) -> list[int]:
    last = path[-1]
    row, col = last // 5, last % 5
    out = []
    for dr, dc in DIRS_8:
        nr, nc = row + dr, col + dc
        if 0 <= nr < 5 and 0 <= nc < 5:
            idx = index_of(nr, nc)
            if board.is_active_index(idx) and not _visited_has(visited, idx):
                out.append(idx)
    if flags and flags.horizontal_wrap:
        if col == 0:
            wrap = index_of(row, 4)
            if board.is_active_index(wrap) and not _visited_has(visited, wrap):
                out.append(wrap)
        elif col == 4:
            wrap = index_of(row, 0)
            if board.is_active_index(wrap) and not _visited_has(visited, wrap):
                out.append(wrap)
    return out


def _physical_letter(tile: Tile) -> str:
    """Glyph on tile for Full Moon matching (not word-position transforms like Flamingo)."""
    if is_chess_piece(tile):
        return ""
    if tile.curse in (CurseType.WILDCARD, CurseType.FRACTION):
        return ""
    glyph = normalize_tile_glyph(tile.char or "")
    if tile.curse == CurseType.CURRENCY:
        return glyph if glyph in CURRENCY_MAP else ""
    if len(glyph) == 1 and glyph.isalpha():
        return glyph.upper()
    return ""


def _double_letter_teleport_neighbors(
    board: Board,
    path: list[int],
    visited: int | set[int],
    flags: StampSearchFlags,
) -> list[int]:
    """Full Moon: jump to another unused tile with the same letter or identical chess piece."""
    last_tile = board.get_by_index(path[-1])
    letter = _physical_letter(last_tile)
    out: list[int] = []
    for idx in _active_indices(board):
        if idx == path[-1] or _visited_has(visited, idx):
            continue
        other = board.get_by_index(idx)
        if letter and _physical_letter(other) == letter:
            out.append(idx)
        elif identical_chess_piece(last_tile, other):
            out.append(idx)
    return out


def neighbors_from_tile(
    board: Board,
    path: list[int],
    visited: int | set[int],
    *,
    flags: StampSearchFlags | None = None,
) -> list[int]:
    """Curse-aware neighbor expansion."""
    last_tile = board.get_by_index(path[-1])
    flags = flags or StampSearchFlags()

    # WHITE tile: teleport to any unused cell (wiki / game movement)
    if last_tile.color == TileColor.WHITE:
        if isinstance(visited, set):
            return [
                i
                for i in _active_indices(board)
                if i not in visited
            ]
        return [
            i
            for i in _active_indices(board)
            if not (visited & (1 << i))
        ]

    if is_chess_piece(last_tile):
        nbrs = chess_neighbors(board, path, visited, flags)
    else:
        nbrs = neighbors_standard(board, path, visited, flags=flags)

    if flags.double_letter_teleport:
        seen = set(nbrs)
        for idx in _double_letter_teleport_neighbors(board, path, visited, flags):
            if idx not in seen:
                nbrs.append(idx)
                seen.add(idx)
    return nbrs


def _neighbors_sorted_by_base_score(
    board: Board,
    path: list[int],
    visited: int | set[int],
    *,
    flags: StampSearchFlags | None = None,
) -> list[int]:
    nbrs = neighbors_from_tile(board, path, visited, flags=flags)
    last = board.get_by_index(path[-1])

    def sort_key(idx: int) -> tuple[int, float, int]:
        tile = board.get_by_index(idx)
        base = float(tile.base_score)
        if is_fraction_tile(last):
            if tile.curse == CurseType.NUMBER:
                return (0, -base, idx)
            return (2, -base, idx)
        if last.curse == CurseType.NUMBER:
            if is_fraction_tile(tile):
                return (0, -base, idx)
            if is_number_like_tile(tile):
                return (1, -base, idx)
        return (3, -base, idx)

    nbrs.sort(key=sort_key)
    return nbrs


def _neighbors_sorted_for_loadout(
    board: Board,
    path: list[int],
    visited: int | set[int],
    *,
    flags: StampSearchFlags | None = None,
    hints: MultNeighborHints | None = None,
) -> list[int]:
    nbrs = neighbors_from_tile(board, path, visited, flags=flags)
    if not hints or not nbrs:
        return _neighbors_sorted_by_base_score(board, path, visited, flags=flags)
    last = board.get_by_index(path[-1])
    letter_pos = len(path)

    def sort_key(idx: int) -> tuple[int, int, float, int]:
        tile = board.get_by_index(idx)
        base = float(tile.base_score)
        mult_pri = neighbor_mult_priority(
            board, path, idx, hints, letter_pos=letter_pos
        )
        if is_fraction_tile(last):
            if tile.curse == CurseType.NUMBER:
                return (mult_pri, 0, -base, idx)
            return (mult_pri, 2, -base, idx)
        if last.curse == CurseType.NUMBER:
            if is_fraction_tile(tile):
                return (mult_pri, 0, -base, idx)
            if is_number_like_tile(tile):
                return (mult_pri, 1, -base, idx)
        return (mult_pri, 3, -base, idx)

    nbrs.sort(key=sort_key)
    return nbrs


def _color_end_indices(board: Board, color_name: str) -> list[int]:
    target = color_name.lower()
    if target == "yellow":
        # Legacy rule data may still use "yellow"; the runtime enum uses "gold".
        target = "gold"
    color_map = {
        "blue": TileColor.BLUE,
        "red": TileColor.RED,
        "green": TileColor.GREEN,
        "gold": TileColor.GOLD,
        "pink": TileColor.PINK,
        "purple": TileColor.PURPLE,
    }
    tc = color_map.get(target)
    if tc is None:
        return []
    return [
        i
        for i in _active_indices(board)
        if tile_counts_as_color(board.get_by_index(i), tc)
    ]


def _suit_endpoint_indices(board: Board) -> list[int]:
    out: list[int] = []
    for i in _active_indices(board):
        tile = board.get_by_index(i)
        if card_suit(tile) or is_joker_tile(tile):
            out.append(i)
    return out


def _number_tile_start_indices(board: Board) -> list[int]:
    """All number tiles, sorted by face value then index (fair share of digit-pass time)."""
    starts = [
        i
        for i in _active_indices(board)
        if is_number_like_tile(board.get_by_index(i))
    ]
    def _face_key(i: int) -> int:
        tile = board.get_by_index(i)
        if tile.number_value is not None:
            return tile.number_value
        if is_fraction_tile(tile):
            parts = fraction_parts(tile)
            if parts is not None:
                return parts[0]
        return 99

    return sorted(starts, key=lambda i: (_face_key(i), i))


def _is_wildcard_tile(tile: Tile) -> bool:
    return (
        tile.curse == CurseType.WILDCARD
        or tile.letter == "?"
        or is_joker_tile(tile)
    )


def _wildcard_start_indices(board: Board) -> list[int]:
    return [i for i in _active_indices(board) if _is_wildcard_tile(board.get_by_index(i))]


def _shortest_path_between_indices(
    board: Board,
    start: int,
    end: int,
    max_len: int,
    *,
    flags: StampSearchFlags | None = None,
) -> list[int] | None:
    """BFS shortest acyclic path from start to end (for joker-pair seeding)."""
    if start == end:
        return [start]
    from collections import deque

    queue: deque[list[int]] = deque([[start]])
    visited: set[int] = {start}
    while queue:
        path = queue.popleft()
        if len(path) > max_len:
            continue
        last = path[-1]
        if last == end:
            return path
        visited_mask = sum(1 << idx for idx in path)
        for nbr in neighbors_from_tile(board, path, visited_mask, flags=flags):
            if nbr in visited:
                continue
            visited.add(nbr)
            queue.append(path + [nbr])
    return None


def _high_value_path_between_indices(
    board: Board,
    start: int,
    end: int,
    max_len: int,
    *,
    flags: StampSearchFlags | None = None,
) -> list[int] | None:
    """A* path from start to end favoring high base_score tiles (joker-pair seeding)."""
    import heapq

    end_row, end_col = divmod(end, 5)

    def manhattan(idx: int) -> int:
        row, col = divmod(idx, 5)
        return abs(row - end_row) + abs(col - end_col)

    start_tile = board.get_by_index(start)
    start_sum = float(start_tile.base_score)
    heap: list[tuple[float, float, tuple[int, ...], int]] = [
        (
            start_sum - manhattan(start) * 0.25,
            start_sum,
            (start,),
            1 << start,
        )
    ]
    best_seen: dict[tuple[int, int], float] = {}

    while heap:
        _prio, tile_sum, path, visited = heapq.heappop(heap)
        state = (path[-1], visited)
        if state in best_seen and best_seen[state] >= tile_sum:
            continue
        best_seen[state] = tile_sum
        if path[-1] == end:
            return list(path)
        if len(path) >= max_len:
            continue
        for nbr in _neighbors_sorted_by_base_score(
            board, list(path), visited, flags=flags
        ):
            nvis = visited | (1 << nbr)
            nstate = (nbr, nvis)
            tile = board.get_by_index(nbr)
            nsum = tile_sum + float(tile.base_score)
            if nstate in best_seen and best_seen[nstate] >= nsum:
                continue
            prio = nsum - manhattan(nbr) * 0.25
            heapq.heappush(heap, (prio, nsum, path + (nbr,), nvis))
    return None


def _paths_between_indices(
    board: Board,
    start: int,
    end: int,
    max_len: int,
    *,
    flags: StampSearchFlags | None = None,
    path_cap: int = 48,
) -> list[list[int]]:
    """Acyclic paths from start to end (capped) for joker-cluster seeding."""
    found: list[list[int]] = []
    cap = path_cap

    def dfs(path: list[int], visited: int) -> None:
        if len(found) >= cap:
            return
        if path[-1] == end:
            found.append(list(path))
            return
        if len(path) >= max_len:
            return
        for nbr in _neighbors_sorted_by_base_score(
            board, path, visited, flags=flags
        ):
            dfs(path + [nbr], visited | (1 << nbr))

    dfs([start], 1 << start)
    return found


def _all_shortest_paths_between_indices(
    board: Board,
    start: int,
    end: int,
    max_len: int,
    *,
    flags: StampSearchFlags | None = None,
) -> list[list[int]]:
    """Every minimum-length path from start to end (BFS layer collect)."""
    from collections import deque

    queue: deque[list[int]] = deque([[start]])
    found_len: int | None = None
    paths: list[list[int]] = []
    while queue:
        path = queue.popleft()
        if found_len is not None and len(path) > found_len:
            break
        if path[-1] == end:
            if found_len is None:
                found_len = len(path)
            if len(path) == found_len:
                paths.append(path)
            continue
        if len(path) >= max_len:
            continue
        visited = sum(1 << idx for idx in path)
        for nbr in neighbors_from_tile(board, path, visited, flags=flags):
            queue.append(path + [nbr])
    return paths


def _joker_hub_bridge_paths(
    board: Board,
    start: int,
    end: int,
    max_len: int,
    *,
    flags: StampSearchFlags | None = None,
    hub_count: int = 8,
) -> list[list[int]]:
    """Stitch shortest paths start→hub→end for high base_score hubs (joker-pair seeding)."""
    hubs = sorted(
        _active_indices(board),
        key=lambda i: -float(board.get_by_index(i).base_score),
    )[:hub_count]
    merged: list[list[int]] = []
    for hub in hubs:
        if hub in (start, end):
            continue
        left = _shortest_path_between_indices(
            board, start, hub, max_len, flags=flags
        )
        if left is None:
            continue
        for right in _all_shortest_paths_between_indices(
            board, hub, end, max_len, flags=flags
        ):
            path = left + right[1:]
            if len(path) <= max_len:
                merged.append(path)
    return merged


def _joker_pair_paths(
    board: Board,
    max_len: int,
    *,
    flags: StampSearchFlags | None = None,
) -> list[list[int]]:
    """Paths connecting two jokers (both directions) for Hanafuda multi-joker hands."""
    jokers = _wildcard_start_indices(board)
    out: list[list[int]] = []
    seen: set[tuple[int, ...]] = set()
    cap = max_len
    for i, a in enumerate(jokers):
        for b in jokers[i + 1 :]:
            for start_idx, end_idx in ((a, b), (b, a)):
                short = _shortest_path_between_indices(
                    board, start_idx, end_idx, cap, flags=flags
                )
                if short is not None:
                    key = tuple(short)
                    if key not in seen:
                        seen.add(key)
                        out.append(short)
                rich = _high_value_path_between_indices(
                    board, start_idx, end_idx, cap, flags=flags
                )
                if rich is not None:
                    key = tuple(rich)
                    if key not in seen:
                        seen.add(key)
                        out.append(rich)
                for path in (
                    _joker_hub_bridge_paths(
                        board, start_idx, end_idx, cap, flags=flags
                    )
                    + _paths_between_indices(
                        board,
                        start_idx,
                        end_idx,
                        cap,
                        flags=flags,
                        path_cap=128,
                    )
                ):
                    key = tuple(path)
                    if key not in seen:
                        seen.add(key)
                        out.append(path)
    return out


def _balanced_start_indices(board: Board) -> list[int]:
    """Main-pass DFS order: wildcards first, then letters/high base, then numbers."""

    def priority(i: int) -> tuple[int, float, int, int]:
        tile = board.get_by_index(i)
        if _is_wildcard_tile(tile):
            return (0, 0.0, 0, i)
        if is_fraction_tile(tile):
            if not fraction_position_valid(tile, 0, relaxed=False):
                return (4, 0.0, 0, i)
            return (0, 0.0, 0, i)
        if is_chess_piece(tile):
            # Chess tiles often need early DFS start to discover capture-chain
            # extensions (e.g. Markkaa regression).
            return (1, -float(tile.base_score), 0, i)
        if tile.curse == CurseType.NUMBER and (
            float(tile.base_score) >= 40.0 or _adjacent_to_fraction(board, i)
        ):
            nv = tile.number_value if tile.number_value is not None else 99
            return (0, -float(tile.base_score), nv, i)
        if tile.curse == CurseType.LETTER:
            return (1, -float(tile.base_score), 0, i)
        if tile.curse == CurseType.NUMBER:
            nv = tile.number_value if tile.number_value is not None else 99
            return (2, 0.0, nv, i)
        return (3, 0.0, 0, i)

    return sorted(_legal_word_start_indices(board), key=priority)


def _chess_start_indices(board: Board) -> list[int]:
    """Chess tiles as DFS starts (low priority in main pass; used for prefix seeding)."""
    return [
        i
        for i in _active_indices(board)
        if is_chess_piece(board.get_by_index(i))
    ]


def _chess_tile_count(board: Board) -> int:
    return sum(1 for t in board.flat if is_chess_piece(t))


def _chess_prefix_budget_sec(board: Board) -> float:
    """Adaptive budget for chess-only prefix seeding (0 = skip)."""
    count = _chess_tile_count(board)
    if count < 3:
        return 0.0
    if count < 6:
        return 0.5
    return 2.0


def _interleaved_number_starts(board: Board) -> list[int]:
    """Round-robin across number faces so one '1' tile cannot monopolize digit-pass time."""
    buckets: dict[int, list[int]] = {}
    for i in _number_tile_start_indices(board):
        tile = board.get_by_index(i)
        if tile.number_value is not None:
            face = tile.number_value
        elif is_fraction_tile(tile):
            parts = fraction_parts(tile)
            face = parts[0] if parts is not None else 99
        else:
            face = 99
        buckets.setdefault(face, []).append(i)
    faces = sorted(buckets)
    out: list[int] = []
    while any(buckets[f] for f in faces):
        for face in faces:
            if buckets[face]:
                out.append(buckets[face].pop(0))
    return out


def _adjacent_to_fraction(board: Board, idx: int) -> bool:
    for nbr in neighbors_from_tile(board, [idx], 1 << idx):
        if is_fraction_tile(board.get_by_index(nbr)):
            return True
    return False


def _fraction_cluster_number_starts(board: Board) -> list[int]:
    """NUMBER tiles touching a fraction tile; high base score first (shiny cluster)."""
    fraction_indices = [
        i for i in _active_indices(board) if is_fraction_tile(board.get_by_index(i))
    ]
    if not fraction_indices:
        return []
    starts: set[int] = set()
    for fi in fraction_indices:
        for nbr in neighbors_from_tile(board, [fi], 1 << fi):
            tile = board.get_by_index(nbr)
            if tile.curse == CurseType.NUMBER:
                starts.add(nbr)
    return sorted(
        starts,
        key=lambda i: (-float(board.get_by_index(i).base_score), i),
    )

class WordSearcher:
    def __init__(
        self,
        dictionary: WordDictionary | None = None,
        min_len: int = 3,
        max_len: int = 15,
        time_budget: float = 45.0,
        score_fn: Callable | None = None,
        candidate_heap_size: int | None = None,
        blocked: bool = False,
        block_reason: str = "",
        setup_weight: float = 0.4,
        setup_discount: float = 0.85,
        mult_search_weight: float = 0.4,
        mult_search_passes: bool = True,
        search_workers: int = 1,
        wordlist_path: Path | None = None,
        use_fast_rank: bool | None = None,
    ) -> None:
        self.dictionary = dictionary or WordDictionary()
        self.validator = PathValidator(self.dictionary, min_len)
        self.min_len = min_len
        self.max_len = max_len
        self.blocked = blocked
        self.block_reason = block_reason
        self.time_budget = time_budget
        self.scoring = ScoringPipeline()
        self.score_fn = score_fn
        self.candidate_heap_size = candidate_heap_size
        self.setup_weight = setup_weight
        self.setup_discount = setup_discount
        self.mult_search_weight = mult_search_weight
        self.mult_search_passes = mult_search_passes
        self.search_workers = max(1, int(search_workers))
        self._mult_rules: list = []
        self._mult_hints: MultNeighborHints | None = None
        self._wordlist_path = wordlist_path or getattr(
            self.dictionary, "path", None
        )
        self._use_fast_rank_override = use_fast_rank
        self._score_cache: dict[tuple[tuple[int, ...], str], tuple[float, float, float]] = {}
        self._number_extend_cache: dict[tuple[frozenset[int], int], bool] = {}
        self._prune_heap: _CandidateHeap | None = None
        self._parallel_executor: ProcessPoolExecutor | None = None
        self._active_deadline: float | None = None
        self.last_search_timing: SearchTiming | None = None
        self._active_timing: SearchTiming | None = None

    def _min_start_slice_sec(self) -> float:
        if self.time_budget >= 12.0:
            return 1.0
        if self.time_budget >= 6.0:
            return 0.5
        if self.time_budget >= 3.0:
            return 0.25
        return 0.0

    def _adaptive_min_slice(
        self,
        candidates: "_CandidateHeap",
        pass_idx: int,
    ) -> float:
        """Shrink per-start guaranteed slice when heap is saturated."""
        base = self._min_start_slice_sec()
        if base <= 0.0:
            return base
        # Don't shrink until the heap has been fully populated for at least 2 passes.
        if pass_idx < 2 or len(candidates) < candidates._k:
            return base
        bot = candidates.min_rank_score()
        if bot is None:
            return base
        # Find approximate top score: last heap entry after sorting is best.
        heap = candidates._heap
        if not heap:
            return base
        top = max(e[0] for e in heap)
        if top <= 0:
            return base
        if bot / top >= 0.85:
            # Heap is saturated (floor within 15% of ceiling) — halve the guarantee.
            return base * 0.5
        return base

    def _use_fast_rank_for(self, loadout: Loadout) -> bool:
        if self._use_fast_rank_override is not None:
            return self._use_fast_rank_override
        return loadout_allows_fast_rank(loadout, setup_weight=self.setup_weight)

    def _use_mult_prune_for(self, loadout: Loadout) -> bool:
        if self._use_fast_rank_for(loadout):
            return True
        return loadout_allows_mult_prune(
            loadout, self.scoring.rules, setup_weight=self.setup_weight
        )

    def _time_expired(self) -> bool:
        dl = self._active_deadline
        return dl is not None and time.monotonic() >= dl

    def _time_check_interval(self, loadout: Loadout) -> int:
        if loadout.stickers or loadout.stamps or loadout.boss_effect:
            return 32
        return TIME_CHECK_INTERVAL

    def _collect_words_fair_starts(
        self,
        board: Board,
        loadout: Loadout,
        candidates: "_CandidateHeap",
        pass_deadline: float,
        max_len: int,
        starts: list[int],
        *,
        digits_only: bool = False,
        min_slice_override: float | None = None,
        start_productivity: dict[int, int] | None = None,
    ) -> None:
        """Give each start a fair share of pass_deadline (prevents cell 0 eating the whole budget)."""
        if not starts or time.monotonic() >= pass_deadline:
            return
        pool = self._parallel_executor
        if (
            pool is not None
            and self.search_workers > 1
            and len(starts) > 1
            and not digits_only
        ):
            from cursed_words_solver.search_parallel import parallel_collect_fair_starts

            parallel_collect_fair_starts(
                executor=pool,
                workers=self.search_workers,
                board=board,
                loadout=loadout,
                candidates=candidates,
                deadline=pass_deadline,
                max_len=max_len,
                min_len=self.min_len,
                starts=starts,
                digits_only=digits_only,
                setup_weight=self.setup_weight,
                setup_discount=self.setup_discount,
                use_fast_rank=self._use_fast_rank_for(loadout),
            )
            return
        n = len(starts)
        pass_start = time.monotonic()
        pass_duration = max(pass_deadline - pass_start, 0.0)
        if min_slice_override is not None:
            base_min = min_slice_override
        else:
            base_min = self._min_start_slice_sec()
        # When focusing on short chess capture chains (e.g. Markkaa cap=8),
        # each start needs a bit more time to reach the required depth.
        if max_len <= 8 and starts:
            if any(is_chess_piece(board.get_by_index(i)) for i in starts):
                base_min = max(base_min, 2.0)
        wild_in_pass = any(
            _is_wildcard_tile(board.get_by_index(i)) for i in starts
        )
        # For pure letter boards with many starts, cap guarantee so late starts
        # aren't starved.
        if n > 0 and base_min > 0 and pass_duration > 0:
            per_start_cap = pass_duration / (n * 2)
            if per_start_cap < base_min:
                base_min = per_start_cap
        if wild_in_pass and n * base_min > pass_duration:
            min_slice = pass_duration / n
        else:
            min_slice = base_min
        for idx, start in enumerate(starts):
            now = time.monotonic()
            if now >= pass_deadline:
                break
            left = pass_deadline - now
            remaining = n - idx
            per = max(min_slice, left / remaining) if remaining else left
            sub_deadline = min(pass_deadline, now + per)
            before = len(candidates)
            self._collect_words(
                board,
                loadout,
                candidates,
                sub_deadline,
                max_len,
                digits_only=digits_only,
                start_indices=[start],
            )
            if start_productivity is not None:
                start_productivity[start] = start_productivity.get(start, 0) + (
                    len(candidates) - before
                )

    def _collect_words(
        self,
        board: Board,
        loadout: Loadout,
        candidates: _CandidateHeap,
        deadline: float,
        max_len: int,
        digits_only: bool = False,
        start_indices: list[int] | None = None,
    ) -> None:
        use_prune = self._use_mult_prune_for(loadout)
        if any(is_number_like_tile(board.get_by_index(i)) for i in _active_indices(board)):
            use_prune = False
        prev_heap = self._prune_heap
        prev_deadline = self._active_deadline
        self._prune_heap = candidates if use_prune else None
        mult_hints = self._mult_hints
        self._active_deadline = deadline
        check_interval = self._time_check_interval(loadout)
        stamp_flags = stamp_search_flags(loadout)
        hanafuda_level = hanafuda_sticker_level(loadout)
        use_hanafuda_physical = hanafuda_level > 0

        def scoring_word_for_path(path: list[int], search_word: str) -> str:
            if use_hanafuda_physical:
                return physical_word_for_path(board, path, flags=stamp_flags)
            return search_word

        def path_accepted(
            path: list[int],
            search_word: str,
            *,
            trie_compatible: bool,
            prefix_cursor: dict[str, dict] | None,
        ) -> tuple[bool, str]:
            if len(search_word) < self.min_len:
                return False, search_word
            # Fast-path: letter-only prefix that is a complete trie word.
            if (
                trie_compatible
                and prefix_cursor is not None
                and self.dictionary.cursor_is_word(prefix_cursor)
                and self.validator._path_constraints_ok(
                    board, path, search_word, stamp_flags
                )
            ):
                return True, scoring_word_for_path(path, search_word)
            if self.validator.word_ok(board, path, search_word, stamp_flags):
                return True, scoring_word_for_path(path, search_word)
            if use_hanafuda_physical:
                phys = physical_word_for_path(board, path, flags=stamp_flags)
                if phys != search_word and self.validator.word_ok(
                    board, path, phys, stamp_flags
                ):
                    return True, phys
            if loadout is not None and any(
                is_number_like_tile(board.get_by_index(i)) for i in path
            ):
                from cursed_words_solver.suggestion import dictionary_word_for_path

                alt = dictionary_word_for_path(
                    board,
                    path,
                    search_word,
                    loadout,
                    self.dictionary,
                    min_len=self.min_len,
                    pipeline=self.scoring,
                )
                if alt and self.validator.word_ok(board, path, alt, stamp_flags):
                    return True, scoring_word_for_path(path, alt)
            return False, search_word

        def score_path(path: list[int], word: str) -> float | None:
            return self._rank_score_for_candidate(
                board,
                path,
                word,
                loadout,
                prune_heap=candidates if use_prune else None,
            )

        expansions = 0
        timed_out = False
        timing = self._active_timing
        stitch_active = bool(stamp_flags and stamp_flags.word_stitch)
        _num_extend_cache = (
            self._number_extend_cache
            if getattr(self, "_board_has_number_tiles", False)
            else None
        )

        def _step_token_cursor(
            cursor: dict[str, dict] | None, token: str
        ) -> dict[str, dict] | None:
            node = cursor
            for c in token:
                node = self.dictionary.step_cursor(node, c)
                if node is None:
                    return None
            return node

        def _update_stitch_state(
            prefix_cursor: dict[str, dict] | None,
            suffix_cursors: list[dict[str, dict] | None],
            is_word_end_at_depth: list[bool],
            token: str,
        ) -> tuple[
            dict[str, dict] | None,
            list[dict[str, dict] | None],
            list[bool],
        ]:
            node = prefix_cursor
            for c in token:
                node = self.dictionary.step_cursor(node, c)
                next_suffix: list[dict[str, dict] | None] = [
                    self.dictionary.step_cursor(prev, c)
                    for prev in suffix_cursors
                ]
                next_suffix.append(
                    self.dictionary.step_cursor(
                        self.dictionary.root_cursor(), c
                    )
                )
                suffix_cursors = next_suffix
                is_word_end_at_depth.append(self.dictionary.cursor_is_word(node))
            return node, suffix_cursors, is_word_end_at_depth

        def _stitch_prefix_ok(
            prefix_len: int,
            is_word_end_at_depth: list[bool],
            suffix_cursors: list[dict[str, dict] | None],
        ) -> bool:
            for k in range(self.min_len, prefix_len):
                if k >= len(is_word_end_at_depth):
                    break
                if is_word_end_at_depth[k] and k < len(suffix_cursors):
                    if suffix_cursors[k] is not None:
                        return True
            return False

        def dfs(
            path: list[int],
            chars: list[str],
            visited_mask: int,
            *,
            prefix_cursor: dict[str, dict] | None,
            has_wildcard: bool,
            has_digit: bool,
            prefix_len: int,
            suffix_cursors: list[dict[str, dict] | None] | None = None,
            is_word_end_at_depth: list[bool] | None = None,
        ) -> None:
            nonlocal expansions, timed_out
            if timed_out or self._time_expired():
                timed_out = True
                return
            expansions += 1
            if timing is not None:
                timing.dfs_expansions += 1
            if expansions % check_interval == 0 and time.monotonic() > deadline:
                timed_out = True
                return

            word = "".join(chars).lower()
            trie_compatible = not has_wildcard and not has_digit
            ok, score_word = path_accepted(
                path,
                word,
                trie_compatible=trie_compatible,
                prefix_cursor=prefix_cursor if trie_compatible else None,
            )
            if ok:
                if not digits_only or any(ch.isdigit() for ch in score_word):
                    sc = score_path(path, score_word)
                    if sc is not None:
                        candidates.consider(sc, score_word, path)

            if len(path) >= max_len or timed_out:
                return

            steps_left = max_len - len(path)
            if trie_compatible and prefix_cursor is None:
                if stitch_active:
                    if not (
                        suffix_cursors is not None
                        and is_word_end_at_depth is not None
                        and _stitch_prefix_ok(
                            prefix_len, is_word_end_at_depth, suffix_cursors
                        )
                    ):
                        if not (
                            steps_left > 0
                            and self.validator._may_extend_to_number_word(
                                board, path, steps_left, _num_extend_cache
                            )
                        ):
                            return
                else:
                    if not (
                        steps_left > 0
                        and self.validator._may_extend_to_number_word(
                            board, path, steps_left, _num_extend_cache
                        )
                    ):
                        return

            for idx in _neighbors_sorted_for_loadout(
                board,
                path,
                visited_mask,
                flags=stamp_flags,
                hints=mult_hints,
            ):
                if timed_out or self._time_expired():
                    timed_out = True
                    break
                tile = board.get_by_index(idx)
                token = resolve_letter(tile, prefix_len, flags=stamp_flags)
                next_has_wildcard = has_wildcard or ("?" in token)
                next_has_digit = has_digit or any(c.isdigit() for c in token)
                next_prefix_len = prefix_len + len(token)
                next_prefix_cursor = (
                    None
                    if (next_has_wildcard or next_has_digit)
                    else _step_token_cursor(prefix_cursor, token)
                )
                next_suffix = suffix_cursors
                next_is_word_end = is_word_end_at_depth
                if stitch_active and not (next_has_wildcard or next_has_digit):
                    base_suffix = (
                        list(suffix_cursors)
                        if suffix_cursors is not None
                        else []
                    )
                    base_is_word = (
                        list(is_word_end_at_depth)
                        if is_word_end_at_depth is not None
                        else [False]
                    )
                    next_prefix_cursor, next_suffix, next_is_word_end = _update_stitch_state(
                        prefix_cursor, base_suffix, base_is_word, token
                    )
                chars.append(token)
                dfs(
                    path + [idx],
                    chars,
                    visited_mask | (1 << idx),
                    prefix_cursor=next_prefix_cursor,
                    has_wildcard=next_has_wildcard,
                    has_digit=next_has_digit,
                    prefix_len=next_prefix_len,
                    suffix_cursors=next_suffix,
                    is_word_end_at_depth=next_is_word_end,
                )
                chars.pop()

        if start_indices is not None:
            starts = [s for s in start_indices if board.is_active_index(s)]
        else:
            starts = _legal_word_start_indices(board)
        for start in starts:
            if timed_out or time.monotonic() > deadline:
                break
            tile = board.get_by_index(start)
            token = resolve_letter(tile, 0, flags=stamp_flags)
            has_wildcard = "?" in token
            has_digit = any(c.isdigit() for c in token)
            prefix_len = len(token)
            prefix_cursor = (
                None
                if (has_wildcard or has_digit)
                else _step_token_cursor(self.dictionary.root_cursor(), token)
            )
            suffix_cursors: list[dict[str, dict] | None] | None = None
            is_word_end_at_depth: list[bool] | None = None
            if stitch_active and not (has_wildcard or has_digit):
                suffix_cursors = []
                is_word_end_at_depth = [False]
                prefix_cursor, suffix_cursors, is_word_end_at_depth = _update_stitch_state(
                    self.dictionary.root_cursor(),
                    suffix_cursors,
                    is_word_end_at_depth,
                    token,
                )
            dfs(
                [start],
                [token],
                1 << start,
                prefix_cursor=prefix_cursor,
                has_wildcard=has_wildcard,
                has_digit=has_digit,
                prefix_len=prefix_len,
                suffix_cursors=suffix_cursors,
                is_word_end_at_depth=is_word_end_at_depth,
            )

        self._prune_heap = prev_heap
        self._active_deadline = prev_deadline

    def _seed_single_number_tile_words(
        self,
        board: Board,
        loadout: Loadout,
        candidates: "_CandidateHeap",
    ) -> None:
        """Seed lone NUMBER tiles (e.g. word '1' on a 1-tile) the game accepts without a dictionary entry."""
        flags = stamp_search_flags(loadout)
        for idx in _active_indices(board):
            tile = board.get_by_index(idx)
            if tile.curse != CurseType.NUMBER:
                continue
            nv = tile_number_value(tile)
            if nv is None:
                continue
            words_to_try = {str(nv)}
            if flags.microscope_base_score:
                bp = _microscope_base_as_position(tile)
                if bp is not None:
                    words_to_try.add(str(bp))
            path = [idx]
            for word in words_to_try:
                if len(word) < self.min_len:
                    continue
                if not self.validator.word_ok(board, path, word, flags):
                    continue
                sc = self._rank_score_for_candidate(board, path, word, loadout)
                if sc is not None:
                    candidates.consider(sc, word, path)

    def _collect_joker_cluster_candidates(
        self,
        board: Board,
        loadout: Loadout,
        candidates: _CandidateHeap,
        deadline: float,
        max_len: int,
    ) -> None:
        """Seed paths that connect two jokers (Hanafuda three-of-a-kind with L2+)."""
        if hanafuda_sticker_level(loadout) < 1:
            return
        if time.monotonic() >= deadline:
            return
        stamp_flags = stamp_search_flags(loadout)
        prev_deadline = self._active_deadline
        self._active_deadline = deadline
        try:
            for path in _joker_pair_paths(board, max_len, flags=stamp_flags):
                if time.monotonic() >= deadline:
                    break
                if len(path) < self.min_len:
                    continue
                phys = physical_word_for_path(board, path, flags=stamp_flags)
                if not self.validator.word_ok(board, path, phys, stamp_flags):
                    continue
                sc = self._rank_score_for_candidate(
                    board, path, phys, loadout
                )
                if sc is not None:
                    candidates.consider(sc, phys, path)
        finally:
            self._active_deadline = prev_deadline

    def _collect_mult_seed_candidates(
        self,
        board: Board,
        loadout: Loadout,
        candidates: _CandidateHeap,
        deadline: float,
        max_len: int,
    ) -> None:
        """Seed paths for color-ending mults and Wrestlers suit endpoints."""
        if not self.mult_search_passes or not self._mult_rules:
            return
        if time.monotonic() >= deadline:
            return
        stamp_flags = stamp_search_flags(loadout)
        prev_deadline = self._active_deadline
        self._active_deadline = deadline
        try:
            end_colors: set[str] = set()
            need_suit_endpoints = False
            need_length = False
            for mr in self._mult_rules:
                if mr.condition.startswith("ends_with_color:"):
                    end_colors.add(mr.condition.split(":", 1)[1].lower())
                if mr.condition == "word_starts_ends_different_suit":
                    need_suit_endpoints = True
                if mr.condition.startswith(
                    ("path_length_gte:", "word_length_gte:")
                ):
                    need_length = True

            starts = _legal_word_start_indices(board)
            cap = min(max_len, 10)

            for color in end_colors:
                if time.monotonic() >= deadline:
                    break
                ends = _color_end_indices(board, color)
                for end_idx in ends[:6]:
                    for start in starts[:12]:
                        if start == end_idx or time.monotonic() >= deadline:
                            continue
                        for path in _paths_between_indices(
                            board, start, end_idx, cap, flags=stamp_flags
                        ):
                            if len(path) < self.min_len:
                                continue
                            word = "".join(
                                resolve_letter(
                                    board.get_by_index(i), j, flags=stamp_flags
                                )
                                for j, i in enumerate(path)
                            ).lower()
                            if not self.validator.word_ok(
                                board, path, word, stamp_flags
                            ):
                                continue
                            sc = self._rank_score_for_candidate(
                                board, path, word, loadout
                            )
                            if sc is not None:
                                candidates.consider(sc, word, path)

            if need_suit_endpoints:
                suited = _suit_endpoint_indices(board)
                for i, a in enumerate(suited[:8]):
                    if time.monotonic() >= deadline:
                        break
                    for b in suited[i + 1 : i + 9]:
                        if a == b:
                            continue
                        sa = card_suit(board.get_by_index(a))
                        sb = card_suit(board.get_by_index(b))
                        if not sa or not sb:
                            if not (
                                is_joker_tile(board.get_by_index(a))
                                or is_joker_tile(board.get_by_index(b))
                            ):
                                continue
                        elif sa == sb:
                            continue
                        for path in _paths_between_indices(
                            board, a, b, cap, flags=stamp_flags
                        ):
                            if len(path) < self.min_len:
                                continue
                            if not word_starts_ends_different_suit(board, path):
                                continue
                            word = "".join(
                                resolve_letter(
                                    board.get_by_index(ix), j, flags=stamp_flags
                                )
                                for j, ix in enumerate(path)
                            ).lower()
                            if not self.validator.word_ok(
                                board, path, word, stamp_flags
                            ):
                                continue
                            sc = self._rank_score_for_candidate(
                                board, path, word, loadout
                            )
                            if sc is not None:
                                candidates.consider(sc, word, path)

            if need_length:
                self._extend_top_candidates(
                    board,
                    loadout,
                    candidates,
                    top_paths=min(60, len(candidates) or 30),
                    max_rounds=min(4, max_len - self.min_len),
                    deadline=deadline,
                )
        finally:
            self._active_deadline = prev_deadline

    def _chess_prefix_candidates(
        self,
        board: Board,
        loadout: Loadout,
        *,
        budget_sec: float | None = None,
        solve_deadline: float | None = None,
        max_cap: int = 5,
        heap_k: int = 200,
    ) -> list[tuple[float, str, tuple[int, ...]]]:
        """Quick DFS from chess starts; returned paths seed extension (not main heap)."""
        if solve_deadline is not None and time.monotonic() >= solve_deadline:
            return []
        if budget_sec is None:
            budget_sec = _chess_prefix_budget_sec(board)
        if budget_sec <= 0:
            return []
        if solve_deadline is not None:
            budget_sec = min(budget_sec, max(0.0, solve_deadline - time.monotonic()))
            if budget_sec <= 0:
                return []
        chess_starts = _chess_start_indices(board)
        if not chess_starts:
            return []
        mini = _CandidateHeap(heap_k)
        deadline = time.monotonic() + budget_sec
        if solve_deadline is not None:
            deadline = min(deadline, solve_deadline)
        cap_hi = min(max_cap, self.max_len)
        for cap in range(self.min_len, cap_hi + 1):
            if time.monotonic() >= deadline:
                break
            self._collect_words_fair_starts(
                board,
                loadout,
                mini,
                deadline,
                cap,
                chess_starts,
            )
        return mini.best_sorted()

    def _extend_top_candidates(
        self,
        board: Board,
        loadout: Loadout,
        candidates: _CandidateHeap,
        *,
        top_paths: int = 20,
        max_rounds: int | None = None,
        extra_seeds: list[tuple[float, str, tuple[int, ...]]] | None = None,
        deadline: float | None = None,
    ) -> None:
        """Extend strong partial paths by one tile per round (cheap cap+N refinement)."""
        if self.max_len <= self.min_len:
            return
        if deadline is not None and time.monotonic() >= deadline:
            return
        if max_rounds is None:
            max_rounds = min(self.max_len - self.min_len, 12)
        stamp_flags = stamp_search_flags(loadout)

        use_prune = self._use_mult_prune_for(loadout)

        def score_path(path: list[int], word: str) -> float | None:
            if self._time_expired():
                return None
            return self._rank_score_for_candidate(
                board,
                path,
                word,
                loadout,
                prune_heap=candidates if use_prune else None,
            )

        prev_deadline = self._active_deadline
        if deadline is not None:
            self._active_deadline = deadline
        try:
            for _round in range(max_rounds):
                if deadline is not None and time.monotonic() >= deadline:
                    break
                extended = False
                seen_prefixes: set[tuple[int, ...]] = set()
                seed_entries = list(candidates.best_sorted()[:top_paths])
                if extra_seeds:
                    seed_entries.extend(extra_seeds)
                for _score, _word, path_tuple in seed_entries:
                    if deadline is not None and time.monotonic() >= deadline:
                        break
                    path = list(path_tuple)
                    if len(path) >= self.max_len:
                        continue
                    key = tuple(path)
                    if key in seen_prefixes:
                        continue
                    seen_prefixes.add(key)
                    visited_mask = sum(1 << idx for idx in path)
                    letters = "".join(
                        resolve_letter(board.get_by_index(idx), j, flags=stamp_flags)
                        for j, idx in enumerate(path)
                    )
                    for idx in neighbors_from_tile(
                        board, path, visited_mask, flags=stamp_flags
                    ):
                        if deadline is not None and time.monotonic() >= deadline:
                            break
                        tile = board.get_by_index(idx)
                        ch = resolve_letter(tile, len(letters), flags=stamp_flags)
                        word = (letters + ch).lower()
                        new_path = path + [idx]
                        if len(word) < self.min_len:
                            continue
                        if not self.validator.word_ok(
                            board, new_path, word, stamp_flags
                        ):
                            continue
                        sc = score_path(new_path, word)
                        if sc is not None:
                            candidates.consider(sc, word, new_path)
                            extended = True
                if not extended:
                    break
        finally:
            self._active_deadline = prev_deadline

    def _refine_candidates_with_extension(
        self,
        board: Board,
        loadout: Loadout,
        candidates: _CandidateHeap,
        chess_seeds: list[tuple[float, str, tuple[int, ...]]],
        *,
        top_paths: int,
    ) -> None:
        """Extend chess capture chains on a large scratch heap, then merge back."""
        if not chess_seeds:
            return
        main_entries = candidates.best_sorted()
        refine = _CandidateHeap(4000)
        for score, word, path in chess_seeds:
            refine.consider(score, word, list(path))
        self._extend_top_candidates(
            board,
            loadout,
            refine,
            top_paths=min(120, len(chess_seeds) + 20),
            extra_seeds=None,
            max_rounds=6,
        )
        candidates._heap.clear()
        for score, word, path in refine.best_sorted()[:120]:
            candidates.consider(score, word, list(path))
        for score, word, path in main_entries:
            candidates.consider(score, word, list(path))

    def _rank_score_for_candidate(
        self,
        board: Board,
        path: list[int],
        word: str,
        loadout: Loadout,
        *,
        prune_heap: _CandidateHeap | None = None,
    ) -> float | None:
        if self._time_expired():
            return None
        key = (tuple(path), word)
        cached = self._score_cache.get(key)
        if cached is not None:
            return cached[2]
        heap = prune_heap
        hanafuda_level = hanafuda_sticker_level(loadout)
        score_word = (
            physical_word_for_path(
                board, path, flags=stamp_search_flags(loadout)
            )
            if hanafuda_level > 0
            else word
        )
        if heap is not None and not (
            hanafuda_level > 0
            and hanafuda_hand_satisfied(board, path, hanafuda_level)
        ):
            min_sc = heap.min_rank_score()
            if min_sc is not None:
                if self._use_mult_prune_for(loadout):
                    lb = mult_aware_lower_bound(
                        board, path, loadout, self.scoring.rules
                    )
                else:
                    lb = fast_rank_lower_bound(board, path)
                if lb <= min_sc:
                    return None
        setup_bonus = 0.0
        timing = self._active_timing
        if self.score_fn:
            immediate = self.score_fn(board, path, score_word, loadout)
            rank = immediate
        else:
            t0 = time.perf_counter()
            immediate = self.scoring.score_total_only(
                board, path, score_word, loadout
            )
            if timing is not None:
                timing.score_sec += time.perf_counter() - t0
                timing.score_calls += 1
            t_setup = time.perf_counter()
            _setup_rank, setup_bonus = rank_score_for_word(
                board,
                path,
                score_word,
                loadout,
                immediate,
                setup_weight=self.setup_weight,
                setup_discount=self.setup_discount,
                rules=self.scoring.rules,
            )
            if timing is not None:
                timing.setup_rank_sec += time.perf_counter() - t_setup
            mult_factor = 1.0
            if self.mult_search_weight > 0 and self._mult_rules:
                t_mult = time.perf_counter()
                mult_factor = optimistic_mult_factor(
                    loadout,
                    board,
                    path,
                    score_word,
                    self.scoring.rules,
                    self._mult_rules,
                )
                if timing is not None:
                    timing.mult_rank_sec += time.perf_counter() - t_mult
            rank = search_rank_score(
                immediate,
                mult_factor,
                mult_weight=self.mult_search_weight,
                setup_bonus=setup_bonus,
            )
            if hanafuda_level > 0 and hanafuda_hand_satisfied(
                board, path, hanafuda_level
            ):
                rank += 800.0
        cache_key = (tuple(path), score_word)
        self._score_cache[cache_key] = (immediate, setup_bonus, rank)
        if cache_key != key:
            self._score_cache[key] = (immediate, setup_bonus, rank)
        return rank

    def _immediate_and_setup(
        self, board: Board, path: list[int], word: str, loadout: Loadout
    ) -> tuple[float, float]:
        key = (tuple(path), word)
        cached = self._score_cache.get(key)
        if cached is not None:
            return cached[0], cached[1]
        self._rank_score_for_candidate(board, path, word, loadout)
        cached = self._score_cache.get(key)
        if cached is not None:
            return cached[0], cached[1]
        immediate = self.scoring.score_total_only(board, path, word, loadout)
        return immediate, 0.0

    def find_best_words(
        self,
        board: Board,
        loadout: Loadout | None = None,
        top_n: int = 3,
    ) -> list[WordResult]:
        if self.blocked:
            return []
        self._score_cache.clear()
        self._number_extend_cache.clear()
        clear_chess_attack_cache()
        loadout = loadout or Loadout(money=board.money)
        board = effective_board_for_loadout(board, loadout, self.scoring.rules)
        _active = _active_indices(board)
        self._mult_rules = loadout_mult_rules(
            loadout,
            self.scoring.rules,
            board=board,
            path=[_active[0]] if _active else [],
        )
        self._mult_hints = (
            build_mult_neighbor_hints(self._mult_rules)
            if self._mult_rules
            else None
        )
        mult_count = len(self._mult_rules)
        heap_k = self.candidate_heap_size or _candidate_heap_size(
            top_n, mult_count
        )
        candidates = _CandidateHeap(heap_k)
        solve_start = time.monotonic()
        timing = SearchTiming(parallel_workers=self.search_workers)
        self._active_timing = timing
        has_number_tiles = any(is_number_like_tile(t) for t in board.flat)
        self._board_has_number_tiles = has_number_tiles
        has_fraction_tiles = any(is_fraction_tile(t) for t in board.flat)
        void_letter_starts = [
            i
            for i in _active_indices(board)
            if board.get_by_index(i).color == TileColor.VOID
            and board.get_by_index(i).curse == CurseType.LETTER
        ]
        if has_number_tiles:
            # Tight budgets need more time reserved for digit passes; otherwise
            # the cap progression (7 -> 8) can time out before reaching cap=8.
            number_reserve = min(
                10.0,
                self.time_budget * (0.6 if self.time_budget < 3.0 else 0.45),
            )
            fraction_cluster_reserve = (
                min(15.0, self.time_budget * 0.35) if has_fraction_tiles else 0.0
            )
            void_reserve = (
                min(3.0, self.time_budget * 0.35) if void_letter_starts else 0.0
            )
            reserved = number_reserve + void_reserve + fraction_cluster_reserve
            cap = self.time_budget * 0.85
            if reserved > cap and reserved > 0:
                scale = cap / reserved
                number_reserve *= scale
                void_reserve *= scale
                fraction_cluster_reserve *= scale
        else:
            number_reserve = 0.0
            void_reserve = 0.0
            fraction_cluster_reserve = 0.0

        chess_reserve = 0.0
        if _chess_tile_count(board) >= 3:
            # DFS cap progression can consume the whole budget on chess-heavy
            # boards. Reserve some time so the chess prefix extension phase
            # still runs.
            chess_reserve = min(8.0, self.time_budget * 0.35)

        joker_count = len(_wildcard_start_indices(board))
        hanafuda_level = hanafuda_sticker_level(loadout)
        seed_reserve = 0.0
        if hanafuda_level >= 1 and joker_count >= 2:
            seed_reserve = min(5.0, self.time_budget * 0.12)

        extension_reserve = 0.0
        if self.max_len > self.min_len:
            extension_reserve = min(5.0, self.time_budget * 0.12)

        letter_starts = _balanced_start_indices(board)
        chess_starts = _chess_start_indices(board) if chess_reserve > 0.0 else []
        if chess_starts:
            # Prefer higher indices first for short chess-cap passes, so we don't
            # starve the specific chess start tiles needed for capture-chain
            # regressions under fair-start time slicing.
            chess_starts = sorted(chess_starts, key=lambda i: i, reverse=True)
        use_parallel = (
            self.search_workers > 1
            and self._wordlist_path is not None
        )
        # Short budgets: one pass at max_len. Longer budgets: deepen so DFS does not
        # exhaust the first high-base-score branch to max_len before shorter words.
        # Parallel mode uses one pass at max_len to avoid repeated pool scheduling.
        if use_parallel:
            # One pool round at max_len; add cap=8 when jokers need hub-bridge paths.
            if (
                hanafuda_level >= 1
                and joker_count >= 2
                and self.max_len > 8
            ):
                caps = [8, self.max_len]
            else:
                caps = [self.max_len]
        elif chess_reserve > 0.0 and self.max_len > self.min_len:
            # For chess-heavy boards, a full `cap=max_len` DFS can be too
            # expensive to reach the specific capture-chain lengths in time.
            # Run a targeted pass at cap=8 first (Markkaa regression) and then
            # (only) probe cap=8.
            first_cap = 8 if self.max_len >= 8 else self.max_len
            caps = [first_cap]
        elif self.time_budget >= 6.0 and self.max_len > self.min_len:
            caps = range(self.min_len, self.max_len + 1)
        else:
            caps = [self.max_len]

        from cursed_words_solver.search_parallel import get_search_pool

        pool = (
            get_search_pool(self._wordlist_path, self.search_workers)
            if use_parallel
            else None
        )
        # Budget starts after pool handle exists (workers should already be warm).
        search_begin = time.monotonic()
        deadline = search_begin + self.time_budget
        main_deadline = (
            deadline
            - number_reserve
            - void_reserve
            - fraction_cluster_reserve
            - chess_reserve
            - seed_reserve
            - extension_reserve
        )
        pre_extend_deadline = deadline - extension_reserve if extension_reserve > 0 else deadline
        dfs_start = search_begin
        self._parallel_executor = pool
        start_productivity: dict[int, int] = {}
        if hanafuda_level >= 1 and joker_count >= 2:
            self._collect_joker_cluster_candidates(
                board,
                loadout,
                candidates,
                deadline,
                self.max_len,
            )
        heap_before_letter = len(candidates)
        try:
            for pass_idx, cap in enumerate(caps):
                if time.monotonic() >= main_deadline:
                    break
                if cap <= 8 and chess_starts:
                    starts_for_cap = chess_starts[:3]
                    min_slice = None
                else:
                    # Reorder letter starts by productivity from previous pass.
                    if pass_idx > 0 and start_productivity:
                        letter_starts = sorted(
                            letter_starts,
                            key=lambda s: (-start_productivity.get(s, 0), s),
                        )
                    starts_for_cap = letter_starts
                    min_slice = self._adaptive_min_slice(candidates, pass_idx)
                letter_pass_deadline = main_deadline
                if use_parallel and starts_for_cap is letter_starts:
                    now = time.monotonic()
                    rem = max(0.0, main_deadline - now)
                    letter_pass_deadline = min(
                        main_deadline,
                        now + min(12.0, rem * 0.45),
                    )
                self._collect_words_fair_starts(
                    board,
                    loadout,
                    candidates,
                    letter_pass_deadline,
                    cap,
                    starts_for_cap,
                    min_slice_override=min_slice,
                    start_productivity=start_productivity if starts_for_cap is letter_starts else None,
                )

            timing.letter_dfs_added = len(candidates) - heap_before_letter
            needs_serial_fallback = use_parallel and (
                not candidates
                or timing.letter_dfs_added == 0
                or candidates.all_words_max_len(1)
            )
            if needs_serial_fallback:
                timing.parallel_serial_fallback = True
                self._parallel_executor = None
                saved_workers = self.search_workers
                self.search_workers = 1
                fallback_caps = (
                    range(self.min_len, self.max_len + 1)
                    if self.time_budget >= 6.0 and self.max_len > self.min_len
                    else [self.max_len]
                )
                try:
                    for cap in fallback_caps:
                        if time.monotonic() >= pre_extend_deadline:
                            break
                        self._collect_words_fair_starts(
                            board,
                            loadout,
                            candidates,
                            pre_extend_deadline,
                            cap,
                            letter_starts,
                            min_slice_override=self._adaptive_min_slice(
                                candidates, 0
                            ),
                            start_productivity=start_productivity,
                        )
                finally:
                    self.search_workers = saved_workers
                    self._parallel_executor = pool

            if has_number_tiles:
                self._seed_single_number_tile_words(board, loadout, candidates)
                self._parallel_executor = None
                if fraction_cluster_reserve > 0 and time.monotonic() < pre_extend_deadline:
                    cluster_starts = _fraction_cluster_number_starts(board)
                    if cluster_starts:
                        cluster_deadline = min(
                            pre_extend_deadline,
                            time.monotonic() + fraction_cluster_reserve,
                        )
                        priority_starts = [
                            i
                            for i in cluster_starts
                            if float(board.get_by_index(i).base_score) >= 40.0
                        ]
                        if not priority_starts:
                            priority_starts = cluster_starts[:1]
                        cluster_cap = min(9, self.max_len)
                        for cap in range(7, cluster_cap + 1):
                            if time.monotonic() >= cluster_deadline:
                                break
                            self._collect_words_fair_starts(
                                board,
                                loadout,
                                candidates,
                                cluster_deadline,
                                cap,
                                priority_starts,
                                digits_only=True,
                            )

                if void_letter_starts and time.monotonic() < pre_extend_deadline:
                    void_cap = 7 if self.max_len >= 7 else self.max_len
                    void_deadline = min(
                        pre_extend_deadline, time.monotonic() + void_reserve
                    )
                    self._collect_words_fair_starts(
                        board,
                        loadout,
                        candidates,
                        void_deadline,
                        void_cap,
                        void_letter_starts,
                        digits_only=True,
                    )

                number_starts = _interleaved_number_starts(board)
                # With very tight budgets, focus on the most important digit
                # face (the first interleaved start) so we can still reach
                # the target length-8 word within the time slice.
                if self.time_budget <= 2.0 and number_starts:
                    number_starts = number_starts[:1]
                digit_start = max(self.min_len, 1)
                for cap in range(digit_start, self.max_len + 1):
                    if time.monotonic() >= pre_extend_deadline or not number_starts:
                        break
                    before = len(candidates)
                    self._collect_words_fair_starts(
                        board,
                        loadout,
                        candidates,
                        pre_extend_deadline,
                        cap,
                        number_starts,
                        digits_only=True,
                    )
                    # For tight budgets, the `cap=8` attempt may not add
                    # candidates in time-slice granularity even though
                    # higher caps can still discover the length-8 word.
                    if (
                        cap >= 8
                        and len(candidates) == before
                        and self.time_budget >= 6.0
                    ):
                        break
        finally:
            self._parallel_executor = None

        timing.dfs_sec = time.monotonic() - dfs_start

        seed_start = time.monotonic()
        if (
            hanafuda_level >= 1
            and joker_count >= 2
            and time.monotonic() < pre_extend_deadline
        ):
            self._collect_joker_cluster_candidates(
                board,
                loadout,
                candidates,
                pre_extend_deadline,
                self.max_len,
            )

        if (
            self.mult_search_passes
            and mult_count > 0
            and self.time_budget >= 6.0
            and time.monotonic() < pre_extend_deadline
        ):
            mult_reserve = min(4.0, self.time_budget * 0.12)
            mult_deadline = min(pre_extend_deadline, time.monotonic() + mult_reserve)
            self._collect_mult_seed_candidates(
                board,
                loadout,
                candidates,
                mult_deadline,
                self.max_len,
            )
        timing.seed_sec = time.monotonic() - seed_start

        chess_seeds: list[tuple[float, str, tuple[int, ...]]] = []
        if len(candidates) > 0 and time.monotonic() < deadline:
            chess_start = time.monotonic()
            chess_seeds = self._chess_prefix_candidates(
                board, loadout, solve_deadline=pre_extend_deadline
            )
            timing.chess_sec = time.monotonic() - chess_start
            heap_k = self.candidate_heap_size or _candidate_heap_size(top_n)
            extend_start = time.monotonic()
            extend_deadline = deadline
            top_paths = (
                min(120, len(candidates), heap_k)
                if chess_seeds
                else min(30, len(candidates), heap_k)
            )
            max_extend_rounds: int | None = None
            if self.max_len > self.min_len:
                preview = candidates.best_sorted()[:top_paths]
                if any("?" in word for _sc, word, _path in preview):
                    top_paths = min(120, len(candidates), heap_k)
                    max_extend_rounds = min(self.max_len - self.min_len, 16)
            self._extend_top_candidates(
                board,
                loadout,
                candidates,
                top_paths=top_paths,
                max_rounds=max_extend_rounds,
                extra_seeds=chess_seeds or None,
                deadline=extend_deadline if extension_reserve > 0 else deadline,
            )
            timing.extend_sec = time.monotonic() - extend_start

        timing.wall_sec = time.monotonic() - solve_start
        self.last_search_timing = timing

        seen_words: set[str] = set()
        unique: list[WordResult] = []
        for rank_sc, word, path_tuple in candidates.best_sorted():
            if word in seen_words:
                continue
            seen_words.add(word)
            path = list(path_tuple)
            immediate, setup = self._immediate_and_setup(board, path, word, loadout)
            t_final = time.perf_counter()
            _, bd = self.scoring.score(board, path, word, loadout)
            timing.final_score_sec += time.perf_counter() - t_final
            unique.append(
                WordResult(
                    word=word,
                    path=path,
                    score=immediate,
                    breakdown=bd,
                    setup_bonus=setup,
                    rank_score=rank_sc if rank_sc else immediate + setup,
                )
            )
        unique.sort(key=lambda r: (-r.score, -len(r.word), r.word))
        self._active_timing = None
        return unique[:top_n]
