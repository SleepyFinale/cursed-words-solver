"""Engine movement and word rules for callers that inspect paths (not search).

``BoardPaths`` wraps one board + loadout: ``GetValidNextTiles`` movement, the
exact ``Vocabulary`` matcher (every dictionary word a path can spell) and a
display spelling. Cursedle and the F8 suggestion gates use it instead of
re-deriving the game's rules.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Iterator

from cursed_words_solver.engine.calc import EnginePlan
from cursed_words_solver.engine.model import CURRENCY_MAP_LOWER, G_CURRENCY, G_FRACTION, G_LETTER, G_NUMBER
from cursed_words_solver.engine.search import ExactSearch, _np_advance, _np_spell, _numpy_trie, _word_string
from cursed_words_solver.engine.trie import CsrTrie
from cursed_words_solver.models import Board, Loadout

_EMPTY_TRIE = CsrTrie.from_words(())
_CACHE: OrderedDict[tuple, "BoardPaths"] = OrderedDict()
_CACHE_SIZE = 8


class BoardPaths:
    """Movement / spelling for one board and loadout (no dictionary needed)."""

    def __init__(self, board: Board, loadout: Loadout | None = None) -> None:
        self.board = board
        self.loadout = loadout or Loadout(money=board.money)
        self.plan = EnginePlan.build(board, self.loadout)
        self.search = ExactSearch(self.plan, _EMPTY_TRIE)

    @classmethod
    def for_board(cls, board: Board, loadout: Loadout | None = None) -> "BoardPaths":
        """Cached per (board, loadout) object identity + board fingerprint."""
        from cursed_words_solver.fingerprints import board_fingerprint

        key = (id(board), id(loadout), board_fingerprint(board))
        hit = _CACHE.get(key)
        if hit is not None and hit.board is board:
            _CACHE.move_to_end(key)
            return hit
        inst = cls(board, loadout)
        _CACHE[key] = inst
        while len(_CACHE) > _CACHE_SIZE:
            _CACHE.popitem(last=False)
        return inst

    # ------------------------------------------------------------------ movement

    def next_tiles(self, path: list[int] | tuple[int, ...]) -> list[int]:
        """Tiles the game lets you select after ``path`` (storage indices)."""
        if not path:
            return list(self.search._available_allowed)
        prefix = tuple(path)
        return self.search.next_tiles(prefix, set(prefix), self.search.inventory_for(prefix))

    def moves_ok(self, path: list[int] | tuple[int, ...]) -> bool:
        """Every step follows ``GetValidNextTiles`` and no tile repeats."""
        n = len(self.search.tiles)
        if not path or any(not (0 <= i < n) or not self.search.clickable[i] for i in path):
            return False
        if len(set(path)) != len(path):
            return False
        return all(path[k + 1] in self.next_tiles(path[: k + 1]) for k in range(len(path) - 1))

    def walk(
        self,
        min_len: int,
        max_len: int,
        *,
        prefix: list[int] | None = None,
        starts: list[int] | None = None,
    ) -> Iterator[list[int]]:
        """Every legal path with ``min_len <= len <= max_len`` (optionally extending ``prefix``)."""
        search = self.search

        def rec(path: list[int], visited: int) -> Iterator[list[int]]:
            if len(path) >= min_len:
                yield list(path)
            if len(path) >= max_len:
                return
            for j in search._path_moves(path[-1], visited, path):
                path.append(j)
                yield from rec(path, visited | (1 << j))
                path.pop()

        if prefix:
            if not self.moves_ok(prefix):
                return
            yield from rec(list(prefix), sum(1 << i for i in prefix))
            return
        for s in search._available_allowed if starts is None else starts:
            yield from rec([s], 1 << s)

    # ------------------------------------------------------------------ words

    def words(self, path: list[int] | tuple[int, ...], trie: CsrTrie, *, limit: int = 256) -> list[str]:
        """Dictionary words the game's matcher accepts on ``path`` (alphabetical, up to ``limit``)."""
        import numpy as np

        search = self.search
        path = tuple(path)
        if not path:
            return []
        inv = search.inventory_for(path)
        tiles = [search.tiles[i] for i in path]
        nums = [t.number_float() for t in tiles if t.is_number()]
        ascending = all(nums[i] > nums[i - 1] for i in range(1, len(nums)))
        arrays = _numpy_trie(trie)
        nodes = np.zeros(1, dtype=np.int32)
        for i, t in enumerate(tiles):
            wild, codes, tokens = search._matcher(t, i, inv, ascending)
            nodes = _np_advance(arrays, nodes, wild, codes, tokens)
            if nodes is None or not nodes.size:
                return []
        hits = nodes[arrays[4][nodes]]
        return sorted(_np_spell(arrays, int(n)) for n in hits[:limit])

    def wildcard_count(self, path: list[int] | tuple[int, ...]) -> int:
        """Tiles on ``path`` that match any letter at their position."""
        search = self.search
        path = tuple(path)
        inv = search.inventory_for(path)
        tiles = [search.tiles[i] for i in path]
        nums = [t.number_float() for t in tiles if t.is_number()]
        ascending = all(nums[i] > nums[i - 1] for i in range(1, len(nums)))
        return sum(1 for i, t in enumerate(tiles) if search._is_wildcard(t, i, inv, ascending))

    def spell(self, path: list[int] | tuple[int, ...]) -> str:
        """Face spelling: letters as shown, ``?`` for wildcards, ``qu`` for Queenie's Q.

        Non-wildcard numbers / fractions keep their digits so the result is never
        mistaken for a dictionary word.
        """
        search = self.search
        path = tuple(path)
        inv = search.inventory_for(path)
        tiles = [search.tiles[i] for i in path]
        nums = [t.number_float() for t in tiles if t.is_number()]
        ascending = all(nums[i] > nums[i - 1] for i in range(1, len(nums)))
        out: list[str] = []
        for i, t in enumerate(tiles):
            if search._is_wildcard(t, i, inv, ascending):
                out.append("?")
                continue
            s = _word_string(t)
            if t.glyph == G_LETTER and s == "q" and inv.queen:
                out.append("qu")
            elif t.glyph == G_CURRENCY:
                out.append(CURRENCY_MAP_LOWER.get(s, s))
            elif t.glyph == G_NUMBER:
                out.append(str(t.number))
            elif t.glyph == G_FRACTION:
                a, b = t.fraction or (0, 0)
                out.append(f"{a}/{b}")
            else:
                out.append(s)
        return "".join(out)


def clear_cache() -> None:
    _CACHE.clear()
