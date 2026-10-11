"""Word search entry point: ``WordSearcher`` runs the exact game-port engine.

Every board is searched by ``engine/search.py`` (movement, vocabulary and scoring
ported from the game), so suggestions are exactly the paths the game accepts,
ranked by the score the game will give. See docs/SEARCH_ARCHITECTURE.md.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from cursed_words_solver.config import DEFAULT_SEARCH_TIME_BUDGET_SEC
from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.models import Board, Loadout, WordResult


@dataclass
class SearchTiming:
    """Phase timings from the last ``find_best_words`` call."""

    wall_sec: float = 0.0
    enum_sec: float = 0.0
    score_sec: float = 0.0
    paths: int = 0
    scored: int = 0
    nodes: int = 0
    parallel_workers: int = 1
    exhaustive: bool = True

    def summary(self) -> str:
        coverage = "exhaustive" if self.exhaustive else "time-limited"
        workers = f", {self.parallel_workers} workers" if self.parallel_workers > 1 else ""
        return (
            f"enumerate {self.enum_sec:.2f}s, score {self.score_sec:.2f}s "
            f"({self.scored} paths scored, {coverage}{workers}; {self.wall_sec:.2f}s total)"
        )


# Legacy ``StampSearchFlags`` bits -> the item each one stands for (tests and old
# callers describe a loadout this way; the engine reads real items).
_FLAG_ITEMS = (
    (1 << 0, "hungry_snake"),
    (1 << 1, "full_moon"),
    (1 << 2, "queenie"),
    (1 << 3, "red_envelope"),
    (1 << 4, "sluggish_zombie"),
    (1 << 5, "flamingo"),
    (1 << 6, "test_tube"),
    (1 << 7, "card_shark"),
    (1 << 8, "spicy_pepper"),
    (1 << 9, "number_go_up"),
    (1 << 10, "honeypot"),
    (1 << 11, "bunch_of_grapes"),
    (1 << 12, "jellyfish"),
    (1 << 13, "suspension_bridge"),
    (1 << 14, "king_of_the_bridge"),
    (1 << 15, "television"),
    (1 << 16, "microscope"),
)


def loadout_for(board: Board, loadout: Loadout | None, flags: Any = 0) -> Loadout:
    """``loadout``, or one holding the items legacy search ``flags`` describe."""
    if loadout is not None:
        return loadout
    from cursed_words_solver.models import LoadoutItem
    from cursed_words_solver.rules.stamp_behaviors import coerce_search_flags

    mask = coerce_search_flags(flags)
    stamps = [LoadoutItem(slug, slug, 1, "stamp") for bit, slug in _FLAG_ITEMS if mask & bit]
    return Loadout(money=board.money, stamps=stamps)


class PathValidator:
    """Search constraints the caller adds on top of the game's rules.

    ``required_consumable_indices``: tiles every suggestion must use (placed
    consumables). ``quest_loadout``: loadout the game rules come from.
    ``word_ok`` asks the engine whether the game accepts ``path``.
    """

    def __init__(self, dictionary: WordDictionary, min_len: int = 3, **_ignored: Any) -> None:
        self.dictionary = dictionary
        self.min_len = min_len
        self.required_consumable_indices: frozenset[int] = frozenset()
        self.quest_loadout: Loadout | None = None

    def word_ok(self, board: Board, path: list[int], word: str = "", flags: Any = 0, *, stamp_flags: Any = 0) -> bool:
        """The game accepts ``path`` (``word`` is ignored: the engine derives the
        spelling from the board and loadout; ``flags`` only stand in for a loadout)."""
        from cursed_words_solver.engine.solver import engine_path_submittable

        required = self.required_consumable_indices
        if required and not required.issubset(path):
            return False
        loadout = loadout_for(board, self.quest_loadout, flags or stamp_flags)
        return engine_path_submittable(board, list(path), loadout, self.dictionary, min_len=self.min_len)


def path_movement_ok(board: Board, path: list[int], *, loadout: Loadout | None = None, flags: Any = 0, **_ignored: Any) -> bool:
    """Every step of ``path`` is a legal selection in the game."""
    from cursed_words_solver.engine.solver import engine_path_movement_ok

    return engine_path_movement_ok(board, list(path), loadout_for(board, loadout, flags))


def search_word_from_path(board: Board, path: list[int], *, loadout: Loadout | None = None, flags: Any = 0, **_ignored: Any) -> str:
    """Face spelling of ``path``: letters as shown, ``?`` for wildcard tiles."""
    from cursed_words_solver.engine.board_paths import BoardPaths

    return BoardPaths.for_board(board, loadout_for(board, loadout, flags)).spell(path)


def neighbors_from_tile(
    board: Board, path: list[int], visited: set[int] | int = 0, *, loadout: Loadout | None = None, flags: Any = 0
) -> list[int]:
    """Tiles selectable after ``path`` (excluding ``visited``)."""
    from cursed_words_solver.engine.board_paths import BoardPaths

    used = visited if isinstance(visited, set) else {i for i in range(64) if (int(visited) >> i) & 1}
    return [j for j in BoardPaths.for_board(board, loadout_for(board, loadout, flags)).next_tiles(path) if j not in used]


def paths_between(board: Board, start: int, end: int, max_len: int, *, limit: int = 1, loadout: Loadout | None = None) -> list[list[int]]:
    """Up to ``limit`` legal paths from ``start`` to ``end`` with at most ``max_len`` tiles."""
    from cursed_words_solver.engine.board_paths import BoardPaths

    out: list[list[int]] = []
    for path in BoardPaths.for_board(board, loadout).walk(2, max_len, starts=[start]):
        if path[-1] == end:
            out.append(path)
            if len(out) >= limit:
                break
    return out


class WordSearcher:
    """Find the best-scoring words on a board (exact engine search)."""

    def __init__(
        self,
        dictionary: WordDictionary | None = None,
        min_len: int = 3,
        max_len: int = 15,
        time_budget: float = DEFAULT_SEARCH_TIME_BUDGET_SEC,
        *,
        blocked: bool = False,
        block_reason: str = "",
        search_workers: int = 1,
        wordlist_path: Path | None = None,
    ) -> None:
        self.dictionary = dictionary or WordDictionary()
        self.validator = PathValidator(self.dictionary, min_len)
        self.min_len = min_len
        self.max_len = max_len
        self.time_budget = time_budget
        self.blocked = blocked
        self.block_reason = block_reason
        self.search_workers = max(1, int(search_workers))
        self._wordlist_path = wordlist_path or getattr(self.dictionary, "path", None)
        self._cancel_check: Callable[[], bool] | None = None
        self.last_search_timing: SearchTiming | None = None
        self.last_exact_info: dict = {}

    def find_best_words(
        self,
        board: Board,
        loadout: Loadout | None = None,
        top_n: int = 3,
        *,
        deadline: float | None = None,
        run_until_found: bool = False,
        cancel_check: Callable[[], bool] | None = None,
    ) -> list[WordResult]:
        """Best ``top_n`` distinct words by game score (quest targets rank by closeness).

        ``deadline`` is a ``time.monotonic()`` instant; without one the search gets
        ``time_budget`` seconds. ``run_until_found`` is accepted for API
        compatibility (the exact search does not stop early on a find).
        """
        del run_until_found
        if self.blocked:
            return []
        from cursed_words_solver.engine.solver import ParallelSpec, exact_find_best_words
        from cursed_words_solver.rules.quest_scoring import (
            bullseye_active,
            encounter_remaining_from_loadout,
            search_rank_for_quest,
        )

        start = time.monotonic()
        loadout = loadout or Loadout(money=board.money)
        quest_target: float | None = None
        if bullseye_active(loadout):
            remaining = encounter_remaining_from_loadout(loadout)
            if remaining > 0:
                quest_target = float(remaining)
        if deadline is None and self.time_budget:
            deadline = start + float(self.time_budget)
        perf_deadline = None
        if deadline is not None:
            perf_deadline = time.perf_counter() + max(0.0, deadline - time.monotonic())
        cancel = cancel_check or self._cancel_check
        parallel = None
        if self.search_workers > 1 and self._wordlist_path is not None:
            from cursed_words_solver.search_parallel import get_search_pool

            pool = get_search_pool(Path(self._wordlist_path), self.search_workers)
            if pool is not None:
                parallel = ParallelSpec(pool, self.search_workers, quest_target)
        results, info = exact_find_best_words(
            self.dictionary,
            board,
            loadout,
            top_n=top_n,
            min_len=self.min_len,
            max_len=self.max_len,
            required_indices=frozenset(self.validator.required_consumable_indices or ()),
            deadline=perf_deadline,
            cancel_check=cancel,
            rank=lambda s: search_rank_for_quest(float(s), loadout, quest_target=quest_target),
            parallel=parallel,
        )
        info.pop("plan", None)
        self.last_exact_info = info
        self.last_search_timing = SearchTiming(
            wall_sec=time.monotonic() - start,
            enum_sec=float(info.get("enum_sec", 0.0)),
            score_sec=float(info.get("score_sec", 0.0)),
            paths=int(info.get("paths", 0) or 0),
            scored=int(info.get("scored", 0) or 0),
            nodes=int(info.get("nodes", 0) or 0),
            parallel_workers=int(info.get("parallel_workers", 1)),
            exhaustive=bool(info.get("exhaustive", True)),
        )
        return results


def microscope_position_uses(
    board: Board, path: list[int], word: str = "", *, loadout: Loadout | None = None, flags: Any = 0, **_ignored: Any
) -> list[dict[str, Any]]:
    """Path positions that are wildcards only because Microscope matches the tile's value."""
    import copy

    from cursed_words_solver.engine.board_paths import BoardPaths
    from cursed_words_solver.engine.model import G_LETTER

    search = BoardPaths.for_board(board, loadout_for(board, loadout, flags)).search
    path = tuple(path)
    inv = search.inventory_for(path)
    if not inv.microscope:
        return []
    without = copy.copy(inv)
    without.microscope = False
    tiles = [search.tiles[i] for i in path]
    nums = [t.number_float() for t in tiles if t.is_number()]
    ascending = all(nums[i] > nums[i - 1] for i in range(1, len(nums)))
    uses: list[dict[str, Any]] = []
    for pos, (idx, t) in enumerate(zip(path, tiles)):
        if word and t.glyph == G_LETTER and pos < len(word) and word[pos].lower() == t.letter:
            continue  # the tile's own letter is used; Microscope was not needed
        if t.value == pos + 1 and not search._is_wildcard(t, pos, without, ascending):
            tile = board.get_by_index(idx)
            uses.append(
                {
                    "index": idx,
                    "position": pos + 1,
                    "tile": tile.letter or tile.char,
                    "base_score": t.value,
                    "mode": "letter_as_digit" if t.glyph == G_LETTER else "alternate_number_position",
                }
            )
    return uses


def format_microscope_position_hint(uses: list[dict[str, Any]]) -> str:
    """Single-line hint for overlay / trace when Microscope position flex applies."""
    if not uses:
        return ""
    parts = [
        f"{use.get('tile') or '?'} at position {int(use['position'])} via base_score {int(use['base_score'])}"
        for use in uses
    ]
    return "Microscope: " + "; ".join(parts)
