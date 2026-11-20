"""Target builds for build-conditioned RL.

Each run may carry a TARGET BUILD (``RunConfig.target_build``): one plan of
``policy.BUILD_PLANS`` ("Red"), a combo ("Red+Blue"), or ``FREE`` ("": no target, the policy
chooses, i.e. the unconditioned behaviour). It is an AI input only (``obs`` columns
``target_set`` / ``target:*`` and per-item ``pc:*``); the simulation ignores it and the policy
may deviate from it.

``PLANS`` is the fixed, append-only column order of the obs multi-hot. In file names write a
combo with "-" instead of "+" (``file_tag``).
"""

from __future__ import annotations

import random
from dataclasses import FrozenInstanceError, replace
from functools import lru_cache
from typing import TYPE_CHECKING

from cursed_words_solver.sim.game import policy as _policy

if TYPE_CHECKING:  # pragma: no cover
    from cursed_words_solver.sim.game.run import Game

# Fixed, APPEND-ONLY order (obs columns ``target:{p}``).
PLANS: tuple[str, ...] = ("Red", "Blue", "Void", "Shiny", "Blank", "Rainbow", "Numbers", "Chess", "Cards", "Curse",
                          "Consumable", "Cash", "ScatteredItems", "Colourless")
assert set(PLANS) == set(_policy.BUILD_PLANS), "rl.targets.PLANS out of sync with policy.BUILD_PLANS"

FREE = ""   # no target: the policy chooses (today's behaviour)

# Themed builds per character (character class names).
THEMES: dict[str, tuple[str, ...]] = {
    "BonesTheDog": ("Cards",),
    "HayleyBayles": ("Numbers",),
    "NathaServo": ("ScatteredItems",),
    "NinaNix": ("Void", "Rainbow"),
    "Octacles": ("Curse",),
    "PrismaticBean": ("Rainbow",),
    "SamGambit": ("Chess", "Curse"),
    "SandySaguaro": ("Consumable", "Red"),
    "SockHead": ("Curse", "Chess"),
    "Spike": ("Cash", "Curse"),
    "WetDennis": ("Red", "Blue", "Rainbow"),
}

# Plans a run may be given at random (Colourless is the Chromaphobia quest's plan only).
SAMPLE_PLANS: tuple[str, ...] = tuple(p for p in PLANS if p != "Colourless")

_ON = ("generator", "fits")


@lru_cache(maxsize=None)
def parse(target: str) -> tuple[str, ...]:
    """``""`` -> (); ``"Red+Blue"`` -> ("Red", "Blue"). Unknown plan names raise ValueError."""
    if not target:
        return ()
    parts = tuple(p.strip() for p in str(target).split("+"))
    bad = [p for p in parts if p not in _policy.BUILD_PLANS]
    if bad:
        raise ValueError(f"unknown build plan(s) {bad} in target {target!r}; known: {PLANS}")
    return parts


def canonical(target: str) -> str:
    """The target with its parts joined by "+" (whitespace dropped)."""
    return "+".join(parse(target))


@lru_cache(maxsize=None)
def item_class(target: str, game_class: str) -> str | None:
    """None for FREE; else the item's place in the target ("generator" / "fits" / "neutral" /
    "off"), best over a combo's parts (``policy.plan_class``)."""
    parts = parse(target)
    if not parts:
        return None
    return _policy.plan_class("+".join(parts), game_class)


def sample_target(rng: random.Random, character: str, mix: tuple[float, float, float] = (0.34, 0.33, 0.33),
                  weights: dict[str, float] | None = None) -> str:
    """FREE / one of the character's themes / any sampleable plan, by the shares in ``mix``
    (normalised). One ``rng.random()`` then (unless FREE) one ``rng.choice`` (``rng.choices``
    by ``weights`` {plan: weight} when given: the PPO target curriculum)."""
    p_free, p_theme, p_any = (max(0.0, float(x)) for x in mix)
    tot = p_free + p_theme + p_any
    u = rng.random() * (tot if tot > 0 else 1.0)
    if tot <= 0 or u < p_free:
        return FREE
    pool = (THEMES.get(character) or SAMPLE_PLANS) if u < p_free + p_theme else SAMPLE_PLANS
    if weights:
        return rng.choices(pool, weights=[max(1e-6, float(weights.get(x, 1.0))) for x in pool])[0]
    return rng.choice(pool)


def teacher_plan(target: str, character: str, quest: str | None) -> str:
    """The rules-player ``build_plan`` a teacher plays for ``target`` (mirrors
    ``PowerPolicy._tune``): FREE -> the default plan for the character, else the target; a
    quest in ``QUEST_PLANS`` then overrides it. Teachers record this EFFECTIVE plan as the
    episode's target ("" -> FREE)."""
    plan = canonical(target) if target else _policy.DEFAULT_PLAN_CHARS.get(character, _policy.DEFAULT_PLAN)
    if plan and quest in _policy.QUEST_PLANS:
        plan = _policy.QUEST_PLANS[quest]
    return plan


def display(target: str) -> str:
    """"Free", or "Red + Blue"."""
    parts = parse(target)
    return " + ".join(parts) if parts else "Free"


def file_tag(target: str) -> str:
    """Target as it goes in file names: "Red-Blue" ("free" for FREE)."""
    return "-".join(parse(target)) or "free"


def get_target(game: "Game") -> str:
    """The game's target build (``RunConfig.target_build``; FREE when absent)."""
    return getattr(getattr(game, "config", None), "target_build", FREE) or FREE


def set_target(game: "Game", target: str) -> None:
    """Set the target build on a game (imported games, live advice). Validated."""
    from cursed_words_solver.sim.game.run import RunConfig

    target = canonical(target) if target else FREE
    cfg = getattr(game, "config", None)
    if cfg is None:
        game.config = RunConfig(target_build=target)
        return
    try:
        cfg.target_build = target
    except (FrozenInstanceError, AttributeError):
        game.config = replace(cfg, target_build=target)


def _owned(game: "Game"):
    p = game.player
    return [it for it in (*p.stickers, *p.stamps) if it is not None]


def on_plan_count(game: "Game", target: str) -> int:
    """Owned stickers + stamps (not the pin) that are the target's generators or fit it (0 for FREE)."""
    if not target:
        return 0
    return sum(item_class(target, it.game_class) in _ON for it in _owned(game))


def off_plan_count(game: "Game", target: str) -> int:
    """Owned stickers + stamps (not the pin) that belong only to other builds (0 for FREE)."""
    if not target:
        return 0
    return sum(item_class(target, it.game_class) == "off" for it in _owned(game))


# ------------------------------------------------------------------ pivot targets
# A good player does not fix a build at run start: they watch what the shops offer and what
# they own, then commit to the build that has become viable. A PIVOT run starts FREE and, from
# ``pivot_stage`` on, re-reads the build its owned items lean to at every shop entry
# (``pivot_update``; hysteresis keeps a chosen build until another clearly leads).

LEAN_WEIGHTS = {"generator": 1.5, "fits": 1.0}
LEAN_MIN_SCORE = 2.0
LEAN_MARGIN = 2.0


def lean_scores(game: "Game") -> dict[str, float]:
    """{plan: score} over ``SAMPLE_PLANS``: per owned sticker / stamp (not the pin) 1.5 if it is
    one of the plan's generators, 1.0 if it fits it, else 0. Visible state only."""
    owned = [it.game_class for it in _owned(game)]
    return {p: sum(LEAN_WEIGHTS.get(item_class(p, c) or "", 0.0) for c in owned) for p in SAMPLE_PLANS}


def lean(game: "Game", current: str = FREE, min_score: float = LEAN_MIN_SCORE,
         margin: float = LEAN_MARGIN) -> str:
    """The plan the owned items lean to: the best ``lean_scores`` plan (ties: ``current`` if it is
    among the best, else the first in ``PLANS`` order); FREE if the best scores < ``min_score``;
    a non-FREE ``current`` is kept while its score >= best - ``margin`` (hysteresis)."""
    sc = lean_scores(game)
    best = max(sc.values()) if sc else 0.0
    cur = canonical(current) if current else FREE
    if best < min_score:
        return FREE
    if cur and cur in sc and sc[cur] >= best - margin:
        return cur
    return next(p for p in PLANS if p in sc and sc[p] == best)


def pivot_update(game: "Game", pivot_stage: int, current: str = FREE) -> str:
    """A pivot run's target at a shop entry: FREE before stage ``pivot_stage``, else ``lean``."""
    if int(game.player.run.stage) < int(pivot_stage):
        return FREE
    return lean(game, current)


def pivot_label(pivot_stage: int) -> str:
    """Eval / target-table arm name of a pivot run: "pivot:2"."""
    return f"pivot:{int(pivot_stage)}"


def parse_pivot_label(text: str) -> int | None:
    """"pivot:2" -> 2; "pivot" -> 2 (default stage); anything else -> None."""
    t = str(text or "").strip().lower()
    if t == "pivot":
        return 2
    if t.startswith("pivot:"):
        try:
            s = int(t.split(":", 1)[1])
        except ValueError:
            return None
        return s if s > 0 else None
    return None


# ------------------------------------------------------------------ target table
# RL_HOME/target_table.json (written by ``evaluate pick`` / ``evaluate table``, read by the live
# assistant and ``evaluate run --target-table``):
#     {"version": 1, "source": "...", "table": {character class: {crown key: target}}}
# A crown key is a band "lo-hi" (inclusive; ``pick`` writes "0-3" / "4-7") or one crown "5";
# the FIRST key (file order) that matches the crown wins; no match / no row -> FREE. A target is
# a plan ("Curse", "Red+Blue"), "" / "free" (FREE) or a pivot mode "pivot:S".


def crown_matches(key: str, crown: int) -> bool:
    """Target-table crown key ("4-7" inclusive, or "5") matches ``crown``."""
    key = str(key).strip()
    if "-" in key:
        lo, _, hi = key.partition("-")
        try:
            return int(lo) <= crown <= int(hi)
        except ValueError:
            return False
    try:
        return int(key) == crown
    except ValueError:
        return False


def table_target(data: dict, character: str, crown: int) -> str:
    """The target (or "pivot:S") a loaded target table gives ``character`` at ``crown``; FREE
    when it has no entry. Raises on a malformed table / unknown plan (callers decide)."""
    row = ((data or {}).get("table") or {}).get(character) or {}
    for k, t in row.items():
        if crown_matches(k, int(crown)):
            ps = parse_pivot_label(str(t)) if t else None
            if ps is not None:
                return pivot_label(ps)
            return canonical(str(t)) if t and str(t).lower() != "free" else FREE
    return FREE
