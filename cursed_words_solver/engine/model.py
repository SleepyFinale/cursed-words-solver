"""Game-faithful tile, selection, and item-instance model for the scoring engine.

``ETile`` mirrors the fields of the game ``Tile`` that scoring reads (TileType,
GlyphType, letter/number/fraction/chess/suit faces, GetValue, consumable and
glitch flags, scattered item). ``ItemInst`` is one live ``Item`` with its upgrade
components, relevant colours and per-instance counters (Ruler distance, Neapolitan
multicoloured words, ...).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from cursed_words_solver.engine.item_data import ITEMS, ItemInfo
from cursed_words_solver.models import Board, CurseType, Tile, TileColor

# --- TileType / GlyphType / Suit as short strings -------------------------------------

NORMAL = "normal"
RED = "red"
BLUE = "blue"
PURPLE = "purple"
GOLD = "gold"
SHINY = "shiny"
VOID = "void"
WHITE = "white"
PINK = "pink"
GREEN = "green"
CACTUS = "cactus"
GLITCH = "glitch"

G_BLANK = "blank"
G_LETTER = "letter"
G_NUMBER = "number"
G_FRACTION = "fraction"
G_CHESS = "chess"
G_CARD = "bespoke_card"
G_CURRENCY = "currency"
G_ARROW = "arrow"
G_ITEM = "scattered_item"
G_NONE = "none"

SUIT_NONE = "none"
SUIT_JOKER = "joker"
SUITS = ("clubs", "diamonds", "hearts", "spades")

# TileSelectionMethod values that matter to scoring.
SEL_NORMAL = "normal"
SEL_TAKE = "chess_take"
SEL_EN_PASSANT = "en_passant"

# CurseType (game enum) values.
C_BLANK = "Blank"
C_NUMBER = "Number"
C_CHESS = "Chess"
C_CARD = "Card"
C_WOBBLY = "Wobbly"
C_CURRENCY = "Currency"
C_ARROW = "Arrow"
C_ITEM = "ScatteredItem"

CHESS_VALUES = {"none": 0, "pawn": 1, "knight": 3, "bishop": 3, "rook": 5, "queen": 9, "king": 15}

LETTERS = "abcdefghijklmnopqrstuvwxyz"
VOWELS = frozenset("aeiou")
CONSONANTS = frozenset("bcdfghjklmnpqrstvwxyz")
LETTER_VALUES = {
    "a": 1, "b": 3, "c": 3, "d": 2, "e": 1, "f": 4, "g": 2, "h": 4, "i": 1, "j": 8,
    "k": 5, "l": 1, "m": 3, "n": 1, "o": 1, "p": 3, "q": 10, "r": 1, "s": 1, "t": 1,
    "u": 1, "v": 4, "w": 4, "x": 8, "y": 4, "z": 10,
}

_COLOR_TO_TYPE = {
    TileColor.COLORLESS: NORMAL,
    TileColor.RED: RED,
    TileColor.BLUE: BLUE,
    TileColor.PURPLE: PURPLE,
    TileColor.GOLD: GOLD,
    TileColor.SHINY: SHINY,
    TileColor.VOID: VOID,
    TileColor.WHITE: WHITE,
    TileColor.PINK: PINK,
    TileColor.GREEN: GREEN,
    TileColor.CACTUS: CACTUS,
    TileColor.GLITCH: GLITCH,
    TileColor.UNKNOWN: NORMAL,
}

_CHESS_CURSES = {
    CurseType.CHESS_PAWN: "pawn",
    CurseType.CHESS_KNIGHT: "knight",
    CurseType.CHESS_BISHOP: "bishop",
    CurseType.CHESS_ROOK: "rook",
    CurseType.CHESS_QUEEN: "queen",
    CurseType.CHESS_KING: "king",
}


@dataclass(eq=False)
class ETile:
    """One grid tile as the game's ``Tile`` sees it (identity == the board cell)."""

    idx: int
    x: int  # game x: column within the playable area
    y: int  # row within the playable area (top-first; game y = height - 1 - y)
    tile_type: str
    glyph: str
    letter: str = ""  # lowercase Letter (letter / arrow) or mapped letter (currency)
    symbol: str = ""  # currency glyph as stored in Tile.Letter (e.g. "$")
    number: int | None = None
    fraction: tuple[int, int] | None = None
    piece: str = "none"
    white: bool = True
    suit: str = SUIT_NONE
    value: int = 0  # GetValue() at export time
    was_consumable: bool = False
    was_glitch: bool = False
    item: str = ""  # scattered item slug
    item_level: int | None = None
    in_void: bool = False  # IsInTheVoid / HasBeenDestroyed / inactive cell
    crossed_out: bool = False  # IsCrossedOut: cannot be clicked
    row: int = 0  # storage row / col (Board.tiles)
    col: int = 0

    def is_type(self, tt: str) -> bool:
        """``Tile.IsTileType`` — purple counts as red and blue."""
        if self.tile_type == PURPLE and tt in (RED, BLUE):
            return True
        return self.tile_type == tt

    def is_number(self) -> bool:
        return self.glyph in (G_NUMBER, G_FRACTION)

    def is_blank(self) -> bool:
        return self.glyph == G_BLANK

    def is_chess(self) -> bool:
        return self.glyph == G_CHESS

    @property
    def srep(self) -> str:
        """``GetStringRepresentation()`` (display form; font tags as stable tokens)."""
        g = self.glyph
        if g == G_CARD and self.suit == SUIT_JOKER:
            return "<joker>"
        if g == G_LETTER:
            return self.letter
        if g == G_CURRENCY:
            return f"<cur:{self.symbol}>"
        if g == G_ARROW:
            return f"<arrow:{self.letter.upper()}>"
        if g == G_FRACTION:
            a, b = self.fraction or (0, 0)
            return f"<frac:{a}/{b}>"
        if g == G_NUMBER:
            return str(self.number)
        if g == G_CHESS:
            return f"<chess:{self.piece}:{'w' if self.white else 'b'}>"
        if g == G_BLANK:
            return "?"
        if g == G_ITEM:
            return f"<item:{self.item}>"
        if g == G_NONE:
            return ""
        return self.letter

    def fraction_float(self) -> float:
        a, b = self.fraction or (0, 1)
        return float(a) / float(b) if b else 0.0

    def number_float(self) -> float:
        if self.glyph == G_NUMBER:
            return float(self.number or 0)
        return self.fraction_float()

    def curse_types(self, wobbly_letter: bool) -> list[str]:
        """``Tile.GetCurseTypes`` (``wobbly_letter`` = IsDisplayingAsVariableLetter)."""
        out: list[str] = []
        if self.suit != SUIT_NONE or self.glyph == G_CARD:
            out.append(C_CARD)
        g = self.glyph
        if g == G_CHESS:
            out.append(C_CHESS)
        elif g == G_CURRENCY:
            out.append(C_CURRENCY)
        elif g == G_ARROW:
            out.append(C_ARROW)
        elif g in (G_NUMBER, G_FRACTION):
            out.append(C_NUMBER)
        elif g == G_BLANK:
            out.append(C_BLANK)
        elif g == G_ITEM:
            out.append(C_ITEM)
        if wobbly_letter:
            out.append(C_WOBBLY)
        return out


@dataclass
class Selection:
    """``TileSelection`` fields read by items."""

    method: str = SEL_NORMAL
    en_passant: ETile | None = None
    move_distance: int = 0
    wobbly: bool = False


@dataclass
class ItemInst:
    """A live game ``Item``: upgrade components, colours, and mutable counters."""

    slug: str
    info: ItemInfo | None
    levels: list[int] = field(default_factory=list)
    variables: list[int] = field(default_factory=list)
    colours: list[str] = field(default_factory=list)
    state: dict[str, Any] = field(default_factory=dict)
    # Containers (RAM pin memory, Frankenstein stitches, Snapshot copy).
    nested: list["ItemInst"] = field(default_factory=list)
    is_scattered: bool = False

    @property
    def cls(self) -> str:
        return self.info.cls if self.info else ""

    @property
    def is_sticker(self) -> bool:
        return bool(self.info) and len(self.info.components) == 1

    @property
    def rarity(self) -> str:
        return self.info.rarity if self.info else "common"

    def var(self, i: int = 0) -> int:
        return self.variables[i] if i < len(self.variables) else 0

    def level(self, i: int = 0) -> int:
        return self.levels[i] if i < len(self.levels) else 1

    def clone(self) -> "ItemInst":
        """Per-submit copy: fresh counters/levels, shared immutable metadata."""
        state = dict(self.state)
        counts = state.get("letter_counts")
        if isinstance(counts, dict):
            state["letter_counts"] = dict(counts)
        return ItemInst(
            slug=self.slug,
            info=self.info,
            levels=list(self.levels),
            variables=list(self.variables),
            colours=self.colours,
            state=state,
            nested=[n.clone() for n in self.nested],
            is_scattered=self.is_scattered,
        )

    def upgrade(self, i: int = 0) -> None:
        if not self.info or i >= len(self.info.components):
            return
        self.levels[i] += 1
        self.variables[i] += self.info.components[i][1]


def make_item(
    slug: str,
    level: int | None = None,
    *,
    variables: list[int] | None = None,
    levels: list[int] | None = None,
) -> ItemInst:
    """Instantiate an item at ``level`` (component 0) like repeated ``Upgrade(0)``."""
    info = ITEMS.get(slug)
    inst = ItemInst(slug=slug, info=info)
    if info is None:
        return inst
    inst.levels = [c[0] for c in info.components]
    inst.variables = [c[2] for c in info.components]
    inst.colours = list(info.colours)
    if levels is not None:
        for i, lv in enumerate(levels[: len(inst.levels)]):
            inst.levels[i] = lv
            inst.variables[i] = info.components[i][2] + (lv - info.components[i][0]) * info.components[i][1]
    elif level is not None and inst.levels:
        target = max(1, int(level))
        while inst.levels[0] < target:
            inst.upgrade(0)
    if variables is not None:
        for i, v in enumerate(variables[: len(inst.variables)]):
            if v is not None:
                inst.variables[i] = int(v)
    return inst


def etile_from_tile(tile: Tile, idx: int, x: int, y: int, *, active: bool = True) -> ETile:
    """Build an ``ETile`` from the solver's parsed board ``Tile``."""
    meta = tile.metadata or {}
    tt = _COLOR_TO_TYPE.get(tile.color, NORMAL)
    curse = tile.curse
    suit = str(meta.get("card_suit") or "").strip().lower() or SUIT_NONE
    if suit not in SUITS and suit != SUIT_JOKER:
        suit = SUIT_NONE
    # Only BespokeCard jokers export is_joker; Bucket / fairy grids also put
    # Suit.Joker on ordinary letter / currency tiles, which keep their glyph.
    is_joker = bool(meta.get("is_joker"))
    letter = ""
    symbol = ""
    number = None
    fraction = None
    piece = "none"
    white = True
    item = ""
    item_level = None
    if not active:
        glyph = G_LETTER
    elif is_joker:
        glyph = G_CARD
        suit = SUIT_JOKER
    elif curse == CurseType.LETTER:
        glyph = G_LETTER
        letter = (tile.letter or tile.char or "").strip().lower()
    elif curse in (CurseType.WILDCARD, CurseType.BLANK):
        glyph = G_BLANK
    elif curse == CurseType.CURRENCY:
        glyph = G_CURRENCY
        from cursed_words_solver.models import CURRENCY_MAP

        symbol = (tile.char or "").strip()
        letter = CURRENCY_MAP.get(symbol, tile.letter or symbol).lower()
    elif curse == CurseType.NUMBER:
        glyph = G_NUMBER
        number = int(tile.number_value) if tile.number_value is not None else _int_or_zero(tile.char)
    elif curse == CurseType.FRACTION:
        glyph = G_FRACTION
        from cursed_words_solver.rules.fraction_tiles import fraction_parts

        parts = fraction_parts(tile)
        fraction = (int(parts[0]), int(parts[1])) if parts else (0, 1)
    elif curse in _CHESS_CURSES:
        glyph = G_CHESS
        piece = _CHESS_CURSES[curse]
        white = str(meta.get("chess_color") or "white").strip().lower() != "black"
    elif curse == CurseType.ITEM:
        glyph = G_ITEM
        item = str(meta.get("scattered_item_id") or "").strip().lower()
        lvl = meta.get("scattered_item_level")
        item_level = int(lvl) if lvl is not None else None
    elif curse == CurseType.ARROW:
        glyph = G_ARROW
        letter = (tile.letter or tile.char or "").strip().lower()
    else:
        glyph = G_LETTER
        letter = (tile.letter or "").strip().lower()
    try:
        value = int(round(float(tile.base_score)))
    except (TypeError, ValueError):
        value = 0
    if active and tt == VOID and value >= 0 and "value_exact" not in meta:
        # Legacy melmod clamps GetValue() to >= 0 except for void letters, and the
        # oldest captures omitted base_score: rebuild -(glyph base + ValueModifier).
        if glyph == G_LETTER and value > 0:
            value = -value
        elif glyph != G_LETTER or meta.get("base_score_missing"):
            base = _glyph_base(glyph, letter, number, fraction, piece)
            try:
                base += int(meta.get("value_modifier") or 0)
            except (TypeError, ValueError):
                pass
            value = -base
    return ETile(
        idx=idx,
        x=x,
        y=y,
        tile_type=tt,
        glyph=glyph,
        letter=letter,
        symbol=symbol,
        number=number,
        fraction=fraction,
        piece=piece,
        white=white,
        suit=suit,
        value=value if active else 0,
        was_consumable=bool(meta.get("was_consumable") or meta.get("consumable")),
        was_glitch=bool(meta.get("was_glitch")),
        item=item,
        item_level=item_level,
        in_void=not active,
        crossed_out=bool(meta.get("is_crossed_out")),
        row=y,
        col=x,
    )


def _glyph_base(glyph: str, letter: str, number: int | None, fraction: tuple[int, int] | None, piece: str) -> int:
    """``Tile.GetValue`` glyph term (before colour bonus / modifier / void sign)."""
    if glyph == G_NUMBER:
        return int(number or 0)
    if glyph == G_FRACTION:
        return sum(fraction or ())
    if glyph == G_LETTER:
        return LETTER_VALUES.get(letter, 0)
    if glyph == G_CHESS:
        return CHESS_VALUES.get(piece, 0)
    return 0


def _int_or_zero(raw: Any) -> int:
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return 0


def _playable_bounds(board: Board) -> tuple[int, int, int, int]:
    """Rows/cols of the live grid inside storage (Bat shrinks to 4x4)."""
    rows = [r for r in range(board.storage_rows) for c in range(board.storage_cols) if board.is_active_index(r * board.storage_cols + c)]
    cols = [c for r in range(board.storage_rows) for c in range(board.storage_cols) if board.is_active_index(r * board.storage_cols + c)]
    if board.playable_origin and board.playable_origin != "full":
        return board.playable_min_row, board.playable_max_row, board.playable_min_col, board.playable_max_col
    if not rows:
        return 0, board.storage_rows - 1, 0, board.storage_cols - 1
    if board.rows < board.storage_rows or board.cols < board.storage_cols:
        return min(rows), max(rows), min(cols), max(cols)
    return 0, board.storage_rows - 1, 0, board.storage_cols - 1


class EGrid:
    """``GridData`` view: tiles by storage index plus game-style coordinates."""

    def __init__(self, board: Board) -> None:
        self.board = board
        min_r, max_r, min_c, max_c = _playable_bounds(board)
        self.width = max_c - min_c + 1
        self.height = max_r - min_r + 1
        self.tiles: list[ETile] = []
        for idx in range(board.cell_count):
            r, c = board.coords_at(idx)
            tile = board.tiles[r][c]
            inside = min_r <= r <= max_r and min_c <= c <= max_c
            et = etile_from_tile(tile, idx, c, r, active=board.is_active_index(idx) and inside)
            et.x, et.y = c - min_c, r - min_r
            self.tiles.append(et)
        void_letters = [t for t in self.tiles if not t.in_void and t.tile_type == VOID and t.glyph == G_LETTER]
        if void_letters and all(t.value == 0 for t in void_letters):
            # Early melmod builds zeroed every void letter; signed exports always
            # carry at least one negative void letter on such a board.
            for t in void_letters:
                meta = board.tiles[t.row][t.col].metadata or {}
                if "value_exact" in meta:
                    continue
                t.value = -(LETTER_VALUES.get(t.letter, 0) + int(meta.get("value_modifier") or 0))
        self._by_xy = {(t.x, t.y): t for t in self.tiles}
        self.available = [t for t in self.tiles if not t.in_void]

    def at(self, x: int, y: int) -> ETile | None:
        return self._by_xy.get((x, y))

    def adjacent(self, tile: ETile, wrapping: bool) -> list[ETile]:
        """``GridUtility.GetTilesAdjacentToCoordinates`` (wrap branch skips void filter)."""
        out: list[ETile] = []
        seen: set[int] = set()
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                t = self._by_xy.get((tile.x + dx, tile.y + dy))
                if t is not None and not t.in_void and t.idx not in seen:
                    seen.add(t.idx)
                    out.append(t)
        if wrapping:
            wrap_x = None
            if tile.x == 0:
                wrap_x = self.width - 1
            elif tile.x == self.width - 1:
                wrap_x = 0
            if wrap_x is not None:
                for dy in (-1, 0, 1):
                    t = self._by_xy.get((wrap_x, tile.y + dy))
                    if t is not None and t.idx not in seen:
                        seen.add(t.idx)
                        out.append(t)
        return out


def are_adjacent(a: ETile, b: ETile) -> bool:
    """``GridUtility.AreAdjacentTiles`` (no wrapping)."""
    if abs(a.x - b.x) <= 1 and abs(a.y - b.y) <= 1:
        return not (a.x == b.x and a.y == b.y)
    return False


def _currency_map_lower() -> dict[str, str]:
    from cursed_words_solver.models import CURRENCY_MAP

    return {sym.lower(): letter.lower() for sym, letter in CURRENCY_MAP.items()}


# Currency glyph (word-validity form, lowercased) -> the letter it spells.
CURRENCY_MAP_LOWER: dict[str, str] = _currency_map_lower()
