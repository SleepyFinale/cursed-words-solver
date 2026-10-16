"""melmod ``game_state/1`` (live ``run_state.json`` or a round-log capture) → simulator objects.

``game_from_game_state`` rebuilds a ``Game`` positioned at the captured encounter so
an agent can plan from the real game, and so captures can validate the simulator.
Hidden state the export lacks (future boss drafts, RNG) is resampled.
"""

from __future__ import annotations

from typing import Any

from cursed_words_solver.engine.item_data import CLASS_TO_SLUG
from cursed_words_solver.sim.game import core as C
from cursed_words_solver.sim.game.core import GridData, Tile
from cursed_words_solver.sim.game.items import Item, catalog_rows, make_item
from cursed_words_solver.sim.game.player import BossModifier, HistoricWord, Node, boss_rows

_ASCENSIONS = {
    "None": 0, "CursedBosses": 1, "UnkindShops": 2, "LowerTileScores": 3, "LockedStampSlots": 4,
    "HarderGridGeneration": 5, "LockedStickerSlots": 6, "OneFewerGrid": 7, "HarderBosses": 8,
}
_SLUG_TO_CLASS = {s: c for c, s in CLASS_TO_SLUG.items()}


def _int(raw: Any, default: int = 0) -> int:
    try:
        if isinstance(raw, str) and raw.strip().lower() in ("inf", "infinity"):
            return 10**18
        return int(raw)
    except (TypeError, ValueError):
        return default


def item_from_row(row: dict[str, Any]) -> Item | None:
    cls = str(row.get("class") or "") or _SLUG_TO_CLASS.get(str(row.get("id") or ""), "")
    if cls not in catalog_rows():
        return None
    it = make_item(cls)
    levels = row.get("levels") or []
    values = row.get("values") or []
    for i, comp in enumerate(it.components):
        if i < len(levels):
            comp[0] = _int(levels[i], comp[0])
        if i < len(values):
            comp[2] = _int(values[i], comp[2])
    if it.components:
        it.times_upgraded = max(0, it.level(0) - 1)
    colours = row.get("colours")
    if isinstance(colours, list) and colours:
        it.relevant_colours = [C.TYPE_FROM_GAME.get(str(c), str(c).lower()) for c in colours]
    fields = row.get("fields")
    if isinstance(fields, dict):
        for k, v in fields.items():
            if k in ("IsFoil",):
                it.is_foil = bool(v)
            elif k == "TimesUpgraded":
                it.times_upgraded = _int(v)
            elif k == "MoneyInvested" and isinstance(v, list):
                it.money_invested = [_int(x) for x in v]
            else:
                it.fields[k] = v
    if "foil" in row:
        it.is_foil = bool(row["foil"])
    if "times_upgraded" in row:
        it.times_upgraded = _int(row["times_upgraded"])
    if isinstance(row.get("money_invested"), list):
        it.money_invested = [_int(x) for x in row["money_invested"]]
    if "selling_prevented" in row:
        it.selling_prevented = bool(row["selling_prevented"])
    if "discount" in row:
        it.discount = _int(row["discount"])
    # TileType-valued fields come over as enum names ("Cactus"); the sim uses lowercase types.
    for key in ("ChosenTileTypes",):
        val = it.fields.get(key)
        if isinstance(val, list):
            it.fields[key] = [C.TYPE_FROM_GAME.get(str(v), str(v).lower()) for v in val]
    if cls == "Bucket":
        tib = it.fields.pop("TilesInBucket", None)
        if isinstance(tib, list):
            it.tiles_in_bucket = [tile_from_row(t) for t in tib if isinstance(t, dict)]
        it.next_tiles = [
            tile_from_row(it.fields.pop(k)) if isinstance(it.fields.get(k), dict) else None
            for k in ("TileToAddToBucket1", "TileToAddToBucket2")
        ]
    if cls == "RandomAccessMemory":
        it.next_items = [
            item_from_row(it.fields.pop(k)) if isinstance(it.fields.get(k), dict) else None
            for k in ("ItemToAddToMemory1", "ItemToAddToMemory2")
        ]
        it.fields.pop("ItemsInMemory", None)
    if cls == "Frankenstein":
        it.fields.pop("StitchedItems", None)
    if cls == "Snapshot":
        it.fields.pop("SnapshottedItem", None)
    nested = [n for n in (row.get("nested") or []) if isinstance(n, dict)]
    if nested:
        kids = [k for k in (item_from_row(n) for n in nested) if k is not None]
        if cls == "RandomAccessMemory":
            it.memory = kids
        elif cls == "Frankenstein":
            it.stitched = kids
        elif cls == "Snapshot" and kids:
            it.snapshotted = kids[0]
    return it


def tile_from_row(row: dict[str, Any]) -> Tile:
    glyph = C.GLYPH_FROM_GAME.get(str(row.get("glyph") or "Letter"), C.G_LETTER)
    t = Tile()
    t.x, t.y = _int(row.get("x")), _int(row.get("y"))
    t.glyph = glyph
    t.letter = str(row.get("letter") or "")
    t.number = _int(row.get("number"), -1000)
    frac = row.get("fraction")
    if isinstance(frac, list) and len(frac) >= 2:
        t.fraction = (_int(frac[0]), _int(frac[1]))
    suit = str(row.get("suit") or "None").lower()
    t.suit = C.SUIT_NONE if suit == "none" else suit
    piece = str(row.get("piece") or "None").lower()
    t.piece = "none" if piece == "none" else piece
    t.white = bool(row.get("white"))
    t.tile_type = C.TYPE_FROM_GAME.get(str(row.get("type") or "Normal"), C.NORMAL)
    t.value_modifier = _int(row.get("value_modifier"))
    t.cactus_growth = _int(row.get("cactus_growth"))
    flags = set(row.get("flags") or ())
    t.was_consumable = "was_consumable" in flags
    t.was_glitch = "was_glitch" in flags
    t.crossed_out = "crossed_out" in flags
    t.in_void = "in_void" in flags
    t.destroyed = "destroyed" in flags
    t.gone = "gone" in flags
    if row.get("available") is False and not (t.in_void or t.destroyed):
        t.destroyed = True
    item = row.get("item")
    if isinstance(item, dict):
        t.item = item_from_row(item)
    return t


def apply_player(player, gs: dict[str, Any]) -> None:
    prow = gs.get("player") or {}
    player.money = _int(prow.get("money"))
    for key, arr in (("stickers", player.stickers), ("stamps", player.stamps)):
        rows = prow.get(key) or []
        for i in range(5):
            row = rows[i] if i < len(rows) else None
            arr[i] = item_from_row(row) if isinstance(row, dict) else None
    pin = prow.get("pin")
    if isinstance(pin, dict):
        player.pin = item_from_row(pin)
    cons = prow.get("consumables") or []
    player.consumables = [tile_from_row(r) if isinstance(r, dict) else None for r in cons[:10]]
    player.consumables += [None] * (10 - len(player.consumables))
    from cursed_words_solver.sim.game.shop import ItemInStock

    for key, n in (("frozen_stickers", 4), ("frozen_stamps", 2)):
        rows = prow.get(key)
        if isinstance(rows, list):
            frozen: list = []
            for r in rows[:n]:
                it = item_from_row(r) if isinstance(r, dict) else None
                frozen.append(ItemInStock(it, _int(r.get("cost"), it.base_cost), frozen=True) if it is not None else None)
            frozen += [None] * (n - len(frozen))
            setattr(player, key, frozen)
    for s in player.stickers:
        if s is not None and s.game_class != "LeftHumanHand":
            idx = player.stickers.index(s)
            if idx + 1 < 5 and player.stickers[idx + 1] is not None and player.stickers[idx + 1].game_class == "LeftHumanHand":
                s.is_hb_favourite_sticker = True


def apply_run(player, gs: dict[str, Any]) -> None:
    run = player.run
    rrow = gs.get("run") or {}
    run.stage = _int(rrow.get("stage"), 1)
    node = str(rrow.get("node_type") or "EncounterFirst")
    try:
        run.node = Node[_snake(node)]
    except KeyError:
        run.node = Node.ENCOUNTER_FIRST
    if "ascension" in rrow:
        run.ascension = _ASCENSIONS.get(str(rrow.get("ascension") or "None"), 0)
    else:
        run.ascension = _infer_ascension(gs)
    colours = rrow.get("available_colours")
    if isinstance(colours, list) and colours:
        run.available_colours = [C.TYPE_FROM_GAME.get(str(c), str(c).lower()) for c in colours]
    run.cactus_growth_level = _int(rrow.get("cactus_growth_level"))
    run.cursed_bosses_defeated = [_int(x) for x in rrow.get("cursed_bosses_defeated") or []]
    run.embargoed = {str(x) for x in rrow.get("embargoed_items") or []}
    if "has_faced_uncursed_boss" in rrow:
        player.has_faced_uncursed_boss = bool(rrow["has_faced_uncursed_boss"])
    if "piggy_bank_saved" in rrow:
        player.piggy_bank = _int(rrow["piggy_bank_saved"])
    ch = rrow.get("challenge")
    if isinstance(ch, dict) and ch.get("class"):
        from cursed_words_solver.sim.game.challenges import make_challenge

        try:
            run.challenge = make_challenge(str(ch["class"]))
        except KeyError:
            run.challenge = None


def _infer_ascension(gs: dict[str, Any]) -> int:
    """Older exports lack the crown: plain letters valued from the crown-3 table imply ≥ 3."""
    lower = normal = 0
    for t in (gs.get("grid") or {}).get("tiles") or ():
        if not isinstance(t, dict) or t.get("glyph") != "Letter" or t.get("type") != "Normal":
            continue
        if _int(t.get("value_modifier")) != 0:
            continue
        letter = str(t.get("letter") or "").lower()
        if letter not in C.LETTER_VALUES or C.LETTER_VALUES[letter] == C.ASCENSION_LETTER_VALUES[letter]:
            continue
        v = _int(t.get("value"))
        if v == C.ASCENSION_LETTER_VALUES[letter]:
            lower += 1
        elif v == C.LETTER_VALUES[letter]:
            normal += 1
    return 3 if lower > normal else 0


def _snake(name: str) -> str:
    import re

    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).upper()


def boss_from_row(row: dict[str, Any]) -> BossModifier | None:
    cls = str(row.get("class") or "")
    if cls not in boss_rows():
        return None
    b = BossModifier(cls)
    fields = row.get("fields") or {}
    b.floor_mod = _int(fields.get("FloorAdjustedModification"), b.floor_mod)
    b.cursed = bool(fields.get("IsCursed", False))
    if cls == "ExtraVoids" and fields.get("TileTypeToScatter"):
        b.fields["TileTypeToScatter"] = C.TYPE_FROM_GAME.get(str(fields["TileTypeToScatter"]), C.VOID)
    if cls == "DestroyGrid" and isinstance(fields.get("DestroyedCoordinates"), list):
        b.fields["DestroyedCoordinates"] = [tuple(c) for c in fields["DestroyedCoordinates"] if isinstance(c, (list, tuple))]
    if cls == "MichaelBoss":
        b.summoned_defeated = bool(fields.get("SummonedBossesDefeated"))
    return b


def apply_encounter(enc, gs: dict[str, Any]) -> None:
    erow = gs.get("encounter") or {}
    grow = gs.get("grid") or {}
    grid = GridData(width=_int(grow.get("width"), 5), height=_int(grow.get("height"), 5),
                    grid_number=_int(grow.get("grid_number"), 1))
    grid.tiles = [tile_from_row(r) for r in grow.get("tiles") or [] if isinstance(r, dict)]
    enc.grid = grid
    enc.total_target = _int(erow.get("total_target"))
    enc.remaining_target = _int(erow.get("remaining_target"), enc.total_target)
    enc.total_grids = _int(erow.get("total_grids"), 5)
    enc.remaining_grids = _int(erow.get("remaining_grids"), enc.total_grids - 1)
    enc.rerolls = _int(erow.get("rerolls"), 1)
    enc.twinkle_available = bool(erow.get("twinkle_toes_swap_available"))
    enc.bosses = [b for b in (boss_from_row(r) for r in erow.get("bosses") or [] if isinstance(r, dict)) if b is not None]
    words: list[HistoricWord] = []
    for w in erow.get("previous_words") or []:
        if not isinstance(w, dict):
            continue
        tiles = [tile_from_row(t) for t in w.get("tiles") or [] if isinstance(t, dict)]
        dims = w.get("dims") or [grid.width, grid.height]
        words.append(HistoricWord(
            tiles=tiles, words=[str(x) for x in w.get("words") or []], skipped=bool(w.get("skipped")),
            score=_int(w.get("score")), remainder=_int(w.get("remainder")), submitted_round=_int(w.get("round")),
            dims=(int(dims[0]), int(dims[1])), values=[_int(t.get("value")) for t in w.get("tiles") or [] if isinstance(t, dict)],
        ))
    enc.previous_words = words


def game_from_game_state(gs: dict[str, Any], *, seed: int | str = 0, wordlist=None):
    """A ``Game`` placed in the captured encounter (boss drafts for later floors resampled)."""
    from cursed_words_solver.sim.game.encounter import Encounter
    from cursed_words_solver.sim.game.run import Game, RunConfig

    prow = gs.get("player") or {}
    character = str(prow.get("character") or "WetDennis")
    g = Game.__new__(Game)
    g.config = RunConfig(character=character, seed=seed, wordlist=wordlist)
    from cursed_words_solver.sim.game.core import Rng
    from cursed_words_solver.sim.game.player import Player
    from cursed_words_solver.sim.game.run import _Words

    g.rng = Rng(seed)
    g.player = Player(character)
    g.words = _Words(wordlist)
    g.events = []
    g.shop = None
    g.won = None
    g.end_reason = ""
    apply_run(g.player, gs)
    apply_player(g.player, gs)
    had_uncursed = g.player.has_faced_uncursed_boss
    g.player.run.generate_boss_drafts(g.rng, g.player)
    g.player.has_faced_uncursed_boss = had_uncursed or g.player.run.ascension == 0
    visible = (gs.get("run") or {}).get("boss_draft")
    run = g.player.run
    if isinstance(visible, list) and 0 < run.stage <= len(run.boss_drafts):
        opts = [b for b in (boss_from_row(r) for r in visible if isinstance(r, dict)) if b is not None]
        if opts:
            run.boss_drafts[run.stage - 1].options = opts
    enc = Encounter(g)
    apply_encounter(enc, gs)
    if g.player.run.node == Node.BOSS and enc.bosses and enc.bosses[0].game_class == "MichaelBoss":
        enc.michael = enc.bosses[0]
    g.encounter = enc
    return g
