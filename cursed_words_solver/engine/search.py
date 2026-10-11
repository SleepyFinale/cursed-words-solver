"""Exact word search: enumerate every path the game accepts, score each exactly.

Movement is ``GridUtility.GetValidNextTiles`` (white-tile portals, Full Moon,
chess moves incl. en passant and king-safety, arrows, Hungry Snake wrap, Sicilian
Defense knight moves); word validity is ``Vocabulary.GetValidWordFromTiles``
(wildcards, numeric wildcards by position, item letter substitutions, Queenie's
"qu"). The DFS walks the dictionary trie with a superset matcher; every complete
path is then checked with the exact validity rules (path-dependent inventory) and
scored by ``EnginePlan``. Scores depend on the path, not the matched spelling, so
each path is scored once.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from cursed_words_solver.engine import packet as P
from cursed_words_solver.engine.calc import EnginePlan, _extra_int
from cursed_words_solver.engine.item_data import ITEMS
from cursed_words_solver.engine.model import (
    CURRENCY_MAP_LOWER,
    G_ARROW,
    G_BLANK,
    G_CARD,
    G_CHESS,
    G_CURRENCY,
    G_FRACTION,
    G_ITEM,
    G_LETTER,
    G_NUMBER,
    LETTERS,
    NORMAL,
    SUIT_JOKER,
    WHITE,
    ETile,
)
from cursed_words_solver.engine.trie import CsrTrie

ALL = None  # matcher sentinel: tile matches any letter

# Michael's finale submits ``Vocabulary.GetRandomTwentyFiveLetterWord()``; scoring
# only reads the word for Michael's Book, which never asks for a 25-letter word.
FINALE_WORD = "?" * 25

_ARROW_DIRS = {
    "↑": (0, 1), "→": (1, 0), "↓": (0, -1), "←": (-1, 0),
    "↖": (-1, 1), "↗": (1, 1), "↘": (1, -1), "↙": (-1, -1),
}

# Item classes whose presence changes movement or letter matching.
_MOVE_CLASSES = frozenset({"FullMoon", "HungrySnake", "KingOfTheBridge", "Television"})
_LETTER_CLASSES = frozenset({
    "RedEnvelope", "SpicyPepper", "Automobile", "SluggishZombie", "Jellyfish",
    "CardShark", "NumbersBunchOfGrapes", "Queen", "NumberGoUp", "TestTube",
    "Flamingo", "Microscope",
})


@dataclass
class Candidate:
    path: tuple[int, ...]
    word: str
    score: int | float
    nondeterministic: bool = False


@dataclass
class SearchStats:
    nodes: int = 0
    paths: int = 0
    valid_paths: int = 0
    enum_sec: float = 0.0
    score_sec: float = 0.0
    timed_out: bool = False
    unsupported: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


class _Inventory:
    """``InventoryCache`` + movement flags for a set of item classes."""

    def __init__(self, plan: EnginePlan, extra_classes: frozenset[str]) -> None:
        exact = plan.inventory_classes is not None
        classes = set(plan.inventory_classes if exact else plan.item_classes) | set(extra_classes)
        self.classes = classes
        colours = {k: list(v) for k, v in ((plan.inventory_colours or {}) if exact else plan.colour_lists).items()}
        for cls in extra_classes:
            slug = _CLASS_SLUG.get(cls)
            if slug and cls in ("Flamingo", "RedEnvelope", "SpicyPepper", "Automobile"):
                colours.setdefault(cls, []).extend(ITEMS[slug].colours)
        self.colours = colours
        self.hungry_snake = "HungrySnake" in classes
        self.full_moon = "FullMoon" in classes
        self.king_of_bridge = "KingOfTheBridge" in classes
        self.television = "Television" in classes
        self.queen = "Queen" in classes
        self.number_go_up = "NumberGoUp" in classes
        self.test_tube = "TestTube" in classes
        self.microscope = "Microscope" in classes
        flamingo = colours.get("Flamingo") or []
        self.flamingo_first = flamingo[0] if "Flamingo" in classes and flamingo else None


_CLASS_SLUG = {info.cls: slug for slug, info in ITEMS.items()}


def _word_string(t: ETile) -> str:
    """``GetStringRepresentation(forWordValidity: true)``."""
    g = t.glyph
    if g == G_CARD and t.suit == SUIT_JOKER:
        return "!"
    if g == G_LETTER:
        return t.letter
    if g == G_CURRENCY:
        return t.symbol.lower()
    if g == G_ARROW:
        return t.letter
    if g == G_BLANK:
        return "?"
    return "!"


def _numpy_trie(trie: CsrTrie) -> tuple:
    """numpy views of the CSR trie + sorted edge keys (parent * 32 + letter).

    Cached on the trie itself: an ``id()``-keyed cache hands a new trie the arrays
    of a freed one that had the same id.
    """
    import numpy as np

    cached = getattr(trie, "_np", None)
    if cached is not None:
        return cached
    starts = np.frombuffer(trie.starts, dtype=np.int32).astype(np.int64)
    counts = np.frombuffer(trie.counts, dtype=np.int32).astype(np.int64)
    childs = np.frombuffer(trie.childs, dtype=np.int32)
    chars = np.frombuffer(trie.chars, dtype=np.uint8).astype(np.int64)
    parents = np.repeat(np.arange(len(starts), dtype=np.int64), counts)
    edge_keys = parents * 32 + (chars - 97)
    is_word = np.frombuffer(trie.is_word, dtype=np.uint8).astype(bool)
    parent = np.zeros(len(starts), dtype=np.int32)
    letter = np.zeros(len(starts), dtype=np.uint8)
    parent[childs] = parents.astype(np.int32)
    letter[childs] = chars.astype(np.uint8)
    arrays = (starts, counts, childs, edge_keys, is_word, parent, letter)
    trie._np = arrays
    return arrays


def _np_advance(arrays, nodes, wild: bool, codes: bytes, tokens: tuple[str, ...]):
    """Trie nodes reachable from ``nodes`` through one tile (numpy, deduped)."""
    import numpy as np

    starts_np, counts_np, childs_np, edge_keys = arrays[0], arrays[1], arrays[2], arrays[3]
    if not len(edge_keys):
        return None  # empty dictionary

    def step_letter(ns, code: int):
        keys = ns.astype(np.int64) * 32 + (code - 97)
        pos = np.searchsorted(edge_keys, keys)
        pos = np.minimum(pos, len(edge_keys) - 1)
        hit = edge_keys[pos] == keys
        return childs_np[pos[hit]]

    parts = []
    if wild:
        cnt = counts_np[nodes]
        total = int(cnt.sum())
        if total:
            st = starts_np[nodes]
            offs = np.repeat(st - np.concatenate(([0], np.cumsum(cnt)[:-1])), cnt)
            parts.append(childs_np[np.arange(total) + offs])
    else:
        for c in codes:
            r = step_letter(nodes, c)
            if r.size:
                parts.append(r)
    for tok in tokens:
        r = nodes
        for ch in tok:
            r = step_letter(r, ord(ch))
            if not r.size:
                break
        if r.size:
            parts.append(r)
    if not parts:
        return None
    out = parts[0] if len(parts) == 1 else np.concatenate(parts)
    if tokens and out.size > 1:
        # Children of distinct trie nodes are distinct, so letter steps never
        # duplicate; a multi-letter token ("qu") can land on a node another
        # member reaches by a letter.
        out = np.unique(out)
    return out


def _np_spell(arrays, node: int) -> str:
    """The prefix a trie node stands for (parent pointers)."""
    parent, letter = arrays[5], arrays[6]
    out: list[str] = []
    while node:
        out.append(chr(letter[node]))
        node = int(parent[node])
    return "".join(reversed(out))


class ExactSearch:
    """Enumerate + score all valid words on one board for one loadout."""

    def __init__(self, plan: EnginePlan, trie: CsrTrie) -> None:
        self.plan = plan
        self.trie = trie
        grid = plan.grid
        self.grid = grid
        self.tiles = grid.tiles
        self.clickable = [
            not t.in_void and not t.crossed_out and not (t.glyph == G_LETTER and not t.letter)
            for t in grid.tiles
        ]
        # Every scattered item on the board could join the inventory mid-path.
        board_item_classes = frozenset(
            ITEMS[t.item].cls for t in grid.available if t.glyph == G_ITEM and t.item in ITEMS
        )
        self.base_inv = _Inventory(plan, frozenset())
        self.super_inv = _Inventory(plan, board_item_classes & (_MOVE_CLASSES | _LETTER_CLASSES))
        self._inv_cache: dict[frozenset[str], _Inventory] = {frozenset(): self.base_inv}
        self._move_cache: dict[tuple, list[int]] = {}
        extras = plan.extras
        self.min_len = max(1, _extra_int(extras, "encounter_min_word_length") or _extra_int(extras, "cobra_min_length") or 1)
        self.max_len = _extra_int(extras, "wolf_max_length") or 999
        # Honeypot checks each of the two words against the boss length limits.
        self.part_max_len = self.max_len
        self.max_len = min(self.max_len, len(grid.available))
        self.honeypot = "Honeypot" in (plan.inventory_classes if plan.inventory_classes is not None else plan.item_classes)
        # Item accumulator words (Bar Chart numbers, Microphone item names, ...).
        self.acc_trie = CsrTrie.from_words(plan.accumulator_words) if plan.accumulator_words else None
        self.challenge = plan.challenge
        # Michael's 25-tile finale grid: validity is "all wildcards", not the dictionary.
        self.finale = str(extras.get("michael_summoned_bosses_defeated") or "").lower() == "true"
        self.up_and_up_center = _extra_int(extras, "up_and_up_center_index")
        self.stats = SearchStats()
        # Tiles a word may never contain under the active challenge (static prune).
        ch = self.challenge
        allowed = []
        for t in grid.tiles:
            ok = self.clickable[t.idx]
            if ch == "Chromaphobia" and t.tile_type != NORMAL:
                ok = False
            elif ch == "Chromaphilia" and t.tile_type == NORMAL:
                ok = False
            elif ch == "Cursophobia" and plan.is_cursed(t):
                ok = False
            allowed.append(ok)
        self.allowed_tile = allowed
        self._available_allowed = sorted((t.idx for t in grid.available if allowed[t.idx]), key=lambda j: -grid.tiles[j].value)

    # ------------------------------------------------------------------ inventory

    def inventory_for(self, path: tuple[int, ...]) -> _Inventory:
        classes = frozenset(
            ITEMS[self.tiles[i].item].cls
            for i in path
            if self.tiles[i].glyph == G_ITEM and self.tiles[i].item in ITEMS
        ) & (_MOVE_CLASSES | _LETTER_CLASSES)
        inv = self._inv_cache.get(classes)
        if inv is None:
            inv = _Inventory(self.plan, classes)
            self._inv_cache[classes] = inv
        return inv

    # ------------------------------------------------------------------ movement

    def move_tables(self, inv: _Inventory) -> tuple[list[bool], list[list[int]], list[list[int]], list[bool]]:
        """Per tile: (portal?, Full Moon group, primary moves, primary-is-chess?).

        ``GetValidNextTiles`` = portal targets + Full Moon targets, then the chess /
        arrow / adjacent targets not already listed. (The decompiled chess branch
        reads ``Exists(t => t.SelectedTile == t.SelectedTile)`` -- ILSpy reused one
        name for two lambda variables; the game de-duplicates, and real captures
        play chess moves after Full Moon targets.)
        """
        cached = getattr(inv, "_tables", None)
        if cached is not None:
            return cached
        tiles = self.tiles
        n = len(tiles)
        portal = [False] * n
        moon: list[list[int]] = [[] for _ in range(n)]
        primary: list[list[int]] = [[] for _ in range(n)]
        is_chess = [False] * n
        groups: dict[tuple[str, str], list[int]] = {}
        if inv.full_moon:
            for t in self.grid.available:
                groups.setdefault((t.srep, t.glyph), []).append(t.idx)
        for t in self.grid.available:
            i = t.idx
            portal[i] = t.tile_type == WHITE
            if inv.full_moon:
                moon[i] = [j for j in groups[(t.srep, t.glyph)] if j != i and self.clickable[j]]
            if self.challenge == "SicilianDefense":
                lst = list(self._knight_moves(t, inv, sicilian=True))
                if inv.television and t.glyph == G_CHESS and t.piece in ("king", "pawn"):
                    lst += [a.idx for a in self.grid.available if a.glyph == G_ITEM]
            elif t.glyph == G_CHESS:
                lst = list(self._chess_moves(t, inv))
                is_chess[i] = True
            elif t.glyph == G_ARROW:
                lst = self._arrow_targets(t, inv)
            else:
                lst = [a.idx for a in self.grid.adjacent(t, inv.hungry_snake)]
            by_value = lambda j: -tiles[j].value  # noqa: E731
            primary[i] = sorted((j for j in dict.fromkeys(lst) if j != i and self.clickable[j] and self.allowed_tile[j]), key=by_value)
            moon[i] = sorted((j for j in moon[i] if self.allowed_tile[j]), key=by_value)
        tables = (portal, moon, primary, is_chess)
        inv._tables = tables
        return tables

    def next_tiles(self, path: tuple[int, ...] | list[int], visited: set[int] | int, inv: _Inventory) -> list[int]:
        """``GetValidNextTiles`` targets from the last tile (excluding used tiles)."""
        cur = self.tiles[path[-1]]
        out: list[int] = []
        seen: set[int] = set()

        def used(i: int) -> bool:
            return (visited >> i) & 1 if isinstance(visited, int) else i in visited

        def add(i: int) -> None:
            if i not in seen and self.clickable[i] and not used(i):
                seen.add(i)
                out.append(i)

        if cur.tile_type == WHITE:
            for t in self.grid.available:
                add(t.idx)
        if inv.full_moon:
            rep = cur.srep
            for t in self.grid.available:
                if t.srep == rep and t.glyph == cur.glyph:
                    add(t.idx)
        if self.challenge == "SicilianDefense":
            for i in self._knight_moves(cur, inv, sicilian=True):
                add(i)
            if inv.television and cur.glyph == G_CHESS and cur.piece in ("king", "pawn"):
                for t in self.grid.available:
                    if t.glyph == G_ITEM:
                        add(t.idx)
            return out
        if cur.glyph == G_CHESS:
            for i in self._chess_moves(cur, inv):
                add(i)
            return out
        if cur.glyph == G_ARROW:
            for i in self._arrow_targets(cur, inv):
                add(i)
            return out
        for t in self.grid.adjacent(cur, inv.hungry_snake):
            add(t.idx)
        return out

    def _gy(self, t: ETile) -> int:
        return self.grid.height - 1 - t.y

    def _at_game(self, x: int, gy: int) -> ETile | None:
        if not (0 <= x < self.grid.width and 0 <= gy < self.grid.height):
            return None
        return self.grid.at(x, self.grid.height - 1 - gy)

    def _chess_moves(self, t: ETile, inv: _Inventory, *, checking: bool = False, board_override: dict | None = None) -> list[int]:
        key = (t.idx, inv.hungry_snake, inv.king_of_bridge, inv.television, checking, id(board_override) if board_override else 0)
        cached = self._move_cache.get(key)
        if cached is not None:
            return cached
        piece = t.piece
        if piece == "pawn":
            res = self._pawn_moves(t, inv, checking, board_override)
        elif piece == "knight":
            res = self._knight_moves(t, inv, checking=checking, board_override=board_override)
        elif piece in ("bishop", "rook", "queen"):
            dirs = []
            if piece in ("bishop", "queen"):
                dirs += [(1, 1), (-1, 1), (1, -1), (-1, -1)]
            if piece in ("rook", "queen"):
                dirs += [(0, 1), (1, 0), (0, -1), (-1, 0)]
            res = self._slide_moves(t, dirs, inv, checking, board_override)
        elif piece == "king":
            res = self._king_moves(t, inv, checking, board_override)
        else:
            res = []
        if board_override is None:
            self._move_cache[key] = res
        return res

    def _tile_at(self, x: int, gy: int, board_override: dict | None) -> ETile | None:
        t = self._at_game(x, gy)
        if t is not None and board_override is not None and t.idx in board_override:
            return board_override[t.idx]
        return t

    def _pawn_moves(self, t: ETile, inv: _Inventory, checking: bool, board_override: dict | None) -> list[int]:
        w, h = self.grid.width, self.grid.height
        x, gy = t.x, self._gy(t)
        first_rank = (t.white and gy == 1) or (not t.white and gy == h - 2)
        ep_rank = (t.white and gy == h - 4) or (not t.white and gy == 3)
        dy = 1 if t.white else -1
        out: list[int] = []
        fwd = self._tile_at(x, gy + dy, board_override)
        if fwd is not None and fwd.glyph != G_CHESS and not checking:
            out.append(fwd.idx)
            if first_rank:
                fwd2 = self._tile_at(x, gy + 2 * dy, board_override)
                if fwd2 is not None and fwd2.glyph != G_CHESS:
                    out.append(fwd2.idx)
        for dx in (1, -1):
            nx = x + dx if t.white else x - dx
            ny = gy + dy
            if inv.hungry_snake:
                nx %= w
            target = self._tile_at(nx, ny, board_override)
            if target is None:
                continue
            behind = self._tile_at(nx, ny - dy, board_override)
            capture = target.glyph == G_CHESS and (target.white != t.white or inv.king_of_bridge)
            ep = (
                ep_rank
                and behind is not None
                and behind.glyph == G_CHESS
                and behind.piece == "pawn"
                and behind.white != t.white
                and target.glyph != G_CHESS
                and not checking
            )
            if capture or ep or checking:
                out.append(target.idx)
        if inv.television:
            for a in self.grid.available:
                if a.glyph == G_ITEM and a.idx not in out:
                    out.append(a.idx)
        return out

    def _knight_moves(self, t: ETile, inv: _Inventory, *, sicilian: bool = False, checking: bool = False, board_override: dict | None = None) -> list[int]:
        w = self.grid.width
        x, gy = t.x, self._gy(t)
        out: list[int] = []
        for dx, dy in ((1, 2), (-1, 2), (1, -2), (-1, -2), (2, 1), (-2, 1), (2, -1), (-2, -1)):
            nx, ny = x + dx, gy + dy
            if inv.hungry_snake:
                nx = (nx + w) % w
            target = self._tile_at(nx, ny, board_override)
            if target is None:
                continue
            is_chess = target.glyph == G_CHESS
            if not is_chess or t.glyph != G_CHESS or target.white != t.white or inv.king_of_bridge or checking:
                out.append(target.idx)
        if sicilian and t.glyph == G_CHESS and t.piece == "king" and not checking:
            threats = self._sicilian_threats(t, inv)
            out = [i for i in out if i not in threats]
        return out

    def _sicilian_threats(self, king: ETile, inv: _Inventory) -> set[int]:
        blank = ETile(idx=king.idx, x=king.x, y=king.y, tile_type=NORMAL, glyph=G_BLANK)
        override = {king.idx: blank}
        threats: set[int] = set()
        for t in self.grid.tiles:
            if t.glyph == G_CHESS and t.white != king.white and not t.in_void:
                # checking=True: a defended piece is threatened too (as in _checkmate_positions).
                threats.update(self._knight_moves(t, inv, checking=True, board_override=override))
        return threats

    def _slide_moves(self, t: ETile, dirs, inv: _Inventory, checking: bool, board_override: dict | None) -> list[int]:
        w = self.grid.width
        out: list[int] = []
        seen: set[int] = set()
        for dx, dy in dirs:
            x, gy = t.x, self._gy(t)
            for _ in range(100):
                x += dx
                gy += dy
                if inv.hungry_snake:
                    x = (x + w) % w
                if x == t.x and gy == self._gy(t):
                    break
                target = self._tile_at(x, gy, board_override)
                if target is None:
                    break
                if target.glyph == G_CHESS:
                    if target.white != t.white or inv.king_of_bridge or checking:
                        if target.idx not in seen:
                            seen.add(target.idx)
                            out.append(target.idx)
                    break
                if target.idx not in seen:
                    seen.add(target.idx)
                    out.append(target.idx)
        return out

    def _king_moves(self, t: ETile, inv: _Inventory, checking: bool, board_override: dict | None) -> list[int]:
        adj = [a for a in self.grid.adjacent(t, inv.hungry_snake)]
        if board_override:
            adj = [board_override.get(a.idx, a) for a in adj]
        if checking:
            out = [a.idx for a in adj]
            if inv.television:
                out += [a.idx for a in self.grid.available if a.glyph == G_ITEM and a.idx not in out]
            return out
        mate = self._checkmate_positions(t, inv, friendly=False)
        out = [
            a.idx
            for a in adj
            if (a.glyph != G_CHESS or a.white != t.white or inv.king_of_bridge) and a.idx not in mate
        ]
        if inv.king_of_bridge:
            friendly = self._checkmate_positions(t, inv, friendly=True)
            out = [i for i in out if i not in friendly]
        if inv.television:
            out += [a.idx for a in self.grid.available if a.glyph == G_ITEM and a.idx not in out]
        return out

    def _checkmate_positions(self, king: ETile, inv: _Inventory, *, friendly: bool) -> set[int]:
        blank = ETile(idx=king.idx, x=king.x, y=king.y, tile_type=NORMAL, glyph=G_BLANK)
        override = {king.idx: blank}
        out: set[int] = set()
        for t in self.grid.tiles:
            if t.in_void or t.glyph != G_CHESS or t is king:
                continue
            if friendly != (t.white == king.white):
                continue
            out.update(self._chess_moves(t, inv, checking=True, board_override=override))
        return out

    def _arrow_targets(self, t: ETile, inv: _Inventory) -> list[int]:
        d = _ARROW_DIRS.get(t.letter) or _ARROW_DIRS.get(t.symbol)
        if d is None:
            return []
        w, h = self.grid.width, self.grid.height
        out: list[int] = []
        x, gy = t.x + d[0], self._gy(t) + d[1]
        for _ in range(max(w, h)):
            target = self._at_game(x, gy)
            if target is not None and target.in_void:
                target = None
            if target is not None and target is not t and target.idx not in out:
                out.append(target.idx)
            if inv.hungry_snake and target is None:
                x = (x + w) % w
                t2 = self._at_game(x, gy)
                if t2 is not None and not t2.in_void and t2 is not t and t2.idx not in out:
                    out.append(t2.idx)
            x += d[0]
            gy += d[1]
        return out

    # ------------------------------------------------------------------ letters

    def _matcher(self, t: ETile, index: int, inv: _Inventory, path_numbers_ascending: bool | None) -> tuple[bool, bytes, tuple[str, ...]]:
        """(wildcard?, single-letter codes, multi-letter tokens) for tile at index."""
        if self._is_wildcard(t, index, inv, path_numbers_ascending):
            return True, b"", ()
        s = _word_string(t)
        letters: set[str] = set()
        tokens: list[str] = []
        if len(s) == 1:
            letters.add(s)
        if s == "q" and inv.queen:
            tokens.append("qu")
        if "RedEnvelope" in inv.classes and any(t.is_type(c) for c in inv.colours.get("RedEnvelope", ())):
            letters.add("e")
        if "SpicyPepper" in inv.classes and any(t.is_type(c) for c in inv.colours.get("SpicyPepper", ())):
            letters.add("s")
        if "Automobile" in inv.classes and t.glyph == G_LETTER and any(t.is_type(c) for c in inv.colours.get("Automobile", ())) and s in LETTERS:
            k = LETTERS.index(s)
            letters.update(LETTERS[j] for j in range(max(0, k - 1), min(26, k + 2)))
        if "SluggishZombie" in inv.classes and s == "z":
            letters.add("s")
        if "Jellyfish" in inv.classes and s == "j":
            letters.update("yh")
        if "CardShark" in inv.classes:
            letter = {"clubs": "c", "spades": "s", "diamonds": "d", "hearts": "h"}.get(t.suit)
            if letter:
                letters.add(letter)
        if t.glyph == G_CURRENCY:
            mapped = CURRENCY_MAP_LOWER.get(s)
            if mapped:
                letters.add(mapped)
        if "NumbersBunchOfGrapes" in inv.classes and t.glyph == G_NUMBER:
            letters.update({1: "i", 5: "v", 10: "x"}.get(t.number, ""))
        letters = {c for c in letters if "a" <= c <= "z"}
        return False, bytes(sorted(ord(c) for c in letters)), tuple(tokens)

    def _is_wildcard(self, t: ETile, index: int, inv: _Inventory, numbers_ascending: bool | None) -> bool:
        if t.glyph in (G_BLANK, G_CHESS, G_ARROW, G_ITEM) or t.suit == SUIT_JOKER:
            return True
        if inv.number_go_up and t.is_number():
            if numbers_ascending is None or numbers_ascending:
                return True
        allowed = {index + 1}
        if inv.test_tube:
            allowed.update((index, index + 2))
        if t.glyph == G_NUMBER and t.number in allowed:
            return True
        if t.glyph == G_FRACTION and t.fraction and (t.fraction[0] in allowed or t.fraction[1] in allowed):
            return True
        if inv.flamingo_first is not None and t.is_type(inv.flamingo_first) and index == 0:
            return True
        if inv.microscope and t.value == index + 1:
            return True
        return False

    # ------------------------------------------------------------------ validity

    def valid_word(self, path: tuple[int, ...]) -> str | None:
        """Exact ``GetValidWordFromTiles`` for a full path (None if invalid).

        With Honeypot, ``GetConcatenatedValidWordsFromTiles``: the whole path as one
        word, else the first split (shortest first word) into two valid words,
        returned space-separated.
        """
        if self.finale:
            return FINALE_WORD if self.finale_valid(path) else None
        inv = self.inventory_for(path)
        if self.acc_trie is not None:
            # TryGetAccumulatorWordFromTiles runs before the dictionary.
            acc = self._part_word(path, inv, self.min_len, self.max_len, self.acc_trie)
            if acc is not None:
                return acc
        word = self._part_word(path, inv, self.min_len, self.max_len)
        if word is not None or not self.honeypot:
            return word
        for k in range(1, len(path)):
            first = self._part_word(path[:k], inv, self.min_len, self.part_max_len)
            if first is None:
                continue
            second = self._part_word(path[k:], inv, self.min_len, self.part_max_len)
            if second is not None:
                return f"{first} {second}"
        return None

    def _part_word(self, path: tuple[int, ...], inv: _Inventory, min_len: int, max_len: int, trie: CsrTrie | None = None) -> str | None:
        """One ``GetValidWordFromTiles`` call on ``path`` (inventory from the whole submit).

        Steps the set of trie nodes consistent with each tile and spells the first
        word node reached.
        """
        import numpy as np

        n = len(path)
        if n < min_len or n > max_len:
            return None
        tiles = [self.tiles[i] for i in path]
        nums = [t.number_float() for t in tiles if t.is_number()]
        ascending = all(nums[i] > nums[i - 1] for i in range(1, len(nums)))
        arrays = _numpy_trie(trie or self.trie)
        nodes = np.zeros(1, dtype=np.int32)
        for i, t in enumerate(tiles):
            wild, codes, tokens = self._matcher(t, i, inv, ascending)
            nodes = _np_advance(arrays, nodes, wild, codes, tokens)
            if nodes is None or not nodes.size:
                return None
        words = nodes[arrays[4][nodes]]
        if not words.size:
            return None
        return _np_spell(arrays, int(words.min()))

    def path_allowed(self, path: tuple[int, ...]) -> bool:
        """Challenge / boss word restrictions (TileSelectionManager.PopulateValidityAndScore)."""
        ch = self.challenge
        if ch == "UpAndUp" and self.up_and_up_center is not None and self.up_and_up_center not in path:
            return False
        tiles = [self.tiles[i] for i in path]
        if ch == "Chromaphobia" and any(t.tile_type != NORMAL for t in tiles):
            return False
        if ch == "Chromaphilia" and any(t.tile_type == NORMAL for t in tiles):
            return False
        if ch == "Cursophobia" and any(self.plan.is_cursed(t) for t in tiles):
            return False
        return True

    # ------------------------------------------------------------------ search

    def enumerate(
        self,
        deadline: float | None = None,
        cancel_check: Callable[[], bool] | None = None,
        *,
        inv: _Inventory | None = None,
        require_pickup: frozenset[int] = frozenset(),
        starts: list[int] | None = None,
        node_budget: int | None = None,
    ) -> dict[tuple[int, ...], str]:
        """All valid paths -> one matching spelling (superset matcher; see ``run``).

        Paths start on ``starts`` (default: every allowed tile). Exhaustive unless
        ``node_budget`` DFS nodes are exceeded (wildcard / chess-dense boards);
        ``stats.extra["exhaustive"]`` reports it.
        """
        start_tiles = self._available_allowed if starts is None else starts
        trie = self.trie
        starts, counts, chars, childs, is_word = trie.starts, trie.counts, trie.chars, trie.childs, trie.is_word
        inv = inv or self.base_inv
        pickup_mask = sum(1 << i for i in require_pickup)
        tiles = self.tiles
        max_len = self.max_len
        min_len = self.min_len
        match_cache: dict[tuple[int, int, bool], tuple[bool, bytes, tuple[str, ...]]] = {}
        # Number Go Up: numbers are wildcards only while the numbers so far ascend.
        ngu = inv.number_go_up
        num_value = [t.number_float() if t.is_number() else None for t in tiles]

        def matcher(i: int, d: int, ascending: bool = True):
            key = (i, d, ascending)
            m = match_cache.get(key)
            if m is None:
                m = self._matcher(tiles[i], d, inv, ascending if ngu else None)
                match_cache[key] = m
            return m

        found: dict[tuple[int, ...], str] = {}
        path: list[int] = []
        letters: list[str] = []
        stats = self.stats
        check_every = 4096
        counter = [0]
        stopped = [False]
        budget = [self.exhaustive_node_budget if node_budget is None else node_budget]
        dynamic_inv = bool(self.super_inv.classes - self.base_inv.classes)
        all_allowed = self._available_allowed
        base_tables = self.move_tables(self.base_inv)

        def moves(idx: int, visited: int) -> list[int]:
            if dynamic_inv:
                portal, moon, primary, is_chess = self.move_tables(self.inventory_for(tuple(path)))
            else:
                portal, moon, primary, is_chess = base_tables
            out = [j for j in all_allowed if not (visited >> j) & 1] if portal[idx] else []
            for j in moon[idx]:
                if not (visited >> j) & 1 and j not in out:
                    out.append(j)
            if out:
                for j in primary[idx]:
                    if not (visited >> j) & 1 and j not in out:
                        out.append(j)
                return out
            return [j for j in primary[idx] if not (visited >> j) & 1]

        # Honeypot: a word may be two dictionary words; the second restarts at the
        # trie root, and its positional wildcards / Number Go Up run count from 0.
        honeypot = self.honeypot
        part_max = self.part_max_len
        total_max = len(self.grid.available) if honeypot else max_len

        def dfs(idx: int, node: int, depth: int, visited: int, last_num: float | None = None, asc: bool = True, part_start: int = 0) -> None:
            stats.nodes += 1
            counter[0] += 1
            if counter[0] >= check_every:
                counter[0] = 0
                if (deadline is not None and time.perf_counter() > deadline) or (cancel_check is not None and cancel_check()):
                    stopped[0] = True
            budget[0] -= 1
            if stopped[0] or budget[0] < 0:
                return
            length = depth + 1
            part_len = length - part_start
            word_end = is_word[node] and part_len >= min_len
            if word_end and (not pickup_mask or visited & pickup_mask):
                key = tuple(path)
                prev = found.get(key)
                if prev is None or (" " in prev and not part_start):
                    found[key] = "".join(letters)
            if length >= total_max:
                return
            if part_len < (part_max if part_start else max_len):
                expand(idx, node, length, visited, last_num, asc, part_start)
            if honeypot and not part_start and word_end and part_len <= part_max:
                letters.append(" ")
                expand(idx, 0, length, visited, None, True, length)
                letters.pop()

        def expand(idx: int, node: int, length: int, visited: int, last_num, asc: bool, part_start: int) -> None:
            pos = length - part_start
            for nxt in moves(idx, visited):
                nv = num_value[nxt]
                n_last, n_asc = last_num, asc
                if nv is not None:
                    n_asc = asc and (last_num is None or nv > last_num)
                    n_last = nv
                wild, codes, tokens = matcher(nxt, pos, n_asc)
                path.append(nxt)
                vis2 = visited | (1 << nxt)
                for tok in tokens:
                    child = trie.walk(node, tok)
                    if child >= 0:
                        letters.append(tok)
                        dfs(nxt, child, length, vis2, n_last, n_asc, part_start)
                        letters.pop()
                s = starts[node]
                e = s + counts[node]
                if wild:
                    for k in range(s, e):
                        letters.append(chr(chars[k]))
                        dfs(nxt, childs[k], length, vis2, n_last, n_asc, part_start)
                        letters.pop()
                else:
                    for c in codes:
                        k = chars.find(c, s, e)
                        if k >= 0:
                            letters.append(chr(c))
                            dfs(nxt, childs[k], length, vis2, n_last, n_asc, part_start)
                            letters.pop()
                path.pop()
                if stopped[0] or budget[0] < 0:
                    return

        for i in start_tiles:
            wild, codes, tokens = matcher(i, 0)
            path.append(i)
            vis = 1 << i
            n0 = num_value[i]
            for tok in tokens:
                child = trie.walk(0, tok)
                if child >= 0:
                    letters.append(tok)
                    dfs(i, child, 0, vis, n0)
                    letters.pop()
            if wild:
                for k in range(starts[0], starts[0] + counts[0]):
                    letters.append(chr(chars[k]))
                    dfs(i, childs[k], 0, vis, n0)
                    letters.pop()
            else:
                for c in codes:
                    child = trie.child(0, c)
                    if child >= 0:
                        letters.append(chr(c))
                        dfs(i, child, 0, vis, n0)
                        letters.pop()
            path.pop()
            if stopped[0] or budget[0] < 0:
                break
        exhaustive = not stopped[0] and budget[0] >= 0
        stats.extra["exhaustive"] = exhaustive
        stats.timed_out = not exhaustive
        stats.paths = len(found)
        return found

    def enumerate_subsets(
        self,
        deadline: float | None = None,
        cancel_check: Callable[[], bool] | None = None,
        *,
        inv: _Inventory | None = None,
        require_pickup: frozenset[int] = frozenset(),
        starts: list[int] | None = None,
        path_budget: int | None = None,
    ) -> tuple[dict[tuple[int, ...], str], bool]:
        """Tier 2: DFS over tile paths carrying numpy arrays of trie nodes.

        Wildcards cost one vectorised child expansion instead of 26 recursive
        branches, so wildcard-heavy boards whose *tile* paths are still limited
        (Number Go Up tours, a few jokers) finish exhaustively. Runs until the
        deadline (``subset_path_budget`` tile paths when there is none) and
        returns ``(found, complete)``; partial results are kept.
        """
        import numpy as np

        arrays = _numpy_trie(self.trie)
        is_word_np = arrays[4]
        inv = inv or self.base_inv
        pickup_mask = sum(1 << i for i in require_pickup)
        tiles = self.tiles
        max_len = self.max_len
        min_len = self.min_len
        ngu = inv.number_go_up
        num_value = [t.number_float() if t.is_number() else None for t in tiles]
        match_cache: dict[tuple[int, int, bool], tuple[bool, bytes, tuple[str, ...]]] = {}

        def matcher(i: int, d: int, ascending: bool):
            key = (i, d, ascending)
            m = match_cache.get(key)
            if m is None:
                m = self._matcher(tiles[i], d, inv, ascending if ngu else None)
                match_cache[key] = m
            return m

        def advance(nodes, i: int, d: int, asc: bool):
            wild, codes, tokens = matcher(i, d, asc)
            return _np_advance(arrays, nodes, wild, codes, tokens)

        found: dict[tuple[int, ...], str] = {}
        path: list[int] = []
        if path_budget is None:
            path_budget = self.subset_path_budget if deadline is None else 1 << 62
        budget = [path_budget]
        stopped = [False]
        counter = [0]
        dynamic_inv = bool(self.super_inv.classes - self.base_inv.classes)
        all_allowed = self._available_allowed
        base_tables = self.move_tables(self.base_inv)

        def moves(idx: int, visited: int) -> list[int]:
            if dynamic_inv:
                portal, moon, primary, is_chess = self.move_tables(self.inventory_for(tuple(path)))
            else:
                portal, moon, primary, is_chess = base_tables
            out = [j for j in all_allowed if not (visited >> j) & 1] if portal[idx] else []
            for j in moon[idx]:
                if not (visited >> j) & 1 and j not in out:
                    out.append(j)
            if out:
                for j in primary[idx]:
                    if not (visited >> j) & 1 and j not in out:
                        out.append(j)
                return out
            return [j for j in primary[idx] if not (visited >> j) & 1]

        def dfs(idx: int, nodes, depth: int, visited: int, last_num, asc: bool) -> None:
            budget[0] -= 1
            counter[0] += 1
            if counter[0] >= 512:
                counter[0] = 0
                if (deadline is not None and time.perf_counter() > deadline) or (cancel_check is not None and cancel_check()):
                    stopped[0] = True
            if budget[0] < 0 or stopped[0]:
                return
            length = depth + 1
            if length >= min_len and (not pickup_mask or visited & pickup_mask):
                words = nodes[is_word_np[nodes]]
                if words.size:
                    found.setdefault(tuple(path), _np_spell(arrays, int(words.min())))
            if length >= max_len:
                return
            for nxt in moves(idx, visited):
                nv = num_value[nxt]
                n_last, n_asc = last_num, asc
                if nv is not None:
                    n_asc = asc and (last_num is None or nv > last_num)
                    n_last = nv
                nn = advance(nodes, nxt, length, n_asc)
                if nn is None or not nn.size:
                    continue
                path.append(nxt)
                dfs(nxt, nn, length, visited | (1 << nxt), n_last, n_asc)
                path.pop()
                if budget[0] < 0 or stopped[0]:
                    return

        root = np.zeros(1, dtype=np.int32)
        for i in all_allowed if starts is None else starts:
            nodes = advance(root, i, 0, True)
            if nodes is None or not nodes.size:
                continue
            path.append(i)
            dfs(i, nodes, 0, 1 << i, num_value[i], True)
            path.pop()
            if budget[0] < 0 or stopped[0]:
                break
        visited_paths = path_budget - budget[0]
        self.stats.extra["subset_paths_visited"] = self.stats.extra.get("subset_paths_visited", 0) + visited_paths
        return found, not (budget[0] < 0 or stopped[0])

    # ------------------------------------------------------------------ Michael's finale

    finale_length = 25
    # Complete finale tours collected before scoring (all tiles, so scores differ little).
    max_finale_paths = 20_000

    def _path_moves(self, idx: int, visited: int, path: list[int]) -> list[int]:
        """``GetValidNextTiles`` from ``idx`` (precomputed tables, path-dependent inventory)."""
        portal, moon, primary, is_chess = self.move_tables(self.inventory_for(tuple(path)))
        out = [j for j in self._available_allowed if not (visited >> j) & 1] if portal[idx] else []
        for j in moon[idx]:
            if not (visited >> j) & 1 and j not in out:
                out.append(j)
        if out:
            for j in primary[idx]:
                if not (visited >> j) & 1 and j not in out:
                    out.append(j)
            return out
        return [j for j in primary[idx] if not (visited >> j) & 1]

    def finale_valid(self, path: tuple[int, ...]) -> bool:
        """``PopulateValidityAndScore`` on Michael's finale grid: 25 tiles, every one a
        wildcard at its position (the game then submits a random 25-letter word)."""
        if len(path) < self.finale_length:
            return False
        inv = self.inventory_for(path)
        tiles = [self.tiles[i] for i in path]
        nums = [t.number_float() for t in tiles if t.is_number()]
        ascending = all(nums[i] > nums[i - 1] for i in range(1, len(nums)))
        return all(self._is_wildcard(t, i, inv, ascending) for i, t in enumerate(tiles))

    def enumerate_finale(
        self,
        deadline: float | None = None,
        cancel_check: Callable[[], bool] | None = None,
        *,
        starts: list[int] | None = None,
        node_budget: int | None = None,
    ) -> tuple[dict[tuple[int, ...], str], bool]:
        """Every 25-tile tour of all-wildcard positions (up to ``max_finale_paths``).

        Numbers / fractions / Microscope tiles are wildcards only at fixed positions,
        so each tile gets the latest depth it may still be placed at; a branch dies
        as soon as one unvisited tile can no longer be placed.
        """
        target = self.finale_length
        inv = self.super_inv
        tiles = self.tiles
        n = len(tiles)
        allowed_at: list[int] = [0] * n  # bitmask of depths
        for t in self.grid.available:
            if not self.allowed_tile[t.idx]:
                continue
            mask = 0
            for d in range(target):
                if self._is_wildcard(t, d, inv, None):
                    mask |= 1 << d
            allowed_at[t.idx] = mask
        cands = [i for i in self._available_allowed if allowed_at[i]]
        if len(cands) < target:
            return {}, True
        # must_by[d]: tiles whose last allowed depth is <= d (must be placed by then).
        latest = {i: allowed_at[i].bit_length() - 1 for i in cands}
        must_by = [0] * target
        for i, last in latest.items():
            for d in range(last, target):
                must_by[d] |= 1 << i
        found: dict[tuple[int, ...], str] = {}
        path: list[int] = []
        budget = [self.exhaustive_node_budget * 10 if node_budget is None else node_budget]
        stopped = [False]
        counter = [0]
        cap = self.max_finale_paths

        def dfs(idx: int, depth: int, visited: int) -> None:
            budget[0] -= 1
            counter[0] += 1
            if counter[0] >= 2048:
                counter[0] = 0
                if (deadline is not None and time.perf_counter() > deadline) or (cancel_check is not None and cancel_check()):
                    stopped[0] = True
            if budget[0] < 0 or stopped[0]:
                return
            if must_by[depth] & ~visited:
                return
            if depth + 1 == target:
                found[tuple(path)] = ""
                if len(found) >= cap:
                    stopped[0] = True
                return
            nd = depth + 1
            for nxt in self._path_moves(idx, visited, path):
                if not (allowed_at[nxt] >> nd) & 1:
                    continue
                path.append(nxt)
                dfs(nxt, nd, visited | (1 << nxt))
                path.pop()
                if budget[0] < 0 or stopped[0]:
                    return

        for i in cands if starts is None else [s for s in starts if allowed_at[s] & 1]:
            if not allowed_at[i] & 1:
                continue
            path.append(i)
            dfs(i, 0, 1 << i)
            path.pop()
            if budget[0] < 0 or stopped[0]:
                break
        complete = not (budget[0] < 0 or stopped[0]) or len(found) >= cap
        exact = {p: w for p, w in found.items() if self.finale_valid(p)}
        self.stats.extra["finale_tours"] = len(exact)
        return exact, complete

    def _enumerate_tiers(self, deadline, cancel_check, inv, require_pickup, starts=None) -> tuple[dict[tuple[int, ...], str], bool]:
        """Per start tile: letter DFS, then the vectorised subset tier if it overflowed.

        Each start gets a fair share of the time left (unused time rolls over to
        later starts), so an explosive start tile cannot starve the rest of the
        board; partial results from a start that runs out of time are kept.
        """
        order = list(self._available_allowed if starts is None else starts)
        found: dict[tuple[int, ...], str] = {}
        exhaustive = True
        per_start_nodes = max(self.min_start_node_budget, self.exhaustive_node_budget // max(1, len(order)))
        # Without a deadline the subset tier's overall path budget is shared out too.
        per_start_paths = None if deadline is not None else max(
            self.min_start_node_budget, self.subset_path_budget // max(1, len(order))
        )
        for k, start in enumerate(order):
            if cancel_check is not None and cancel_check():
                return found, False
            now = time.perf_counter()
            if deadline is not None and now >= deadline:
                return found, False
            slice_end = None if deadline is None else now + (deadline - now) / (len(order) - k)
            part = self.enumerate(
                slice_end, cancel_check, inv=inv, require_pickup=require_pickup,
                starts=[start], node_budget=per_start_nodes,
            )
            if not self.stats.extra.get("exhaustive", True):
                sub, complete = self.enumerate_subsets(
                    slice_end, cancel_check, inv=inv, require_pickup=require_pickup, starts=[start],
                    path_budget=per_start_paths,
                )
                for p, w in sub.items():
                    if not part.get(p):
                        part[p] = w
                self.stats.extra["tier"] = "subset"
                exhaustive = exhaustive and complete
            for p, w in part.items():
                if not found.get(p):
                    found[p] = w
        return found, exhaustive

    def _enumerate_all(self, deadline, cancel_check, starts=None) -> tuple[dict[tuple[int, ...], str], set[tuple[int, ...]]]:
        """Pass A: exact base inventory (always valid). Pass B: inventory widened by
        board scattered items, keeping only paths that pick one up (checked later).
        Extra items only ever add matches, so A + checked B is exactly the valid set.
        """
        if self.finale:
            found, exhaustive = self.enumerate_finale(deadline, cancel_check, starts=starts)
            found = dict.fromkeys(found, FINALE_WORD)
            self.stats.extra["exhaustive"] = exhaustive
            self.stats.timed_out = not exhaustive
            self.stats.paths = len(found)
            return found, set()
        two_pass = self.super_inv.classes != self.base_inv.classes
        deadline_a = deadline
        if two_pass and deadline is not None:
            now = time.perf_counter()
            deadline_a = now + 0.6 * max(0.0, deadline - now)
        found, exhaustive = self._enumerate_tiers(deadline_a, cancel_check, self.base_inv, frozenset(), starts)
        needs_check: set[tuple[int, ...]] = set()
        if two_pass:
            pickups = frozenset(
                t.idx for t in self.grid.available
                if t.glyph == G_ITEM and t.item in ITEMS and ITEMS[t.item].cls in (_MOVE_CLASSES | _LETTER_CLASSES)
            )
            extra, ex_b = self._enumerate_tiers(deadline, cancel_check, self.super_inv, pickups, starts)
            for p, w in extra.items():
                if p not in found:
                    found[p] = w
                    needs_check.add(p)
            exhaustive = exhaustive and ex_b
        if self.acc_trie is not None:
            # Accumulator words: same DFS over their tiny trie (no Honeypot splits:
            # GetConcatenatedValidWordsFromTiles clears them before splitting).
            saved, honeypot = self.trie, self.honeypot
            self.trie, self.honeypot = self.acc_trie, False
            try:
                acc = self.enumerate(deadline, cancel_check, inv=self.super_inv, starts=starts)
            finally:
                self.trie, self.honeypot = saved, honeypot
            for p in acc:
                found[p] = ""  # valid_word: accumulator word first, else dictionary
                needs_check.add(p)
        if self.honeypot:
            needs_check.update(p for p, w in found.items() if " " in w)
        if self.super_inv.number_go_up:
            # Number Go Up wildcards were granted while the prefix ascended; the game
            # checks the whole path, so any path that stops ascending is re-checked.
            values = [t.number_float() if t.is_number() else None for t in self.tiles]
            for p in found:
                nums = [values[i] for i in p if values[i] is not None]
                if any(nums[k] <= nums[k - 1] for k in range(1, len(nums))):
                    needs_check.add(p)
        self.stats.extra["exhaustive"] = exhaustive
        self.stats.timed_out = not exhaustive
        self.stats.paths = len(found)
        return found, needs_check

    # Tile-path DFS nodes allowed for the vectorised subset tier.
    subset_path_budget = 400_000
    max_exact_paths = 25000
    # Node budget for the plain exhaustive pass; explosive boards then fall back
    # to widening per-(trie node, tile) expansion caps.
    exhaustive_node_budget = 400_000
    # Floor for each start tile's share of ``exhaustive_node_budget``.
    min_start_node_budget = 20_000
    # Time held back from enumeration to score up to ``max_exact_paths`` paths.
    score_reserve_sec = 2.0

    def _shortlist(self, items: list[tuple[tuple[int, ...], str]]) -> list[tuple[tuple[int, ...], str]]:
        """Too many paths to score exactly: keep the best by tile-value proxy.

        Keeps the top paths overall plus each distinct word's best path so a
        high-multiplier short word is never starved by long high-base paths.
        """
        values = [t.value for t in self.tiles]

        def proxy(p: tuple[int, ...]) -> tuple[int, int]:
            return (sum(values[i] for i in p), len(p))

        ranked = sorted(items, key=lambda kv: proxy(kv[0]), reverse=True)
        keep: dict[tuple[int, ...], str] = dict(ranked[: self.max_exact_paths // 2])
        best_per_word: dict[str, tuple[int, ...]] = {}
        for p, w in ranked:
            if w not in best_per_word:
                best_per_word[w] = p
        for w, p in best_per_word.items():
            if len(keep) >= self.max_exact_paths:
                break
            keep.setdefault(p, w)
        return list(keep.items())

    # ------------------------------------------------------------------ beam

    # Beam passes widen from ``beam_start_width`` (x2 per pass) until the deadline.
    beam_start_width = 64
    beam_max_width = 2048
    # Width of the single beam pass when there is no deadline (deterministic tests).
    beam_fixed_width = 256
    # Share of a deadline-bound search given to enumeration before the beam may run.
    enum_share_before_beam = 0.55

    def beam_search(
        self,
        deadline: float | None = None,
        cancel_check: Callable[[], bool] | None = None,
        *,
        rank: Callable[[int | float], float] | None = None,
        starts: list[int] | None = None,
        width: int | None = None,
    ) -> dict[tuple[int, ...], Candidate]:
        """Score-guided beam over tile paths for boards too dense to enumerate.

        Each depth extends every kept path by one legal move (``GetValidNextTiles``)
        whose letters still lead somewhere in the trie, scores the extensions
        exactly (``EnginePlan.score``) and keeps the ``width`` best by ``rank``.
        Every extension that spells a word is recorded. With a deadline the beam
        restarts twice as wide while time remains; without one it runs a single
        ``beam_fixed_width`` pass. Returns path -> scored candidate.
        """
        import numpy as np

        key = rank or (lambda s: s)
        found: dict[tuple[int, ...], Candidate] = {}
        if self.finale:
            return found
        arrays = _numpy_trie(self.trie)
        is_word = arrays[4]
        inv = self.super_inv
        # A path that picks up a letter / movement item, or Number Go Up, needs the
        # exact (path-dependent) validity check; otherwise the node set is exact.
        pickup = {
            t.idx for t in self.grid.available
            if t.glyph == G_ITEM and t.item in ITEMS and ITEMS[t.item].cls in (_MOVE_CLASSES | _LETTER_CLASSES)
        }
        loose = bool(self.super_inv.number_go_up)
        start_tiles = list(self._available_allowed if starts is None else starts)
        plan = self.plan
        word_scored = "MichaelsBook" in plan.item_classes
        widths = [width or self.beam_fixed_width] if deadline is None else []
        w = self.beam_start_width
        while deadline is not None and w <= self.beam_max_width:
            widths.append(w)
            w *= 2

        def out_of_time() -> bool:
            return (deadline is not None and time.perf_counter() > deadline) or (
                cancel_check is not None and cancel_check()
            )

        def record(path: tuple[int, ...], nodes, res) -> None:
            if path in found or len(path) < self.min_len or not is_word[nodes].any():
                return
            if loose or pickup.intersection(path):
                word = self.valid_word(path)
            else:
                word = _np_spell(arrays, int(nodes[is_word[nodes]].min()))
            if word and self.path_allowed(path):
                if word_scored:
                    res = plan.score(list(path), word)  # Michael's Book reads the word
                found[path] = Candidate(path, word, res.score, res.nondeterministic)

        root = np.zeros(1, dtype=np.int32)
        for width_now in widths:
            # Node sets shared between beam states at one depth (wildcard chains
            # make many identical); cleared per depth to bound memory.
            beam: list[tuple[float, tuple[int, ...], Any]] = []
            for s in start_tiles:
                nodes = _np_advance(arrays, root, *self._matcher(self.tiles[s], 0, inv, True))
                if nodes is None or not nodes.size:
                    continue
                res = plan.score([s], "")
                beam.append((key(P.to_int(res.score)), (s,), nodes))
                record((s,), nodes, res)
            seen: set[tuple[int, ...]] = set()
            stopped = False
            for depth in range(1, self.max_len):
                interned: dict[tuple, Any] = {}
                memo: dict[tuple, Any] = {}
                nxt: list[tuple[float, tuple[int, ...], Any]] = []
                for _, path, nodes in beam:
                    if out_of_time():
                        stopped = True
                        break
                    visited = 0
                    for i in path:
                        visited |= 1 << i
                    nid = id(nodes)
                    for j in self._path_moves(path[-1], visited, list(path)):
                        q = path + (j,)
                        if q in seen:
                            continue
                        seen.add(q)
                        m = self._matcher(self.tiles[j], depth, inv, True)
                        mk = (nid, m)
                        nn = memo.get(mk, False)
                        if nn is False:
                            nn = _np_advance(arrays, nodes, *m)
                            if nn is not None and nn.size:
                                ik = (nn.size, int(nn[0]), int(nn[-1]), hash(nn.tobytes()))
                                nn = interned.setdefault(ik, nn)
                            else:
                                nn = None
                            memo[mk] = nn
                        if nn is None:
                            continue
                        res = plan.score(list(q), "")
                        nxt.append((key(P.to_int(res.score)), q, nn))
                        record(q, nn, res)
                if stopped or not nxt:
                    break
                nxt.sort(key=lambda e: e[0], reverse=True)
                beam = nxt[:width_now]
            self.stats.extra["beam_width"] = width_now
            if stopped:
                break
        self.stats.extra["beam_found"] = len(found)
        return found

    def run(
        self,
        *,
        top_n: int = 3,
        deadline: float | None = None,
        cancel_check: Callable[[], bool] | None = None,
        rank: Callable[[int | float], float] | None = None,
        starts: list[int] | None = None,
    ) -> list[Candidate]:
        """Enumerate, validate exactly, score every path; return the best ``top_n``.

        ``starts`` restricts paths to those start tiles (parallel workers split
        the board this way). With a deadline, enumeration stops early enough to
        score what it found. If enumeration cannot finish (wildcard / chess-dense
        boards), a score-guided beam (``beam_search``) uses the remaining time and
        its exactly scored finds join the results.
        """
        t0 = time.perf_counter()
        enum_deadline = deadline
        if deadline is not None:
            budget = max(0.0, deadline - t0)
            enum_deadline = t0 + budget * self.enum_share_before_beam
        found, needs_check = self._enumerate_all(enum_deadline, cancel_check, starts)
        beam_found: dict[tuple[int, ...], Candidate] = {}
        if not self.stats.extra.get("exhaustive", True) and not (cancel_check is not None and cancel_check()):
            enum_exhaustive = False
            beam_deadline = None
            if deadline is not None:
                left = max(0.0, deadline - time.perf_counter())
                beam_deadline = deadline - min(self.score_reserve_sec, 0.3 * left)
            tb = time.perf_counter()
            beam_found = self.beam_search(beam_deadline, cancel_check, rank=rank, starts=starts)
            self.stats.extra["beam_sec"] = round(time.perf_counter() - tb, 3)
            self.stats.extra["exhaustive"] = enum_exhaustive
            self.stats.timed_out = True
        self.last_found = found
        t1 = time.perf_counter()
        self.stats.enum_sec = t1 - t0
        plan = self.plan
        scored: list[Candidate] = []
        # Paths that went through a scattered item were matched with the superset
        # inventory; check those exactly. Everything else is already exact.
        for p in needs_check:
            exact = self.valid_word(p)
            if exact is None:
                found.pop(p, None)
            else:
                found[p] = exact
        items = list(found.items())
        core = len(items)
        if len(items) > self.max_exact_paths:
            short = self._shortlist(items)
            core = len(short)
            if deadline is not None:
                # Score the shortlist, then keep going down the proxy order until the deadline.
                kept = set(p for p, _ in short)
                values = [t.value for t in self.tiles]
                rest = sorted(
                    ((p, w) for p, w in items if p not in kept),
                    key=lambda kv: (sum(values[i] for i in kv[0]), len(kv[0])),
                    reverse=True,
                )
                items = short + rest
            else:
                items = short
        n_scored = 0
        for n_scored, (p, word) in enumerate(items, 1):
            if n_scored > core and n_scored % 512 == 0 and time.perf_counter() > deadline:
                break
            if not word:
                word = self.valid_word(p) or ""
                if not word:
                    continue
            if not self.path_allowed(p):
                continue
            res = plan.score(list(p), word)
            scored.append(Candidate(p, word, res.score, res.nondeterministic))
        if n_scored < len(items):
            self.stats.extra["shortlisted"] = n_scored
        if beam_found:
            have = {c.path for c in scored}
            scored.extend(c for path, c in beam_found.items() if path not in have)
        self.stats.valid_paths = len(scored)
        key = rank or (lambda s: s)
        scored.sort(key=lambda c: key(c.score), reverse=True)
        self.stats.score_sec = time.perf_counter() - t1
        return scored[:top_n] if top_n else scored
