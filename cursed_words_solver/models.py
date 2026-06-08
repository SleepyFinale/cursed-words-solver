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
    BLANK = "blank"
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
    ARROW = "arrow"
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

_MELMOD_CURSE_ALIASES: dict[str, CurseType] = {
    "letter": CurseType.LETTER,
    "wildcard": CurseType.WILDCARD,
    "blank": CurseType.BLANK,
    "currency": CurseType.CURRENCY,
    "number": CurseType.NUMBER,
    "fraction": CurseType.FRACTION,
    "chess_pawn": CurseType.CHESS_PAWN,
    "chess_bishop": CurseType.CHESS_BISHOP,
    "chess_rook": CurseType.CHESS_ROOK,
    "chess_knight": CurseType.CHESS_KNIGHT,
    "chess_queen": CurseType.CHESS_QUEEN,
    "chess_king": CurseType.CHESS_KING,
    "card": CurseType.CARD,
    "item": CurseType.ITEM,
    "arrow": CurseType.ARROW,
    "unknown": CurseType.UNKNOWN,
}


def curse_type_from_key(key: str) -> CurseType:
    """Map melmod/wiki curse string to CurseType."""
    k = (key or "letter").strip().lower()
    if k.startswith("chess_"):
        return _MELMOD_CURSE_ALIASES.get(k, CurseType.CHESS_PAWN)
    return _MELMOD_CURSE_ALIASES.get(k, CurseType.UNKNOWN)


def tile_counts_as_color(tile: Tile, color: TileColor) -> bool:
    """Game IsTileType: PURPLE counts as both RED and BLUE."""
    if tile.color == color:
        return True
    if tile.color == TileColor.PURPLE and color in (TileColor.RED, TileColor.BLUE):
        return True
    return False


def normalize_glyph_curse(curse: CurseType) -> CurseType:
    """Blank tiles behave as wildcards in search/scoring."""
    if curse == CurseType.BLANK:
        return CurseType.WILDCARD
    return curse


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
    _flat_cache: list[Tile] | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if len(self.active) != 25:
            self.active = [True] * 25
        self._rebuild_flat_cache()

    def _rebuild_flat_cache(self) -> None:
        self._flat_cache = [t for row in self.tiles for t in row]

    def _flat_cache_valid(self) -> bool:
        cache = self._flat_cache
        if cache is None:
            return False
        for i in range(25):
            r, c = divmod(i, 5)
            if cache[i] is not self.tiles[r][c]:
                return False
        return True

    @property
    def flat(self) -> list[Tile]:
        global _board_flat_call_count
        _board_flat_call_count += 1
        if not self._flat_cache_valid():
            self._rebuild_flat_cache()
        return self._flat_cache

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
        row, col = divmod(idx, 5)
        return self.tiles[row][col]


_board_flat_call_count = 0


def reset_board_flat_call_count() -> None:
    """Reset Board.flat access counter (used by structure analysis)."""
    global _board_flat_call_count
    _board_flat_call_count = 0


def board_flat_call_count() -> int:
    return _board_flat_call_count


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
class ShopOffer:
    slot: str  # sticker | stamp | tile
    index: int
    id: str
    name: str
    level: int = 1
    foil: bool = False
    price: int = 0
    base_price: int = 0
    frozen: bool = False
    free: bool = False
    sold: bool = False
    hippo_eligible: bool = False
    color: str = ""
    curse: str = ""
    letter: str = ""
    base_score: float = 0.0


@dataclass
class SellCandidate:
    kind: str  # sticker | stamp
    slot: int
    id: str
    name: str
    level: int = 1
    foil: bool = False
    sell_value: int = 0
    sell_cost: int = 0
    costs_money_to_sell: bool = False


@dataclass
class ShopState:
    restock_cost: int = 0
    free_item_available: bool = False
    angel_investment_available: bool = False
    hungry_hippo_equipped: bool = False
    offers: list[ShopOffer] = field(default_factory=list)


@dataclass
class EncounterGridRerollState:
    remaining: int = 0
    cost_per_use: int = 0
    can_reroll: bool = False
    wheel_equipped: bool = False
    fan_equipped: bool = False


# Backward compatibility alias
EncounterRerollState = EncounterGridRerollState


@dataclass
class RankedAction:
    action: str
    label: str
    net_value: float
    score_lift: float = 0.0
    money_delta: int = 0
    reason: str = ""
    offer_index: int | None = None
    sell_slot: int | None = None
    kind: str = ""


@dataclass
class ActionRecommendation:
    action: str  # buy | skip | yes | no
    label: str
    net_value: float = 0.0
    reason: str = ""


@dataclass
class ShopAdvice:
    buys: list[RankedAction] = field(default_factory=list)
    sells: list[RankedAction] = field(default_factory=list)
    restock: ActionRecommendation | None = None
    special_actions: list[RankedAction] = field(default_factory=list)
    freezes: list[RankedAction] = field(default_factory=list)
    leave_shop: ActionRecommendation | None = None
    warnings: list[str] = field(default_factory=list)
    primary_action: str = ""
    build: str = ""
    function: str = ""
    reason: str = ""


@dataclass
class WordResult:
    word: str
    path: list[int]  # tile indices 0-24
    score: float
    breakdown: dict[str, Any] = field(default_factory=dict)
    dictionary_word: str | None = None
    setup_bonus: float = 0.0
    rank_score: float = 0.0

    def path_coords(self) -> list[tuple[int, int]]:
        return [(i // 5, i % 5) for i in self.path]

    def display_word(self) -> str:
        """Word shown in UI: resolved dictionary spelling when available."""
        if self.dictionary_word and self.dictionary_word.lower() != self.word.lower():
            return self.dictionary_word
        return self.word
