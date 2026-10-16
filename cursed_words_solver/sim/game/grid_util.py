"""``GridUtilitySingleton`` helpers used by start-of-grid effects, plus the generation context.

``GenCtx`` stands in for the ``vizSteps`` list: the last viz step's
``PlayerConsumableTiles`` (the rack items build on), money / reroll changes and the
item a boss steals. ``EncounterController.ShowGridGenerationViz`` applies them to
the player once generation finishes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

from cursed_words_solver.sim.game.core import (
    BLUE,
    G_FRACTION,
    G_LETTER,
    G_NONE,
    G_NUMBER,
    NORMAL,
    PURPLE,
    RED,
    SUIT_NONE,
    GridData,
    Rng,
    Tile,
    adjacent_tiles,
)

if TYPE_CHECKING:  # pragma: no cover
    from cursed_words_solver.sim.game.items import Item
    from cursed_words_solver.sim.game.player import HistoricWord, Player


@dataclass
class GenCtx:
    player: "Player"
    rng: Rng
    grid: GridData
    grid_number: int  # CurrentGridsGenerated() at generation time
    number_of_grids: int  # _totalGridsPerRound
    previous_words: list["HistoricWord"]
    is_reroll: bool = False
    rack: list[Tile | None] = field(default_factory=lambda: [None] * 10)
    money_change: int = 0
    rerolls_change: int = 0
    items_to_remove: list["Item"] = field(default_factory=list)
    earnings: dict[str, int] = field(default_factory=dict)
    # Vocabulary.GetRandomWord(length) (Sandy Saguaro boss, Michael's Book).
    word_source: Callable[[int], str | None] | None = None

    # -- rack (ConsumableTileUtility on the viz-step copy) -----------------------

    def add_to_rack(self, tile: Tile) -> None:
        self.rack = add_tile_to_array(self.player, tile, self.rack)

    def last_word(self) -> "HistoricWord | None":
        return self.previous_words[-1] if self.previous_words else None


def rack_count(rack: list[Tile | None]) -> int:
    return sum(1 for t in rack if t is not None)


def add_tile_to_array(player: "Player", tile: Tile, rack: list[Tile | None]) -> list[Tile | None]:
    """``ConsumableTileUtility.AddTileToArray`` (Brick, Luffing Jib Crane, Erupting Volcano)."""
    arr = list(rack)
    tile.was_consumable = True
    full = (not player.unpacked_of("Stadium") and rack_count(arr) >= 5) or rack_count(arr) >= 10
    if full:
        for brick in player.unpacked_of("Brick"):
            for t in arr:
                if t is not None and not t.sandy_boss_tile:
                    t.change_value_modifier(brick.var(0))
        return arr
    for crane in player.unpacked_of("LuffingJibCrane"):
        if not tile.already_on_rack and not tile.sandy_boss_tile:
            tile.change_value_modifier(crane.var(0))
    for volcano in player.unpacked_of("EruptingVolcano"):
        if not tile.sandy_boss_tile and volcano.relevant_colours:
            tile.tile_type = volcano.relevant_colours[0]
    for i, t in enumerate(arr):
        if t is None:
            arr[i] = tile
            break
    tile.already_on_rack = True
    return arr


def remove_tile_from_array(player: "Player", tile: Tile, applied_to_grid: bool, rack: list[Tile | None]) -> list[Tile | None]:
    """``ConsumableTileUtility.RemoveTileFromArray``."""
    arr = list(rack)
    if applied_to_grid:
        player.run.stats_consumables_used += 1
        for ninja in player.unpacked_of("TileNinja"):
            ninja.fields["ConsumableTilesUsed"] = int(ninja.fields.get("ConsumableTilesUsed", 0)) + 1
        if tile.safe_from_destruction:
            return arr
    for i, t in enumerate(rack):
        if t is tile:
            arr[i] = None
            break
    return arr


# ---------------------------------------------------------------------------- scatter


def tile_for_item_scatter(
    g: GenCtx,
    tile_type: str,
    glyph: str,
    whitelist: list[Tile] | None = None,
    suited: bool = False,
) -> Tile | None:
    """``GridUtilitySingleton.GetTileForItemScatter``."""
    grid, player, rng = g.grid, g.player, g.rng
    if whitelist is not None and len(whitelist) < 1:
        return None
    pool = grid.available() if whitelist is None else list(whitelist)
    if player.run.challenge_is("UpAndUp") and glyph != G_NONE:
        cx, cy = grid.width // 2, grid.height // 2
        pool = [t for t in pool if (t.x, t.y) != (cx, cy)]
    if not pool:
        return None

    sax_colours: list[str] = []
    for sax in player.unpacked_of("Saxophone"):
        sax_colours.extend(sax.relevant_colours)
    flag = tile_type in sax_colours or (RED in sax_colours and tile_type == PURPLE) or (BLUE in sax_colours and tile_type == PURPLE)
    relevant = BLUE
    if flag:
        if tile_type in sax_colours:
            relevant = tile_type
        elif BLUE in sax_colours:
            relevant = BLUE
        else:
            relevant = RED
    adj_blue: list[Tile] = []
    if flag:
        for t in grid.available():
            if t.is_type(relevant):
                adj_blue.extend(a for a in adjacent_tiles(grid, t.x, t.y, player) if a.is_type(NORMAL))
    flag2 = glyph in (G_NUMBER, G_FRACTION) and bool(player.unpacked_of("Magnet"))
    adj_num: list[Tile] = []
    if flag2:
        for t in grid.available():
            if t.get_glyph() in (G_NUMBER, G_FRACTION):
                adj_num.extend(a for a in adjacent_tiles(grid, t.x, t.y, player) if a.get_glyph() == G_LETTER)
    blue_ids = {id(t) for t in adj_blue}
    num_ids = {id(t) for t in adj_num}

    def pick(cands: list[Tile]) -> Tile:
        return cands[rng.range(0, len(cands))]

    def tiered(base: list[Tile], use_blue: bool, use_num: bool) -> Tile | None:
        if use_blue and use_num:
            both = [t for t in base if id(t) in blue_ids and id(t) in num_ids]
            if both:
                return pick(both)
        if use_num:
            nn = [t for t in base if id(t) in num_ids]
            if nn:
                return pick(nn)
        if use_blue:
            bb = [t for t in base if id(t) in blue_ids]
            if bb:
                return pick(bb)
        if base:
            return pick(base)
        return None

    if tile_type != NORMAL and glyph != G_NONE and suited:
        base = [t for t in pool if t.get_glyph() == G_LETTER and t.is_type(NORMAL) and t.suit == SUIT_NONE]
        hit = tiered(base, flag, flag2)
        if hit is not None:
            return hit
    if tile_type != NORMAL and glyph != G_NONE:
        base = [t for t in pool if t.get_glyph() == G_LETTER and t.is_type(NORMAL)]
        hit = tiered(base, flag, flag2)
        if hit is not None:
            return hit
    if glyph != G_NONE and suited:
        base = [t for t in pool if t.get_glyph() == G_LETTER and t.suit == SUIT_NONE]
        hit = tiered(base, False, flag2)
        if hit is not None:
            return hit
    if tile_type != NORMAL and suited:
        base = [t for t in pool if t.is_type(NORMAL) and t.suit == SUIT_NONE]
        hit = tiered(base, flag, False)
        if hit is not None:
            return hit
    if glyph != G_NONE:
        base = [t for t in pool if t.get_glyph() == G_LETTER]
        hit = tiered(base, False, flag2)
        if hit is not None:
            return hit
    if tile_type != NORMAL:
        base = [t for t in pool if t.is_type(NORMAL)]
        hit = tiered(base, flag, False)
        if hit is not None:
            return hit
    if suited:
        base = [t for t in pool if t.suit == SUIT_NONE]
        if base:
            return pick(base)
    if tile_type != NORMAL and glyph == G_NONE:
        base = [t for t in pool if t.tile_type != tile_type]
        hit = tiered(base, flag, False)
        if hit is not None:
            return hit
    return pick(pool)


def tile_for_boss_scatter(g: GenCtx, blacklist: list[Tile]) -> Tile | None:
    """``GetTileForBossScatter``."""
    grid = g.grid
    unusable = {id(t) for t in blacklist}
    if g.player.run.challenge_is("UpAndUp"):
        mid = grid.at(grid.width // 2, grid.height // 2)
        if mid is not None:
            unusable.add(id(mid))
    pool = [t for t in grid.available() if id(t) not in unusable]
    if not pool:
        return None
    return pool[g.rng.range(0, len(pool))]


def contains_2x2(grid: GridData, tiles: list[Tile]) -> bool:
    coords = {(t.x, t.y) for t in tiles}
    for i in range(grid.width - 1):
        for j in range(grid.height - 1):
            if {(i, j), (i + 1, j), (i, j + 1), (i + 1, j + 1)} <= coords:
                return True
    return False


def knight_targets(grid: GridData, tile: Tile, player: "Player") -> list[Tile]:
    """Tiles a knight on ``tile`` can move to (``GetValidNextTiles`` for a lone knight)."""
    wrap = bool(player.unpacked_of("HungrySnake"))
    out: list[Tile] = []
    for dx, dy in ((1, 2), (2, 1), (2, -1), (1, -2), (-1, -2), (-2, -1), (-2, 1), (-1, 2)):
        x, y = tile.x + dx, tile.y + dy
        if wrap:
            x %= grid.width
        t = grid.available_at(x, y) if grid.valid(x, y) else None
        if t is not None and t is not tile:
            out.append(t)
    return out


def shuffle(rng: Rng, items: list) -> list:
    """``Player.Shuffle``: each element dropped into a random null slot.

    Null elements still roll but leave their slot null (free), like the game.
    """
    arr: list = [None] * len(items)
    for it in items:
        free = [i for i, v in enumerate(arr) if v is None]
        arr[free[rng.range(0, len(free))]] = it
    return arr
