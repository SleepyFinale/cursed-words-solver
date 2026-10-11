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

    def all_items(self) -> list[ItemInst]:
        """``Player.GetAllItems()``: character item, stickers, stamps (non-null).

        Under Playing Favourites only the pin, the favourite sticker (left of
        Left Hand), Left Hand, Right Hand and the stamp after Right Hand.
        """
        out: list[ItemInst] = []
        if self.character_item is not None:
            out.append(self.character_item)
        if self.challenge == "PlayingFavourites":
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
