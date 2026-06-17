"""Improve-word registry for meta stamps (Flashy Fountain Pen, Bar Chart, Book of Openings)."""

from __future__ import annotations

from cursed_words_solver.models import Loadout

FLASHY_FOUNTAIN_PEN = "flashy_fountain_pen"
BAR_CHART = "bar_chart"
BOOK_OF_OPENINGS = "book_of_openings"

_COLOUR_NAMES = frozenset(
    {
        "red",
        "blue",
        "void",
        "shiny",
        "purple",
        "gold",
        "white",
        "green",
        "pink",
        "glitch",
        "cactus",
    }
)

_UNITS = (
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
)
_TEENS = (
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
)
_COMPOUND_TWENTY = (
    "twentyone",
    "twentytwo",
    "twentythree",
    "twentyfour",
    "twentyfive",
)
_NUMBER_NAMES = frozenset(_UNITS + _TEENS + ("twenty",) + _COMPOUND_TWENTY)

_CHESS_NAMES = frozenset(
    {
        "pawn",
        "knight",
        "bishop",
        "rook",
        "queen",
        "king",
    }
)

STAMP_IMPROVE_WORDS: dict[str, frozenset[str]] = {
    FLASHY_FOUNTAIN_PEN: _COLOUR_NAMES,
    BAR_CHART: _NUMBER_NAMES,
    BOOK_OF_OPENINGS: _CHESS_NAMES,
}

STAMP_IMPROVE_LABELS: dict[str, str] = {
    FLASHY_FOUNTAIN_PEN: "Flashy",
    BAR_CHART: "Bar",
    BOOK_OF_OPENINGS: "Book",
}

_COLOUR_NPV_WEIGHT: dict[str, float] = {
    "shiny": 90.0,
    "void": 40.0,
    "red": 20.0,
    "blue": 18.0,
    "purple": 20.0,
    "gold": 22.0,
    "green": 18.0,
    "pink": 18.0,
    "white": 15.0,
    "glitch": 20.0,
    "cactus": 18.0,
}

_CHESS_NPV_WEIGHT: dict[str, float] = {
    "king": 15.0,
    "queen": 72.0,
    "rook": 40.0,
    "bishop": 24.0,
    "knight": 24.0,
    "pawn": 8.0,
}

_NUMBER_NAME_TO_FACE: dict[str, int] = {}
for i, name in enumerate(_UNITS + _TEENS + ("twenty",), start=1):
    _NUMBER_NAME_TO_FACE[name] = i
for i, name in enumerate(_COMPOUND_TWENTY, start=21):
    _NUMBER_NAME_TO_FACE[name] = i


def equipped_improve_stamps(loadout: Loadout) -> frozenset[str]:
    slugs: set[str] = set()
    for item in loadout.stamps or []:
        sid = (item.id or "").lower()
        if sid in STAMP_IMPROVE_WORDS:
            slugs.add(sid)
    return frozenset(slugs)


def equipped_improve_words(loadout: Loadout) -> frozenset[str]:
    words: set[str] = set()
    for slug in equipped_improve_stamps(loadout):
        words.update(STAMP_IMPROVE_WORDS[slug])
    return frozenset(words)


def stamp_improve_match(loadout: Loadout, word: str) -> list[tuple[str, str]]:
    w = word.lower()
    out: list[tuple[str, str]] = []
    for slug in equipped_improve_stamps(loadout):
        if w in STAMP_IMPROVE_WORDS[slug]:
            out.append((slug, w))
    return out


def stamp_improve_npv_weight(slug: str, token: str) -> float:
    token = token.lower()
    if slug == FLASHY_FOUNTAIN_PEN:
        return _COLOUR_NPV_WEIGHT.get(token, 18.0)
    if slug == BAR_CHART:
        face = _NUMBER_NAME_TO_FACE.get(token, 1)
        return float(face) * 8.0
    if slug == BOOK_OF_OPENINGS:
        return _CHESS_NPV_WEIGHT.get(token, 8.0)
    return 0.0
