"""DLC word search: path-dependent movement + upper/lower-case word validity.

``ExactSearch`` hands boards with DLC mechanics here (``needs_dlc_search``): wire,
domino and zodiac movement, Strong Signal / Goose / Astronaut / Helicopter moves,
lowercase letters (an uppercase and a lowercase word in one submit), brackets and the
new letter / wildcard items. The DFS carries two trie frontiers (uppercase group,
lowercase group) with a *superset* matcher per tile, so it never prunes a valid path;
every reached candidate is then validated exactly by ``dlc_rules.WordRules`` and
scored with its word groups.

Movement mirrors ``GridUtility.GetValidNextTiles`` (decompiled DLC build): portal,
Full Moon, Strong Signal, Goose, then Sicilian Defense / chess / Zodiac (Astronaut
first) / Wire / Domino / Arrow / adjacent, with ``FilterInvalidDominoEntries`` on
every branch except a domino's own exits (and never from a White tile).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

import numpy as np

from cursed_words_solver.engine import dlc_rules as R
from cursed_words_solver.engine.item_data import ITEMS
from cursed_words_solver.engine.model import (
    DIRECTION_OFFSETS,
    DLC_GLYPHS,
    G_ARROW,
    G_BLANK,
    G_BRACKET,
    G_CHESS,
    G_DICE,
    G_DOMINO,
    G_FRACTION,
    G_ITEM,
    G_NUMBER,
    G_WIRE,
    G_ZODIAC,
    NORMAL,
    SUIT_JOKER,
    WHITE,
    WIRE_CONNECTIONS,
    ZODIAC_DIRECTION,
    ETile,
    zodiac_element,
)

# New (DLC) classes that change movement or word validity: boards with any of these
# (or DLC glyphs / lowercase letters / required tiles) use this search.
DLC_SEARCH_CLASSES = frozenset({
    "StrongSignal", "Goose", "Astronaut", "Helicopter", "Comet", "PowerOfFriendship",
    "PowerOfLove", "Syringe", "MolluscShell", "Coral", "MoonCake", "Bagel", "Chameleon",
    "EvilMonkey", "CremeCaramel", "ShoshinshaMark", "CreepyCrawly", "Handbag",
})
_CARDINALS = ((0, 1), (1, 0), (0, -1), (-1, 0))


def needs_dlc_search(plan) -> bool:
    grid = plan.grid
    for t in grid.available:
        if t.glyph in DLC_GLYPHS or t.is_lowercase_letter() or t.required or t.extra_types:
            return True
        if t.glyph == G_NUMBER and (t.number or 0) <= 0:
            return True
        if t.glyph == G_ITEM and t.item in ITEMS and ITEMS[t.item].cls in DLC_SEARCH_CLASSES:
            return True
    classes = {i.cls for i in plan.inventory_insts_for([])}
    if classes & DLC_SEARCH_CLASSES:
        return True
    if "Microscope" in classes and any(t.value <= 0 for t in grid.available):
        return True
    return False


@dataclass(frozen=True)
class Sel:
    """The TileSelection fields movement reads."""

    idx: int
    direction: tuple[int, int] = (0, 0)  # DirectionFromPreviousTile (game offsets)
    d1: tuple | None = None  # DominoEntryDataPath1: (previous path, flipped)
    d2: tuple | None = None
    prior_flip: bool = False


# ------------------------------------------------------------------ trie frontier


def _np_children(arrays, nodes):
    return R._np_children(arrays, nodes)


def _step(arrays, frontier: dict, wild: bool, texts: list[str], codes: set[str]) -> dict:
    """One tile on a ``match_tiles`` frontier (ldiff -> trie nodes)."""
    nxt: dict[int, list] = {}
    for ldiff, nodes in frontier.items():
        for text in texts:
            walked = R._np_text(arrays, nodes, text) if text else nodes
            if walked.size:
                nxt.setdefault(ldiff, []).append(walked)
            if wild:
                step = _np_children(arrays, nodes)
            else:
                parts = [R._np_letter(arrays, nodes, c) for c in codes]
                parts = [p for p in parts if p.size]
                step = np.concatenate(parts) if parts else None
            if step is not None and step.size:
                nxt.setdefault(ldiff + len(text) - 1, []).append(step)
    out = {}
    for ld, parts in nxt.items():
        arr = parts[0] if len(parts) == 1 else np.unique(np.concatenate(parts))
        if arr.size:
            out[ld] = arr
    return out


def _has_word(arrays, frontier: dict) -> bool:
    nodes = frontier.get(0)
    return nodes is not None and bool(nodes.size) and bool(arrays[4][nodes].any())


_START = {0: np.zeros(1, dtype=np.int32)}


class DlcSearch:
    def __init__(self, es) -> None:
        self.es = es
        plan = es.plan
        self.plan = plan
        self.grid = plan.grid
        self.tiles = self.grid.tiles
        self.min_len = es.min_len
        self.max_len = min(es.max_len, len(self.grid.available))
        self.rules = R.WordRules(plan, es.trie, plan.accumulator_words, es.min_len, es.part_max_len)
        self.rules.max_len = es.max_len
        self.honeypot = es.honeypot
        # Superset inventory: every item plus every scattered item on the board.
        avail = list(self.grid.available)
        items = plan.inventory_insts_for([t for t in avail if t.glyph == G_ITEM])
        self.inv = R.Inventory(items, plan.money, avail, self.grid)
        self.classes = self.inv.classes
        self._match_cache: dict[tuple[int, int], tuple] = {}
        self.required = [t.idx for t in avail if t.required and "DLCHumanBoyUnlock" in plan.challenges]
        self.stats_nodes = 0

    # ------------------------------------------------------------------ superset matcher

    def _matcher(self, t: ETile, i: int) -> tuple[bool, list[str], set[str]]:
        key = (t.idx, i)
        hit = self._match_cache.get(key)
        if hit is not None:
            return hit
        inv = self.inv
        g = t.glyph
        wild = g in (G_BLANK, G_CHESS, G_ARROW, G_ITEM, G_WIRE, G_DICE, G_ZODIAC, G_DOMINO) or t.suit == SUIT_JOKER
        if not wild and g == G_BRACKET:
            wild = True  # wildcard once the submit's brackets are satisfied
        if not wild and inv.evil_monkey and 6 - inv.evil_monkey_level <= i < 6:
            wild = True
        if not wild and inv.number_go_up and t.is_number():
            wild = True
        if not wild:
            wild = any(inv.numeric_wildcard(t, i, n) for n in range(i + 1, self.max_len + 1))
        s = R.word_srep(t)
        texts = [s]
        if s == "q" and inv.queen:
            texts.append("qu")
        codes: set[str] = set()
        if not wild:
            cursed = self.plan.is_cursed_in(t, [])
            saved = inv.shoshinsha
            inv.shoshinsha = False
            codes = inv.letter_codes(t, s, i, True, cursed)
            inv.shoshinsha = saved
            if saved and cursed:
                codes.update(x for x in R.column_letters_below(self.grid, t) if len(x) == 1)
        out = (wild, texts, codes)
        self._match_cache[key] = out
        return out

    # ------------------------------------------------------------------ movement

    def _gxy(self, t: ETile) -> tuple[int, int]:
        return t.x, self.grid.height - 1 - t.y

    def _at(self, gx: int, gy: int, wrap: bool) -> ETile | None:
        w, h = self.grid.width, self.grid.height
        if wrap and w > 0:
            gx %= w
        if not (0 <= gx < w and 0 <= gy < h):
            return None
        t = self.grid.at(gx, h - 1 - gy)
        if t is None or not self.es.clickable[t.idx]:
            return None
        return t

    def _wire_dir(self, cur: ETile, wire: ETile, wrap: bool) -> tuple[int, int]:
        gx, gy = self._gxy(cur)
        for d in _CARDINALS:
            if self._at(gx + d[0], gy + d[1], wrap) is wire:
                return d
        return (0, 0)

    def _viable(self, a: ETile, b: ETile, classes: set[str]) -> bool:
        if a.glyph == G_WIRE or b.glyph == G_WIRE:
            return False
        if "PowerOfFriendship" in classes and a.tile_type != NORMAL and a.tile_type == b.tile_type:
            return True
        if "PowerOfLove" in classes:
            ca = a.curse_types(bool(self.plan.variable_letter(a)))
            cb = b.curse_types(bool(self.plan.variable_letter(b)))
            if ca and cb and set(ca) == set(cb):
                return True
        return a.glyph == b.glyph and a.srep == b.srep

    def moves(self, path: list[int], sels: list[Sel]) -> list[Sel]:
        tiles = self.tiles
        cur = tiles[path[-1]]
        used = set(path)
        path_tiles = [tiles[i] for i in path]
        items = self.plan.inventory_insts_for(path_tiles)
        classes = {i.cls for i in items}
        wrap = "HungrySnake" in classes
        avail = [t for t in self.grid.available if self.es.clickable[t.idx]]
        out: list[Sel] = []
        seen: set[int] = set()

        def add(t: ETile, direction=(0, 0)) -> None:
            if t.idx in used or t.idx in seen:
                return
            seen.add(t.idx)
            out.append(Sel(t.idx, direction))

        if cur.tile_type == WHITE:
            for t in avail:
                add(t)
        if "FullMoon" in classes:
            for t in avail:
                if t.srep == cur.srep and t.glyph == cur.glyph:
                    add(t)
        if "StrongSignal" in classes:
            first = path_tiles[0]
            if first.glyph != G_WIRE and len(path) >= 2 and any(t.glyph == G_WIRE for t in path_tiles):
                for t in avail:
                    if self._viable(first, t, classes):
                        add(t)
        for it in items:
            if it.cls == "Goose" and it.colours:
                for t in avail:
                    if t.is_type(it.colours[0]):
                        add(t)
        es = self.es
        if "SicilianDefense" in self.plan.challenges or cur.glyph in (G_CHESS, G_ARROW):
            legacy = es.inventory_for(tuple(path))
            for j in es.next_tiles(tuple(path), set(path), legacy):
                add(tiles[j])
            return self._filter(cur, out)
        if cur.glyph == G_ZODIAC:
            if "Astronaut" in classes:
                el = zodiac_element(cur.symbol)
                for t in avail:
                    if t.glyph == G_ZODIAC and zodiac_element(t.symbol) == el:
                        add(t)
            el = cur.element()
            offs = DIRECTION_OFFSETS[ZODIAC_DIRECTION[el]] if el else ()
            if "Comet" in {i.cls for i in self.plan.unpacked}:
                offs = offs[1:2]
            gx, gy = self._gxy(cur)
            unpacked_snake = self.plan.hungry_snake
            for d in offs:
                t = self._at(gx + d[0], gy + d[1], unpacked_snake)
                if t is not None and t is not cur and (t.glyph != G_WIRE or d[0] == 0 or d[1] == 0):
                    add(t, d)
            return self._filter(cur, out)
        if cur.glyph == G_WIRE:
            gx, gy = self._gxy(cur)
            dprev = sels[-1].direction
            if dprev == (0, 0):
                dirs = list(_CARDINALS)
            else:
                back = (-dprev[0], -dprev[1])
                dirs = []
                for rot in _rotations(cur.symbol):
                    if back in rot:
                        dirs.extend(d for d in rot if d not in dirs)
            for d in dirs:
                t = self._at(gx + d[0], gy + d[1], wrap)
                if t is not None:
                    add(t, d)
            return self._filter(cur, out)
        if cur.glyph == G_DOMINO:
            cand = [t for t in self.grid.adjacent(cur, False) if es.clickable[t.idx]]
            if "Helicopter" in classes:
                cand += [t for t in self.grid.tiles if t.glyph == G_DOMINO and es.clickable[t.idx]]
            exits = self._domino_exits(cand, sels[-1], used)
            have = {s.idx for s in out}
            return out + [s for s in exits if s.idx not in have]
        for t in self.grid.adjacent(cur, wrap):
            if not es.clickable[t.idx]:
                continue
            if t.glyph == G_WIRE:
                d = self._wire_dir(cur, t, wrap)
                if d == (0, 0):
                    continue
                add(t, d)
            else:
                add(t)
        return self._filter(cur, out)

    def _filter(self, cur: ETile, sels: list[Sel]) -> list[Sel]:
        """``FilterInvalidDominoEntries``."""
        if cur.tile_type == WHITE:
            return sels
        link = cur.domino_link_values()
        out = []
        for s in sels:
            t = self.tiles[s.idx]
            if t.glyph != G_DOMINO:
                out.append(s)
                continue
            a, b = t.domino()
            d1 = (0, False) if (a in link or a == 0) else None
            d2 = (0, True) if a != b and (b in link or b == 0) else None
            if d1 is not None or d2 is not None:
                out.append(Sel(s.idx, s.direction, d1, d2))
        return out

    def _domino_exits(self, cand: list[ETile], last: Sel, used: set[int]) -> list[Sel]:
        """``GetValidDominoExits``."""
        cur = self.tiles[last.idx]
        num = int(cur.value)
        v = list(cur.domino())
        p1, p2 = last.d1, last.d2
        out: list[Sel] = []
        seen: set[int] = set()

        def term(d) -> int:
            return v[0] if d[1] else v[1]

        for t in cand:
            if t.idx in used or t.idx in seen:
                continue
            seen.add(t.idx)
            if t.glyph == G_DOMINO:
                w = list(t.domino())
                num2 = int(t.value)
                e1 = e2 = None
                flag = False
                if p1 is None and p2 is None:
                    if 0 in v:
                        e1, flag = (0, False), True
                    elif w[0] in v:
                        e1, flag = (0, False), True
                    elif num == w[0] and num2 in v:
                        e1, flag = (0, False), True
                    if w[0] != w[1]:
                        if 0 in v or w[1] in v or (num == w[1] and num2 in v):
                            e2, flag = (0, True), True
                else:
                    both = False
                    if p1 is not None:
                        n3 = term(p1)
                        if n3 == 0:
                            e1, e2, flag, both = (1, False), (1, True), True, True
                        elif n3 == w[0]:
                            e1, flag = (1, False), True
                        elif n3 == w[1]:
                            e2, flag = (1, True), True
                    if not both and p2 is not None:
                        n4 = term(p2)
                        if n4 == 0:
                            e1, e2, flag, both = (2, False), (2, True), True, True
                        elif e1 is None and n4 == w[0]:
                            e1, flag = (2, False), True
                        elif e2 is None and n4 == w[1]:
                            e2, flag = (2, True), True
                    if not both and e1 is None and num == w[0]:
                        if p1 is not None:
                            if term(p1) == num2:
                                e1, flag = (1, False), True
                        elif p2 is not None and term(p2) == num2:
                            e1, flag = (2, False), True
                    elif not both and e2 is None and num == w[1]:
                        if p1 is not None:
                            if term(p1) == num2:
                                e2, flag = (1, True), True
                        elif p2 is not None and term(p2) == num2:
                            e2, flag = (2, True), True
                if 0 in w:
                    f3 = w[0] != 0
                    if e1 is None and e2 is None:
                        e1, flag = (0, f3), True
                    elif e1 is None:
                        if (w[1] if e2[1] else w[0]) != 0:
                            e1, flag = (0, f3), True
                    elif e2 is None and (w[1] if e1[1] else w[0]) != 0:
                        e2, flag = (0, f3), True
                if flag:
                    out.append(Sel(t.idx, (0, 0), e1, e2))
                continue
            link = t.domino_link_values()
            if p1 is None and p2 is None:
                if 0 in v:
                    out.append(Sel(t.idx, prior_flip=v[1] != 0))
                elif v[1] in link:
                    out.append(Sel(t.idx))
                elif v[0] in link:
                    out.append(Sel(t.idx, prior_flip=True))
                continue
            if p1 is not None:
                n9 = term(p1)
                if n9 == 0 or n9 in link:
                    out.append(Sel(t.idx))
                    continue
            if p2 is not None:
                n10 = term(p2)
                if n10 == 0 or n10 in link:
                    out.append(Sel(t.idx))
        return out

    # ------------------------------------------------------------------ DFS

    def enumerate(self, trie_arrays, deadline: float | None, cancel_check, node_budget: int,
                  starts=None) -> tuple[dict[tuple[int, ...], None], bool]:
        tiles = self.tiles
        es = self.es
        found: dict[tuple[int, ...], None] = {}
        allowed = es.allowed_tile
        max_len = self.max_len
        lo = self.min_len
        nodes = 0
        exhaustive = True
        start_idx = [t.idx for t in self.grid.available if allowed[t.idx] and es.clickable[t.idx]]
        if starts is not None:
            keep = set(starts)
            start_idx = [i for i in start_idx if i in keep]

        def lens_ok(nu: int, nl: int) -> bool:
            return (nu == 0 or lo <= nu <= max_len) and (nl == 0 or lo <= nl <= max_len)

        stack: list[tuple] = []
        for s in start_idx:
            t = tiles[s]
            stack.append(([s], [Sel(s)], _START, _START, 0, 0))
        while stack:
            path, sels, fu, fl, nu, nl = stack.pop()
            t = tiles[path[-1]]
            i = len(path) - 1
            wild, texts, codes = self._matcher(t, i)
            if t.is_lowercase_letter():
                fl = _step(trie_arrays, fl, wild, texts, codes)
                nl += 1
                if not fl:
                    continue
            else:
                fu = _step(trie_arrays, fu, wild, texts, codes)
                nu += 1
                if not fu:
                    continue
            nodes += 1
            if nodes > node_budget or (deadline is not None and nodes % 256 == 0 and time.perf_counter() > deadline):
                exhaustive = False
                break
            if cancel_check is not None and nodes % 1024 == 0 and cancel_check():
                exhaustive = False
                break
            if lens_ok(nu, nl) and (nu == 0 or _has_word(trie_arrays, fu)) and (nl == 0 or _has_word(trie_arrays, fl)):
                found[tuple(path)] = None
            if len(path) >= max_len * 2 or nu >= max_len and nl >= max_len:
                continue
            for s in self.moves(path, sels):
                if not allowed[s.idx]:
                    continue
                stack.append((path + [s.idx], sels + [s], fu, fl, nu, nl))
        self.stats_nodes += nodes
        return found, exhaustive

    def validate(self, path: tuple[int, ...]) -> R.Submitted | None:
        if self.required and any(r not in path for r in self.required):
            return None
        if self.honeypot:
            return self.rules.concatenated(list(path), self.es.part_max_len)
        return self.rules.upper_lower(list(path))

    def run(self, *, top_n: int, deadline: float | None, cancel_check, rank, starts=None):
        from cursed_words_solver.engine.search import Candidate, _numpy_trie

        es = self.es
        t0 = time.perf_counter()
        self.stats_nodes = 0
        budget = es.exhaustive_node_budget
        enum_deadline = None
        if deadline is not None:
            enum_deadline = t0 + max(0.0, deadline - t0) * 0.7
        found, exhaustive = self.enumerate(_numpy_trie(es.trie), enum_deadline, cancel_check, budget, starts)
        if self.rules.acc_trie is not None:
            more, ex2 = self.enumerate(_numpy_trie(self.rules.acc_trie), enum_deadline, cancel_check, budget, starts)
            found.update(more)
            exhaustive = exhaustive and ex2
        t1 = time.perf_counter()
        es.stats.enum_sec = t1 - t0
        es.stats.nodes = self.stats_nodes
        es.stats.paths = len(found)
        es.stats.extra["exhaustive"] = exhaustive
        es.stats.extra["dlc_search"] = True
        es.stats.timed_out = not exhaustive
        values = [t.value for t in self.tiles]
        order = sorted(found, key=lambda p: (sum(values[i] for i in p), len(p)), reverse=True)
        if len(order) > es.max_exact_paths:
            order = order[: es.max_exact_paths]
        scored = []
        plan = self.plan
        es.last_found = {}
        for n, p in enumerate(order, 1):
            if deadline is not None and n > es.min_scored_before_deadline and n % 32 == 0 and time.perf_counter() > deadline:
                break
            sub = self.validate(p)
            if sub is None or not es.path_allowed(p):
                continue
            text = sub.text()
            es.last_found[p] = text
            res = plan.score(list(p), text, words=sub.all_words(), groups=sub.all_groups())
            scored.append(Candidate(p, text, res.score, res.nondeterministic))
        es.stats.valid_paths = len(scored)
        key = rank or (lambda s: s)
        scored.sort(key=lambda c: key(c.score), reverse=True)
        es.stats.score_sec = time.perf_counter() - t1
        return scored[:top_n] if top_n else scored


def _rotations(symbol: str) -> list[list[tuple[int, int]]]:
    base = WIRE_CONNECTIONS.get(symbol, ())
    out = []
    for k in range(4):
        rot = []
        for d in base:
            x, y = d
            for _ in range(k):
                x, y = -y, x
            rot.append((x, y))
        out.append(rot)
    return out
