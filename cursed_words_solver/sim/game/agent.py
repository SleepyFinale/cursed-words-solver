"""Agent interface over ``Game``: actions, legal-action enumeration, cloning, word candidates.

``Action`` is a small tagged record so policies (heuristic, search, learned) and the
training loop share one vocabulary. ``Candidates`` wraps the exact engine search so
every policy sees the same top-K words for a grid.
"""

from __future__ import annotations

import copy
import os
import pickle
import threading
from dataclasses import dataclass, field
from typing import Any, Iterable

from cursed_words_solver.sim.game.bridge import board_and_loadout, index_to_coords
from cursed_words_solver.sim.game.run import Game


@dataclass(frozen=True)
class Action:
    kind: str
    args: tuple = ()
    label: str = ""

    def __str__(self) -> str:  # pragma: no cover
        return self.label or f"{self.kind}{self.args}"


@dataclass
class WordOption:
    word: str
    words: list[str]
    path: list[tuple[int, int]]
    score: int  # progress toward the target (Two Wrongs: the negated engine score, as SubmitResult)
    placements: list[tuple[int, int, int]] = field(default_factory=list)  # (rack_idx, x, y)
    raw: int | None = None  # engine score when it differs from ``score`` (Two Wrongs)
    grants_item: str | None = None  # Microphone: the item class this word's name adds
    money: int | None = None  # money_words: what the word earns in-grid (it does not clear)


_BULLSEYE_EXACT_SCALE = 4

# Engine search limits scaled by ``Candidates.effort`` (deterministic, load-independent).
_EFFORT_ATTRS = {
    "subset_path_budget": 1, "exhaustive_node_budget": 1, "min_start_node_budget": 1,
    "max_exact_paths": 2000, "beam_fixed_width": 32,
}


class Candidates:
    """Top-K engine words for the current grid (cached per grid state).

    ``effort`` (0–1] switches to a deterministic search: the engine's node / path / beam
    limits scaled by ``effort`` and no deadline, so results do not depend on machine load
    (0.05 ≈ 0.25 s per grid and beats a 0.6 s deadline). Otherwise ``time_budget`` seconds.
    ``cheap_floor`` also scales the exact-scoring floor down with effort (about 2x faster
    runs, slightly weaker play): meant for play-outs and long benchmarks, not live advice.
    """

    def __init__(self, wordlist=None, time_budget: float = 8.0, *, dictionary=None,
                 effort: float | None = None, cheap_floor: bool = False) -> None:
        from cursed_words_solver.config import resolve_wordlist
        from cursed_words_solver.dictionary import WordDictionary
        from cursed_words_solver.search import WordSearcher

        self.wordlist = wordlist or resolve_wordlist(None)
        self.dictionary = dictionary or WordDictionary(self.wordlist)
        self.effort = effort
        self.cheap_floor = cheap_floor
        self.searcher = WordSearcher(self.dictionary, time_budget=0 if effort else time_budget)

    def with_budget(self, time_budget: float) -> "Candidates":
        """Same dictionary, different search deadline (fast probes). In effort mode the
        effort shrinks in proportion instead (a 0.6 s budget keeps it unchanged)."""
        if self.effort:
            return self.with_effort(max(0.01, self.effort * min(1.0, time_budget / 0.6)))
        return Candidates(self.wordlist, time_budget, dictionary=self.dictionary)

    def with_effort(self, effort: float, cheap_floor: bool | None = None) -> "Candidates":
        """Same dictionary, deterministic search at ``effort`` (floor mode kept unless given)."""
        return Candidates(self.wordlist, dictionary=self.dictionary, effort=effort,
                          cheap_floor=self.cheap_floor if cheap_floor is None else cheap_floor)

    def _find(self, board, loadout, top_n: int):
        return self._search(board, loadout, top_n, None)

    def _search(self, board, loadout, top_n: int, searcher=None):
        """``_find`` with another searcher (Microphone item names); ``None`` = the dictionary."""
        if searcher is None:
            searcher = self.searcher
        if not self.effort:
            return searcher.find_best_words(board, loadout, top_n=top_n)
        from cursed_words_solver.engine.search import ExactSearch

        saved = {k: getattr(ExactSearch, k) for k in _EFFORT_ATTRS}
        # Bullseye wants an exact hit, often a low-value path of a word the value shortlist
        # already holds once: score more paths exactly.
        bullseye = str((loadout.extras or {}).get("challenge_game_class") or "") == "Bullseye"
        try:
            for k, floor in _EFFORT_ATTRS.items():
                scale = 2 * self.effort if k == "beam_fixed_width" else self.effort
                if k == "max_exact_paths" and self.cheap_floor:  # exact scoring dominates cheap searches
                    floor = max(500, int(floor * min(1.0, self.effort / 0.05)))
                value = max(floor, int(saved[k] * scale))
                if k == "max_exact_paths" and bullseye:
                    value *= _BULLSEYE_EXACT_SCALE
                setattr(ExactSearch, k, value)
            return searcher.find_best_words(board, loadout, top_n=top_n)
        finally:
            for k, v in saved.items():
                setattr(ExactSearch, k, v)

    def words(self, game: Game, top_n: int = 5) -> list[WordOption]:
        enc = game.encounter
        if enc is None:
            return []
        board, loadout = board_and_loadout(enc)
        bullseye = game.player.run.challenge_is("Bullseye")
        results = self._find(board, loadout, max(80, 12 * top_n) if bullseye else top_n)
        out = []
        for r in results:
            out.append(_option(game, r.word, [index_to_coords(enc, i) for i in r.path], r.score))
        if bullseye and out:
            out = self._bullseye_spread(game, board, loadout, out, top_n)
        if not out:
            out = self.placement_words(game, top_n)
        else:
            out = self._with_rack_words(game, out, top_n)
        out += self.item_name_words(game, board, loadout, out)
        out += self.money_words(game, board, loadout, out)
        return out

    def _with_rack_words(self, game: Game, out: list[WordOption], top_n: int, k: int = 3) -> list[WordOption]:
        """Board words exist, but rack tiles placed first often make a far better word (Red
        Letter Day's consonant grids, Chromaphobia's coloured squares made usable by a Normal
        tile). Add the best ``k`` rack words that beat the best board word; board words stay
        so the policy can save the rack."""
        if not any(t is not None for t in game.player.consumables):
            return out
        if game.player.run.challenge_is("Bullseye"):
            return out
        best = out[0].score
        extra = [o for o in self.placement_words(game, k) if o.score > best][:k]
        if not extra:
            return out
        return sorted(out + extra, key=lambda o: -o.score)

    def money_words(self, game: Game, board, loadout, have: list[WordOption], k: int = 2) -> list[WordOption]:
        """When the best word clears and grids remain, a word that does not clear but picks up
        currency tiles earns money on this grid and leaves the next one to clear (Do Not Pass
        Go pays nothing for clearing or unused grids). The top words all clear, so offer the
        ``k`` non-clearing words that earn the most (exact engine money)."""
        enc = game.encounter
        run = game.player.run
        if (not have or enc is None or enc.remaining_grids < 1 or run.challenge_is("Bullseye")
                or not clears(game, have[0].score)):
            return []
        from cursed_words_solver.sim.game.core import G_CURRENCY

        cash = {(t.x, t.y) for t in enc.grid.available() if t.get_glyph() == G_CURRENCY}
        if not cash:
            return []
        seen = {(o.word, tuple(o.path)) for o in have}
        pool = []
        for r in self._find(board, loadout, 48):
            o = _option(game, r.word, [index_to_coords(enc, i) for i in r.path], r.score)
            n = sum(xy in cash for xy in o.path)
            if n and o.score > 0 and not clears(game, o.score) and (o.word, tuple(o.path)) not in seen:
                pool.append((n, o))
        if not pool:
            return []
        pool.sort(key=lambda t: (-t[0], -t[1].score))
        from cursed_words_solver.engine.calc import EnginePlan
        from cursed_words_solver.sim.game.bridge import coords_to_index

        plan = EnginePlan.build(board, loadout)
        earned = []
        for _n, o in pool[:6]:
            try:
                res = plan.score([coords_to_index(enc, x, y) for x, y in o.path], " ".join(o.words),
                                 words=[w.lower() for w in o.words])
                m = int(res.steps[-1].money - res.steps[0].money)
            except Exception:
                continue
            if m > 0:
                o.money = m
                earned.append(o)
        earned.sort(key=lambda o: (-o.money, -o.score))
        return earned[:k]

    def _names_searcher(self, names: frozenset):
        """Engine searcher over item names only (Microphone), cached per name set."""
        cache = self.__dict__.setdefault("_name_searchers", {})
        hit = cache.get(names)
        if hit is None:
            from cursed_words_solver.search import WordSearcher

            if len(cache) > 64:
                cache.clear()
            hit = cache[names] = WordSearcher(_NameDictionary(names), time_budget=0 if self.effort else 1.0)
        return hit

    def item_name_words(self, game: Game, board, loadout, have: list[WordOption], k: int = 3) -> list[WordOption]:
        """Microphone (``GetAccumulatorWords`` / ``ApplyWordBonus``): spelling an un-owned
        single-word item's name adds the item. Names are short and score low, so they never
        make the top words; offer the best ``k`` on the board, plus the best that needs rack
        tiles placed (the only item source in In The Beginning)."""
        p = game.player
        if not p.unpacked_of("Microphone"):
            return []
        from cursed_words_solver.sim.game.encounter import microphone_tables

        single, pairs = microphone_tables(p)
        enc = game.encounter
        for o in have:  # a name already among the top words (two-word names via Honeypot)
            if o.grants_item is None:
                o.grants_item = single.get(o.word) if len(o.words) == 1 else pairs.get(" ".join(o.words)) if len(o.words) == 2 else None
        out_pairs = self._pair_name_words(game, board, loadout, pairs, have) if p.unpacked_of("Honeypot") else []
        names = frozenset(n for n in single if n.isalpha())
        if not names:
            return out_pairs
        searcher = self._names_searcher(names)
        seen = {(o.word, tuple(o.path)) for o in have}
        got = {o.word for o in have}
        out: list[WordOption] = []
        for r in self._search(board, loadout, 4 * k, searcher):
            if r.word not in names or r.word in got:
                continue
            o = _option(game, r.word, [index_to_coords(enc, i) for i in r.path], r.score)
            if (o.word, tuple(o.path)) in seen:
                continue
            o.grants_item = single[r.word]
            out.append(o)
            got.add(r.word)
            if len(out) >= k:
                break
        if any(t is not None for t in p.consumables):
            for o in self.placement_words(game, 4, searcher):
                if o.word in names and o.word not in got:
                    o.grants_item = single[o.word]
                    out.append(o)
                    got.add(o.word)
                    if len(out) >= k + 2:
                        break
        return out + out_pairs

    def _pair_name_words(self, game: Game, board, loadout, pairs: dict[str, str], have, k: int = 2) -> list[WordOption]:
        """Honeypot + Microphone: a two-word item name (``GetAccumulatorPairs``) submitted as
        two words adds the item. ``GetConcatenatedValidWordsFromTiles`` tries the pairs first,
        each half matched only against the pair's own word; for a repeated first word only the
        first pair's second half is tried (``IndexOf``). Search the joined names, then score the
        path as the two words."""
        firsts: dict[str, str] = {}
        for name in pairs:  # pool order, as Microphone builds the lists
            a, b = name.split(" ")
            firsts.setdefault(a, b)
        joined = {a + b: (a, b) for a, b in firsts.items() if a.isalpha() and b.isalpha()}
        if not joined:
            return []
        from cursed_words_solver.engine.calc import EnginePlan
        from cursed_words_solver.sim.game.bridge import coords_to_index

        enc = game.encounter
        got = {o.word for o in have}
        plan = None
        out: list[WordOption] = []
        for r in self._search(board, loadout, 4 * k, self._names_searcher(frozenset(joined))):
            halves = joined.get(r.word)
            if halves is None or " ".join(halves) in got:
                continue
            path = [index_to_coords(enc, i) for i in r.path]
            plan = plan or EnginePlan.build(board, loadout)
            try:
                res = plan.score([coords_to_index(enc, x, y) for x, y in path], " ".join(halves), words=list(halves))
            except Exception:
                continue
            o = _option(game, " ".join(halves), path, res.int_score)
            o.grants_item = pairs[" ".join(halves)]
            out.append(o)
            got.add(o.word)
            if len(out) >= k:
                break
        return out

    def _bullseye_spread(self, game: Game, board, loadout, out: list[WordOption], top_n: int) -> list[WordOption]:
        """Bullseye (``newRemainingTarget = |remaining - score|``, only 0 wins): the closest
        words alone are often one score repeated, leaving a remainder no word can hit. Keep one
        word per score, add words aimed at ``remaining + floor`` (an overshoot that leaves a
        remainder some word reaches), and rank exact hits, then reachable remainders, by distance."""
        rem = int(game.encounter.remaining_target)
        pos = [o.score for o in out if o.score > 0]
        floor = min(pos) if pos else 0
        if floor and rem > 0:
            import copy as _copy

            lo = _copy.copy(loadout)
            lo.extras = dict(loadout.extras or {})
            lo.extras["encounter_remaining_target"] = str(rem + floor)
            enc = game.encounter
            for r in self._find(board, lo, max(40, 6 * top_n)):
                out.append(_option(game, r.word, [index_to_coords(enc, i) for i in r.path], r.score))
        by_score: dict[int, WordOption] = {}
        for o in out:
            by_score.setdefault(o.score, o)
        return sorted(by_score.values(), key=lambda o: bullseye_key(rem, o.score, floor))[:top_n]

    def placement_words(self, game: Game, top_n: int = 5, searcher=None) -> list[WordOption]:
        """Words that need rack tiles placed first (board-only search found none).

        Empty Grid boards hold no letters and Advent Calendar boards are numbers that
        only count as the Nth letter, so a grid often has no word until consumables are
        placed (``ApplyConsumableTile``). Up to 9 rack tiles go in a compact block
        (snake order, so consecutive rack tiles touch: 1-2-3 number tiles chain) at a few
        anchors, the engine searches each variant board, and each word keeps only the
        placements on its path (in path order). Deterministic and cheap: at most
        ``len(_ANCHORS)`` extra searches, and only on grids with no board word.
        """
        enc = game.encounter
        if enc is None or enc.grid is None or enc.finale or not enc.can_submit or enc.awaiting_forced_sell:
            return []
        p = game.player
        # every rack tile, duplicates too (words repeat letters: "lilac" from l ? a i l)
        rack: list[tuple[int, Any]] = [(i, t) for i, t in enumerate(p.consumables) if t is not None]
        if not rack:
            return []
        rack.sort(key=lambda it: _rack_order_key(it[1]))
        rack = rack[:9]
        n = len(rack)
        w, h = (2, 1) if n <= 2 else (2, 2) if n <= 4 else (3, 2) if n <= 6 else (3, 3)
        allowed = {(t.x, t.y) for t in enc.grid.available() if t.consumable_replacement_allowed(p)}
        width = max((x for x, _ in allowed), default=-1) + 1
        height = max((y for _, y in allowed), default=-1) + 1
        if width < w or height < h:
            w, h = min(w, width), min(h, height)
        cells_by_anchor: list[list[tuple[int, int]]] = []
        letters_on_board = any(not t.empty for t in enc.grid.available())
        anchors = _ANCHORS if letters_on_board else _ANCHORS[:1]
        for ax, ay in anchors:
            x0 = {"lo": 0, "mid": (width - w) // 2, "hi": width - w}[ax]
            y0 = {"lo": 0, "mid": (height - h) // 2, "hi": height - h}[ay]
            snake = []
            for dy in range(h):
                xs = range(w) if dy % 2 == 0 else range(w - 1, -1, -1)
                snake.extend((x0 + dx, y0 + dy) for dx in xs)
            cells = [c for c in snake if c in allowed][:n]
            if cells and cells not in cells_by_anchor:
                cells_by_anchor.append(cells)
        layouts = [list(zip([ri for ri, _ in rack], cells)) for cells in cells_by_anchor]
        layouts += _colour_quest_layouts(game, rack, allowed)
        best: dict[tuple, WordOption] = {}
        for layout in layouts:
            g = clone(game, light=True)
            placed: dict[tuple[int, int], int] = {}
            for ri, (x, y) in layout:
                if g.encounter.place_consumable(ri, x, y):
                    placed[(x, y)] = ri
            if not placed:
                continue
            board, loadout = board_and_loadout(g.encounter)
            found = self._find(board, loadout, top_n) if searcher is None else self._search(board, loadout, top_n, searcher)
            for r in found:
                path = [index_to_coords(g.encounter, i) for i in r.path]
                used = [(placed[xy], xy[0], xy[1]) for xy in path if xy in placed]
                if not used:
                    continue
                opt = _option(game, r.word, path, r.score, used)
                # the same word at another anchor is the same play (centre anchor kept)
                key = (r.word, opt.score, len(used))
                if key not in best:
                    best[key] = opt
        # fewest rack tiles spent breaks score ties
        if game.player.run.challenge_is("Bullseye"):
            rem = int(enc.remaining_target)
            return sorted(best.values(), key=lambda o: (bullseye_key(rem, o.score), len(o.placements)))[:top_n]
        return sorted(best.values(), key=lambda o: (-o.score, len(o.placements)))[:top_n]


def _colour_quest_layouts(game: Game, rack, allowed: set, squares: int = 4) -> list[list]:
    """Single-tile placements that make a banned square usable: under Chromaphobia a Normal
    rack tile on a coloured square (``ApplyConsumableTile`` copies the rack tile's type),
    under Chromaphilia a coloured one on a Normal square. Squares with the most usable
    neighbours first."""
    from cursed_words_solver.sim.game import core as C

    run = game.player.run
    phobia, philia = run.challenge_is("Chromaphobia"), run.challenge_is("Chromaphilia")
    if not (phobia or philia):
        return []

    def usable(t) -> bool:
        return (t.tile_type == C.NORMAL) == phobia

    tiles = {(t.x, t.y): t for t in game.encounter.grid.available()}
    good_rack = [(ri, t) for ri, t in rack if usable(t)]
    seen: set = set()
    picks = []
    for ri, t in good_rack:
        k = (t.srep(), t.tile_type)
        if k not in seen:
            seen.add(k)
            picks.append(ri)
    picks = picks[:2]
    if not picks:
        return []
    banned = [xy for xy, t in tiles.items() if xy in allowed and not usable(t)]

    def nbrs(xy) -> int:
        x, y = xy
        return sum(1 for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                   if (dx or dy) and (x + dx, y + dy) in tiles and usable(tiles[(x + dx, y + dy)]))

    banned.sort(key=lambda xy: (-nbrs(xy), xy))
    return [[(ri, xy)] for ri in picks for xy in banned[:squares]]


# Block anchors for ``Candidates.placement_words``: centre first (most neighbours), then
# two corners so board tiles on either side can extend a placed word.
_ANCHORS = (("mid", "mid"), ("lo", "lo"), ("hi", "hi"))


def _option(game: Game, word: str, path, raw: float, placements=None) -> WordOption:
    """``WordOption`` whose ``score`` counts toward the target: Two Wrongs negates the engine
    score (``EncounterController``: ``scoreFromScoreCalcInfo *= -1``), so only negative words help."""
    raw_i = int(round(raw))
    neg = game.player.run.challenge_is("TwoWrongs")
    return WordOption(word=word, words=word.split(), path=path, score=-raw_i if neg else raw_i,
                      placements=list(placements or []), raw=raw_i if neg else None)


class _NameDictionary:
    """``WordDictionary`` stand-in over a fixed set of words (item names)."""

    path = None

    def __init__(self, words) -> None:
        self.words = set(words)

    @property
    def trie(self):
        from cursed_words_solver.engine.solver import trie_for

        return trie_for(self)

    def contains(self, word: str) -> bool:
        return word.lower() in self.words

    def is_valid_word(self, word: str, min_len: int = 1) -> bool:
        return len(word) >= min_len and word.lower() in self.words

    def has_prefix(self, prefix: str) -> bool:
        return self.trie.walk(0, prefix.lower()) >= 0

    def __len__(self) -> int:
        return len(self.words)


def clears(game: Game, score: int) -> bool:
    """Does a word scoring ``score`` (target progress) win the encounter? Bullseye needs an
    exact hit (``|remaining - score| <= 0``); otherwise reaching the target is enough."""
    rem = game.encounter.remaining_target
    if game.player.run.challenge_is("Bullseye"):
        return int(score) == int(rem)
    return score >= rem


def bullseye_key(rem: int, score: int, floor: int = 0) -> tuple:
    """Sort key under Bullseye: exact hit first, then remainders a word can still reach
    (at least the grid's lowest word score), then the rest; closer first within each."""
    left = abs(rem - score)
    return (left != 0, not (left == 0 or (floor and left >= floor)), left)


def _rack_order_key(t) -> tuple:
    """Numbers / fractions ascending first (so they chain as positional wildcards), then the rest."""
    try:
        if t.is_number():
            return (0, float(t.number_float()), "")
    except Exception:
        pass
    return (1, 0.0, t.srep())


def submit_action(o: WordOption, label: str | None = None) -> Action:
    """Submit ``o``; a word that needs rack tiles placed first carries them as a third arg."""
    args = (tuple(o.path), tuple(o.words))
    if o.placements:
        args += (tuple(tuple(pl) for pl in o.placements),)
    if label is None:
        tags = ([f"+{len(o.placements)} rack"] if o.placements else []) + ([f"raw {o.raw}"] if o.raw is not None else [])             + ([f"adds {o.grants_item}"] if o.grants_item else []) + ([f"+${o.money}, no clear"] if o.money else [])
        label = f"{o.word}{' [' + ', '.join(tags) + ']' if tags else ''} ({o.score})"
    return Action("submit", args, label)


def spawn_pool(workers: int, initializer=None, initargs: tuple = ()):
    """``multiprocessing`` spawn pool whose workers share one string-hash seed, so set
    iteration (and therefore every seeded run) is reproducible across processes."""
    import multiprocessing as mp
    import os

    os.environ.setdefault("PYTHONHASHSEED", "0")
    return mp.get_context("spawn").Pool(workers, initializer=initializer, initargs=initargs)


def clone(game: Game, *, light: bool = False) -> Game:
    """Independent copy (shares only the read-only word list).

    ``light`` also shares the run's word history and the encounter's previous words —
    for evaluate-only copies (apply one shop / boss / pin action and read the state);
    never play words on a light copy.

    One C pickle round-trip (~2-3x faster than ``copy.deepcopy``, same result: both go
    through ``__reduce_ex__``). ``CWS_DEEPCOPY_CLONE=1`` selects the deepcopy reference;
    anything that does not pickle falls back to it.
    """
    if os.environ.get("CWS_DEEPCOPY_CLONE") != "1":
        try:
            return _pickle_clone(game, light)
        except Exception:
            pass
    return _deepcopy_clone(game, light)


_CLONE_LOCK = threading.Lock()   # the dump briefly detaches attributes of the source game


def _pickle_clone(game: Game, light: bool) -> Game:
    with _CLONE_LOCK:
        return _pickle_clone_locked(game, light)


def _pickle_clone_locked(game: Game, light: bool) -> Game:
    # Shared objects are detached for the dump and re-attached to both games. Matches the
    # deepcopy memo only while each is reachable solely via its own attribute
    # (tests/sim/test_clone_parity.py checks that).
    words, run, enc = game.words, game.player.run, game.encounter
    stats = prev = None
    game.words = None
    if light:
        stats, run.stats = run.stats, None
        if enc is not None:
            prev, enc.previous_words = enc.previous_words, None
    try:
        data = pickle.dumps(game, pickle.HIGHEST_PROTOCOL)
    finally:
        game.words = words
        if light:
            run.stats = stats
            if enc is not None:
                enc.previous_words = prev
    g = pickle.loads(data)
    g.words = words
    if light:
        g.player.run.stats = stats
        if g.encounter is not None:
            g.encounter.previous_words = prev
    return g


def _deepcopy_clone(game: Game, light: bool) -> Game:
    memo = {id(game.words): game.words}
    if light:
        stats = game.player.run.stats
        memo[id(stats)] = stats
        if game.encounter is not None:
            memo[id(game.encounter.previous_words)] = game.encounter.previous_words
    return copy.deepcopy(game, memo)


def determinize(game: Game, key: str) -> Game:
    """Replace everything a player can't know with a fresh sample, in place.

    Search, rollouts and advice play clones forward; a plain clone carries the real RNG
    stream (next grid, next shop stock, item rolls) and the pre-rolled boss drafts of later
    floors — information a human doesn't have. This rebinds one fresh ``Rng(key)`` for the
    game, shop and encounter and re-rolls the drafts of floors after the current one (the
    current stage's draft is shown to the player, so it is kept). Use the same ``key`` for
    every candidate of one decision so they face the same sampled future (common random
    numbers)."""
    from cursed_words_solver.sim.game.core import Rng
    from cursed_words_solver.sim.game.player import NUMBER_OF_STAGES

    game.rng = Rng(key)
    if game.shop is not None:
        game.shop.rng = game.rng
    if game.encounter is not None:
        game.encounter.rng = game.rng
    run = game.player.run
    start = max(run.stage, 1)
    if start < NUMBER_OF_STAGES and len(run.boss_drafts) >= start:
        run.generate_boss_drafts(game.rng, game.player, start_floor=start)
    enc = game.encounter
    m = getattr(enc, "michael", None) if enc is not None else None
    if m is not None and getattr(m, "drafts", None):
        _resample_michael_drafts(m, enc, game.rng)
    return game


def _resample_michael_drafts(m, enc, rng) -> None:
    """Michael pre-rolls every draft pair at setup; only the drafted ones and the pair on
    screen are visible. Re-roll the rest from the pool minus what the player has seen
    (keeping the Min/Max-length exclusion consistent with anything already shown)."""
    from cursed_words_solver.sim.game.player import BossModifier, boss_rows

    keep =len(m.drafted) + (1 if enc.michael_draft is not None else 0)
    if keep >= len(m.drafts):
        return
    seen = {b.game_class for pair in m.drafts[:keep] for b in pair} | {b.game_class for b in m.drafted}
    pool = [BossModifier(b) for b in boss_rows() if b != "MichaelBoss"]
    pool = [b for b in pool if b.summonable and b.game_class not in seen]
    if "MinWordLength" in seen:
        drop = "MaxWordLength"
    elif "MaxWordLength" in seen:
        drop = "MinWordLength"
    else:
        drop = "MinWordLength" if rng.range(0, 2) == 0 else "MaxWordLength"
    pool = [b for b in pool if b.game_class != drop]
    drafts = [list(p) for p in m.drafts[:keep]]
    for n in range(keep, len(m.drafts)):
        pair = []
        for _ in range(2):
            if not pool:
                break
            b = pool.pop(rng.range(0, len(pool)))
            b.set_floor(5 - n, False)
            pair.append(b)
        drafts.append(pair)
    m.drafts = drafts


# ---------------------------------------------------------------------------- legal actions


def legal_actions(game: Game, cands: Candidates | None = None, *, top_n: int = 5) -> list[Action]:
    ph = game.phase
    out: list[Action] = []
    p = game.player
    if ph == "encounter":
        enc = game.encounter
        if enc.michael_draft is not None:
            return [Action("michael_pick", (i,), f"Michael draft: {b.game_class}") for i, b in enumerate(enc.michael_draft)]
        if enc.finale:
            return [Action("finale", (), "Solve Michael's puzzle grid")]
        if not enc.awaiting_forced_sell and cands is not None:
            for opt in cands.words(game, top_n):
                out.append(submit_action(opt))
        if not enc.awaiting_forced_sell:
            out.append(Action("skip", (), "skip grid"))
            if enc.can_reroll():
                out.append(Action("reroll_grid", (), "reroll grid"))
            for i, t in enumerate(p.consumables):
                if t is None:
                    continue
                for tile in enc.grid.available():
                    if tile.consumable_replacement_allowed(p):
                        out.append(Action("place", (i, tile.x, tile.y), f"place {t.srep()} on {tile.x},{tile.y}"))
        out.extend(_sell_actions(game))
    elif ph == "shop":
        s = game.shop
        for k, o in enumerate(s.stickers):
            if o is not None and s.can_buy("sticker", k):
                out.append(Action("buy", ("sticker", k), f"buy {o.item.game_class} ${s.offer_cost(o)}"))
                if p.unpacked_of("HungryHippo"):
                    out.append(Action("hippo", ("sticker", k), f"feed {o.item.game_class} to Hungry Hippo"))
            if o is not None and not s.slots_hidden("sticker"):
                out.append(Action("freeze", ("sticker", k), f"{'unfreeze' if o.frozen else 'freeze'} {o.item.game_class}"))
        for k, o in enumerate(s.stamps):
            if o is not None and s.can_buy("stamp", k):
                out.append(Action("buy", ("stamp", k), f"buy {o.item.game_class} ${s.offer_cost(o)}"))
            if o is not None and not s.slots_hidden("stamp"):
                out.append(Action("freeze", ("stamp", k), f"{'unfreeze' if o.frozen else 'freeze'} {o.item.game_class}"))
        for k, o in enumerate(s.tiles):
            if s.can_buy_tile(k):
                out.append(Action("buy", ("tile", k), f"buy tile {o.tile.srep()} ({o.tile.tile_type}) ${o.get_price(p)}"))
        if s.can_reroll():
            out.append(Action("reroll_shop", (), f"reroll shop ${s.reroll_cost}"))
        out.extend(_sell_actions(game))
        out.append(Action("leave", (), "leave shop"))
    elif ph == "boss_draft":
        for i, b in enumerate(game.boss_options()):
            out.append(Action("boss", (i,), f"fight {b.game_class}{' (cursed)' if b.cursed else ''} [{b.floor_mod}]"))
    elif ph == "pin_reward":
        for c in game.pin_options():
            out.append(Action("pin", (c,), f"pin upgrade: {c}"))
    return out


def _sell_actions(game: Game) -> Iterable[Action]:
    from cursed_words_solver.sim.game.shop import can_sell

    p = game.player
    for kind, arr in (("sticker", p.stickers), ("stamp", p.stamps)):
        for i, it in enumerate(arr):
            if it is not None and can_sell(p, it):
                yield Action("sell", (kind, i), f"sell {it.game_class}")


def apply(game: Game, action: Action) -> Any:
    k, a = action.kind, action.args
    if k == "submit":
        for ri, x, y in (a[2] if len(a) > 2 else ()):  # rack tiles the word needs placed first
            game.place_consumable(ri, x, y)
        return game.submit([tuple(c) for c in a[0]], list(a[1]))
    if k == "skip":
        return game.skip()
    if k == "reroll_grid":
        return game.reroll_grid()
    if k == "place":
        return game.place_consumable(*a)
    if k == "swap":
        return game.twinkle_swap(a[0], a[1])
    if k == "michael_pick":
        return game.choose_michael_boss(a[0])
    if k == "finale":
        game._end(True, "michael")
        return True
    if k == "sell":
        return game.sell(*a)
    if k == "sell_buy":  # (kind, owned slot, offer index): swap an owned item for an offer
        if game.sell(a[0], a[1]) is None:
            return False
        return game.buy(a[0], a[2])
    if k == "move":
        return game.move(*a)
    if k == "discard":
        return game.discard_tile(a[0])
    if k == "buy":
        return game.buy(*a)
    if k == "hippo":
        return game.buy(a[0], a[1], hippo=True)
    if k == "freeze":
        return game.freeze(*a)
    if k == "reroll_shop":
        return game.reroll_shop()
    if k == "leave":
        return game.leave_shop()
    if k == "boss":
        return game.choose_boss(a[0])
    if k == "pin":
        return game.upgrade_pin(a[0])
    raise ValueError(action)
