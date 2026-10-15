"""Run-level rules ported from Assembly-CSharp (see docs/game-research/run-structure.md).

Pure functions: stage/node progression, encounter targets, payouts, grids per round,
letter / tile-colour weights, shop prices and sell values, boss drafts.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import IntEnum

import numpy as np

from cursed_words_solver.sim.catalog import BossDef, RunCatalog


class Ascension(IntEnum):
    """``AscensionLevel`` — the crown number. Each level includes all lower ones."""

    NONE = 0
    CURSED_BOSSES = 1
    UNKIND_SHOPS = 2
    LOWER_TILE_SCORES = 3
    LOCKED_STAMP_SLOTS = 4
    HARDER_GRID_GENERATION = 5
    LOCKED_STICKER_SLOTS = 6
    ONE_FEWER_GRID = 7
    HARDER_BOSSES = 8


class Node(IntEnum):
    """``NodeType`` — position within a stage."""

    NONE = 0
    SHOP_ZERO = 1
    ENCOUNTER_FIRST = 2
    SHOP_ONE = 3
    ENCOUNTER_SECOND = 4
    SHOP_TWO = 5
    BOSS_DRAFT = 6
    BOSS = 7
    BOSS_REWARD = 8
    MEG_SHOP = 9


ENCOUNTER_NODES = (Node.ENCOUNTER_FIRST, Node.ENCOUNTER_SECOND, Node.BOSS)
SHOP_NODES = (Node.SHOP_ZERO, Node.SHOP_ONE, Node.SHOP_TWO, Node.MEG_SHOP)

# GameStatics (fully unlocked profile: NumbersUnlock → 5 stages).
NUMBER_OF_STAGES = 5
MICHAEL_STAGE = 6
GRIDS_PER_ROUND = 5
GRID_DIMENSION = 5
GRID_REROLLS_PER_ENCOUNTER = 1

# Player inventory arrays.
STICKER_SLOTS = 5
STAMP_SLOTS = 5
CONSUMABLE_SLOTS = 10
CONSUMABLE_SLOTS_WITHOUT_STADIUM = 5

# ShopController stock arrays.
SHOP_STICKER_SLOTS = 4
SHOP_STAMP_SLOTS = 2
SHOP_TILE_SLOTS = 2

_ENCOUNTER_INDEX = {Node.ENCOUNTER_FIRST: 0, Node.ENCOUNTER_SECOND: 1, Node.BOSS: 2}
_ENCOUNTER_MULT = {Node.ENCOUNTER_FIRST: 1.0, Node.ENCOUNTER_SECOND: 1.4, Node.BOSS: 2.0}


def _f32(x: float) -> np.float32:
    return np.float32(x)


def round_to_int(x: float) -> int:
    """``Mathf.RoundToInt`` — round half to even (same as Python ``round``)."""
    return int(round(float(x)))


# ---------------------------------------------------------------------------
# Progression (RunProgress.AdvanceToNextNodeType)
# ---------------------------------------------------------------------------


def next_node(stage: int, node: Node) -> tuple[int, Node]:
    """Next (stage, node). Michael / Meg-shop / secret-boss special cases are the caller's.

    Stage 1 has no ShopZero: None → stage 1 EncounterFirst. After BossReward the stage
    increments and starts at ShopZero. Stage 6 (Michael) skips BossDraft: ShopTwo → Boss.
    """
    if node == Node.MEG_SHOP:
        return stage, Node.BOSS
    if node == Node.NONE:
        return stage + 1, Node.ENCOUNTER_FIRST
    if node == Node.BOSS_REWARD:
        return stage + 1, Node.SHOP_ZERO
    if node == Node.SHOP_TWO and stage == MICHAEL_STAGE:
        return stage, Node.BOSS
    return stage, Node(node + 1)


def is_final_stage_boss(stage: int, node: Node) -> bool:
    return stage == NUMBER_OF_STAGES and node == Node.BOSS


def run_won_after_boss(
    stage: int,
    *,
    ascension: Ascension,
    has_faced_uncursed_boss: bool,
) -> bool:
    """Beating the stage-5 boss ends the run unless every boss so far was cursed.

    ``EncounterController.TryGoToNextGrid``: final stage wins when ascension < CursedBosses
    or the player has faced an uncursed boss. Otherwise the run continues to Michael.
    """
    if stage == MICHAEL_STAGE:
        return True
    if stage != NUMBER_OF_STAGES:
        return False
    return ascension < Ascension.CURSED_BOSSES or has_faced_uncursed_boss


# ---------------------------------------------------------------------------
# Encounter targets, grids, payouts (RunProgress / EncounterController)
# ---------------------------------------------------------------------------


def encounter_target(
    stage: int,
    node: Node,
    ascension: Ascension | int = Ascension.NONE,
    *,
    diving_mask_percent: int = 0,
    has_diving_mask: bool = False,
) -> int:
    """``RunProgress.GetEncounterTarget`` (float32 like Unity's Mathf)."""
    base = 12 * round_to_int(_f32(np.power(_f32(3.8), _f32(stage - 1))))
    progress = _f32(((stage - 1) * 3 + _ENCOUNTER_INDEX[node]) / _f32(14.0))
    ramp = _f32(np.power(progress, _f32(1.2)))
    asc_mult = _f32(1.0) + _f32(int(ascension)) * _f32(0.4) * ramp
    mask_mult = _f32(1.0)
    if has_diving_mask:
        mask_mult = _f32((100 - diving_mask_percent) / _f32(100.0))
        if mask_mult <= 0:
            return 1
    value = _f32(base) * _f32(_ENCOUNTER_MULT[node]) * mask_mult * asc_mult
    return round_to_int(value)


def grids_per_round(
    *,
    ascension: Ascension | int = Ascension.NONE,
    fewer_grids_modification: int = 0,
    extra_grids: int = 0,
) -> int:
    """``EncounterController.GameSetup`` — base 5, Badger boss subtracts its floor value,
    Diya (and Human Boy / Overhand interactions) add ``extra_grids``, crown 7 subtracts 1."""
    total = GRIDS_PER_ROUND - fewer_grids_modification + extra_grids
    if int(ascension) >= Ascension.ONE_FEWER_GRID:
        total -= 1
    return total


@dataclass(frozen=True)
class EncounterPayout:
    clear: int
    unused_grids: int
    boss: int
    ogre: int
    interest: int

    @property
    def total(self) -> int:
        return self.clear + self.unused_grids + self.boss + self.ogre + self.interest


def encounter_payout(
    grids_unused: int,
    *,
    is_boss: bool,
    money_before: int,
    ogre_count: int = 0,
    dragon_count: int = 0,
    do_not_pass_go: bool = False,
) -> EncounterPayout:
    """Money awarded on encounter clear (``TryGoToNextGrid``).

    $10 clear + $2 per unused grid, +$5 boss, +$5 per Ogre on bosses; Dragon pays
    floor(10%) of (money + base payout) per Dragon. See ``OGRE_BONUS_CREDITED``.
    """
    if do_not_pass_go:
        return EncounterPayout(0, 0, 0, 0, 0)
    clear = 10
    unused = grids_unused * 2
    boss = 5 if is_boss else 0
    ogre = 5 * ogre_count if is_boss else 0
    interest = 0
    if dragon_count:
        basis = money_before + clear + unused + boss
        interest = dragon_count * int(np.floor(_f32(basis) * _f32(0.1)))
    return EncounterPayout(clear, unused, boss, ogre, interest)


# Ogre (stamp): wiki says bosses "give double reward money" (+$5 per Ogre on the $5 boss
# bonus). In the decompiled TryGoToNextGrid the "Ogre bonus" is added to the rewards
# panel but never passed to Player.ChangeMoney. Unverified in game — flip if a run
# shows the money arriving.
OGRE_BONUS_CREDITED = False


def credited_payout(p: EncounterPayout, *, ogre_credited: bool | None = None) -> int:
    """Money actually added by ``Player.ChangeMoney``."""
    credit_ogre = OGRE_BONUS_CREDITED if ogre_credited is None else ogre_credited
    return p.clear + p.unused_grids + p.boss + p.interest + (p.ogre if credit_ogre else 0)


# ---------------------------------------------------------------------------
# Grid generation weights (EnglishDefaultAlphabet / ItemPools)
# ---------------------------------------------------------------------------

LETTER_FREQUENCIES: dict[str, int] = {
    "a": 9, "b": 2, "c": 2, "d": 4, "e": 12, "f": 2, "g": 3, "h": 2, "i": 9, "j": 1,
    "k": 1, "l": 4, "m": 2, "n": 6, "o": 8, "p": 2, "q": 1, "r": 6, "s": 4, "t": 6,
    "u": 4, "v": 2, "w": 2, "x": 1, "y": 2, "z": 1,
}
ASCENSION_LETTER_FREQUENCIES: dict[str, int] = {
    "a": 7, "b": 2, "c": 2, "d": 4, "e": 8, "f": 2, "g": 3, "h": 2, "i": 6, "j": 3,
    "k": 3, "l": 4, "m": 2, "n": 6, "o": 6, "p": 2, "q": 2, "r": 6, "s": 4, "t": 6,
    "u": 4, "v": 3, "w": 3, "x": 3, "y": 3, "z": 2,
}
LETTER_VALUES: dict[str, int] = {
    "a": 1, "b": 3, "c": 3, "d": 2, "e": 1, "f": 4, "g": 2, "h": 4, "i": 1, "j": 8,
    "k": 5, "l": 1, "m": 3, "n": 1, "o": 1, "p": 3, "q": 10, "r": 1, "s": 1, "t": 1,
    "u": 1, "v": 4, "w": 4, "x": 8, "y": 4, "z": 10,
}
ASCENSION_LETTER_VALUES: dict[str, int] = {
    "a": 1, "b": 3, "c": 2, "d": 1, "e": 0, "f": 3, "g": 1, "h": 3, "i": 1, "j": 6,
    "k": 4, "l": 1, "m": 3, "n": 1, "o": 1, "p": 2, "q": 8, "r": 1, "s": 0, "t": 1,
    "u": 1, "v": 3, "w": 4, "x": 6, "y": 3, "z": 8,
}

# ItemPools.TileTypeWeightings (consumable / scatter colour roll).
TILE_TYPE_WEIGHTS: dict[str, int] = {
    "normal": 24, "red": 4, "blue": 4, "void": 3, "shiny": 1, "purple": 2,
    "gold": 2, "white": 2, "pink": 2, "green": 2, "cactus": 2,
}
# RunProgress constructor; new colours are added by items (GetNewTileColour).
STARTING_COLOURS = ("red", "blue", "void", "shiny")
UNLOCKABLE_COLOURS = ("purple", "gold", "white", "green", "pink", "cactus")


def letter_values(ascension: Ascension | int) -> dict[str, int]:
    return ASCENSION_LETTER_VALUES if int(ascension) >= Ascension.LOWER_TILE_SCORES else LETTER_VALUES


def random_letter(rng: random.Random, ascension: Ascension | int = Ascension.NONE) -> str:
    """``Alphabet.GetRandomLetterWeighted`` (crown 5+: ``GetRandomLetterAscensionWeighted``)."""
    freqs = (
        ASCENSION_LETTER_FREQUENCIES
        if int(ascension) >= Ascension.HARDER_GRID_GENERATION
        else LETTER_FREQUENCIES
    )
    return _weighted(rng, freqs)


def random_tile_type(
    rng: random.Random,
    available_colours: tuple[str, ...] | list[str] = STARTING_COLOURS,
    *,
    coloured_only: bool = False,
) -> str:
    """``ItemPools.GetRandomTileTypeWeighted`` / ``GetRandomColouredTileTypeWeighted``.

    Note: the uncoloured variant filters on available colours, which never contains
    ``Normal`` — so consumable / scatter tiles always roll a colour in practice.
    """
    allowed = set(available_colours)
    weights = {
        k: v for k, v in TILE_TYPE_WEIGHTS.items()
        if k in allowed and not (coloured_only and k == "normal")
    }
    return _weighted(rng, weights)


def _weighted(rng: random.Random, weights: dict[str, int]) -> str:
    total = sum(weights.values())
    roll = rng.randrange(total)
    for key, w in weights.items():
        if roll < w:
            return key
        roll -= w
    raise AssertionError("unreachable")


# ---------------------------------------------------------------------------
# Shop economics (ShopController / Item)
# ---------------------------------------------------------------------------

# ShopController._tileTypeCosts (TileInStock.Price; Falling Leaf makes every tile $1).
TILE_COSTS: dict[str, int] = {
    "normal": 2, "red": 3, "blue": 3, "void": 2, "shiny": 4, "purple": 3,
    "gold": 3, "white": 3, "green": 3, "cactus": 3, "pink": 3, "glitch": 3,
}

RARE_STICKER_PERCENT = 10
RARE_STAMP_PERCENT = 13
LEGENDARY_PERCENT = 1
FOIL_PERCENT = 1  # Fortune Cookie: 5
BUILD_BIAS_ONE_IN = 10

# ShopController._consumableTileTypeWeightings after GetTotalFrequency with the
# Numbers, Cards and Chess bulk unlocks (each adds +3 Letter and its own glyph at 1).
CONSUMABLE_GLYPH_WEIGHTS: dict[str, int] = {
    "letter": 19, "blank": 1, "number": 1, "joker": 1, "chess": 1,
}


def starting_reroll_price(ascension: Ascension | int, *, meg_shop: bool = False) -> int:
    if meg_shop:
        return 1
    return 2 if int(ascension) >= Ascension.UNKIND_SHOPS else 1


def reroll_price(base_price: int, *, fried_shrimp: bool = False) -> int:
    """``GetRerollPrice`` — base increments by 1 per paid reroll; Fried Shrimp −1."""
    return max(base_price - (1 if fried_shrimp else 0), 0)


def first_item_free(stage: int, node: Node, ascension: Ascension | int) -> bool:
    """Stage-1 ShopOne gives one free (Common-only) pick unless crown ≥ 2."""
    return stage == 1 and node == Node.SHOP_ONE and int(ascension) < Ascension.UNKIND_SHOPS


def item_price(
    base_cost: int,
    *,
    discount: int = 0,
    avocado_count: int = 0,
    northern_cardinal_red: bool = False,
    blessing_of_the_shopkeeper: bool = False,
) -> int:
    """``Item.GetCost`` — (Cost − Discount), ×2 per Avocado, −4 for red items with
    Northern Cardinal, flat $10 with Blessing of the Shopkeeper (applied in item order;
    Blessing wins when present, matching the common inventory order)."""
    price = max(base_cost - discount, 0)
    price *= 2 ** avocado_count
    if northern_cardinal_red:
        price = max(0, price - 4)
    if blessing_of_the_shopkeeper:
        price = 10
    return max(0, price)


def sell_value(money_invested: list[int], *, receipt: bool = False) -> int:
    """``Item.GetSellValue`` — half of the first payment + a quarter of each upgrade."""
    if receipt:
        return max(0, sum(money_invested))
    total = 0
    for i, paid in enumerate(money_invested):
        total += paid // 2 if i == 0 else paid // 4
    return max(0, total)


def max_upgrade_count(*, foil: bool = False, stack_of_pancakes: int = 0, hungry_hippo: bool = False) -> int:
    """``GameStatics.GetMaxUpgradeCount`` — 2 (+2 foil). Stack of Pancakes extends it
    (per-item rule not yet ported; pass the extra levels explicitly)."""
    if hungry_hippo:
        return 99_999_999
    return 2 + (2 if foil else 0) + stack_of_pancakes


# ---------------------------------------------------------------------------
# Boss drafts (RunProgress.GetRandomBossDrafts)
# ---------------------------------------------------------------------------


@dataclass
class BossChoice:
    boss: BossDef
    floor_index: int
    cursed: bool = False
    harder: bool = False

    @property
    def floor_modification(self) -> int:
        return self.boss.floor_modification(self.floor_index, cursed=self.cursed, harder_bosses=self.harder)

    def curse(self) -> None:
        self.cursed = True


@dataclass
class BossDraft:
    options: list[BossChoice] = field(default_factory=list)
    selected: BossChoice | None = None

    def curse_all(self) -> None:
        """``RunProgress.CurseCurrentStageBosses`` / Ogre at BossReward."""
        for c in self.options:
            c.curse()


def on_ogre_acquired(drafts: list[BossDraft], stage: int) -> None:
    """Ogre ``OnAcquire``: curse both options of the current floor (stays cursed if sold)."""
    if 0 < stage <= NUMBER_OF_STAGES:
        drafts[stage - 1].curse_all()


def on_boss_reward_advance(drafts: list[BossDraft], stage: int, *, holds_ogre: bool) -> None:
    """Leaving BossReward while holding Ogre curses the next floor's options."""
    if holds_ogre and stage < NUMBER_OF_STAGES:
        drafts[stage].curse_all()


def cursed_boss_counts(ascension: Ascension | int) -> bool:
    """A cursed-boss win only counts toward Michael at crown >= 1 (``Ascension > None``)."""
    return int(ascension) > Ascension.NONE


def generate_boss_drafts(
    rng: random.Random,
    catalog: RunCatalog,
    ascension: Ascension | int = Ascension.NONE,
    *,
    banned_by_floor: dict[int, set[str]] | None = None,
) -> list[BossDraft]:
    """Five floors of two bosses (no repeats across the run), then Michael alone.

    Crown ≥ 1 curses one random boss per floor. ``banned_by_floor`` mirrors
    ``ChallengeRun.BannedBossModifiers`` (game class names).
    """
    harder = int(ascension) >= Ascension.HARDER_BOSSES
    remaining = [
        b for b in catalog.bosses.values()
        if not b.is_secret_character and b.game_class != "MichaelBoss"
    ]
    drafts: list[BossDraft] = []
    for floor in range(NUMBER_OF_STAGES):
        banned = (banned_by_floor or {}).get(floor, set())
        candidates = [
            b for b in remaining
            if b.game_class not in banned and floor not in b.banned_floor_indexes
        ]
        first = candidates.pop(rng.randrange(len(candidates)))
        second = candidates.pop(rng.randrange(len(candidates)))
        remaining = [b for b in remaining if b not in (first, second)]
        draft = BossDraft([
            BossChoice(first, floor, harder=harder),
            BossChoice(second, floor, harder=harder),
        ])
        if int(ascension) >= Ascension.CURSED_BOSSES:
            draft.options[rng.randrange(2)].curse()
        drafts.append(draft)
    michael = catalog.bosses.get("MichaelBoss")
    if michael is not None:
        drafts.append(BossDraft([BossChoice(michael, MICHAEL_STAGE - 1, harder=harder)]))
    return drafts


# ---------------------------------------------------------------------------
# What the player can see during a round (AI observation; never future floors)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VisibleBoss:
    game_class: str
    boss_id: str
    cursed: bool
    floor_modification: int


@dataclass(frozen=True)
class RoundPreview:
    """Map-screen info: the round's three targets and the current floor's boss options.

    Boss targets are before boss effects (e.g. Toothed Whale scales its own target).
    """

    stage: int
    targets: tuple[int, int, int]  # EncounterFirst, EncounterSecond, Boss
    boss_options: tuple[VisibleBoss, ...]


def round_preview(
    stage: int,
    ascension: Ascension | int,
    drafts: list[BossDraft],
    *,
    diving_mask_percent: int = 0,
    has_diving_mask: bool = False,
) -> RoundPreview:
    targets = tuple(
        encounter_target(
            stage, n, ascension,
            diving_mask_percent=diving_mask_percent, has_diving_mask=has_diving_mask,
        )
        for n in ENCOUNTER_NODES
    )
    draft = drafts[stage - 1] if 0 < stage <= len(drafts) else BossDraft()
    options = tuple(
        VisibleBoss(c.boss.game_class, c.boss.boss_id, c.cursed, c.floor_modification)
        for c in draft.options
    )
    return RoundPreview(stage, targets, options)  # type: ignore[arg-type]
