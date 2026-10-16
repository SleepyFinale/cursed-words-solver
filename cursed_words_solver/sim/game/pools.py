"""``ItemPools`` port: shop sticker / stamp rolls (fully unlocked profile)."""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING, Iterable

from cursed_words_solver.sim.game.core import Rng
from cursed_words_solver.sim.game.items import GENERATOR_TAGS, Item, catalog_rows, make_item

if TYPE_CHECKING:  # pragma: no cover
    from cursed_words_solver.sim.game.player import Player

RARE_STICKER_PERCENT = 10
RARE_STAMP_PERCENT = 13
LEGENDARY_PERCENT = 1
_EXCLUDED_RARITIES = frozenset({"Unique", "Weird"})


@lru_cache(maxsize=1)
def _pools() -> tuple[tuple[str, ...], tuple[str, ...], dict[str, tuple[str, ...]], dict[str, tuple[str, ...]], dict[str, str]]:
    stickers: list[str] = []
    stamps: list[str] = []
    by_tag_sticker: dict[str, list[str]] = {}
    by_tag_stamp: dict[str, list[str]] = {}
    rarity: dict[str, str] = {}
    for cls, row in catalog_rows().items():
        r = row.get("rarity") or "Common"
        rarity[cls] = r
        if r in _EXCLUDED_RARITIES:
            continue
        slot = row.get("slot")
        if slot == "sticker":
            stickers.append(cls)
            for t in row.get("tags") or ():
                by_tag_sticker.setdefault(t, []).append(cls)
        elif slot == "stamp":
            stamps.append(cls)
            for t in row.get("tags") or ():
                by_tag_stamp.setdefault(t, []).append(cls)
    return (
        tuple(stickers),
        tuple(stamps),
        {k: tuple(v) for k, v in by_tag_sticker.items()},
        {k: tuple(v) for k, v in by_tag_stamp.items()},
        rarity,
    )


def sticker_pool() -> tuple[str, ...]:
    return _pools()[0]


def stamp_pool() -> tuple[str, ...]:
    return _pools()[1]


def rarity_of(cls: str) -> str:
    return _pools()[4].get(cls, "Common")


def _multiplier(player: "Player", base: int) -> int:
    n = base
    for _ in player.unpacked_of("Genie"):
        n *= 3
    for snail in player.unpacked_of("Snail"):
        n = int(n * snail.rarity_multiplier())
    return n


def rare_sticker_percent(player: "Player") -> int:
    return _multiplier(player, RARE_STICKER_PERCENT)


def rare_stamp_percent(player: "Player") -> int:
    return _multiplier(player, RARE_STAMP_PERCENT)


def legendary_percent(player: "Player") -> int:
    return _multiplier(player, LEGENDARY_PERCENT)


def _pick(rng: Rng, classes: list[str]) -> Item | None:
    if not classes:
        return None
    return make_item(classes[rng.range(0, len(classes))])


def random_sticker(rng: Rng, player: "Player", blacklist: Iterable[str], rarity: str | None = None) -> Item | None:
    """``GetRandomSticker`` (± rarity)."""
    black = set(blacklist)
    src = [c for c in sticker_pool() if c not in black]
    if rarity is not None:
        return _pick(rng, [c for c in src if rarity_of(c) == rarity])
    if rng.range(0, 100) < rare_sticker_percent(player):
        rares = [c for c in src if rarity_of(c) == "Rare"]
        if rares:
            return _pick(rng, rares)
    commons = [c for c in src if rarity_of(c) == "Common"]
    if commons:
        return _pick(rng, commons)
    return _pick(rng, [c for c in src if rarity_of(c) == "Rare"])


def random_stamp(rng: Rng, player: "Player", blacklist: Iterable[str], rarity: str | None = None) -> Item | None:
    """``GetRandomStamp`` (± rarity)."""
    black = set(blacklist)
    src = [c for c in stamp_pool() if c not in black]
    if rarity is not None:
        return _pick(rng, [c for c in src if rarity_of(c) == rarity])
    roll = rng.range(0, 100)
    if roll < legendary_percent(player):
        leg = [c for c in src if rarity_of(c) == "Legendary"]
        if leg:
            return _pick(rng, leg)
    if roll < rare_stamp_percent(player):
        rares = [c for c in src if rarity_of(c) == "Rare"]
        if rares:
            return _pick(rng, rares)
    for r in ("Common", "Rare", "Legendary"):
        got = [c for c in src if rarity_of(c) == r]
        if got:
            return _pick(rng, got)
    return None


def _with_tag(
    rng: Rng,
    player: "Player",
    tags: Iterable[str],
    is_stamp: bool,
    blacklist: set[str],
    rarity: str | None = None,
) -> Item | None:
    """``GetItemWithTag`` (rolled rarity unless forced)."""
    by_tag = _pools()[3] if is_stamp else _pools()[2]
    forced = rarity is not None
    if not forced:
        rare = rng.range(0, 100) < (rare_stamp_percent(player) if is_stamp else rare_sticker_percent(player))
        leg = rng.range(0, 100) < legendary_percent(player)
        rarity = "Legendary" if leg else "Rare" if rare else "Common"
    cands: list[str] = []
    for t in tags:
        for c in by_tag.get(t, ()):
            if c not in cands:
                cands.append(c)
    cands = [c for c in cands if c not in blacklist]
    if not cands:
        return None
    exact = [c for c in cands if rarity_of(c) == rarity]
    if forced:
        return _pick(rng, exact)
    if not exact:
        exact = [c for c in cands if rarity_of(c) != "Legendary"]
    if not exact:
        return _pick(rng, cands)
    return _pick(rng, exact)


def _non_max_upgrade_sticker(rng: Rng, player: "Player", blacklist: set[str]) -> Item | None:
    stickers = player.stickers_list(for_comparison=True)
    if len(stickers) < 5:
        return None
    cands = [
        s for s in stickers
        if s.game_class not in blacklist
        and s.times_upgraded < player.max_upgrade_count(s)
        and (s.rarity != "Unique" or s.game_class == "Frankenstein")
    ]
    if not cands:
        return None
    pick = cands[rng.range(0, len(cands))]
    if pick.game_class == "Frankenstein":
        return make_item(pick.stitched[rng.range(0, 2)].game_class)
    return make_item(pick.game_class)


def build_biased_sticker(
    rng: Rng,
    player: "Player",
    unavailable: list[str],
    *,
    rarity: str | None = None,
    bias_for_build: bool = False,
) -> Item | None:
    """``GetRandomBuildBiasedSticker`` (± rarity)."""
    black = set(unavailable)
    for s in player.stickers_list(for_comparison=True):
        if s.game_class == "Frankenstein" and s.times_upgraded >= player.max_upgrade_count(s):
            black |= {i.game_class for i in s.stitched[:2]}
    if rng.range(0, 10) == 0 and not bias_for_build:
        hit = _with_tag(rng, player, player.unfulfilled_dependency_tags(), False, black, rarity)
        if hit is not None:
            return hit
    upgrade_one_in = 10 if rarity is not None else (6 - len(player.stickers_list(for_comparison=True))) * 5 + 5
    if rng.range(0, upgrade_one_in) == 0 and not bias_for_build:
        hit = _non_max_upgrade_sticker(rng, player, black)
        if hit is not None:
            return hit
    tags = player.ordered_build_synergy_tags()
    for idx in range(3):
        if len(tags) > idx and (rng.range(0, 10) == 0 or bias_for_build):
            hit = _with_tag(rng, player, [tags[idx]], False, black, rarity)
            if hit is not None:
                return hit
    if rng.range(0, 10) == 0:
        if player.run.stage < 2 or not player.has_generator():
            return _with_tag(rng, player, GENERATOR_TAGS, False, black, rarity)
    return random_sticker(rng, player, black, rarity)


def build_biased_stamp(rng: Rng, player: "Player", unavailable: list[str], *, rarity: str | None = None) -> Item | None:
    """``GetRandomBuildBiasedStamp`` (± rarity)."""
    black = set(unavailable)
    if rng.range(0, 10) == 0:
        hit = _with_tag(rng, player, player.unfulfilled_dependency_tags(), True, black, rarity)
        if hit is not None:
            return hit
    tags = player.ordered_build_synergy_tags()
    for idx in range(3):
        if len(tags) > idx and rng.range(0, 10) == 0:
            hit = _with_tag(rng, player, [tags[idx]], True, black, rarity)
            if hit is not None:
                return hit
    if rng.range(0, 10) == 0:
        if player.run.stage < 2 or not player.has_generator():
            return _with_tag(rng, player, GENERATOR_TAGS, True, black, rarity)
    return random_stamp(rng, player, black, rarity)
