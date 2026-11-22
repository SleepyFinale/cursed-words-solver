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


def parse_arrange(value: Any) -> bool:
    """Job / env value as a flag: True, 1, "1", "on", "yes", "true" -> True; else False."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in ("1", "on", "yes", "true")


def env_arrange() -> bool:
    """``CWS_AI_ARRANGE`` for the live assistant: default ON since 2026-11-21 (Human Boy, 240 paired
    fresh seeds: 61.7% vs 43.8% wins, z 5.7); set it to 0 to turn it off. Sim play / env / eval
    stay off unless asked (``CWEnv(arrange=True)``, ``evaluate run --arrange``)."""
    return parse_arrange(os.environ.get(ARRANGE_ENV, "1"))


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
    from cursed_words_solver.sim.game.agent import clone

    p = game.player
    rows = _rows(p)
    st0 = tuple(i if it is not None else None for i, it in enumerate(p.stickers))
    sp0 = tuple(i if it is not None else None for i, it in enumerate(p.stamps))
    cls = {(k, i): it.game_class for k, arr in (("sticker", p.stickers), ("stamp", p.stamps))
           for i, it in enumerate(arr) if it is not None}
    base = _objective(game, opts)
    evals = 1
    if base == float("-inf"):
        return []
    cur_g, cur_obj, cur = game, base, (st0, sp0)
    drags: list[tuple[str, int, int]] = []
    seen = {cur}
    for _ in range(max(0, int(rounds))):
        rel = _relations(*cur, cls)
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
                    if nxt in seen or _relations(*nxt, cls) == rel:
                        continue
                    seen.add(nxt)
                    g = clone(cur_g, light=True)   # a reorder draws no randomness
                    if not g.move(kind, src, dst):
                        continue
                    v = _objective(g, opts)
                    evals += 1
                    if best is None or v > best[0] + 1e-9:
                        best = (v, (kind, src, dst), g, nxt)
        if best is None or best[0] <= cur_obj + 1e-9:
            break
        cur_obj, cur_g, cur = best[0], best[2], best[3]
        drags.append(best[1])
    if info is not None:
        info.update(base=base, best=cur_obj, evals=evals)
    if not drags or cur_obj - base <= min_gain * max(abs(base), 1.0):
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
