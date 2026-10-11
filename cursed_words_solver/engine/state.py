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
        """``Player.GetAllItems()``: character item, stickers, stamps (non-null)."""
        out: list[ItemInst] = []
        if self.character_item is not None:
            out.append(self.character_item)
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
