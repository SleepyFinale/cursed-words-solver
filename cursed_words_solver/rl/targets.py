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


def sample_target(rng: random.Random, character: str, mix: tuple[float, float, float] = (0.34, 0.33, 0.33)) -> str:
    """FREE / one of the character's themes / any sampleable plan, by the shares in ``mix``
    (normalised). One ``rng.random()`` then (unless FREE) one ``rng.choice``."""
    p_free, p_theme, p_any = (max(0.0, float(x)) for x in mix)
    tot = p_free + p_theme + p_any
    u = rng.random() * (tot if tot > 0 else 1.0)
    if tot <= 0 or u < p_free:
        return FREE
    if u < p_free + p_theme:
        return rng.choice(THEMES.get(character) or SAMPLE_PLANS)
    return rng.choice(SAMPLE_PLANS)


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
