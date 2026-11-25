"""Per-submit scoring state: ``ScoreCalcVizInfo`` steps and the read-only context."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from cursed_words_solver.engine.model import EGrid, ETile, ItemInst, Selection


@dataclass
class WordBonus:
    """``WordBonusToken``: additive or multiplicative (percent) bonus."""

    value: int | float
    mult: bool
    poison: bool = False


@dataclass
class Step:
    """``ScoreCalcVizInfo`` subset that affects the final score."""

    ts: list[int | float]
    money: int
    consumables: int  # occupied PlayerConsumableTiles slots
    wb: WordBonus | None = None
    item: str = ""  # RelevantItem slug (trace only)
    note: str = ""
    float_mult: bool = False

    def next(self) -> "Step":
        """``GetMatchingStep``: copy tile scores, money and rack; fresh word bonus."""
        return Step(ts=list(self.ts), money=self.money, consumables=self.consumables)


@dataclass
class HistWord:
    """``HistoricWord`` facts the scorers read (melmod historic_words row)."""

    score: int
    skipped: bool = False
    first_srep: str = ""
    first_is_letter: bool = False
    red_count: int = 0
    green_count: int = 0
    # Tile types of the word's tiles (game_state captures); empty for legacy exports.
    tile_types: tuple[str, ...] = ()


@dataclass
class Ctx:
    grid: EGrid
    tiles: list[ETile]
    sels: list[Selection]
    words: list[str]
    grid_number: int  # CurrentGridsGenerated() (ApplyWordBonus gridNumber)
    prev_words: list[HistWord]
    stickers: list[ItemInst | None]  # Player.Stickers slots
    stamps: list[ItemInst | None]  # Player.Stamps slots
    character_item: ItemInst | None
    unpacked: list[ItemInst]  # GetUnpackedItemsOfType universe
    hungry_snake: bool
    martini: bool
    cursed_bosses_defeated: int
    challenge: str
    flags: dict[str, Any] = field(default_factory=dict)
    # GridData.GridNumber: 0 on Michael's finale puzzle grid (not GenerateGrid).
    grid_data_number: int = 1
    # Per-tile IsCursed() (no path scattered items), filled by the engine.
    cursed: list[bool] = field(default_factory=list)
    # Per-tile IsDisplayingAsVariableLetter() used by GetCurseTypes on raw tiles.
    variable_letter: list[bool] = field(default_factory=list)
    nondeterministic: bool = False
    # DLC: SubmittedWords groups (path positions; uppercase words then lowercase words).
    groups: list[list[int]] | None = None
    plan: Any = None  # the EnginePlan (DLC hooks read grid / inventory helpers)
    # View bookkeeping (see view_all / set_view): full path lists while a group view is on.
    saved: tuple | None = None
    view_positions: list[int] | None = None
    _all_tiles: list[ETile] | None = None
    challenges: frozenset = frozenset()
    # DLC dice items: a random.Random samples each roll; None = expected value.
    rng: Any = None

    @property
    def all_tiles(self) -> list[ETile]:
        """``allTiles`` of ApplyWordBonus: every group's tiles concatenated (list4)."""
        return self._all_tiles if self._all_tiles is not None else self.tiles

    @property
    def path_tiles(self) -> list[ETile]:
        """The submitted path in selection order (whatever view is on)."""
        return self.saved[0] if self.saved is not None else self.tiles

    @property
    def path_sels(self) -> list[Selection]:
        return self.saved[1] if self.saved is not None else self.sels

    def view_all(self):
        """Context manager: remember the full-path lists and restore them afterwards."""
        ctx = self

        class _View:
            def __enter__(self_inner):
                ctx.saved = (ctx.tiles, ctx.sels, ctx.cursed, ctx.variable_letter)
                return ctx

            def __exit__(self_inner, *exc):
                ctx.tiles, ctx.sels, ctx.cursed, ctx.variable_letter = ctx.saved
                ctx.saved = None
                ctx.view_positions = None
                ctx._all_tiles = None
                return False

        return _View()

    def set_view(self, full: tuple, positions: list[int], all_positions: list[int] | None = None) -> None:
        tiles, sels, cursed, vl = full
        self.tiles = [tiles[k] for k in positions]
        self.sels = [sels[k] for k in positions]
        self.cursed = [cursed[k] for k in positions]
        self.variable_letter = [vl[k] for k in positions]
        self.view_positions = positions
        self._all_tiles = [tiles[k] for k in (all_positions if all_positions is not None else positions)]

    def all_items(self) -> list[ItemInst]:
        """``Player.GetAllItems()``: character item, stickers, stamps (non-null).

        Under Playing Favourites only the pin, the favourite sticker (left of
        Left Hand), Left Hand, Right Hand and the stamp after Right Hand.
        """
        out: list[ItemInst] = []
        if self.character_item is not None:
            out.append(self.character_item)
        if "PlayingFavourites" in self.challenges:
            st, sp = self.stickers, self.stamps
            for i, item in enumerate(st):
                if item is not None and i + 1 < len(st) and st[i + 1] is not None and st[i + 1].cls == "LeftHumanHand":
                    out.append(item)
            out.extend([i for i in st if i is not None and i.cls == "LeftHumanHand"][:1])
            right = [k for k, i in enumerate(sp) if i is not None and i.cls == "RightHumanHand"][:1]
            out.extend(sp[k] for k in right)
            if right and right[0] < 4 and right[0] + 1 < len(sp) and sp[right[0] + 1] is not None:
                out.append(sp[right[0] + 1])
            return out
        out.extend(i for i in self.stickers if i is not None)
        out.extend(i for i in self.stamps if i is not None)
        return out

    def has_unpacked(self, cls: str) -> bool:
        return any(i.cls == cls for i in self.unpacked)

    def last_prev_word(self) -> HistWord | None:
        for word in reversed(self.prev_words):
            if not word.skipped:
                return word
        return None
