"""Inference-time deployment rules applied on top of the policy (and search) pick.

Boss rule (``boss_rule`` crown N, 0 = off): at a boss draft of a run at crown >= N, if the pick
is a CURSED boss and the draft has an uncursed option, take the uncursed one instead (several:
the lowest learned boss risk, ``sim.game.bossrisk``, at this crown / character when the table
exists, else the first). Fresh-seed diagnosis (2026-11-18, champion, forced at every boss draft):
crown 6 wins 33 -> 44 of 88, crown 7 18 -> 22.

Used by ``rl.play.play`` (job["boss_rule"]), ``rl.evaluate run --boss-rule N`` and the live
assistant (env ``CWS_AI_BOSS_RULE``, default off).
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any, Sequence

BOSS_RULE_ENV = "CWS_AI_BOSS_RULE"


def parse_boss_rule(value: Any) -> int:
    """Crown threshold from a job value / env string: an int >= 1, else 0 (off).
    "", None, "0", "off", "no", "false" and junk -> 0."""
    if value is None or isinstance(value, bool):
        return 0
    try:
        n = int(str(value).strip())
    except ValueError:
        return 0
    return n if n > 0 else 0


def env_boss_rule() -> int:
    """``CWS_AI_BOSS_RULE`` as a crown threshold (0 = off, the default)."""
    return parse_boss_rule(os.environ.get(BOSS_RULE_ENV, ""))


@lru_cache(maxsize=1)
def _risk_table():
    try:
        from cursed_words_solver.sim.game.bossrisk import DEFAULT_PATH, BossRisk

        return BossRisk.load(DEFAULT_PATH) if DEFAULT_PATH.is_file() else None
    except Exception:
        return None


def _action(c):
    return getattr(c, "action", c)


def uncursed_boss_override(game, action, candidates: Sequence, min_crown: int, risk="default"):
    """The uncursed boss action to play instead of ``action``, or None (rule off / not a boss
    draft / crown < ``min_crown`` / pick not cursed / no uncursed option among ``candidates``).
    ``candidates``: legal Actions or objects with ``.action`` (env candidates). ``risk``: a
    ``BossRisk`` (None = no risk ordering; "default" = the learned table if present)."""
    min_crown = parse_boss_rule(min_crown)
    a = _action(action)
    if not min_crown or a is None or getattr(a, "kind", None) != "boss" or getattr(game, "phase", None) != "boss_draft":
        return None
    p = game.player
    crown = int(p.run.ascension)
    if crown < min_crown:
        return None
    opts = game.boss_options()
    if not opts or not opts[a.args[0]].cursed:
        return None
    alts = [_action(c) for c in candidates]
    alts = [x for x in alts if x.kind == "boss" and not opts[x.args[0]].cursed]
    if not alts:
        return None
    if risk == "default":
        risk = _risk_table()
    if risk is not None and len(alts) > 1:
        try:
            # stable sort: ties keep the first
            alts = sorted(alts, key=lambda x: risk.risk(opts[x.args[0]], crown, p.character))
        except Exception:
            pass
    return alts[0]


def boss_rule_index(game, cands: Sequence, i: int, min_crown: int, risk="default") -> int:
    """``i`` (an index into ``cands``), or the index of the uncursed override."""
    alt = uncursed_boss_override(game, cands[i], cands, min_crown, risk)
    if alt is None:
        return i
    return next(j for j, c in enumerate(cands) if _action(c) is alt)


def boss_rule_action(game, action, min_crown: int, risk="default"):
    """For a policy that returns an Action (the teacher): the override among the draft's legal
    boss actions, else ``action``."""
    if not parse_boss_rule(min_crown) or getattr(action, "kind", None) != "boss":
        return action
    from cursed_words_solver.sim.game.agent import legal_actions

    alt = uncursed_boss_override(game, action, legal_actions(game), min_crown, risk)
    return action if alt is None else alt


# ------------------------------------------------------------------------- auto-arrange
#
# Auto-arrange (``best_arrangement``): Human Boy's (SockHead) Left Hand favourites the sticker to
# its LEFT and his Right Hand re-triggers the stamp to its RIGHT, so item ORDER is a large part
# of his power, yet the policy almost never drags items. Before a submit decision (and at shop
# leave, on a probe encounter) find the drags that raise the best (target-capped) score over the
# top-K submit candidates and make them with the game's own move (``Game.move``: remove and
# re-insert, as a human drag). Only drags that change what a positional item (Left / Right Hand,
# Overhand, Underhand) points at are searched (greedy, best single drag per round), so it is
# cheap; it is deterministic and draws no randomness. Off by default: ``rl.play`` job["arrange"],
# ``CWEnv(arrange=True)``, ``rl.evaluate run --arrange``, assistant env ``CWS_AI_ARRANGE=1``.

ARRANGE_ENV = "CWS_AI_ARRANGE"
ARRANGE_MIN_GAIN = 0.005   # relative gain at or below which the order is left alone
ARRANGE_K = 8               # submit candidates scored per arrangement

# positional items and the row they sit in (what they point at: ``_relations``)
POSITIONAL = {"LeftHumanHand": "sticker", "Overhand": "sticker", "RightHumanHand": "stamp", "Underhand": "stamp"}


ARRANGE_GRID = "grid"


def parse_arrange_mode(value: Any) -> str:
    """Job / env value as an arrange mode: "" (off), "score" (True, 1, "1", "on", "yes", "true":
    drag for the next submit's score) or "grid" ("grid": also drag for the grid about to be
    built, at shop leave and before a grid reroll, ``grid_arrangement``)."""
    if isinstance(value, bool):
        return "score" if value else ""
    if value is None:
        return ""
    s = str(value).strip().lower()
    if s == ARRANGE_GRID:
        return ARRANGE_GRID
    return "score" if s in ("1", "on", "yes", "true", "score") else ""


def parse_arrange(value: Any) -> bool:
    """Job / env value as a flag: True, 1, "1", "on", "yes", "true", "grid" -> True; else False."""
    return bool(parse_arrange_mode(value))


def env_arrange_mode() -> str:
    """``CWS_AI_ARRANGE`` as a mode (``parse_arrange_mode``; unset = "score")."""
    return parse_arrange_mode(os.environ.get(ARRANGE_ENV, "1"))


def env_arrange() -> bool:
    """``CWS_AI_ARRANGE`` for the live assistant: default ON since 2026-11-21 (Human Boy, 240 paired
    fresh seeds: 61.7% vs 43.8% wins, z 5.7); set it to 0 to turn it off. Sim play / env / eval
    stay off unless asked (``CWEnv(arrange=True)``, ``evaluate run --arrange``)."""
    return bool(env_arrange_mode())


def has_positional(p) -> bool:
    """Does the player own an item whose effect depends on its slot (Hands, Over/Underhand)?"""
    return any(it is not None and POSITIONAL.get(it.game_class) == kind
               for kind, arr in (("sticker", p.stickers), ("stamp", p.stamps)) for it in arr)


def _rows(p) -> list[str]:
    """Rows whose order can change a positional item's target."""
    cls = {it.game_class for arr in (p.stickers, p.stamps) for it in arr if it is not None}
    rows = []
    if cls & {"LeftHumanHand", "Overhand", "Underhand"}:
        rows.append("sticker")
    if cls & {"RightHumanHand", "Overhand", "Underhand"}:
        rows.append("stamp")
    return rows


def _relations(st: tuple, sp: tuple, cls: dict) -> tuple:
    """What each positional item points at, on index orders (``st`` / ``sp``: original slot
    index per slot, None = empty; ``cls``: (row, original index) -> game class)."""
    out = []
    for i, o in enumerate(st):
        c = cls.get(("sticker", o)) if o is not None else None
        if c == "LeftHumanHand":
            out.append(("L", o, st[i - 1] if i > 0 else None))
        elif c == "Overhand":
            out.append(("O", o, sp[i]))
    for i, o in enumerate(sp):
        c = cls.get(("stamp", o)) if o is not None else None
        if c == "RightHumanHand":
            out.append(("R", o, sp[i + 1] if i + 1 < len(sp) else None))
        elif c == "Underhand":
            out.append(("U", o, st[i]))
    return tuple(out)


# which row each relation's target sits in (``_relations``: L / U point at stickers, R / O at stamps)
_TARGET_ROW = {"L": "sticker", "U": "sticker", "R": "stamp", "O": "stamp"}


def _rel(st: tuple, sp: tuple, cls: dict, relevant: frozenset | None) -> tuple:
    rel = _relations(st, sp, cls)
    if relevant is None:
        return rel
    return tuple((t, o, x if x is not None and (_TARGET_ROW[t], x) in relevant else None) for t, o, x in rel)


def _drag(order: tuple, src: int, dst: int) -> tuple:
    a = list(order)
    a.insert(dst, a.pop(src))
    return tuple(a)


def _objective(game, opts: Sequence) -> float:
    """Best target-capped progress over ``opts`` (WordOptions without rack placements) under the
    game's current order (the engine scorer, as ``Encounter.score_preview``; Two Wrongs negated
    like ``WordOption.score``)."""
    from cursed_words_solver.engine.calc import EnginePlan
    from cursed_words_solver.sim.game.bridge import board_and_loadout, coords_to_index

    enc = game.encounter
    board, loadout = board_and_loadout(enc)
    plan = EnginePlan.build(board, loadout)
    cap = float(enc.remaining_target) if enc.remaining_target > 0 else float("inf")
    neg = game.player.run.challenge_is("TwoWrongs")
    best = float("-inf")
    for o in opts:
        try:
            idx = [coords_to_index(enc, x, y) for x, y in o.path]
            raw = float(plan.score(idx, " ".join(o.words), words=[w.lower() for w in o.words]).score)
        except Exception:
            continue
        best = max(best, min(-raw if neg else raw, cap))
    return best


def _applicable(game) -> bool:
    enc = game.encounter
    if enc is None or not enc.can_submit or enc.finale or enc.grid is None:
        return False
    # Bullseye wants an exact hit (more is not better); Capybara reshuffles the order on submit
    return not game.player.run.challenge_is("Bullseye") and enc.boss("RandomiseItemOrder") is None


def _search(game, opts: Sequence, rounds: int, min_gain: float, info: dict | None) -> list[tuple[str, int, int]]:
    return _search_fn(game, lambda g: _objective(g, opts), rounds, min_gain, info)


def _search_fn(game, value, rounds: int, min_gain: float, info: dict | None,
               relevant: frozenset | None = None, abs_gain: float = 0.0) -> list[tuple[str, int, int]]:
    """Greedy drag search (best single relation-changing drag per round) maximising ``value(g)``
    over light clones ``g`` of ``game`` with the drags made. ``relevant``: (row, slot) of the items
    whose relations count (others are treated as nothing: drags that only change what a hand
    points at among them are skipped); None = all."""
    from cursed_words_solver.sim.game.agent import clone

    p = game.player
    rows = _rows(p)
    st0 = tuple(i if it is not None else None for i, it in enumerate(p.stickers))
    sp0 = tuple(i if it is not None else None for i, it in enumerate(p.stamps))
    cls = {(k, i): it.game_class for k, arr in (("sticker", p.stickers), ("stamp", p.stamps))
           for i, it in enumerate(arr) if it is not None}
    base = value(game)
    evals = 1
    if base == float("-inf"):
        return []
    cur_g, cur_obj, cur = game, base, (st0, sp0)
    drags: list[tuple[str, int, int]] = []
    seen = {cur}
    for _ in range(max(0, int(rounds))):
        rel = _rel(*cur, cls, relevant)
        best = None
        for kind in rows:
            order = cur[0] if kind == "sticker" else cur[1]
            for src in range(5):
                if order[src] is None:
                    continue
                for dst in range(5):
                    if dst == src:
                        continue
                    o2 = _drag(order, src, dst)
                    nxt = (o2, cur[1]) if kind == "sticker" else (cur[0], o2)
                    if nxt in seen or _rel(*nxt, cls, relevant) == rel:
                        continue
                    seen.add(nxt)
                    g = clone(cur_g, light=True)   # a reorder draws no randomness
                    if not g.move(kind, src, dst):
                        continue
                    v = value(g)
                    evals += 1
                    if best is None or v > best[0] + 1e-9:
                        best = (v, (kind, src, dst), g, nxt)
        if best is None or best[0] <= cur_obj + 1e-9:
            break
        cur_obj, cur_g, cur = best[0], best[2], best[3]
        drags.append(best[1])
    if info is not None:
        info.update(base=base, best=cur_obj, evals=evals)
    if not drags or cur_obj - base <= min_gain * max(abs(base), 1.0) or cur_obj - base <= abs_gain:
        return []
    return drags


def _probe(game, cands):
    """(probe game, its Candidates) for the next encounter (``PowerPolicy._probe_game``: a clone
    with its own probe RNG, the real game's RNG is untouched); None when unavailable."""
    from cursed_words_solver.sim.game.policy import PowerPolicy, next_encounter_node

    try:
        from cursed_words_solver.rl.obs import prober

        pr = prober()
    except Exception:
        pr = None
    if pr is not None:
        pol = pr.pol
    elif cands is not None and hasattr(cands, "with_budget"):
        pol = PowerPolicy(cands)
    else:
        return None
    stage, node = next_encounter_node(game)
    return pol._probe_game(game, stage, node, 0), pol.probe_cands


def best_arrangement(game, words: Sequence | None = None, k: int = ARRANGE_K, *, cands=None, rounds: int = 3,
                     min_gain: float = ARRANGE_MIN_GAIN, info: dict | None = None) -> list[tuple[str, int, int]]:
    """Drags ``(kind, src, dst)`` (apply in order with ``game.move``) that maximise the best
    target-capped score over the top ``k`` submit candidates ``words`` (WordOptions; None: found
    with ``cands.words``; rack-placement words are left out), or [] (no positional item owned,
    not a submit decision, or a gain of at most ``min_gain``). In a shop (no encounter) the order
    is scored on a probe of the next encounter (needs ``cands`` or the obs prober; else []).
    Deterministic: scores clones and draws no randomness. ``info`` gets base / best / evals."""
    p = game.player
    if not has_positional(p):
        return []
    try:
        if game.encounter is None:
            if getattr(game, "phase", None) != "shop":
                return []
            pr = _probe(game, cands)
            if pr is None:
                return []
            g, pc = pr
            if not _applicable(g):
                return []
            opts = [o for o in pc.words(g, k) if not o.placements][:k]
            return _search(g, opts, rounds, min_gain, info) if opts else []
        if not _applicable(game):
            return []
        if words is None:
            if cands is None:
                return []
            words = cands.words(game, k)
        opts = sorted((o for o in words if not getattr(o, "placements", None)), key=lambda o: -o.score)[:k]
        return _search(game, opts, rounds, min_gain, info) if opts else []
    except Exception:
        return []


# ------------------------------------------------------------- grid-aware arrange ("grid" mode)
#
# Human Boy's hands also act when a grid is BUILT: the Right Hand re-triggers its favourite stamp's
# grid-generation effect (gridgen ``is_hb_favourite_stamp``) and its encounter-start effect (Diya:
# extra grids, encounter._setup_rest), the Left Hand's favourite sticker is upgraded, Overhand /
# Underhand repeat theirs. The game lets the player drag items in a shop at any time and in an
# encounter only while it waits for a word (``ItemObject.BeginDrag``: EncounterThreadStage
# WaitingForWordSubmission), i.e. after a grid appears and before the submit / skip / reroll that
# builds the next one. So the best play is two orders: one for the grid about to be built (at shop
# leave, before a grid reroll or skip), then the scoring order once it exists (the per-submit
# ``best_arrangement``). Every candidate order builds its grid on sampled futures (a keyed probe /
# ``determinize``: no real-RNG peeking, the same samples for every order) and is valued with the
# scoring order dragged in afterwards, as the next submit decision does.
# Sub-envs (look-ahead rollouts) keep the cheaper score mode: a grid search per rollout shop is
# too slow for the search budget.

GRID_ROUNDS = 2            # drag rounds for the grid order
GRID_SAMPLES = 4           # sampled grids per candidate order (common to all orders)
GRID_MIN_GAIN_SHOP = 0.1   # spare grids at or below which the shop order is left alone
GRID_MIN_GAIN_GRID = 0.05  # relative best-score gain at or below which a reroll / skip order is left alone
GRID_EFFORT = 0.05         # deterministic word search for the valuation (load-independent)
# item hooks that run when a grid is built / an encounter is set up
_GRID_HOOKS = ("start_of_grid", "final_start_of_grid")
_SETUP_HOOKS = ("start_of_encounter",)
_NESTING = frozenset({"RandomAccessMemory", "Frankenstein"})
# hooks that only redraw a number / set a flag: repeating them does not change the grid
_GRID_INERT = frozenset({"LuckyDice", "Dartboard", "EightBall", "TwinkleToes", "Wheel"})


def _grid_items(p, *, setup: bool) -> frozenset:
    """(row, slot) of owned items with a grid-build effect (``setup``: also encounter-start
    effects, Diya included: they run only when an encounter starts, not on a reroll / skip)."""
    from cursed_words_solver.sim.game.items import Item

    hooks = _GRID_HOOKS + (_SETUP_HOOKS if setup else ())
    out = set()
    for kind, arr in (("sticker", p.stickers), ("stamp", p.stamps)):
        for i, it in enumerate(arr):
            if it is None or it.game_class in POSITIONAL or it.game_class in _GRID_INERT:
                continue
            cl = type(it)
            if (it.game_class in _NESTING or (setup and it.game_class == "Diya")
                    or any(getattr(cl, h, None) is not getattr(Item, h, None) for h in hooks)):
                out.add((kind, i))
    return frozenset(out)


def _det(c):
    """Deterministic, load-independent word search for valuation (effort mode)."""
    if c is not None and not getattr(c, "effort", None) and hasattr(c, "with_effort"):
        return c.with_effort(GRID_EFFORT)
    return c


def _best_on_grid(g, cands, k: int) -> float:
    """Best target-capped score on ``g``'s current grid under the scoring order the next submit
    decision would drag in (``best_arrangement``'s rounds and acceptance rule)."""
    if not _applicable(g):
        return float("-inf")
    opts = sorted((o for o in cands.words(g, k) if not o.placements), key=lambda o: -o.score)[:k]
    if not opts:
        return float("-inf")
    info: dict = {}
    drags = _search(g, opts, 3, ARRANGE_MIN_GAIN, info)
    return float(info["best"]) if drags else float(info.get("base", _objective(g, opts)))


def _grid_probe(game, stage: int, node, s: int):
    """``PowerPolicy._probe_game`` with a position-keyed probe RNG, so orders that consume
    different amounts of randomness at encounter setup still get the same letters per grid."""
    from cursed_words_solver.sim.game.agent import clone
    from cursed_words_solver.sim.game.core import KeyedRng
    from cursed_words_solver.sim.game.encounter import Encounter
    from cursed_words_solver.sim.game.player import Node

    g = clone(game)
    g.rng = KeyedRng(f"arrange|probe|{stage}|{node.name}|{s}")
    run = g.player.run
    run.stage, run.node = stage, (Node.ENCOUNTER_SECOND if node == Node.BOSS else node)
    g.shop = None
    g.player._shop_listener = None
    enc = Encounter(g)
    g.player.active_bosses = []
    g.encounter = enc
    enc._setup_rest()
    enc.awaiting_forced_sell = False
    enc.remaining_target = 10**15
    return g


def _shop_grid_value(gs, cands, k: int) -> float:
    """Spare grids of the next encounter under ``gs``'s order: the grids it starts with (Diya
    and the like count) minus target / best first-grid score, averaged over ``GRID_SAMPLES``."""
    from cursed_words_solver.sim.game.policy import next_encounter_node

    stage, node = next_encounter_node(gs)
    vals = []
    for s in range(GRID_SAMPLES):
        pg = _grid_probe(gs, stage, node, s)
        best = _best_on_grid(pg, cands, k)
        if best == float("-inf"):
            return best
        target = float(pg.player.run.current_encounter_target(pg.player))
        vals.append(pg.encounter.remaining_grids + 1 - target / max(best, 1.0))
    return sum(vals) / len(vals)


def _next_key(game, via: str) -> str:
    run, enc = game.player.run, game.encounter
    return f"arrange|{via}|{run.stage}|{run.node.name}|{enc.grids_generated}|{getattr(enc, 'reroll_tracker', 0)}"


def _next_grid_value(gr, cands, k: int, key: str, via: str) -> float:
    """Mean best score on the grid a reroll / skip builds under ``gr``'s order (sampled futures,
    the same for every order)."""
    from cursed_words_solver.sim.game.agent import clone, determinize

    vals = []
    for s in range(GRID_SAMPLES):
        h = determinize(clone(gr), f"{key}|{s}")
        if via == "skip":
            h.skip()
            if h.encounter is None or h.phase != "encounter" or h.encounter.grid is None:
                return float("-inf")
        elif not h.reroll_grid():
            return float("-inf")
        best = _best_on_grid(h, cands, k)
        if best == float("-inf"):
            return best
        vals.append(best)
    return sum(vals) / len(vals)


def grid_arrangement(game, cands=None, k: int = ARRANGE_K, *, via: str = "reroll", rounds: int = GRID_ROUNDS,
                     info: dict | None = None) -> list[tuple[str, int, int]]:
    """Drags ``(kind, src, dst)`` for the grid about to be built: in a shop (before leaving) the
    order that gives the next encounter the most spare grids; in an encounter before a grid
    reroll (``via`` "reroll") or a skip ("skip") the order whose next grid scores best; both valued
    with the scoring order dragged in afterwards. [] when no positional item is owned, no hand can
    point at a grid-build item, nothing gains by more than the gate, or it is not applicable.
    Deterministic; the real game is not changed and its RNG is not read."""
    p = game.player
    if not has_positional(p) or cands is None:
        return []
    cands = _det(cands)
    try:
        if game.encounter is None:
            if getattr(game, "phase", None) != "shop":
                return []
            rel = _grid_items(p, setup=True)
            if not rel:
                return []
            return _search_fn(game, lambda g: _shop_grid_value(g, cands, k), rounds, 0.0, info, rel,
                              abs_gain=GRID_MIN_GAIN_SHOP)
        enc = game.encounter
        if not _applicable(game):
            return []
        if via == "reroll" and not enc.can_reroll():
            return []
        if via == "skip" and enc.remaining_grids <= 0:
            return []   # a skip with no grid left ends the encounter: no grid is built
        rel = _grid_items(p, setup=False)
        if not rel:
            return []
        key = _next_key(game, via)
        return _search_fn(game, lambda g: _next_grid_value(g, cands, k, key, via), rounds, GRID_MIN_GAIN_GRID,
                          info, rel)
    except Exception:
        return []


def apply_arrangement(game, drags: Sequence) -> int:
    """Make the drags with the game's own move (as a human would); returns how many applied."""
    return sum(bool(game.move(kind, src, dst)) for kind, src, dst in drags)


def describe_drags(game, drags: Sequence) -> list[str]:
    """Human-followable steps, 'rearrange: move LeftHumanHand to sticker slot 3' (slots 1-5 from
    the left), each item named on the order before its drag (class names: callers ``display``)."""
    from cursed_words_solver.sim.game.agent import clone

    g = clone(game, light=True)
    out = []
    for kind, src, dst in drags:
        arr = g.player.stickers if kind == "sticker" else g.player.stamps
        it = arr[src]
        out.append(f"rearrange: move {it.game_class if it is not None else '?'} to {kind} slot {dst + 1}")
        g.move(kind, src, dst)
    return out
