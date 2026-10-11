"""``ScoreCalculation.CalculateOverallScore`` + ``GetScoreFromScoreCalcInfo`` port.

``EnginePlan.build`` resolves a loadout into live item instances once per solve;
``EnginePlan.score`` then scores any path on that board. The flow mirrors
``EncounterController.SubmitWord``:

1. Cable Car upgrades on-path scattered stickers.
2. Glitch settle (random → flagged nondeterministic), initial ``GetValue`` scores.
3. Boss modifiers (unless an odd number of Hourglasses reverses the order).
4. Bones Round poker hand, currency money, pink piggy-bank money.
5. Scattered path items then ``GetAllItems`` (pin, stickers, stamps), with RAM /
   Frankenstein / Snapshot / Overhand / Human Boy replays.
6. Reversed bosses (Hourglass), Lexographer, green poison.
7. Final fold: sum last step's tile scores, then apply word bonuses in order.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Any

from cursed_words_solver.engine import packet as P
from cursed_words_solver.engine.item_data import CLASS_TO_SLUG, ITEMS, POOLS
from cursed_words_solver.engine.items import TILE_HOOKS, WORD_HOOKS, scissors_steps
from cursed_words_solver.engine.model import (
    G_ARROW,
    G_BLANK,
    G_CARD,
    G_CHESS,
    G_CURRENCY,
    G_ITEM,
    G_LETTER,
    G_NUMBER,
    G_FRACTION,
    GLITCH,
    GREEN,
    LETTER_VALUES,
    PINK,
    SEL_EN_PASSANT,
    SEL_TAKE,
    SUIT_JOKER,
    SUIT_NONE,
    WHITE,
    EGrid,
    ETile,
    ItemInst,
    Selection,
    make_item,
)
from cursed_words_solver.engine.state import Ctx, HistWord, Step, WordBonus
from cursed_words_solver.models import Board, Loadout

_COLOUR_POOLS = {"red": "RedBuildItems", "blue": "BlueBuildItems", "void": "VoidBuildItems"}


def _scatter_pool(inst: ItemInst) -> tuple[str, ...] | None:
    """Pool an upgrading scatterer draws from (GetRandomColourBuildItem etc.)."""
    if inst.cls in ("RetroRaider", "Toolbox"):
        colour = inst.colours[0] if inst.colours else ("void" if inst.cls == "RetroRaider" else "")
        return POOLS.get(_COLOUR_POOLS.get(colour, ""), ())
    if inst.cls == "CursedVHS":
        return POOLS.get("CursedBuildItems", ())
    if inst.cls == "Radio":
        return POOLS.get("ColourlessBuildItems", ())
    return None

# Boss slugs (melmod boss_id) -> BossModifier class acted on in ApplyBossModifier.
_BOSS_CLASS = {
    "salamander": "ReducedLetterValue",
    "fox": "StealsMoney",
    "robo_monkey": "NegativeMoney",
}


@dataclass
class EngineResult:
    score: int | float
    steps: list[Step]
    nondeterministic: bool = False
    # Inventory item counters after this submit (slug -> state), e.g. Ruler distance.
    final_states: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def int_score(self) -> int:
        return P.to_int(self.score)

    def trace(self) -> list[dict[str, Any]]:
        """Per-step trace (same step granularity as melmod's actual_trace)."""
        out: list[dict[str, Any]] = []
        running: int | float = 0
        for i, st in enumerate(self.steps):
            row: dict[str, Any] = {
                "phase": "init" if i == 0 else ("item" if st.item else (st.note or "step")),
                "rule_id": st.item,
                "tile_scores": [P.to_int(v) for v in st.ts],
                "money": st.money,
            }
            if st.wb is not None:
                row["word_bonus"] = P.to_int(st.wb.value)
                row["word_bonus_multiplicative"] = st.wb.mult
                row["word_bonus_poison"] = st.wb.poison
            out.append(row)
        running = final_score(self.steps)
        if out:
            out[-1]["final_score"] = P.to_int(running)
        return out


def _extra(extras: dict[str, Any], key: str) -> Any:
    raw = extras.get(key)
    if isinstance(raw, str):
        raw = raw.strip()
        if raw == "":
            return None
    return raw


def _extra_int(extras: dict[str, Any], key: str) -> int | None:
    raw = _extra(extras, key)
    if raw is None:
        return None
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return None


def _extra_json(extras: dict[str, Any], key: str) -> Any:
    raw = _extra(extras, key)
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None
    return raw


def _slug(raw: Any) -> str:
    import re

    return re.sub(r"[^0-9a-z]+", "_", str(raw or "").lower()).strip("_")


def _seed_state(inst: ItemInst, extras: dict[str, Any]) -> None:
    """Load an inventory item's persistent counters from melmod extras."""
    cls = inst.cls
    if cls == "Neapolitan":
        pct = _extra_int(extras, "neapolitan_percent")
        if pct is not None and pct >= 100:
            inst.state["count"] = (pct - 100) // 5
    elif cls == "Ruler":
        dist = _extra_int(extras, "ruler_distance")
        if dist is not None:
            inst.state["distance"] = max(0, dist)
    elif cls == "Bicycle":
        bonus = _extra_int(extras, "bicycle_word_score_bonus")
        if bonus is not None:
            inst.state["bonus"] = bonus
    elif cls == "BirthdayCake":
        raw = _extra(extras, "birthday_cake_bonus")
        if raw is not None:
            try:
                inst.state["bonus"] = float(raw)
            except (TypeError, ValueError):
                pass
    elif cls == "MovieCamera":
        bonus = _extra_int(extras, "movie_camera_word_score_bonus")
        if bonus is not None:
            inst.state["bonus"] = bonus
    elif cls == "MichaelsBook":
        # Count x 30; legacy melmod sometimes exported another int field
        # (WordLength), so only multiples of 30 are trusted.
        bonus = _extra_int(extras, "michael_book_bonus")
        if bonus is not None and bonus > 0 and bonus % 30 == 0:
            inst.state["count"] = bonus // 30
        word = _extra(extras, "michael_book_word")
        if word:
            inst.state["current_word"] = str(word).lower()
    elif cls == "MutatingDNA":
        counts = _extra_json(extras, "mutating_dna_letter_counts")
        if isinstance(counts, dict):
            inst.state["letter_counts"] = {
                (k.lower() if len(str(k)) == 1 and str(k).isalpha() else str(k)): int(v)
                for k, v in counts.items()
            }
    elif cls == "TileNinja":
        used = _extra_int(extras, "tile_ninja_consumables_used")
        if used is None:
            pct = _extra_int(extras, "tile_ninja_word_bonus_percent")
            if pct is not None and pct >= 120:
                used = (pct - 120) // 2
        if used is not None:
            inst.state["used"] = used
    elif cls == "ShavedIce":
        freezes = _extra_int(extras, "shaved_ice_freezes")
        if freezes is None:
            pct = _extra_int(extras, "shaved_ice_word_bonus_percent")
            if pct is not None and pct >= 100:
                freezes = (pct - 100) // 20
        if freezes is not None:
            inst.state["freezes"] = freezes
    elif cls == "LuckyDice":
        target = _extra_int(extras, "target_number")
        if target is not None:
            inst.state["dice_number"] = target
    elif cls == "Avocado":
        inst.state["mushy"] = str(_extra(extras, "avocado_mushy") or "").lower() == "true"
    elif cls == "EightBall":
        piece = _extra(extras, "target_chess_piece")
        if piece:
            inst.state["selected_piece"] = _slug(piece)
    elif cls == "CrystalBall":
        curse = _extra(extras, "target_curse_type")
        if curse:
            names = {"blank": "Blank", "number": "Number", "chess": "Chess", "card": "Card",
                     "wobbly": "Wobbly", "currency": "Currency", "arrow": "Arrow",
                     "scattereditem": "ScatteredItem", "scattered_item": "ScatteredItem"}
            inst.state["chosen_curse"] = names.get(_slug(curse), str(curse))
    # Generic per-item fields (melmod item_state export) override legacy extras.


_ITEM_STATE_FIELDS: dict[str, str] = {
    "MulticolouredWordsSubmitted": "count",
    "Distance": "distance",
    "WordScoreBonus": "bonus",
    "Count": "count",
    "CurrentWord": "current_word",
    "ConsumableTilesUsed": "used",
    "Freezes": "freezes",
    "_diceNumber": "dice_number",
    "_targetNumber": "target_number",
    "_selectedPiece": "selected_piece",
    "ChosenCurseType": "chosen_curse",
    "IsMushy": "mushy",
    "Bonus": "bonus",
    "NumberOfGlitchTilesUsed": "glitch_used",
    "IsBroken": "broken",
    "LetterUseCounts": "letter_counts",
}


def _apply_item_state(inst: ItemInst, fields: dict[str, Any] | None) -> None:
    """Map raw game field values (melmod ``state`` export) onto engine counters."""
    if not isinstance(fields, dict):
        return
    mapping = _ITEM_STATE_FIELDS
    for key, value in fields.items():
        target = mapping.get(key)
        if target is None:
            continue
        if target == "selected_piece" and isinstance(value, str):
            value = value.lower()
        if target == "chosen_curse" and isinstance(value, str):
            value = value  # CurseType enum name, matches engine C_* constants
        if target == "current_word" and isinstance(value, str):
            value = value.lower()
        inst.state[target] = value
    colours = fields.get("RelevantColours")
    if isinstance(colours, list) and colours:
        inst.colours = [_tile_type_name(c) for c in colours]


def inst_from_state(d: dict[str, Any]) -> ItemInst:
    """ItemInst from melmod ``item_states`` (exact levels / values / counters)."""
    slug = _slug(d.get("id"))
    inst = make_item(slug)
    levels = d.get("levels")
    values = d.get("values")
    if isinstance(levels, list) and levels:
        inst.levels = [int(x) for x in levels]
    if isinstance(values, list) and values:
        inst.variables = [int(x) for x in values]
    colours = d.get("colours")
    if isinstance(colours, list) and colours:
        inst.colours = [_tile_type_name(c) for c in colours]
    _apply_item_state(inst, d.get("fields"))
    for nested in d.get("nested") or ():
        if isinstance(nested, dict):
            inst.nested.append(inst_from_state(nested))
    return inst


def _tile_type_name(raw: Any) -> str:
    name = str(raw or "").strip().lower()
    return "normal" if name in ("normal", "colourless", "colorless") else name


@dataclass
class EnginePlan:
    """Loadout resolved into live items for one board (build once per solve)."""

    grid: EGrid
    extras: dict[str, Any]
    money: int
    stickers: list[ItemInst | None]
    stamps: list[ItemInst | None]
    character_item: ItemInst | None
    unpacked: list[ItemInst]
    item_classes: set[str]
    colour_lists: dict[str, list[str]]
    boss_mods: list[tuple[str, int]]
    hourglass_odd: bool
    challenge: str
    prev_words: list[HistWord]
    grid_number: int
    cable_cars: int
    favourite_stamps: set[int] = field(default_factory=set)
    overhand: dict[int, int] = field(default_factory=dict)  # stamp slot -> repeats
    martini_all: bool = False
    martini_unpacked: bool = False
    hungry_snake: bool = False
    king_of_bridge: bool = False
    full_moon: bool = False
    kokeshi: bool = False
    cursed_bosses_defeated: int = 0
    sicilian: bool = False

    # ------------------------------------------------------------------ build

    @classmethod
    def build(cls, board: Board, loadout: Loadout) -> "EnginePlan":
        extras = dict(loadout.extras or {})
        grid = EGrid(board)
        money = int(loadout.money if loadout.money is not None else board.money)

        item_states = _extra_json(extras, "item_states") or {}

        def inst_for(slug: str, level: int | None, key: str) -> ItemInst:
            inst = make_item(slug, level)
            _seed_state(inst, extras)
            _apply_item_state(inst, item_states.get(key) if isinstance(item_states, dict) else None)
            return inst

        exact_states = item_states if isinstance(item_states, dict) and "stickers" in item_states else None
        stickers: list[ItemInst | None] = []
        stamps: list[ItemInst | None] = []
        if exact_states is not None:
            # Exact slots (empty slots kept), levels, values and counters.
            for key, out in (("stickers", stickers), ("stamps", stamps)):
                for row in exact_states.get(key) or ():
                    out.append(inst_from_state(row) if isinstance(row, dict) else None)
        else:
            for i, s in enumerate(loadout.stickers):
                stickers.append(inst_for(_slug(s.id), int(s.level or 1), f"sticker:{i}"))
            for i, s in enumerate(loadout.stamps):
                stamps.append(inst_for(_slug(s.id), 1, f"stamp:{i}"))

        pin_slug = _slug(_extra(extras, "pin_effect") or "")
        character_item: ItemInst | None = None
        if exact_states is not None and isinstance(exact_states.get("pin"), dict):
            character_item = inst_from_state(exact_states["pin"])
        elif pin_slug and pin_slug in ITEMS:
            levels = [_extra_int(extras, "pin_left_level") or 1, _extra_int(extras, "pin_right_level") or 1]
            variables = [_extra_int(extras, "pin_left_variable"), _extra_int(extras, "pin_right_variable")]
            character_item = make_item(pin_slug, levels=levels, variables=variables)
            _seed_state(character_item, extras)
            _apply_item_state(character_item, item_states.get("pin") if isinstance(item_states, dict) else None)

        levels_exact = exact_states is not None or extras.get("item_levels_exact") in (True, "true", "1")
        if not levels_exact and character_item is not None and character_item.cls == "HumanHands":
            # Player.RefreshFavouriteSticker: the sticker left of Left Hand gets
            # LeftHandUpgrade (Upgrade(0) x pin left VariableValue), which the
            # legacy TimesUpgraded-based level export never saw.
            for idx in range(1, len(stickers)):
                hand, fav = stickers[idx], stickers[idx - 1]
                if hand is not None and hand.cls == "LeftHumanHand" and fav is not None and fav.levels:
                    for _ in range(character_item.var(0)):
                        fav.upgrade(0)

        # Containers (legacy extras; exact item_states already carry nested items).
        if exact_states is None and character_item is not None and character_item.cls == "RandomAccessMemory":
            memory = _extra_json(extras, "pin_memory")
            if isinstance(memory, list):
                for j, row in enumerate(memory):
                    if not isinstance(row, dict):
                        continue
                    mem = make_item(_slug(row.get("id")), int(row.get("level") or 1))
                    if row.get("birthday_cake_bonus") is not None:
                        mem.state["bonus"] = float(row["birthday_cake_bonus"])
                    _apply_item_state(mem, row.get("state"))
                    character_item.nested.append(mem)
        stitched = _extra_json(extras, "stitched_sticker_ids")
        for s in stickers if exact_states is None else ():
            if s is not None and s.cls == "Frankenstein" and isinstance(stitched, list):
                for row in stitched:
                    if isinstance(row, dict):
                        s.nested.append(make_item(_slug(row.get("id")), int(row.get("level") or 1)))
                    else:
                        s.nested.append(make_item(_slug(row), 1))
        snap_slug = _slug(_extra(extras, "snapshot_copy_slug") or "")
        for s in (stickers + stamps) if exact_states is None else ():
            if s is not None and s.cls == "Snapshot" and snap_slug and snap_slug in ITEMS:
                copy_inst = make_item(snap_slug, _extra_int(extras, "snapshot_copy_level") or 1)
                _seed_state(copy_inst, extras)
                s.nested.append(copy_inst)

        # GetUnpackedItemsOfType universe.
        all_items = ([character_item] if character_item else []) + [i for i in stickers + stamps if i]
        unpacked = list(all_items)
        for it in all_items:
            if it.cls in ("RandomAccessMemory", "Snapshot", "Frankenstein"):
                unpacked.extend(it.nested)
        classes = {i.cls for i in all_items}
        for it in all_items:
            if it.cls in ("RandomAccessMemory", "Snapshot"):
                classes.update(n.cls for n in it.nested)
        colour_lists: dict[str, list[str]] = {}
        for it in all_items + [n for it in all_items if it.cls in ("RandomAccessMemory", "Snapshot") for n in it.nested]:
            if it.cls in ("Flamingo", "RedEnvelope", "SpicyPepper", "Automobile"):
                colour_lists.setdefault(it.cls, []).extend(it.colours)
        for it in all_items:
            if it.cls == "Frankenstein":
                classes.update(n.cls for n in it.nested)

        if "GlobeTrotter" in classes:
            # GlobeTrotter: corner tiles become currency with ValueModifier +10;
            # legacy exports clamp the void version (-10) to 0.
            w, h = grid.width, grid.height
            for t in grid.tiles:
                corner = t.x in (0, w - 1) and t.y in (0, h - 1)
                meta = board.tiles[t.row][t.col].metadata or {}
                if corner and t.glyph == G_CURRENCY and t.tile_type == "void" and t.value == 0 and "value_exact" not in meta:
                    t.value = -10

        boss_mods: list[tuple[str, int]] = []
        mods = _extra_json(extras, "boss_modifiers")
        floor_mods = _extra_json(extras, "boss_modifier_floor_mods") or {}
        boss_ids = [str(m) for m in mods] if isinstance(mods, list) else ([loadout.boss_id] if loadout.boss_id else [])
        for bid in boss_ids:
            name = _BOSS_CLASS.get(_slug(bid))
            if name is None:
                continue
            mod = floor_mods.get(bid) if isinstance(floor_mods, dict) else None
            if mod is None:
                mod = _extra_int(extras, "boss_floor_modification") or 0
            boss_mods.append((name, int(mod)))

        hourglasses = sum(1 for i in unpacked if i.cls == "Hourglass")
        if hourglasses == 0:
            hourglasses = _extra_int(extras, "hourglass_count") or 0

        prev_words = _historic_words(extras)

        # Player.IsHumanBoyFavouriteStamp: the stamp right after Right Hand.
        favourite = {
            idx
            for idx in range(1, len(stamps))
            if stamps[idx] is not None and stamps[idx - 1] is not None and stamps[idx - 1].cls == "RightHumanHand"
        }

        overhand: dict[int, int] = {}
        for idx, st in enumerate(stickers):
            if st is not None and st.cls == "Overhand" and idx < len(stamps) and stamps[idx] is not None:
                overhand[idx] = st.var() or (_extra_int(extras, "overhand_level") or 1)

        return cls(
            grid=grid,
            extras=extras,
            money=money,
            stickers=stickers,
            stamps=stamps,
            character_item=character_item,
            unpacked=unpacked,
            item_classes=classes,
            colour_lists=colour_lists,
            boss_mods=boss_mods,
            hourglass_odd=hourglasses % 2 == 1,
            challenge=str(_extra(extras, "challenge_game_class") or ""),
            prev_words=prev_words,
            grid_number=_extra_int(extras, "grid_number") or 1,
            cable_cars=sum(1 for i in unpacked if i.cls == "CableCar"),
            favourite_stamps=favourite,
            overhand=overhand,
            martini_all="Martini" in {i.cls for i in all_items},
            martini_unpacked=any(i.cls == "Martini" for i in unpacked),
            hungry_snake=any(i.cls == "HungrySnake" for i in unpacked),
            king_of_bridge="KingOfTheBridge" in classes,
            full_moon="FullMoon" in classes,
            kokeshi=any(i.cls == "KokeshiDolls" for i in unpacked),
            cursed_bosses_defeated=_extra_int(extras, "cursed_bosses_defeated_count") or 0,
            sicilian=str(_extra(extras, "challenge_game_class") or "") == "SicilianDefense",
        )

    # ------------------------------------------------------------- helpers

    @property
    def rack_count(self) -> int:
        """Occupied ``Player.ConsumableTiles`` slots when scoring starts."""
        count = _extra_int(self.extras, "consumable_rack_count")
        if count is None:
            rack = _extra_json(self.extras, "consumable_rack")
            count = len(rack) if isinstance(rack, list) else 0
        return max(0, min(10, count))

    def variable_letter(self, t: ETile, extra_classes: set[str] = frozenset()) -> bool:
        """``Tile.IsDisplayingAsVariableLetter`` (extra_classes = path scattered items)."""
        if t.glyph in (G_BLANK, G_CHESS, G_ARROW, G_ITEM) or t.suit == SUIT_JOKER:
            return False
        classes = self.item_classes | extra_classes if extra_classes else self.item_classes
        rep = t.srep
        cl = self.colour_lists
        if extra_classes:
            cl = dict(cl)
            for cls_name in extra_classes:
                if cls_name in ("Flamingo", "RedEnvelope", "SpicyPepper", "Automobile"):
                    slug = CLASS_TO_SLUG.get(cls_name)
                    cl[cls_name] = list(cl.get(cls_name, [])) + list(ITEMS[slug].colours if slug else ())
        if "RedEnvelope" in classes and any(t.is_type(c) for c in cl.get("RedEnvelope", ())):
            if (t.glyph != G_LETTER or rep != "e") and (t.glyph != G_CURRENCY or t.symbol != "€"):
                return True
        if "SpicyPepper" in classes and any(t.is_type(c) for c in cl.get("SpicyPepper", ())):
            if (t.glyph != G_LETTER or rep != "s") and (t.glyph != G_CURRENCY or t.symbol != "$"):
                return True
        if "Automobile" in classes and any(t.is_type(c) for c in cl.get("Automobile", ())) and t.glyph == G_LETTER:
            return True
        if "SluggishZombie" in classes and t.glyph == G_LETTER and rep == "z":
            return True
        if "Jellyfish" in classes and t.glyph == G_LETTER and rep == "j":
            return True
        if "CardShark" in classes:
            suit = t.suit
            if suit == "clubs" and rep != "c":
                return True
            if suit == "diamonds" and rep != "d":
                return True
            if suit == "hearts" and rep != "h":
                return True
            if suit == "spades" and rep != "s" and t.symbol != "$":
                return True
            return False
        if "Queen" in classes and t.glyph == G_LETTER and rep == "q":
            return True
        if "Flamingo" in classes and any(t.is_type(c) for c in cl.get("Flamingo", ())):
            if t.glyph not in (G_NUMBER, G_FRACTION):
                return True
            if t.glyph == G_NUMBER and t.number != 1:
                return True
            if t.glyph == G_FRACTION and 1 not in (t.fraction or ()):
                return True
            return False
        if "TestTube" in classes and t.is_number():
            return True
        if "Microscope" in classes and t.value > 0:
            if t.glyph not in (G_NUMBER, G_FRACTION):
                return True
            if t.glyph == G_NUMBER and t.number != t.value:
                return True
            if t.glyph == G_FRACTION and t.value not in (t.fraction or ()):
                return True
            return False
        if "NumbersBunchOfGrapes" in classes and t.glyph == G_NUMBER and t.number in (1, 5, 10):
            return True
        return False

    def is_cursed(self, t: ETile) -> bool:
        """``Tile.IsCursed()``."""
        if t.glyph != G_LETTER:
            return True
        if t.suit != SUIT_NONE:
            return True
        return self.variable_letter(t)

    def _game_y(self, t: ETile) -> int:
        return self.grid.height - 1 - t.y

    def selections(self, tiles: list[ETile], path_classes: set[str]) -> list[Selection]:
        """Rebuild ``TileSelection`` methods along a path (GetValidNextTiles)."""
        sels: list[Selection] = []
        for i, cur in enumerate(tiles):
            sel = Selection(wobbly=self.variable_letter(cur, path_classes))
            if i > 0:
                prev = tiles[i - 1]
                if prev.glyph == G_CHESS:
                    if cur.glyph == G_CHESS and (cur.white != prev.white or self.king_of_bridge):
                        sel.method = SEL_TAKE
                    elif not self.sicilian and self._chess_moves_generated(prev, tiles[:i]):
                        ep = self._en_passant(prev, cur)
                        if ep is not None:
                            sel.method = SEL_EN_PASSANT
                            sel.en_passant = ep
                    if not self.sicilian and prev.piece in ("rook", "bishop", "queen") and self._chess_moves_generated(prev, tiles[:i]):
                        sel.move_distance = self._slide_distance(prev, cur)
            sels.append(sel)
        return sels

    def _chess_moves_generated(self, prev: ETile, prefix: list[ETile]) -> bool:
        """Chess moves are skipped when portal / Full Moon selections already exist."""
        if prev.tile_type == WHITE:
            return False
        if self.full_moon:
            used = {t.idx for t in prefix}
            for t in self.grid.available:
                if t.idx not in used and t.srep == prev.srep and t.glyph == prev.glyph:
                    return False
        return True

    def _en_passant(self, pawn: ETile, cur: ETile) -> ETile | None:
        if pawn.piece != "pawn" or cur.glyph == G_CHESS:
            return None
        h = self.grid.height
        py = self._game_y(pawn)
        on_rank = (pawn.white and py == h - 4) or (not pawn.white and py == 3)
        if not on_rank:
            return None
        dy = 1 if pawn.white else -1
        cy = self._game_y(cur)
        dx = cur.x - pawn.x
        if self.hungry_snake:
            w = self.grid.width
            dx = ((cur.x - pawn.x + 1) % w) - 1
        if cy - py != dy or dx not in (-1, 1):
            return None
        behind_y = cy - dy
        behind = self.grid.at(cur.x, h - 1 - behind_y)
        if behind is None or behind.glyph != G_CHESS or behind.piece != "pawn" or behind.white == pawn.white:
            return None
        return behind

    def _slide_distance(self, piece: ETile, cur: ETile) -> int:
        dirs: list[tuple[int, int]] = []
        if piece.piece in ("rook", "queen"):
            dirs += [(0, 1), (1, 0), (0, -1), (-1, 0)]
        if piece.piece in ("bishop", "queen"):
            dirs += [(1, 1), (1, -1), (-1, 1), (-1, -1)]
        w, h = self.grid.width, self.grid.height
        best = 0
        for dx, dy in dirs:
            x, gy = piece.x, self._game_y(piece)
            for n in range(1, 100):
                x += dx
                gy += dy
                if self.hungry_snake:
                    x %= w
                if not (0 <= x < w and 0 <= gy < h) or (x == piece.x and gy == self._game_y(piece)):
                    break
                t = self.grid.at(x, h - 1 - gy)
                if t is None:
                    break
                if t is cur:
                    best = max(best, n)
                if t.glyph == G_CHESS:
                    break
        return best

    # ------------------------------------------------------------- scoring

    def score(self, path: list[int], word: str = "", *, words: list[str] | None = None) -> EngineResult:
        grid = self.grid
        tiles = [grid.tiles[i] for i in path]
        path_items = [t for t in tiles if t.glyph == G_ITEM and t.item]
        path_classes = {ITEMS[t.item].cls for t in path_items if t.item in ITEMS}
        sels = self.selections(tiles, path_classes)
        word_list = words if words is not None else ([word.lower()] if word else [])

        # Per-submit item copies so persistent counters never leak between paths.
        stickers = [_fresh(s) for s in self.stickers]
        stamps = [_fresh(s) for s in self.stamps]
        character_item = _fresh(self.character_item)

        ctx = Ctx(
            grid=grid,
            tiles=tiles,
            sels=sels,
            words=word_list,
            grid_number=self.grid_number,
            prev_words=self.prev_words,
            stickers=stickers,
            stamps=stamps,
            character_item=character_item,
            unpacked=self.unpacked,
            hungry_snake=self.hungry_snake,
            martini=self.martini_all,
            cursed_bosses_defeated=self.cursed_bosses_defeated,
            challenge=self.challenge,
        )
        if str(self.extras.get("michael_summoned_bosses_defeated") or "").lower() == "true":
            ctx.grid_data_number = 0
        else:
            ctx.grid_data_number = self.grid_number
        ctx.variable_letter = [self.variable_letter(t) for t in tiles]
        ctx.cursed = [self.is_cursed(t) for t in tiles]

        steps: list[Step] = []
        if any(t.tile_type == GLITCH for t in tiles):
            ctx.nondeterministic = True
        rack = self.rack_count
        first = Step(ts=[t.value for t in tiles], money=self.money, consumables=min(10, rack))
        steps.append(first)

        if not self.hourglass_odd:
            for name, mod in self.boss_mods:
                steps.append(self._boss_step(steps[-1], name, mod, tiles))

        if self.challenge == "TheBonesRound" and any(t.suit != SUIT_NONE for t in tiles):
            from cursed_words_solver.engine.poker import HAND_POINTS, poker_hand

            step = steps[-1].next()
            hand, kind = poker_hand(tiles, 3 if self.martini_all else 5)
            if hand is not None and kind in HAND_POINTS:
                step.wb = WordBonus(HAND_POINTS[kind], False)
                step.note = kind
            steps.append(step)

        currency = [t for t in tiles if t.glyph == G_CURRENCY]
        if currency:
            step = steps[-1].next()
            for t in currency:
                step.money += LETTER_VALUES.get(t.letter, 1) if self.kokeshi else 1
            steps.append(step)
        pinks = [t for t in tiles if t.tile_type == PINK]
        if pinks:
            step = steps[-1].next()
            for _ in pinks:
                if step.money > 0:
                    step.money -= 1
            steps.append(step)

        # Item order: scattered items on the path, then GetAllItems().
        order: list[tuple[ItemInst, str, int]] = []
        for t in path_items:
            state = (self.grid.board.tiles[t.row][t.col].metadata or {}).get("scattered_item_state")
            inst = inst_from_state(state) if isinstance(state, dict) else make_item(t.item, self._scatter_level(t))
            inst.is_scattered = True
            for _ in range(self.cable_cars):
                if inst.is_sticker:
                    inst.upgrade(0)
            order.append((inst, "scattered", -1))
        if character_item is not None:
            order.append((character_item, "pin", -1))
        if self.challenge == "PlayingFavourites":
            # Player.GetAllItems under Playing Favourites: pin, favourite stickers,
            # Left Hand, Right Hand, and the stamp after Right Hand.
            fav = [
                (s, "sticker", i)
                for i, s in enumerate(stickers)
                if s is not None and i + 1 < len(stickers) and stickers[i + 1] is not None
                and stickers[i + 1].cls == "LeftHumanHand"
            ]
            order += fav
            order += [(s, "sticker", i) for i, s in enumerate(stickers) if s is not None and s.cls == "LeftHumanHand"][:1]
            right = [i for i, s in enumerate(stamps) if s is not None and s.cls == "RightHumanHand"][:1]
            order += [(stamps[i], "stamp", i) for i in right]
            if right and right[0] < 4 and right[0] + 1 < len(stamps) and stamps[right[0] + 1] is not None:
                order.append((stamps[right[0] + 1], "stamp", right[0] + 1))
        else:
            order += [(s, "sticker", i) for i, s in enumerate(stickers) if s is not None]
            order += [(s, "stamp", i) for i, s in enumerate(stamps) if s is not None]
        if self.hourglass_odd:
            order.reverse()

        human_boy_repeats = 0
        if self.favourite_stamps and character_item is not None:
            human_boy_repeats = max(0, character_item.var(1) - 1)

        for inst, kind, slot in order:
            if inst.cls == "RandomAccessMemory":
                for mem in inst.nested:
                    self._apply(mem, steps, ctx)
                continue
            if inst.cls == "Frankenstein":
                for part in inst.nested:
                    self._apply(part, steps, ctx)
                continue
            self._apply(inst, steps, ctx)
            if kind == "stamp" and slot in self.favourite_stamps:
                for _ in range(human_boy_repeats):
                    self._apply(inst, steps, ctx)
            if kind == "stamp" and slot in self.overhand:
                for _ in range(self.overhand[slot]):
                    self._apply(inst, steps, ctx)

        if self.hourglass_odd:
            for name, mod in reversed(self.boss_mods):
                steps.append(self._boss_step(steps[-1], name, mod, tiles))

        if self.challenge == "Lexographer":
            step = steps[-1].next()
            for i, t in enumerate(tiles):
                if sels[i].wobbly or ctx.cursed[i]:
                    step.ts[i] = 0
            steps.append(step)

        for prev in self.prev_words:
            if prev.green_count > 0:
                step = steps[-1].next()
                step.wb = WordBonus(P.mul(prev.green_count, P.scale(prev.score, 0.1)), False, True)
                step.note = "poison"
                steps.append(step)

        final_states: dict[str, dict[str, Any]] = {}
        for inst in ([character_item] if character_item else []) + [i for i in stickers + stamps if i]:
            final_states.setdefault(inst.slug, inst.state)
        return EngineResult(
            score=final_score(steps),
            steps=steps,
            nondeterministic=ctx.nondeterministic,
            final_states=final_states,
        )

    def _scatter_level(self, t: ETile) -> int | None:
        """Scattered item level (component 0) before Cable Car.

        Legacy melmod exports read ``TimesUpgraded``, which ``Item.Upgrade`` never
        bumps, so Retro Raider's void-pool scatters (upgraded to its own level in
        ``ApplyStartOfGridEffect``) export as level 1.
        """
        if self.extras.get("item_levels_exact") in (True, "true", "1"):
            return t.item_level
        info = ITEMS.get(t.item)
        if info is None or len(info.components) != 1:
            return t.item_level
        # Only these scatterers Upgrade(0) what they scatter (to their own level);
        # everything else lands at level 1. Legacy melmod level heuristics
        # (equipped-tier bleed, tombstone tier sums) are ignored.
        best = 1
        for s in self.stickers + self.stamps:
            if s is None:
                continue
            pool = _scatter_pool(s)
            if pool is not None and t.item in pool:
                best = max(best, s.var())
            if s.cls == "Stethoscope" and t.item in POOLS.get("NumberBuildStickers", ()):
                return t.item_level
        return best

    def _apply(self, inst: ItemInst, steps: list[Step], ctx: Ctx) -> None:
        cls = inst.cls
        if cls == "Scissors":
            steps.extend(scissors_steps(inst, steps[-1], ctx))
            return
        target = inst
        if cls == "Snapshot":
            if not inst.nested:
                return
            target = inst.nested[0]
        tile_hook = TILE_HOOKS.get(target.cls)
        word_hook = WORD_HOOKS.get(target.cls)
        if tile_hook is None and word_hook is None:
            return
        step = steps[-1].next()
        if tile_hook is not None:
            for i in range(len(ctx.tiles)):
                tile_hook(target, step, i, ctx)
        if word_hook is not None:
            word_hook(target, step, ctx)
        step.item = inst.slug if target is inst else f"{inst.slug}>{target.slug}"
        steps.append(step)

    def _boss_step(self, prev: Step, name: str, mod: int, tiles: list[ETile]) -> Step:
        step = prev.next()
        if name == "ReducedLetterValue":
            step.ts = [P.sub(v, mod) for v in step.ts]
        elif name == "StealsMoney" and step.money > 0:
            step.money = max(step.money - mod, 0)
        elif name == "NegativeMoney" and self.money > 0:
            step.wb = WordBonus(-mod * step.money, False)
        step.item = f"boss:{name}"
        return step


# Classes whose scoring hooks mutate per-instance counters during a submit.
_STATEFUL = frozenset({
    "Bicycle", "BirthdayCake", "MovieCamera", "Neapolitan", "MichaelsBook",
    "MutatingDNA", "Ruler", "ErrorItem", "MushroomUpgrade", "NestEgg",
})


def _fresh(inst: ItemInst | None) -> ItemInst | None:
    """Per-submit instance: clone only when a hook could mutate it."""
    if inst is None:
        return None
    if inst.cls in _STATEFUL or inst.nested:
        return inst.clone()
    return inst


def final_score(steps: list[Step]) -> int | float:
    """``GetScoreFromScoreCalcInfo``."""
    if not steps:
        return 0
    total: int | float = 0
    for v in steps[-1].ts:
        total = P.add(total, v)
    for step in steps:
        wb = step.wb
        if wb is None:
            continue
        if wb.mult:
            total = P.div(P.mul(total, wb.value), 100)
        else:
            total = P.add(total, wb.value)
    return total


def _historic_words(extras: dict[str, Any]) -> list[HistWord]:
    rows = _extra_json(extras, "historic_words")
    out: list[HistWord] = []
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            skipped = bool(row.get("skipped") or row.get("is_skipped"))
            try:
                score = int(float(row.get("score") or 0))
            except (TypeError, ValueError):
                score = 0
            out.append(
                HistWord(
                    score=score,
                    skipped=skipped,
                    red_count=int(row.get("red_tile_count") or 0),
                    green_count=int(row.get("green_tile_count") or 0),
                )
            )
    # The game's _previousWords for this encounter; stale melmod rows beyond the
    # live count (e.g. from an earlier encounter) are dropped.
    live = _extra_int(extras, "scoring_previous_words_count")
    if live is not None and 0 <= live < len(out):
        out = out[len(out) - live :] if live else []
    first = str(_extra(extras, "previous_word_first_letter") or "").strip().lower()
    if first:
        target = next((w for w in reversed(out) if not w.skipped), None)
        if target is None:
            target = HistWord(score=0)
            out.append(target)
        target.first_srep = first
        target.first_is_letter = len(first) == 1 and first.isalpha()
    return out
