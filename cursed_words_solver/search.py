"""Word search on 5x5 board with curse-aware movement."""

from __future__ import annotations

import heapq
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator

from concurrent.futures import ProcessPoolExecutor

from cursed_words_solver.config import DEFAULT_SEARCH_TIME_BUDGET_SEC
from cursed_words_solver.dictionary import TrieCursor, WordDictionary
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
from cursed_words_solver.fingerprints import board_fingerprint
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.scoring_conditions import (
    CARD_SUIT_FIRST_LETTER,
    card_suit,
    hanafuda_hand_satisfied,
    is_card_tile,
    is_consumable_tile,
    is_joker_tile,
    is_fraction_tile,
    is_number_like_tile,
    is_placed_consumable_tile,
    number_digits_ascending,
    tile_counts_as_color,
    tile_number_value,
    word_starts_ends_consumable,
    word_starts_ends_different_suit,
)
from cursed_words_solver.rules.fraction_tiles import (
    fraction_position_valid,
    tile_fraction_position_values,
)
from cursed_words_solver.fast_rank import (
    build_search_tile_base,
    loadout_allows_dfs_bb,
    loadout_allows_fast_rank,
    loadout_allows_mult_prune,
    loadout_allows_tier2_screen,
    loadout_allows_tier2_two_phase,
    mult_aware_lower_bound,
    number_aware_lower_bound,
    path_has_scattered_grid_items,
    prefix_immediate_upper_bound,
    prefix_rank_upper_bound,
    tier2_immediate_lower_bound,
    tier2_immediate_upper_bound,
    tier2_rank_lower_bound,
    tier2_rank_upper_bound,
)
from cursed_words_solver.rules.quest_scoring import (
    bullseye_active,
    encounter_remaining_from_loadout,
    prune_cannot_beat_heap,
    quest_candidate_rank,
    quest_inverts_search_rank,
    quest_skips_rank_ub_prune,
    search_rank_for_quest,
    set_quest_search_target,
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
    chess_neighbors_mask,
    chess_side,
    chess_side_known,
    clear_chess_attack_cache,
    identical_chess_piece,
    is_chess_piece,
)
from cursed_words_solver.graph_bitboard import (
    BoardGraphContext,
    CELL_COUNT,
    CURSE_CODE_NUMBER,
    NEIGHBORS_8,
    NEIGHBORS_8_WRAP,
    RED_COLOR_CODE,
    build_board_graph_context,
    collect_mask_indices,
    get_valid_extensions,
    iter_mask,
    mask_from_indices,
)
from cursed_words_solver.rules.stamp_behaviors import (
    FLAG_CARD_SUIT_FIRST_LETTER,
    FLAG_CHESS_ALLIES_CAN_TAKE,
    FLAG_DOUBLE_LETTER_TELEPORT,
    FLAG_HORIZONTAL_WRAP,
    FLAG_J_AS_H_OR_Y,
    FLAG_MICROSCOPE_BASE_SCORE,
    FLAG_NUMBER_ASCENDING_FREE_POSITION,
    FLAG_NUMBER_PLUS_MINUS_ONE,
    FLAG_NUMBER_ROMAN_IVX,
    FLAG_Q_AS_QU,
    FLAG_RED_AS_E,
    FLAG_RED_AS_S,
    FLAG_RED_LETTER_PLUS_MINUS_ONE,
    FLAG_SHINY_AS_ONE,
    FLAG_WORD_STITCH,
    FLAG_Z_AS_S,
    SearchFlagsMask,
    coerce_search_flags,
    flag_clear,
    flag_test,
    path_scattered_search_flags_mask,
)
from cursed_words_solver.solve_context import (
    SolveContext,
    build_solve_context,
    hanafuda_sticker_level,
)
from cursed_words_solver.setup_value import (
    project_setup_delta,
    rank_score_for_word,
    setup_future_value,
)
from cursed_words_solver.stamp_improve_words import equipped_improve_words

# 8 directions
DIRS_8 = [
    (-1, -1), (-1, 0), (-1, 1),
    (0, -1),           (0, 1),
    (1, -1),  (1, 0),  (1, 1),
]

TIME_CHECK_INTERVAL = 256
DEFAULT_CANDIDATE_HEAP_SIZE = 100
_WILDCARD_LETTERS = tuple("abcdefghijklmnopqrstuvwxyz")
_NEIGHBOR_SCRATCH: list[int] = [0] * CELL_COUNT
MAIN_DFS_FLOOR_FRAC = 0.30
MAX_TOTAL_RESERVE_FRAC = 0.55
REFINE_OVERRUN_SEC = 10.0
TIER2_ADAPTIVE_SAMPLE_SEC = 2.0
TIER2_DEFER_CAP_NORMAL = 500
TIER2_DEFER_CAP_DEEP = 2000


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
    refine_sec: float = 0.0
    score_calls: int = 0
    worker_score_calls: int = 0
    parallel_serial_fallback: bool = False
    reserve_scaling_applied: bool = False
    main_dfs_slice_sec: float = 0.0
    refine_overrun_sec: float = 0.0
    refine_overrun_deferred: int = 0
    letter_dfs_added: int = 0
    dfs_expansions: int = 0
    score_cache_hits: int = 0
    score_cache_misses: int = 0
    dict_path_cache_hits: int = 0
    dict_path_cache_misses: int = 0
    chess_attack_cache_hits: int = 0
    chess_attack_cache_misses: int = 0
    board_flat_calls: int = 0
    trie_steps: int = 0
    trie_prunes: int = 0
    trie_fast_accepts: int = 0
    tier2_screen_sec: float = 0.0
    tier2_screen_skips: int = 0
    tier2_screen_calls: int = 0
    tier2_rank_screen_skips: int = 0
    tier2_phase1_calls: int = 0
    tier2_phase2_calls: int = 0
    tier2_phase2_deferred: int = 0
    dfs_bb_prunes: int = 0
    dfs_bb_calls: int = 0
    grid_refs_cache_hits: int = 0
    grid_refs_cache_misses: int = 0

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


def _prefix_tile_base(
    graph_ctx: BoardGraphContext,
    search_tile_base: tuple[float, ...],
    idx: int,
) -> float:
    if graph_ctx.item_mask & (1 << idx):
        return graph_ctx.item_tile_base[idx]
    return search_tile_base[idx]


def index_of(row: int, col: int) -> int:
    return row * 5 + col


def _visited_has(visited: int | set[int], idx: int) -> bool:
    if isinstance(visited, set):
        return idx in visited
    return bool(visited & (1 << idx))


def _candidate_heap_size(
    top_n: int,
    mult_rule_count: int = 0,
    graph_ctx: BoardGraphContext | None = None,
) -> int:
    base = max(top_n * 20, DEFAULT_CANDIDATE_HEAP_SIZE)
    if mult_rule_count >= 2:
        base = int(base * (1 + 0.25 * mult_rule_count))
    if graph_ctx is not None:
        branch = (
            graph_ctx.wildcard_mask.bit_count()
            + graph_ctx.chess_piece_mask.bit_count() * 2
            + graph_ctx.item_mask.bit_count()
        )
        if branch >= 6:
            base = int(base * 1.5)
        elif branch <= 2:
            base = max(int(base * 0.85), max(top_n * 10, DEFAULT_CANDIDATE_HEAP_SIZE // 2))
    return base


def _scale_post_dfs_reserves(
    *,
    time_budget: float,
    number_reserve: float,
    void_reserve: float,
    fraction_cluster_reserve: float,
    chess_reserve: float,
    seed_reserve: float,
    extension_reserve: float,
    up_and_up_reserve: float = 0.0,
) -> tuple[float, float, float, float, float, float, float, bool]:
    """Scale post-DFS reserves so primary DFS keeps a minimum time slice."""
    reserves = [
        number_reserve,
        void_reserve,
        fraction_cluster_reserve,
        chess_reserve,
        seed_reserve,
        extension_reserve,
        up_and_up_reserve,
    ]
    scaled = False
    total = sum(reserves)
    max_total = time_budget * MAX_TOTAL_RESERVE_FRAC
    if total > max_total and total > 0:
        factor = max_total / total
        reserves = [r * factor for r in reserves]
        scaled = True
        total = sum(reserves)
    floor = time_budget * MAIN_DFS_FLOOR_FRAC
    if time_budget - total < floor and total > 0:
        max_allowed = max(0.0, time_budget - floor)
        factor = max_allowed / total
        reserves = [r * factor for r in reserves]
        scaled = True
    return (
        reserves[0],
        reserves[1],
        reserves[2],
        reserves[3],
        reserves[4],
        reserves[5],
        reserves[6],
        scaled,
    )


def _path_shares_leader_prefix(
    path: tuple[int, ...], leader_prefixes: list[tuple[int, ...]]
) -> bool:
    for prefix in leader_prefixes:
        if len(path) >= len(prefix) and path[: len(prefix)] == prefix:
            return True
        if len(prefix) >= len(path) and prefix[: len(path)] == path:
            return True
    return False


class _CandidateHeap:
    """Min-heap of worst candidates; keeps the best K by rank_score."""

    __slots__ = ("_k", "_heap")

    def __init__(self, k: int) -> None:
        self._k = k
        self._heap: list[tuple[float, float, int, str, tuple[int, ...]]] = []

    def __len__(self) -> int:
        return len(self._heap)

    def consider(
        self,
        score: float,
        word: str,
        path: list[int],
        *,
        immediate: float | None = None,
    ) -> None:
        # Keep best candidates by rank_score. For equal rank, prefer longer words
        # so late chess/board extensions with the same immediate score don't get
        # evicted by shorter prefixes.
        imm = -1.0 if immediate is None else float(immediate)
        entry = (score, imm, len(word), word, tuple(path))
        if len(self._heap) < self._k:
            heapq.heappush(self._heap, entry)
        elif (score, imm, len(word)) > (self._heap[0][0], self._heap[0][1], self._heap[0][2]):
            heapq.heapreplace(self._heap, entry)

    def min_rank_score(self) -> float | None:
        """Lowest rank_score among kept candidates, or None if heap not full."""
        if len(self._heap) < self._k:
            return None
        return self._heap[0][0]

    def min_immediate_score(self) -> float | None:
        """Lowest pipeline immediate among scored heap entries, or None if heap not full."""
        if len(self._heap) < self._k:
            return None
        known = [entry[1] for entry in self._heap if entry[1] >= 0.0]
        if not known:
            return None
        return min(known)

    def max_immediate_score(self) -> float | None:
        """Best pipeline immediate among scored heap entries, or None if heap empty."""
        if not self._heap:
            return None
        known = [entry[1] for entry in self._heap if entry[1] >= 0.0]
        if not known:
            return None
        return max(known)

    def max_rank_score(self) -> float | None:
        """Best rank_score among heap entries, or None if heap empty."""
        if not self._heap:
            return None
        return max(entry[0] for entry in self._heap)

    def replace_entry(
        self,
        word: str,
        path: tuple[int, ...],
        *,
        score: float,
        immediate: float,
    ) -> bool:
        """Update a heap entry after deferred phase-2 scoring."""
        for i, entry in enumerate(self._heap):
            if entry[3] == word and entry[4] == path:
                self._heap[i] = (score, immediate, len(word), word, path)
                heapq.heapify(self._heap)
                return True
        return False

    def best_sorted(self) -> list[tuple[float, str, tuple[int, ...]]]:
        out: list[tuple[float, str, tuple[int, ...]]] = []
        for score, _imm, _neg_len, word, path in sorted(self._heap, reverse=True):
            out.append((score, word, path))
        out.sort(key=lambda x: (-x[0], -len(x[1]), x[1]))
        return out

    def all_words_max_len(self, max_len: int) -> bool:
        if not self._heap:
            return False
        return all(len(entry[3]) <= max_len for entry in self._heap)

    def all_paths_max_len(self, max_len: int) -> bool:
        if not self._heap:
            return False
        return all(len(entry[4]) <= max_len for entry in self._heap)


def resolve_letter(
    tile: Tile,
    position: int,
    *,
    flags: SearchFlagsMask = 0,
) -> str:
    """Letter used in word at 0-based position."""
    flags = coerce_search_flags(flags)
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
    if tile.curse == CurseType.ITEM:
        return "?"
    if tile.curse == CurseType.ARROW:
        from cursed_words_solver.arrow_tiles import arrow_glyph_from_tile

        if arrow_glyph_from_tile(tile) is not None:
            return "?"
        ch = (tile.letter or "").strip()
        if len(ch) == 1 and ch.isalpha():
            return ch.upper()
        return "?"
    if flag_test(flags, FLAG_CARD_SUIT_FIRST_LETTER) and is_card_tile(tile):
        suit = card_suit(tile)
        if suit and suit in CARD_SUIT_FIRST_LETTER:
            return CARD_SUIT_FIRST_LETTER[suit]
    if (
        flag_test(flags, FLAG_SHINY_AS_ONE)
        and position == 0
        and tile.color == TileColor.SHINY
        and tile.curse == CurseType.LETTER
    ):
        return "1"
    ch = (tile.letter or "?").lower()
    if flag_test(flags, FLAG_RED_AS_S) and tile.color == TileColor.RED and tile.curse == CurseType.LETTER:
        return "s"
    if flag_test(flags, FLAG_RED_AS_E) and tile.color == TileColor.RED and tile.curse == CurseType.LETTER:
        return "e"
    if flag_test(flags, FLAG_Z_AS_S) and ch == "z":
        return "s"
    if flag_test(flags, FLAG_Q_AS_QU) and ch == "q":
        return "qu"
    return tile.letter.upper() if tile.letter else "?"


def path_word_char_len(
    board: Board,
    path: list[int],
    *,
    flags: SearchFlagsMask = 0,
    through_path_index: int | None = None,
) -> int:
    """Character length of the word string built from path tiles (0-based char offset after last tile)."""
    flags = coerce_search_flags(flags)
    char_pos = 0
    for path_i, idx in enumerate(path):
        if through_path_index is not None and path_i > through_path_index:
            break
        tile = board.get_by_index(idx)
        if tile.curse == CurseType.ITEM:
            char_pos += 1
        else:
            char_pos += len(resolve_letter(tile, char_pos, flags=flags))
    return char_pos


def search_word_from_path(
    board: Board,
    path: list[int],
    *,
    flags: SearchFlagsMask = 0,
) -> str:
    """Search trie / dictionary resolve string; scattered items count as wildcards."""
    flags = coerce_search_flags(flags)
    parts: list[str] = []
    char_pos = 0
    for idx in path:
        tile = board.get_by_index(idx)
        if tile.curse == CurseType.ITEM:
            parts.append("?")
            char_pos += 1
        else:
            token = resolve_letter(tile, char_pos, flags=flags)
            parts.append(token)
            char_pos += len(token)
    return "".join(parts).lower()


def physical_word_for_path(
    board: Board,
    path: list[int],
    *,
    flags: SearchFlagsMask = 0,
) -> str:
    """Word from tile face letters; ignores Card Shark suit-first-letter remapping."""
    flags = coerce_search_flags(flags)
    phys_flags = (
        flag_clear(flags, FLAG_CARD_SUIT_FIRST_LETTER)
        if flag_test(flags, FLAG_CARD_SUIT_FIRST_LETTER)
        else flags
    )
    parts: list[str] = []
    char_pos = 0
    for idx in path:
        token = resolve_letter(board.get_by_index(idx), char_pos, flags=phys_flags)
        parts.append(token)
        char_pos += len(token)
    return "".join(parts).lower()


ROMAN_BY_NUMBER: dict[int, str] = {1: "i", 5: "v", 10: "x"}


def resolve_letter_options(
    tile: Tile,
    position: int,
    *,
    flags: SearchFlagsMask = 0,
) -> list[str]:
    """Lowercase letter alternatives for search validation."""
    flags = coerce_search_flags(flags)
    base = resolve_letter(tile, position, flags=flags)
    if base in ("?", "qu") or len(base) != 1:
        return [base.lower() if base != "?" else "?"]
    ch = base.lower()
    physical = (tile.letter or "").strip().lower()
    if len(physical) == 1 and physical.isalpha() and physical != ch:
        alts = {ch, physical}
    else:
        alts = {ch}
    if flag_test(flags, FLAG_J_AS_H_OR_Y) and (ch == "j" or physical == "j"):
        return ["h", "y"]
    if (
        flag_test(flags, FLAG_RED_LETTER_PLUS_MINUS_ONE)
        and tile.color == TileColor.RED
        and tile.curse == CurseType.LETTER
        and ch.isalpha()
    ):
        expanded: set[str] = set()
        for letter in alts:
            if not letter.isalpha() or len(letter) != 1:
                continue
            expanded.add(letter)
            if letter > "a":
                expanded.add(chr(ord(letter) - 1))
            if letter < "z":
                expanded.add(chr(ord(letter) + 1))
        alts = expanded
    if tile.metadata.get("is_wobbly") and physical and physical.isalpha():
        alts.add(physical)
        if flag_test(flags, FLAG_RED_AS_E) and tile.color == TileColor.RED:
            alts.add("e")
        if flag_test(flags, FLAG_RED_AS_S) and tile.color == TileColor.RED:
            alts.add("s")
        if flag_test(flags, FLAG_Z_AS_S) and physical == "z":
            alts.add("s")
    return sorted(alts)


def _wildcard_branch_letters(
    tile: Tile,
    position: int,
    *,
    flags: SearchFlagsMask = 0,
) -> tuple[str, ...]:
    """Letters to try when a tile resolves to wildcard '?' during trie DFS."""
    token = resolve_letter(tile, position, flags=flags)
    if "?" not in token:
        return ()
    options = resolve_letter_options(tile, position, flags=flags)
    if len(options) == 1 and options[0] == "?":
        return _WILDCARD_LETTERS
    letters = tuple(
        o.lower() for o in options if len(o) == 1 and o.isalpha()
    )
    return letters if letters else _WILDCARD_LETTERS


def _tile_word_token(tile: Tile, char_pos: int, *, flags: SearchFlagsMask = 0) -> str:
    """Lowercase token this tile contributes to a path word string at char_pos."""
    return resolve_letter(tile, char_pos, flags=flags).lower()


def path_letter_tiles_match_word(
    board: Board,
    path: list[int],
    word: str,
    *,
    flags: SearchFlagsMask = 0,
) -> bool:
    """True when each letter tile on the path allows its word segment (stamp transforms)."""
    char_pos = 0
    for i, idx in enumerate(path):
        tile = board.get_by_index(idx)
        token = _tile_word_token(tile, char_pos, flags=flags)
        if tile.curse != CurseType.LETTER:
            char_pos += len(token)
            continue
        if char_pos >= len(word):
            return False
        if len(token) == 2 and token == "qu":
            if word[char_pos : char_pos + 2].lower() != "qu":
                return False
            char_pos += 2
            continue
        ch = word[char_pos].lower()
        if not ch.isalpha():
            return False
        options = resolve_letter_options(tile, char_pos, flags=flags)
        allowed = {o.lower() for o in options if o not in ("?", "qu")}
        if ch not in allowed:
            return False
        char_pos += 1
    return char_pos == len(word)


def _tile_accepts_word_letter(
    tile: Tile,
    path_index: int,
    letter: str,
    word: str,
    *,
    flags: SearchFlagsMask = 0,
) -> bool:
    """Whether dictionary letter may sit on tile at path_index (full-board word placement)."""
    flags = coerce_search_flags(flags)
    ch = letter.lower()
    if not ch.isalpha():
        return False
    if not number_position_valid(tile, path_index, segment=word, flags=flags):
        return False
    if not fraction_position_valid(tile, path_index, relaxed=False):
        return False
    if tile.curse == CurseType.LETTER:
        options = resolve_letter_options(tile, path_index, flags=flags)
        allowed = {o.lower() for o in options if len(o) == 1 and o.isalpha()}
        return not allowed or ch in allowed
    if tile.curse in CHESS_CURSES:
        face = (tile.letter or "").strip()
        if face not in ("", "?"):
            options = resolve_letter_options(tile, path_index, flags=flags)
            allowed = {o.lower() for o in options if len(o) == 1 and o.isalpha()}
            if allowed and ch not in allowed:
                return False
        return True
    if tile.curse == CurseType.NUMBER:
        return is_numeric_wildcard(tile, path_index, flags=flags, segment=word)
    return True


def word_assignable_on_path(
    board: Board,
    path: list[int],
    word: str,
    *,
    flags: SearchFlagsMask = 0,
) -> bool:
    """True when each dictionary letter is allowed on its path tile (stamps, chess, wildcards)."""
    flags = coerce_search_flags(flags)
    if len(word) != len(path):
        return False
    lowered = word.lower()
    for i, idx in enumerate(path):
        tile = board.get_by_index(idx)
        ch = lowered[i]
        if not ch.isalpha():
            return False
        if tile.curse == CurseType.LETTER:
            options = resolve_letter_options(tile, i, flags=flags)
            allowed = {o.lower() for o in options if len(o) == 1 and o.isalpha()}
            if allowed and ch not in allowed:
                return False
            continue
        if tile.curse in CHESS_CURSES:
            face = (tile.letter or "").strip()
            if face not in ("", "?"):
                options = resolve_letter_options(tile, i, flags=flags)
                allowed = {o.lower() for o in options if len(o) == 1 and o.isalpha()}
                if allowed and ch not in allowed:
                    return False
            continue
        # Items, fractions, wildcards, and chess with letter "?" accept any alpha.
    return True


def _tile_digit_face_matches(
    segment: str,
    tile: Tile,
    stamp_flags: SearchFlagsMask,
) -> bool:
    """True when segment equals the tile's number face (supports multi-digit Bison tiles)."""
    if not segment.isdigit():
        return False
    stamp_flags = coerce_search_flags(stamp_flags)
    if tile.letter == segment or tile.letter.lower() == segment.lower():
        return True
    if tile.curse == CurseType.NUMBER:
        nv = tile_number_value(tile)
        if nv and str(nv) == segment:
            return True
    if flag_test(stamp_flags, FLAG_MICROSCOPE_BASE_SCORE):
        bp = _microscope_base_as_position(tile)
        if bp is not None and str(bp) == segment:
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


def _microscope_face_number_values(tile: Tile) -> list[int]:
    """1-based positions from face number only (no Microscope base_score alternate)."""
    if tile.curse != CurseType.NUMBER:
        return []
    nv = tile_number_value(tile)
    if nv is None and tile.letter.isdigit():
        nv = int(tile.letter)
    if nv is not None and nv >= 1:
        return [nv]
    return []


def microscope_position_uses(
    board: Board,
    path: list[int],
    word: str,
    *,
    flags: SearchFlagsMask = 0,
) -> list[dict[str, Any]]:
    """Positions where Microscope base_score flex was required (not face-number slots)."""
    flags = coerce_search_flags(flags)
    if not flag_test(flags, FLAG_MICROSCOPE_BASE_SCORE):
        return []
    uses: list[dict[str, Any]] = []
    char_pos = 0
    for i, idx in enumerate(path):
        tile = board.get_by_index(idx)
        token = _tile_word_token(tile, char_pos, flags=flags)
        if char_pos + len(token) > len(word):
            return uses
        segment = word[char_pos : char_pos + len(token)]
        char_pos += len(token)
        bp = _microscope_base_as_position(tile)
        if bp is None:
            continue
        pos = i + 1
        if pos != bp:
            continue
        face_values = _microscope_face_number_values(tile)
        if tile.curse == CurseType.LETTER:
            if segment.isdigit() and int(segment) == bp:
                uses.append(
                    {
                        "index": idx,
                        "position": pos,
                        "tile": tile.letter,
                        "base_score": bp,
                        "mode": "letter_as_digit",
                    }
                )
            continue
        if tile.curse == CurseType.NUMBER and pos not in face_values:
            uses.append(
                {
                    "index": idx,
                    "position": pos,
                    "tile": tile.letter,
                    "face": face_values[0] if face_values else None,
                    "base_score": bp,
                    "mode": "alternate_number_position",
                }
            )
    return uses


def format_microscope_position_hint(uses: list[dict[str, Any]]) -> str:
    """Single-line hint for overlay / trace when Microscope position flex applies."""
    if not uses:
        return ""
    parts: list[str] = []
    for use in uses:
        tile = str(use.get("tile") or "?")
        pos = int(use["position"])
        base = int(use["base_score"])
        if use.get("mode") == "letter_as_digit":
            parts.append(f"{tile} as digit {base} at position {pos}")
        else:
            face = use.get("face")
            if face is not None:
                parts.append(
                    f"{tile} at position {pos} via base_score {base} (face {face})"
                )
            else:
                parts.append(f"{tile} at position {pos} via base_score {base}")
    return "Microscope: " + "; ".join(parts)


def tile_number_position_values(
    tile: Tile,
    flags: SearchFlagsMask,
) -> list[int]:
    """1-based position indices this tile may claim (face number + Microscope base_score)."""
    flags = coerce_search_flags(flags)
    values: list[int] = []
    if tile.curse == CurseType.NUMBER:
        nv = tile.number_value
        if nv is None and tile.letter.isdigit():
            nv = int(tile.letter)
        if nv is not None and nv >= 1:
            values.append(nv)
        if (
            flag_test(flags, FLAG_SHINY_AS_ONE)
            and tile.color == TileColor.SHINY
            and 1 not in values
        ):
            values.append(1)
    if flag_test(flags, FLAG_MICROSCOPE_BASE_SCORE):
        bp = _microscope_base_as_position(tile)
        if bp is not None and bp not in values:
            values.append(bp)
    return values


def is_numeric_wildcard(
    tile: Tile,
    path_index: int,
    *,
    flags: SearchFlagsMask = 0,
    segment: str | None = None,
) -> bool:
    """True when tile is a numeric wildcard at path_index (game Tile.IsNumericWildcard)."""
    flags = coerce_search_flags(flags)
    if tile.curse != CurseType.NUMBER:
        return False
    if (
        flag_test(flags, FLAG_NUMBER_ASCENDING_FREE_POSITION)
        and segment
        and number_digits_ascending(segment)
    ):
        return True
    values = tile_number_position_values(tile, flags)
    if not values:
        return False
    return _position_matches_number_values(path_index, values, flags)


def _position_matches_number_values(
    position: int,
    values: list[int],
    flags: SearchFlagsMask,
) -> bool:
    if not values:
        return True
    pos = position + 1
    if flag_test(flags, FLAG_NUMBER_PLUS_MINUS_ONE):
        return any(pos in (v - 1, v, v + 1) and v >= 1 for v in values)
    return any(pos == v for v in values)


def number_position_valid(
    tile: Tile,
    position: int,
    relaxed: bool = False,
    *,
    flags: SearchFlagsMask = 0,
    segment: str | None = None,
) -> bool:
    flags = coerce_search_flags(flags)
    if (
        flag_test(flags, FLAG_SHINY_AS_ONE)
        and position == 0
        and tile.color == TileColor.SHINY
        and tile.curse == CurseType.LETTER
    ):
        return True
    if relaxed or tile.curse != CurseType.NUMBER:
        return True
    if (
        segment
        and position < len(segment)
        and segment[position].isalpha()
    ):
        return is_numeric_wildcard(
            tile, position, flags=flags, segment=segment
        )
    if (
        flag_test(flags, FLAG_NUMBER_ASCENDING_FREE_POSITION)
        and segment
        and number_digits_ascending(segment)
    ):
        return True
    if (
        flag_test(flags, FLAG_NUMBER_ROMAN_IVX)
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


_quest_movement_loadout: Loadout | None = None


def set_quest_movement_loadout(loadout: Loadout | None) -> None:
    global _quest_movement_loadout
    _quest_movement_loadout = loadout


def path_movement_ok(
    board: Board,
    path: list[int],
    *,
    flags: SearchFlagsMask = 0,
    graph_ctx: BoardGraphContext | None = None,
) -> bool:
    """True when every consecutive pair follows search neighbor rules (8-dir, wrap, chess, etc.)."""
    if len(path) < 2:
        return True
    visited = 0
    for i in range(len(path) - 1):
        a, b = path[i], path[i + 1]
        visited |= 1 << a
        mask = neighbors_mask(
            board,
            visited,
            cell_id=a,
            flags=flags,
            graph_ctx=graph_ctx,
        )
        if not (mask & (1 << b)):
            return False
        visited |= 1 << b
    return True


class PathValidator:
    def __init__(
        self,
        dictionary: WordDictionary,
        min_len: int = 3,
        relaxed_numbers: bool = False,
        extra_valid_words: frozenset[str] = frozenset(),
    ) -> None:
        self.dictionary = dictionary
        self.min_len = min_len
        self.relaxed_numbers = relaxed_numbers
        self.extra_valid_words = extra_valid_words
        self.required_consumable_indices: frozenset[int] = frozenset()
        self.quest_loadout: Loadout | None = None

    def build_word(self, board: Board, path: list[int], letters: str) -> str:
        return letters.lower()

    def prefix_ok(
        self,
        prefix: str,
        board: Board | None = None,
        path: list[int] | None = None,
        steps_remaining: int = 0,
        stamp_flags: SearchFlagsMask = 0,
    ) -> bool:
        stamp_flags = coerce_search_flags(stamp_flags)
        if "?" in prefix:
            return self.dictionary.pattern_has_prefix(prefix.lower())
        if any(ch.isdigit() for ch in prefix):
            pat = "".join(
                "?" if c.isdigit() else c.lower()
                for c in prefix
                if c.isalpha() or c.isdigit()
            )
            if self.dictionary.pattern_has_prefix(pat):
                return True
        if self.dictionary.has_prefix(prefix):
            return True
        if flag_test(stamp_flags, FLAG_WORD_STITCH):
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
        if self.extra_valid_words:
            pl = prefix.lower()
            if any(
                w.startswith(pl) and len(w) >= self.min_len
                for w in self.extra_valid_words
            ):
                return True
        return False

    def _path_constraints_ok(
        self,
        board: Board,
        path: list[int],
        word: str,
        stamp_flags: SearchFlagsMask,
    ) -> bool:
        required = self.required_consumable_indices
        if required and not required.issubset(path):
            return False
        from cursed_words_solver.rules.quest_effects import quest_path_allowed

        if not quest_path_allowed(board, path, loadout=self.quest_loadout):
            return False
        if not path_movement_ok(board, path, flags=stamp_flags):
            return False
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
        stamp_flags: SearchFlagsMask,
    ) -> bool:
        if any(ch.isdigit() for ch in word):
            return self._number_word_valid(board, path, word, stamp_flags)
        if "?" in word:
            return self._wildcard_valid(word)
        if any(is_number_like_tile(board.get_by_index(i)) for i in path):
            return self._number_word_valid(board, path, word, stamp_flags)
        if word.lower() in self.extra_valid_words:
            return len(word) >= self.min_len
        if not self.dictionary.is_valid_word(word, self.min_len):
            return False
        return word_assignable_on_path(board, path, word, flags=stamp_flags)

    def _stitched_word_ok(
        self,
        board: Board,
        path: list[int],
        word: str,
        stamp_flags: SearchFlagsMask,
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
        stamp_flags: SearchFlagsMask = 0,
    ) -> bool:
        stamp_flags = coerce_search_flags(stamp_flags)
        if len(word) < self.min_len:
            return False
        if self._path_constraints_ok(board, path, word, stamp_flags) and self._word_content_ok(
            board, path, word, stamp_flags
        ):
            return True
        if flag_test(stamp_flags, FLAG_WORD_STITCH):
            return self._stitched_word_ok(board, path, word, stamp_flags)
        return False

    def _number_word_valid(
        self,
        board: Board,
        path: list[int],
        word: str,
        stamp_flags: SearchFlagsMask = 0,
    ) -> bool:
        """Number tiles are position-locked wildcards; validate via dictionary pattern."""
        stamp_flags = coerce_search_flags(stamp_flags)
        char_pos = 0
        pattern_chars: list[str] = []
        for i, idx in enumerate(path):
            tile = board.get_by_index(idx)
            if char_pos >= len(word):
                return False
            if (
                tile.curse == CurseType.NUMBER
                and word[char_pos].isdigit()
            ):
                face = str(tile_number_value(tile))
                if (
                    face.isdigit()
                    and len(face) > 1
                    and char_pos + len(face) <= len(word)
                ):
                    segment = word[char_pos : char_pos + len(face)]
                    if segment.isdigit() and _tile_digit_face_matches(
                        segment, tile, stamp_flags
                    ):
                        if not self._number_digit_segment_ok(
                            segment, tile, i, word, stamp_flags
                        ):
                            return False
                        pattern_chars.append("?")
                        char_pos += len(face)
                        continue
            ch = word[char_pos]
            if ch.isdigit():
                if (
                    flag_test(stamp_flags, FLAG_SHINY_AS_ONE)
                    and tile.color == TileColor.SHINY
                    and tile.curse == CurseType.LETTER
                    and int(ch) == 1
                ):
                    if i + 1 != 1:
                        return False
                    pattern_chars.append("?")
                    char_pos += 1
                    continue
                if is_fraction_tile(tile):
                    if not fraction_position_valid(
                        tile, i, relaxed=self.relaxed_numbers
                    ):
                        return False
                    pattern_chars.append("?")
                    char_pos += 1
                    continue
                if tile.curse != CurseType.NUMBER:
                    if (
                        flag_test(stamp_flags, FLAG_MICROSCOPE_BASE_SCORE)
                        and _tile_digit_face_matches(ch, tile, stamp_flags)
                    ):
                        bp = _microscope_base_as_position(tile)
                        if bp is not None and i + 1 == bp:
                            pattern_chars.append("?")
                            char_pos += 1
                            continue
                    return False
                if not self._number_digit_segment_ok(
                    ch, tile, i, word, stamp_flags
                ):
                    return False
                pattern_chars.append("?")
                char_pos += 1
            else:
                if is_fraction_tile(tile):
                    if not fraction_position_valid(
                        tile, i, relaxed=self.relaxed_numbers
                    ):
                        return False
                    pattern_chars.append("?")
                    char_pos += 1
                    continue
                if tile.curse == CurseType.NUMBER:
                    if (
                        flag_test(stamp_flags, FLAG_NUMBER_ROMAN_IVX)
                        and ch.isalpha()
                    ):
                        nv = tile_number_value(tile)
                        if nv in ROMAN_BY_NUMBER and ch.lower() == ROMAN_BY_NUMBER[nv]:
                            pattern_chars.append("?")
                            char_pos += 1
                            continue
                    if ch.isalpha():
                        if is_numeric_wildcard(
                            tile, i, flags=stamp_flags, segment=word
                        ):
                            pattern_chars.append("?")
                            char_pos += 1
                            continue
                        return False
                    return False
                if tile.curse == CurseType.LETTER:
                    token = _tile_word_token(tile, char_pos, flags=stamp_flags)
                    if len(token) == 2 and token == "qu":
                        if word[char_pos : char_pos + 2].lower() != "qu":
                            return False
                        pattern_chars.append("?")
                        char_pos += 2
                        continue
                    options = resolve_letter_options(tile, char_pos, flags=stamp_flags)
                    allowed = {o.lower() for o in options if o not in ("?", "qu")}
                    if not ch.isalpha() or ch.lower() not in allowed:
                        return False
                pattern_chars.append(ch)
                char_pos += 1
        if char_pos != len(word):
            return False
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

    def _number_digit_segment_ok(
        self,
        segment: str,
        tile: Tile,
        tile_index: int,
        word: str,
        stamp_flags: SearchFlagsMask,
    ) -> bool:
        """Digit segment at a NUMBER tile matches face / stamp flex rules."""
        stamp_flags = coerce_search_flags(stamp_flags)
        try:
            digit_val = int(segment)
        except ValueError:
            return False
        if flag_test(stamp_flags, FLAG_NUMBER_PLUS_MINUS_ONE):
            values = tile_number_position_values(tile, stamp_flags)
            allowed = {
                x
                for v in values
                if v >= 1
                for x in (v - 1, v, v + 1)
            }
            return digit_val in allowed
        if (
            flag_test(stamp_flags, FLAG_NUMBER_ASCENDING_FREE_POSITION)
            and number_digits_ascending(word)
        ):
            return True
        return _tile_digit_face_matches(segment, tile, stamp_flags)

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
    return [i for i in range(board.cell_count) if board.is_active_index(i)]


def tile_playable_for_path(tile: Tile) -> bool:
    """False when SupplyAndDemand (or similar) marks the tile crossed out."""
    from cursed_words_solver.rules.quest_effects import tile_is_crossed_out

    return not tile_is_crossed_out(tile)


def _legal_word_start_indices(board: Board) -> list[int]:
    """Active tiles that may start a word (fractions only when 1-based pos 1 is legal)."""
    out: list[int] = []
    for i in _active_indices(board):
        tile = board.get_by_index(i)
        if not tile_playable_for_path(tile):
            continue
        if is_fraction_tile(tile) and not fraction_position_valid(tile, 0, relaxed=False):
            continue
        out.append(i)
    return out


def _probe_fraction_chess_prefixes(
    board: Board,
    loadout: Loadout,
    *,
    max_depth: int = 6,
    max_paths: int = 80,
    max_visited: int = 1200,
) -> list[list[int]]:
    """BFS from fraction starts preferring chess tiles (captures knight branches)."""
    from cursed_words_solver.rules.stamp_behaviors import stamp_search_flags
    from cursed_words_solver.suggestion import path_tiles_need_dictionary_resolve

    if _chess_tile_count(board) < 3:
        return []
    flags = stamp_search_flags(loadout)
    graph_ctx = build_board_graph_context(board)
    fraction_starts = [
        i
        for i in _legal_word_start_indices(board)
        if is_fraction_tile(board.get_by_index(i))
    ]
    if not fraction_starts:
        return []
    out: list[list[int]] = []
    seen: set[tuple[int, ...]] = set()
    for start in fraction_starts:
        queue: list[tuple[list[int], int]] = [([start], 1 << start)]
        head = 0
        while head < len(queue):
            if len(seen) >= max_visited or len(out) >= max_paths:
                break
            path, visited_mask = queue[head]
            head += 1
            key = tuple(path)
            if key in seen:
                continue
            seen.add(key)
            if (
                len(path) >= 3
                and path_tiles_need_dictionary_resolve(board, path, flags=flags)
                and path_movement_ok(board, path, flags=flags)
            ):
                out.append(list(path))
                if len(out) >= max_paths:
                    break
            if len(path) >= max_depth:
                continue
            nbr_mask = neighbors_mask(
                board,
                visited_mask,
                cell_id=path[-1],
                flags=flags,
                graph_ctx=graph_ctx,
            )
            nbrs = list(
                _iter_expansion_neighbors(
                    board,
                    visited_mask,
                    cell_id=path[-1],
                    path=path,
                    path_length=len(path),
                    flags=flags,
                    graph_ctx=graph_ctx,
                    nbr_mask=nbr_mask,
                )
            )
            nbrs.sort(
                key=lambda idx: (
                    0 if board.get_by_index(idx).curse in CHESS_CURSES else 1,
                    -float(board.get_by_index(idx).base_score),
                    idx,
                )
            )
            for idx in nbrs[:10]:
                if visited_mask & (1 << idx):
                    continue
                tile = board.get_by_index(idx)
                if not tile_playable_for_path(tile):
                    continue
                if is_fraction_tile(tile) and not fraction_position_valid(
                    tile, len(path), relaxed=False
                ):
                    continue
                queue.append((path + [idx], visited_mask | (1 << idx)))
        if len(out) >= max_paths:
            break
    return out


def neighbors_standard_mask(
    board: Board,
    cell_id: int,
    visited_mask: int,
    *,
    flags: SearchFlagsMask = 0,
    active_mask: int | None = None,
    graph_ctx: BoardGraphContext | None = None,
) -> int:
    flags = coerce_search_flags(flags)
    if graph_ctx is not None:
        base = (
            graph_ctx.neighbors_8_wrap[cell_id]
            if flag_test(flags, FLAG_HORIZONTAL_WRAP)
            else graph_ctx.neighbors_8[cell_id]
        )
    else:
        from cursed_words_solver.graph_bitboard import adjacency_for_board

        adj = adjacency_for_board(
            board, horizontal_wrap=flag_test(flags, FLAG_HORIZONTAL_WRAP)
        )
        base = adj[cell_id]
    if active_mask is None:
        active_mask = sum(1 << i for i in _active_indices(board))
    return get_valid_extensions(base & active_mask, visited_mask)


def neighbors_standard(
    board: Board,
    path: list[int],
    visited: int | set[int],
    *,
    flags: SearchFlagsMask = 0,
) -> list[int]:
    visited_mask = (
        visited if isinstance(visited, int) else mask_from_indices(visited)
    )
    mask = neighbors_standard_mask(
        board, path[-1], visited_mask, flags=flags
    )
    return list(iter_mask(mask))


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


def _double_letter_teleport_mask(
    board: Board,
    cell_id: int,
    visited_mask: int,
    *,
    graph_ctx: BoardGraphContext | None = None,
) -> int:
    """Full Moon: jump to another unused tile with the same letter or identical chess piece."""
    last_tile = board.get_by_index(cell_id)
    letter = _physical_letter(last_tile)
    mask = 0
    if graph_ctx is not None:
        if letter:
            mask |= get_valid_extensions(
                graph_ctx.letter_masks.get(letter, 0),
                visited_mask,
            ) & ~(1 << cell_id)
        if is_chess_piece(last_tile) and chess_side_known(last_tile):
            key = (last_tile.curse.value, chess_side(last_tile))
            group = graph_ctx.identical_chess_masks.get(key, 0)
            mask |= get_valid_extensions(group, visited_mask) & ~(1 << cell_id)
        return mask
    for idx in _active_indices(board):
        if idx == cell_id or visited_mask & (1 << idx):
            continue
        other = board.get_by_index(idx)
        if letter and _physical_letter(other) == letter:
            mask |= 1 << idx
        elif identical_chess_piece(last_tile, other):
            mask |= 1 << idx
    return mask


def _double_letter_teleport_neighbors(
    board: Board,
    path: list[int],
    visited: int | set[int],
    flags: SearchFlagsMask,
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


def _coerce_visited_mask(visited: int | set[int]) -> int:
    if isinstance(visited, int):
        return visited
    return mask_from_indices(visited)


def neighbors_mask(
    board: Board,
    visited: int | set[int],
    *,
    cell_id: int | None = None,
    path: list[int] | None = None,
    flags: SearchFlagsMask = 0,
    graph_ctx: BoardGraphContext | None = None,
) -> int:
    """Curse-aware neighbor expansion as a bitmask."""
    flags = coerce_search_flags(flags)
    visited_mask = _coerce_visited_mask(visited)
    if cell_id is None:
        if path is None:
            raise ValueError("neighbors_mask requires cell_id or path")
        cell_id = path[-1]
    last_tile = board.get_by_index(cell_id)
    active_mask = graph_ctx.active_mask if graph_ctx else None
    item_mask = graph_ctx.item_mask if graph_ctx else 0

    if last_tile.curse == CurseType.ARROW:
        if graph_ctx is not None and graph_ctx.arrow_mask & (1 << cell_id):
            table = (
                graph_ctx.arrow_target_masks_wrap
                if flag_test(flags, FLAG_HORIZONTAL_WRAP)
                else graph_ctx.arrow_target_masks
            )
            return get_valid_extensions(table[cell_id], visited_mask)
        from cursed_words_solver.arrow_tiles import (
            arrow_direction_delta,
            arrow_ray_target_mask,
        )

        delta = arrow_direction_delta(last_tile)
        if delta is None:
            return 0
        if active_mask is None:
            active_mask = sum(1 << i for i in _active_indices(board))
        ray = arrow_ray_target_mask(
            cell_id,
            delta,
            active_mask,
            horizontal_wrap=flag_test(flags, FLAG_HORIZONTAL_WRAP),
        )
        return get_valid_extensions(ray, visited_mask)

    if last_tile.color == TileColor.WHITE:
        if active_mask is None:
            active_mask = sum(1 << i for i in _active_indices(board))
        return get_valid_extensions(active_mask, visited_mask)

    if is_chess_piece(last_tile):
        mask = chess_neighbors_mask(
            board,
            cell_id,
            visited_mask,
            flags,
            item_mask=item_mask,
            active_mask=active_mask or 0,
            graph_ctx=graph_ctx,
        )
    else:
        mask = neighbors_standard_mask(
            board,
            cell_id,
            visited_mask,
            flags=flags,
            active_mask=active_mask,
            graph_ctx=graph_ctx,
        )

    if flag_test(flags, FLAG_DOUBLE_LETTER_TELEPORT):
        mask |= _double_letter_teleport_mask(
            board, cell_id, visited_mask, graph_ctx=graph_ctx
        )
    if _quest_movement_loadout is not None:
        from cursed_words_solver.rules.quest_movement import neighbors_mask_for_quest

        return neighbors_mask_for_quest(
            board,
            visited_mask,
            cell_id=cell_id,
            flags=flags,
            graph_ctx=graph_ctx,
            loadout=_quest_movement_loadout,
            standard_mask=mask,
        )
    return mask


def neighbors_from_tile(
    board: Board,
    path: list[int],
    visited: int | set[int],
    *,
    flags: SearchFlagsMask = 0,
    graph_ctx: BoardGraphContext | None = None,
) -> list[int]:
    """Curse-aware neighbor expansion."""
    cell_id = path[-1]
    mask = neighbors_mask(
        board,
        visited,
        cell_id=cell_id,
        flags=flags,
        graph_ctx=graph_ctx,
    )
    return list(
        _iter_expansion_neighbors(
            board,
            visited,
            cell_id=cell_id,
            path=path,
            path_length=len(path),
            flags=flags,
            graph_ctx=graph_ctx,
            nbr_mask=mask,
        )
    )


def _insertion_sort_indices(
    scratch: list[int],
    n: int,
    sort_key: Callable[[int], tuple],
) -> None:
    for i in range(1, n):
        j = i
        while j > 0 and sort_key(scratch[j]) < sort_key(scratch[j - 1]):
            scratch[j], scratch[j - 1] = scratch[j - 1], scratch[j]
            j -= 1


def _teleport_letter_neighbor_tier(
    board: Board,
    neighbor_idx: int,
    visited_mask: int,
    *,
    flags: SearchFlagsMask = 0,
    graph_ctx: BoardGraphContext | None = None,
) -> int:
    """0 when neighbor letter can Full Moon teleport to another tile; else 1."""
    flags = coerce_search_flags(flags)
    if not flag_test(flags, FLAG_DOUBLE_LETTER_TELEPORT):
        return 1
    letter = _physical_letter(board.get_by_index(neighbor_idx))
    if not letter:
        return 1
    block = visited_mask | (1 << neighbor_idx)
    if graph_ctx is not None:
        group = graph_ctx.letter_masks.get(letter, 0)
        if get_valid_extensions(group, block) & ~(1 << neighbor_idx):
            return 0
        return 1
    for j in _active_indices(board):
        if j == neighbor_idx or block & (1 << j):
            continue
        if _physical_letter(board.get_by_index(j)) == letter:
            return 0
    return 1


def _iter_expansion_neighbors(
    board: Board,
    visited: int | set[int],
    *,
    cell_id: int | None = None,
    path: list[int] | None = None,
    path_length: int | None = None,
    flags: SearchFlagsMask = 0,
    hints: MultNeighborHints | None = None,
    graph_ctx: BoardGraphContext | None = None,
    nbr_mask: int | None = None,
) -> Iterator[int]:
    """Yield neighbor indices for DFS expansion; reuses scratch buffer instead of list(iter_mask)."""
    if cell_id is None:
        if path is None:
            raise ValueError("_iter_expansion_neighbors requires cell_id or path")
        cell_id = path[-1]
    plen = path_length if path_length is not None else (len(path) if path else 0)
    if nbr_mask is None:
        nbr_mask = neighbors_mask(
            board,
            visited,
            cell_id=cell_id,
            flags=flags,
            graph_ctx=graph_ctx,
        )
    if not nbr_mask:
        return

    visited_mask = _coerce_visited_mask(visited)
    n = collect_mask_indices(nbr_mask, _NEIGHBOR_SCRATCH)
    if n <= 1:
        ordered = _NEIGHBOR_SCRATCH[:n]
        for idx in ordered:
            yield idx
        return

    if graph_ctx is not None:
        last_frac = graph_ctx.is_fraction[cell_id]
        last_number = graph_ctx.curse_code[cell_id] == CURSE_CODE_NUMBER
        tile_bases = graph_ctx.tile_base
        nbr_fraction = graph_ctx.is_fraction
        nbr_number_like = graph_ctx.number_like
    else:
        last_tile = board.get_by_index(cell_id)
        last_frac = is_fraction_tile(last_tile)
        last_number = last_tile.curse == CurseType.NUMBER

        def _nbr_base(idx: int) -> float:
            return float(board.get_by_index(idx).base_score)

        def _nbr_frac(idx: int) -> bool:
            return is_fraction_tile(board.get_by_index(idx))

        def _nbr_numlike(idx: int) -> bool:
            return is_number_like_tile(board.get_by_index(idx))

        nbr_fraction = _nbr_frac
        nbr_number_like = _nbr_numlike
        tile_bases = _nbr_base

    if hints is not None and path is not None:
        letter_pos = plen

        def sort_key(idx: int) -> tuple[int, int, float, int]:
            base = (
                tile_bases[idx]
                if graph_ctx is not None
                else tile_bases(idx)
            )
            mult_pri = neighbor_mult_priority(
                board, path, idx, hints, letter_pos=letter_pos
            )
            if last_frac:
                if (
                    graph_ctx is not None
                    and graph_ctx.curse_code[idx] == CURSE_CODE_NUMBER
                ) or (
                    graph_ctx is None
                    and board.get_by_index(idx).curse == CurseType.NUMBER
                ):
                    return (mult_pri, 0, -base, idx)
                return (mult_pri, 2, -base, idx)
            if last_number:
                n_frac = (
                    nbr_fraction[idx] if graph_ctx is not None else nbr_fraction(idx)
                )
                n_num = (
                    nbr_number_like[idx]
                    if graph_ctx is not None
                    else nbr_number_like(idx)
                )
                if n_frac:
                    return (mult_pri, 0, -base, idx)
                if n_num:
                    return (mult_pri, 1, -base, idx)
            tele = _teleport_letter_neighbor_tier(
                board,
                idx,
                visited_mask,
                flags=flags,
                graph_ctx=graph_ctx,
            )
            return (mult_pri, tele, 3, -base, idx)
    else:

        def sort_key(idx: int) -> tuple[int, float, int]:
            base = (
                tile_bases[idx]
                if graph_ctx is not None
                else tile_bases(idx)
            )
            if last_frac:
                if (
                    graph_ctx is not None
                    and graph_ctx.curse_code[idx] == CURSE_CODE_NUMBER
                ) or (
                    graph_ctx is None
                    and board.get_by_index(idx).curse == CurseType.NUMBER
                ):
                    return (0, -base, idx)
                return (2, -base, idx)
            if last_number:
                n_frac = (
                    nbr_fraction[idx] if graph_ctx is not None else nbr_fraction(idx)
                )
                n_num = (
                    nbr_number_like[idx]
                    if graph_ctx is not None
                    else nbr_number_like(idx)
                )
                if n_frac:
                    return (0, -base, idx)
                if n_num:
                    return (1, -base, idx)
            tele = _teleport_letter_neighbor_tier(
                board,
                idx,
                visited_mask,
                flags=flags,
                graph_ctx=graph_ctx,
            )
            return (tele, 3, -base, idx)

    _insertion_sort_indices(_NEIGHBOR_SCRATCH, n, sort_key)
    ordered = _NEIGHBOR_SCRATCH[:n]
    for idx in ordered:
        yield idx


def _neighbors_sorted_by_base_score(
    board: Board,
    path: list[int],
    visited: int | set[int],
    *,
    flags: SearchFlagsMask = 0,
    graph_ctx: BoardGraphContext | None = None,
    nbr_mask: int | None = None,
) -> list[int]:
    return list(
        _iter_expansion_neighbors(
            board,
            visited,
            cell_id=path[-1],
            path=path,
            path_length=len(path),
            flags=flags,
            graph_ctx=graph_ctx,
            nbr_mask=nbr_mask,
        )
    )


def _neighbors_sorted_for_loadout(
    board: Board,
    path: list[int],
    visited: int | set[int],
    *,
    flags: SearchFlagsMask = 0,
    hints: MultNeighborHints | None = None,
    graph_ctx: BoardGraphContext | None = None,
    nbr_mask: int | None = None,
) -> list[int]:
    cell_id = path[-1]
    if nbr_mask is None:
        nbr_mask = neighbors_mask(
            board,
            visited,
            cell_id=cell_id,
            flags=flags,
            graph_ctx=graph_ctx,
        )
    if not hints or not nbr_mask:
        return _neighbors_sorted_by_base_score(
            board,
            path,
            visited,
            flags=flags,
            graph_ctx=graph_ctx,
            nbr_mask=nbr_mask,
        )
    return list(
        _iter_expansion_neighbors(
            board,
            visited,
            cell_id=cell_id,
            path=path,
            path_length=len(path),
            flags=flags,
            hints=hints,
            graph_ctx=graph_ctx,
            nbr_mask=nbr_mask,
        )
    )


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


def _consumable_endpoint_indices(board: Board) -> list[int]:
    """Board cells that count as consumable path endpoints (placed rack or native)."""
    out: list[int] = []
    for i in _active_indices(board):
        tile = board.get_by_index(i)
        if is_consumable_tile(tile) or is_placed_consumable_tile(tile):
            out.append(i)
    return out


def _max_number_face_on_board(board: Board) -> int:
    """Highest number_value among active NUMBER tiles (Bison scatters up to 17)."""
    best = 0
    for i in _active_indices(board):
        tile = board.get_by_index(i)
        if tile.curse != CurseType.NUMBER:
            continue
        nv = tile_number_value(tile)
        if nv > best:
            best = nv
    return best


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
            values = tile_fraction_position_values(tile)
            if values:
                return min(values)
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


def _up_and_up_center_adjacent_starts(board: Board, center_idx: int) -> list[int]:
    """Start tiles for Up and Up: center plus active 8-neighbors."""
    if not board.is_active_index(center_idx):
        return []
    out = [center_idx]
    for nbr in iter_mask(NEIGHBORS_8[center_idx]):
        if board.is_active_index(nbr):
            out.append(nbr)
    return sorted(set(out))


def _up_and_up_cap_sequence(
    min_len: int,
    max_len: int,
    *,
    prefer_long_first: bool,
    board: Board | None = None,
    center_idx: int | None = None,
) -> list[int]:
    """DFS length caps for Up and Up center passes."""
    if max_len <= min_len:
        return [max_len]
    center_nv: int | None = None
    if board is not None and center_idx is not None:
        center_tile = board.get_by_index(center_idx)
        if is_number_like_tile(center_tile):
            center_nv = tile_number_value(center_tile)
    if prefer_long_first:
        # Wildcard-heavy paths are usually 7–12 tiles, but honor center number face
        # (e.g. Bison 13) without starting at max_len=25.
        base_top = max(12, center_nv or 0)
        top = min(max_len, base_top)
        window = min(12, top - min_len + 1)
        bottom = max(min_len, top - window + 1)
        caps = list(range(top, bottom - 1, -1))
        if center_nv is not None and min_len <= center_nv <= max_len:
            caps = [center_nv] + [c for c in caps if c != center_nv]
        return caps
    return list(range(min_len, max_len + 1))


def _enumerate_paths_including_index(
    board: Board,
    start: int,
    must_include: int,
    max_len: int,
    min_len: int,
    *,
    flags: SearchFlagsMask = 0,
    graph_ctx: BoardGraphContext | None = None,
) -> Iterator[list[int]]:
    """Yield acyclic paths from start with length in [min_len, max_len] that visit must_include."""
    path = [start]
    visited_mask = 1 << start

    def rec() -> Iterator[list[int]]:
        if must_include in path and min_len <= len(path) <= max_len:
            yield list(path)
        if len(path) >= max_len:
            return
        for nbr in neighbors_from_tile(
            board, path, visited_mask, flags=flags, graph_ctx=graph_ctx
        ):
            if must_include not in path:
                remaining_after = max_len - len(path) - 1
                if nbr != must_include:
                    need = _min_steps_to_index(
                        board,
                        nbr,
                        must_include,
                        visited_mask | (1 << nbr),
                        flags=flags,
                        graph_ctx=graph_ctx,
                    )
                    if need is None or need > remaining_after:
                        continue
            path.append(nbr)
            yield from rec()
            path.pop()

    yield from rec()


def _candidate_heap_includes_index(candidates: _CandidateHeap, idx: int) -> bool:
    for _sc, _word, path in candidates.best_sorted():
        if idx in path:
            return True
    return False


def _shortest_path_between_indices(
    board: Board,
    start: int,
    end: int,
    max_len: int,
    *,
    flags: SearchFlagsMask = 0,
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


def _min_steps_to_index(
    board: Board,
    start: int,
    end: int,
    visited_mask: int,
    *,
    flags: SearchFlagsMask = 0,
    graph_ctx: BoardGraphContext | None = None,
) -> int | None:
    """Shortest acyclic steps from start to end without revisiting visited_mask cells."""
    if start == end:
        return 0
    from collections import deque

    queue: deque[tuple[int, int]] = deque([(start, 0)])
    seen: set[int] = {start}
    while queue:
        cell, dist = queue.popleft()
        mask = neighbors_mask(
            board,
            visited_mask | (1 << cell),
            cell_id=cell,
            flags=flags,
            graph_ctx=graph_ctx,
        )
        for nbr in iter_mask(mask):
            if nbr in seen or visited_mask & (1 << nbr):
                continue
            if nbr == end:
                return dist + 1
            seen.add(nbr)
            queue.append((nbr, dist + 1))
    return None


def _high_value_path_between_indices(
    board: Board,
    start: int,
    end: int,
    max_len: int,
    *,
    flags: SearchFlagsMask = 0,
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
    flags: SearchFlagsMask = 0,
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
        cell_id = path[-1]
        nbr_mask = neighbors_mask(
            board, visited, cell_id=cell_id, flags=flags
        )
        for nbr in _iter_expansion_neighbors(
            board,
            visited,
            cell_id=cell_id,
            path=path,
            path_length=len(path),
            flags=flags,
            nbr_mask=nbr_mask,
        ):
            path.append(nbr)
            dfs(path, visited | (1 << nbr))
            path.pop()

    dfs([start], 1 << start)
    return found


def _paths_spelling_word(
    board: Board,
    target: str,
    max_len: int,
    *,
    flags: SearchFlagsMask = 0,
    path_cap: int = 24,
) -> list[list[int]]:
    """Acyclic paths whose resolved letters equal target (for improve-word seeding)."""
    target = target.lower()
    length = len(target)
    if length > max_len or length < 1:
        return []
    found: list[list[int]] = []

    for start in _legal_word_start_indices(board):
        if len(found) >= path_cap:
            break
        if (
            resolve_letter(board.get_by_index(start), 0, flags=flags).lower()
            != target[0]
        ):
            continue

        def dfs(path: list[int], visited: int, pos: int) -> None:
            if len(found) >= path_cap:
                return
            if pos == length:
                found.append(list(path))
                return
            if len(path) >= max_len:
                return
            cell_id = path[-1]
            nbr_mask = neighbors_mask(
                board, visited, cell_id=cell_id, flags=flags
            )
            for nbr in _iter_expansion_neighbors(
                board,
                visited,
                cell_id=cell_id,
                path=path,
                path_length=len(path),
                flags=flags,
                nbr_mask=nbr_mask,
            ):
                if (
                    resolve_letter(board.get_by_index(nbr), pos, flags=flags).lower()
                    != target[pos]
                ):
                    continue
                path.append(nbr)
                dfs(path, visited | (1 << nbr), pos + 1)
                path.pop()

        dfs([start], 1 << start, 1)
    return found


def _all_shortest_paths_between_indices(
    board: Board,
    start: int,
    end: int,
    max_len: int,
    *,
    flags: SearchFlagsMask = 0,
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
    flags: SearchFlagsMask = 0,
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
    flags: SearchFlagsMask = 0,
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


_WRAP_WC_MIN_LEN = 8
_WRAP_WC_MAX_PATHS = 8000


def _wrap_wildcard_chess_tile_ok(tile: Tile) -> bool:
    return _is_wildcard_tile(tile) or is_chess_piece(tile)


def _wrap_wildcard_chess_path_seeds(
    board: Board,
    *,
    max_len: int,
    flags: SearchFlagsMask,
    min_len: int = _WRAP_WC_MIN_LEN,
    max_paths: int = _WRAP_WC_MAX_PATHS,
) -> Iterator[list[int]]:
    """BFS from chess starts through wildcard/chess tiles (Hungry Snake long paths)."""
    if not flag_test(flags, FLAG_HORIZONTAL_WRAP):
        return
    from collections import deque

    starts = sorted(
        i
        for i in _active_indices(board)
        if is_chess_piece(board.get_by_index(i))
    )
    emitted = 0
    for start in starts:
        queue: deque[tuple[list[int], int]] = deque()
        queue.append(([start], 1 << start))
        while queue and emitted < max_paths:
            path, visited_mask = queue.popleft()
            if len(path) >= max_len:
                continue
            for nbr in neighbors_from_tile(
                board, path, visited_mask, flags=flags
            ):
                tile = board.get_by_index(nbr)
                if not _wrap_wildcard_chess_tile_ok(tile):
                    continue
                new_path = path + [nbr]
                new_vis = visited_mask | (1 << nbr)
                if len(new_path) >= min_len:
                    yield new_path
                    emitted += 1
                    if emitted >= max_paths:
                        return
                queue.append((new_path, new_vis))


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


def _chess_cap_start_indices(chess_starts: list[int]) -> list[int]:
    """Start tiles for short (cap<=8) chess DFS passes.

    Slice to three starts on chess-heavy boards to preserve budget, but keep
    every chess start when there are only a few (voteless regression: path
    begins on the fourth pawn).
    """
    if len(chess_starts) <= 4:
        return chess_starts
    return chess_starts[:3]


_SMALL_BOARD_HAMILTONIAN_MAX = 9


def _is_shrunk_board(board: Board) -> bool:
    storage = max(board.storage_rows, board.storage_cols)
    return board.rows < storage or board.cols < storage


def _scattered_item_cap_sequence(
    min_len: int,
    max_len: int,
    *,
    active_count: int | None = None,
) -> list[int]:
    """Cap progression when 2+ scattered grid items need short paths explored."""
    if (
        active_count is not None
        and active_count <= _SMALL_BOARD_HAMILTONIAN_MAX
        and max_len >= active_count
    ):
        caps: list[int] = []
        if active_count >= min_len:
            caps.append(active_count)
        if max_len > active_count:
            caps.append(max_len)
        if caps:
            return caps
    mid = min(8, max_len)
    caps = list(range(min_len, mid + 1))
    if max_len > mid:
        caps.append(max_len)
    return caps


def _chess_serial_cap_sequence(min_len: int, max_len: int) -> list[int]:
    """Serial chess-heavy passes: boss min_len, then short capture-chain cap."""
    first_cap = 8 if max_len >= 8 else max_len
    caps: list[int] = []
    if min_len < first_cap:
        caps.append(min_len)
    if first_cap not in caps:
        caps.append(first_cap)
    return caps


def _dfs_starts_for_cap(
    cap: int,
    min_len: int,
    letter_starts: list[int],
    chess_starts: list[int],
) -> list[int]:
    """DFS start tiles for a cap pass (boss min_len uses letter starts)."""
    if cap == min_len:
        return letter_starts
    if cap <= 8 and chess_starts:
        return _chess_cap_start_indices(chess_starts)
    return letter_starts


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
            faces = [tile.number_value]
        elif is_fraction_tile(tile):
            faces = tile_fraction_position_values(tile) or [99]
        else:
            faces = [99]
        for face in faces:
            buckets.setdefault(face, []).append(i)
    face_keys = sorted(buckets)
    out: list[int] = []
    emitted: set[int] = set()
    while any(buckets[f] for f in face_keys):
        round_seen: set[int] = set()
        for face in face_keys:
            while buckets[face]:
                idx = buckets[face].pop(0)
                if idx in round_seen:
                    continue
                round_seen.add(idx)
                if idx not in emitted:
                    emitted.add(idx)
                    out.append(idx)
                break
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
        time_budget: float = DEFAULT_SEARCH_TIME_BUDGET_SEC,
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
        use_tier2_screen: bool | None = None,
        use_tier2_two_phase: bool | None = None,
        use_dfs_bb: bool | None = None,
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
        self._use_tier2_screen_override = use_tier2_screen
        self._use_tier2_two_phase_override = use_tier2_two_phase
        self._use_dfs_bb_override = use_dfs_bb
        self._score_cache: dict[tuple[tuple[int, ...], str], tuple[float, float, float]] = {}
        self._grid_refs_cache: dict[tuple[int, ...], tuple] = {}
        self._provisional_candidates: dict[tuple[tuple[int, ...], str], float] = {}
        self._dict_path_cache: dict[tuple[int, ...], str] = {}
        self._dict_valid_words_cache: dict[tuple[int, ...], str] = {}
        self._number_extend_cache: dict[tuple[frozenset[int], int], bool] = {}
        self._prune_heap: _CandidateHeap | None = None
        self._parallel_executor: ProcessPoolExecutor | None = None
        self._active_deadline: float | None = None
        self.last_search_timing: SearchTiming | None = None
        self._active_timing: SearchTiming | None = None
        self._solve_ctx: SolveContext | None = None
        self._graph_ctx: BoardGraphContext | None = None
        self._board_scoring_ctx = None
        self._placement_screen_pass = False
        self._tier2_adaptive_mode: str | None = None
        self._solve_start_mono: float | None = None

    def _elapsed_wall_sec(self) -> float:
        if self._solve_start_mono is None:
            return 0.0
        return time.monotonic() - self._solve_start_mono

    def _update_tier2_adaptive_mode(self) -> None:
        """After a short sample window, tune tier-2 screening depth from score share."""
        if self._tier2_adaptive_mode is not None:
            return
        elapsed = self._elapsed_wall_sec()
        if elapsed < TIER2_ADAPTIVE_SAMPLE_SEC:
            return
        timing = self._active_timing
        if timing is None:
            return
        if timing.dfs_expansions < 100 and timing.score_calls < 5:
            return
        score_pct = 100.0 * timing.score_sec / elapsed if elapsed > 0 else 0.0
        if score_pct < 40.0:
            self._tier2_adaptive_mode = "light"
        elif score_pct >= 55.0:
            self._tier2_adaptive_mode = "deep"
        else:
            self._tier2_adaptive_mode = "normal"

    def _tier2_screen_active(self) -> bool:
        mode = self._tier2_adaptive_mode
        if mode == "light":
            return False
        return True

    def _tier2_two_phase_active(self, loadout: Loadout) -> bool:
        if not self._use_tier2_two_phase_for(loadout):
            return False
        mode = self._tier2_adaptive_mode
        if mode == "light":
            return False
        return True

    def _tier2_defer_cap(self, heap: _CandidateHeap | None) -> int:
        mode = self._tier2_adaptive_mode
        if mode == "light":
            return 0
        k = heap._k if heap is not None else DEFAULT_CANDIDATE_HEAP_SIZE
        if mode == "deep":
            return max(TIER2_DEFER_CAP_DEEP, k * 4)
        return max(TIER2_DEFER_CAP_NORMAL, k * 2)

    def _tier2_refine_cap(self, candidates: _CandidateHeap) -> int:
        mode = self._tier2_adaptive_mode
        k = candidates._k
        if mode == "deep":
            return max(k * 4, 1)
        if mode == "light":
            return max(k, 1)
        return max(k * 2, 1)

    def _board_graph(self, board: Board) -> BoardGraphContext:
        if self._graph_ctx is not None and self._graph_ctx.board is board:
            return self._graph_ctx
        return build_board_graph_context(board)

    def _search_ctx(self, loadout: Loadout) -> SolveContext:
        if self._solve_ctx is not None:
            return self._solve_ctx
        return build_solve_context(loadout, self.scoring.rules)

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

    def _use_tier2_screen_for(self, loadout: Loadout) -> bool:
        if self._use_tier2_screen_override is not None:
            return self._use_tier2_screen_override
        if not self._tier2_screen_active():
            return False
        ctx = self._search_ctx(loadout)
        return loadout_allows_tier2_screen(
            ctx,
            loadout,
            setup_weight=self.setup_weight,
            score_fn=self.score_fn,
        )

    def _use_tier2_two_phase_for(self, loadout: Loadout) -> bool:
        if self._use_tier2_two_phase_override is not None:
            return self._use_tier2_two_phase_override
        if not self._use_tier2_screen_for(loadout):
            return False
        ctx = self._search_ctx(loadout)
        return loadout_allows_tier2_two_phase(
            ctx,
            loadout,
            setup_weight=self.setup_weight,
            score_fn=self.score_fn,
        )

    def _use_dfs_bb_for(
        self,
        loadout: Loadout,
        *,
        has_number_tiles: bool,
        has_chess_pieces: bool,
    ) -> bool:
        if self._use_dfs_bb_override is not None:
            return self._use_dfs_bb_override
        ctx = self._search_ctx(loadout)
        return loadout_allows_dfs_bb(
            ctx,
            loadout,
            has_number_tiles=has_number_tiles,
            has_chess_pieces=has_chess_pieces,
            setup_weight=self.setup_weight,
            score_fn=self.score_fn,
        )

    def _pipeline_cache_kwargs(self) -> dict:
        return {
            "graph_ctx": self._graph_ctx,
            "board_scoring_ctx": self._board_scoring_ctx,
            "grid_refs_cache": self._grid_refs_cache,
            "grid_refs_timing": self._active_timing,
        }

    def _score_total_for_path(
        self,
        board: Board,
        path: list[int],
        word: str,
        loadout: Loadout,
        ctx: SolveContext,
    ) -> float:
        cache_kw = self._pipeline_cache_kwargs()
        if ctx.capybara_shuffles:
            from cursed_words_solver.rules.capybara_scoring import score_capybara_ev

            return score_capybara_ev(
                self.scoring,
                board,
                path,
                word,
                loadout,
                self.scoring.rules,
                solve_context=ctx,
                grid_refs_cache=cache_kw.get("grid_refs_cache"),
                grid_refs_timing=cache_kw.get("grid_refs_timing"),
            )
        return self.scoring.score_total_only(
            board,
            path,
            word,
            loadout,
            solve_context=ctx,
            **cache_kw,
        )

    def _refine_provisional_heap(
        self,
        board: Board,
        loadout: Loadout,
        candidates: _CandidateHeap,
        *,
        deadline: float | None = None,
        pending: dict[tuple[tuple[int, ...], str], float] | None = None,
        refined_keys: set[tuple[tuple[int, ...], str]] | None = None,
        path_prefixes: list[tuple[int, ...]] | None = None,
        refine_cap_override: int | None = None,
    ) -> None:
        """Phase 2: run full pipeline for heap entries admitted on tier-1 bounds only."""
        source = (
            pending
            if pending is not None
            else self._provisional_candidates
        )
        if not source:
            return
        if deadline is None:
            deadline = self._active_deadline
        ctx = self._search_ctx(loadout)
        timing = self._active_timing
        pending_sorted = sorted(
            source.items(),
            key=lambda item: -item[1],
        )
        if pending is None:
            self._provisional_candidates.clear()
        refine_cap = refine_cap_override or self._tier2_refine_cap(candidates)
        refined_this_pass = 0
        for (path_tuple, word), _rank_ub in pending_sorted:
            if path_prefixes is not None and not _path_shares_leader_prefix(
                path_tuple, path_prefixes
            ):
                continue
            if deadline is not None and time.monotonic() >= deadline:
                break
            if refined_this_pass >= refine_cap:
                break
            path = list(path_tuple)
            key = (path_tuple, word)
            self._score_cache.pop(key, None)
            t0 = time.perf_counter()
            immediate = self._score_total_for_path(
                board,
                path,
                word,
                loadout,
                ctx,
            )
            if timing is not None:
                timing.score_sec += time.perf_counter() - t0
                timing.tier2_phase2_calls += 1
                timing.score_calls += 1
            setup_bonus = 0.0
            if self.setup_weight > 0:
                _setup_rank, setup_bonus = rank_score_for_word(
                    board,
                    path,
                    word,
                    loadout,
                    immediate,
                    setup_weight=self.setup_weight,
                    setup_discount=self.setup_discount,
                    rules=self.scoring.rules,
                )
            mult_factor = 1.0
            if self.mult_search_weight > 0 and self._mult_rules:
                mult_factor = optimistic_mult_factor(
                    loadout,
                    board,
                    path,
                    word,
                    self.scoring.rules,
                    self._mult_rules,
                )
            rank = search_rank_score(
                immediate,
                mult_factor,
                mult_weight=self.mult_search_weight,
                setup_bonus=setup_bonus,
            )
            if ctx.hanafuda_level > 0 and hanafuda_hand_satisfied(
                board, path, ctx.hanafuda_level
            ):
                rank += 800.0
            self._score_cache[key] = (immediate, setup_bonus, rank)
            candidates.replace_entry(
                word, path_tuple, score=rank, immediate=immediate
            )
            refined_this_pass += 1
            if refined_keys is not None:
                refined_keys.add((path_tuple, word))

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
                use_tier2_screen=self._use_tier2_screen_for(loadout),
                use_dfs_bb=self._use_dfs_bb_for(
                    loadout,
                    has_number_tiles=getattr(self, "_board_has_number_tiles", False),
                    has_chess_pieces=(
                        self._graph_ctx.has_chess_pieces
                        if self._graph_ctx is not None
                        else False
                    ),
                ),
                required_consumable_indices=self.validator.required_consumable_indices,
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

    def _linguistic_cache_key(self, board: Board, path: list[int]) -> tuple[int, ...]:
        """Scoring-only dict resolve key; path tuple is unique per traversal."""
        return tuple(path)

    def _path_needs_dictionary_resolve(
        self, board: Board, path: list[int], search_word: str
    ) -> bool:
        from cursed_words_solver.suggestion import path_needs_dictionary_resolve

        return path_needs_dictionary_resolve(board, path, search_word)

    def _accept_path_for_search(
        self,
        board: Board,
        path: list[int],
        search_word: str,
        loadout: Loadout,
        stamp_flags: SearchFlagsMask,
        *,
        trie_compatible: bool = False,
        prefix_cursor: TrieCursor | None = None,
        pattern_cursor: TrieCursor | None = None,
        use_hanafuda_physical: bool = False,
    ) -> tuple[bool, str]:
        """Whether a path is playable and which word form to score/rank."""
        if len(search_word) < self.min_len:
            return False, search_word

        def scoring_word_for_path_local(sw: str) -> str:
            if use_hanafuda_physical:
                return physical_word_for_path(board, path, flags=stamp_flags)
            return sw

        if (
            trie_compatible
            and prefix_cursor is not None
            and self.dictionary.cursor_is_word(prefix_cursor)
            and self.validator._path_constraints_ok(
                board, path, search_word, stamp_flags
            )
        ):
            timing = self._active_timing
            if timing is not None:
                timing.trie_fast_accepts += 1
            accepted = self._accepted_scoring_word(
                board,
                path,
                search_word,
                loadout,
                stamp_flags,
                use_hanafuda_physical=use_hanafuda_physical,
            )
            return True, accepted
        if self.validator.word_ok(board, path, search_word, stamp_flags):
            accepted = self._accepted_scoring_word(
                board,
                path,
                search_word,
                loadout,
                stamp_flags,
                use_hanafuda_physical=use_hanafuda_physical,
            )
            return True, accepted
        if use_hanafuda_physical:
            phys = physical_word_for_path(board, path, flags=stamp_flags)
            if phys != search_word and self.validator.word_ok(
                board, path, phys, stamp_flags
            ):
                return True, phys
        if loadout is not None and (
            any(is_number_like_tile(board.get_by_index(i)) for i in path)
            or self._path_needs_dictionary_resolve(board, path, search_word)
        ):
            if (
                trie_compatible
                and prefix_cursor is not None
                and self.dictionary.cursor_is_word(prefix_cursor)
                and self.validator._path_constraints_ok(
                    board, path, search_word, stamp_flags
                )
            ):
                timing = self._active_timing
                if timing is not None:
                    timing.trie_fast_accepts += 1
                accepted = self._accepted_scoring_word(
                    board,
                    path,
                    search_word,
                    loadout,
                    stamp_flags,
                    use_hanafuda_physical=use_hanafuda_physical,
                )
                return True, accepted
        if self._path_needs_dictionary_resolve(board, path, search_word):
            if not self.validator._path_constraints_ok(
                board, path, search_word, stamp_flags
            ):
                return False, search_word
            resolved = self._dictionary_scoring_word(
                board, path, search_word, loadout, stamp_flags
            )
            if resolved:
                return True, scoring_word_for_path_local(resolved)
        return False, search_word

    def _dictionary_scoring_word(
        self,
        board: Board,
        path: list[int],
        search_word: str,
        loadout: Loadout | None,
        stamp_flags: SearchFlagsMask,
    ) -> str | None:
        """Resolved dictionary spelling for this path, or None when unresolved."""
        if loadout is None:
            return None
        from cursed_words_solver.suggestion import (
            dictionary_word_for_path,
            path_requires_tile_dictionary_resolve,
        )

        if not path_requires_tile_dictionary_resolve(
            board, path, flags=stamp_flags
        ):
            return None

        path_key = tuple(path)
        cached_valid = self._dict_valid_words_cache.get(path_key)
        if cached_valid is None:
            cached_valid = (
                dictionary_word_for_path(
                    board,
                    path,
                    search_word,
                    loadout,
                    self.dictionary,
                    min_len=self.min_len,
                    pipeline=self.scoring,
                )
                or ""
            )
            self._dict_valid_words_cache[path_key] = cached_valid
        return cached_valid if cached_valid else None

    def _accepted_scoring_word(
        self,
        board: Board,
        path: list[int],
        search_word: str,
        loadout: Loadout | None,
        stamp_flags: SearchFlagsMask,
        *,
        use_hanafuda_physical: bool = False,
    ) -> str:
        if use_hanafuda_physical:
            return physical_word_for_path(board, path, flags=stamp_flags)
        resolved = self._dictionary_scoring_word(
            board, path, search_word, loadout, stamp_flags
        )
        return resolved if resolved else search_word

    def _collect_words(
        self,
        board: Board,
        loadout: Loadout,
        candidates: _CandidateHeap,
        deadline: float,
        max_len: int,
        digits_only: bool = False,
        start_indices: list[int] | None = None,
        must_include_index: int | None = None,
    ) -> None:
        use_prune = self._use_mult_prune_for(loadout)
        has_number_tiles = any(
            is_number_like_tile(board.get_by_index(i)) for i in _active_indices(board)
        )
        use_tier2 = self._use_tier2_screen_for(loadout)
        use_heap = use_prune or use_tier2
        prev_heap = self._prune_heap
        prev_deadline = self._active_deadline
        self._prune_heap = candidates if use_heap else None
        mult_hints = self._mult_hints
        self._active_deadline = deadline
        check_interval = self._time_check_interval(loadout)
        ctx = self._search_ctx(loadout)
        stamp_flags = ctx.search_flags
        graph_ctx = self._board_graph(board)
        from cursed_words_solver.suggestion import path_tiles_need_dictionary_resolve
        hanafuda_level = ctx.hanafuda_level
        use_hanafuda_physical = hanafuda_level > 0
        use_dfs_bb = self._use_dfs_bb_for(
            loadout,
            has_number_tiles=has_number_tiles,
            has_chess_pieces=graph_ctx.has_chess_pieces,
        )
        search_tile_base = (
            build_search_tile_base(board, ctx, graph_ctx) if use_dfs_bb else ()
        )

        def path_accepted(
            path: list[int],
            search_word: str,
            *,
            trie_compatible: bool,
            prefix_cursor: TrieCursor | None,
            pattern_cursor: TrieCursor | None = None,
        ) -> tuple[bool, str]:
            path_flags = path_scattered_search_flags_mask(
                board, path, stamp_flags, self.scoring.rules
            )
            return self._accept_path_for_search(
                board,
                path,
                search_word,
                loadout,
                path_flags,
                trie_compatible=trie_compatible,
                prefix_cursor=prefix_cursor,
                pattern_cursor=pattern_cursor,
                use_hanafuda_physical=use_hanafuda_physical,
            )

        def score_path(
            path: list[int],
            word: str,
            *,
            resolved_word: str | None = None,
        ) -> float | None:
            return self._rank_score_for_candidate(
                board,
                path,
                word,
                loadout,
                prune_heap=candidates if use_heap else None,
                resolved_word=resolved_word,
            )

        expansions = 0
        timed_out = False
        timing = self._active_timing
        stitch_active = flag_test(stamp_flags, FLAG_WORD_STITCH)
        _num_extend_cache = (
            self._number_extend_cache
            if getattr(self, "_board_has_number_tiles", False)
            else None
        )
        bb_mult_cache: dict[tuple[int, ...], float] = {}

        def _step_token_cursor(
            cursor: TrieCursor | None, token: str
        ) -> TrieCursor | None:
            node = cursor
            for c in token:
                if timing is not None:
                    timing.trie_steps += 1
                node = self.dictionary.step_cursor(node, c)
                if node is None:
                    return None
            return node

        def _update_stitch_state(
            prefix_cursor: TrieCursor | None,
            suffix_cursors: list[TrieCursor | None],
            is_word_end_at_depth: list[bool],
            token: str,
        ) -> tuple[
            TrieCursor | None,
            list[TrieCursor | None],
            list[bool],
        ]:
            node = prefix_cursor
            for c in token:
                if timing is not None:
                    timing.trie_steps += 1
                node = self.dictionary.step_cursor(node, c)
                next_suffix: list[TrieCursor | None] = []
                for prev in suffix_cursors:
                    if timing is not None:
                        timing.trie_steps += 1
                    next_suffix.append(self.dictionary.step_cursor(prev, c))
                if timing is not None:
                    timing.trie_steps += 1
                next_suffix.append(
                    self.dictionary.step_cursor(self.dictionary.root_cursor(), c)
                )
                suffix_cursors = next_suffix
                is_word_end_at_depth.append(self.dictionary.cursor_is_word(node))
            return node, suffix_cursors, is_word_end_at_depth

        def _stitch_prefix_ok(
            prefix_len: int,
            is_word_end_at_depth: list[bool],
            suffix_cursors: list[TrieCursor | None],
        ) -> bool:
            for k in range(self.min_len, prefix_len):
                if k >= len(is_word_end_at_depth):
                    break
                if is_word_end_at_depth[k] and k < len(suffix_cursors):
                    if suffix_cursors[k] is not None:
                        return True
            return False

        def _record_trie_prune() -> None:
            if timing is not None:
                timing.trie_prunes += 1

        def _pattern_after_token(
            pattern_prefix: str | None, token: str, *, active: bool
        ) -> str | None:
            if not active and pattern_prefix is None:
                return None
            out = pattern_prefix or ""
            for ch in token.lower():
                if ch.isdigit():
                    out += "?"
                elif ch.isalpha():
                    out += ch
            return out

        def _prefix_can_continue(
            letter_trie: bool,
            prefix_cursor: TrieCursor | None,
            pattern_prefix: str | None,
            pattern_cursor: TrieCursor | None,
            has_digit_path: bool,
            *,
            path: list[int],
            steps_left: int,
        ) -> bool:
            if letter_trie and prefix_cursor is not None:
                return True
            if has_digit_path and pattern_cursor is not None:
                return True
            if has_digit_path and pattern_prefix is not None:
                return self.dictionary.pattern_has_prefix(pattern_prefix)
            if (
                steps_left > 0
                and path_tiles_need_dictionary_resolve(
                    board, path, flags=path_scattered_search_flags_mask(
                        board, path, stamp_flags, self.scoring.rules
                    )
                )
            ):
                return True
            return False

        def _path_flags_for(path: list[int]) -> SearchFlagsMask:
            return path_scattered_search_flags_mask(
                board, path, stamp_flags, self.scoring.rules
            )

        def _step_pattern_cursor(
            cursor: TrieCursor | None, token: str, *, active: bool
        ) -> TrieCursor | None:
            if not active:
                return cursor
            mixed = self.dictionary.mixed_step_cursor(cursor, token)
            if timing is not None:
                timing.trie_steps += len(token)
            return mixed

        def dfs(
            path: list[int],
            chars: list[str],
            visited_mask: int,
            *,
            prefix_cursor: TrieCursor | None,
            has_wildcard: bool,
            has_digit: bool,
            prefix_len: int,
            prefix_base: float = 0.0,
            prefix_red_count: int = 0,
            pattern_prefix: str | None = None,
            pattern_cursor: TrieCursor | None = None,
            suffix_cursors: list[TrieCursor | None] | None = None,
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
            if expansions % check_interval == 0:
                self._update_tier2_adaptive_mode()

            letter_trie = not has_digit
            is_alpha_path = not has_wildcard and not has_digit
            trie_fast_end = (
                letter_trie
                and is_alpha_path
                and prefix_cursor is not None
                and prefix_len >= self.min_len
                and self.dictionary.cursor_is_word(prefix_cursor)
            )
            if len(chars) >= self.min_len and (
                trie_fast_end or has_wildcard or has_digit or stitch_active
            ):
                word = "".join(chars).lower()
                trie_compatible = (
                    prefix_cursor is not None and not has_digit and is_alpha_path
                )
                ok, score_word = path_accepted(
                    path,
                    word,
                    trie_compatible=trie_compatible,
                    prefix_cursor=prefix_cursor if letter_trie else None,
                    pattern_cursor=pattern_cursor,
                )
                if ok:
                    if not digits_only or any(ch.isdigit() for ch in score_word):
                        trie_confirmed = (
                            trie_compatible
                            and prefix_cursor is not None
                            and self.dictionary.cursor_is_word(prefix_cursor)
                        )
                        resolved_word = (
                            score_word
                            if trie_confirmed
                            and score_word.isalpha()
                            and "?" not in score_word
                            else None
                        )
                        self._consider_path_candidate(
                            board,
                            loadout,
                            candidates,
                            path,
                            score_word,
                            _path_flags_for(path),
                            score_path,
                            resolved_word=resolved_word,
                        )

            if len(path) >= max_len or timed_out:
                return

            steps_left = max_len - len(path)
            if not _prefix_can_continue(
                letter_trie,
                prefix_cursor,
                pattern_prefix,
                pattern_cursor,
                has_digit,
                path=path,
                steps_left=steps_left,
            ):
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
                            _record_trie_prune()
                            return
                else:
                    if not (
                        steps_left > 0
                        and self.validator._may_extend_to_number_word(
                            board, path, steps_left, _num_extend_cache
                        )
                    ):
                        _record_trie_prune()
                        return

            if (
                use_dfs_bb
                and use_heap
                and not stitch_active
                and not has_wildcard
                and not has_digit
            ):
                min_imm = candidates.min_immediate_score()
                min_rank = candidates.min_rank_score()
                best_imm = candidates.max_immediate_score()
                no_reachable_wild = not (
                    graph_ctx.wildcard_mask & graph_ctx.active_mask & ~visited_mask
                )
                if (
                    min_imm is not None
                    or min_rank is not None
                    or (no_reachable_wild and best_imm is not None)
                ):
                    if timing is not None:
                        timing.dfs_bb_calls += 1
                    imm_ub = prefix_immediate_upper_bound(
                        prefix_base,
                        board,
                        path,
                        chars,
                        visited_mask,
                        steps_left,
                        loadout,
                        ctx,
                        self._mult_rules,
                        graph_ctx,
                        search_tile_base,
                        max_len=max_len,
                        prefix_red_count=prefix_red_count,
                    )
                    if self.mult_search_weight > 0 and self._mult_rules:
                        path_key = tuple(path)
                        if path_key not in bb_mult_cache:
                            bb_mult_cache[path_key] = optimistic_mult_factor(
                                loadout,
                                board,
                                path,
                                "".join(chars),
                                self.scoring.rules,
                                self._mult_rules,
                            )
                    rank_ub = prefix_rank_upper_bound(
                        prefix_base,
                        board,
                        path,
                        chars,
                        visited_mask,
                        steps_left,
                        loadout,
                        ctx,
                        self._mult_rules,
                        graph_ctx,
                        search_tile_base,
                        mult_weight=self.mult_search_weight,
                        max_len=max_len,
                        prefix_red_count=prefix_red_count,
                        hanafuda_level=hanafuda_level,
                        setup_weight=self.setup_weight,
                        setup_discount=self.setup_discount,
                        rules=self.scoring.rules,
                    )
                    pruned = False
                    if no_reachable_wild and best_imm is not None and imm_ub <= best_imm:
                        if not bullseye_active(loadout):
                            pruned = True
                    elif min_imm is not None and imm_ub < min_imm:
                        if not bullseye_active(loadout):
                            pruned = True
                    elif min_rank is not None and not quest_skips_rank_ub_prune(loadout):
                        if prune_cannot_beat_heap(rank_ub, min_rank, loadout):
                            pruned = True
                    if pruned:
                        if timing is not None:
                            timing.dfs_bb_prunes += 1
                        return

            cell_id = path[-1]
            path_flags = _path_flags_for(path)
            nbr_mask = neighbors_mask(
                board,
                visited_mask,
                cell_id=cell_id,
                flags=path_flags,
                graph_ctx=graph_ctx,
            )
            for idx in _iter_expansion_neighbors(
                board,
                visited_mask,
                cell_id=cell_id,
                path=path,
                path_length=len(path),
                flags=path_flags,
                hints=mult_hints,
                graph_ctx=graph_ctx,
                nbr_mask=nbr_mask,
            ):
                if timed_out or self._time_expired():
                    timed_out = True
                    break
                tile = board.get_by_index(idx)
                if not tile_playable_for_path(tile):
                    continue
                if is_fraction_tile(tile) and not fraction_position_valid(
                    tile, len(path), relaxed=False
                ):
                    continue
                if must_include_index is not None and must_include_index not in path:
                    remaining_after = max_len - len(path) - 1
                    if remaining_after < 0:
                        continue
                    if idx != must_include_index:
                        need = _min_steps_to_index(
                            board,
                            idx,
                            must_include_index,
                            visited_mask | (1 << idx),
                            flags=path_flags,
                            graph_ctx=graph_ctx,
                        )
                        if need is None or need > remaining_after:
                            continue
                token = resolve_letter(tile, prefix_len, flags=path_flags)
                next_has_digit = has_digit or any(c.isdigit() for c in token)
                letter_options = resolve_letter_options(tile, prefix_len, flags=path_flags)
                multi_letter = (
                    len(letter_options) > 1
                    and all(len(o) == 1 and o.isalpha() for o in letter_options)
                )
                branch_letters = (
                    tuple(letter_options)
                    if multi_letter
                    else _wildcard_branch_letters(tile, prefix_len, flags=path_flags)
                    if "?" in token and not next_has_digit
                    else ()
                )

                if branch_letters:
                    extensions: list[
                        tuple[
                            str,
                            TrieCursor | None,
                            TrieCursor | None,
                            bool,
                            str | None,
                        ]
                    ] = []
                    pat_active = (
                        has_wildcard
                        or has_digit
                        or pattern_prefix is not None
                        or pattern_cursor is not None
                    )
                    for ch in branch_letters:
                        child = _step_token_cursor(prefix_cursor, ch)
                        next_pat = _pattern_after_token(
                            pattern_prefix, ch, active=has_wildcard or has_digit
                        )
                        next_pat_cursor = _step_pattern_cursor(
                            pattern_cursor, ch, active=pat_active or True
                        )
                        extensions.append(
                            (ch, child, next_pat_cursor, False, next_pat)
                        )
                else:
                    next_has_wildcard = has_wildcard or ("?" in token)
                    pattern_active = (
                        has_digit
                        or next_has_digit
                        or next_has_wildcard
                        or pattern_prefix is not None
                        or pattern_cursor is not None
                    )
                    next_pat = _pattern_after_token(
                        pattern_prefix, token, active=pattern_active
                    )
                    next_pat_cursor = _step_pattern_cursor(
                        pattern_cursor, token, active=pattern_active
                    )
                    if next_has_digit:
                        mixed = self.dictionary.mixed_step_cursor(
                            prefix_cursor if letter_trie else pattern_cursor, token
                        )
                        if timing is not None:
                            timing.trie_steps += len(token)
                        extensions = [
                            (token, mixed, next_pat_cursor, next_has_wildcard, next_pat)
                        ]
                    else:
                        child = _step_token_cursor(prefix_cursor, token)
                        extensions = [
                            (
                                token,
                                child,
                                next_pat_cursor,
                                next_has_wildcard,
                                next_pat,
                            )
                        ]

                for (
                    ext_token,
                    ext_cursor,
                    ext_pat_cursor,
                    ext_wildcard,
                    next_pattern,
                ) in extensions:
                    next_prefix_len = prefix_len + len(ext_token)
                    if next_has_digit or (
                        next_pattern is not None and "?" in next_pattern
                    ):
                        if ext_pat_cursor is None and (
                            next_pattern is None
                            or not self.dictionary.pattern_has_prefix(next_pattern)
                        ):
                            if not (
                                is_fraction_tile(tile)
                                or tile.curse == CurseType.ITEM
                            ):
                                if timing is not None:
                                    timing.trie_prunes += 1
                                continue
                    next_prefix_cursor = (
                        None if next_has_digit and ext_cursor is None else ext_cursor
                    )
                    next_has_wildcard = ext_wildcard
                    if (
                        not next_has_digit
                        and next_prefix_cursor is None
                        and not next_has_wildcard
                        and path_tiles_need_dictionary_resolve(
                            board, path + [idx], flags=stamp_flags
                        )
                    ):
                        next_has_wildcard = True
                        next_prefix_cursor = None
                    next_suffix = suffix_cursors
                    next_is_word_end = is_word_end_at_depth
                    if stitch_active and not (ext_wildcard or next_has_digit):
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
                        next_prefix_cursor, next_suffix, next_is_word_end = (
                            _update_stitch_state(
                                prefix_cursor, base_suffix, base_is_word, ext_token
                            )
                        )
                    chars.append(ext_token)
                    path.append(idx)
                    next_prefix_base = prefix_base
                    next_prefix_red = prefix_red_count
                    if use_dfs_bb:
                        next_prefix_base += _prefix_tile_base(
                            graph_ctx, search_tile_base, idx
                        )
                        if graph_ctx.tile_color_code[idx] == RED_COLOR_CODE:
                            next_prefix_red += 1
                    dfs(
                        path,
                        chars,
                        visited_mask | (1 << idx),
                        prefix_cursor=next_prefix_cursor,
                        has_wildcard=next_has_wildcard,
                        has_digit=next_has_digit,
                        prefix_len=next_prefix_len,
                        prefix_base=next_prefix_base,
                        prefix_red_count=next_prefix_red,
                        pattern_prefix=next_pattern,
                        pattern_cursor=ext_pat_cursor,
                        suffix_cursors=next_suffix,
                        is_word_end_at_depth=next_is_word_end,
                    )
                    path.pop()
                    chars.pop()

        if start_indices is not None:
            starts = [s for s in start_indices if board.is_active_index(s)]
        else:
            starts = _legal_word_start_indices(board)
        for start in starts:
            if timed_out or time.monotonic() > deadline:
                break
            tile = board.get_by_index(start)
            if not tile_playable_for_path(tile):
                continue
            if is_fraction_tile(tile) and not fraction_position_valid(
                tile, 0, relaxed=False
            ):
                continue
            token = resolve_letter(tile, 0, flags=stamp_flags)
            has_wildcard = "?" in token
            has_digit = any(c.isdigit() for c in token)
            prefix_len = len(token)
            start_options = resolve_letter_options(tile, 0, flags=stamp_flags)
            multi_letter = (
                len(start_options) > 1
                and all(len(o) == 1 and o.isalpha() for o in start_options)
            )
            branch_letters = (
                tuple(start_options)
                if multi_letter
                else _wildcard_branch_letters(tile, 0, flags=stamp_flags)
                if "?" in token and not has_digit
                else ()
            )
            if branch_letters:
                for ch in branch_letters:
                    prefix_cursor = _step_token_cursor(
                        self.dictionary.root_cursor(), ch
                    )
                    pat_cursor = self.dictionary.mixed_step_cursor(None, ch)
                    if timing is not None:
                        timing.trie_steps += 1
                    dfs(
                        [start],
                        [ch],
                        1 << start,
                        prefix_cursor=prefix_cursor,
                        has_wildcard=False,
                        has_digit=False,
                        prefix_len=1,
                        prefix_base=(
                            _prefix_tile_base(graph_ctx, search_tile_base, start)
                            if use_dfs_bb
                            else 0.0
                        ),
                        prefix_red_count=(
                            1
                            if use_dfs_bb
                            and graph_ctx.tile_color_code[start] == RED_COLOR_CODE
                            else 0
                        ),
                        pattern_prefix=ch,
                        pattern_cursor=pat_cursor,
                    )
            else:
                pattern_start = (
                    self.dictionary.pattern_from_chars([token])
                    if (has_wildcard or has_digit)
                    else None
                )
                pattern_start_cursor = (
                    self.dictionary.mixed_step_cursor(None, token)
                    if (has_wildcard or has_digit)
                    else None
                )
                if pattern_start_cursor is not None and timing is not None:
                    timing.trie_steps += len(token)
                prefix_cursor = (
                    None
                    if (has_wildcard or has_digit)
                    else _step_token_cursor(
                        self.dictionary.root_cursor(), token
                    )
                )
                suffix_cursors: list[TrieCursor | None] | None = None
                is_word_end_at_depth: list[bool] | None = None
                if stitch_active and not (has_wildcard or has_digit):
                    suffix_cursors = []
                    is_word_end_at_depth = [False]
                    prefix_cursor, suffix_cursors, is_word_end_at_depth = (
                        _update_stitch_state(
                            self.dictionary.root_cursor(),
                            suffix_cursors,
                            is_word_end_at_depth,
                            token,
                        )
                    )
                dfs(
                    [start],
                    [token],
                    1 << start,
                    prefix_cursor=prefix_cursor,
                    has_wildcard=has_wildcard,
                    has_digit=has_digit,
                    prefix_len=prefix_len,
                    prefix_base=(
                        _prefix_tile_base(graph_ctx, search_tile_base, start)
                        if use_dfs_bb
                        else 0.0
                    ),
                    prefix_red_count=(
                        1
                        if use_dfs_bb
                        and graph_ctx.tile_color_code[start] == RED_COLOR_CODE
                        else 0
                    ),
                    pattern_prefix=pattern_start,
                    pattern_cursor=pattern_start_cursor,
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
        flags = self._search_ctx(loadout).search_flags
        for idx in _active_indices(board):
            tile = board.get_by_index(idx)
            if tile.curse != CurseType.NUMBER:
                continue
            nv = tile_number_value(tile)
            if nv is None:
                continue
            words_to_try = {str(nv)}
            if flag_test(flags, FLAG_MICROSCOPE_BASE_SCORE):
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
                    cached = self._score_cache.get((tuple(path), word))
                    candidates.consider(
                        sc,
                        word,
                        path,
                        immediate=cached[0] if cached is not None else None,
                    )

    def _seed_stamp_improve_words(
        self,
        board: Board,
        loadout: Loadout,
        candidates: "_CandidateHeap",
        improve_words: frozenset[str],
    ) -> None:
        """Seed paths spelling stamp improve words (colour/number/chess names)."""
        if not improve_words:
            return
        flags = self._search_ctx(loadout).search_flags
        cap = self.max_len
        for word in sorted(improve_words, key=len):
            if len(word) < self.min_len or len(word) > cap:
                continue
            for path in _paths_spelling_word(board, word, cap, flags=flags):
                if len(path) < self.min_len:
                    continue
                spelled = "".join(
                    resolve_letter(board.get_by_index(i), j, flags=flags)
                    for j, i in enumerate(path)
                ).lower()
                if spelled != word:
                    continue
                if not self.validator.word_ok(board, path, spelled, flags):
                    continue
                sc = self._rank_score_for_candidate(board, path, spelled, loadout)
                if sc is not None:
                    cached = self._score_cache.get((tuple(path), spelled))
                    candidates.consider(
                        sc,
                        spelled,
                        path,
                        immediate=cached[0] if cached is not None else None,
                    )

    def _collect_joker_cluster_candidates(
        self,
        board: Board,
        loadout: Loadout,
        candidates: _CandidateHeap,
        deadline: float,
        max_len: int,
    ) -> None:
        """Seed paths that connect two jokers (Hanafuda three-of-a-kind with L2+)."""
        ctx = self._search_ctx(loadout)
        if ctx.hanafuda_level < 1:
            return
        if time.monotonic() >= deadline:
            return
        stamp_flags = ctx.search_flags
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
                    cached = self._score_cache.get((tuple(path), phys))
                    candidates.consider(
                        sc,
                        phys,
                        path,
                        immediate=cached[0] if cached is not None else None,
                    )
        finally:
            self._active_deadline = prev_deadline

    def _fast_rank_score_for_seed(
        self,
        board: Board,
        path: list[int],
        word: str,
        loadout: Loadout,
    ) -> tuple[float, float] | None:
        """Full pipeline score for seed paths; skips tier-2 deferral (fast)."""
        ctx = self._search_ctx(loadout)
        key = (tuple(path), word)
        cached = self._score_cache.get(key)
        if cached is not None:
            return cached[2], cached[0]
        immediate = self._score_total_for_path(
            board, path, word, loadout, ctx
        )
        setup_bonus = 0.0
        if self.setup_weight > 0:
            _, setup_bonus = rank_score_for_word(
                board,
                path,
                word,
                loadout,
                immediate,
                setup_weight=self.setup_weight,
                setup_discount=self.setup_discount,
                rules=self.scoring.rules,
            )
        mult_factor = 1.0
        if self.mult_search_weight > 0 and self._mult_rules:
            mult_factor = optimistic_mult_factor(
                loadout,
                board,
                path,
                word,
                self.scoring.rules,
                self._mult_rules,
            )
        rank = search_rank_score(
            immediate,
            mult_factor,
            mult_weight=self.mult_search_weight,
            setup_bonus=setup_bonus,
        )
        self._score_cache[key] = (immediate, setup_bonus, rank)
        return rank, immediate

    def _collect_wrap_wildcard_chess_path_seeds(
        self,
        board: Board,
        loadout: Loadout,
        candidates: _CandidateHeap,
        deadline: float,
        max_len: int,
    ) -> None:
        """Seed long wildcard/chess paths reachable only via Hungry Snake wrap."""
        if time.monotonic() >= deadline:
            return
        ctx = self._search_ctx(loadout)
        stamp_flags = ctx.search_flags
        prev_deadline = self._active_deadline
        self._active_deadline = deadline
        try:
            paths = list(
                _wrap_wildcard_chess_path_seeds(
                    board, max_len=max_len, flags=stamp_flags
                )
            )
            paths.sort(key=len, reverse=True)
            for path in paths:
                if time.monotonic() >= deadline:
                    break
                if len(path) < self.min_len:
                    continue
                phys = physical_word_for_path(board, path, flags=stamp_flags)
                if not self.validator.word_ok(board, path, phys, stamp_flags):
                    continue
                scored = self._fast_rank_score_for_seed(
                    board, path, phys, loadout
                )
                if scored is not None:
                    sc, immediate = scored
                    candidates.consider(
                        sc,
                        phys,
                        path,
                        immediate=immediate,
                    )
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
        stamp_flags = self._search_ctx(loadout).search_flags
        prev_deadline = self._active_deadline
        self._active_deadline = deadline
        try:
            end_colors: set[str] = set()
            need_suit_endpoints = False
            need_consumable_endpoints = False
            need_length = False
            for mr in self._mult_rules:
                if mr.condition.startswith("ends_with_color:"):
                    end_colors.add(mr.condition.split(":", 1)[1].lower())
                if mr.condition == "word_starts_ends_different_suit":
                    need_suit_endpoints = True
                if mr.condition == "word_starts_ends_consumable":
                    need_consumable_endpoints = True
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
                                cached = self._score_cache.get((tuple(path), word))
                                candidates.consider(
                                    sc,
                                    word,
                                    path,
                                    immediate=cached[0] if cached is not None else None,
                                )

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
                                cached = self._score_cache.get((tuple(path), word))
                                candidates.consider(
                                    sc,
                                    word,
                                    path,
                                    immediate=cached[0] if cached is not None else None,
                                )

            if need_consumable_endpoints:
                consumable_ends = _consumable_endpoint_indices(board)
                for i, a in enumerate(consumable_ends[:8]):
                    if time.monotonic() >= deadline:
                        break
                    for b in consumable_ends[i + 1 : i + 9]:
                        if a == b:
                            continue
                        for path in _paths_between_indices(
                            board, a, b, cap, flags=stamp_flags
                        ):
                            if len(path) < self.min_len:
                                continue
                            if not word_starts_ends_consumable(board, path):
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
                                cached = self._score_cache.get((tuple(path), word))
                                candidates.consider(
                                    sc,
                                    word,
                                    path,
                                    immediate=cached[0] if cached is not None else None,
                                )
                        for path in _paths_between_indices(
                            board, b, a, cap, flags=stamp_flags
                        ):
                            if len(path) < self.min_len:
                                continue
                            if not word_starts_ends_consumable(board, path):
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
                                cached = self._score_cache.get((tuple(path), word))
                                candidates.consider(
                                    sc,
                                    word,
                                    path,
                                    immediate=cached[0] if cached is not None else None,
                                )

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

    def _dictionary_resolve_extension_seeds(
        self,
        board: Board,
        loadout: Loadout,
        candidates: _CandidateHeap,
        *,
        cap: int = 40,
    ) -> list[tuple[float, str, tuple[int, ...]]]:
        """Valid dictionary-resolve word paths that may extend to longer words."""
        if self.max_len <= self.min_len:
            return []
        from cursed_words_solver.suggestion import path_tiles_need_dictionary_resolve

        stamp_flags = self._search_ctx(loadout).search_flags
        seeds: list[tuple[float, str, tuple[int, ...]]] = []
        seen: set[tuple[int, ...]] = set()
        for rank_sc, word, path_tuple in candidates.best_sorted():
            path = list(path_tuple)
            key = tuple(path)
            if key in seen:
                continue
            plen = len(path)
            if plen < self.min_len or plen >= self.max_len:
                continue
            if not path_tiles_need_dictionary_resolve(
                board, path, flags=stamp_flags
            ):
                continue
            search_word = search_word_from_path(board, path, flags=stamp_flags)
            accepted, _ = self._accept_path_for_search(
                board,
                path,
                search_word,
                loadout,
                stamp_flags,
            )
            if not accepted:
                continue
            seen.add(key)
            seeds.append((rank_sc, word, key))
            if len(seeds) >= cap:
                break
        return seeds

    def _supplement_fraction_chess_word_boundaries(
        self,
        board: Board,
        loadout: Loadout,
        candidates: _CandidateHeap,
        *,
        deadline: float | None = None,
    ) -> None:
        """Probe fraction→chess branches and seed word-boundary paths into the heap."""
        if self.max_len <= self.min_len:
            return
        if deadline is not None and time.monotonic() >= deadline:
            return
        if not any(is_fraction_tile(t) for t in board.flat):
            return
        if _chess_tile_count(board) < 3:
            return
        stamp_flags = self._search_ctx(loadout).search_flags
        probe_depth = min(8, self.max_len)
        probe_paths = _probe_fraction_chess_prefixes(
            board, loadout, max_depth=probe_depth
        )
        probe_paths.sort(key=len, reverse=True)
        added = 0
        for path in probe_paths:
            if added >= 20:
                break
            if deadline is not None and time.monotonic() >= deadline:
                break
            if len(path) >= self.max_len:
                continue
            search_word = search_word_from_path(board, path, flags=stamp_flags)
            accepted, scoring_word = self._accept_path_for_search(
                board,
                path,
                search_word,
                loadout,
                stamp_flags,
            )
            if not accepted:
                continue
            rank_sc = self._rank_score_for_candidate(
                board, path, scoring_word, loadout
            )
            if rank_sc is not None:
                candidates.consider(rank_sc, scoring_word, path)
                added += 1

    def _extend_dictionary_resolve_boundaries(
        self,
        board: Board,
        loadout: Loadout,
        candidates: _CandidateHeap,
        *,
        deadline: float | None = None,
    ) -> None:
        """Extend wildcard/chess word boundaries in isolation, then merge into heap."""
        seeds = self._dictionary_resolve_extension_seeds(
            board, loadout, candidates
        )
        if not seeds:
            return
        if deadline is not None and time.monotonic() >= deadline:
            return
        long_seeds = [entry for entry in seeds if len(entry[2]) >= 4]
        if long_seeds:
            seeds = long_seeds
        use_per_seed = any(
            is_fraction_tile(t) for t in board.flat
        ) and _chess_tile_count(board) >= 3
        if use_per_seed:
            # Shortest resolve boundaries extend furthest; prefer them over
            # longer heap leaders that cannot reach buzzsaw-length paths.
            seeds = sorted(
                seeds,
                key=lambda entry: (len(entry[2]), -entry[0]),
            )
            probe_mandatory: list[tuple[float, str, tuple[int, ...]]] = []
            stamp_flags = self._search_ctx(loadout).search_flags
            probe_depth = min(8, self.max_len)
            for path in _probe_fraction_chess_prefixes(
                board, loadout, max_depth=probe_depth
            ):
                if len(path) < self.min_len or len(path) >= self.max_len:
                    continue
                key = tuple(path)
                if any(key == entry[2] for entry in seeds):
                    continue
                search_word = search_word_from_path(
                    board, path, flags=stamp_flags
                )
                accepted, scoring_word = self._accept_path_for_search(
                    board,
                    path,
                    search_word,
                    loadout,
                    stamp_flags,
                )
                if not accepted:
                    continue
                rank_sc = self._rank_score_for_candidate(
                    board, path, scoring_word, loadout
                )
                if rank_sc is not None:
                    probe_mandatory.append((rank_sc, scoring_word, key))
            probe_mandatory.sort(key=lambda entry: (len(entry[2]), -entry[0]))
            seen_seed: set[tuple[int, ...]] = set()
            merged: list[tuple[float, str, tuple[int, ...]]] = []
            for entry in probe_mandatory + seeds:
                if entry[2] in seen_seed:
                    continue
                seen_seed.add(entry[2])
                merged.append(entry)
            seeds = merged
        else:
            seeds = sorted(seeds, key=lambda entry: len(entry[2]), reverse=True)
        if use_per_seed:
            seed_cap = 12 if self.time_budget >= 30.0 else 8
            seeds = seeds[:seed_cap]
            per_seed_rounds = min(self.max_len - self.min_len, 16)
            boundaries_budget = min(
                10.0 if self.time_budget >= 30.0 else 6.0,
                self.time_budget * 0.18,
            )
            boundaries_end = time.monotonic() + boundaries_budget
            if deadline is not None and deadline > time.monotonic():
                boundaries_end = min(boundaries_end, deadline)
            for rank_sc, word, path_tuple in seeds:
                if time.monotonic() >= boundaries_end:
                    break
                if len(path_tuple) >= self.max_len:
                    continue
                mini = _CandidateHeap(200)
                mini.consider(rank_sc, word, list(path_tuple))
                resolve_seeds = self._dictionary_resolve_extension_seeds(
                    board, loadout, mini
                )
                self._extend_top_candidates(
                    board,
                    loadout,
                    mini,
                    top_paths=30,
                    max_rounds=min(
                        per_seed_rounds, self.max_len - len(path_tuple)
                    ),
                    extra_seeds=resolve_seeds or None,
                    deadline=boundaries_end,
                )
                for ext_sc, ext_word, ext_path in mini.best_sorted():
                    candidates.consider(ext_sc, ext_word, list(ext_path))
            return
        seeds = seeds[:20]
        top_paths = len(seeds)
        max_rounds = min(self.max_len - self.min_len, 8)
        if (
            self.search_workers > 1
            and len(seeds) >= 4
            and self._wordlist_path is not None
        ):
            from cursed_words_solver.search_parallel import (
                get_search_pool,
                parallel_extend_seeds,
            )

            pool = get_search_pool(Path(self._wordlist_path), self.search_workers)
            if pool is not None:
                extended = parallel_extend_seeds(
                    executor=pool,
                    workers=self.search_workers,
                    board=board,
                    loadout=loadout,
                    seeds=seeds,
                    deadline=deadline,
                    min_len=self.min_len,
                    max_len=self.max_len,
                    top_paths=top_paths,
                    max_rounds=max_rounds,
                    setup_weight=self.setup_weight,
                    setup_discount=self.setup_discount,
                    wordlist_path=Path(self._wordlist_path),
                )
                for rank_sc, word, path_tuple in extended:
                    candidates.consider(rank_sc, word, list(path_tuple))
                return
        mini = _CandidateHeap(max(len(seeds) + 50, 80))
        for rank_sc, word, path_tuple in seeds:
            mini.consider(rank_sc, word, list(path_tuple))
        self._extend_top_candidates(
            board,
            loadout,
            mini,
            top_paths=top_paths,
            max_rounds=max_rounds,
            deadline=deadline,
        )
        for rank_sc, word, path_tuple in mini.best_sorted():
            candidates.consider(rank_sc, word, list(path_tuple))

    def _guarantee_fraction_chess_probe_extensions(
        self,
        board: Board,
        loadout: Loadout,
        candidates: _CandidateHeap,
        *,
        deadline: float | None = None,
    ) -> None:
        """Extend shortest fraction→chess probe paths in isolation (bazz→buzzsaw)."""
        if self.max_len <= self.min_len:
            return
        if not any(is_fraction_tile(t) for t in board.flat):
            return
        if _chess_tile_count(board) < 3:
            return
        budget = min(
            15.0 if self.time_budget >= 30.0 else 7.0,
            self.time_budget * 0.25,
        )
        guarantee_end = time.monotonic() + budget
        prev_deadline = self._active_deadline
        self._active_deadline = guarantee_end
        try:
            stamp_flags = self._search_ctx(loadout).search_flags
            probe_depth = min(8, self.max_len)
            probe_paths = sorted(
                _probe_fraction_chess_prefixes(
                    board, loadout, max_depth=probe_depth
                ),
                key=len,
            )
            per_seed_rounds = min(self.max_len - self.min_len, 16)
            seeds: list[tuple[float, str, list[int]]] = []
            for path in probe_paths:
                if len(path) < 4 or len(path) >= self.max_len:
                    continue
                search_word = search_word_from_path(
                    board, path, flags=stamp_flags
                )
                accepted, scoring_word = self._accept_path_for_search(
                    board,
                    path,
                    search_word,
                    loadout,
                    stamp_flags,
                )
                if not accepted:
                    continue
                rank_sc = self._rank_score_for_candidate(
                    board, path, scoring_word, loadout
                )
                if rank_sc is None:
                    continue
                seeds.append((rank_sc, scoring_word, list(path)))
            if not seeds:
                return
            # Extend the shortest boundary with the full guarantee budget.
            rank_sc, scoring_word, path = min(
                seeds, key=lambda s: (len(s[2]), -s[0])
            )
            seed_end = guarantee_end
            self._active_deadline = seed_end
            mini = _CandidateHeap(200)
            mini.consider(rank_sc, scoring_word, path)
            resolve_seeds = self._dictionary_resolve_extension_seeds(
                board, loadout, mini
            )
            self._extend_top_candidates(
                board,
                loadout,
                mini,
                top_paths=30,
                max_rounds=per_seed_rounds,
                extra_seeds=resolve_seeds or None,
                deadline=seed_end,
            )
            for ext_sc, ext_word, ext_path in mini.best_sorted():
                candidates.consider(ext_sc, ext_word, list(ext_path))
        finally:
            self._active_deadline = prev_deadline

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
        stamp_flags = self._search_ctx(loadout).search_flags
        graph_ctx = self._board_graph(board)
        from cursed_words_solver.suggestion import path_tiles_need_dictionary_resolve

        use_prune = self._use_mult_prune_for(loadout)
        use_tier2 = self._use_tier2_screen_for(loadout)
        use_heap = use_prune or use_tier2

        def score_path(
            path: list[int],
            word: str,
            *,
            resolved_word: str | None = None,
        ) -> float | None:
            if self._time_expired():
                return None
            return self._rank_score_for_candidate(
                board,
                path,
                word,
                loadout,
                prune_heap=candidates if use_heap else None,
                resolved_word=resolved_word,
            )

        prev_deadline = self._active_deadline
        if deadline is not None:
            self._active_deadline = deadline
        timing = self._active_timing
        try:
            for _round in range(max_rounds):
                if deadline is not None and time.monotonic() >= deadline:
                    break
                extended = False
                seen_prefixes: set[tuple[int, ...]] = set()
                seed_entries = list(candidates.best_sorted()[:top_paths])
                if extra_seeds:
                    seed_entries.extend(extra_seeds)
                for _score, seed_word, path_tuple in seed_entries:
                    if deadline is not None and time.monotonic() >= deadline:
                        break
                    path = list(path_tuple)
                    if len(path) >= self.max_len:
                        continue
                    key = tuple(path)
                    if key in seen_prefixes:
                        continue
                    seen_prefixes.add(key)
                    if path_tiles_need_dictionary_resolve(
                        board, path, flags=stamp_flags
                    ):
                        seed_lower = search_word_from_path(
                            board, path, flags=stamp_flags
                        ).lower()
                        seed_has_wildcard = "?" in seed_lower or any(
                            c.isdigit() for c in seed_lower
                        )
                        seed_has_digit = any(c.isdigit() for c in seed_lower)
                        seed_cursor = None
                    else:
                        seed_lower = seed_word.lower()
                        seed_has_wildcard = "?" in seed_lower
                        seed_has_digit = any(c.isdigit() for c in seed_lower)
                        seed_cursor = (
                            None
                            if (seed_has_wildcard or seed_has_digit)
                            else self.dictionary.step_token_cursor(
                                self.dictionary.root_cursor(), seed_lower
                            )
                        )
                    visited_mask = sum(1 << idx for idx in path)
                    prefix_len = path_word_char_len(
                        board, path, flags=stamp_flags
                    )
                    nbr_mask = neighbors_mask(
                        board,
                        visited_mask,
                        cell_id=path[-1],
                        flags=stamp_flags,
                        graph_ctx=graph_ctx,
                    )
                    for idx in _neighbors_sorted_for_loadout(
                        board,
                        path,
                        visited_mask,
                        flags=stamp_flags,
                        graph_ctx=graph_ctx,
                        nbr_mask=nbr_mask,
                    ):
                        if deadline is not None and time.monotonic() >= deadline:
                            break
                        tile = board.get_by_index(idx)
                        if not tile_playable_for_path(tile):
                            continue
                        if is_fraction_tile(tile) and not fraction_position_valid(
                            tile, len(path), relaxed=False
                        ):
                            continue
                        path.append(idx)
                        token = resolve_letter(tile, prefix_len, flags=stamp_flags)
                        next_has_digit = seed_has_digit or any(
                            c.isdigit() for c in token
                        )
                        branch_letters = (
                            _wildcard_branch_letters(
                                tile, prefix_len, flags=stamp_flags
                            )
                            if "?" in token and not next_has_digit
                            else ()
                        )
                        extensions: list[tuple[str, TrieCursor | None, bool]] = []
                        if branch_letters:
                            for ch in branch_letters:
                                child = self.dictionary.step_cursor(seed_cursor, ch)
                                if timing is not None:
                                    timing.trie_steps += 1
                                extensions.append((ch, child, True))
                        elif next_has_digit:
                            extensions.append((token, None, seed_has_wildcard))
                        else:
                            child = self.dictionary.step_token_cursor(
                                seed_cursor, token
                            )
                            if timing is not None:
                                timing.trie_steps += len(token)
                            extensions.append(
                                (
                                    token,
                                    child,
                                    seed_has_wildcard or ("?" in token),
                                )
                            )

                        for ext_token, ext_cursor, ext_wildcard in extensions:
                            if (
                                not next_has_digit
                                and ext_cursor is None
                                and not ext_wildcard
                            ):
                                if timing is not None:
                                    timing.trie_prunes += 1
                                continue
                            word = search_word_from_path(
                                board, path, flags=stamp_flags
                            )
                            if len(word) < self.min_len:
                                continue
                            ext_resolved = (seed_lower + ext_token).lower()
                            trie_compatible = (
                                ext_cursor is not None
                                and not next_has_digit
                                and ext_resolved.isalpha()
                            )
                            accepted, scoring_word = self._accept_path_for_search(
                                board,
                                path,
                                word,
                                loadout,
                                stamp_flags,
                                trie_compatible=trie_compatible,
                                prefix_cursor=ext_cursor if not next_has_digit else None,
                            )
                            if not accepted:
                                continue
                            ext_trie_confirmed = (
                                trie_compatible
                                and ext_cursor is not None
                                and self.dictionary.cursor_is_word(ext_cursor)
                            )
                            resolved_word = (
                                scoring_word
                                if ext_trie_confirmed
                                and scoring_word.isalpha()
                                and "?" not in scoring_word
                                else None
                            )
                            if self._consider_path_candidate(
                                board,
                                loadout,
                                candidates,
                                path,
                                scoring_word,
                                stamp_flags,
                                score_path,
                                resolved_word=resolved_word,
                            ):
                                extended = True
                        path.pop()
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

    def _score_cache_key(
        self,
        path: list[int],
        word: str,
        *,
        resolved_word: str | None = None,
    ) -> tuple[tuple[int, ...], str]:
        canonical = (resolved_word or word).lower()
        return (tuple(path), canonical)

    def _consider_path_candidate(
        self,
        board: Board,
        loadout: Loadout,
        candidates: _CandidateHeap,
        path: list[int],
        score_word: str,
        stamp_flags: SearchFlagsMask,
        score_path: Callable[..., float | None],
        *,
        resolved_word: str | None = None,
    ) -> bool:
        """Push path to heap; also index item-aware search_word when it differs."""
        added = False
        cache_key = self._score_cache_key(
            path, score_word, resolved_word=resolved_word
        )
        sc = score_path(path, score_word, resolved_word=resolved_word)
        if sc is not None:
            cached = self._score_cache.get(cache_key)
            candidates.consider(
                sc,
                score_word,
                path,
                immediate=cached[0] if cached is not None else None,
            )
            added = True
        alt_sw = search_word_from_path(board, path, flags=stamp_flags)
        alt_norm = alt_sw.lower()
        word_norm = score_word.lower()
        canonical = (resolved_word or score_word).lower()
        if alt_norm != word_norm and alt_norm != canonical:
            alt_key = self._score_cache_key(
                path, alt_sw, resolved_word=resolved_word
            )
            if alt_key == cache_key:
                return added
            sc_alt = score_path(path, alt_sw, resolved_word=resolved_word)
            if sc_alt is not None:
                cached_alt = self._score_cache.get(alt_key)
                candidates.consider(
                    sc_alt,
                    alt_sw,
                    path,
                    immediate=cached_alt[0] if cached_alt is not None else None,
                )
                added = True
        return added

    def _resolved_word_for_path(
        self,
        board: Board,
        path: list[int],
        word: str,
        loadout: Loadout,
    ) -> str:
        """Dictionary spelling for a wildcard/chess path (cached); '' when unresolved."""
        cache_key = self._linguistic_cache_key(board, path)
        cached = self._dict_path_cache.get(cache_key)
        timing = self._active_timing
        if cached is not None:
            if timing is not None:
                timing.dict_path_cache_hits += 1
            return cached
        if timing is not None:
            timing.dict_path_cache_misses += 1
        from cursed_words_solver.suggestion import dictionary_word_for_path

        alt = dictionary_word_for_path(
            board,
            path,
            word,
            loadout,
            self.dictionary,
            min_len=self.min_len,
            pipeline=self.scoring,
        )
        resolved = alt or ""
        self._dict_path_cache[cache_key] = resolved
        return resolved

    def _rank_score_for_candidate(
        self,
        board: Board,
        path: list[int],
        word: str,
        loadout: Loadout,
        *,
        prune_heap: _CandidateHeap | None = None,
        resolved_word: str | None = None,
    ) -> float | None:
        self._update_tier2_adaptive_mode()
        if self._time_expired():
            return None
        timing = self._active_timing
        key = self._score_cache_key(path, word, resolved_word=resolved_word)
        cached = self._score_cache.get(key)
        if cached is not None:
            if timing is not None:
                timing.score_cache_hits += 1
            return quest_candidate_rank(cached[0], cached[2], loadout)
        if timing is not None:
            timing.score_cache_misses += 1
        heap = prune_heap
        ctx = self._search_ctx(loadout)
        hanafuda_level = ctx.hanafuda_level
        score_word = (
            physical_word_for_path(board, path, flags=ctx.search_flags)
            if hanafuda_level > 0
            else word
        )
        if hanafuda_level == 0:
            if resolved_word:
                score_word = resolved_word
            elif "?" in score_word or self._path_needs_dictionary_resolve(
                board, path, word
            ):
                resolved = self._resolved_word_for_path(board, path, word, loadout)
                if resolved:
                    score_word = resolved
        if heap is not None and not (
            hanafuda_level > 0
            and hanafuda_hand_satisfied(board, path, hanafuda_level)
        ):
            min_sc = heap.min_rank_score()
            if (
                min_sc is not None
                and self._use_mult_prune_for(loadout)
                and not path_has_scattered_grid_items(board, path)
            ):
                if getattr(self, "_board_has_number_tiles", False):
                    lb = number_aware_lower_bound(
                        board,
                        path,
                        loadout,
                        self.scoring.rules,
                        graph_ctx=self._graph_ctx,
                    )
                else:
                    lb = mult_aware_lower_bound(
                        board, path, loadout, self.scoring.rules
                    )
                if prune_cannot_beat_heap(lb, min_sc, loadout):
                    return None
        if heap is not None and self._use_tier2_screen_for(loadout):
            min_imm = heap.min_immediate_score()
            min_rank = heap.min_rank_score()
            if min_imm is not None or min_rank is not None:
                if timing is not None:
                    timing.tier2_screen_calls += 1
                t_tier2 = time.perf_counter()
                imm_ub = tier2_immediate_upper_bound(
                    board,
                    path,
                    score_word,
                    loadout,
                    ctx,
                    self._mult_rules,
                    graph_ctx=self._graph_ctx,
                    board_scoring_ctx=self._board_scoring_ctx,
                )
                rank_ub = (
                    tier2_rank_upper_bound(
                        board,
                        path,
                        score_word,
                        loadout,
                        ctx,
                        self._mult_rules,
                        mult_weight=self.mult_search_weight,
                        hanafuda_level=hanafuda_level,
                        graph_ctx=self._graph_ctx,
                        board_scoring_ctx=self._board_scoring_ctx,
                        setup_weight=self.setup_weight,
                        setup_discount=self.setup_discount,
                        rules=self.scoring.rules,
                    )
                    if min_rank is not None
                    else None
                )
                if timing is not None:
                    timing.tier2_screen_sec += time.perf_counter() - t_tier2
                if min_imm is not None and imm_ub < min_imm:
                    if timing is not None:
                        timing.tier2_screen_skips += 1
                    return None
                if rank_ub is not None and min_rank is not None:
                    prune_bound = (
                        tier2_rank_lower_bound(
                            board,
                            path,
                            score_word,
                            loadout,
                            ctx,
                            self._mult_rules,
                            mult_weight=self.mult_search_weight,
                            hanafuda_level=hanafuda_level,
                            graph_ctx=self._graph_ctx,
                            board_scoring_ctx=self._board_scoring_ctx,
                        )
                        if quest_inverts_search_rank(loadout)
                        else rank_ub
                    )
                    if prune_cannot_beat_heap(prune_bound, min_rank, loadout):
                        if timing is not None:
                            timing.tier2_rank_screen_skips += 1
                        return None
                if (
                    self._tier2_two_phase_active(loadout)
                    and min_rank is not None
                    and rank_ub is not None
                ):
                    rank_lb = tier2_rank_lower_bound(
                        board,
                        path,
                        score_word,
                        loadout,
                        ctx,
                        self._mult_rules,
                        mult_weight=self.mult_search_weight,
                        hanafuda_level=hanafuda_level,
                        graph_ctx=self._graph_ctx,
                        board_scoring_ctx=self._board_scoring_ctx,
                    )
                    if prune_cannot_beat_heap(rank_lb, min_rank, loadout):
                        defer_cap = self._tier2_defer_cap(heap)
                        if defer_cap <= 0 or len(self._provisional_candidates) >= defer_cap:
                            pass
                        else:
                            if timing is not None:
                                timing.tier2_phase1_calls += 1
                                timing.tier2_phase2_deferred += 1
                            prev_ub = self._provisional_candidates.get(key)
                            if prev_ub is None or rank_ub > prev_ub:
                                self._provisional_candidates[key] = rank_ub
                            return rank_ub
        setup_bonus = 0.0
        timing = self._active_timing
        if self.score_fn:
            immediate = self.score_fn(board, path, score_word, loadout)
            rank = immediate
        else:
            t0 = time.perf_counter()
            immediate = self._score_total_for_path(
                board, path, score_word, loadout, ctx
            )
            if timing is not None and self._tier2_two_phase_active(loadout):
                timing.tier2_phase2_calls += 1
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
        cache_key = self._score_cache_key(
            path, score_word, resolved_word=resolved_word
        )
        self._score_cache[cache_key] = (immediate, setup_bonus, rank)
        if cache_key != key:
            self._score_cache[key] = (immediate, setup_bonus, rank)
        return quest_candidate_rank(immediate, rank, loadout)

    def _immediate_and_setup(
        self, board: Board, path: list[int], word: str, loadout: Loadout
    ) -> tuple[float, float]:
        timing = self._active_timing
        key = self._score_cache_key(path, word)
        cached = self._score_cache.get(key)
        if cached is not None:
            if timing is not None:
                timing.score_cache_hits += 1
            return cached[0], cached[1]
        self._rank_score_for_candidate(board, path, word, loadout)
        cached = self._score_cache.get(key)
        if cached is not None:
            return cached[0], cached[1]
        ctx = self._search_ctx(loadout)
        immediate = self._score_total_for_path(board, path, word, loadout, ctx)
        return immediate, 0.0

    def _search_prefix_viable(
        self, search_word: str, cap: int, *, path_len: int | None = None
    ) -> bool:
        tiles = path_len if path_len is not None else len(search_word)
        if tiles >= cap:
            return True
        if "?" in search_word or any(ch.isdigit() for ch in search_word):
            return self.dictionary.pattern_has_prefix(search_word)
        return self.dictionary.has_prefix(search_word)

    def _seed_up_and_up_dictionary_paths(
        self,
        board: Board,
        loadout: Loadout,
        candidates: _CandidateHeap,
        deadline: float,
        center_idx: int,
        cap: int,
    ) -> None:
        """Dictionary-guided path geometry for Up and Up (wildcard-heavy boards)."""
        if time.monotonic() >= deadline:
            return
        ctx = self._search_ctx(loadout)
        stamp_flags = ctx.search_flags
        graph_ctx = self._board_graph(board)
        up_starts = _up_and_up_center_adjacent_starts(board, center_idx)
        fraction_starts = [
            s for s in up_starts if is_fraction_tile(board.get_by_index(s))
        ]
        search_starts = fraction_starts or up_starts

        def score_path(
            path: list[int],
            word: str,
            *,
            resolved_word: str | None = None,
        ) -> float | None:
            return self._rank_score_for_candidate(
                board,
                path,
                word,
                loadout,
                prune_heap=None,
                resolved_word=resolved_word,
            )

        def rec(path: list[int], visited_mask: int) -> bool:
            if time.monotonic() >= deadline:
                return True
            if center_idx in path and len(path) >= self.min_len:
                search_word = search_word_from_path(
                    board, path, flags=stamp_flags
                )
                accepted, score_word = self._accept_path_for_search(
                    board,
                    path,
                    search_word,
                    loadout,
                    stamp_flags,
                )
                if accepted:
                    self._consider_path_candidate(
                        board,
                        loadout,
                        candidates,
                        path,
                        score_word,
                        stamp_flags,
                        score_path,
                    )
                    return True
            if len(path) >= cap:
                return False
            for nbr in neighbors_from_tile(
                board,
                path,
                visited_mask,
                flags=stamp_flags,
                graph_ctx=graph_ctx,
            ):
                if center_idx not in path:
                    remaining_after = cap - len(path) - 1
                    if remaining_after < 0:
                        continue
                    if nbr != center_idx:
                        need = _min_steps_to_index(
                            board,
                            nbr,
                            center_idx,
                            visited_mask | (1 << nbr),
                            flags=stamp_flags,
                            graph_ctx=graph_ctx,
                        )
                        if need is None or need > remaining_after:
                            continue
                path.append(nbr)
                next_mask = visited_mask | (1 << nbr)
                search_word = search_word_from_path(
                    board, path, flags=stamp_flags
                )
                if center_idx in path and len(path) >= self.min_len:
                    accepted, score_word = self._accept_path_for_search(
                        board,
                        path,
                        search_word,
                        loadout,
                        stamp_flags,
                    )
                    if accepted:
                        self._consider_path_candidate(
                            board,
                            loadout,
                            candidates,
                            path,
                            score_word,
                            stamp_flags,
                            score_path,
                        )
                        path.pop()
                        return True
                if len(path) >= cap:
                    path.pop()
                    continue
                if self._search_prefix_viable(
                    search_word, cap, path_len=len(path)
                ):
                    if rec(path, next_mask):
                        path.pop()
                        return True
                path.pop()
            return False

        for start in search_starts:
            if time.monotonic() >= deadline:
                break
            if rec([start], 1 << start):
                break
            if _candidate_heap_includes_index(candidates, center_idx):
                break

    def _collect_up_and_up_center_words(
        self,
        board: Board,
        loadout: Loadout,
        candidates: _CandidateHeap,
        deadline: float,
        center_idx: int,
        max_len: int,
        *,
        has_fraction_tiles: bool = False,
        has_number_tiles: bool = False,
    ) -> None:
        """DFS from center-adjacent tiles with deepening caps (Up and Up quest)."""
        up_starts = _up_and_up_center_adjacent_starts(board, center_idx)
        if not up_starts or time.monotonic() >= deadline:
            return
        saved_pool = self._parallel_executor
        self._parallel_executor = None
        try:
            prefer_long = has_fraction_tiles or has_number_tiles
            if self.time_budget >= 6.0 and max_len > self.min_len:
                caps = _up_and_up_cap_sequence(
                    self.min_len,
                    max_len,
                    prefer_long_first=prefer_long,
                    board=board,
                    center_idx=center_idx,
                )
            else:
                caps = [max_len]
            fraction_starts = [
                s
                for s in up_starts
                if is_fraction_tile(board.get_by_index(s))
            ]
            center_nv: int | None = None
            center_tile = board.get_by_index(center_idx)
            if is_number_like_tile(center_tile):
                center_nv = tile_number_value(center_tile)
            if caps:
                seed_cap = caps[0]
                if center_nv is not None and self.min_len <= center_nv <= max_len:
                    seed_cap = max(seed_cap, center_nv)
                seed_deadline = deadline
                if center_nv is not None and center_nv >= 13:
                    seed_slice = min(18.0, self.time_budget * 0.35)
                    seed_deadline = min(
                        deadline, time.monotonic() + seed_slice
                    )
                self._seed_up_and_up_dictionary_paths(
                    board,
                    loadout,
                    candidates,
                    seed_deadline,
                    center_idx,
                    seed_cap,
                )
            if _candidate_heap_includes_index(candidates, center_idx):
                return
            for i, cap in enumerate(caps):
                if time.monotonic() >= deadline:
                    break
                remaining = max(0.0, deadline - time.monotonic())
                caps_left = len(caps) - i
                if i == 0 and fraction_starts:
                    cap_deadline = deadline
                else:
                    cap_deadline = min(
                        deadline,
                        time.monotonic() + max(0.5, remaining / caps_left),
                    )
                if i == 0 and fraction_starts:
                    per_start = max(
                        3.0, (cap_deadline - time.monotonic()) / len(fraction_starts)
                    )
                    for start in fraction_starts:
                        if time.monotonic() >= cap_deadline:
                            break
                        self._collect_words(
                            board,
                            loadout,
                            candidates,
                            min(cap_deadline, time.monotonic() + per_start),
                            cap,
                            start_indices=[start],
                            must_include_index=center_idx,
                        )
                else:
                    per_start = max(
                        1.5,
                        (cap_deadline - time.monotonic()) / max(1, len(up_starts)),
                    )
                    for start in up_starts:
                        if time.monotonic() >= cap_deadline:
                            break
                        self._collect_words(
                            board,
                            loadout,
                            candidates,
                            min(cap_deadline, time.monotonic() + per_start),
                            cap,
                            start_indices=[start],
                            must_include_index=center_idx,
                        )
                if _candidate_heap_includes_index(candidates, center_idx):
                    break
        finally:
            self._parallel_executor = saved_pool

    def _collect_hamiltonian_word_candidates(
        self,
        board: Board,
        loadout: Loadout,
        candidates: _CandidateHeap,
        deadline: float,
        *,
        target_len: int,
        score_all: bool,
    ) -> None:
        """Try dictionary words of target_len that span a valid path on the board."""
        if target_len < 1:
            return
        words = self.dictionary.words_by_length.get(target_len, ())
        if not words:
            return

        ctx = self._search_ctx(loadout)
        stamp_flags = ctx.search_flags
        graph_ctx = self._board_graph(board)

        def score_path(
            path: list[int],
            word: str,
            *,
            resolved_word: str | None = None,
        ) -> float | None:
            return self._rank_score_for_candidate(
                board,
                path,
                word,
                loadout,
                prune_heap=candidates,
                resolved_word=resolved_word,
            )

        def find_path_for_word(target: str) -> list[int] | None:
            target = target.lower()
            if len(target) != target_len:
                return None

            def dfs(path: list[int], visited_mask: int) -> list[int] | None:
                if self._time_expired():
                    return None
                if deadline != float("inf") and time.monotonic() >= deadline:
                    return None
                k = len(path)
                if k == target_len:
                    if self.validator.word_ok(board, path, target, stamp_flags):
                        return path
                    return None
                cell = path[-1]
                nbr_mask = neighbors_mask(
                    board,
                    visited_mask,
                    cell_id=cell,
                    flags=stamp_flags,
                    graph_ctx=graph_ctx,
                )
                next_ch = target[k]
                for nbr in _iter_expansion_neighbors(
                    board,
                    visited_mask,
                    cell_id=cell,
                    path=path,
                    path_length=k,
                    flags=stamp_flags,
                    nbr_mask=nbr_mask,
                ):
                    tile = board.get_by_index(nbr)
                    if not _tile_accepts_word_letter(
                        tile, k, next_ch, target, flags=stamp_flags
                    ):
                        continue
                    hit = dfs(path + [nbr], visited_mask | (1 << nbr))
                    if hit is not None:
                        return hit
                return None

            for start in _legal_word_start_indices(board):
                tile = board.get_by_index(start)
                if not _tile_accepts_word_letter(
                    tile, 0, target[0], target, flags=stamp_flags
                ):
                    continue
                hit = dfs([start], 1 << start)
                if hit is not None:
                    return hit
            return None

        for target in words:
            if deadline != float("inf") and time.monotonic() >= deadline:
                break
            path = find_path_for_word(target)
            if path is None:
                continue
            self._consider_path_candidate(
                board,
                loadout,
                candidates,
                path,
                target,
                stamp_flags,
                score_path,
                resolved_word=target,
            )
            if not score_all:
                break

    def _collect_small_board_hamiltonian_candidates(
        self,
        board: Board,
        loadout: Loadout,
        candidates: _CandidateHeap,
        deadline: float,
        *,
        target_len: int,
    ) -> None:
        """Enumerate full-grid visits on tiny boards; score via dictionary resolve."""
        active = _active_indices(board)
        n = len(active)
        if (
            n > _SMALL_BOARD_HAMILTONIAN_MAX
            or target_len != n
            or target_len < self.min_len
            or target_len > self.max_len
        ):
            return

        ctx = self._search_ctx(loadout)
        stamp_flags = ctx.search_flags
        graph_ctx = self._board_graph(board)
        required_mask = sum(1 << i for i in active)

        def score_path(
            path: list[int],
            word: str,
            *,
            resolved_word: str | None = None,
        ) -> float | None:
            return self._rank_score_for_candidate(
                board,
                path,
                word,
                loadout,
                prune_heap=candidates,
                resolved_word=resolved_word,
            )

        def dfs(path: list[int], visited_mask: int) -> None:
            if self._time_expired() or time.monotonic() >= deadline:
                return
            if len(path) == n:
                if visited_mask != required_mask:
                    return
                search_word = search_word_from_path(
                    board, path, flags=stamp_flags
                )
                accepted, score_word = self._accept_path_for_search(
                    board,
                    path,
                    search_word,
                    loadout,
                    stamp_flags,
                )
                if accepted:
                    self._consider_path_candidate(
                        board,
                        loadout,
                        candidates,
                        path,
                        score_word,
                        stamp_flags,
                        score_path,
                    )
                return
            cell = path[-1]
            nbr_mask = neighbors_mask(
                board,
                visited_mask,
                cell_id=cell,
                flags=stamp_flags,
                graph_ctx=graph_ctx,
            )
            for nbr in _iter_expansion_neighbors(
                board,
                visited_mask,
                cell_id=cell,
                path=path,
                path_length=len(path),
                flags=stamp_flags,
                nbr_mask=nbr_mask,
            ):
                path.append(nbr)
                dfs(path, visited_mask | (1 << nbr))
                path.pop()

        for start in active:
            if time.monotonic() >= deadline:
                break
            dfs([start], 1 << start)

    def _collect_full_board_hamiltonian_candidates(
        self,
        board: Board,
        loadout: Loadout,
        candidates: _CandidateHeap,
        deadline: float,
    ) -> None:
        """Full-board exact length: try each dictionary word of matching length."""
        active = _active_indices(board)
        n = len(active)
        if n < 1 or self.min_len != n or self.max_len != n:
            return
        self._collect_hamiltonian_word_candidates(
            board,
            loadout,
            candidates,
            deadline,
            target_len=n,
            score_all=False,
        )

    def find_best_words(
        self,
        board: Board,
        loadout: Loadout | None = None,
        top_n: int = 3,
        *,
        deadline: float | None = None,
        run_until_found: bool = False,
    ) -> list[WordResult]:
        if self.blocked:
            return []
        from cursed_words_solver.models import reset_board_flat_call_count

        self._run_until_found = run_until_found
        self._score_cache.clear()
        self._dict_path_cache.clear()
        self._dict_valid_words_cache.clear()
        self._number_extend_cache.clear()
        self._grid_refs_cache.clear()
        self._provisional_candidates.clear()
        self._tier2_adaptive_mode = None
        self._solve_start_mono = None
        reset_board_flat_call_count()
        loadout = loadout or Loadout(money=board.money)
        quest_target: float | None = None
        if bullseye_active(loadout):
            remaining = encounter_remaining_from_loadout(loadout)
            if remaining > 0:
                quest_target = float(remaining)
        set_quest_search_target(quest_target)
        board = effective_board_for_loadout(board, loadout, self.scoring.rules)
        _active = _active_indices(board)
        active_count = len(_active)
        self._full_board_exact = (
            self.min_len == self.max_len
            and self.min_len == active_count
            and self.min_len >= 20
        )
        self._small_board_hamiltonian = (
            _is_shrunk_board(board)
            and active_count <= _SMALL_BOARD_HAMILTONIAN_MAX
            and self.max_len >= active_count
            and active_count >= self.min_len
            and not self._full_board_exact
        )
        self.validator.quest_loadout = loadout
        self.validator.extra_valid_words = equipped_improve_words(loadout)
        set_quest_movement_loadout(loadout)
        self._solve_ctx = build_solve_context(loadout, self.scoring.rules)
        self._mult_rules = loadout_mult_rules(
            loadout,
            self.scoring.rules,
            board=board,
            path=[_active[0]] if _active else [],
            solve_context=self._solve_ctx,
        )
        self._mult_hints = (
            build_mult_neighbor_hints(self._mult_rules)
            if self._mult_rules
            else None
        )
        self._graph_ctx = build_board_graph_context(board)
        from cursed_words_solver.board_scoring_context import (
            build_board_scoring_context,
        )

        self._board_scoring_ctx = build_board_scoring_context(
            board,
            loadout,
            self._solve_ctx,
            self._graph_ctx,
            self.scoring.rules,
        )
        clear_chess_attack_cache(
            has_chess_pieces=self._graph_ctx.has_chess_pieces,
            board_fingerprint=(
                board_fingerprint(board) if self._graph_ctx.has_chess_pieces else None
            ),
        )
        mult_count = len(self._mult_rules)
        heap_k = self.candidate_heap_size or _candidate_heap_size(
            top_n, mult_count, self._graph_ctx
        )
        candidates = _CandidateHeap(heap_k)
        solve_start = time.monotonic()
        self._solve_start_mono = solve_start
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
        center_idx = self._solve_ctx.quest_ctx.require_center_index
        up_and_up_reserve = 0.0
        if center_idx is not None:
            center_tile = board.get_by_index(center_idx)
            if is_number_like_tile(center_tile):
                up_and_up_reserve = min(18.0, self.time_budget * 0.35)
            else:
                up_and_up_reserve = min(15.0, self.time_budget * 0.30)
            if has_fraction_tiles:
                up_and_up_reserve = max(
                    up_and_up_reserve, min(20.0, self.time_budget * 0.42)
                )
            if is_number_like_tile(center_tile):
                center_nv = tile_number_value(center_tile)
                if center_nv is not None and center_nv >= 13:
                    up_and_up_reserve = max(
                        up_and_up_reserve,
                        min(22.0, self.time_budget * 0.45),
                    )
        placement_screen = bool(getattr(self, "_placement_screen_pass", False))
        required_placement = bool(self.validator.required_consumable_indices)
        if self._full_board_exact:
            number_reserve = 0.0
            void_reserve = 0.0
            fraction_cluster_reserve = 0.0
        elif has_number_tiles:
            # Tight budgets need more time reserved for digit passes; otherwise
            # the cap progression (7 -> 8) can time out before reaching cap=8.
            if self.time_budget < 2.0 and (placement_screen or required_placement):
                number_reserve = min(0.5, self.time_budget * 0.25)
            else:
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
        if not self._full_board_exact and _chess_tile_count(board) >= 3:
            # DFS cap progression can consume the whole budget on chess-heavy
            # boards. Reserve some time so the chess prefix extension phase
            # still runs.
            chess_reserve = min(8.0, self.time_budget * 0.35)

        joker_count = len(_wildcard_start_indices(board))
        hanafuda_level = self._solve_ctx.hanafuda_level
        seed_reserve = 0.0
        if hanafuda_level >= 1 and joker_count >= 2:
            seed_reserve = min(5.0, self.time_budget * 0.12)

        extension_reserve = 0.0
        if self.max_len > self.min_len:
            extension_reserve = min(5.0, self.time_budget * 0.12)
            branch = (
                self._graph_ctx.wildcard_mask.bit_count()
                + self._graph_ctx.chess_piece_mask.bit_count()
                + self._graph_ctx.item_mask.bit_count()
            )
            if branch >= 5:
                extension_reserve = min(8.0, extension_reserve * 1.4)
            if branch <= 2:
                extension_reserve *= 0.85

        (
            number_reserve,
            void_reserve,
            fraction_cluster_reserve,
            chess_reserve,
            seed_reserve,
            extension_reserve,
            up_and_up_reserve,
            reserve_scaled,
        ) = _scale_post_dfs_reserves(
            time_budget=self.time_budget,
            number_reserve=number_reserve,
            void_reserve=void_reserve,
            fraction_cluster_reserve=fraction_cluster_reserve,
            chess_reserve=chess_reserve,
            seed_reserve=seed_reserve,
            extension_reserve=extension_reserve,
            up_and_up_reserve=up_and_up_reserve,
        )
        if center_idx is not None:
            up_and_up_reserve = max(
                up_and_up_reserve,
                min(10.0, self.time_budget * 0.28),
            )

        letter_starts = _balanced_start_indices(board)
        chess_starts = _chess_start_indices(board) if chess_reserve > 0.0 else []
        if chess_starts:
            # Prefer higher indices first for short chess-cap passes, so we don't
            # starve the specific chess start tiles needed for capture-chain
            # regressions under fair-start time slicing.
            chess_starts = sorted(chess_starts, key=lambda i: i, reverse=True)
        item_count = (
            self._graph_ctx.item_mask.bit_count()
            if self._graph_ctx is not None
            else 0
        )
        use_parallel = (
            self.search_workers > 1
            and self._wordlist_path is not None
            and (
                item_count < 2
                or self._full_board_exact
                or (
                    _is_shrunk_board(board)
                    and active_count <= _SMALL_BOARD_HAMILTONIAN_MAX
                )
            )
        )
        # Short budgets: one pass at max_len. Longer budgets: deepen so DFS does not
        # exhaust the first high-base-score branch to max_len before shorter words.
        # Parallel mode uses one pass at max_len to avoid repeated pool scheduling.
        item_heavy_caps = item_count >= 2 and self.max_len > self.min_len
        if item_heavy_caps:
            caps = _scattered_item_cap_sequence(
                self.min_len,
                self.max_len,
                active_count=active_count if _is_shrunk_board(board) else None,
            )
        elif use_parallel:
            # One pool round at max_len; add cap=8 when jokers need hub-bridge paths.
            if (
                hanafuda_level >= 1
                and joker_count >= 2
                and self.max_len > 8
            ):
                caps = [8, self.max_len]
            elif (
                has_fraction_tiles
                and _chess_tile_count(board) >= 3
                and self.max_len > 8
            ):
                caps = [8, self.max_len]
            else:
                caps = [self.max_len]
        elif chess_reserve > 0.0 and self.max_len > self.min_len:
            caps = _chess_serial_cap_sequence(self.min_len, self.max_len)
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
        if run_until_found:
            deadline = float("inf")
            self._active_deadline = None
        else:
            local_deadline = search_begin + self.time_budget
            if deadline is not None:
                local_deadline = min(local_deadline, deadline)
            deadline = local_deadline
            self._active_deadline = deadline
        post_dfs_reserve = (
            number_reserve
            + void_reserve
            + fraction_cluster_reserve
            + chess_reserve
            + seed_reserve
            + extension_reserve
            + up_and_up_reserve
        )
        main_deadline = deadline - post_dfs_reserve
        main_dfs_floor = search_begin + self.time_budget * MAIN_DFS_FLOOR_FRAC
        if main_deadline < main_dfs_floor:
            main_deadline = main_dfs_floor
        timing.reserve_scaling_applied = reserve_scaled
        timing.main_dfs_slice_sec = max(0.0, main_deadline - search_begin)
        pre_extend_deadline = deadline - extension_reserve if extension_reserve > 0 else deadline
        curse_heavy = joker_count >= 2 and _chess_tile_count(board) >= 3
        parallel_dfs_viable = use_parallel and main_deadline > search_begin
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
        ctx_for_wrap = self._search_ctx(loadout)
        if (
            flag_test(ctx_for_wrap.search_flags, FLAG_HORIZONTAL_WRAP)
            and joker_count >= 2
            and _chess_tile_count(board) >= 2
        ):
            wrap_deadline = min(
                deadline,
                search_begin + min(2.0, self.time_budget * 0.05),
            )
            self._collect_wrap_wildcard_chess_path_seeds(
                board,
                loadout,
                candidates,
                wrap_deadline,
                self.max_len,
            )
        heap_before_letter = len(candidates)
        if self._full_board_exact:
            ham_deadline = float("inf") if run_until_found else main_deadline
            self._collect_full_board_hamiltonian_candidates(
                board,
                loadout,
                candidates,
                ham_deadline,
            )
        elif self._small_board_hamiltonian:
            ham_slice = min(12.0, self.time_budget * 0.2)
            ham_deadline = min(main_deadline, search_begin + ham_slice)
            if ham_deadline > time.monotonic():
                self._collect_small_board_hamiltonian_candidates(
                    board,
                    loadout,
                    candidates,
                    ham_deadline,
                    target_len=active_count,
                )
        try:
            standard_search = len(candidates) == 0 or self._small_board_hamiltonian
            if (
                standard_search
                and not self._full_board_exact
                and has_fraction_tiles
                and _chess_tile_count(board) >= 3
                and self.max_len >= 8
                and time.monotonic() < main_deadline
            ):
                fraction_starts = [
                    i
                    for i in _legal_word_start_indices(board)
                    if is_fraction_tile(board.get_by_index(i))
                ]
                if fraction_starts:
                    frac_slice = min(3.0, self.time_budget * 0.08)
                    frac_deadline = min(
                        main_deadline, time.monotonic() + frac_slice
                    )
                    self._collect_words_fair_starts(
                        board,
                        loadout,
                        candidates,
                        frac_deadline,
                        min(8, self.max_len),
                        fraction_starts,
                    )
            if standard_search and center_idx is not None and up_and_up_reserve > 0.0:
                up_deadline = min(main_deadline, search_begin + up_and_up_reserve)
                if up_deadline > time.monotonic():
                    self._collect_up_and_up_center_words(
                        board,
                        loadout,
                        candidates,
                        up_deadline,
                        center_idx,
                        self.max_len,
                        has_fraction_tiles=has_fraction_tiles,
                        has_number_tiles=has_number_tiles,
                    )
            if standard_search and parallel_dfs_viable:
                for pass_idx, cap in enumerate(caps):
                    if time.monotonic() >= main_deadline:
                        break
                    starts_for_cap = _dfs_starts_for_cap(
                        cap, self.min_len, letter_starts, chess_starts
                    )
                    if starts_for_cap is letter_starts:
                        if pass_idx > 0 and start_productivity:
                            letter_starts = sorted(
                                letter_starts,
                                key=lambda s: (-start_productivity.get(s, 0), s),
                            )
                            starts_for_cap = letter_starts
                        min_slice = self._adaptive_min_slice(candidates, pass_idx)
                    else:
                        min_slice = None
                    letter_pass_deadline = main_deadline
                    if starts_for_cap is letter_starts:
                        now = time.monotonic()
                        rem = max(0.0, main_deadline - now)
                        pass_share = 0.65 if curse_heavy else 0.45
                        letter_pass_deadline = min(
                            main_deadline,
                            now + min(12.0, rem * pass_share),
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
            elif standard_search and not use_parallel:
                center_still_needed = (
                    center_idx is not None
                    and not _candidate_heap_includes_index(candidates, center_idx)
                )
                if not center_still_needed:
                    for pass_idx, cap in enumerate(caps):
                        if time.monotonic() >= main_deadline:
                            break
                        starts_for_cap = _dfs_starts_for_cap(
                            cap, self.min_len, letter_starts, chess_starts
                        )
                        if starts_for_cap is letter_starts:
                            if pass_idx > 0 and start_productivity:
                                letter_starts = sorted(
                                    letter_starts,
                                    key=lambda s: (-start_productivity.get(s, 0), s),
                                )
                                starts_for_cap = letter_starts
                            min_slice = self._adaptive_min_slice(
                                candidates, pass_idx
                            )
                        else:
                            min_slice = None
                        self._collect_words_fair_starts(
                            board,
                            loadout,
                            candidates,
                            main_deadline,
                            cap,
                            starts_for_cap,
                            min_slice_override=min_slice,
                            start_productivity=start_productivity if starts_for_cap is letter_starts else None,
                        )
                elif center_idx is not None and time.monotonic() < main_deadline:
                    self._collect_up_and_up_center_words(
                        board,
                        loadout,
                        candidates,
                        main_deadline,
                        center_idx,
                        self.max_len,
                        has_fraction_tiles=has_fraction_tiles,
                        has_number_tiles=has_number_tiles,
                    )

            timing.letter_dfs_added = len(candidates) - heap_before_letter
            center_missing = (
                center_idx is not None
                and not _candidate_heap_includes_index(candidates, center_idx)
            )
            needs_serial_fallback = use_parallel and (
                not parallel_dfs_viable
                or not candidates
                or timing.letter_dfs_added == 0
                or candidates.all_paths_max_len(1)
                or center_missing
            )
            if standard_search and needs_serial_fallback:
                timing.parallel_serial_fallback = True
                self._parallel_executor = None
                saved_workers = self.search_workers
                self.search_workers = 1
                if center_missing:
                    fallback_starts = _up_and_up_center_adjacent_starts(
                        board, center_idx
                    )
                    prefer_long = has_fraction_tiles or has_number_tiles
                    if self.time_budget >= 6.0 and self.max_len > self.min_len:
                        fallback_caps = _up_and_up_cap_sequence(
                            self.min_len,
                            self.max_len,
                            prefer_long_first=prefer_long,
                            board=board,
                            center_idx=center_idx,
                        )
                    else:
                        fallback_caps = [self.max_len]
                    fallback_deadline = pre_extend_deadline
                else:
                    fallback_caps = (
                        list(range(self.min_len, self.max_len + 1))
                        if self.time_budget >= 6.0 and self.max_len > self.min_len
                        else [self.max_len]
                    )
                    post_dfs_budget = (
                        number_reserve + void_reserve + fraction_cluster_reserve
                        if has_number_tiles
                        else 0.0
                    )
                    fallback_deadline = pre_extend_deadline
                    if post_dfs_budget > 0.0:
                        remaining = max(0.0, pre_extend_deadline - time.monotonic())
                        fallback_deadline = min(
                            pre_extend_deadline,
                            time.monotonic()
                            + max(0.0, remaining - post_dfs_budget),
                        )
                    fallback_starts = letter_starts
                try:
                    for i, cap in enumerate(fallback_caps):
                        if time.monotonic() >= fallback_deadline:
                            break
                        cap_deadline = fallback_deadline
                        if center_missing:
                            remaining = max(0.0, fallback_deadline - time.monotonic())
                            caps_left = len(fallback_caps) - i
                            cap_deadline = min(
                                fallback_deadline,
                                time.monotonic() + max(0.5, remaining / caps_left),
                            )
                        self._collect_words_fair_starts(
                            board,
                            loadout,
                            candidates,
                            cap_deadline,
                            cap,
                            fallback_starts,
                            min_slice_override=self._adaptive_min_slice(
                                candidates, 0
                            ),
                            start_productivity=start_productivity,
                        )
                        if (
                            center_missing
                            and center_idx is not None
                            and _candidate_heap_includes_index(candidates, center_idx)
                        ):
                            break
                finally:
                    self.search_workers = saved_workers
                    self._parallel_executor = pool

            if standard_search and has_number_tiles:
                self._seed_single_number_tile_words(board, loadout, candidates)

            improve_words = equipped_improve_words(loadout)
            if standard_search and improve_words:
                self._seed_stamp_improve_words(
                    board, loadout, candidates, improve_words
                )

            if standard_search and has_number_tiles:
                self._parallel_executor = None
                if (
                    not self._full_board_exact
                    and fraction_cluster_reserve > 0
                    and time.monotonic() < pre_extend_deadline
                ):
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
                        max_number_face = _max_number_face_on_board(board)
                        cluster_cap = min(
                            max(9, max_number_face), self.max_len
                        )
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
                max_number_face = _max_number_face_on_board(board)
                min_cap_for_numbers = max(8, max_number_face)
                if (
                    number_starts
                    and self.time_budget >= 6.0
                    and time.monotonic() < pre_extend_deadline
                ):
                    lead_deadline = min(
                        pre_extend_deadline,
                        time.monotonic() + number_reserve,
                    )
                    if lead_deadline > time.monotonic():
                        self._collect_words(
                            board,
                            loadout,
                            candidates,
                            lead_deadline,
                            min_cap_for_numbers,
                            digits_only=True,
                            start_indices=[number_starts[0]],
                        )
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
                    if (
                        cap >= min_cap_for_numbers
                        and len(candidates) == before
                        and self.time_budget >= 6.0
                    ):
                        break
        finally:
            self._parallel_executor = None

        timing.dfs_sec = time.monotonic() - dfs_start

        if (
            center_idx is not None
            and time.monotonic() < pre_extend_deadline
            and not _candidate_heap_includes_index(candidates, center_idx)
        ):
            center_slice = min(12.0, self.time_budget * 0.25)
            reserve = max(up_and_up_reserve, center_slice)
            up_deadline = min(
                pre_extend_deadline,
                time.monotonic() + reserve,
            )
            if up_deadline > time.monotonic():
                self._collect_up_and_up_center_words(
                    board,
                    loadout,
                    candidates,
                    up_deadline,
                    center_idx,
                    self.max_len,
                    has_fraction_tiles=has_fraction_tiles,
                    has_number_tiles=has_number_tiles,
                )

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

        heap_k = self.candidate_heap_size or _candidate_heap_size(top_n, mult_count)
        chess_seeds: list[tuple[float, str, tuple[int, ...]]] = []
        post_extend_slack = min(8.0, max(extension_reserve, 5.0))
        resolve_grace = min(20.0, extension_reserve + post_extend_slack + 8.0)
        resolve_phase_deadline = deadline + resolve_grace
        if len(candidates) > 0 and time.monotonic() < resolve_phase_deadline:
            self._active_deadline = resolve_phase_deadline
            chess_start = time.monotonic()
            chess_max_cap = (
                self.max_len
                if self._full_board_exact
                else (
                    8
                    if has_fraction_tiles and _chess_tile_count(board) >= 3
                    else 5
                )
            )
            chess_seeds = self._chess_prefix_candidates(
                board,
                loadout,
                solve_deadline=pre_extend_deadline,
                max_cap=chess_max_cap,
            )
            timing.chess_sec = time.monotonic() - chess_start
            extend_start = time.monotonic()
            extend_deadline = resolve_phase_deadline
            leader_imm = candidates.max_immediate_score()
            if leader_imm is not None and leader_imm >= 400:
                extend_cap = min(3.0, extension_reserve or 3.0)
                extend_deadline = min(
                    extend_deadline, time.monotonic() + extend_cap
                )
            top_paths = (
                min(120, len(candidates), heap_k)
                if chess_seeds
                else min(
                    60 if curse_heavy else 30,
                    len(candidates),
                    heap_k,
                )
            )
            max_extend_rounds: int | None = None
            if self.max_len > self.min_len:
                preview = candidates.best_sorted()[:top_paths]
                ext_stamp_flags = self._search_ctx(loadout).search_flags
                from cursed_words_solver.suggestion import (
                    path_tiles_need_dictionary_resolve,
                )

                if any(
                    "?" in word
                    or path_tiles_need_dictionary_resolve(
                        board, list(path), flags=ext_stamp_flags
                    )
                    for _sc, word, path in preview
                ):
                    top_paths = min(120, len(candidates), heap_k)
                    max_extend_rounds = min(self.max_len - self.min_len, 16)
            leader_extra_seeds = [
                (sc, word, path)
                for sc, word, path in candidates.best_sorted()[:5]
            ]
            resolve_extra_seeds = self._dictionary_resolve_extension_seeds(
                board, loadout, candidates
            )
            combined_extra_seeds: list[tuple[float, str, tuple[int, ...]]] = []
            if chess_seeds:
                combined_extra_seeds.extend(chess_seeds)
            combined_extra_seeds.extend(leader_extra_seeds)
            seen_seed_paths: set[tuple[int, ...]] = set()
            deduped_extra: list[tuple[float, str, tuple[int, ...]]] = []
            for entry in combined_extra_seeds + resolve_extra_seeds:
                path_key = entry[2]
                if path_key in seen_seed_paths:
                    continue
                seen_seed_paths.add(path_key)
                deduped_extra.append(entry)
            if time.monotonic() < extend_deadline:
                self._supplement_fraction_chess_word_boundaries(
                    board,
                    loadout,
                    candidates,
                    deadline=extend_deadline,
                )
            self._extend_top_candidates(
                board,
                loadout,
                candidates,
                top_paths=top_paths,
                max_rounds=max_extend_rounds,
                extra_seeds=deduped_extra or None,
                deadline=extend_deadline if extension_reserve > 0 else deadline,
            )
            if time.monotonic() < extend_deadline:
                resolve_deadline = extend_deadline
                if extension_reserve > 0 and not (
                    has_fraction_tiles and _chess_tile_count(board) >= 3
                ):
                    resolve_deadline = min(
                        extend_deadline,
                        time.monotonic()
                        + max(4.0, extension_reserve * 0.55),
                    )
                self._extend_dictionary_resolve_boundaries(
                    board,
                    loadout,
                    candidates,
                    deadline=resolve_deadline,
                )
            timing.extend_sec = time.monotonic() - extend_start

        refine_start = time.monotonic()
        deferred_snapshot = dict(self._provisional_candidates)
        refined_keys: set[tuple[tuple[int, ...], str]] = set()
        self._refine_provisional_heap(
            board,
            loadout,
            candidates,
            deadline=deadline,
            refined_keys=refined_keys,
        )
        unrefined = len(deferred_snapshot) - len(refined_keys)
        if (
            unrefined > 0
            and self._use_tier2_two_phase_for(loadout)
            and len(candidates) > 0
        ):
            leader_prefixes = [
                path for _sc, _word, path in candidates.best_sorted()[:heap_k]
            ]
            overrun_start = time.monotonic()
            self._refine_provisional_heap(
                board,
                loadout,
                candidates,
                deadline=deadline + REFINE_OVERRUN_SEC,
                pending={
                    key: rank_ub
                    for key, rank_ub in deferred_snapshot.items()
                    if key not in refined_keys
                },
                refined_keys=refined_keys,
                path_prefixes=leader_prefixes,
                refine_cap_override=heap_k,
            )
            timing.refine_overrun_sec = time.monotonic() - overrun_start
            timing.refine_overrun_deferred = unrefined
        timing.refine_sec = time.monotonic() - refine_start

        if (
            self.max_len > self.min_len
            and extension_reserve > 0
            and len(candidates) > 0
        ):
            post_extend_start = time.monotonic()
            post_extend_reserve = min(8.0, max(extension_reserve, 5.0))
            post_extend_deadline = resolve_phase_deadline
            post_top_paths = min(heap_k, 60, len(candidates))
            post_resolve_seeds = self._dictionary_resolve_extension_seeds(
                board, loadout, candidates
            )
            post_max_rounds = (
                min(self.max_len - self.min_len, 16)
                if post_resolve_seeds
                else min(3, self.max_len - self.min_len)
            )
            self._extend_top_candidates(
                board,
                loadout,
                candidates,
                top_paths=post_top_paths,
                max_rounds=post_max_rounds,
                extra_seeds=post_resolve_seeds or None,
                deadline=post_extend_deadline,
            )
            if time.monotonic() < post_extend_deadline:
                self._extend_dictionary_resolve_boundaries(
                    board,
                    loadout,
                    candidates,
                    deadline=post_extend_deadline,
                )
            timing.extend_sec += time.monotonic() - post_extend_start

        if self.max_len > self.min_len and len(candidates) > 0:
            if any(is_fraction_tile(t) for t in board.flat) and _chess_tile_count(
                board
            ) >= 3:
                final_resolve_deadline = resolve_phase_deadline
                self._active_deadline = final_resolve_deadline
                self._extend_dictionary_resolve_boundaries(
                    board,
                    loadout,
                    candidates,
                    deadline=final_resolve_deadline,
                )
                self._guarantee_fraction_chess_probe_extensions(
                    board,
                    loadout,
                    candidates,
                    deadline=final_resolve_deadline,
                )

        best_by_word: dict[
            str, tuple[float, float, float, str, tuple[int, ...]]
        ] = {}
        finalize_deadline = time.monotonic() + 5.0
        prev_finalize_deadline = self._active_deadline
        self._active_deadline = finalize_deadline
        try:
            for rank_sc, word, path_tuple in candidates.best_sorted():
                path = list(path_tuple)
                immediate, setup = self._immediate_and_setup(
                    board, path, word, loadout
                )
                cached = self._score_cache.get((path_tuple, word))
                if cached is None:
                    ctx = self._search_ctx(loadout)
                    score_word = physical_word_for_path(
                        board, path, flags=ctx.search_flags
                    )
                    cached = self._score_cache.get((path_tuple, score_word))
                if cached is not None:
                    sort_rank = cached[2]
                elif immediate > 0:
                    sort_rank = immediate + setup
                else:
                    sort_rank = rank_sc
                prev = best_by_word.get(word)
                if prev is not None:
                    if quest_inverts_search_rank(loadout):
                        if immediate >= prev[0]:
                            continue
                    elif bullseye_active(loadout):
                        if quest_candidate_rank(
                            immediate, sort_rank, loadout
                        ) <= quest_candidate_rank(prev[0], prev[2], loadout):
                            continue
                    elif immediate <= prev[0]:
                        continue
                best_by_word[word] = (
                    immediate,
                    setup,
                    sort_rank,
                    word,
                    path_tuple,
                )
        finally:
            self._active_deadline = prev_finalize_deadline

        unique: list[WordResult] = []
        ranked_finalists = sorted(
            best_by_word.values(),
            key=lambda row: -quest_candidate_rank(row[0], row[2], loadout),
        )
        for immediate, setup, rank_sc, word, path_tuple in ranked_finalists:
            if time.monotonic() >= deadline and len(unique) >= top_n:
                break
            path = list(path_tuple)
            t_final = time.perf_counter()
            _, bd = self.scoring.score(
                board,
                path,
                word,
                loadout,
                solve_context=self._solve_ctx,
                **self._pipeline_cache_kwargs(),
            )
            timing.final_score_sec += time.perf_counter() - t_final
            ms_uses = microscope_position_uses(
                board,
                path,
                word,
                flags=self._solve_ctx.search_flags,
            )
            if ms_uses:
                bd = dict(bd)
                bd["microscope_positions"] = ms_uses
                bd["microscope_hint"] = format_microscope_position_hint(ms_uses)
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
        if not unique and len(candidates) > 0:
            for rank_sc, word, path_tuple in candidates.best_sorted()[:top_n]:
                path = list(path_tuple)
                immediate, setup = self._immediate_and_setup(
                    board, path, word, loadout
                )
                unique.append(
                    WordResult(
                        word=word,
                        path=path,
                        score=immediate,
                        breakdown={},
                        setup_bonus=setup,
                        rank_score=rank_sc if rank_sc else immediate + setup,
                    )
                )
        from cursed_words_solver.models import board_flat_call_count
        from cursed_words_solver.rules.chess_tiles import chess_attack_cache_stats

        ch, cm = chess_attack_cache_stats()
        timing.chess_attack_cache_hits = ch
        timing.chess_attack_cache_misses = cm
        timing.board_flat_calls = board_flat_call_count()
        timing.wall_sec = time.monotonic() - solve_start
        self.last_search_timing = timing
        self._active_timing = None
        self._active_deadline = None
        self.validator.quest_loadout = None
        self.validator.extra_valid_words = frozenset()
        set_quest_movement_loadout(None)
        set_quest_search_target(None)
        if center_idx is not None:
            unique = [r for r in unique if center_idx in r.path]
        return unique[:top_n]
