"""``GridUtilitySingleton.GenerateGrid`` port.

basic grid → item start-of-grid effects → challenge adjustments → boss adjustments
(reversed with an odd number of Hourglasses), then any non-available colour that
appeared is added to ``RunProgress.AvailableColours``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cursed_words_solver.sim.game import core as C
from cursed_words_solver.sim.game.core import GridData, Rng, Tile, is_edge
from cursed_words_solver.sim.game.grid_util import GenCtx, tile_for_boss_scatter

if TYPE_CHECKING:  # pragma: no cover
    from cursed_words_solver.sim.game.items import Item
    from cursed_words_solver.sim.game.player import BossModifier, HistoricWord, Player


def generate_basic_grid(
    g: GenCtx,
    width: int,
    height: int,
    bosses: list["BossModifier"],
    static_tiles: list[Tile] | None = None,
) -> GridData:
    """``GenerateBasicGridData``."""
    player, rng = g.player, g.rng
    run = player.run
    grid = GridData(width=width, height=height, grid_number=g.grid_number)
    harder = run.asc(5)
    nums = list(range(1, width * height + 1))
    statics = {(t.x, t.y): t for t in static_tiles or ()}
    for j in range(width * height):
        x, y = j % width, j // width
        if (x, y) in statics:
            grid.tiles.append(statics[(x, y)])
            continue
        t = Tile(x=x, y=y)
        grid.tiles.append(t)
        if run.challenge_is("RedLetterDay"):
            t.set_letter(C.random_consonant_weighted(rng))
        elif run.challenge_is("RedPepperDay"):
            t.set_letter(C.random_vowel_weighted(rng))
        elif run.challenge_is("EmptyGrid"):
            t.set_empty(True)
        elif run.challenge_is("Sudoku"):
            idx = rng.range(0, len(nums))
            t.set_number(nums.pop(idx))
        else:
            t.set_letter(C.random_letter_weighted(rng, harder))
    if run.challenge_is("CallOfTheVoid"):
        for t in grid.tiles:
            if not is_edge(t, grid):
                t.in_void = True
                t.gone = True
    ch = run.challenge
    if run.challenge_is("MunchTime"):
        if not ch.munched:
            ch.path = generate_path_through_grid(grid, rng, player)
        for (x, y) in ch.munched:
            t = grid.at(x, y)
            if t is not None:
                t.destroyed = True
                t.gone = True
    if run.challenge_is("SupplyAndDemand") and run.stats.words_submitted:
        last = run.stats.words_submitted[-1].tiles
        reps = {lt.srep() for lt in last}
        for t in grid.tiles:
            t.crossed_out = t.srep() in reps
    for boss in bosses:
        if boss.game_class == "DestroyGrid":
            for (x, y) in boss.fields["DestroyedCoordinates"]:
                t = grid.at(x, y)
                if t is not None:
                    t.destroyed = True
                    t.gone = True
    g.grid = grid
    g.rack = list(player.consumables)
    return grid


def _apply_items(g: GenCtx, items: list["Item"], final: bool) -> None:
    """Item loop of ``MakeStartOfGridItemAdjustments`` (one of the two passes)."""
    player = g.player
    cactus_before = [(t.x, t.y) for t in g.grid.available() if t.is_type(C.CACTUS)]
    seedling = any(i.relevant_colours and i.relevant_colours[0] == C.CACTUS for i in player.unpacked_of("SaguaroSeedling"))
    overhand = next((s for s in player.stickers_list() if s.game_class == "Overhand"), None)

    def run(it: "Item") -> None:
        if final:
            it.final_start_of_grid(g)
        else:
            it.start_of_grid(g)

    for it in items:
        if it.game_class in ("RandomAccessMemory", "Frankenstein"):
            nested = list(it.nested_items())
            if g_backwards[0]:
                nested.reverse()
            for n in nested:
                if n is not None:
                    run(n)
            if final:
                cactus_before = _grow_cactus(g, cactus_before, seedling)
            continue
        run(it)
        if player.is_hb_favourite_stamp(it) and player.pin is not None and player.pin.var(1) > 1:
            for _ in range(player.pin.var(1) - 1):
                run(it)
        if overhand is not None and player.is_overhand_target(it):
            for _ in range(overhand.var(0)):
                run(it)
        if final:
            cactus_before = _grow_cactus(g, cactus_before, seedling)


g_backwards = [False]


def _grow_cactus(g: GenCtx, before: list[tuple[int, int]], seedling: bool) -> list[tuple[int, int]]:
    """New cactus tiles grow by the run's ``CactusGrowthLevel``."""
    now = [t for t in g.grid.available() if t.tile_type == C.CACTUS]
    if len(now) == len(before):
        return before
    for t in now:
        if (t.x, t.y) not in before:
            g.player.run.cactus_growth_level += 2 if seedling else 1
            t.cactus_growth += g.player.run.cactus_growth_level
    return [(t.x, t.y) for t in now]


def item_adjustments(g: GenCtx, backwards: bool = False) -> None:
    """``MakeStartOfGridItemAdjustments``."""
    player = g.player
    items: list["Item"] = []
    last = g.last_word()
    if last is not None:
        items.extend(t.item for t in last.tiles if t.get_glyph() == C.G_ITEM and t.item is not None)
    items.extend(player.all_items())
    if backwards:
        items.reverse()
    g_backwards[0] = backwards
    _apply_items(g, items, final=False)
    finals = list(player.all_items())
    if backwards:
        finals.reverse()
    _apply_items(g, finals, final=True)


def challenge_adjustments(g: GenCtx) -> None:
    """``MakeStartOfGridChallengeAdjustments``."""
    run = g.player.run
    if run.challenge_is("MunchTime") and not g.is_reroll:
        ch = run.challenge
        if ch.path:
            coord = ch.path.pop()
            ch.munched.append(coord)
            if len(ch.path) <= run.remaining_encounters():
                g.grid.has_lost_challenge = True
            t = g.grid.at(*coord)
            if t is not None:
                t.destroyed = True
    elif run.challenge_is("UpAndUp"):
        n = 15 - run.remaining_encounters()
        t = g.grid.at(g.grid.width // 2, g.grid.height // 2)
        if t is not None:
            t.set_number(n)
            t.number_go_up_middle = True


def boss_adjustments(g: GenCtx, bosses: list["BossModifier"], backwards: bool = False) -> None:
    """``MakeStartOfGridBossAdjustments``."""
    player, rng, grid = g.player, g.rng, g.grid
    seedling = any(i.relevant_colours and i.relevant_colours[0] == C.CACTUS for i in player.unpacked_of("SaguaroSeedling"))
    cactus = [(t.x, t.y) for t in grid.available() if t.is_type(C.CACTUS)]
    order = list(bosses)
    if backwards:
        order.reverse()
    for boss in order:
        cls, mod = boss.game_class, boss.floor_mod
        if cls == "ExtraQs":
            for _ in range(mod):
                t = tile_for_boss_scatter(g, [x for x in grid.available() if x.srep() == "q"])
                if t is not None:
                    t.set_letter("q")
        elif cls == "ExtraVoids":
            tt = boss.fields.get("TileTypeToScatter", C.VOID)
            for _ in range(mod):
                t = tile_for_boss_scatter(g, [x for x in grid.available() if x.is_type(tt)])
                if t is not None:
                    t.tile_type = tt
        elif cls == "AddNumbers":
            used: list[Tile] = []
            for n in range(7, mod + 1):
                t = tile_for_boss_scatter(g, used)
                if t is not None:
                    t.set_number(n)
                    used.append(t)
        elif cls == "DiscolourTiles":
            for _ in range(mod):
                t = tile_for_boss_scatter(g, [x for x in grid.available() if x.tile_type == C.NORMAL])
                if t is not None:
                    t.tile_type = C.NORMAL
        elif cls == "DestroyGrid" and not g.is_reroll:
            coords = [(t.x, t.y) for t in grid.available() if not t.destroyed]
            n = mod - (1 if len(boss.fields["DestroyedCoordinates"]) > 3 else 0)
            for _ in range(n):
                if len(coords) > 1:
                    c = coords.pop(rng.range(0, len(coords)))
                    boss.fields["DestroyedCoordinates"].append(c)
                    t = grid.at(*c)
                    if t is not None:
                        t.destroyed = True
        elif cls == "SandySaguaroBoss":
            g.rack = sandy_consumables(boss, g)
        elif cls == "HumanBoyBoss" and g.grid_number == 1 and not g.is_reroll:
            steal = human_boy_item_to_steal(player)
            boss.fields["StolenItem"] = steal
            if steal is not None:
                g.items_to_remove.append(steal)
        elif cls == "PrismaticBeanBoss":
            types = [C.RED, C.BLUE, C.GREEN, C.GOLD, C.PURPLE, C.WHITE, C.VOID, C.SHINY, C.PINK, C.CACTUS, C.GLITCH]
            for t in grid.available():
                t.tile_type = types[rng.range(0, len(types))]
        now = [t for t in grid.available() if t.tile_type == C.CACTUS]
        if len(now) != len(cactus):
            for t in now:
                if (t.x, t.y) not in cactus:
                    player.run.cactus_growth_level += 2 if seedling else 1
                    t.cactus_growth += player.run.cactus_growth_level
            cactus = [(t.x, t.y) for t in now]


def human_boy_item_to_steal(player: "Player") -> "Item | None":
    """``HumanBoyBoss.GetItemToSteal``: highest-level sticker (name tiebreak), else first stamp by name."""
    stickers = sorted(player.stickers_list(for_comparison=True), key=lambda i: (i.level(0), i.name))
    if stickers:
        return stickers[-1]
    stamps = sorted(player.stamps_list(for_comparison=True), key=lambda i: i.name)
    return stamps[0] if stamps else None


def sandy_consumables(boss: "BossModifier", g: GenCtx) -> list[Tile | None]:
    """``SandySaguaroBoss.GenerateConsumableTiles``: two cactus letters from a random 5-letter word."""
    word = g.word_source(5) if g.word_source is not None else None
    word = word or "cacti"
    rng = g.rng
    a = rng.range(0, len(word))
    b = (a + rng.range(1, len(word))) % len(word)
    tiles: list[Tile] = []
    for ch in (word[a], word[b]):
        t = Tile()
        t.tile_type = C.CACTUS
        t.set_letter(ch)
        t.selling_prevented = True
        t.sandy_boss_tile = True
        tiles.append(t)
    boss.fields["CurrentlyActiveConsumableTiles"] = tiles
    rack: list[Tile | None] = [None] * 10
    rack[0], rack[1] = tiles[0], tiles[1]
    return rack


def generate_path_through_grid(grid: GridData, rng: Rng, player: "Player") -> list[tuple[int, int]]:
    """``GeneratePathThroughGrid`` (Munch Time)."""
    from cursed_words_solver.sim.game.core import adjacent_tiles

    tiles = list(grid.tiles)
    path: list[Tile] = []
    coords: list[tuple[int, int]] = []
    for i in range(min(25, len(tiles))):
        if i == 0:
            t = tiles[rng.range(0, len(tiles))]
        else:
            adj: list[Tile] = []
            for p in path:
                adj.extend(adjacent_tiles(grid, p.x, p.y, player))
            seen: set[int] = set()
            cands = []
            for a in adj:
                if a in path or id(a) in seen:
                    continue
                seen.add(id(a))
                cands.append(a)
            if not cands:
                break
            t = cands[rng.range(0, len(cands))]
        path.append(t)
        coords.append((t.x, t.y))
    return coords


def generate_grid(
    g: GenCtx,
    width: int,
    height: int,
    bosses: list["BossModifier"],
    static_tiles: list[Tile] | None = None,
) -> GridData:
    """``GridUtilitySingleton.GenerateGrid``."""
    player = g.player
    hourglass_odd = len(player.unpacked_of("Hourglass")) % 2 == 1
    generate_basic_grid(g, width, height, bosses, static_tiles)
    if hourglass_odd:
        boss_adjustments(g, bosses, backwards=True)
        challenge_adjustments(g)
        item_adjustments(g, backwards=True)
    else:
        item_adjustments(g)
        challenge_adjustments(g)
        boss_adjustments(g, bosses)
    avail = player.run.available_colours
    for t in g.grid.available():
        if t.tile_type not in (C.NORMAL, C.GLITCH) and t.tile_type not in avail:
            avail.append(t.tile_type)
    return g.grid
