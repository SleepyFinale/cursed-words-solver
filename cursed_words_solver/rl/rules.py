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
