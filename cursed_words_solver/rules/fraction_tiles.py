"""Fraction tile parsing and position rules (wiki: Tiles — Fractions)."""

from __future__ import annotations

import re
from fractions import Fraction

from cursed_words_solver.models import CurseType, Tile, normalize_tile_glyph

_VULGAR_FRACTIONS: dict[str, tuple[int, int]] = {
    "½": (1, 2),
    "⅓": (1, 3),
    "⅔": (2, 3),
    "¼": (1, 4),
    "¾": (3, 4),
    "⅕": (1, 5),
    "⅖": (2, 5),
    "⅗": (3, 5),
    "⅘": (4, 5),
    "⅙": (1, 6),
    "⅚": (5, 6),
    "⅛": (1, 8),
    "⅜": (3, 8),
    "⅝": (5, 8),
    "⅞": (7, 8),
    "⅐": (1, 7),
    "⅑": (1, 9),
    "⅒": (1, 10),
}

_MAX_FRACTION_DENOMINATOR = 20
_VULGAR_BY_PARTS: dict[tuple[int, int], str] = {
    parts: glyph for glyph, parts in _VULGAR_FRACTIONS.items()
}


def format_fraction_parts(num: int, den: int) -> str:
    """Vulgar glyph when known (game set of 18), else slash notation."""
    if den <= 0:
        return "?"
    glyph = _VULGAR_BY_PARTS.get((num, den))
    if glyph:
        return glyph
    return f"{num}/{den}"


def format_fraction_value(value: float) -> str:
    """Display a melmod fraction_value (e.g. 0.8 → ⅘)."""
    parts = parse_fraction_parts_from_float(value)
    if parts is None:
        return str(value)
    return format_fraction_parts(*parts)


def format_fraction_text(text: str) -> str | None:
    """Normalize decimal/slash/vulgar fraction text to display form."""
    parts = parse_fraction_parts_from_text(text)
    if parts is None:
        return None
    return format_fraction_parts(*parts)


def format_fraction_tile(tile: Tile) -> str:
    """User-facing label for a fraction curse tile."""
    ch = normalize_tile_glyph(tile.char or "")
    if ch and ch != "?" and ch in _VULGAR_FRACTIONS:
        return ch
    if ch and ch != "?":
        formatted = format_fraction_text(ch)
        if formatted:
            return formatted
    parts = fraction_parts(tile)
    if parts is not None:
        return format_fraction_parts(*parts)
    if tile.fraction_value is not None:
        return format_fraction_value(tile.fraction_value)
    return "?"


def parse_fraction_parts_from_float(value: float) -> tuple[int, int] | None:
    """Derive numerator/denominator from melmod fraction_value (e.g. 0.1 → 1/10)."""
    try:
        fr = Fraction(value).limit_denominator(_MAX_FRACTION_DENOMINATOR)
    except (TypeError, ValueError, OverflowError):
        return None
    if fr.denominator <= 0 or fr.numerator < 0:
        return None
    if abs(float(fr) - float(value)) > 1e-4:
        return None
    return fr.numerator, fr.denominator


def parse_fraction_parts_from_text(text: str) -> tuple[int, int] | None:
    """Parse numerator/denominator from display text (3/5, ⅗, etc.)."""
    cleaned = normalize_tile_glyph((text or "").strip())
    if not cleaned:
        return None
    if cleaned in _VULGAR_FRACTIONS:
        return _VULGAR_FRACTIONS[cleaned]
    match = re.search(r"(\d+)\s*/\s*(\d+)", cleaned)
    if match:
        num, den = int(match.group(1)), int(match.group(2))
        if den > 0:
            return num, den
    # Decimal fractions from melmod (e.g. 0.6) — not bare integers (those are NUMBER tiles).
    if re.search(r"\.\d", cleaned) or (
        cleaned.startswith("0") and len(cleaned) > 1 and cleaned[1].isdigit()
    ):
        try:
            value = float(cleaned)
        except ValueError:
            return None
        return parse_fraction_parts_from_float(value)
    return None


def attach_fraction_metadata(tile: Tile) -> None:
    """Store fraction_num/fraction_den on tile.metadata when parseable."""
    parts = fraction_parts(tile)
    if parts is not None:
        tile.metadata["fraction_num"] = parts[0]
        tile.metadata["fraction_den"] = parts[1]


def fraction_parts(tile: Tile) -> tuple[int, int] | None:
    meta = tile.metadata
    if "fraction_num" in meta and "fraction_den" in meta:
        try:
            return int(meta["fraction_num"]), int(meta["fraction_den"])
        except (TypeError, ValueError):
            pass
    parts = parse_fraction_parts_from_text(tile.char)
    if parts is not None:
        return parts
    parts = parse_fraction_parts_from_text(tile.letter)
    if parts is not None:
        return parts
    if tile.fraction_value is not None:
        return parse_fraction_parts_from_float(tile.fraction_value)
    return None


def is_fraction_tile(tile: Tile) -> bool:
    return tile.curse == CurseType.FRACTION


def tile_fraction_position_values(tile: Tile) -> list[int]:
    """1-based position indices this fraction may claim (numerator and denominator)."""
    if not is_fraction_tile(tile):
        return []
    parts = fraction_parts(tile)
    if parts is None:
        return []
    num, den = parts
    if num == den:
        return [num]
    return sorted({num, den})


def _position_matches_fraction_values(position: int, values: list[int]) -> bool:
    if not values:
        return False
    pos = position + 1
    return pos in values


def _position_matches_fraction_values_with_flags(
    position: int,
    values: list[int],
    *,
    number_plus_minus_one: bool = False,
) -> bool:
    """Match game Tile.IsNumericWildcard for fractions (optional Test Tube ±1)."""
    if not values:
        return False
    pos = position + 1
    if number_plus_minus_one:
        return any(pos in (v - 1, v, v + 1) and v >= 1 for v in values)
    return pos in values


def fraction_position_valid(tile: Tile, position: int, relaxed: bool = False) -> bool:
    """Fraction wildcards are valid at numerator or denominator position only (1-based)."""
    if relaxed or not is_fraction_tile(tile):
        return True
    values = tile_fraction_position_values(tile)
    if not values:
        return False
    return _position_matches_fraction_values(position, values)


def fraction_is_numeric_wildcard(
    tile: Tile,
    path_index: int,
    *,
    number_plus_minus_one: bool = False,
) -> bool:
    """True when a fraction is a letter wildcard at path_index (game IsNumericWildcard)."""
    if not is_fraction_tile(tile):
        return False
    values = tile_fraction_position_values(tile)
    return _position_matches_fraction_values_with_flags(
        path_index,
        values,
        number_plus_minus_one=number_plus_minus_one,
    )
