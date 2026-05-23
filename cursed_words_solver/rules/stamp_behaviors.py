"""Stamp effects that alter word search (movement, letter resolution)."""

from __future__ import annotations

from dataclasses import dataclass

from cursed_words_solver.models import Loadout
from cursed_words_solver.rules.rule_lookup import slugify_name


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


def stamp_slugs(loadout: Loadout | None) -> frozenset[str]:
    if not loadout:
        return frozenset()
    return frozenset(
        slugify_name(s.id or s.name) for s in loadout.stamps
    )


def loadout_has_stamp(loadout: Loadout | None, slug: str) -> bool:
    return slug in stamp_slugs(loadout)


def stamp_search_flags(loadout: Loadout | None) -> StampSearchFlags:
    slugs = stamp_slugs(loadout)
    return StampSearchFlags(
        horizontal_wrap="hungry_snake" in slugs,
        double_letter_teleport="full_moon" in slugs,
        q_as_qu="queenie" in slugs,
        red_as_e="red_envelope" in slugs,
        z_as_s="sluggish_zombie" in slugs,
        shiny_as_one="flamingo" in slugs,
        number_plus_minus_one="test_tube" in slugs,
        card_suit_first_letter="card_shark" in slugs,
        red_as_s="spicy_pepper" in slugs,
        number_ascending_free_position="number_go_up" in slugs,
        word_stitch="honeypot" in slugs,
        number_roman_ivx="bunch_of_grapes" in slugs,
        j_as_h_or_y="jellyfish" in slugs,
        red_letter_plus_minus_one="suspension_bridge" in slugs,
        chess_allies_can_take="king_of_the_bridge" in slugs,
        chess_king_queen_item_movement="television" in slugs,
    )
