"""DLC item scoring ports (``ApplyTileBonus`` / ``ApplyWordBonus`` / ``ApplySubmissionBonus``).

One function per new game class, registered into the same hook tables as
``items.py``. Word hooks see ``ctx.tiles`` = the word group's tiles (the game's
``tiles``) and ``ctx.all_tiles`` = every group's tiles (``allTiles``); tile hooks see
the concatenated groups (``list4``); submission hooks see the whole path.

Dice items roll ``UnityEngine.Random`` during scoring. With ``ctx.rng`` set (a
``random.Random``) each roll is sampled; otherwise the hook applies the roll's
*expected* effect (probability-weighted bonus) so the search ranks paths by expected
score. Either way the result is flagged ``nondeterministic``.
"""

from __future__ import annotations

import math

import numpy as np

from cursed_words_solver.engine import dlc_rules as R
from cursed_words_solver.engine import packet as P
from cursed_words_solver.engine.items import _mult, _add, _tadd, _tmul, submission, tile, word
from cursed_words_solver.engine.model import (
    G_BRACKET,
    G_DICE,
    G_DOMINO,
    G_FRACTION,
    G_HYPER,
    G_ITEM,
    G_LETTER,
    G_NUMBER,
    G_WIRE,
    G_ZODIAC,
    NORMAL,
    VOWELS,
    ZODIAC_ANIMALS,
    ZODIAC_ELEMENTS,
    ZODIAC_ORDER,
    ETile,
    ItemInst,
    zodiac_element,
    zodiac_position,
)
from cursed_words_solver.engine.state import Ctx, Step, WordBonus

# Item.PeopleCount set in each class's constructor (NaughtyList).
PEOPLE_COUNT = {
    "Astronaut": 1, "Baby": 1, "Beefeater": 1, "BlessingOfTheFairies": 1, "Bride": 1,
    "Builder": 1, "Cartwheeler": 1, "Clown": 1, "Dancer": 1, "DNDPlayer": 1,
    "DoubleVision": 1, "Dracula": 1, "Electrician": 1, "Elevator": 3, "FoodPoisoning": 1,
    "FrostBite": 1, "Genie": 1, "HeadInTheClouds": 1, "HeadTrauma": 1, "IDCard": 1,
    "Joker": 1, "Juggler": 1, "KingOfTheBridge": 1, "Mage": 1, "Meditator": 1,
    "Mermaid": 1, "NaughtyList": 1, "Parachute": 1, "PartyTime": 1, "PopStar": 1,
    "PowerOfFriendship": 2, "Programmer": 1, "Racehorse": 1, "RockClimber": 1,
    "Rollercoaster": 4, "ScaredToLook": 1, "Scientist": 1, "Shrugger": 1,
    "SluggishZombie": 1, "SlySpy": 1, "Snowboarder": 1, "Supervillain": 1, "Surfer": 1,
    "TemperTantrum": 1, "TileNinja": 1, "Twinsies": 2, "Weightlifter": 1, "Witch": 1,
    "Wrestlers": 2,
}

L_WIRE, I_WIRE, T_WIRE = "╚", "║", "╦"
CONSUMABLE_SLOTS = 10


# ------------------------------------------------------------------ small helpers


def _fld(inst: ItemInst, name: str, default=None):
    """Mutable game field: the per-submit value if a hook changed it, else the export."""
    key = "f:" + name
    if key in inst.state:
        return inst.state[key]
    return R.item_field(inst, name, default)


def _setf(inst: ItemInst, name: str, value) -> None:
    inst.state["f:" + name] = value


def _int(v, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _element_field(inst: ItemInst, name: str, default: str) -> str:
    v = _fld(inst, name, default)
    if isinstance(v, int):
        return ("", "fire", "water", "air", "earth")[v] if 0 <= v <= 4 else ""
    return str(v or "").strip().lower().replace("none", "")


def _is_symbol_element(symbol: str, element: str) -> bool:
    return bool(element) and symbol in ZODIAC_ELEMENTS.get(element, ())


def _zodiac(tiles) -> list[ETile]:
    return [t for t in tiles if t.glyph == G_ZODIAC]


def _vl(ctx: Ctx, t: ETile, lst) -> bool:
    """``IsDisplayingAsVariableLetter(null, lst)``."""
    plan = ctx.plan
    if plan is None:
        return False
    return bool(plan.variable_letter(t, lst, (), False))


def _curse_types(ctx: Ctx, t: ETile) -> list[str]:
    """``Tile.GetCurseTypes()`` (no word list)."""
    plan = ctx.plan
    vl = bool(plan.variable_letter(t)) if plan is not None else False
    return t.curse_types(vl)


def _add_consumables(step: Step, n: int) -> None:
    step.consumables = min(CONSUMABLE_SLOTS, step.consumables + n)


def _wrapping(ctx: Ctx, tiles) -> bool:
    """GetTilesAdjacentToCoordinates' wrap flag: Hungry Snake on the path or unpacked."""
    if ctx.hungry_snake:
        return True
    return any(t.glyph == G_ITEM and t.item == "hungry_snake" for t in tiles)


# ------------------------------------------------------------------ dice


def _chance(ctx: Ctx, k: float, sides: int) -> float:
    """P(``Random.Range(1, sides + 1) <= k``): sampled with ``ctx.rng``, else exact."""
    p = min(max(math.floor(k), 0), sides) / sides
    if 0.0 < p < 1.0:
        ctx.nondeterministic = True
    rng = getattr(ctx, "rng", None)
    if rng is not None and 0.0 < p < 1.0:
        return 1.0 if rng.randint(1, sides) <= k else 0.0
    return p


def _dice_total(tiles) -> int:
    """``Dice.GetPlayerTotalFromDiceRollInfo(MakeCommunalDiceRollCheck(tiles))``."""
    return sum(t.dice_number() for t in tiles if t.glyph == G_DICE)


def _mult_p(step: Step, percent: float, p: float) -> None:
    if p <= 0.0:
        return
    if p >= 1.0:
        _mult(step, percent)
    else:
        step.wb = WordBonus(int(round(100 + (percent - 100) * p)), True)  # ints only: floats are ±inf


def _tmul_p(step: Step, i: int, factor: int, p: float) -> None:
    if p <= 0.0:
        return
    if p >= 1.0:
        _tmul(step, i, factor)
    else:
        step.ts[i] = P.scale(step.ts[i], 1.0 + (factor - 1) * p)
        step.float_mult = True


def _tadd_p(step: Step, i: int, amount: int, p: float) -> None:
    if p <= 0.0:
        return
    _tadd(step, i, amount if p >= 1.0 else int(round(amount * p)))


def _money_p(step: Step, amount: int, p: float) -> None:
    if p > 0.0:
        step.money += amount if p >= 1.0 else int(round(amount * p))


# ------------------------------------------------------------------ wires


def wire_viable(ctx: Ctx, a: ETile, b: ETile) -> bool:
    """``Wires.AreViablePowerSources``."""
    if a.glyph == G_WIRE or b.glyph == G_WIRE:
        return False
    if ctx.has_unpacked("PowerOfFriendship") and a.tile_type != NORMAL and a.tile_type == b.tile_type:
        return True
    if ctx.has_unpacked("PowerOfLove"):
        ca, cb = _curse_types(ctx, a), _curse_types(ctx, b)
        if ca and cb and set(ca) == set(cb):
            return True
    if a.glyph != b.glyph:
        return False
    return a.srep == b.srep


def wire_connected(ctx: Ctx, tiles) -> bool:
    """``Wires.IsConnected``."""
    if len(tiles) < 3:
        return False
    if not any(t.glyph == G_WIRE for t in tiles[1:-1]):
        return False
    return wire_viable(ctx, tiles[0], tiles[-1])


def _wires(tiles) -> list[ETile]:
    return [t for t in tiles if t.glyph == G_WIRE]


def _lit(tiles) -> bool:
    syms = {t.symbol for t in tiles if t.glyph == G_WIRE}
    return L_WIRE in syms and I_WIRE in syms and T_WIRE in syms


# ------------------------------------------------------------------ hyper / lowercase / misc word hooks


@word("Alien")
def _alien(inst, step, ctx):
    tiles = ctx.tiles
    if tiles and all(t.glyph == G_HYPER for t in tiles):
        _mult(step, 100 * len(tiles))


@word("AudioMixerItem")
def _audio_mixer(inst, step, ctx):
    n = sum(1 for t in ctx.tiles if t.glyph == G_LETTER and t.letter in ("d", "o", "m", "i", "n"))
    if n > 0:
        _add_consumables(step, n)


@word("Baby")
def _baby(inst, step, ctx):
    if ctx.tiles and all(t.is_lowercase_letter() for t in ctx.tiles):
        _mult(step, 100 * inst.var())


@word("BettingSlip")
def _betting_slip(inst, step, ctx):
    if ctx.tiles:
        _mult_p(step, inst.var(), _chance(ctx, _dice_total(ctx.tiles), 20))


@word("Casino")
def _casino(inst, step, ctx):
    if any(t.glyph == G_DICE for t in ctx.tiles):
        _money_p(step, 2, _chance(ctx, _dice_total(ctx.tiles), 20))


@word("HoleInOne")
def _hole_in_one(inst, step, ctx):
    if any(t.glyph == G_DICE for t in ctx.tiles):
        _mult_p(step, 1000, _chance(ctx, _dice_total(ctx.tiles), 100))


@word("WheelOfFortune")
def _wheel_of_fortune(inst, step, ctx):
    # Only breaks itself / upgrades a random sticker afterwards: no score this submit.
    if not _fld(inst, "Broken", False) and any(t.glyph == G_DICE for t in ctx.tiles):
        ctx.nondeterministic = True


@word("Chains")
def _chains(inst, step, ctx):
    tiles = ctx.tiles
    if tiles and tiles[0].glyph == G_HYPER and tiles[-1].glyph == G_HYPER:
        _mult(step, 100 * inst.var())


@word("ChickenFoot")
def _chicken_foot(inst, step, ctx):
    tiles = ctx.tiles
    if (len(tiles) >= 3 and (tiles[0].glyph != G_DOMINO or tiles[-1].glyph != G_DOMINO)
            and any(t.glyph == G_DOMINO for t in tiles)):
        _mult(step, inst.var())


@word("CrossedFlags")
def _crossed_flags(inst, step, ctx):
    n = 0
    for t in ctx.tiles:
        if t.glyph == G_DOMINO:
            a, b = t.domino()
            if a == b and a >= 0:
                n += 1
    if n > 0:
        step.money += n


@word("Eyes")
def _eyes(inst, step, ctx):
    if ctx.tiles and sum(1 for t in ctx.tiles if t.glyph == G_DICE and t.dice_number() == 1) >= 2:
        _mult(step, 100 * inst.var())


@word("Frisbee")
def _frisbee(inst, step, ctx):
    if ctx.tiles and len({t.dice_number() for t in ctx.tiles if t.glyph == G_DICE}) == 6:
        _mult(step, 200)


@word("HotDog")
def _hot_dog(inst, step, ctx):
    n = sum(len(t.symbol) for t in ctx.tiles if t.glyph == G_BRACKET) // 2
    if n > 0:
        f = np.float32(math.pow(float(np.float32(inst.var()) / np.float32(100.0)), n))
        _mult(step, int(np.float32(f * np.float32(100.0))))


@word("Meditator")
def _meditator(inst, step, ctx):
    stickers = [s for s in ctx.stickers if s is not None]
    if not stickers:
        return
    rest = [s for s in stickers if s.cls != "LeftHumanHand"]
    if not rest or all(s.level(0) == rest[0].level(0) for s in rest):
        _mult(step, 200)


@word("Mermaid")
def _mermaid(inst, step, ctx):
    if sum(1 for t in ctx.tiles if _vl(ctx, t, ctx.all_tiles)) >= 3:
        _mult(step, inst.var())


@word("MexicanTrain")
def _mexican_train(inst, step, ctx):
    n = 0
    for t in ctx.tiles:
        if t.glyph == G_DOMINO:
            n += sum(t.domino())
        elif t.glyph == G_DICE:
            n += t.dice_number()
    if n >= 20:
        _mult(step, 100 * inst.var())


@word("MoonRock")
def _moon_rock(inst, step, ctx):
    el = _element_field(inst, "ChosenElement", "")
    n = sum(1 for t in _zodiac(ctx.tiles) if _is_symbol_element(t.symbol, el))
    if n > 0:
        step.money += n


@word("Owl")
def _owl(inst, step, ctx):
    tiles = ctx.tiles
    if not tiles:
        return
    plan = ctx.plan
    for t in tiles:
        if plan is not None and plan.is_cursed_in(t, ctx.all_tiles, ()):
            return
    n = _int(_fld(inst, "WordsSubmitted", 0)) + 1
    _setf(inst, "WordsSubmitted", n)
    _mult(step, 100 + n * 5)


@word("Platform6")
def _platform6(inst, step, ctx):
    doms = [t for t in ctx.tiles if t.glyph == G_DOMINO]
    if not doms:
        return
    lowest = 6
    for t in doms:
        for v in t.domino():
            if v < lowest:
                lowest = v
    if lowest != 1:
        _mult(step, 100 * lowest)


@word("Plunger")
def _plunger(inst, step, ctx):
    for t in ctx.tiles:
        if t.is_number() and t.number is not None and t.number < 0:
            _mult(step, 100 * t.number)
            break


@word("Pretzel")
def _pretzel(inst, step, ctx):
    n = 0
    scopes: list[list] = []  # [opening tile, count]
    for t in ctx.tiles:
        if t.glyph != G_BRACKET:
            for s in scopes:
                s[1] += 1
            continue
        for b in t.brackets():
            if b and b[0] == ")":
                if not scopes:
                    continue
                s = scopes.pop()
                if s[1] >= 4:
                    n += 1
            else:
                scopes.append([t, 0])
        for s in scopes:
            if s[0] is not t:
                s[1] += 1
    if n > 0:
        step.money += n


@word("Racehorse")
def _racehorse(inst, step, ctx):
    acc = _int(_fld(inst, "AccumulatedValue", 0))
    if ctx.tiles and acc != 0:
        _add(step, acc)


@word("RailwayTrack")
def _railway_track(inst, step, ctx):
    cur = best = 0
    for t in ctx.tiles:
        if t.glyph == G_DOMINO:
            cur += 1
            continue
        best = max(best, cur)
        cur = 0
    best = max(best, cur)
    if best != 1:
        _mult(step, 100 * best)


@word("Raven")
def _raven(inst, step, ctx):
    n = sum(1 for s in ctx.stickers if s is not None and s.state.get("_foil"))
    if n > 0:
        f = np.float32(math.pow(float(np.float32(inst.var()) / np.float32(100.0)), n))
        _mult(step, int(np.float32(f * np.float32(100.0))))


@word("SkullAndCrossbones")
def _skull(inst, step, ctx):
    if sum(1 for t in ctx.grid.available if t.glyph == G_HYPER) >= 5:
        _mult(step, inst.var())


@word("Sloth")
def _sloth(inst, step, ctx):
    if not ctx.tiles:
        return
    total = np.float32(0.0)
    for t in ctx.tiles:
        if t.glyph == G_FRACTION:
            total = np.float32(total + np.float32(t.fraction_float()))
        elif t.glyph == G_NUMBER:
            total = np.float32(total + np.float32(t.number or 0))
    if total <= -7:
        _mult(step, -inst.var() * 100)


@word("Taxi")
def _taxi(inst, step, ctx):
    if sum(1 for t in ctx.tiles if t.glyph == G_DOMINO) >= 3:
        _mult(step, inst.var())


@word("Tornado")
def _tornado(inst, step, ctx):
    grid_types: set[str] = set()
    for t in ctx.grid.available:
        grid_types.update(_curse_types(ctx, t))
    for t in ctx.tiles:
        grid_types.difference_update(_curse_types(ctx, t))
    if len(grid_types) != 1:
        _mult(step, 100 * len(grid_types))


@word("Tractor")
def _tractor(inst, step, ctx):
    tiles = ctx.tiles
    if len(tiles) < 3 or tiles[0].glyph == G_DOMINO or tiles[-1].glyph == G_DOMINO:
        return
    if any(t.glyph == G_DOMINO for t in tiles[1:-1]):
        _mult(step, 200)


@word("Bat")
def _bat(inst, step, ctx):
    _mult(step, -100)


def _bingo_line(ctx: Ctx, tiles) -> bool:
    coords = {(t.x, t.y) for t in tiles}
    if not tiles or len(coords) != len(tiles):
        return False
    w, h = ctx.grid.width, ctx.grid.height
    if len(coords) == w:
        for y in range(h):
            if coords == {(x, y) for x in range(w)}:
                return True
    if len(coords) == h:
        for x in range(w):
            if coords == {(x, y) for y in range(h)}:
                return True
    if w == h and len(coords) == w:
        if coords == {(i, i) for i in range(w)} or coords == {(w - 1 - i, i) for i in range(w)}:
            return True
    return False


@word("Bingo")
def _bingo(inst, step, ctx):
    if ctx.tiles and _bingo_line(ctx, ctx.tiles):
        _mult(step, inst.var())


@word("BoonOfTheCapybara")
def _boon_capybara(inst, step, ctx):
    if ctx.tiles:
        _mult(step, inst.var())


@word("BoonOfTheCobra")
def _boon_cobra(inst, step, ctx):
    if ctx.tiles and len(ctx.tiles) >= inst.var():
        _add(step, (inst.var() - 6) * 77)


@word("BoonOfTheFox")
def _boon_fox(inst, step, ctx):
    _mult(step, 100 + _int(_fld(inst, "MoneyStolen", 0)) * inst.var())


@word("BoonOfTheHyena")
def _boon_hyena(inst, step, ctx):
    _mult(step, 100 + _int(_fld(inst, "ItemsSold", 0)) * 10)


@word("BoonOfTheMorayEel")
def _boon_moray(inst, step, ctx):
    _add(step, _int(_fld(inst, "TilesEaten", 0)) * 5)


@word("BoonOfTheYetiCrab")
def _boon_yeti(inst, step, ctx):
    _mult(step, 100 + _int(_fld(inst, "ColoursRemoved", 0)) * 2)


@word("Bride")
def _bride(inst, step, ctx):
    if any(t.forever for t in ctx.tiles) and any(t.custom_bag for t in ctx.tiles):
        _mult(step, inst.var() * 100)


@word("Cigarette")
def _cigarette(inst, step, ctx):
    if sum(1 for t in ctx.tiles if t.value < 0) >= 3:
        _mult(step, 100 * inst.var())


@word("Comet")
def _comet(inst, step, ctx):
    if len(_zodiac(ctx.tiles)) >= 2:
        _mult(step, 200)


@word("DesertIsland")
def _desert_island(inst, step, ctx):
    tiles = ctx.tiles
    e1 = _element_field(inst, "ChosenElement1", "air")
    e2 = _element_field(inst, "ChosenElement2", "water")
    if (tiles and tiles[0].glyph == G_ZODIAC and tiles[-1].glyph == G_ZODIAC
            and _is_symbol_element(tiles[0].symbol, e1) and _is_symbol_element(tiles[-1].symbol, e2)):
        _mult(step, inst.var() * 100)


@word("EmptyPlate")
def _empty_plate(inst, step, ctx):
    _mult(step, inst.var() * 100)


@word("Gloves")
def _gloves(inst, step, ctx):
    if not ctx.tiles:
        return
    count = _int(_fld(inst, "Count", 0)) + sum(1 for t in ctx.grid.available if t.glyph == G_HYPER)
    _setf(inst, "Count", count)
    if count > 0:
        _mult(step, 100 + count)


@word("GoldStar")
def _gold_star(inst, step, ctx):
    tiles = ctx.tiles
    if tiles and tiles[0].glyph == G_ZODIAC and tiles[-1].glyph == G_ZODIAC and tiles[0].symbol == tiles[-1].symbol:
        _mult(step, inst.var() * 100)


@word("Horoscope")
def _horoscope(inst, step, ctx):
    if not ctx.tiles:
        return
    sign = str(_fld(inst, "_chosenHoroscope", ZODIAC_ORDER[0]) or ZODIAC_ORDER[0])
    acc = _int(_fld(inst, "AccumulatedValue", 0))
    if any(t.glyph == G_ZODIAC and t.symbol == sign for t in ctx.tiles):
        acc += inst.var()
        _setf(inst, "AccumulatedValue", acc)
    if acc > 0:
        _add(step, acc)


@word("Hyacinth")
def _hyacinth(inst, step, ctx):
    syms = {t.symbol for t in _zodiac(ctx.tiles)}
    found: list[ETile] = []
    for el, members in ZODIAC_ELEMENTS.items():
        if all(m in syms for m in members):
            found = [t for t in _zodiac(ctx.tiles) if zodiac_element(t.symbol) == el]
            break
    if len(found) >= 3:
        _mult(step, inst.var() * 100)


@word("Joystick")
def _joystick(inst, step, ctx):
    if ctx.tiles and _is_tetromino(ctx.tiles):
        _mult(step, inst.var() * 100)


@word("Karategi")
def _karategi(inst, step, ctx):
    _mult(step, _int(_fld(inst, "Multiplier", 100), 100))


@word("YinYang")
def _yin_yang(inst, step, ctx):
    _mult(step, _int(_fld(inst, "Multiplier", 100), 100))


@word("Koala")
def _koala(inst, step, ctx):
    tiles = ctx.tiles
    if tiles and tiles[0].value < 0 and tiles[-1].value < 0:
        _mult(step, inst.var())


@word("Ladder")
def _ladder(inst, step, ctx):
    depth = R.max_bracket_depth(ctx.tiles)
    if depth != 1:
        _mult(step, 100 * depth)


@word("LifeBelt")
def _life_belt(inst, step, ctx):
    n = 0
    open_ = False
    for t in ctx.tiles:
        s = t.symbol if t.glyph == G_BRACKET else ""
        if s and s[0] == "(":
            open_ = True
        elif s and s[0] == ")" and open_:
            n += 1
            open_ = False
        else:
            open_ = False
    total = _int(_fld(inst, "EmptyPairsSubmitted", 0)) + n
    _setf(inst, "EmptyPairsSubmitted", total)
    _mult(step, 100 + total * 5)


@word("LucrativeInvestment")
def _lucrative(inst, step, ctx):
    if not ctx.tiles:
        return
    count = _int(_fld(inst, "Count", 0))
    for t in ctx.tiles:
        if t.forever:
            count += 1
            if count % 5 == 0:
                step.money += count // 5
    _setf(inst, "Count", count)


def _same_element(tiles) -> bool:
    el = ""
    for t in tiles:
        if t.glyph == G_ZODIAC:
            e = zodiac_element(t.symbol)
            if not el:
                el = e
            elif e != el:
                return False
    return True


@word("Mage")
def _mage(inst, step, ctx):
    if ctx.tiles and _zodiac(ctx.tiles) and _same_element(ctx.tiles):
        _mult(step, inst.var())


@word("Medallion")
def _medallion(inst, step, ctx):
    el = _element_field(inst, "_chosenElement", "fire")
    if ctx.tiles and any(zodiac_element(t.symbol) == el for t in _zodiac(ctx.tiles)):
        step.money += 2


@word("MoneyAutomobile")
def _money_automobile(inst, step, ctx):
    seen: list[str] = []
    for t in ctx.tiles:
        if t.glyph == G_LETTER:
            s = t.srep
            if s in VOWELS and s not in seen:
                seen.append(s)
    if seen:
        step.money += len(seen)


@word("NaughtyList")
def _naughty_list(inst, step, ctx):
    n = sum(PEOPLE_COUNT.get(it.cls, 0) for it in ctx.all_items())
    for t in ctx.tiles:
        if t.glyph == G_ITEM and t.item:
            from cursed_words_solver.engine.model import make_item

            cls = make_item(t.item).cls
            if PEOPLE_COUNT.get(cls, 0) > 0 and not (inst.is_scattered and inst.scatter_idx == t.idx):
                n += PEOPLE_COUNT[cls]
    if n >= 1:
        _mult(step, 100 + n * 25)


@word("PrayerBeads")
def _prayer_beads(inst, step, ctx):
    if ctx.tiles and len({zodiac_element(t.symbol) for t in _zodiac(ctx.tiles)} - {""}) >= 2:
        _mult(step, inst.var())


def _elements_present(tiles) -> int:
    return sum(1 for el in ("air", "earth", "fire", "water")
               if any(_is_symbol_element(t.symbol, el) for t in _zodiac(tiles)))


@word("Quatrefoil")
def _quatrefoil(inst, step, ctx):
    if _elements_present(ctx.tiles) >= 4:
        _mult(step, 200)


@word("Trident")
def _trident(inst, step, ctx):
    if _elements_present(ctx.tiles) >= 3:
        _mult(step, inst.var() * 100)


@word("Shrugger")
def _shrugger(inst, step, ctx):
    tiles = ctx.tiles
    neg = any(t.glyph == G_NUMBER and (t.number or 0) < 0 for t in tiles)
    pos = any(t.glyph == G_NUMBER and (t.number or 0) > 0 for t in tiles) or any(t.glyph == G_FRACTION for t in tiles)
    if neg and pos:
        _mult(step, inst.var())


@word("SmoothJazz")
def _smooth_jazz(inst, step, ctx):
    if ctx.tiles and all(t.glyph == G_LETTER and t.letter in "abcdefg" and len(t.letter) == 1 for t in ctx.tiles):
        _mult(step, inst.var() * 100)


@word("TollingBell")
def _tolling_bell(inst, step, ctx):
    bonus = _int(_fld(inst, "WordScoreBonus", 0))
    if ctx.tiles and bonus != 0:
        _add(step, bonus)


@word("TreeRings")
def _tree_rings(inst, step, ctx):
    tiles = ctx.tiles
    if tiles and tiles[0].glyph == G_BRACKET and tiles[-1].glyph == G_BRACKET:
        _mult(step, inst.var())


@word("Tsukimi")
def _tsukimi(inst, step, ctx):
    el = _element_field(inst, "ChosenElement", "")
    tiles = ctx.tiles
    if tiles and el and all(t.glyph == G_ZODIAC and _is_symbol_element(t.symbol, el) for t in tiles):
        _mult(step, 100 * len(tiles))


@word("Weightlifter")
def _weightlifter(inst, step, ctx):
    if not ctx.words or not ctx.words[0]:
        return
    f = np.float32(len(ctx.tiles)) / np.float32(len(ctx.words[0]))
    if f != np.float32(1.0):
        _mult(step, int(np.float32(f * np.float32(100.0))))


@word("WinterCoat")
def _winter_coat(inst, step, ctx):
    if all(t.value <= 0 for t in ctx.tiles):
        _mult(step, -200)


@word("Zoologist")
def _zoologist(inst, step, ctx):
    if ctx.tiles and sum(1 for t in _zodiac(ctx.tiles) if t.symbol in ZODIAC_ANIMALS) >= 3:
        _mult(step, inst.var() * 100)


# ------------------------------------------------------------------ tile hooks


def _dice_tile_roll(ctx: Ctx, t: ETile, sides: int) -> float:
    return _chance(ctx, t.dice_number(), sides)


@tile("BadmintonRacket")
def _badminton(inst, step, i, ctx):
    t = ctx.tiles[i]
    if t.glyph == G_DICE:
        _tmul_p(step, i, inst.var(), _dice_tile_roll(ctx, t, 10))


@tile("CricketBat")
def _cricket_bat(inst, step, i, ctx):
    t = ctx.tiles[i]
    if t.glyph == G_DICE:
        _tadd_p(step, i, inst.var(), _dice_tile_roll(ctx, t, 6))


@tile("Butterfly")
def _butterfly(inst, step, i, ctx):
    if _vl(ctx, ctx.tiles[i], ctx.tiles):
        _tmul(step, i, inst.var())


@tile("Duck")
def _duck(inst, step, i, ctx):
    tiles = ctx.tiles
    if not any(t.is_number() for t in tiles):
        return
    total = np.float32(0.0)
    for t in tiles:
        if t.glyph == G_NUMBER:
            total = np.float32(total + np.float32(t.number or 0))
        elif t.glyph == G_FRACTION:
            total = np.float32(total + np.float32(t.fraction_float()))
    target = _int(_fld(inst, "_targetNumber", 0))
    if not abs(float(total) - target) > 0.001:
        _add(step, inst.var())


@tile("FigureEightKnot")
def _figure_eight(inst, step, i, ctx):
    t = ctx.tiles[i]
    if t.glyph == G_DOMINO and sum(t.domino()) >= 8:
        _tmul(step, i, inst.var())


@tile("FuelPump")
def _fuel_pump(inst, step, i, ctx):
    tiles = ctx.tiles
    if (i == 0 or i == len(tiles) - 1) and wire_connected(ctx, tiles):
        n = len(_wires(tiles))
        if n > 0:
            _tmul(step, i, n)


@tile("Garlic")
def _garlic(inst, step, i, ctx):
    if ctx.tiles[i].glyph == G_HYPER:
        _tadd(step, i, inst.var())


@tile("LightBulb")
def _light_bulb(inst, step, i, ctx):
    if ctx.tiles[i].glyph == G_WIRE and wire_connected(ctx, ctx.tiles):
        _tadd(step, i, inst.var(1))


@tile("MagicBeans")
def _magic_beans(inst, step, i, ctx):
    if _vl(ctx, ctx.tiles[i], ctx.tiles):
        n = _int(_fld(inst, "WobblyCount", 1), 1)
        _tadd(step, i, n)
        _setf(inst, "WobblyCount", n + 1)


@tile("MagnifyingGlass")
def _magnifying_glass(inst, step, i, ctx):
    if ctx.tiles[i].glyph == G_LETTER:
        _tadd(step, i, inst.var(1))


@tile("Megaphone")
def _megaphone(inst, step, i, ctx):
    tiles = ctx.tiles
    if tiles[i].glyph != G_WIRE:
        return
    n = sum(inst.var() for t in tiles[:i] if t.glyph == G_WIRE)
    if n > 0:
        _tadd(step, i, n)


@tile("NestingDolls")
def _nesting_dolls(inst, step, i, ctx):
    if R.bracket_depth(ctx.tiles, i) != 0:
        _tadd(step, i, inst.var(1))


@tile("NutAndBolt")
def _nut_and_bolt(inst, step, i, ctx):
    tiles = ctx.tiles
    if tiles[i].glyph != G_WIRE:
        return
    n = 0
    if i >= 1 and tiles[i - 1].glyph == G_WIRE:
        n += inst.var()
    if i < len(tiles) - 1 and tiles[i + 1].glyph == G_WIRE:
        n += inst.var()
    if n > 0:
        _tadd(step, i, n)


@tile("Orangutan")
def _orangutan(inst, step, i, ctx):
    if ctx.tiles[i].glyph == G_BRACKET:
        n = R.non_bracket_tiles_contained(ctx.tiles, i)
        if n != 0:
            _tmul(step, i, n)


@tile("Popcorn")
def _popcorn(inst, step, i, ctx):
    d = R.bracket_depth(ctx.tiles, i)
    if d != 0:
        _tadd(step, i, d * inst.var())


@tile("PostOffice")
def _post_office(inst, step, i, ctx):
    tiles = ctx.tiles
    n = sum(1 for t in tiles if t.glyph == G_LETTER)
    if tiles[i].glyph == G_DOMINO and n != 1:
        _tmul(step, i, n)


@tile("SafetyGoggles")
def _safety_goggles(inst, step, i, ctx):
    tiles = ctx.tiles
    if tiles[i].glyph != G_WIRE:
        return
    n = 1
    if i >= 1 and tiles[i - 1].glyph == G_WIRE:
        n *= inst.var()
    if i < len(tiles) - 1 and tiles[i + 1].glyph == G_WIRE:
        n *= inst.var()
    if n > 0:
        _tmul(step, i, n)


@tile("Saw")
def _saw(inst, step, i, ctx):
    if ctx.tiles[i].glyph == G_WIRE and wire_connected(ctx, ctx.tiles):
        _tmul(step, i, inst.var())


@tile("Skunk")
def _skunk(inst, step, i, ctx):
    adj = ctx.grid.adjacent(ctx.tiles[i], _wrapping(ctx, ctx.tiles))
    if any(t.glyph == G_HYPER for t in adj):
        _tmul(step, i, inst.var())


@tile("SpiderWeb")
def _spider_web(inst, step, i, ctx):
    adj = ctx.grid.adjacent(ctx.tiles[i], _wrapping(ctx, ctx.tiles))
    n = sum(1 for t in adj if t.glyph == G_HYPER)
    if n:
        _tadd(step, i, n * inst.var())


@tile("Snowboarder")
def _snowboarder(inst, step, i, ctx):
    adj = ctx.grid.adjacent(ctx.tiles[i], _wrapping(ctx, ctx.tiles))
    n = sum(1 for t in adj if t.value <= 0)
    if n:
        _tadd(step, i, -n * inst.var())


@tile("Sunset")
def _sunset(inst, step, i, ctx):
    tiles = ctx.tiles
    n = len({t.element() for t in tiles} - {""})
    if tiles[i].glyph == G_ZODIAC and n != 1:
        _tmul(step, i, n)


@tile("Taco")
def _taco(inst, step, i, ctx):
    if R.bracket_depth(ctx.tiles, i) > 0:
        _tmul(step, i, inst.var())


@tile("Tangerine")
def _tangerine(inst, step, i, ctx):
    t = ctx.tiles[i]
    if t.glyph == G_DOMINO:
        if sum(t.domino()) >= 4:
            _tmul(step, i, inst.var())
    elif t.glyph == G_DICE and t.dice_number() >= 4:
        _tmul(step, i, inst.var())


@tile("Thermometer")
def _thermometer(inst, step, i, ctx):
    if inst.var() >= 1 and i == 0:
        _tmul(step, i, inst.var(1))


@tile("Tram")
def _tram(inst, step, i, ctx):
    tiles = ctx.tiles
    if tiles[i].glyph == G_DOMINO and (
        (i > 0 and tiles[i - 1].glyph == G_DOMINO) or (i < len(tiles) - 1 and tiles[i + 1].glyph == G_DOMINO)
    ):
        _tadd(step, i, inst.var(1))


@tile("WatermelonSlice")
def _watermelon(inst, step, i, ctx):
    t = ctx.tiles[i]
    if t.glyph == G_DOMINO:
        n = sum(t.domino())
        if n > 0:
            _tadd(step, i, n * inst.var())
    elif t.glyph == G_DICE:
        _tadd(step, i, t.dice_number() * inst.var())


@tile("Basket")
def _basket(inst, step, i, ctx):
    if ctx.tiles[i].glyph == G_BRACKET:
        _setf(inst, "Score", _int(_fld(inst, "Score", 0)) + 1)


@tile("BoonOfTheBat")
def _boon_bat(inst, step, i, ctx):
    t = ctx.tiles[i]
    w, h = ctx.grid.width - 1, ctx.grid.height - 1
    if t.x in (0, w) and t.y in (0, h):
        _tmul(step, i, 5)


@tile("Conifer")
def _conifer(inst, step, i, ctx):
    t = ctx.tiles[i]
    if t.forever or t.custom_bag:
        _tadd(step, i, inst.var(1))


@tile("IceSkate")
def _ice_skate(inst, step, i, ctx):
    _tadd(step, i, -inst.var())


@tile("PieceOfString")
def _piece_of_string(inst, step, i, ctx):
    if inst.var() >= 1 and inst.colours and ctx.tiles[i].is_type(inst.colours[0]):
        _tmul(step, i, inst.var())


@tile("Sunrise")
def _sunrise(inst, step, i, ctx):
    t = ctx.tiles[i]
    if t.glyph == G_ZODIAC:
        _tadd(step, i, inst.var() * zodiac_position(t.symbol))


@tile("Witch")
def _witch(inst, step, i, ctx):
    if ctx.tiles[i].glyph == G_ZODIAC and _same_element(ctx.tiles):
        _tadd(step, i, inst.var())


# --- items with both a tile and a word hook (tile step first, then word steps)


@tile("FrostBite")
def _frost_bite_tile(inst, step, i, ctx):
    t = ctx.tiles[i]
    if t.glyph == G_NUMBER and (t.number or 0) < 0:
        _setf(inst, "Reduction", _int(_fld(inst, "Reduction", 0)) - t.number)


@word("FrostBite")
def _frost_bite(inst, step, ctx):
    r = _int(_fld(inst, "Reduction", 0))
    if r >= 100:
        _mult(step, (r // 100 + 1) * 100)


@tile("InfiniteLoop")
def _infinite_loop_tile(inst, step, i, ctx):
    t = ctx.tiles[i]
    if t.forever or t.custom_bag:
        _setf(inst, "ForeverTilesUsed", _int(_fld(inst, "ForeverTilesUsed", 0)) + 1)


@word("InfiniteLoop")
def _infinite_loop(inst, step, ctx):
    n = _int(_fld(inst, "ForeverTilesUsed", 0))
    if n > 0:
        _mult(step, 100 + n * 2)


@tile("Stopwatch")
def _stopwatch_tile(inst, step, i, ctx):
    t = ctx.tiles[i]
    if t.glyph != G_ZODIAC:
        return
    req = _fld(inst, "RequiredSigns", None)
    req = list(req) if isinstance(req, list) else list(ZODIAC_ORDER)
    if t.symbol in req:
        req.remove(t.symbol)
        if not req:
            _setf(inst, "Count", _int(_fld(inst, "Count", 0)) + 1)
            req = list(ZODIAC_ORDER)
        _setf(inst, "RequiredSigns", req)


@word("Stopwatch")
def _stopwatch(inst, step, ctx):
    n = _int(_fld(inst, "Count", 0))
    if n > 0:
        _mult(step, (1 + n) * 100)


# ------------------------------------------------------------------ submission hooks (whole path)


@submission("Electrician")
def _electrician(inst, step, ctx):
    if wire_connected(ctx, ctx.tiles):
        step.money += 2


@submission("Flashlight")
def _flashlight(inst, step, ctx):
    if wire_connected(ctx, ctx.tiles) and _lit(ctx.tiles):
        _mult(step, inst.var() * 100)


@submission("Rocket")
def _rocket(inst, step, ctx):
    if wire_connected(ctx, ctx.tiles):
        _mult(step, len(_wires(ctx.tiles)) * 50)


@submission("Twinsies")
def _twinsies(inst, step, ctx):
    lens = [len(w) for w in ctx.words]
    if len(lens) != len(set(lens)):
        _add(step, inst.var())


@submission("Zap")
def _zap(inst, step, ctx):
    if wire_connected(ctx, ctx.tiles) and len(_wires(ctx.tiles)) >= 3:
        _mult(step, inst.var())


@submission("Selfie")
def _selfie(inst, step, ctx):
    if ctx.tiles and wire_connected(ctx, ctx.tiles):
        _add_consumables(step, 2)


@submission("DeadBattery")
def _dead_battery(inst, step, ctx):
    if wire_connected(ctx, ctx.tiles):
        _setf(inst, "StoredWireCount", _int(_fld(inst, "StoredWireCount", 0)) + 1)


# HoroscopeWriter only counts zodiac-name words (no score this submit).


# ------------------------------------------------------------------ tetrominoes (Joystick)


def _normalize(coords) -> tuple:
    mx = min(c[0] for c in coords)
    my = min(c[1] for c in coords)
    return tuple(sorted(((x - mx, y - my) for x, y in coords), key=lambda c: (c[1], c[0])))


def _tetrominoes() -> frozenset:
    base = [
        [(0, 0), (1, 0), (2, 0), (3, 0)], [(0, 0), (1, 0), (0, 1), (1, 1)],
        [(0, 0), (1, 0), (2, 0), (1, 1)], [(0, 0), (0, 1), (0, 2), (1, 2)],
        [(1, 0), (1, 1), (1, 2), (0, 2)], [(0, 1), (1, 1), (1, 0), (2, 0)],
        [(0, 0), (1, 0), (1, 1), (2, 1)],
    ]
    out = set()
    for shape in base:
        s = set(shape)
        for _ in range(4):
            out.add(_normalize(s))
            s = {(-y, x) for x, y in s}
            out.add(_normalize({(-x, y) for x, y in s}))
    return frozenset(out)


_TETROMINOES = _tetrominoes()


def _is_tetromino(tiles) -> bool:
    # Game coordinates are bottom-origin; a vertical flip keeps the shape set closed.
    coords = {(t.x, t.y) for t in tiles}
    return len(coords) == 4 and _normalize(coords) in _TETROMINOES
