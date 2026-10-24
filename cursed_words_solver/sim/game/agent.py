"""Agent interface over ``Game``: actions, legal-action enumeration, cloning, word candidates.

``Action`` is a small tagged record so policies (heuristic, search, learned) and the
training loop share one vocabulary. ``Candidates`` wraps the exact engine search so
every policy sees the same top-K words for a grid.
"""

from __future__ import annotations

import copy
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
    score: int
    placements: list[tuple[int, int, int]] = field(default_factory=list)  # (rack_idx, x, y)


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
        if not self.effort:
            return self.searcher.find_best_words(board, loadout, top_n=top_n)
        from cursed_words_solver.engine.search import ExactSearch

        saved = {k: getattr(ExactSearch, k) for k in _EFFORT_ATTRS}
        try:
            for k, floor in _EFFORT_ATTRS.items():
                scale = 2 * self.effort if k == "beam_fixed_width" else self.effort
                if k == "max_exact_paths" and self.cheap_floor:  # exact scoring dominates cheap searches
                    floor = max(500, int(floor * min(1.0, self.effort / 0.05)))
                setattr(ExactSearch, k, max(floor, int(saved[k] * scale)))
            return self.searcher.find_best_words(board, loadout, top_n=top_n)
        finally:
            for k, v in saved.items():
                setattr(ExactSearch, k, v)

    def words(self, game: Game, top_n: int = 5) -> list[WordOption]:
        enc = game.encounter
        if enc is None:
            return []
        board, loadout = board_and_loadout(enc)
        results = self._find(board, loadout, top_n)
        out = []
        for r in results:
            out.append(WordOption(
                word=r.word,
                words=r.word.split(),
                path=[index_to_coords(enc, i) for i in r.path],
                score=int(round(r.score)),
            ))
        return out


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
    """
    memo = {id(game.words): game.words}
    if light:
        stats = game.player.run.stats
        memo[id(stats)] = stats
        if game.encounter is not None:
            memo[id(game.encounter.previous_words)] = game.encounter.previous_words
    return copy.deepcopy(game, memo)


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
                out.append(Action("submit", (tuple(opt.path), tuple(opt.words)), f"{opt.word} ({opt.score})"))
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
            if o is not None:
                out.append(Action("freeze", ("sticker", k), f"{'unfreeze' if o.frozen else 'freeze'} {o.item.game_class}"))
        for k, o in enumerate(s.stamps):
            if o is not None and s.can_buy("stamp", k):
                out.append(Action("buy", ("stamp", k), f"buy {o.item.game_class} ${s.offer_cost(o)}"))
            if o is not None:
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
    if k == "move":
        return game.move(*a)
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
