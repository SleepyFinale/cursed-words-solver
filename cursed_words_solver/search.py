"""Word search on 5x5 board with curse-aware movement."""

from __future__ import annotations

import heapq
import time
from typing import Callable

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
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.scoring_conditions import (
    CARD_SUIT_FIRST_LETTER,
    card_suit,
    is_card_tile,
    fraction_parts,
    is_fraction_tile,
    is_number_like_tile,
    number_digits_ascending,
    tile_number_value,
)
from cursed_words_solver.rules.fraction_tiles import fraction_position_valid
from cursed_words_solver.rules.chess_tiles import (
    chess_neighbors,
    identical_chess_piece,
    is_chess_piece,
)
from cursed_words_solver.rules.stamp_behaviors import StampSearchFlags, stamp_search_flags

# 8 directions
DIRS_8 = [
    (-1, -1), (-1, 0), (-1, 1),
    (0, -1),           (0, 1),
    (1, -1),  (1, 0),  (1, 1),
]

TIME_CHECK_INTERVAL = 256
DEFAULT_CANDIDATE_HEAP_SIZE = 100


def index_of(row: int, col: int) -> int:
    return row * 5 + col


def _visited_has(visited: int | set[int], idx: int) -> bool:
    if isinstance(visited, set):
        return idx in visited
    return bool(visited & (1 << idx))


def _candidate_heap_size(top_n: int) -> int:
    return max(top_n * 20, DEFAULT_CANDIDATE_HEAP_SIZE)


class _CandidateHeap:
    """Min-heap of worst candidates; keeps the best K by score."""

    __slots__ = ("_k", "_heap")

    def __init__(self, k: int) -> None:
        self._k = k
        self._heap: list[tuple[float, int, str, tuple[int, ...]]] = []

    def __len__(self) -> int:
        return len(self._heap)

    def consider(self, score: float, word: str, path: list[int]) -> None:
        entry = (-score, -len(word), word, tuple(path))
        if len(self._heap) < self._k:
            heapq.heappush(self._heap, entry)
        elif entry < self._heap[0]:
            heapq.heapreplace(self._heap, entry)

    def best_sorted(self) -> list[tuple[float, str, tuple[int, ...]]]:
        out: list[tuple[float, str, tuple[int, ...]]] = []
        for neg_score, _neg_len, word, path in sorted(self._heap):
            out.append((-neg_score, word, path))
        out.sort(key=lambda x: (-x[0], -len(x[1]), x[1]))
        return out


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
    nv = tile.number_value
    if nv is None and tile.letter.isdigit():
        nv = int(tile.letter)
    if nv is None:
        return True
    pos = position + 1
    if flags and flags.number_plus_minus_one:
        return pos in (nv - 1, nv, nv + 1) and nv >= 1
    return pos == nv


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
        relaxed_fractions = self.relaxed_numbers or any(
            ch.isdigit() for ch in word
        ) and any(is_fraction_tile(board.get_by_index(idx)) for idx in path)
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
        self, board: Board, path: list[int], max_steps: int
    ) -> bool:
        """Letter prefix not in trie may still reach a NUMBER tile within max_steps."""
        visited = set(path)
        frontier = [path[-1]]
        for _ in range(max_steps):
            next_frontier: list[int] = []
            for idx in frontier:
                for nbr in neighbors_from_tile(board, [idx], visited):
                    if nbr in visited:
                        continue
                    tile = board.get_by_index(nbr)
                    if is_number_like_tile(tile):
                        return True
                    next_frontier.append(nbr)
            if not next_frontier:
                return False
            visited.update(next_frontier)
            frontier = next_frontier
        return False

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
                    if digit not in (nv - 1, nv, nv + 1) or nv < 1:
                        return False
                elif (
                    stamp_flags
                    and stamp_flags.number_ascending_free_position
                    and number_digits_ascending(word)
                ):
                    pass
                elif tile.letter != ch:
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
                    return False
                pattern_chars.append(ch)
        pattern = "".join(pattern_chars)
        if pattern and all(ch == "?" for ch in pattern):
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

    # WHITE tile: can teleport to any unused cell (once per step from white)
    if last_tile.color.value == "white":
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
    return tile.curse == CurseType.WILDCARD or tile.letter == "?"


def _wildcard_start_indices(board: Board) -> list[int]:
    return [i for i in _active_indices(board) if _is_wildcard_tile(board.get_by_index(i))]


def _balanced_start_indices(board: Board) -> list[int]:
    """Main-pass DFS order: wildcards first, then letters/high base, then numbers."""

    def priority(i: int) -> tuple[int, float, int, int]:
        tile = board.get_by_index(i)
        if _is_wildcard_tile(tile):
            return (0, 0.0, 0, i)
        if is_fraction_tile(tile):
            return (0, 0.0, 0, i)
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

    return sorted(_active_indices(board), key=priority)


def _chess_start_indices(board: Board) -> list[int]:
    """Chess tiles as DFS starts (low priority in main pass; used for prefix seeding)."""
    return [
        i
        for i in _active_indices(board)
        if is_chess_piece(board.get_by_index(i))
    ]


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

    def _min_start_slice_sec(self) -> float:
        if self.time_budget >= 12.0:
            return 1.0
        if self.time_budget >= 6.0:
            return 0.5
        if self.time_budget >= 3.0:
            return 0.25
        return 0.0

    def _collect_words_fair_starts(
        self,
        board: Board,
        loadout: Loadout,
        candidates: _CandidateHeap,
        pass_deadline: float,
        max_len: int,
        starts: list[int],
        *,
        digits_only: bool = False,
    ) -> None:
        """Give each start a fair share of pass_deadline (prevents cell 0 eating the whole budget)."""
        if not starts:
            return
        n = len(starts)
        pass_start = time.monotonic()
        pass_duration = max(pass_deadline - pass_start, 0.0)
        base_min = self._min_start_slice_sec()
        wild_in_pass = any(
            _is_wildcard_tile(board.get_by_index(i)) for i in starts
        )
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
            self._collect_words(
                board,
                loadout,
                candidates,
                sub_deadline,
                max_len,
                digits_only=digits_only,
                start_indices=[start],
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
        def score_path(path: list[int], word: str) -> float:
            if self.score_fn:
                return self.score_fn(board, path, word, loadout)
            return self.scoring.score_total_only(board, path, word, loadout)

        expansions = 0
        timed_out = False

        stamp_flags = stamp_search_flags(loadout)

        def dfs(path: list[int], letters: str, visited_mask: int) -> None:
            nonlocal expansions, timed_out
            if timed_out:
                return
            expansions += 1
            if expansions % TIME_CHECK_INTERVAL == 0:
                if time.monotonic() > deadline:
                    timed_out = True
                    return

            word = letters.lower()
            if len(word) >= self.min_len and self.validator.word_ok(
                board, path, word, stamp_flags
            ):
                if not digits_only or any(ch.isdigit() for ch in word):
                    sc = score_path(path, word)
                    candidates.consider(sc, word, path)

            if len(path) >= max_len:
                return

            steps_left = max_len - len(path)
            if "?" not in word and not self.validator.prefix_ok(
                word, board, path, steps_left, stamp_flags=stamp_flags
            ):
                return

            for idx in _neighbors_sorted_by_base_score(
                board, path, visited_mask, flags=stamp_flags
            ):
                tile = board.get_by_index(idx)
                ch = resolve_letter(tile, len(letters), flags=stamp_flags)
                dfs(path + [idx], letters + ch, visited_mask | (1 << idx))

        if start_indices is not None:
            starts = [s for s in start_indices if board.is_active_index(s)]
        else:
            starts = _active_indices(board)
        for start in starts:
            if timed_out or time.monotonic() > deadline:
                break
            tile = board.get_by_index(start)
            ch = resolve_letter(tile, 0, flags=stamp_flags)
            dfs([start], ch, 1 << start)

    def _chess_prefix_candidates(
        self,
        board: Board,
        loadout: Loadout,
        *,
        budget_sec: float = 2.0,
        max_cap: int = 5,
        heap_k: int = 200,
    ) -> list[tuple[float, str, tuple[int, ...]]]:
        """Quick DFS from chess starts; returned paths seed extension (not main heap)."""
        chess_starts = _chess_start_indices(board)
        if not chess_starts:
            return []
        mini = _CandidateHeap(heap_k)
        deadline = time.monotonic() + budget_sec
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
    ) -> None:
        """Extend strong partial paths by one tile per round (cheap cap+N refinement)."""
        if self.max_len <= self.min_len:
            return
        if max_rounds is None:
            max_rounds = min(self.max_len - self.min_len, 12)
        stamp_flags = stamp_search_flags(loadout)

        def score_path(path: list[int], word: str) -> float:
            if self.score_fn:
                return self.score_fn(board, path, word, loadout)
            return self.scoring.score_total_only(board, path, word, loadout)

        for _round in range(max_rounds):
            extended = False
            seen_prefixes: set[tuple[int, ...]] = set()
            seed_entries = list(candidates.best_sorted()[:top_paths])
            if extra_seeds:
                seed_entries.extend(extra_seeds)
            for _score, _word, path_tuple in seed_entries:
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
                    candidates.consider(sc, word, new_path)
                    extended = True
            if not extended:
                break

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

    def find_best_words(
        self,
        board: Board,
        loadout: Loadout | None = None,
        top_n: int = 3,
    ) -> list[WordResult]:
        if self.blocked:
            return []
        loadout = loadout or Loadout(money=board.money)
        heap_k = self.candidate_heap_size or _candidate_heap_size(top_n)
        candidates = _CandidateHeap(heap_k)
        start_time = time.monotonic()
        deadline = start_time + self.time_budget
        has_number_tiles = any(is_number_like_tile(t) for t in board.flat)
        has_fraction_tiles = any(is_fraction_tile(t) for t in board.flat)
        void_letter_starts = [
            i
            for i in _active_indices(board)
            if board.get_by_index(i).color == TileColor.VOID
            and board.get_by_index(i).curse == CurseType.LETTER
        ]
        if has_number_tiles:
            number_reserve = min(10.0, self.time_budget * 0.45)
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
        main_deadline = (
            deadline - number_reserve - void_reserve - fraction_cluster_reserve
        )

        letter_starts = _balanced_start_indices(board)
        # Short budgets: one pass at max_len. Longer budgets: deepen so DFS does not
        # exhaust the first high-base-score branch to max_len before shorter words.
        if self.time_budget >= 6.0 and self.max_len > self.min_len:
            caps: range | list[int] = range(self.min_len, self.max_len + 1)
        else:
            caps = [self.max_len]
        for cap in caps:
            if time.monotonic() >= main_deadline:
                break
            self._collect_words_fair_starts(
                board,
                loadout,
                candidates,
                main_deadline,
                cap,
                letter_starts,
            )

        if has_number_tiles:
            if fraction_cluster_reserve > 0 and time.monotonic() < deadline:
                cluster_starts = _fraction_cluster_number_starts(board)
                if cluster_starts:
                    cluster_deadline = min(
                        deadline, time.monotonic() + fraction_cluster_reserve
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

            if void_letter_starts and time.monotonic() < deadline:
                void_cap = 7 if self.max_len >= 7 else self.max_len
                void_deadline = min(deadline, time.monotonic() + void_reserve)
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
            digit_start = 7 if self.max_len >= 7 else 6
            for cap in range(digit_start, self.max_len + 1):
                if time.monotonic() >= deadline or not number_starts:
                    break
                before = len(candidates)
                self._collect_words_fair_starts(
                    board,
                    loadout,
                    candidates,
                    deadline,
                    cap,
                    number_starts,
                    digits_only=True,
                )
                if cap >= 8 and len(candidates) == before:
                    break

        if len(candidates) > 0:
            chess_seeds = self._chess_prefix_candidates(board, loadout)
            self._refine_candidates_with_extension(
                board,
                loadout,
                candidates,
                chess_seeds,
                top_paths=min(
                    len(candidates),
                    self.candidate_heap_size or _candidate_heap_size(top_n),
                ),
            )

        seen_words: set[str] = set()
        unique: list[WordResult] = []
        for score, word, path_tuple in candidates.best_sorted():
            if word in seen_words:
                continue
            seen_words.add(word)
            path = list(path_tuple)
            _, bd = self.scoring.score(board, path, word, loadout)
            unique.append(
                WordResult(
                    word=word,
                    path=path,
                    score=score,
                    breakdown=bd,
                )
            )
            if len(unique) >= top_n:
                break
        return unique
