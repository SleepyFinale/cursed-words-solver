"""Stamp/sticker effects that alter word search (movement, letter resolution)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from cursed_words_solver.models import Loadout
from cursed_words_solver.rules.ram_memory import pin_memory_entries, ram_entry_bucket
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

FLAG_HORIZONTAL_WRAP = 1 << 0
FLAG_DOUBLE_LETTER_TELEPORT = 1 << 1
FLAG_Q_AS_QU = 1 << 2
FLAG_RED_AS_E = 1 << 3
FLAG_Z_AS_S = 1 << 4
FLAG_SHINY_AS_ONE = 1 << 5
FLAG_NUMBER_PLUS_MINUS_ONE = 1 << 6
FLAG_CARD_SUIT_FIRST_LETTER = 1 << 7
FLAG_RED_AS_S = 1 << 8
FLAG_NUMBER_ASCENDING_FREE_POSITION = 1 << 9
FLAG_WORD_STITCH = 1 << 10
FLAG_NUMBER_ROMAN_IVX = 1 << 11
FLAG_J_AS_H_OR_Y = 1 << 12
FLAG_RED_LETTER_PLUS_MINUS_ONE = 1 << 13
FLAG_CHESS_ALLIES_CAN_TAKE = 1 << 14
FLAG_CHESS_KING_QUEEN_ITEM_MOVEMENT = 1 << 15
FLAG_MICROSCOPE_BASE_SCORE = 1 << 16

SearchFlagsMask = int

_FLAG_KEY_BITS: dict[str, int] = {
    "horizontal_wrap": FLAG_HORIZONTAL_WRAP,
    "double_letter_teleport": FLAG_DOUBLE_LETTER_TELEPORT,
    "q_as_qu": FLAG_Q_AS_QU,
    "red_as_e": FLAG_RED_AS_E,
    "z_as_s": FLAG_Z_AS_S,
    "shiny_as_one": FLAG_SHINY_AS_ONE,
    "number_plus_minus_one": FLAG_NUMBER_PLUS_MINUS_ONE,
    "card_suit_first_letter": FLAG_CARD_SUIT_FIRST_LETTER,
    "red_as_s": FLAG_RED_AS_S,
    "number_ascending_free_position": FLAG_NUMBER_ASCENDING_FREE_POSITION,
    "word_stitch": FLAG_WORD_STITCH,
    "number_roman_ivx": FLAG_NUMBER_ROMAN_IVX,
    "j_as_h_or_y": FLAG_J_AS_H_OR_Y,
    "red_letter_plus_minus_one": FLAG_RED_LETTER_PLUS_MINUS_ONE,
    "chess_allies_can_take": FLAG_CHESS_ALLIES_CAN_TAKE,
    "chess_king_queen_item_movement": FLAG_CHESS_KING_QUEEN_ITEM_MOVEMENT,
    "microscope_base_score": FLAG_MICROSCOPE_BASE_SCORE,
}


def coerce_search_flags(
    flags: SearchFlagsMask | StampSearchFlags | None,
) -> SearchFlagsMask:
    if flags is None:
        return 0
    if isinstance(flags, int):
        return flags
    return mask_from_flags(flags)


def flag_test(mask: SearchFlagsMask, flag: int) -> bool:
    return bool(mask & flag)


def flag_set(mask: SearchFlagsMask, *flags: int) -> SearchFlagsMask:
    for f in flags:
        mask |= f
    return mask


def flag_clear(mask: SearchFlagsMask, *flags: int) -> SearchFlagsMask:
    for f in flags:
        mask &= ~f
    return mask


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


def mask_from_flags(flags: StampSearchFlags) -> SearchFlagsMask:
    mask = 0
    if flags.horizontal_wrap:
        mask |= FLAG_HORIZONTAL_WRAP
    if flags.double_letter_teleport:
        mask |= FLAG_DOUBLE_LETTER_TELEPORT
    if flags.q_as_qu:
        mask |= FLAG_Q_AS_QU
    if flags.red_as_e:
        mask |= FLAG_RED_AS_E
    if flags.z_as_s:
        mask |= FLAG_Z_AS_S
    if flags.shiny_as_one:
        mask |= FLAG_SHINY_AS_ONE
    if flags.number_plus_minus_one:
        mask |= FLAG_NUMBER_PLUS_MINUS_ONE
    if flags.card_suit_first_letter:
        mask |= FLAG_CARD_SUIT_FIRST_LETTER
    if flags.red_as_s:
        mask |= FLAG_RED_AS_S
    if flags.number_ascending_free_position:
        mask |= FLAG_NUMBER_ASCENDING_FREE_POSITION
    if flags.word_stitch:
        mask |= FLAG_WORD_STITCH
    if flags.number_roman_ivx:
        mask |= FLAG_NUMBER_ROMAN_IVX
    if flags.j_as_h_or_y:
        mask |= FLAG_J_AS_H_OR_Y
    if flags.red_letter_plus_minus_one:
        mask |= FLAG_RED_LETTER_PLUS_MINUS_ONE
    if flags.chess_allies_can_take:
        mask |= FLAG_CHESS_ALLIES_CAN_TAKE
    if flags.chess_king_queen_item_movement:
        mask |= FLAG_CHESS_KING_QUEEN_ITEM_MOVEMENT
    if flags.microscope_base_score:
        mask |= FLAG_MICROSCOPE_BASE_SCORE
    return mask


def flags_from_mask(mask: SearchFlagsMask) -> StampSearchFlags:
    return StampSearchFlags(
        horizontal_wrap=flag_test(mask, FLAG_HORIZONTAL_WRAP),
        double_letter_teleport=flag_test(mask, FLAG_DOUBLE_LETTER_TELEPORT),
        q_as_qu=flag_test(mask, FLAG_Q_AS_QU),
        red_as_e=flag_test(mask, FLAG_RED_AS_E),
        z_as_s=flag_test(mask, FLAG_Z_AS_S),
        shiny_as_one=flag_test(mask, FLAG_SHINY_AS_ONE),
        number_plus_minus_one=flag_test(mask, FLAG_NUMBER_PLUS_MINUS_ONE),
        card_suit_first_letter=flag_test(mask, FLAG_CARD_SUIT_FIRST_LETTER),
        red_as_s=flag_test(mask, FLAG_RED_AS_S),
        number_ascending_free_position=flag_test(mask, FLAG_NUMBER_ASCENDING_FREE_POSITION),
        word_stitch=flag_test(mask, FLAG_WORD_STITCH),
        number_roman_ivx=flag_test(mask, FLAG_NUMBER_ROMAN_IVX),
        j_as_h_or_y=flag_test(mask, FLAG_J_AS_H_OR_Y),
        red_letter_plus_minus_one=flag_test(mask, FLAG_RED_LETTER_PLUS_MINUS_ONE),
        chess_allies_can_take=flag_test(mask, FLAG_CHESS_ALLIES_CAN_TAKE),
        chess_king_queen_item_movement=flag_test(mask, FLAG_CHESS_KING_QUEEN_ITEM_MOVEMENT),
        microscope_base_score=flag_test(mask, FLAG_MICROSCOPE_BASE_SCORE),
    )


def _catalog() -> dict:
    if not _CATALOG_PATH.is_file():
        return {}
    return json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))


def stamp_slugs(loadout: Loadout | None) -> frozenset[str]:
    if not loadout:
        return frozenset()
    slugs = {slugify_name(s.id or s.name) for s in loadout.stamps}
    for entry in pin_memory_entries(loadout):
        if ram_entry_bucket(entry) == "stamps":
            slugs.add(slugify_name(str(entry.get("id") or entry.get("name") or "")))
    return frozenset(slugs)


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


def _merged_flag_keys(loadout: Loadout | None) -> dict[str, bool]:
    merged: dict[str, bool] = {}
    if not loadout:
        return merged
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
    for entry in pin_memory_entries(loadout):
        slug = slugify_name(str(entry.get("id") or entry.get("name") or ""))
        bucket = ram_entry_bucket(entry)
        item_id = str(entry.get("id", "") or "")
        item_name = str(entry.get("name", "") or "")
        _key, rule = get_rule(rules, bucket, item_id, item_name)
        for k, v in _flags_from_rule(slug, rule).items():
            if v:
                merged[k] = True
    if loadout_has_stamp(loadout, "microscope"):
        merged["microscope_base_score"] = True
    return merged


def stamp_search_flags_mask(loadout: Loadout | None) -> SearchFlagsMask:
    mask = 0
    for key, bit in _FLAG_KEY_BITS.items():
        if _merged_flag_keys(loadout).get(key):
            mask |= bit
    return mask


def stamp_search_flags(loadout: Loadout | None) -> StampSearchFlags:
    return flags_from_mask(stamp_search_flags_mask(loadout))


def search_flags_mask_for_item_slug(
    slug: str,
    rules: dict | None = None,
) -> SearchFlagsMask:
    """Search flags from a single stamp/sticker slug (equipped or scattered)."""
    slug = slugify_name(slug)
    if not slug:
        return 0
    rules = rules if rules is not None else _catalog()
    merged: dict[str, bool] = {}
    for bucket in ("stamps", "stickers"):
        _key, rule = get_rule(rules, bucket, slug, slug)
        if rule:
            for k, v in _flags_from_rule(slug, rule).items():
                if v:
                    merged[k] = True
    if not merged:
        for k, v in _LEGACY_STAMP_FLAGS.get(slug, {}).items():
            if v:
                merged[k] = True
    mask = 0
    for key, bit in _FLAG_KEY_BITS.items():
        if merged.get(key):
            mask |= bit
    return mask


def path_scattered_search_flags_mask(
    board,
    path: list[int],
    base_flags: SearchFlagsMask,
    rules: dict | None = None,
) -> SearchFlagsMask:
    """Equipped flags OR flags from scattered stamps/stickers picked up on ``path``."""
    from cursed_words_solver.models import CurseType

    mask = coerce_search_flags(base_flags)
    rules = rules if rules is not None else _catalog()
    seen: set[str] = set()
    for idx in path:
        tile = board.get_by_index(idx)
        if tile.curse != CurseType.ITEM:
            continue
        slug = slugify_name(str(tile.metadata.get("scattered_item_id") or ""))
        if not slug or slug in seen:
            continue
        seen.add(slug)
        mask |= search_flags_mask_for_item_slug(slug, rules)
    return mask
