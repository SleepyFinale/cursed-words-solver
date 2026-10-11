"""Item scoring ports: one function per game class, mirroring the decompiled
``ApplyTileBonus`` / ``ApplyWordBonus`` bodies (Assembly-CSharp, game 0.2.x).

Tile hooks run for every path index on the same step before the word hook, as in
``Item.ApplyItemToScore``. Hooks may mutate ``inst.state`` (persistent counters such
as Ruler distance); the engine works on per-submit copies so this never leaks.
"""

from __future__ import annotations

from typing import Callable

import numpy as np

from cursed_words_solver.engine import packet as P
from cursed_words_solver.engine.model import (
    BLUE,
    C_CHESS,
    CHESS_VALUES,
    CONSONANTS,
    G_BLANK,
    G_CARD,
    G_CHESS,
    G_CURRENCY,
    G_FRACTION,
    G_ITEM,
    G_LETTER,
    G_NUMBER,
    GLITCH,
    LETTERS,
    NORMAL,
    RED,
    SEL_EN_PASSANT,
    SEL_TAKE,
    SHINY,
    SUIT_JOKER,
    SUIT_NONE,
    VOID,
    VOWELS,
    WHITE,
    ETile,
    ItemInst,
    are_adjacent,
)
from cursed_words_solver.engine.poker import (
    get_flush,
    get_straight,
    get_x_of_a_kind,
    max_distinct_pairs,
)
from cursed_words_solver.engine.state import Ctx, Step, WordBonus

TileHook = Callable[[ItemInst, Step, int, Ctx], None]
WordHook = Callable[[ItemInst, Step, Ctx], None]

TILE_HOOKS: dict[str, TileHook] = {}
WORD_HOOKS: dict[str, WordHook] = {}


def tile(cls: str):
    def deco(fn: TileHook) -> TileHook:
        TILE_HOOKS[cls] = fn
        return fn

    return deco


def word(cls: str):
    def deco(fn: WordHook) -> WordHook:
        WORD_HOOKS[cls] = fn
        return fn

    return deco


def _mult(step: Step, percent: int | float) -> None:
    step.wb = WordBonus(percent, True)


def _add(step: Step, value: int | float) -> None:
    step.wb = WordBonus(value, False)


def _tmul(step: Step, i: int, factor: int) -> None:
    step.ts[i] = P.mul(step.ts[i], factor)


def _tadd(step: Step, i: int, amount: int | float) -> None:
    step.ts[i] = P.add(step.ts[i], amount)


def _distinct_colours(tiles: list[ETile]) -> list[str]:
    seen: list[str] = []
    for t in tiles:
        if t.tile_type != NORMAL and t.tile_type not in seen:
            seen.append(t.tile_type)
    return seen


def _is_take(ctx: Ctx, i: int) -> bool:
    return ctx.sels[i].method in (SEL_TAKE, SEL_EN_PASSANT)


def _selection_curse_types(ctx: Ctx, i: int) -> list[str]:
    """``TileSelection.GetCurseTypes`` (adds Wobbly when the selection is wobbly)."""
    out = ctx.tiles[i].curse_types(ctx.variable_letter[i])
    if ctx.sels[i].wobbly and "Wobbly" not in out:
        out.append("Wobbly")
    return out


def _scattered_on_path(ctx: Ctx) -> list[tuple[ETile, ItemInst | None]]:
    from cursed_words_solver.engine.model import make_item

    out = []
    for t in ctx.tiles:
        if t.glyph == G_ITEM and t.item:
            out.append((t, make_item(t.item, t.item_level)))
    return out


# --- tile score hooks ---------------------------------------------------------------


@tile("Abacus")
def _abacus(inst, step, i, ctx):
    t = ctx.tiles[i]
    if t.is_number() and not t.is_type(NORMAL):
        _tadd(step, i, inst.var(1))


@tile("AlembicFlask")
def _alembic(inst, step, i, ctx):
    tiles = ctx.tiles
    if i >= 1 and tiles[i].is_number() and tiles[i - 1].is_number():
        _tadd(step, i, inst.var())
    elif i < len(tiles) - 1 and tiles[i].is_number() and tiles[i + 1].is_number():
        _tadd(step, i, inst.var())


@tile("Ambulance")
def _ambulance(inst, step, i, ctx):
    total = 0
    for t in ctx.tiles:
        total = P.add(total, t.value)
    if not total >= 0:
        _mult(step, inst.var())


@tile("ArtistsPalette")
def _palette(inst, step, i, ctx):
    if not ctx.tiles[i].is_type(NORMAL):
        _tadd(step, i, inst.var())


@tile("Builder")
def _builder(inst, step, i, ctx):
    if ctx.tiles[i].was_consumable:
        n = sum(1 for t in ctx.tiles if t.was_consumable)
        if n >= 2:
            _tmul(step, i, n)


@tile("BunchOfGrapes")  # Bubble Tea
def _bubble_tea(inst, step, i, ctx):
    rep = ctx.tiles[i].srep
    n = sum(1 for t in ctx.tiles if t.srep == rep)
    if n >= 2:
        _tmul(step, i, n)


@tile("CelestialBody")
def _celestial(inst, step, i, ctx):
    if ctx.tiles[i].suit != SUIT_NONE:
        _tadd(step, i, inst.var())


@tile("Cocktail")
def _cocktail(inst, step, i, ctx):
    if inst.var() >= 1:
        colour = ctx.tiles[i].tile_type
        first = next(t for t in ctx.tiles if t.tile_type == colour)
        if first is ctx.tiles[i]:
            _tmul(step, i, inst.var())


@tile("Dartboard")
def _dartboard(inst, step, i, ctx):
    total = 0
    for t in ctx.tiles:
        total = P.add(total, t.value)
    target = inst.state.get("target_number")
    if target is not None and total == target:
        _add(step, inst.var())


@tile("DeepSeaHorror")
def _deep_sea(inst, step, i, ctx):
    if ctx.tiles[i].is_type(inst.colours[0] if inst.colours else VOID):
        _tadd(step, i, inst.var())


@tile("EightBall")  # Magic 8 Ball
def _eight_ball(inst, step, i, ctx):
    t = ctx.tiles[i]
    piece = inst.state.get("selected_piece")
    if t.is_chess() and piece is not None and t.piece == piece:
        _tadd(step, i, inst.var())


@tile("ElectricGuitar")
def _guitar(inst, step, i, ctx):
    t = ctx.tiles[i]
    if t.is_type(inst.colours[0] if inst.colours else RED) and t.srep in ("a", "b", "c", "d", "e", "f", "g"):
        _tadd(step, i, inst.var())


@tile("ErrorItem")
def _error_tile(inst, step, i, ctx):
    t = ctx.tiles[i]
    colour = inst.colours[0] if inst.colours else GLITCH
    hit = t.was_glitch if colour == GLITCH else t.is_type(colour)
    if hit:
        inst.state["glitch_used"] = inst.state.get("glitch_used", 0) + 1
        ctx.nondeterministic = True  # 10% chance to break per tile


@tile("FishCake")
def _fish_cake(inst, step, i, ctx):
    if inst.var() >= 1 and ctx.tiles[i].is_type(inst.colours[0] if inst.colours else SHINY):
        _tmul(step, i, inst.var())


@tile("GlassOfMilk")
def _milk(inst, step, i, ctx):
    if ctx.tiles[i].is_blank():
        _tadd(step, i, inst.var())


@tile("JollyRoger")
def _jolly_roger(inst, step, i, ctx):
    for j in range(i):
        if _is_take(ctx, j):
            return
    if _is_take(ctx, i):
        step.consumables = min(10, step.consumables + 1)


@tile("Kangaroo")
def _kangaroo(inst, step, i, ctx):
    t = ctx.tiles[i]
    if i + 1 < len(ctx.sels) and t.glyph == G_CHESS and t.piece in ("bishop", "rook"):
        _tadd(step, i, ctx.sels[i + 1].move_distance * inst.var())


@tile("LabCoat")
def _lab_coat(inst, step, i, ctx):
    if ctx.tiles[i].is_number():
        _tmul(step, i, inst.var())


@tile("MahjongRedDragon")
def _mahjong(inst, step, i, ctx):
    if ctx.tiles[i].was_consumable:
        _tmul(step, i, inst.var(1))


@tile("MapleLeaf")
def _maple(inst, step, i, ctx):
    limit = inst.var()
    if limit < 1:
        return
    colour = inst.colours[0] if inst.colours else RED
    chosen: list[ETile] = []
    for t in ctx.tiles:
        if t.is_type(colour):
            chosen.append(t)
            if len(chosen) >= limit:
                break
    if any(t is ctx.tiles[i] for t in chosen):
        _tmul(step, i, 3)


@tile("Moai")
def _moai(inst, step, i, ctx):
    if ctx.cursed[i] and ctx.tiles[i].is_type(NORMAL):
        _tadd(step, i, inst.var())


@tile("MushroomUpgrade")
def _mushroom(inst, step, i, ctx):
    if ctx.tiles[i].is_type(inst.colours[0] if inst.colours else RED):
        inst.state["red_count"] = inst.state.get("red_count", 0) + 1


@tile("MutatingDNA")
def _dna(inst, step, i, ctx):
    counts: dict[str, int] = inst.state.setdefault("letter_counts", {})
    rep = ctx.tiles[i].srep
    if rep in counts:
        _tadd(step, i, counts[rep])
        counts[rep] += 1
    else:
        counts[rep] = 1


@tile("MysteriousAmulet")
def _amulet(inst, step, i, ctx):
    if ctx.cursed[i]:
        _tadd(step, i, inst.var())


@tile("NestEgg")
def _nest_egg(inst, step, i, ctx):
    if ctx.tiles[i].is_type(inst.colours[0] if inst.colours else BLUE):
        inst.state["blue_used"] = inst.state.get("blue_used", 0) + 1


@tile("NumbersGiraffe")  # Giraffe
def _numbers_giraffe(inst, step, i, ctx):
    if ctx.tiles[i].is_number():
        _tmul(step, i, i + 1)


@tile("PokerFace")
def _poker_face(inst, step, i, ctx):
    t = ctx.tiles[0]
    if t.suit != SUIT_NONE and t.glyph in (G_LETTER, G_CHESS, G_CARD):
        face = t.suit == SUIT_JOKER or t.srep in ("j", "q", "k")
        if not face and t.glyph == G_CHESS and t.piece in ("queen", "king"):
            face = True
        if face:
            _mult(step, inst.var() * 100)


@tile("Queen")  # Queenie
def _queenie(inst, step, i, ctx):
    if ctx.tiles[i].srep == "q":
        _tmul(step, i, 5)


@tile("QueenOfSpades")  # Down Under
def _down_under(inst, step, i, ctx):
    if inst.var() != 1:
        _tmul(step, i, inst.var())


@tile("SequoiaSapling")
def _sequoia(inst, step, i, ctx):
    if ctx.tiles[i].srep in VOWELS:
        _tadd(step, i, inst.var())


@tile("SlySpy")
def _sly_spy(inst, step, i, ctx):
    if ctx.tiles[i].srep in CONSONANTS:
        _tmul(step, i, inst.var())


@tile("Stiletto")
def _stiletto(inst, step, i, ctx):
    if ctx.tiles[i].is_type(inst.colours[0] if inst.colours else RED):
        step.ts[i] = P.scale(step.ts[i], float(np.float32(ctx.grid_data_number) / np.float32(2.0)))
        step.float_mult = True


@tile("Stilton")
def _stilton(inst, step, i, ctx):
    if ctx.tiles[i].is_type(inst.colours[0] if inst.colours else BLUE):
        _tadd(step, i, inst.var())


@tile("Sushi")
def _sushi(inst, step, i, ctx):
    if inst.var() < 1:
        return
    t = ctx.tiles[i]
    if not t.is_type(NORMAL):
        return
    wrap = ctx.hungry_snake or any(x.glyph == G_ITEM and x.item == "hungry_snake" for x in ctx.tiles)
    colours: set[str] = set()
    for adj in ctx.grid.adjacent(t, wrap):
        if adj.tile_type != NORMAL:
            colours.add(adj.tile_type)
    if len(colours) >= 2:
        _tmul(step, i, inst.var())


@tile("Telescope")
def _telescope(inst, step, i, ctx):
    colour = inst.colours[0] if inst.colours else RED
    if not ctx.tiles[i].is_type(colour):
        return
    count = sum(1 for t in ctx.tiles[: i + 1] if t.is_type(colour))
    count += sum(w.red_count for w in ctx.prev_words)
    _tadd(step, i, inst.var() * count)


@tile("Tombstone")
def _tombstone(inst, step, i, ctx):
    colour = inst.colours[0] if inst.colours else VOID
    wrap = ctx.hungry_snake or any(x.glyph == G_ITEM and x.item == "hungry_snake" for x in ctx.tiles)
    n = sum(1 for adj in ctx.grid.adjacent(ctx.tiles[i], wrap) if adj.is_type(colour))
    if n:
        _tadd(step, i, n * inst.var())


@tile("WadOfCash")
def _wad(inst, step, i, ctx):
    if ctx.tiles[i].glyph == G_CURRENCY and inst.var(1) > 0:
        _tadd(step, i, inst.var(1))


@tile("Zebra")
def _zebra(inst, step, i, ctx):
    if len(ctx.tiles) != i + 1 and _is_take(ctx, i + 1):
        _tmul(step, i, inst.var())


# --- word bonus hooks ---------------------------------------------------------------


def _slot_index(slots: list[ItemInst | None], inst: ItemInst) -> int:
    for idx, item in enumerate(slots):
        if item is inst:
            return idx
    return -1


@word("Arrivals")
def _arrivals(inst, step, ctx):
    if not ctx.tiles:
        return
    if _slot_index(ctx.stickers, inst) == 0:
        _mult(step, inst.var())
    elif ctx.stickers and ctx.stickers[0] is not None and ctx.stickers[0].cls == "Frankenstein" and inst in ctx.stickers[0].nested:
        _mult(step, inst.var())


@word("Departures")
def _departures(inst, step, ctx):
    if not ctx.tiles:
        return
    if _slot_index(ctx.stickers, inst) == 4:
        _add(step, inst.var())
    elif len(ctx.stickers) > 4 and ctx.stickers[4] is not None and ctx.stickers[4].cls == "Frankenstein" and inst in ctx.stickers[4].nested:
        _add(step, inst.var())


@word("Avocado")
def _avocado(inst, step, ctx):
    _mult(step, -200 if inst.state.get("mushy") else 200)


@word("Axe")
def _axe(inst, step, ctx):
    if 0 < len(ctx.tiles) <= 3:
        _mult(step, inst.var())


@word("BabyBottle")
def _baby_bottle(inst, step, ctx):
    if ctx.tiles and sum(1 for t in ctx.tiles if t.glyph == G_BLANK) == 2:
        _mult(step, inst.var())


@word("BarOfSoap")
def _bar_of_soap(inst, step, ctx):
    if ctx.tiles:
        step.consumables = min(10, step.consumables + len(_distinct_colours(ctx.tiles)))


@word("BaseCamp")
def _base_camp(inst, step, ctx):
    if not ctx.tiles:
        return
    total = 0
    for t in ctx.grid.available:
        total = P.add(total, t.value)
    _add(step, inst.var() * _c_int(total))


def _c_int(v: int | float) -> int:
    """``(int)scorePacket.Score``: low 32 bits, sign-extended (Score is 0 when infinite)."""
    if isinstance(v, float):
        return 0
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v >= (1 << 31) else v


@word("BentoBox")
def _bento(inst, step, ctx):
    prev = ctx.last_prev_word()
    if prev is None or not ctx.tiles or not prev.first_srep:
        return
    if ctx.tiles[0].srep == prev.first_srep:
        _mult(step, 150)


@word("Bicycle")
def _bicycle(inst, step, ctx):
    if not ctx.tiles:
        return
    n = sum(inst.var(1) for t in ctx.tiles if t.suit != SUIT_NONE)
    inst.state["bonus"] = inst.state.get("bonus", 0) + n
    if inst.state["bonus"] > 0:
        _add(step, inst.state["bonus"])


@word("BirthdayCake")
def _birthday_cake(inst, step, ctx):
    if not ctx.tiles:
        return
    best = np.float32(0.0)
    for t in ctx.tiles:
        if not t.is_number():
            continue
        val = np.float32(t.fraction_float()) if t.glyph == G_FRACTION else np.float32(t.number or 0)
        if val > best:
            best = val
    bonus = np.float32(inst.state.get("bonus", 0.0)) + best * np.float32(inst.var())
    inst.state["bonus"] = float(bonus)
    if bonus > 0:
        _add(step, P.round_to_int(float(bonus)))


@word("BlessingOfTheFairies")
def _fairies(inst, step, ctx):
    _mult(step, 100 + 50 * ctx.cursed_bosses_defeated)


@word("Blueberries")
def _blueberries(inst, step, ctx):
    if ctx.tiles and ctx.tiles[-1].is_type(inst.colours[0] if inst.colours else BLUE):
        _mult(step, 100 * inst.var())


@word("Bone")
def _bone(inst, step, ctx):
    if ctx.tiles:
        _mult(step, inst.var())


@word("Boomerang")
def _boomerang(inst, step, ctx):
    tiles = ctx.tiles
    if not tiles:
        return
    if len(tiles) == 1 and tiles[0].is_number():
        _mult(step, 100 * inst.var())
    elif len(tiles) > 1 and tiles[0].is_number() and tiles[-1].is_number():
        _mult(step, 100 * inst.var())


@word("Brain")
def _brain(inst, step, ctx):
    if not ctx.tiles:
        return
    total = np.float32(0.0)
    for t in ctx.tiles:
        if not t.is_number():
            continue
        total = total + (np.float32(t.fraction_float()) if t.glyph == G_FRACTION else np.float32(t.number or 0))
    if total >= 7:
        _mult(step, inst.var())


@word("Broom")
def _broom(inst, step, ctx):
    if len(ctx.sels) < 2:
        return
    first = [c for c in dict.fromkeys(_selection_curse_types(ctx, 0))]
    last = [c for c in dict.fromkeys(_selection_curse_types(ctx, len(ctx.sels) - 1))]
    if first and last and (set(first) - set(last) or set(last) - set(first)):
        _mult(step, inst.var())


@word("Burrito")
def _burrito(inst, step, ctx):
    total = sum(s.level(0) for s in ctx.stickers if s is not None and s is not inst and s.levels)
    for t, item in _scattered_on_path(ctx):
        if item is not None and item.levels and item.slug != inst.slug:
            total += item.level(0)
    if total > 0:
        _mult(step, 100 + inst.var() * total)


@word("Cartwheeler")
def _cartwheeler(inst, step, ctx):
    num = np.float32(1.0)
    for _ in ctx.tiles:
        num = num * np.float32(-1.1)
    _mult(step, P.round_to_int(float(num * np.float32(100.0))))


@word("ChequeredFlag")
def _chequered(inst, step, ctx):
    if ctx.grid_number == 1:
        _mult(step, inst.var() * 100)


@word("CherryPie")
def _cherry_pie(inst, step, ctx):
    colour = inst.colours[0] if inst.colours else RED
    if sum(1 for t in ctx.tiles if t.is_type(colour)) >= 3:
        _mult(step, 100 * inst.var())


@word("Chick")
def _chick(inst, step, ctx):
    n = sum(1 for s in ctx.stickers if s is not None and s.levels and s.level(0) == 1)
    for t, item in _scattered_on_path(ctx):
        if item is not None and len(item.levels) == 1 and item.level(0) == 1:
            n += 1
    if n > 0:
        _mult(step, 100 + n * 20)


@word("Chips")
def _chips(inst, step, ctx):
    prev = ctx.last_prev_word()
    if prev is None or not ctx.tiles or not prev.first_srep:
        return
    t = ctx.tiles[0]
    if t.glyph == G_LETTER and prev.first_is_letter and t.srep in LETTERS and prev.first_srep in LETTERS:
        if LETTERS.index(t.srep) > LETTERS.index(prev.first_srep):
            _mult(step, inst.var())


@word("CircusTent")
def _circus(inst, step, ctx):
    cols = inst.colours or [BLUE, RED, NORMAL]
    if ctx.tiles and all(any(t.is_type(c) for t in ctx.tiles) for c in cols[:3]):
        _mult(step, inst.var())


@word("ClapperBoard")
def _clapper(inst, step, ctx):
    if sum(1 for i in range(len(ctx.sels)) if _is_take(ctx, i)) > 1:
        _mult(step, inst.var() * 100)


@word("CoinPurse")  # Piggy Bank
def _piggy(inst, step, ctx):
    count = inst.state.get("count", 0)
    if ctx.tiles and count:
        _mult(step, 100 + count)


@word("ConfettiItem")
def _confetti(inst, step, ctx):
    if len(_distinct_colours(ctx.tiles)) >= 5:
        _mult(step, 100 * inst.var())


@word("CreakyChair")
def _creaky(inst, step, ctx):
    kinds: set[str] = set()
    for i in range(len(ctx.sels)):
        kinds.update(_selection_curse_types(ctx, i))
    if len(kinds) >= 3:
        _mult(step, 100 * inst.var())


@word("CreditCard")
def _credit_card(inst, step, ctx):
    if step.money > 0:
        _add(step, step.money * inst.var())


@word("CrystalBall")
def _crystal_ball(inst, step, ctx):
    chosen = inst.state.get("chosen_curse")
    if chosen is None:
        return
    for i in range(len(ctx.sels)):
        if chosen in _selection_curse_types(ctx, i):
            _add(step, inst.var())
            break


@word("Dagger")
def _dagger(inst, step, ctx):
    n = sum(
        1
        for i, t in enumerate(ctx.tiles)
        if ctx.sels[i].method == SEL_TAKE and t.glyph == G_CHESS and t.piece == "king"
    )
    if n > 0:
        _add(step, inst.var() * n)


@word("Dango")
def _dango(inst, step, ctx):
    n = len(_distinct_colours(ctx.tiles))
    if n != 1:
        _mult(step, 100 * n)


@word("Dove")
def _dove(inst, step, ctx):
    chess = [t for t in ctx.tiles if t.glyph == G_CHESS]
    if chess and sum(1 for t in chess if t.white) == sum(1 for t in chess if not t.white):
        step.money += len(chess)


@word("DustyCoffin")
def _dusty_coffin(inst, step, ctx):
    colour = inst.colours[0] if inst.colours else VOID
    reps = {t.srep for t in ctx.tiles}
    n = sum(1 for t in ctx.grid.available if t.is_type(colour) and t.srep not in reps)
    if n > 0:
        _add(step, inst.var() * n)


@word("Egg")
def _egg(inst, step, ctx):
    if ctx.tiles and ctx.tiles[0].srep in VOWELS:
        _mult(step, inst.var())


@word("EmptyJar")
def _empty_jar(inst, step, ctx):
    if step.money <= 0:
        _mult(step, 200)


@word("ErrorItem")
def _error_word(inst, step, ctx):
    used = inst.state.get("glitch_used", 0)
    if ctx.tiles and not inst.state.get("broken") and used > 0:
        _mult(step, 100 * (used + 1))


@word("FerrisWheel")
def _ferris(inst, step, ctx):
    if not ctx.tiles:
        return
    a, b = ctx.tiles[0], ctx.tiles[-1]
    if not a.is_type(NORMAL) and not b.is_type(NORMAL) and a.tile_type != b.tile_type:
        _mult(step, inst.var())


@word("FireExtinguisher")
def _fire_ext(inst, step, ctx):
    colour = inst.colours[0] if inst.colours else RED
    on_path = {id(t) for t in ctx.tiles}
    n = sum(1 for t in ctx.grid.available if t.is_type(colour) and id(t) not in on_path)
    if n > 0:
        _add(step, n * inst.var())


@word("Footprints")
def _footprints(inst, step, ctx):
    tiles = ctx.tiles
    if not tiles:
        return
    jumps = sum(1 for i in range(1, len(tiles)) if not are_adjacent(tiles[i - 1], tiles[i]))
    if jumps >= 3:
        _mult(step, inst.var() * 100)


@word("FullBattery")
def _full_battery(inst, step, ctx):
    if ctx.tiles and all(t.is_number() for t in ctx.tiles):
        _mult(step, 100 * len(ctx.tiles))


@word("Giraffe")  # Slide
def _slide(inst, step, ctx):
    if get_straight(ctx.tiles, 3 if ctx.martini else 5) is not None:
        _add(step, inst.var())


@word("GoldenRecord")
def _golden_record(inst, step, ctx):
    if ctx.tiles:
        step.consumables = min(10, step.consumables + 1)


@word("GraduationCap")
def _grad_cap(inst, step, ctx):
    if ctx.tiles:
        _add(step, inst.var() * len(ctx.tiles))


@word("HamSandwich")
def _ham(inst, step, ctx):
    tiles = ctx.tiles
    if not tiles:
        return
    if len(tiles) == 1 or tiles[0].srep == tiles[-1].srep:
        _add(step, inst.var())


@word("Hanafuda")
def _hanafuda(inst, step, ctx):
    lv = inst.level(0)
    x = 2 if lv == 1 else (3 if lv == 2 else 4)
    if get_x_of_a_kind(x, ctx.tiles) is None:
        return
    on_path = {id(t) for t in ctx.tiles}
    n = sum(1 for t in ctx.grid.available if t.suit != SUIT_NONE and id(t) not in on_path)
    if n > 0:
        _add(step, n * inst.var())


@word("HeadInTheClouds")
def _head_clouds(inst, step, ctx):
    tiles = ctx.tiles
    if not tiles:
        return
    for i in range(1, len(tiles)):
        if are_adjacent(tiles[i - 1], tiles[i]):
            return
    _mult(step, 150)


@word("HeartOnFire")
def _heart_on_fire(inst, step, ctx):
    colour = inst.colours[0] if inst.colours else RED
    best = run = 0
    for t in ctx.tiles:
        if t.is_type(colour):
            run += 1
            continue
        best = max(best, run)
        run = 0
    best = max(best, run)
    if best != 1:
        _mult(step, 100 * best)


@word("HiVisJacket")
def _hi_vis(inst, step, ctx):
    if step.consumables > 0:
        _mult(step, 100 + inst.var() * step.consumables)
        step.consumables -= 1


@word("HungryHippo")
def _hippo(inst, step, ctx):
    _add(step, inst.var())


@word("JackOLantern")
def _jack(inst, step, ctx):
    if any(ctx.cursed[i] for i in range(len(ctx.tiles))):
        step.money += inst.var()


@word("JigsawPiece")
def _jigsaw(inst, step, ctx):
    total = 0
    for v in step.ts:
        total = P.add(total, v)
    if total == 0:
        _add(step, inst.var())


@word("Kadomatsu")
def _kadomatsu(inst, step, ctx):
    if get_x_of_a_kind(3, ctx.tiles) is not None:
        _add(step, inst.var())


@word("LasVegas")
def _las_vegas(inst, step, ctx):
    if not ctx.tiles:
        return
    jokers = sum(1 for t in ctx.tiles if t.suit == SUIT_JOKER)
    suits = {t.suit for t in ctx.tiles if t.suit not in (SUIT_NONE, SUIT_JOKER)}
    if len(suits) + jokers >= min(inst.var(), 4):
        _mult(step, 100 * inst.var())


@word("Limnophila")
def _limnophila(inst, step, ctx):
    prev = ctx.last_prev_word()
    if prev is None or not ctx.tiles or not prev.first_srep:
        return
    t = ctx.tiles[0]
    if t.glyph == G_LETTER and prev.first_is_letter and t.srep in LETTERS and prev.first_srep in LETTERS:
        if LETTERS.index(t.srep) - LETTERS.index(prev.first_srep) == 1:
            _mult(step, 150)


@word("Lollipop")
def _lollipop(inst, step, ctx):
    bonus = inst.state.get("bonus", 0)
    if bonus:
        _add(step, bonus)


@word("LuckyDice")
def _lucky_dice(inst, step, ctx):
    target = inst.state.get("dice_number")
    if not ctx.tiles or target is None:
        return
    for t in ctx.tiles:
        if t.glyph == G_NUMBER and t.number == target:
            _add(step, inst.var())
            break


@word("LuckyScarf")
def _lucky_scarf(inst, step, ctx):
    colour = inst.colours[0] if inst.colours else RED
    if ctx.tiles and ctx.tiles[0].is_type(colour) and ctx.tiles[-1].is_type(colour):
        _mult(step, 100 * inst.var())


@word("MichaelsBook")
def _michaels_book(inst, step, ctx):
    current = inst.state.get("current_word")
    if current and current in ctx.words:
        inst.state["count"] = inst.state.get("count", 0) + 1
    count = inst.state.get("count", 0)
    if count:
        _add(step, count * 30)


@word("MirrorBall")  # Banana
def _banana(inst, step, ctx):
    groups: dict[str, int] = {}
    for t in ctx.tiles:
        groups[t.srep] = groups.get(t.srep, 0) + 1
    num = np.float32(1.0)
    for n in groups.values():
        if n >= 3:
            num = num * (np.float32(n) / np.float32(2.0))
    if num > 1:
        _mult(step, P.round_to_int(float(num * np.float32(100.0))))


@word("MischievousImp")
def _imp(inst, step, ctx):
    if ctx.tiles and all(ctx.cursed[i] for i in range(len(ctx.tiles))):
        _mult(step, 100 * inst.var())


@word("MovieCamera")
def _movie_camera(inst, step, ctx):
    if not ctx.tiles:
        return
    taken = 0
    bonus = inst.state.get("bonus", 0)
    for i, t in enumerate(ctx.tiles):
        if _is_take(ctx, i):
            if taken < inst.var():
                bonus += CHESS_VALUES.get(t.piece, 0)
            taken += 1
    inst.state["bonus"] = bonus
    if bonus != 0:
        _add(step, bonus)


@word("Neapolitan")
def _neapolitan(inst, step, ctx):
    if len(_distinct_colours(ctx.tiles)) >= 3:
        inst.state["count"] = inst.state.get("count", 0) + 1
    count = inst.state.get("count", 0)
    if count:
        _mult(step, 100 + count * 5)


@word("NewEruptingVolcano")  # Erupting Volcano
def _volcano(inst, step, ctx):
    if ctx.tiles:
        _mult(step, 150)


@word("Newspaper")
def _newspaper(inst, step, ctx):
    if all(t.is_type(NORMAL) for t in ctx.tiles):
        _mult(step, inst.var())


@word("Oden")
def _oden(inst, step, ctx):
    kinds: list[str] = []
    for i in range(len(ctx.sels)):
        for c in _selection_curse_types(ctx, i):
            if c not in kinds:
                kinds.append(c)
    if len(kinds) != 1:
        _mult(step, 100 * len(kinds))


@word("Onigiri")
def _onigiri(inst, step, ctx):
    if ctx.tiles and all(t.is_type(NORMAL) for t in ctx.tiles):
        _add(step, inst.var())


@word("OrnateKey")
def _ornate_key(inst, step, ctx):
    if not any(t.is_type(NORMAL) for t in ctx.tiles):
        _mult(step, inst.var())


@word("PairOfSocks")
def _socks(inst, step, ctx):
    colour = inst.colours[0] if inst.colours else BLUE
    if ctx.tiles and sum(1 for t in ctx.tiles if t.is_type(colour)) == 2:
        _mult(step, inst.var())


@word("Parrot")
def _parrot(inst, step, ctx):
    if not all(t.is_type(NORMAL) for t in ctx.tiles):
        return
    n = sum(1 for t in ctx.grid.available if not t.is_type(NORMAL))
    if n > 0:
        _add(step, inst.var() * n)


@word("Peacock")
def _peacock(inst, step, ctx):
    required = 3 if (ctx.martini or any(t.item == "martini" for t in ctx.tiles if t.glyph == G_ITEM)) else 5
    if get_flush(ctx.tiles, required) is not None:
        _mult(step, 100 * inst.var())


@word("Pear")
def _pear(inst, step, ctx):
    if get_x_of_a_kind(2, ctx.tiles) is not None:
        step.money += inst.var()


@word("PeasOfAPod")
def _peas(inst, step, ctx):
    if get_x_of_a_kind(4, ctx.tiles) is not None:
        _mult(step, 100 * inst.var())


@word("Pneumonia")
def _pneumonia(inst, step, ctx):
    vowels = {t.srep for t in ctx.tiles if t.glyph == G_LETTER and t.srep in VOWELS}
    if vowels:
        _add(step, len(vowels) * inst.var())


@word("PocketMoney")
def _pocket_money(inst, step, ctx):
    if ctx.grid_number != 1 or not ctx.tiles:
        return
    for t in ctx.tiles:
        if t.is_number():
            step.money += int(t.number or 0) if t.glyph == G_NUMBER else (t.fraction or (0, 0))[0]
            return


@word("Postbox")
def _postbox(inst, step, ctx):
    if ctx.tiles and not any(ctx.cursed[i] for i in range(len(ctx.tiles))):
        _mult(step, 100 * inst.var())


@word("Rainbow")
def _rainbow(inst, step, ctx):
    n = len(_distinct_colours(ctx.tiles))
    if n:
        _add(step, inst.var(1) * n)


@word("Ruler")
def _ruler(inst, step, ctx):
    tiles = ctx.tiles
    if not tiles:
        return
    jumps = sum(1 for i in range(1, len(tiles)) if not are_adjacent(tiles[i - 1], tiles[i]))
    inst.state["distance"] = inst.state.get("distance", 0) + jumps
    if inst.state["distance"] > 0:
        _mult(step, 100 + inst.state["distance"] * 2)


@word("ShavedIce")
def _shaved_ice(inst, step, ctx):
    if ctx.tiles:
        _mult(step, 100 + inst.state.get("freezes", 0) * 20)


@word("SillyPuppy")
def _silly_puppy(inst, step, ctx):
    n = sum(1 for i in ctx.all_items() if i is not inst and i.info and i.info.animal)
    for t, item in _scattered_on_path(ctx):
        if item is not None and item.info and item.info.animal and item.slug != inst.slug:
            n += 1
    if n >= 1:
        _mult(step, 100 + n * 25)


@word("StampAlbum")
def _stamp_album(inst, step, ctx):
    total = sum(s.info.cost for s in ctx.stamps if s is not None and s.info)
    for t, item in _scattered_on_path(ctx):
        if item is not None and item.info and not item.info.components:
            total += item.info.cost
    if total > 0:
        _add(step, inst.var() * total)


@word("Steak")
def _steak(inst, step, ctx):
    n = sum(1 for i in ctx.all_items() if i.rarity == "rare")
    for t, item in _scattered_on_path(ctx):
        if item is not None and item.rarity == "rare":
            n += 1
    if n > 0:
        _mult(step, 100 + n * 25)


@word("Sunflower")
def _sunflower(inst, step, ctx):
    if step.money > 0:
        _mult(step, 100 + inst.var() * step.money)


@word("SuperEight")
def _super_8(inst, step, ctx):
    n = sum(1 for i in range(len(ctx.sels)) if _is_take(ctx, i))
    if n > 0:
        _add(step, inst.var(1) * n)


@word("TileNinja")
def _tile_ninja(inst, step, ctx):
    _mult(step, 120 + inst.state.get("used", 0) * 2)


@word("UnderConstruction")
def _under_construction(inst, step, ctx):
    if ctx.tiles and ctx.tiles[0].was_consumable and ctx.tiles[-1].was_consumable:
        _mult(step, inst.var() * 100)


@word("WheezyVixen")
def _vixen(inst, step, ctx):
    if ctx.tiles and ctx.tiles[0].srep in ("v", "w", "x", "y", "z"):
        _mult(step, inst.var() * 100)


@word("WindChime")
def _wind_chime(inst, step, ctx):
    if ctx.tiles and sum(1 for t in ctx.tiles if t.suit != SUIT_NONE) == 5:
        _mult(step, inst.var() * 100)


@word("Wrestlers")
def _wrestlers(inst, step, ctx):
    if not ctx.tiles:
        return
    a, b = ctx.tiles[0], ctx.tiles[-1]
    if a.suit != SUIT_NONE and b.suit != SUIT_NONE and (a.suit != b.suit or a.suit == SUIT_JOKER):
        _mult(step, inst.var())


@word("WrigglyWorm")
def _worm(inst, step, ctx):
    if len(ctx.tiles) >= 10:
        _mult(step, inst.var())


@word("YellowGlasses")
def _yellow_glasses(inst, step, ctx):
    tiles = ctx.tiles
    for i in range(1, len(tiles)):
        if tiles[i].srep == tiles[i - 1].srep:
            _mult(step, inst.var())
            return


# Classes whose ApplyItemToScore is replaced wholesale (Scissors: one step per pair).
def scissors_steps(inst: ItemInst, prev: Step, ctx: Ctx) -> list[Step]:
    pairs = max_distinct_pairs(ctx.tiles)
    if not pairs:
        return [prev.next()]
    out: list[Step] = []
    cur = prev
    for _pair in pairs:
        step = cur.next()
        step.wb = WordBonus(inst.var() + 100, True)
        step.item = inst.slug
        out.append(step)
        cur = step
    return out


SCORING_CLASSES = frozenset(TILE_HOOKS) | frozenset(WORD_HOOKS) | {"Scissors", "Snapshot"}
