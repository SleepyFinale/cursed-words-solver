"""Stamp/sticker effects that alter word search (movement, letter resolution)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from cursed_words_solver.models import Loadout
from cursed_words_solver.rules.rule_lookup import get_rule, slugify_name

_CATALOG_PATH = Path(__file__).resolve().parents[2] / "data" / "wiki" / "stickers.json"

# Legacy slug → search_flags key (used when catalog entry lacks search_flags)
_LEGACY_STAMP_FLAGS: dict[str, dict[str, bool]] = {
    "hungry_snake": {"horizontal_wrap": True},
    "full_moon": {"double_letter_teleport": True},
    "queenie": {"q_as_qu": True},
    "red_envelope": {"red_as_e": True},
    "sluggish_zombie": {"z_as_s": True},
    "flamingo": {"shiny_as_one": True},
    "test_tube": {"number_plus_minus_one": True},
    "card_shark": {"card_suit_first_letter": True},
    "spicy_pepper": {"red_as_s": True},
    "number_go_up": {"number_ascending_free_position": True},
    "honeypot": {"word_stitch": True},
    "bunch_of_grapes": {"number_roman_ivx": True},
    "jellyfish": {"j_as_h_or_y": True},
    "suspension_bridge": {"red_letter_plus_minus_one": True},
    "king_of_the_bridge": {"chess_allies_can_take": True},
    "television": {"chess_king_queen_item_movement": True},
}


@dataclass(frozen=True)
class StampSearchFlags:
    horizontal_wrap: bool = False
    double_letter_teleport: bool = False
    q_as_qu: bool = False
    red_as_e: bool = False
    z_as_s: bool = False
    shiny_as_one: bool = False
    number_plus_minus_one: bool = False
    card_suit_first_letter: bool = False
    red_as_s: bool = False
    number_ascending_free_position: bool = False
    word_stitch: bool = False
    number_roman_ivx: bool = False
    j_as_h_or_y: bool = False
    red_letter_plus_minus_one: bool = False
    chess_allies_can_take: bool = False
    chess_king_queen_item_movement: bool = False
    microscope_base_score: bool = False


@lru_cache(maxsize=1)
def _catalog() -> dict:
    if not _CATALOG_PATH.is_file():
        return {}
    return json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))


def stamp_slugs(loadout: Loadout | None) -> frozenset[str]:
    if not loadout:
        return frozenset()
    return frozenset(slugify_name(s.id or s.name) for s in loadout.stamps)


def loadout_has_stamp(loadout: Loadout | None, slug: str) -> bool:
    return slug in stamp_slugs(loadout)


def _flags_from_rule(slug: str, rule: dict | None) -> dict[str, bool]:
    if not rule:
        return _LEGACY_STAMP_FLAGS.get(slug, {})
    sf = rule.get("search_flags")
    if isinstance(sf, dict):
        return {k: bool(v) for k, v in sf.items()}
    if rule.get("effect_class") == "movement":
        return _LEGACY_STAMP_FLAGS.get(slug, {})
    return _LEGACY_STAMP_FLAGS.get(slug, {})


def stamp_search_flags(loadout: Loadout | None) -> StampSearchFlags:
    merged: dict[str, bool] = {}
    if not loadout:
        return StampSearchFlags()
    rules = _catalog()
    for stamp in loadout.stamps:
        slug = slugify_name(stamp.id or stamp.name)
        _key, rule = get_rule(rules, "stamps", stamp.id, stamp.name)
        for k, v in _flags_from_rule(slug, rule).items():
            if v:
                merged[k] = True
    for sticker in loadout.stickers:
        slug = slugify_name(sticker.id or sticker.name)
        _key, rule = get_rule(rules, "stickers", sticker.id, sticker.name)
        for k, v in _flags_from_rule(slug, rule).items():
            if v:
                merged[k] = True
    return StampSearchFlags(
        horizontal_wrap=merged.get("horizontal_wrap", False),
        double_letter_teleport=merged.get("double_letter_teleport", False),
        q_as_qu=merged.get("q_as_qu", False),
        red_as_e=merged.get("red_as_e", False),
        z_as_s=merged.get("z_as_s", False),
        shiny_as_one=merged.get("shiny_as_one", False),
        number_plus_minus_one=merged.get("number_plus_minus_one", False),
        card_suit_first_letter=merged.get("card_suit_first_letter", False),
        red_as_s=merged.get("red_as_s", False),
        number_ascending_free_position=merged.get("number_ascending_free_position", False),
        word_stitch=merged.get("word_stitch", False),
        number_roman_ivx=merged.get("number_roman_ivx", False),
        j_as_h_or_y=merged.get("j_as_h_or_y", False),
        red_letter_plus_minus_one=merged.get("red_letter_plus_minus_one", False),
        chess_allies_can_take=merged.get("chess_allies_can_take", False),
        chess_king_queen_item_movement=merged.get("chess_king_queen_item_movement", False),
        microscope_base_score=loadout_has_stamp(loadout, "microscope"),
    )
