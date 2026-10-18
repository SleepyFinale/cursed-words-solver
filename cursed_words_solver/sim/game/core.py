"""Game-faithful core types: Unity RNG semantics, ``Tile``, ``GridData``, alphabet tables.

Ported from Assembly-CSharp (``Tile``, ``GridData``, ``Alphabet``/``EnglishDefaultAlphabet``,
``Currency``, ``ChessPieces``, ``PlayingCardUtility``). Names follow the game so the
item / boss / challenge ports read like the decompile.

Tile types and glyphs use the engine's lowercase strings (``engine.model``) so the
scoring bridge can hand tiles straight to the engine.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Iterable

if TYPE_CHECKING:  # pragma: no cover
    from cursed_words_solver.sim.game.items import Item
    from cursed_words_solver.sim.game.player import Player

# ---------------------------------------------------------------------------- RNG


class Rng:
    """``UnityEngine.Random`` semantics on a seeded Python RNG."""

    __slots__ = ("_r",)

    def __init__(self, seed: int | str | None = None) -> None:
        self._r = random.Random(seed)

    def range(self, lo: int, hi: int) -> int:
        """``Random.Range(int, int)``: [lo, hi); returns lo when hi <= lo."""
        if hi <= lo:
            return lo
        return self._r.randrange(lo, hi)

    def range_f(self, lo: float, hi: float) -> float:
        """``Random.Range(float, float)``: inclusive."""
        return self._r.uniform(lo, hi)

    def value(self) -> float:
        """``Random.value``."""
        return self._r.random()

    def choice(self, seq):
        return seq[self.range(0, len(seq))]

    def fork(self, tag: str) -> "Rng":
        return Rng(f"{self._r.random()}|{tag}")

    def reseed(self, key: int | str) -> None:
        """Restart the stream from ``key`` in place (every holder of this Rng sees it)."""
        self._r.seed(key)

    def getstate(self):
        return self._r.getstate()

    def setstate(self, state) -> None:
        self._r.setstate(state)


# ---------------------------------------------------------------------------- enums

NORMAL, RED, BLUE, PURPLE, GOLD, SHINY, VOID = "normal", "red", "blue", "purple", "gold", "shiny", "void"
WHITE, PINK, GREEN, CACTUS, GLITCH = "white", "pink", "green", "cactus", "glitch"
ALL_TILE_TYPES = (NORMAL, RED, BLUE, SHINY, VOID, CACTUS, PINK, GOLD, GREEN, PURPLE, WHITE, GLITCH)
GAME_TYPE_NAMES = {
    NORMAL: "Normal", RED: "Red", BLUE: "Blue", PURPLE: "Purple", GOLD: "Gold", SHINY: "Shiny",
    VOID: "Void", WHITE: "White", PINK: "Pink", GREEN: "Green", CACTUS: "Cactus", GLITCH: "Glitch",
}
TYPE_FROM_GAME = {v: k for k, v in GAME_TYPE_NAMES.items()}

G_LETTER, G_BLANK, G_NUMBER, G_FRACTION, G_CHESS = "letter", "blank", "number", "fraction", "chess"
G_CARD, G_CURRENCY, G_ARROW, G_ITEM, G_NONE = "bespoke_card", "currency", "arrow", "scattered_item", "none"
GAME_GLYPH_NAMES = {
    G_LETTER: "Letter", G_BLANK: "Blank", G_NUMBER: "Number", G_FRACTION: "Fraction", G_CHESS: "Chess",
    G_CARD: "BespokeCard", G_CURRENCY: "Currency", G_ARROW: "Arrow", G_ITEM: "ScatteredItem", G_NONE: "None",
}
GLYPH_FROM_GAME = {v: k for k, v in GAME_GLYPH_NAMES.items()}

SUIT_NONE, SUIT_JOKER = "none", "joker"
CLUBS, SPADES, HEARTS, DIAMONDS = "clubs", "spades", "hearts", "diamonds"
CARD_SUITS = (CLUBS, SPADES, HEARTS, DIAMONDS)  # PlayingCardUtility.CardSuits order

PAWN, KNIGHT, BISHOP, ROOK, QUEEN, KING = "pawn", "knight", "bishop", "rook", "queen", "king"
ALL_CHESS_PIECES = (PAWN, KNIGHT, BISHOP, ROOK, QUEEN, KING)
CHESS_VALUES = {"none": 0, PAWN: 1, KNIGHT: 3, BISHOP: 3, ROOK: 5, QUEEN: 9, KING: 15}

# CurseType
C_BLANK, C_NUMBER, C_CHESS, C_CARD, C_WOBBLY = "Blank", "Number", "Chess", "Card", "Wobbly"
C_CURRENCY, C_ARROW, C_ITEM = "Currency", "Arrow", "ScatteredItem"

# ---------------------------------------------------------------------------- alphabet

# EnglishDefaultAlphabet (dictionary insertion order = a..z).
LETTERS = "abcdefghijklmnopqrstuvwxyz"
VOWELS = "aeiou"
CONSONANTS = "".join(c for c in LETTERS if c not in VOWELS)
LETTER_FREQUENCIES = {
    "a": 9, "b": 2, "c": 2, "d": 4, "e": 12, "f": 2, "g": 3, "h": 2, "i": 9, "j": 1,
    "k": 1, "l": 4, "m": 2, "n": 6, "o": 8, "p": 2, "q": 1, "r": 6, "s": 4, "t": 6,
    "u": 4, "v": 2, "w": 2, "x": 1, "y": 2, "z": 1,
}
ASCENSION_LETTER_FREQUENCIES = {
    "a": 7, "b": 2, "c": 2, "d": 4, "e": 8, "f": 2, "g": 3, "h": 2, "i": 6, "j": 3,
    "k": 3, "l": 4, "m": 2, "n": 6, "o": 6, "p": 2, "q": 2, "r": 6, "s": 4, "t": 6,
    "u": 4, "v": 3, "w": 3, "x": 3, "y": 3, "z": 2,
}
LETTER_VALUES = {
    "a": 1, "b": 3, "c": 3, "d": 2, "e": 1, "f": 4, "g": 2, "h": 4, "i": 1, "j": 8,
    "k": 5, "l": 1, "m": 3, "n": 1, "o": 1, "p": 3, "q": 10, "r": 1, "s": 1, "t": 1,
    "u": 1, "v": 4, "w": 4, "x": 8, "y": 4, "z": 10,
}
ASCENSION_LETTER_VALUES = {
    "a": 1, "b": 3, "c": 2, "d": 1, "e": 0, "f": 3, "g": 1, "h": 3, "i": 1, "j": 6,
    "k": 4, "l": 1, "m": 3, "n": 1, "o": 1, "p": 2, "q": 8, "r": 1, "s": 0, "t": 1,
    "u": 1, "v": 3, "w": 4, "x": 6, "y": 3, "z": 8,
}

FRACTIONS: dict[str, tuple[int, int]] = {
    "⅐": (1, 7), "⅑": (1, 9), "⅒": (1, 10), "½": (1, 2), "⅓": (1, 3), "⅔": (2, 3),
    "¼": (1, 4), "¾": (3, 4), "⅕": (1, 5), "⅖": (2, 5), "⅗": (3, 5), "⅘": (4, 5),
    "⅙": (1, 6), "⅚": (5, 6), "⅛": (1, 8), "⅜": (3, 8), "⅝": (5, 8), "⅞": (7, 8),
}
FRACTION_SYMBOL = {v: k for k, v in FRACTIONS.items()}
FRACTIONS_BY_VALUE: dict[int, tuple[str, ...]] = {
    1: ("⅐", "⅑", "⅒", "⅓", "¼", "⅕", "⅙", "⅛", "½"),
    2: ("½", "⅔", "⅖"),
    3: ("⅓", "⅔", "¾", "⅗", "⅜"),
    4: ("¼", "¾", "⅘"),
    5: ("⅕", "⅖", "⅗", "⅘", "⅝"),
    6: ("⅙", "⅚"),
    7: ("⅐", "⅞"),
    8: ("⅛", "⅜", "⅝", "⅞"),
    9: ("⅑",),
    10: ("⅒",),
}

# Currency.CurrencyLetters (insertion order).
CURRENCY_LETTERS = {
    "฿": "b", "₡": "c", "€": "e", "₣": "f", "₲": "g", "₭": "k", "₦": "n", "₱": "p",
    "$": "s", "₮": "t", "₩": "w", "¥": "y",
}
CURRENCY_FROM_LETTER = {v: k for k, v in CURRENCY_LETTERS.items()}


def weighted_pick(rng: Rng, weights: dict[str, int], keys: Iterable[str] | None = None) -> str:
    """``GetRandom*Weighted``: one ``Range(0, total)`` roll walked in dict order."""
    items = [(k, w) for k, w in weights.items() if keys is None or k in keys]
    total = sum(w for _, w in items)
    roll = rng.range(0, total)
    for k, w in items:
        if roll < w:
            return k
        roll -= w
    raise AssertionError("weights exhausted")


def random_letter_weighted(rng: Rng, ascension: bool = False) -> str:
    return weighted_pick(rng, ASCENSION_LETTER_FREQUENCIES if ascension else LETTER_FREQUENCIES)


def random_consonant_weighted(rng: Rng) -> str:
    return weighted_pick(rng, LETTER_FREQUENCIES, CONSONANTS)


def random_vowel_weighted(rng: Rng) -> str:
    return weighted_pick(rng, LETTER_FREQUENCIES, VOWELS)


def random_fraction(rng: Rng) -> tuple[int, int]:
    keys = list(FRACTIONS)
    return FRACTIONS[keys[rng.range(0, len(keys))]]


def random_currency(rng: Rng) -> str:
    keys = list(CURRENCY_LETTERS)
    return keys[rng.range(0, len(keys))]


def random_chess_piece(rng: Rng) -> tuple[str, bool]:
    piece = ALL_CHESS_PIECES[rng.range(0, len(ALL_CHESS_PIECES))]
    return piece, rng.range(0, 2) == 0


def random_card_suit(rng: Rng) -> str:
    return CARD_SUITS[rng.range(0, len(CARD_SUITS))]


# ---------------------------------------------------------------------------- Tile


@dataclass(eq=False)
class Tile:
    """``Tile`` (game coordinates: x right, y up from the bottom row)."""

    glyph: str = G_LETTER
    letter: str = ""
    number: int = -1000
    fraction: tuple[int, int] | None = None
    suit: str = SUIT_NONE
    piece: str = "none"
    white: bool = False
    item: "Item | None" = None  # ScatteredItem
    tile_type: str = NORMAL
    value_modifier: int = 0
    cactus_growth: int = 0
    empty: bool = False
    x: int = -100
    y: int = -100
    was_consumable: bool = False
    destroyed: bool = False  # HasBeenDestroyed
    crossed_out: bool = False
    in_void: bool = False  # IsInTheVoid
    gone: bool = False
    inverted: bool = False
    selling_prevented: bool = False
    number_go_up_middle: bool = False
    safe_from_destruction: bool = False
    was_glitch: bool = False
    already_on_rack: bool = False
    sandy_boss_tile: bool = False
    # Arrow glyph direction lives in ``letter`` like the game.

    # -- copies -----------------------------------------------------------------

    def get_copy(self, is_consumable: bool) -> "Tile":
        """``Tile.GetCopy`` (scattered items re-instantiated at component-0 level)."""
        t = Tile()
        t.letter = self.letter
        t.number = self.number
        t.fraction = self.fraction
        t.tile_type = self.tile_type
        t.x, t.y = self.x, self.y
        if self.piece != "none":
            t.piece, t.white = self.piece, self.white
        if self.item is not None:
            t.item = self.item.fresh_copy()
        t.glyph = self.glyph
        t.suit = self.suit
        t.value_modifier = self.value_modifier
        t.cactus_growth = self.cactus_growth
        t.was_consumable = is_consumable
        t.already_on_rack = self.already_on_rack
        t.sandy_boss_tile = self.sandy_boss_tile
        return t

    def set_as_copy(self, other: "Tile", change_coords: bool) -> None:
        """``Tile.SetAsCopy``."""
        self.letter = other.letter
        self.number = other.number
        self.fraction = other.fraction
        self.piece, self.white = other.piece, other.white
        self.tile_type = other.tile_type
        self.empty = other.empty
        if other.item is not None:
            self.item = other.item.fresh_copy()
        self.glyph = other.glyph
        if change_coords:
            self.x, self.y = other.x, other.y
        self.set_suit(other.suit)
        self.cactus_growth = other.cactus_growth
        self.value_modifier = other.value_modifier
        self.already_on_rack = other.already_on_rack
        self.sandy_boss_tile = other.sandy_boss_tile

    def is_copy(self, other: "Tile") -> bool:
        return (
            self.glyph == other.glyph
            and self.srep() == other.srep()
            and self.tile_type == other.tile_type
            and self.suit == other.suit
        )

    # -- glyph ------------------------------------------------------------------

    def get_glyph(self) -> str:
        """``GetGlyphType``: gone / void / destroyed tiles report Letter."""
        if self.in_void or self.gone or self.destroyed:
            return G_LETTER
        return self.glyph

    def is_number(self) -> bool:
        return self.glyph in (G_NUMBER, G_FRACTION)

    def is_chess(self) -> bool:
        return self.glyph == G_CHESS

    def is_blank(self) -> bool:
        return self.glyph == G_BLANK

    def set_glyph(self, glyph: str) -> None:
        self.glyph = glyph
        self.value_modifier = 0
        if self.suit == SUIT_JOKER:
            self.suit = SUIT_NONE

    def set_letter(self, letter: str) -> None:
        self.set_glyph(G_LETTER)
        self.letter = letter

    def set_number(self, n: int) -> None:
        self.set_glyph(G_NUMBER)
        self.number = int(n)

    def set_fraction(self, nums: tuple[int, int]) -> None:
        self.set_glyph(G_FRACTION)
        self.fraction = (int(nums[0]), int(nums[1]))

    def set_chess(self, piece: str, white: bool) -> None:
        if piece != "none":
            self.set_glyph(G_CHESS)
            self.piece, self.white = piece, white

    def set_currency(self, symbol: str) -> None:
        self.set_glyph(G_CURRENCY)
        self.letter = symbol

    def set_item(self, item: "Item") -> None:
        self.set_glyph(G_ITEM)
        self.item = item

    def set_suit(self, suit: str) -> None:
        if self.get_glyph() != G_CARD or suit == SUIT_JOKER:
            self.suit = suit

    def set_empty(self, empty: bool) -> None:
        if empty:
            self.letter = ""
        self.empty = empty

    def get_number(self) -> int:
        if self.glyph != G_NUMBER:
            raise ValueError("not a number tile")
        return self.number

    def number_float(self) -> float:
        if self.glyph == G_NUMBER:
            return float(self.number)
        a, b = self.fraction or (0, 1)
        return a / b

    def is_suited_card(self) -> bool:
        return self.suit not in (SUIT_NONE, SUIT_JOKER)

    def is_type(self, tt: str) -> bool:
        """``IsTileType``: purple counts as red and blue."""
        if self.tile_type == PURPLE and tt in (RED, BLUE):
            return True
        return self.tile_type == tt

    @property
    def coords(self) -> tuple[int, int]:
        return (self.x, self.y)

    def srep(self, for_word: bool = False) -> str:
        """``GetStringRepresentation`` (display strings simplified to symbols)."""
        g = self.glyph
        if g == G_CARD and self.suit == SUIT_JOKER:
            return "!" if for_word else "🃏"
        if g == G_LETTER:
            return (self.letter or "").lower()
        if g in (G_CURRENCY, G_ARROW):
            return (self.letter or "").lower() if for_word else (self.letter or "")
        if g == G_FRACTION:
            return "!" if for_word else FRACTION_SYMBOL.get(self.fraction or (0, 0), "")
        if g == G_NUMBER:
            return "!" if for_word else str(self.number)
        if g == G_CHESS:
            return "!" if for_word else f"{'w' if self.white else 'b'}{self.piece}"
        if g == G_BLANK:
            return "?"
        if g == G_ITEM:
            return "!" if for_word else f"[{self.item.game_class if self.item else ''}]"
        if g == G_NONE:
            return ""
        return (self.letter or "").lower()

    # -- value ------------------------------------------------------------------

    def get_value(self, player: "Player") -> int:
        """``Tile.GetValue`` (ScorePacket as Python int)."""
        run = player.run
        if run is not None and run.challenge_is("TheBonesRound"):
            return 0
        if self.gone or self.in_void or self.destroyed:
            return 0
        if self.glyph == G_ITEM:
            return 0
        if self.tile_type == SHINY:
            return 50
        for shield in player.unpacked_of("Shield"):
            if shield.relevant_colours and self.is_type(shield.relevant_colours[0]):
                return shield.var(0)
        if self.tile_type == GOLD:
            return player.money
        result = 0
        g = self.glyph
        if g == G_NUMBER:
            result = self.number
        elif g == G_FRACTION:
            result = sum(self.fraction or (0, 0))
        elif g == G_LETTER:
            values = ASCENSION_LETTER_VALUES if (run is not None and run.ascension >= 3) else LETTER_VALUES
            result = values.get(self.srep(), 0)
        elif g == G_CHESS:
            result = CHESS_VALUES.get(self.piece, 0)
        if self.tile_type in (RED, BLUE):
            result += 1
        elif self.tile_type == PURPLE:
            result += 2
        elif self.tile_type == CACTUS:
            result += self.cactus_growth
        result += self.value_modifier
        if self.tile_type == VOID:
            result *= -1
        return result

    def change_value_modifier(self, change: int) -> None:
        self.value_modifier += int(change)

    def multiply_tile_value(self, multiplier: int, player: "Player") -> None:
        v = self.get_value(player)
        if self.tile_type == VOID:
            self.value_modifier -= v * (multiplier - 1)
        else:
            self.value_modifier += v * (multiplier - 1)

    # -- curses -----------------------------------------------------------------

    def is_variable_letter(self, player: "Player", extra_items: Iterable["Item"] = ()) -> bool:
        """``IsDisplayingAsVariableLetter`` (wobbly)."""
        g = self.glyph
        if g in (G_BLANK, G_CHESS, G_ARROW, G_ITEM) or self.suit == SUIT_JOKER:
            return False
        items = player.all_items_unpacked_for_letters(extra_items)
        classes = {i.game_class for i in items}

        def colours(cls: str) -> list[str]:
            out: list[str] = []
            for i in items:
                if i.game_class == cls:
                    out.extend(i.relevant_colours)
            return out

        rep = self.srep()
        if "RedEnvelope" in classes and any(self.is_type(c) for c in colours("RedEnvelope")):
            if (g != G_LETTER or rep != "e") and (g != G_CURRENCY or self.letter != "€"):
                return True
        if "SpicyPepper" in classes and any(self.is_type(c) for c in colours("SpicyPepper")):
            if (g != G_LETTER or rep != "s") and (g != G_CURRENCY or self.letter != "$"):
                return True
        if "Automobile" in classes and any(self.is_type(c) for c in colours("Automobile")) and g == G_LETTER:
            return True
        if "SluggishZombie" in classes and g == G_LETTER and rep == "z":
            return True
        if "Jellyfish" in classes and g == G_LETTER and rep == "j":
            return True
        if "CardShark" in classes:
            s = self.suit
            if s == CLUBS and rep != "c":
                return True
            if s == DIAMONDS and rep != "d":
                return True
            if s == HEARTS and rep != "h":
                return True
            if s == SPADES and rep != "s" and self.letter != "$":
                return True
            return False
        if "Queen" in classes and g == G_LETTER and rep == "q":
            return True
        if "Flamingo" in classes and any(self.is_type(c) for c in colours("Flamingo")):
            if g not in (G_NUMBER, G_FRACTION):
                return True
            if g == G_NUMBER and self.number != 1:
                return True
            if g == G_FRACTION and 1 not in (self.fraction or ()):
                return True
            return False
        if "TestTube" in classes and self.is_number():
            return True
        if "Microscope" in classes and self.get_value(player) > 0:
            v = self.get_value(player)
            if g not in (G_NUMBER, G_FRACTION):
                return True
            if g == G_NUMBER and self.number != v:
                return True
            if g == G_FRACTION and v not in (self.fraction or ()):
                return True
            return False
        if "NumbersBunchOfGrapes" in classes and g == G_NUMBER and self.number in (1, 5, 10):
            return True
        return False

    def is_cursed(self, player: "Player") -> bool:
        if self.glyph != G_LETTER:
            return True
        if self.suit != SUIT_NONE:
            return True
        return self.is_variable_letter(player)

    def curse_types(self, player: "Player") -> list[str]:
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
        if self.is_variable_letter(player):
            out.append(C_WOBBLY)
        return out

    def consumable_replacement_allowed(self, player: "Player") -> bool:
        if self.tile_type == CACTUS:
            return False
        run = player.run
        if run is not None and run.challenge_is("UpAndUp") and self.number_go_up_middle:
            return False
        return True

    # -- random faces -------------------------------------------------------------

    def set_to_random_letter(self, rng: Rng) -> None:
        self.set_letter(LETTERS[rng.range(0, len(LETTERS))])

    def set_to_random_currency(self, rng: Rng) -> None:
        self.set_currency(random_currency(rng))

    def set_to_random_fraction(self, rng: Rng) -> None:
        self.set_fraction(random_fraction(rng))

    def set_to_random_number(self, rng: Rng) -> None:
        self.set_number(rng.range(1, 9))

    def set_to_random_chess(self, rng: Rng) -> None:
        self.set_chess(*random_chess_piece(rng))

    def set_to_random_item(self, rng: Rng, player: "Player") -> None:
        from cursed_words_solver.sim.game.items import random_scattered_item

        self.set_item(random_scattered_item(rng, player))

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"Tile({self.x},{self.y} {self.tile_type} {self.glyph} {self.srep()!r})"


def randomly_curse_tile(tile: Tile, rng: Rng, player: "Player", allow_items: bool) -> None:
    """``Tile.RandomlyCurseTile`` (fully unlocked profile)."""
    suited = False
    if rng.range(0, 10) == 0:
        if rng.range(0, 10) == 0:
            tile.set_glyph(G_CARD)
            tile.set_suit(SUIT_JOKER)
            return
        suited = True
    options = [G_BLANK, G_CURRENCY, G_NUMBER, G_FRACTION, G_CHESS]
    if allow_items:
        options.append(G_ITEM)
    pick = options[rng.range(0, len(options))]
    if pick == G_BLANK:
        tile.set_glyph(G_BLANK)
    elif pick == G_NUMBER:
        tile.set_number(rng.range(1, 9))
    elif pick == G_FRACTION:
        tile.set_fraction(random_fraction(rng))
    elif pick == G_CHESS:
        tile.set_chess(*random_chess_piece(rng))
    elif pick == G_CURRENCY:
        tile.set_letter(random_currency(rng))
        tile.set_glyph(G_CURRENCY)
    elif pick == G_ITEM:
        tile.set_to_random_item(rng, player)
    if suited and tile.suit == SUIT_NONE:
        tile.set_suit(random_card_suit(rng))


# ---------------------------------------------------------------------------- GridData


@dataclass(eq=False)
class GridData:
    tiles: list[Tile] = field(default_factory=list)
    width: int = 5
    height: int = 5
    grid_number: int = 1
    has_lost_challenge: bool = False

    def available(self) -> list[Tile]:
        """``GetAvailableTiles``."""
        return [t for t in self.tiles if not t.in_void and not t.destroyed]

    def at(self, x: int, y: int) -> Tile | None:
        for t in self.tiles:
            if t.x == x and t.y == y:
                return t
        return None

    def available_at(self, x: int, y: int) -> Tile | None:
        t = self.at(x, y)
        if t is not None and not t.in_void and not t.destroyed:
            return t
        return None

    def valid(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    def clone(self) -> "GridData":
        g = GridData(width=self.width, height=self.height, grid_number=self.grid_number,
                     has_lost_challenge=self.has_lost_challenge)
        for t in self.tiles:
            c = Tile(**{k: getattr(t, k) for k in t.__dataclass_fields__})
            if t.item is not None:
                c.item = t.item.clone()
            g.tiles.append(c)
        return g


def is_corner(t: Tile, grid: GridData) -> bool:
    mx, my = grid.width - 1, grid.height - 1
    return t.x in (0, mx) and t.y in (0, my)


def is_edge(t: Tile, grid: GridData) -> bool:
    mx, my = grid.width - 1, grid.height - 1
    return t.x in (0, mx) or t.y in (0, my)


def are_adjacent(a: Tile, b: Tile) -> bool:
    return abs(a.x - b.x) <= 1 and abs(a.y - b.y) <= 1 and (a.x, a.y) != (b.x, b.y)


def adjacent_tiles(grid: GridData, x: int, y: int, player: "Player | None", force_wrap: bool = False) -> list[Tile]:
    """``GetTilesAdjacentToCoordinates`` (Hungry Snake wraps left/right edges)."""
    wrap = force_wrap or (player is not None and bool(player.unpacked_of("HungrySnake")))
    out: list[Tile] = []
    seen: set[int] = set()

    def add(t: Tile | None) -> None:
        if t is not None and id(t) not in seen:
            seen.add(id(t))
            out.append(t)

    for i in (-1, 0, 1):
        for j in (-1, 0, 1):
            if i == 0 and j == 0:
                continue
            nx, ny = x + i, y + j
            if grid.valid(nx, ny):
                t = grid.at(nx, ny)
                if t is not None and not t.in_void and not t.destroyed:
                    add(t)
    if wrap:
        if x == 0:
            for k in (-1, 0, 1):
                if grid.valid(grid.width - 1, y + k):
                    add(grid.at(grid.width - 1, y + k))
        elif x == grid.width - 1:
            for k in (-1, 0, 1):
                if grid.valid(0, y + k):
                    add(grid.at(0, y + k))
    return out


def to_game_state_tile(t: Tile, player: "Player", *, full: bool = True) -> dict[str, Any]:
    """Serialize like melmod ``GameStateSerializer`` (``game_state/1`` tile)."""
    flags: list[str] = []
    if t.was_consumable:
        flags.append("was_consumable")
    if t.was_glitch:
        flags.append("was_glitch")
    if t.crossed_out:
        flags.append("crossed_out")
    if t.in_void:
        flags.append("in_void")
    if t.destroyed:
        flags.append("destroyed")
    if t.gone:
        flags.append("gone")
    letter = t.letter or ""
    out: dict[str, Any] = {
        "x": t.x,
        "y": t.y,
        "glyph": GAME_GLYPH_NAMES.get(t.glyph, "Letter"),
        "type": GAME_TYPE_NAMES.get(t.tile_type, "Normal"),
        "letter": letter,
        "number": t.number,
        "fraction": list(t.fraction) if t.fraction else [],
        "suit": t.suit.capitalize() if t.suit != SUIT_NONE else "None",
        "piece": t.piece.capitalize() if t.piece != "none" else "None",
        "white": bool(t.white),
        "value": t.get_value(player),
        "value_modifier": t.value_modifier,
        "cactus_growth": t.cactus_growth,
        "srep": t.srep(),
        "srep_word": t.srep(True),
        "flags": flags,
        "available": not (t.in_void or t.destroyed),
    }
    if t.item is not None:
        out["item"] = t.item.to_state()
    return out
