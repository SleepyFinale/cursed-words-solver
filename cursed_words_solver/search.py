"""Word search on 5x5 board with curse-aware movement."""

from __future__ import annotations

import time
from typing import Callable

from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.models import (
    CHESS_CURSES,
    Board,
    CurseType,
    Loadout,
    Tile,
    WordResult,
)
from cursed_words_solver.rules.pipeline import ScoringPipeline

# 8 directions
DIRS_8 = [
    (-1, -1), (-1, 0), (-1, 1),
    (0, -1),           (0, 1),
    (1, -1),  (1, 0),  (1, 1),
]

# Knight L-moves
KNIGHT_DIRS = [
    (-2, -1), (-2, 1), (-1, -2), (-1, 2),
    (1, -2), (1, 2), (2, -1), (2, 1),
]


def index_of(row: int, col: int) -> int:
    return row * 5 + col


def resolve_letter(tile: Tile, position: int) -> str:
    """Letter used in word at 0-based position."""
    if tile.curse == CurseType.CURRENCY:
        return tile.letter
    if tile.curse == CurseType.WILDCARD:
        return "?"
    if tile.curse in CHESS_CURSES:
        return tile.letter if tile.letter != "?" else "?"
    if tile.curse == CurseType.NUMBER:
        return tile.letter
    return tile.letter.upper() if tile.letter else "?"


def number_position_valid(tile: Tile, position: int, relaxed: bool = False) -> bool:
    if relaxed or tile.curse != CurseType.NUMBER:
        return True
    if tile.number_value is None:
        return True
    # Wiki: number N must be at position N (1-indexed)
    return position + 1 == tile.number_value


def fraction_position_valid(
    tile: Tile, position: int, word_len: int, relaxed: bool = False
) -> bool:
    if relaxed or tile.curse != CurseType.FRACTION:
        return True
    # Can occur at numerator or denominator position — allow either slot from OCR
    return True


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

    def prefix_ok(self, prefix: str) -> bool:
        if "?" in prefix:
            return True  # cannot prune wildcards via trie easily
        return self.dictionary.has_prefix(prefix)

    def word_ok(self, board: Board, path: list[int], word: str) -> bool:
        if len(word) < self.min_len:
            return False
        for i, idx in enumerate(path):
            tile = board.get_by_index(idx)
            if not number_position_valid(tile, i, self.relaxed_numbers):
                return False
            if not fraction_position_valid(tile, i, len(word), self.relaxed_numbers):
                return False
        if "?" in word:
            return self._wildcard_valid(word)
        return self.dictionary.is_valid_word(word, self.min_len)

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


def neighbors_standard(
    board: Board, path: list[int], visited: set[int]
) -> list[int]:
    last = path[-1]
    row, col = last // 5, last % 5
    out = []
    for dr, dc in DIRS_8:
        nr, nc = row + dr, col + dc
        if 0 <= nr < 5 and 0 <= nc < 5:
            idx = index_of(nr, nc)
            if idx not in visited:
                out.append(idx)
    return out


def neighbors_from_tile(
    board: Board, path: list[int], visited: set[int]
) -> list[int]:
    """Curse-aware neighbor expansion."""
    last_tile = board.get_by_index(path[-1])

    # WHITE tile: can teleport to any unused cell (once per step from white)
    if last_tile.color.value == "white":
        return [i for i in range(25) if i not in visited]

    if last_tile.curse == CurseType.CHESS_KNIGHT:
        row, col = last_tile.row, last_tile.col
        out = []
        for dr, dc in KNIGHT_DIRS:
            nr, nc = row + dr, col + dc
            if 0 <= nr < 5 and 0 <= nc < 5:
                idx = index_of(nr, nc)
                if idx not in visited:
                    out.append(idx)
        return out

    if last_tile.curse == CurseType.CHESS_ROOK:
        return _line_neighbors(board, path[-1], visited, rook=True)

    if last_tile.curse == CurseType.CHESS_BISHOP:
        return _line_neighbors(board, path[-1], visited, bishop=True)

    if last_tile.curse in (
        CurseType.CHESS_QUEEN,
        CurseType.CHESS_KING,
    ):
        # Queen: any straight line; King: one step any direction
        if last_tile.curse == CurseType.CHESS_KING:
            return neighbors_standard(board, path, visited)
        return _line_neighbors(board, path[-1], visited, rook=True, bishop=True)

    # Pawn: standard 8-neighbor (simplified; color-specific direction optional)
    return neighbors_standard(board, path, visited)


def _line_neighbors(
    board: Board,
    start_idx: int,
    visited: set[int],
    rook: bool = False,
    bishop: bool = False,
) -> list[int]:
    row, col = start_idx // 5, start_idx % 5
    out = []
    straight = [(-1, 0), (1, 0), (0, -1), (0, 1)]
    diag = [(-1, -1), (-1, 1), (1, -1), (1, 1)]
    dirs = []
    if rook:
        dirs.extend(straight)
    if bishop:
        dirs.extend(diag)
    for dr, dc in dirs:
        step = 1
        while True:
            nr, nc = row + dr * step, col + dc * step
            if not (0 <= nr < 5 and 0 <= nc < 5):
                break
            idx = index_of(nr, nc)
            if idx not in visited:
                out.append(idx)
            step += 1
    return out


class WordSearcher:
    def __init__(
        self,
        dictionary: WordDictionary | None = None,
        min_len: int = 3,
        max_len: int = 12,
        time_budget: float = 2.0,
        score_fn: Callable | None = None,
    ) -> None:
        self.dictionary = dictionary or WordDictionary()
        self.validator = PathValidator(self.dictionary, min_len)
        self.min_len = min_len
        self.max_len = max_len
        self.time_budget = time_budget
        self.scoring = ScoringPipeline()
        self.score_fn = score_fn

    def find_best_words(
        self,
        board: Board,
        loadout: Loadout | None = None,
        top_n: int = 3,
    ) -> list[WordResult]:
        loadout = loadout or Loadout(money=board.money)
        results: list[WordResult] = []
        start_time = time.monotonic()

        def score_path(path: list[int], word: str) -> float:
            if self.score_fn:
                return self.score_fn(board, path, word, loadout)
            s, _ = self.scoring.score(board, path, word, loadout)
            return s

        def dfs(path: list[int], letters: str, visited: set[int]) -> None:
            if time.monotonic() - start_time > self.time_budget:
                return

            word = letters.lower()
            if len(word) >= self.min_len and self.validator.word_ok(board, path, word):
                sc = score_path(path, word)
                breakdown = {}
                _, bd = self.scoring.score(board, path, word, loadout)
                breakdown = bd
                results.append(
                    WordResult(word=word, path=path.copy(), score=sc, breakdown=breakdown)
                )

            if len(path) >= self.max_len:
                return

            if "?" not in word and not self.validator.prefix_ok(word):
                return

            nbrs = neighbors_from_tile(board, path, visited)
            for idx in nbrs:
                tile = board.get_by_index(idx)
                ch = resolve_letter(tile, len(letters))
                new_letters = letters + ch
                new_path = path + [idx]
                new_visited = visited | {idx}
                dfs(new_path, new_letters, new_visited)

        for start in range(25):
            if time.monotonic() - start_time > self.time_budget:
                break
            tile = board.get_by_index(start)
            ch = resolve_letter(tile, 0)
            dfs([start], ch, {start})

        results.sort(key=lambda r: r.score, reverse=True)
        seen_words: set[str] = set()
        unique: list[WordResult] = []
        for r in results:
            if r.word not in seen_words:
                seen_words.add(r.word)
                unique.append(r)
            if len(unique) >= top_n:
                break
        return unique
