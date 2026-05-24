"""Core data models."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TileColor(str, Enum):
    COLORLESS = "colorless"
    RED = "red"
    BLUE = "blue"
    SHINY = "shiny"
    VOID = "void"
    PURPLE = "purple"
    WHITE = "white"
    GOLD = "gold"
    PINK = "pink"
    GREEN = "green"
    CACTUS = "cactus"
    GLITCH = "glitch"
    UNKNOWN = "unknown"


class CurseType(str, Enum):
    LETTER = "letter"
    WILDCARD = "wildcard"
    CURRENCY = "currency"
    NUMBER = "number"
    FRACTION = "fraction"
    CHESS_PAWN = "chess_pawn"
    CHESS_BISHOP = "chess_bishop"
    CHESS_ROOK = "chess_rook"
    CHESS_KNIGHT = "chess_knight"
    CHESS_QUEEN = "chess_queen"
    CHESS_KING = "chess_king"
    CARD = "card"
    ITEM = "item"
    UNKNOWN = "unknown"


# Currency symbol -> letter mapping (wiki)
CURRENCY_MAP: dict[str, str] = {
    "฿": "B",
    "¥": "Y",
    "$": "S",
    "₡": "C",
    "€": "E",
    "₭": "K",
    "₮": "T",
    "₦": "N",
    "₩": "W",
    "₱": "P",
    "₣": "F",
    "₲": "G",
}

_UNITY_FONT_RE = re.compile(r"<font[^>]*>(.*?)</font>", re.IGNORECASE | re.DOTALL)


def normalize_tile_glyph(s: str) -> str:
    """Strip Unity rich-text wrappers and extract bare currency symbols."""
    text = (s or "").strip()
    if not text:
        return text
    match = _UNITY_FONT_RE.search(text)
    if match:
        text = match.group(1).strip()
    if text in CURRENCY_MAP:
        return text
    for sym in CURRENCY_MAP:
        if sym in text:
            return sym
    return text


CHESS_CURSES = {
    CurseType.CHESS_PAWN,
    CurseType.CHESS_BISHOP,
    CurseType.CHESS_ROOK,
    CurseType.CHESS_KNIGHT,
    CurseType.CHESS_QUEEN,
    CurseType.CHESS_KING,
}


@dataclass
class Tile:
    row: int
    col: int
    char: str  # display / primary character
    letter: str  # resolved letter for word building (A-Z or ?)
    base_score: float
    color: TileColor = TileColor.COLORLESS
    curse: CurseType = CurseType.LETTER
    number_value: int | None = None  # for NUMBER curse
    fraction_value: float | None = None
    ocr_confidence: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def index(self) -> int:
        return self.row * 5 + self.col

    def pos(self) -> tuple[int, int]:
        return (self.row, self.col)


@dataclass
class Board:
    tiles: list[list[Tile]]  # 5x5 storage; inactive cells may be placeholders
    money: int = 0
    rows: int = 5
    cols: int = 5
    active: list[bool] = field(default_factory=lambda: [True] * 25)
    # Shrunk-grid layout from melmod (top_first row/col); empty origin = full 5×5 slots.
    playable_origin: str = ""
    playable_min_row: int = 0
    playable_max_row: int = 4
    playable_min_col: int = 0
    playable_max_col: int = 4

    def __post_init__(self) -> None:
        if len(self.active) != 25:
            self.active = [True] * 25

    @property
    def flat(self) -> list[Tile]:
        return [t for row in self.tiles for t in row]

    def is_active_index(self, idx: int) -> bool:
        if not (0 <= idx < 25):
            return False
        return self.active[idx]

    def is_active_cell(self, row: int, col: int) -> bool:
        if not (0 <= row < 5 and 0 <= col < 5):
            return False
        return self.is_active_index(row * 5 + col)

    def get(self, row: int, col: int) -> Tile | None:
        if 0 <= row < 5 and 0 <= col < 5:
            return self.tiles[row][col]
        return None

    def get_by_index(self, idx: int) -> Tile:
        if not self.is_active_index(idx):
            raise IndexError(f"inactive board index {idx}")
        return self.flat[idx]


@dataclass
class LoadoutItem:
    id: str
    name: str
    level: int = 1
    kind: str = "sticker"  # pin | sticker | stamp


@dataclass
class Loadout:
    character: str = ""
    pin_branch: str = ""
    stickers: list[LoadoutItem] = field(default_factory=list)
    stamps: list[LoadoutItem] = field(default_factory=list)
    boss_id: str = ""
    boss_name: str = ""
    boss_effect: str = ""
    money: int = 0
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass
class WordResult:
    word: str
    path: list[int]  # tile indices 0-24
    score: float
    breakdown: dict[str, Any] = field(default_factory=dict)
    dictionary_word: str | None = None

    def path_coords(self) -> list[tuple[int, int]]:
        return [(i // 5, i % 5) for i in self.path]

    def display_word(self) -> str:
        """Word shown in UI: resolved dictionary spelling when available."""
        if self.dictionary_word and self.dictionary_word.lower() != self.word.lower():
            return self.dictionary_word
        return self.word
