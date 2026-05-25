#!/usr/bin/env python3
"""Build data/wiki/stickers.json from wiki API dumps and hand-tuned rules."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.catalog.achievement_stamps_catalog import ACHIEVEMENT_STAMPS

WIKI_DIR = ROOT / "data" / "wiki"
OUT_PATH = WIKI_DIR / "stickers.json"
STAMP_SUBCLASSES_PATH = ROOT / "data" / "game" / "stamp_subclasses.json"

# Movement / letter search flags (migrated from stamp_behaviors._LEGACY_STAMP_FLAGS).
STAMP_SEARCH_FLAGS: dict[str, dict[str, bool]] = {
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

LETTER_BEHAVIOR_FLAGS: dict[str, dict[str, bool]] = {
    "q_as_qu": {"q_as_qu": True},
    "red_as_e": {"red_as_e": True},
    "z_as_s": {"z_as_s": True},
    "shiny_as_one": {"shiny_as_one": True},
    "number_plus_minus_one": {"number_plus_minus_one": True},
    "card_suit_first_letter": {"card_suit_first_letter": True},
    "red_as_s": {"red_as_s": True},
    "number_ascending_free_position": {"number_ascending_free_position": True},
    "word_stitch": {"word_stitch": True},
    "number_roman_ivx": {"number_roman_ivx": True},
    "j_as_h_or_y": {"j_as_h_or_y": True},
    "red_letter_plus_minus_one": {"red_letter_plus_minus_one": True},
    "chess_allies_can_take": {"chess_allies_can_take": True},
    "chess_king_queen_item_movement": {"chess_king_queen_item_movement": True},
}


def _slug_to_pascal(slug: str) -> str:
    parts = re.sub(r"[^a-z0-9]+", "_", slug.lower()).strip("_").split("_")
    return "".join(p.capitalize() for p in parts if p)


def enrich_stamps_catalog(stamps: dict[str, dict]) -> None:
    game_classes: dict[str, str] = {}
    if STAMP_SUBCLASSES_PATH.is_file():
        data = json.loads(STAMP_SUBCLASSES_PATH.read_text(encoding="utf-8"))
        for row in data.get("stamps", []):
            if row.get("in_subclasses"):
                game_classes[row["slug"]] = row["game_class"]
    for slug, rule in stamps.items():
        if slug in game_classes and not rule.get("game_class"):
            rule["game_class"] = game_classes[slug]
        elif not rule.get("game_class"):
            rule.setdefault("game_class", _slug_to_pascal(slug))
        flags = dict(STAMP_SEARCH_FLAGS.get(slug, {}))
        for key in ("letter_behavior", "letter_substitute"):
            lb = rule.get(key)
            if isinstance(lb, str) and lb in LETTER_BEHAVIOR_FLAGS:
                flags.update(LETTER_BEHAVIOR_FLAGS[lb])
        if flags:
            existing = rule.get("search_flags")
            if isinstance(existing, dict):
                flags = {**existing, **flags}
            rule["search_flags"] = flags


def enrich_stickers_orchestration(stickers: dict[str, dict]) -> None:
    if "frankenstein" in stickers:
        stickers["frankenstein"].update(
            {
                "type": "frankenstein_stitch",
                "effect_class": "orchestration",
                "game_class": "Frankenstein",
            }
        )
    if "overhand" in stickers:
        stickers["overhand"].update(
            {
                "type": "overhand_replay",
                "effect_class": "orchestration",
                "game_class": "Overhand",
            }
        )

def _grid_scatter(
    name: str,
    wiki_effect: str,
    wiki_page: str,
    *,
    grid_timing: str = "start",
) -> dict:
    timing = grid_timing if grid_timing in ("encounter", "start_encounter") else "start"
    entry = {
        "name": name,
        "type": "scatter_start_encounter" if timing == "encounter" else "scatter_start_grid",
        "effect_class": "scatter",
        "grid_effect": wiki_effect,
        "wiki_effect": wiki_effect,
        "wiki_page": wiki_page,
        "game_class": name.replace(" ", "").replace("'", ""),
    }
    if grid_timing != "start":
        entry["grid_timing"] = grid_timing
    return entry


def _custom_effect(
    name: str,
    wiki_effect: str,
    effect_class: str,
    wiki_page: str = "",
) -> dict:
    entry = {
        "name": name,
        "type": "custom",
        "effect_class": effect_class,
        "wiki_effect": wiki_effect,
    }
    if wiki_page:
        entry["wiki_page"] = wiki_page
    return entry


# Hand-tuned rules (override generated placeholders)
TUNED_STICKERS: dict[str, dict] = {
    # --- Unlocked by default (32) ---
    "april_shower": _grid_scatter(
        "April Shower",
        "START OF ENCOUNTER: chosen letters become BLUE on each grid",
        "April_Shower",
    ),
    "artist_s_palette": {
        "name": "Artist's Palette",
        "type": "add_tile_score",
        "target": "colored",
        "base": 6,
        "upgrade": 6,
        "wiki_effect": "Coloured tiles get +6 TILE SCORE",
        "wiki_page": "Artist's_Palette",
    },
    "blueberries": {
        "name": "Blueberries",
        "type": "multiply_word_scaled",
        "condition": "ends_with_color:blue",
        "base": 2,
        "upgrade": 1,
        "wiki_effect": "If your word ends with a BLUE tile, get ×WORD SCORE",
        "wiki_page": "Blueberries",
    },
    "chequered_flag": {
        "name": "Chequered Flag",
        "type": "multiply_word_scaled",
        "condition": "first_grid_of_encounter",
        "base": 2,
        "upgrade": 1,
        "wiki_effect": "First grid of each encounter gets ×WORD SCORE",
        "wiki_page": "Chequered_Flag",
    },
    "cherries": _grid_scatter(
        "Cherries",
        "Each RED tile used scatters RED tiles onto the next grid",
        "Cherries",
    ),
    "cherry_pie": {
        "name": "Cherry Pie",
        "type": "multiply_word_scaled",
        "condition": "red_count_gte:3",
        "base": 2,
        "upgrade": 1,
        "wiki_effect": "If your word contains 3 or more RED tiles, get ×WORD SCORE",
        "wiki_page": "Cherry_Pie",
    },
    "chips": {
        "name": "Chips",
        "type": "multiply_word_scaled",
        "condition": "word_starts_after_previous",
        "base": 1.5,
        "upgrade": 0.5,
        "wiki_effect": "Word starts later in alphabet than previous word, ×WORD SCORE",
        "wiki_page": "Chips",
    },
    "credit_card": {
        "name": "Credit Card",
        "type": "add_word_score",
        "word_mode": "per_money",
        "base": 2,
        "upgrade": 2,
        "wiki_effect": "Get +0 WORD SCORE (2 for each $ you have)",
        "wiki_page": "Credit_Card",
    },
    "dusty_coffin": {
        "name": "Dusty Coffin",
        "type": "add_word_score",
        "word_mode": "per_void_unused",
        "base": 8,
        "upgrade": 8,
        "wiki_effect": "For each VOID tile on grid whose letter is not in your word, +WORD SCORE",
        "wiki_page": "Dusty_Coffin",
    },
    "egg": {
        "name": "Egg",
        "type": "multiply_word_scaled",
        "condition": "word_starts_vowel",
        "base": 1.5,
        "upgrade": 0.5,
        "wiki_effect": "If your word starts with a vowel, get ×WORD SCORE",
        "wiki_page": "Egg",
    },
    "electric_guitar": {
        "name": "Electric Guitar",
        "type": "add_tile_score",
        "target": "red_note",
        "base": 15,
        "upgrade": 15,
        "wiki_effect": "RED notes (A-G) get +15 TILE SCORE",
        "wiki_page": "Electric_Guitar",
    },
    "fire_extinguisher": {
        "name": "Fire Extinguisher",
        "type": "add_word_score",
        "word_mode": "per_unused_red",
        "base": 5,
        "upgrade": 5,
        "wiki_effect": "For each unused RED tile on the grid, get +WORD SCORE",
        "wiki_page": "Fire_Extinguisher",
    },
    "fountain": _grid_scatter(
        "Fountain",
        "START OF GRID: Scatters BLUE tiles",
        "Fountain",
    ),
    "glass_of_milk": {
        "name": "Glass Of Milk",
        "type": "add_tile_score",
        "target": "wildcard",
        "base": 15,
        "upgrade": 15,
        "wiki_effect": "? tiles get +15 TILE SCORE",
        "wiki_page": "Glass_Of_Milk",
    },
    "graduation_cap": {
        "name": "Graduation Cap",
        "type": "add_word_score",
        "word_mode": "per_path_tile",
        "base": 3,
        "upgrade": 3,
        "wiki_effect": "Get +3 WORD SCORE for each tile in your word",
        "wiki_page": "Graduation_Cap",
    },
    "ham_sandwich": {
        "name": "Ham Sandwich",
        "type": "add_word_score",
        "word_mode": "if_same_start_end",
        "base": 25,
        "upgrade": 25,
        "wiki_effect": "If your word starts and ends with the same letter, +WORD SCORE",
        "wiki_page": "Ham_Sandwich",
    },
    "hi_vis_jacket": {
        "name": "Hi Vis Jacket",
        "type": "multiply_consumable_rack",
        "base": 0.2,
        "upgrade": 0.2,
        "wiki_effect": "×WORD SCORE (0.2 larger per consumable on rack); loses consumable on submit",
        "wiki_page": "Hi_Vis_Jacket",
    },
    "lipstick": _grid_scatter(
        "Lipstick",
        "START OF ENCOUNTER: Scatters RED tiles",
        "Lipstick",
    ),
    "lucky_scarf": {
        "name": "Lucky Scarf",
        "type": "multiply_word_scaled",
        "condition": "word_starts_ends_red",
        "base": 2,
        "upgrade": 1,
        "wiki_effect": "If your word starts and ends with a RED tile, get ×WORD SCORE",
        "wiki_page": "Lucky_Scarf",
    },
    "magic_wand": _grid_scatter(
        "Magic Wand",
        "START OF GRID: chance for RED or BLUE tile to become SHINY",
        "Magic_Wand",
    ),
    "maple_leaf": {
        "name": "Maple Leaf",
        "type": "tile_multiply",
        "target": "first_n_red",
        "factor": 3,
        "base": 2,
        "upgrade": 1,
        "wiki_effect": "Your first N RED tiles get ×3 TILE SCORE",
        "wiki_page": "Maple_Leaf",
    },
    "ornate_key": {
        "name": "Ornate Key",
        "type": "multiply_word_scaled",
        "condition": "no_colorless_on_path",
        "base": 1.5,
        "upgrade": 0.5,
        "wiki_effect": "If your word does not contain COLOURLESS tiles, ×WORD SCORE",
        "wiki_page": "Ornate_Key",
    },
    "pair_of_socks": {
        "name": "Pair Of Socks",
        "type": "multiply_word_scaled",
        "condition": "blue_count_eq:2",
        "base": 2,
        "upgrade": 0.5,
        "wiki_effect": "If your word contains exactly 2 BLUE tiles, get ×WORD SCORE",
        "wiki_page": "Pair_Of_Socks",
    },
    "pneumonia": {
        "name": "Pneumonia",
        "type": "add_word_score",
        "word_mode": "per_unique_vowel",
        "base": 10,
        "upgrade": 10,
        "wiki_effect": "Get +10 WORD SCORE for each unique vowel in your word",
        "wiki_page": "Pneumonia",
    },
    "sequoia_sapling": {
        "name": "Sequoia Sapling",
        "type": "add_tile_score",
        "target": "vowel",
        "base": 6,
        "upgrade": 6,
        "wiki_effect": "Vowels get +6 TILE SCORE",
        "wiki_page": "Sequoia_Sapling",
    },
    "sly_spy": {
        "name": "Sly Spy",
        "type": "tile_multiply",
        "target": "consonant",
        "per_level_factor": True,
        "factor_base": 1.0,
        "factor_per_level": 1.0,
        "wiki_effect": "Consonants get ×2 TILE SCORE",
        "wiki_page": "Sly_Spy",
    },
    "stilton": {
        "name": "Stilton",
        "type": "add_tile_score",
        "target": "blue",
        "base": 8,
        "upgrade": 8,
        "wiki_effect": "BLUE tiles get +8 TILE SCORE",
        "wiki_page": "Stilton",
    },
    "sunflower": {
        "name": "Sunflower",
        "type": "multiply_money_bonus",
        "base": 0.01,
        "upgrade": 0.01,
        "wiki_effect": "Get ×1 WORD SCORE (Extra 0.01 for each $ you have)",
        "wiki_page": "Sunflower",
    },
    "telescope": {
        "name": "Telescope",
        "type": "red_encounter_tile_bonus",
        "wiki_effect": "RED tiles get +N TILE SCORE for each RED used this encounter",
        "wiki_page": "Telescope",
    },
    "wheezy_vixen": {
        "name": "Wheezy Vixen",
        "type": "multiply_word_scaled",
        "condition": "word_starts_vwxyz",
        "base": 2,
        "upgrade": 1,
        "wiki_effect": "If your word starts with V, W, X, Y or Z, get ×WORD SCORE",
        "wiki_page": "Wheezy_Vixen",
    },
    "worn_out_jeans": _grid_scatter(
        "Worn-out Jeans",
        "START OF GRID: BLUE tiles become ?s",
        "Worn-out_Jeans",
    ),
    "yellow_glasses": {
        "name": "Yellow Glasses",
        "type": "multiply_word_scaled",
        "condition": "has_double_letter",
        "base": 1.5,
        "upgrade": 0.5,
        "wiki_effect": "If your word contains a double letter, ×WORD SCORE",
        "wiki_page": "Yellow_Glasses",
    },
    # --- Nina Nix unlock (9) ---
    "deep_sea_horror": {
        "name": "Deep Sea Horror",
        "type": "add_tile_score",
        "target": "void",
        "base": -10,
        "upgrade": -10,
        "wiki_effect": "VOID tiles get -10 TILE SCORE",
        "wiki_page": "Deep_Sea_Horror",
    },
    "doughnut": _grid_scatter(
        "Doughnut",
        "START OF GRID: +BASE per unique neighbouring colour",
        "Doughnut",
    ),
    "ferris_wheel": {
        "name": "Ferris Wheel",
        "type": "multiply_word_scaled",
        "condition": "word_starts_ends_different_color",
        "base": 1.5,
        "upgrade": 0.5,
        "wiki_effect": "Word starts/ends on different coloured tiles, ×WORD SCORE",
        "wiki_page": "Ferris_Wheel",
    },
    "fish_cake": {
        "name": "Fish Cake",
        "type": "tile_multiply",
        "target": "shiny",
        "base": 2,
        "upgrade": 1,
        "wiki_effect": "SHINY tiles get ×2 TILE SCORE",
        "wiki_page": "Fish_Cake",
    },
    "game_pad": _grid_scatter(
        "Game Pad",
        "START OF GRID: Scatters VOID, RED and BLUE tiles",
        "Game_Pad",
    ),
    "jigsaw_piece": {
        "name": "Jigsaw Piece",
        "type": "add_word_score",
        "word_mode": "if_subtotal_zero",
        "base": 100,
        "upgrade": 100,
        "wiki_effect": "If word score is exactly zero when applied, +WORD SCORE",
        "wiki_page": "Jigsaw_Piece",
    },
    "maracas": _grid_scatter(
        "Maracas",
        "Each coloured tile used scatters onto the next grid",
        "Maracas",
    ),
    "rainbow_sprinkles": _grid_scatter(
        "Rainbow Sprinkles",
        "3+ unique coloured tiles in word scatters SHINY on next grid",
        "Rainbow_Sprinkles",
    ),
    "tombstone": {
        "name": "Tombstone",
        "type": "add_tile_score",
        "target": "void_adjacent",
        "base": 5,
        "upgrade": 5,
        "wiki_effect": "Tiles get +5 TILE SCORE for each adjacent VOID tile",
        "wiki_page": "Tombstone",
    },
    # --- Hayley Bayles unlock (11) ---
    "alembic_flask": {
        "name": "Alembic Flask",
        "type": "consecutive_number_tile_bonus",
        "base": 25,
        "upgrade": 25,
        "wiki_effect": "Consecutive number tiles on the word path get +25 TILE SCORE",
        "wiki_page": "Alembic_Flask",
    },
    "birthday_cake": {
        "name": "Birthday Cake",
        "type": "add_word_score",
        "word_mode": "birthday_cake_bonus",
        "base": 1,
        "upgrade": 1,
        "wiki_effect": "Get +X WORD SCORE (accumulated); improved by highest number in word × level",
        "wiki_page": "Birthday_Cake",
    },
    "boomerang": {
        "name": "Boomerang",
        "type": "multiply_word_scaled",
        "condition": "word_starts_ends_number",
        "base": 2,
        "upgrade": 1,
        "wiki_effect": "Word starts and ends on a number tile → ×WORD SCORE",
        "wiki_page": "Boomerang",
    },
    "brain": {
        "name": "Brain",
        "type": "multiply_if_number_sum",
        "min_sum": 7,
        "factor_base": 1.0,
        "factor_per_level": 0.5,
        "wiki_effect": "If the numbers in your word add to 7 or more get ×WORD SCORE",
        "wiki_page": "Brain",
    },
    "lab_coat": {
        "name": "Lab Coat",
        "type": "tile_multiply",
        "target": "number",
        "per_level_factor": True,
        "factor_base": 1.0,
        "factor_per_level": 1.0,
        "wiki_effect": "Numbers get ×N TILE SCORE (N = level + 1)",
        "wiki_page": "Lab_Coat",
    },
    "ladybird": _grid_scatter(
        "Ladybird",
        "START OF GRID: scatter RED even and VOID odd number tiles",
        "Ladybird",
    ),
    "lucky_dice": {
        "name": "Lucky Dice",
        "type": "add_word_score",
        "word_mode": "if_contains_target_number",
        "base": 50,
        "upgrade": 50,
        "wiki_effect": "Word contains target number → +50 WORD SCORE",
        "wiki_page": "Lucky_Dice",
    },
    "petri_dish": _grid_scatter(
        "Petri Dish",
        "START OF GRID: scatter 1, 2, 3",
        "Petri_Dish",
    ),
    "soaring_kite": _grid_scatter(
        "Soaring Kite",
        "START OF GRID: scatter 2 lowest BLUE numbers not on grid",
        "Soaring_Kite",
    ),
    "ten_pin_bowling": _grid_scatter(
        "Ten Pin Bowling",
        "START OF GRID: scatter 2 adjacent VOID consecutive numbers",
        "Ten_Pin_Bowling",
    ),
    "traffic_lights": _grid_scatter(
        "Traffic Lights",
        "START OF GRID: scatter 2 uniquely coloured small numbers",
        "Traffic_Lights",
    ),
    # --- Sam Gambit unlock (8) ---
    "backpack": _grid_scatter(
        "Backpack",
        "START OF GRID: Place RED tiles on their starting ranks",
        "Backpack",
    ),
    "carousel_horse": _grid_scatter(
        "Carousel Horse",
        "START OF GRID: Scatters checkpoints; destination tiles get ×2 BASE SCORE",
        "Carousel_Horse",
    ),
    "clapper_board": {
        "name": "Clapper Board",
        "type": "multiply_word_scaled",
        "condition": "chess_takes_gte:2",
        "base": 2,
        "upgrade": 1,
        "wiki_effect": "Words with 2 or more takes in get ×WORD SCORE",
        "wiki_page": "Clapper_Board",
    },
    "gorilla": _grid_scatter(
        "Gorilla",
        "START OF GRID: Scatters VOID tiles",
        "Gorilla",
    ),
    "movie_camera": {
        "name": "Movie Camera",
        "type": "chess_take_word_bonus",
        "mode": "piece_value_first_n",
        "base": 1,
        "upgrade": 1,
        "strict_takes": True,
        "wiki_effect": "+WORD from first N taken piece values (N = level)",
        "wiki_page": "Movie_Camera",
    },
    "raccoon": _grid_scatter(
        "Raccoon",
        "START OF GRID: Scatters chess pieces",
        "Raccoon",
    ),
    "suitcase": _grid_scatter(
        "Suitcase",
        "START OF GRID: Scatters BLUE tiles",
        "Suitcase",
    ),
    "zebra": {
        "name": "Zebra",
        "type": "tile_multiply",
        "target": "chess_take",
        "per_level_factor": True,
        "factor_base": 1.0,
        "factor_per_level": 2.0,
        "strict_takes": True,
        "wiki_effect": "Chess pieces get ×N TILE SCORE if they take another piece",
        "wiki_page": "Zebra",
    },
    # --- Bones The Dog unlock (12) ---
    "celestial_body": {
        "name": "Celestial Body",
        "type": "add_tile_score",
        "target": "card",
        "base": 10,
        "upgrade": 10,
        "wiki_effect": "Cards get +N TILE SCORE",
        "wiki_page": "Celestial_Body",
    },
    "hanafuda": {
        "name": "Hanafuda",
        "type": "card_hand_word_bonus",
        "hand": "pair",
        "word_mode": "per_unused_card",
        "base": 12,
        "upgrade": 12,
        "wiki_effect": "Pair: +WORD per unused card on grid",
        "wiki_page": "Hanafuda",
    },
    "joker": _grid_scatter(
        "Joker",
        "START OF GRID: Scatters joker cards",
        "Joker",
    ),
    "kadomatsu": {
        "name": "Kadomatsu",
        "type": "card_hand_word_bonus",
        "hand": "three_of_a_kind",
        "base": 80,
        "upgrade": 80,
        "wiki_effect": "Three of a kind: +WORD SCORE",
        "wiki_page": "Kadomatsu",
    },
    "musical_notes": _grid_scatter(
        "Musical Notes",
        "START OF GRID: Scatters randomly suited BLUE Es",
        "Musical_Notes",
    ),
    "peacock": {
        "name": "Peacock",
        "type": "multiply_word_scaled",
        "condition": "card_hand:flush",
        "base": 2,
        "upgrade": 1,
        "wiki_effect": "Flush (5 matching suits): ×WORD SCORE",
        "wiki_page": "Peacock",
    },
    "pear": {
        "name": "Pear",
        "type": "add_money_on_hand",
        "hand": "pair",
        "base": 2,
        "upgrade": 1,
        "wiki_effect": "Pair: +$N",
        "wiki_page": "Pear",
    },
    "peas_of_a_pod": {
        "name": "Peas Of A Pod",
        "type": "multiply_word_scaled",
        "condition": "card_hand:four_of_a_kind",
        "base": 2,
        "upgrade": 1,
        "wiki_effect": "Four of a kind: ×WORD SCORE",
        "wiki_page": "Peas_Of_A_Pod",
    },
    "poker_face": {
        "name": "Poker Face",
        "type": "multiply_word_scaled",
        "condition": "word_starts_face_card",
        "base": 2,
        "upgrade": 1,
        "wiki_effect": "Word starts with suited face card: ×WORD SCORE",
        "wiki_page": "Poker_Face",
    },
    "postal_horn": _grid_scatter(
        "Postal Horn",
        "START OF GRID: Scatters cards",
        "Postal_Horn",
    ),
    "slide": {
        "name": "Slide",
        "type": "card_hand_word_bonus",
        "hand": "straight",
        "base": 150,
        "upgrade": 150,
        "wiki_effect": "Straight (5 ascending ranks with suits): +WORD SCORE",
        "wiki_page": "Slide",
    },
    "wrestlers": {
        "name": "Wrestlers",
        "type": "multiply_word_scaled",
        "condition": "word_starts_ends_different_suit",
        "base": 1.5,
        "upgrade": 0.5,
        "wiki_effect": "Word starts and ends on different card suits: ×WORD SCORE",
        "wiki_page": "Wrestlers",
    },
    # --- Octacles unlock (7) ---
    "amphora": _grid_scatter(
        "Amphora",
        "START OF GRID: Scatters random cursed tiles",
        "Amphora",
    ),
    "ghost": _grid_scatter(
        "Ghost",
        "Each cursed tile used scatters cursed tile on next grid",
        "Ghost",
    ),
    "broom": {
        "name": "Broom",
        "type": "multiply_word_scaled",
        "condition": "word_starts_ends_different_curse_type",
        "base": 1.5,
        "upgrade": 0.5,
        "wiki_effect": "Word starts and ends on different curse types: ×WORD SCORE",
        "wiki_page": "Broom",
    },
    "jack_o_lantern": {
        "name": "Jack-o'-Lantern",
        "type": "add_money_on_condition",
        "condition": "word_all_cursed",
        "base": 1,
        "upgrade": 1,
        "wiki_effect": "Get $N for every cursed word",
        "wiki_page": "Jack-o%27-Lantern",
    },
    "mischievous_imp": {
        "name": "Mischievous Imp",
        "type": "multiply_word_scaled",
        "condition": "word_all_cursed",
        "base": 2,
        "upgrade": 1,
        "wiki_effect": "Words containing only cursed tiles get ×WORD SCORE",
        "wiki_page": "Mischievous_Imp",
    },
    "moai": {
        "name": "Moai",
        "type": "add_tile_score",
        "target": "colourless_cursed",
        "base": 12,
        "upgrade": 12,
        "wiki_effect": "Colourless cursed tiles get +N TILE SCORE",
        "wiki_page": "Moai",
    },
    "mysterious_amulet": {
        "name": "Mysterious Amulet",
        "type": "add_tile_score",
        "target": "cursed",
        "base": 8,
        "upgrade": 8,
        "wiki_effect": "Cursed tiles get +N TILE SCORE",
        "wiki_page": "Mysterious_Amulet",
    },
    # --- Nat-H4 unlock (6) ---
    "burrito": {
        "name": "Burrito",
        "type": "multiply_word_other_sticker_levels",
        "base": 0.05,
        "upgrade": 0.05,
        "wiki_effect": "×WORD; +0.05 per level of other stickers (per Burrito level)",
        "wiki_page": "Burrito",
    },
    "stamp_album": {
        "name": "Stamp Album",
        "type": "add_word_score",
        "word_mode": "per_stamp_shop_price",
        "base": 1,
        "upgrade": 1,
        "wiki_effect": "+WORD per $ of total shop price of all stamps",
        "wiki_page": "Stamp_Album",
    },
    "printer": _grid_scatter(
        "Printer",
        "START OF GRID: Scatters 1 BLUE item from the BLUE pool",
        "Printer",
    ),
    "retro_raider": _grid_scatter(
        "Retro Raider",
        "START OF GRID: Scatters a level 1 item from the VOID pool and 1 adjacent VOID tile",
        "Retro_Raider",
    ),
    "toolbox": _grid_scatter(
        "Toolbox",
        "START OF GRID: Scatters 2 RED items from the RED pool (stickers level 1)",
        "Toolbox",
    ),
    "signal_receiver": {
        "name": "Signal Receiver",
        "type": "custom",
        "effect_class": "sell",
        "wiki_effect": "Sell to get random level N sticker from grid not in inventory",
        "wiki_page": "Signal_Receiver",
    },
    # --- Quest unlock (10) ---
    "mystery_gift": {
        "name": "Mystery Gift",
        "type": "custom",
        "effect_class": "sell",
        "wiki_effect": "Sell to get a random level 1 RARE sticker",
        "wiki_page": "Mystery_Gift",
    },
    "hungry_hippo": {
        "name": "Hungry Hippo",
        "type": "add_word_score",
        "word_mode": "scaled_flat",
        "base": 20,
        "upgrade": 20,
        "wiki_effect": "Get +N WORD SCORE (upgrade by eating in shop)",
        "wiki_page": "Hungry_Hippo",
    },
    "sushi": {
        "name": "Sushi",
        "type": "tile_multiply",
        "target": "colourless_adjacent_two_colours",
        "base": 3,
        "upgrade": 1,
        "wiki_effect": "COLOURLESS tiles get ×N TILE SCORE if next to 2 uniquely coloured tiles",
        "wiki_page": "Sushi",
    },
    "ambulance": {
        "name": "Ambulance",
        "type": "multiply_word_scaled",
        "condition": "word_base_negative",
        "base": 1.5,
        "upgrade": 1,
        "wiki_effect": "If submitted word BASE SCORE was negative, get ×WORD SCORE",
        "wiki_page": "Ambulance",
    },
    "dartboard": {
        "name": "Dartboard",
        "type": "add_word_score",
        "word_mode": "if_base_score_eq_target",
        "base": 101,
        "upgrade": 100,
        "wiki_effect": "If BASE SCORE equals target, get +N WORD SCORE",
        "wiki_page": "Dartboard",
    },
    "magic_8_ball": {
        "name": "Magic 8 Ball",
        "type": "add_tile_score",
        "target": "chess_piece",
        "base": 25,
        "upgrade": 25,
        "wiki_effect": "Target chess pieces get +N TILE SCORE",
        "wiki_page": "Magic_8_Ball",
    },
    "wind_chime": {
        "name": "Wind Chime",
        "type": "multiply_word_scaled",
        "condition": "card_count_eq:5",
        "base": 2,
        "upgrade": 1,
        "wiki_effect": "If word contains exactly 5 cards, get ×WORD SCORE",
        "wiki_page": "Wind_Chime",
    },
    "michael_s_book": {
        "name": "Michael's Book",
        "type": "add_word_score",
        "word_mode": "michael_book_bonus",
        "wiki_effect": "Get +N WORD SCORE from cumulative target-word progress",
        "wiki_page": "Michael%27s_Book",
    },
    "luffing_jib_crane": {
        "name": "Luffing Jib Crane",
        "type": "custom",
        "effect_class": "rack",
        "wiki_effect": "Consumable tiles get +N BASE SCORE when added to tile rack",
        "wiki_page": "Luffing_Jib_Crane",
    },
    "base_camp": {
        "name": "Base Camp",
        "type": "add_word_score",
        "word_mode": "grid_total_base_times_level",
        "base": 1,
        "upgrade": 1,
        "wiki_effect": "Get WORD SCORE equal to total BASE SCORE on grid ×N",
        "wiki_page": "Base_Camp",
    },
    # --- Achievement unlock (46) ---
    "arrivals": {
        "name": "Arrivals",
        "type": "multiply_word_scaled",
        "condition": "requires_sticker_slot:first",
        "base": 1.5,
        "upgrade": 0.5,
        "wiki_effect": "First sticker slot: ×WORD SCORE",
        "wiki_page": "Arrivals",
    },
    "axe": {
        "name": "Axe",
        "type": "multiply_word_scaled",
        "condition": "path_length_lte:3",
        "base": 1.5,
        "upgrade": 0.5,
        "wiki_effect": "Words with 3 or fewer tiles get ×WORD SCORE",
        "wiki_page": "Axe",
    },
    "baby_bottle": {
        "name": "Baby Bottle",
        "type": "multiply_word_scaled",
        "condition": "wildcard_count_eq:2",
        "base": 2,
        "upgrade": 0.5,
        "wiki_effect": "Exactly 2 ? tiles in word get ×WORD SCORE",
        "wiki_page": "Baby_Bottle",
    },
    "brick": _custom_effect(
        "Brick",
        "Overflowing consumable rack gives consumables +N BASE when added to rack",
        "rack",
        "Brick",
    ),
    "candle": _grid_scatter(
        "Candle",
        "START OF GRID: Scatters VOID currencies",
        "Candle",
    ),
    "castle": _grid_scatter(
        "Castle",
        "START OF GRID: Set BASE SCORE of all chess pieces to 16",
        "Castle",
    ),
    "champagne": _grid_scatter(
        "Champagne",
        "START OF GRID: For each 5 coloured tiles, 1 becomes SHINY",
        "Champagne",
    ),
    "circus_tent": {
        "name": "Circus Tent",
        "type": "multiply_word_scaled",
        "condition": "has_blue_red_and_colourless",
        "base": 1.5,
        "upgrade": 0.5,
        "wiki_effect": "Word with BLUE, RED and COLOURLESS tiles gets ×WORD SCORE",
        "wiki_page": "Circus_Tent",
    },
    "cocktail": {
        "name": "Cocktail",
        "type": "tile_multiply",
        "target": "first_of_each_colour",
        "base": 2,
        "upgrade": 1,
        "wiki_effect": "First tile of each colour on path gets ×N TILE SCORE",
        "wiki_page": "Cocktail",
    },
    "coin_purse": _grid_scatter(
        "Coin Purse",
        "START OF GRID: Spends $3 to scatter 1 SHINY ? tile",
        "Coin_Purse",
    ),
    "confetti": {
        "name": "Confetti",
        "type": "multiply_word_scaled",
        "condition": "unique_colours_eq:5",
        "base": 2,
        "upgrade": 1,
        "wiki_effect": "Words with 5 different colours get ×WORD SCORE",
        "wiki_page": "Confetti",
    },
    "creaky_chair": {
        "name": "Creaky Chair",
        "type": "multiply_word_scaled",
        "condition": "curse_types_gte:3",
        "base": 2,
        "upgrade": 1,
        "wiki_effect": "Words with 3+ curse types get ×WORD SCORE",
        "wiki_page": "Creaky_Chair",
    },
    "crystal_ball": {
        "name": "Crystal Ball",
        "type": "add_word_score",
        "word_mode": "if_target_wildcard_on_path",
        "base": 70,
        "upgrade": 70,
        "wiki_effect": "Word with target-curse ? tile gets +N WORD SCORE",
        "wiki_page": "Crystal_Ball",
    },
    "cursed_vhs": _grid_scatter(
        "Cursed VHS",
        "START OF GRID: Scatters cursed pool item per curse type on grid",
        "Cursed_VHS",
    ),
    "dagger": {
        "name": "Dagger",
        "type": "add_word_score",
        "word_mode": "if_king_take_on_path",
        "base": 50,
        "upgrade": 50,
        "wiki_effect": "Taking a king gives +N WORD SCORE",
        "wiki_page": "Dagger",
    },
    "dancer": _grid_scatter(
        "Dancer",
        "START OF GRID: Scatters 2 of clubs",
        "Dancer",
    ),
    "departures": {
        "name": "Departures",
        "type": "add_word_score",
        "word_mode": "if_sticker_slot_last",
        "base": 100,
        "upgrade": 50,
        "wiki_effect": "Last sticker slot: +N WORD SCORE",
        "wiki_page": "Departures",
    },
    "diving_mask": _custom_effect(
        "Diving Mask",
        "Targets are 10% lower per level",
        "target_reduction",
        "Diving_Mask",
    ),
    "down_under": {
        "name": "Down Under",
        "type": "tile_multiply",
        "target": "all",
        "base": -3,
        "upgrade": -2,
        "wiki_effect": "All tiles on path get ×N TILE SCORE (negative)",
        "wiki_page": "Down_Under",
    },
    "fireworks": _grid_scatter(
        "Fireworks",
        "START OF FINAL GRID: Scatters SHINY tiles",
        "Fireworks",
        grid_timing="final",
    ),
    "footprints": {
        "name": "Footprints",
        "type": "multiply_word_scaled",
        "condition": "non_adjacent_steps_gte:3",
        "base": 2,
        "upgrade": 1,
        "wiki_effect": "3+ non-adjacent moves in word get ×WORD SCORE",
        "wiki_page": "Footprints",
    },
    "gold_fish": _grid_scatter(
        "Gold Fish",
        "START OF GRID: Get currency consumable tile(s)",
        "Gold_Fish",
    ),
    "kangaroo": {
        "name": "Kangaroo",
        "type": "add_tile_score",
        "target": "chess_move_tiles",
        "base": 5,
        "upgrade": 5,
        "wiki_effect": "+N TILE SCORE per chess tile on path in valid chess move",
        "wiki_page": "Kangaroo",
    },
    "las_vegas": {
        "name": "Las Vegas",
        "type": "multiply_word_scaled",
        "condition": "distinct_card_suits_gte:2",
        "base": 2,
        "upgrade": 1,
        "wiki_effect": "Words with 2+ card suits get ×WORD SCORE",
        "wiki_page": "Las_Vegas",
    },
    "lollipop": {
        "name": "Lollipop",
        "type": "add_word_score",
        "word_mode": "per_shop_restock",
        "base": 5,
        "upgrade": 5,
        "wiki_effect": "+N WORD SCORE per shop restock this run",
        "wiki_page": "Lollipop",
    },
    "newspaper": {
        "name": "Newspaper",
        "type": "multiply_word_scaled",
        "condition": "word_all_colourless",
        "base": 1.5,
        "upgrade": 0.5,
        "wiki_effect": "COLOURLESS words get ×WORD SCORE",
        "wiki_page": "Newspaper",
    },
    "onigiri": {
        "name": "Onigiri",
        "type": "add_word_score",
        "word_mode": "colourless_word_flat",
        "base": 20,
        "upgrade": 40,
        "wiki_effect": "COLOURLESS words get +N WORD SCORE",
        "wiki_page": "Onigiri",
    },
    "overhand": _custom_effect(
        "Overhand",
        "Executes below Stamp grid and scoring effects again",
        "stamp_replay",
        "Overhand",
    ),
    "parrot": {
        "name": "Parrot",
        "type": "add_word_score",
        "word_mode": "colourless_word_per_coloured_on_grid",
        "base": 8,
        "upgrade": 8,
        "wiki_effect": "COLOURLESS words get +N WORD per coloured tile on grid",
        "wiki_page": "Parrot",
    },
    "postbox": {
        "name": "Postbox",
        "type": "multiply_word_scaled",
        "condition": "word_all_uncursed",
        "base": 2,
        "upgrade": 1,
        "wiki_effect": "Uncursed words get ×WORD SCORE",
        "wiki_page": "Postbox",
    },
    "radio": _grid_scatter(
        "Radio",
        "START OF GRID: Scatters COLOURLESS pool sticker(s)",
        "Radio",
    ),
    "rex": _grid_scatter(
        "Rex",
        "START OF GRID: Scatters bones",
        "Rex",
    ),
    "roller_skate": _grid_scatter(
        "Roller Skate",
        "START OF GRID: Scatters currency per restock in previous shop",
        "Roller_Skate",
    ),
    "rolodex": _grid_scatter(
        "Rolodex",
        "START OF GRID: Scatters cards from same-suit pool",
        "Rolodex",
    ),
    "scissors": {
        "name": "Scissors",
        "type": "multiply_word_per_distinct_pair",
        "base": 1.25,
        "upgrade": 0.25,
        "wiki_effect": "×WORD SCORE per distinct pair in word",
        "wiki_page": "Scissors",
    },
    "shield": {
        "name": "Shield",
        "type": "blue_tile_base_override",
        "base": 10,
        "upgrade": 10,
        "wiki_effect": "BLUE tiles have base score of N",
        "wiki_page": "Shield",
    },
    "snapshot": _grid_scatter(
        "Snapshot",
        "START OF GRID: Becomes copy of random sticker on grid",
        "Snapshot",
    ),
    "snowman": _grid_scatter(
        "Snowman",
        "START OF GRID: Scatters currency per frozen shop item",
        "Snowman",
    ),
    "sticky_plaster": _custom_effect(
        "Sticky Plaster",
        "Number tiles from previous word stick; +N BASE per level",
        "sticky_numbers",
        "Sticky_Plaster",
    ),
    "storm_cloud": _grid_scatter(
        "Storm Cloud",
        "START OF GRID: Get cursed consumable tile(s)",
        "Storm_Cloud",
    ),
    "under_construction": {
        "name": "Under Construction",
        "type": "multiply_word_scaled",
        "condition": "word_starts_ends_consumable",
        "base": 2,
        "upgrade": 1,
        "wiki_effect": "Words starting and ending on consumable tiles get ×WORD SCORE",
        "wiki_page": "Under_Construction",
    },
    "wriggly_worm": {
        "name": "Wriggly Worm",
        "type": "multiply_word_scaled",
        "condition": "path_length_gte:10",
        "base": 1.5,
        "upgrade": 0.5,
        "wiki_effect": "Words with 10+ tiles get ×WORD SCORE",
        "wiki_page": "Wriggly_Worm",
    },
    # --- Cannot be obtained from the shop (4) ---
    "bone": {
        "name": "Bone",
        "type": "multiply_word_scaled",
        "condition": "always",
        "base": 1.5,
        "upgrade": 0.5,
        "wiki_effect": "Get ×WORD SCORE",
        "wiki_page": "Bone",
    },
    "frankenstein": _custom_effect(
        "Frankenstein",
        "The Modern Prometheus (no scoring effect)",
        "unique",
        "Frankenstein",
    ),
    "left_hand": _custom_effect(
        "Left Hand",
        "Points at your favourite Sticker (Human Hands)",
        "meta",
        "Left_Hand",
    ),
    "padlock_sticker": {
        "name": "Padlock (sticker)",
        "type": "custom",
        "effect_class": "sell_cost",
        "sell_price_base": 8,
        "sell_price_upgrade": 8,
        "wiki_effect": "Costs $8 to sell",
        "wiki_page": "Padlock_(sticker)",
    },
    # --- Other tuned stickers ---
    "red_rider": {"name": "Red Rider", "type": "red_tile_bonus", "value": 10},
    "void_flip": {"name": "Void Flip", "type": "void_flip", "value": 0},
    "long_word": {
        "name": "Long Word",
        "type": "word_length_bonus",
        "value": 20,
        "min_length": 5,
    },
    "shiny_chain": {"name": "Shiny Chain", "type": "shiny_chain", "value": 25},
    "double_score": {"name": "Double Score", "type": "multiply", "factor": 2.0},
}

TUNED_STAMPS: dict[str, dict] = {
    # --- Unlocked by default (28) ---
    "avocado": {
        "name": "Avocado",
        "type": "multiply",
        "factor": 2.0,
        "wiki_effect": "×2 WORD SCORE. Shop prices are doubled. Best served fresh",
        "wiki_page": "Avocado",
        "shop_price": 20,
        "effect_class": "shop",
    },
    "bento_box": {
        "name": "Bento Box",
        "type": "multiply_word_scaled",
        "condition": "word_starts_same_as_previous",
        "base": 1.5,
        "upgrade": 0,
        "wiki_effect": "If your word starts with the same letter as your previous word, get ×1.5 WORD SCORE",
        "wiki_page": "Bento_Box",
        "shop_price": 16,
    },
    "bubble_tea": {
        "name": "Bubble Tea",
        "type": "tile_multiply_by_letter_count",
        "wiki_effect": "Tiles get TILE SCORE × same letter count",
        "wiki_page": "Bubble_Tea",
        "shop_price": 18,
    },
    "downward_trending_chart": _custom_effect(
        "Downward Trending Chart",
        "START OF SHOP: Frozen items get $2 cheaper",
        "shop",
        "Downward_Trending_Chart",
    )
    | {"shop_price": 8},
    "efficient_recycler": _custom_effect(
        "Efficient Recycler",
        "Shops restock when you buy a Sticker or a Stamp",
        "shop",
        "Efficient_Recycler",
    )
    | {"shop_price": 9},
    "family_ticket": _grid_scatter(
        "Family Ticket",
        "Each tile used with a base value of 4 or more scatters a RED tile onto the next grid",
        "Family_Ticket",
        grid_timing="on_submit",
    )
    | {"shop_price": 8},
    "full_moon": _custom_effect(
        "Full Moon",
        "You can double letter teleport",
        "movement",
        "Full_Moon",
    )
    | {
        "shop_price": 11,
        "game_class": "FullMoon",
        "search_flags": {"double_letter_teleport": True},
    },
    "golden_record": _custom_effect(
        "Golden Record",
        "Get a random tile from your word as a consumable tile",
        "consumable",
        "Golden_Record",
    )
    | {"shop_price": 18},
    "golden_scales": _custom_effect(
        "Golden Scales",
        "START OF ENCOUNTER: Each empty Sticker slot gives $1",
        "encounter",
        "Golden_Scales",
    )
    | {"shop_price": 10},
    "hungry_snake": {
        "name": "Hungry Snake",
        "type": "custom",
        "effect_class": "movement",
        "game_class": "HungrySnake",
        "wiki_effect": "The grid wraps horizontally",
        "wiki_page": "Hungry_Snake",
        "search_flags": {"horizontal_wrap": True},
        "shop_price": 11,
    },
    "kimono": _grid_scatter(
        "Kimono",
        "Each BLUE tile used scatters a ? onto the next grid",
        "Kimono",
        grid_timing="on_submit",
    )
    | {"shop_price": 16},
    "limnophila": {
        "name": "Limnophila",
        "type": "multiply_word_scaled",
        "condition": "word_starts_after_previous",
        "base": 1.5,
        "upgrade": 0,
        "wiki_effect": "If your word starts with a letter one later in the alphabet than the previous word, ×1.5 WORD SCORE",
        "wiki_page": "Limnophila",
        "shop_price": 8,
    },
    "nest_egg": _custom_effect(
        "Nest Egg",
        "Sells for $0 (Use a BLUE tile to improve)",
        "shop",
        "Nest_Egg",
    )
    | {"shop_price": 12},
    "paper_lantern": _grid_scatter(
        "Paper Lantern",
        "START OF GRID: Positions which were RED in the previous word turn RED",
        "Paper_Lantern",
    )
    | {"shop_price": 12},
    "parachute": _grid_scatter(
        "Parachute",
        "START OF GRID: If there are currently no RED tiles on the grid, scatters 3 RED tiles",
        "Parachute",
    )
    | {"shop_price": 8},
    "pi_ata": _grid_scatter(
        "Piñata",
        "Words containing 7 or more tiles scatter a SHINY tile onto the next grid",
        "Pinata",
        grid_timing="on_submit",
    )
    | {"shop_price": 10},
    "queenie": {
        "name": "Queenie",
        "type": "tile_multiply",
        "target": "letter:q",
        "factor": 5.0,
        "wiki_effect": "Qs can behave as a QU. Qs get ×5 TILE SCORE",
        "wiki_page": "Queenie",
        "shop_price": 10,
        "game_class": "Queenie",
        "letter_behavior": "q_as_qu",
        "search_flags": {"q_as_qu": True},
    },
    "red_envelope": _custom_effect(
        "Red Envelope",
        "RED tiles can behave as an E",
        "letter_behavior",
        "Red_Envelope",
    )
    | {"shop_price": 12, "letter_substitute": "red_as_e"},
    "saxophone": _grid_scatter(
        "Saxophone",
        "Scattered BLUE tiles huddle together",
        "Saxophone",
    )
    | {"shop_price": 7},
    "slot_machine": _grid_scatter(
        "Slot Machine",
        "START OF GRID: Scatters 2 VOID tiles. 1 extra grid reroll per encounter",
        "Slot_Machine",
    )
    | {"shop_price": 12},
    "sluggish_zombie": _grid_scatter(
        "Sluggish Zombie",
        "Zs can behave as an S. START OF GRID: Ss become Zs",
        "Sluggish_Zombie",
    )
    | {"shop_price": 12, "letter_substitute": "z_as_s"},
    "teapot": _grid_scatter(
        "Teapot",
        "START OF GRID: Scatters a BLUE tile for each grid seen this encounter",
        "Teapot",
    )
    | {"shop_price": 9},
    "tile_ninja": {
        "name": "Tile Ninja",
        "type": "multiply_word_scaled",
        "base": 1.2,
        "upgrade": 0,
        "scale_from_extras": "tile_ninja_bonus",
        "wiki_effect": "Get ×1.2 WORD SCORE (Place a consumable tile to improve)",
        "wiki_page": "Tile_Ninja",
        "shop_price": 18,
    },
    "waxy_vizor": _grid_scatter(
        "Waxy Vizor",
        "START OF GRID: Vs, Ws, Xs, Ys and Zs become BLUE",
        "Waxy_Vizor",
    )
    | {"shop_price": 14},
    "weekly_shop": _grid_scatter(
        "Weekly Shop",
        "START OF GRID: Get 2 COLOURLESS consumable tiles",
        "Weekly_Shop",
    )
    | {"shop_price": 14},
    "window": _grid_scatter(
        "Window",
        "Using all tiles in a 2x2 area scatters 4 BLUE tiles onto the next grid",
        "Window",
        grid_timing="on_submit",
    )
    | {"shop_price": 8},
    "xray": _grid_scatter(
        "Xray",
        "START OF GRID: BLUE vowels become ?s",
        "Xray",
    )
    | {"shop_price": 16},
    "young_cardinal": _custom_effect(
        "Young Cardinal",
        "Items with 'red' in their description cost $4 less",
        "shop",
        "Young_Cardinal",
    )
    | {"shop_price": 8},
    # --- Unlocked when unlocking Hayley Bayles (4) ---
    "flamingo": _custom_effect(
        "Flamingo",
        "SHINY tiles can behave as 1s",
        "letter_behavior",
        "Flamingo",
    )
    | {"shop_price": 10, "letter_behavior": "shiny_as_one"},
    "full_battery": {
        "name": "Full Battery",
        "type": "multiply_word_by_number_count",
        "wiki_effect": "Words containing only numbers get WORD SCORE × number of numbers",
        "wiki_page": "Full_Battery",
        "shop_price": 18,
    },
    "microscope": {
        "name": "Microscope",
        "type": "use_base_score_tiles",
        "wiki_effect": "Tiles can act as their BASE SCORE",
        "wiki_page": "Microscope",
        "shop_price": 18,
    },
    "test_tube": _custom_effect(
        "Test Tube",
        "Numbers can behave as the number one higher or one lower",
        "letter_behavior",
        "Test_Tube",
    )
    | {"shop_price": 15, "letter_behavior": "number_plus_minus_one"},
    # --- Unlocked when unlocking Sam Gambit (2) ---
    "business_goose": _grid_scatter(
        "Business Goose",
        "START OF GRID: get randomly promoted",
        "Business_Goose",
    )
    | {"shop_price": 12},
    "queen_bee": _grid_scatter(
        "Queen Bee",
        "START OF GRID: Scatters a Queen and a black Queen",
        "Queen_Bee",
    )
    | {"shop_price": 16},
    # --- Unlocked when unlocking Bones The Dog (7) ---
    "card_shark": _custom_effect(
        "Card Shark",
        "Cards can behave as the first letter of their suit",
        "letter_behavior",
        "Card_Shark",
    )
    | {"shop_price": 10, "letter_behavior": "card_suit_first_letter"},
    "martini": {
        "name": "Martini",
        "type": "card_hand_min_size",
        "min_size": 3,
        "wiki_effect": "Flushes and Straights only require 3 cards",
        "wiki_page": "Martini",
        "shop_price": 13,
    },
    "four_leaf_clover": _grid_scatter(
        "Four Leaf Clover",
        "START OF GRID: Scatters a BLUE, SHINY, RED and VOID of the same suit",
        "Four_Leaf_Clover",
    )
    | {"shop_price": 18},
    "go_fish": _grid_scatter(
        "Go Fish!",
        "START OF GRID: Scatters a BLUE Straight Flush (of numbers!)",
        "Go_Fish",
    )
    | {"shop_price": 16},
    "magician_s_hat": _grid_scatter(
        "Magician's Hat",
        "START OF GRID: Turn all VOID tiles into spades",
        "Magician%27s_Hat",
    )
    | {"shop_price": 12},
    "smart_shirt": _grid_scatter(
        "Smart Shirt",
        "START OF GRID: Turn your coloured tiles into cards",
        "Smart_Shirt",
    )
    | {"shop_price": 10},
    "valentine_s_day_card": _grid_scatter(
        "Valentine's Day Card",
        "START OF GRID: Turn all RED tiles into hearts",
        "Valentine%27s_Day_Card",
    )
    | {"shop_price": 10},
    # --- Unlocked when unlocking Octacles (2) ---
    "haunted_mirror": _grid_scatter(
        "Haunted Mirror",
        "START OF GRID: Randomly recolour all cursed tiles",
        "Haunted_Mirror",
    )
    | {"shop_price": 13},
    "oden": {
        "name": "Oden",
        "type": "multiply_word_by_unique_curse_type_count",
        "wiki_effect": "Get WORD SCORE × number of unique curse types",
        "wiki_page": "Oden",
        "shop_price": 18,
    },
    # --- Unlocked when unlocking Nat-H4 (3) ---
    "delivery_truck": _custom_effect(
        "Delivery Truck",
        "Consumable tiles stocked in the shop are all item tiles",
        "shop",
        "Delivery_Truck",
    )
    | {"shop_price": 12},
    "filing_cabinet": _grid_scatter(
        "Filing Cabinet",
        "START OF GRID: One tile of each colour becomes an item from the RAINBOW pool",
        "Filing_Cabinet",
    )
    | {"shop_price": 16},
    "steak": {
        "name": "Steak",
        "type": "multiply_word_scaled",
        "condition": "always",
        "base": 1,
        "upgrade": 0,
        "scale_from_extras": "rare_item_count",
        "wiki_effect": "Get ×1 WORD SCORE (Increased by your RARE items)",
        "wiki_page": "Steak",
        "shop_price": 15,
    },
    # --- Unlocked when completing quests (15) ---
    "banana": {
        "name": "Banana",
        "type": "multiply_word_by_high_letter_count",
        "min_letter_count": 3,
        "wiki_effect": "For letters which occur at least 3 times, get WORD SCORE × half that letter's count",
        "wiki_page": "Banana",
        "shop_price": 16,
    },
    "head_trauma": _grid_scatter(
        "Head Trauma",
        "START OF GRID: Scatters 2 VOID tiles and 2 BLUE ? tiles",
        "Head_Trauma",
    )
    | {"shop_price": 18},
    "busy_schedule": _grid_scatter(
        "Busy Schedule",
        "Fill the grid with ascending numbers",
        "Busy_Schedule",
    )
    | {"shop_price": 18},
    "number_go_up": _custom_effect(
        "Number Go Up",
        "If all numbers in your word are in ascending order, they can be used in any position",
        "letter_behavior",
        "Number_Go_Up",
    )
    | {"shop_price": 18, "letter_behavior": "number_ascending_free_position"},
    "bar_of_soap": _custom_effect(
        "Bar Of Soap",
        "Each unique tile colour in your word gives a SHINY ? consumable tile",
        "consumable",
        "Bar_Of_Soap",
    )
    | {"shop_price": 41},
    "honeypot": _custom_effect(
        "Honeypot",
        "You can stick two words together",
        "movement",
        "Honeypot",
    )
    | {"shop_price": 16},
    "ruler": {
        "name": "Ruler",
        "type": "multiply_word_scaled",
        "condition": "always",
        "base": 1,
        "upgrade": 0,
        "scale_from_path": "non_adjacent_steps",
        "path_scale": 0.02,
        "wiki_effect": "Get ×1 WORD SCORE. Improved by 0.02 for each non-adjacent move",
        "wiki_page": "Ruler",
        "shop_price": 15,
    },
    "christmas_tree": _grid_scatter(
        "Christmas Tree",
        "START OF GRID: Scatters a colour that isn't on the grid",
        "Christmas_Tree",
    )
    | {"shop_price": 12},
    "juice_box": _grid_scatter(
        "Juice Box",
        "Scatters each submitted word onto the next grid",
        "Juice_Box",
        grid_timing="on_submit",
    )
    | {"shop_price": 16},
    "chick": {
        "name": "Chick",
        "type": "multiply_word_scaled",
        "condition": "always",
        "base": 1,
        "upgrade": 0,
        "scale_from_extras": "level_one_sticker_count",
        "wiki_effect": "Get ×1 WORD SCORE (Increased by your level 1 Stickers)",
        "wiki_page": "Chick",
        "shop_price": 15,
    },
    "spicy_pepper": _custom_effect(
        "Spicy Pepper",
        "RED tiles can behave as an S",
        "letter_behavior",
        "Spicy_Pepper",
    )
    | {"shop_price": 14, "letter_behavior": "red_as_s"},
    "rosebud": _custom_effect(
        "Rosebud",
        "START OF ENCOUNTER: Add a RED R, E, D, S to your tile rack",
        "encounter",
        "Rosebud",
    )
    | {"shop_price": 17},
    "angel_investment": _custom_effect(
        "Angel Investment",
        "Your first item in each shop is free",
        "shop",
        "Angel_Investment",
    )
    | {"shop_price": 35},
    "eraser": _custom_effect(
        "Eraser",
        "Restocking the shop removes all restocked items from the shop pool",
        "shop",
        "Eraser",
    )
    | {"shop_price": 17},
    "tin_of_beans": _custom_effect(
        "Tin Of Beans",
        "Items stocked in the shop have their colours randomised",
        "shop",
        "Tin_Of_Beans",
    )
    | {"shop_price": 10},
    # --- Unlocked when completing various other achievements (82) ---
    **ACHIEVEMENT_STAMPS,
    # --- Created by other mechanics (2) ---
    "padlock_stamp": {
        "name": "Padlock (stamp)",
        "type": "custom",
        "effect_class": "sell_cost",
        "sell_price_base": 8,
        "sell_price_upgrade": 8,
        "wiki_effect": "Costs $8 to sell",
        "wiki_page": "Padlock_(stamp)",
        "unique": True,
    },
    "right_hand": _custom_effect(
        "Right Hand",
        "Points at your favourite Stamp",
        "meta",
        "Right_Hand",
    )
    | {"unique": True},
    # --- Unlocked when unlocking Nina Nix (3) ---
    "chocolate_candy": _grid_scatter(
        "Chocolate Candy",
        "START OF GRID: Ms and Ss become random colours",
        "Chocolate_Candy",
    )
    | {"shop_price": 10},
    "dangerous_summit": _grid_scatter(
        "Dangerous Summit",
        "START OF GRID: The 3 highest base value tiles become VOID",
        "Dangerous_Summit",
    )
    | {"shop_price": 12},
    "dango": {
        "name": "Dango",
        "type": "multiply_word_by_unique_colour_count",
        "wiki_effect": "Get WORD SCORE × unique tile colours used",
        "wiki_page": "Dango",
        "shop_price": 18,
    },
    # --- Other tuned stamps ---
    "newspaper": {
        "name": "Newspaper",
        "type": "add_word_score",
        "value": 8,
        "shop_price": 8,
    },
    "moai": {
        "name": "Moai",
        "type": "word_length_bonus",
        "value": 15,
        "min_length": 4,
        "shop_price": 12,
    },
}

def _boss_grid(name: str, wiki_page: str, wiki_effect: str, scaling: list[dict]) -> dict:
    return {
        "name": name,
        "type": "custom",
        "effect_class": "grid",
        "wiki_page": wiki_page,
        "wiki_effect": wiki_effect,
        "scaling": scaling,
    }


TUNED_BOSSES: dict[str, dict] = {
    "mole": _boss_grid(
        "Mole",
        "Mole",
        "Scatter void tiles (count scales by area)",
        [
            {"area": 1, "value": 3, "cursed": 5},
            {"area": 2, "value": 4, "cursed": 6},
            {"area": 3, "value": 5, "cursed": 8},
            {"area": 4, "value": 5, "cursed": 8},
            {"area": 5, "value": 6, "cursed": 10},
        ],
    ),
    "axolotl": _boss_grid(
        "Axolotl",
        "Axolotl",
        "Scatter Q tiles",
        [
            {"area": 1, "value": 3, "cursed": 5},
            {"area": 2, "value": 4, "cursed": 6},
            {"area": 3, "value": 5, "cursed": 8},
            {"area": 4, "value": 5, "cursed": 8},
            {"area": 5, "value": 6, "cursed": 10},
        ],
    ),
    "bison": _boss_grid(
        "Bison",
        "Bison",
        "Scatters high number tiles (range scales by area)",
        [
            {"area": 1, "value": 9, "cursed": 11},
            {"area": 2, "value": 10, "cursed": 12},
            {"area": 3, "value": 11, "cursed": 14},
            {"area": 4, "value": 12, "cursed": 15},
            {"area": 5, "value": 13, "cursed": 17},
        ],
    ),
    "yeti_crab": _boss_grid(
        "Yeti Crab",
        "Yeti_Crab",
        "Makes colored tiles colorless",
        [
            {"area": 1, "value": 2, "cursed": 3},
            {"area": 2, "value": 3, "cursed": 4},
            {"area": 3, "value": 4, "cursed": 6},
            {"area": 4, "value": 4, "cursed": 7},
            {"area": 5, "value": 5, "cursed": 8},
        ],
    ),
    "robo_eel": _boss_grid(
        "Robo-Eel",
        "Robo-Eel",
        "Eats tiles each grid (board reflects eaten tiles)",
        [
            {"area": 1, "value": 2, "cursed": 3},
            {"area": 2, "value": 2, "cursed": 3},
            {"area": 3, "value": 2, "cursed": 3},
            {"area": 4, "value": 3, "cursed": 4},
            {"area": 5, "value": 3, "cursed": 5},
        ],
    ),
    "bat": {
        "name": "Bat",
        "type": "custom",
        "effect_class": "grid",
        "wiki_page": "Bat",
        "wiki_effect": "Shrinks playable grid (rows×cols)",
        "scaling": [
            {"area": 1, "rows": 4, "cols": 4, "cursed_rows": 4, "cursed_cols": 3},
            {"area": 2, "rows": 4, "cols": 4, "cursed_rows": 4, "cursed_cols": 3},
            {"area": 3, "rows": 4, "cols": 3, "cursed_rows": 3, "cursed_cols": 3},
            {"area": 4, "rows": 4, "cols": 3, "cursed_rows": 3, "cursed_cols": 3},
            {"area": 5, "rows": 3, "cols": 3, "cursed_rows": 3, "cursed_cols": 2},
        ],
    },
    "badger": {
        "name": "Badger",
        "type": "custom",
        "effect_class": "encounter",
        "wiki_page": "Badger",
        "wiki_effect": "Fewer grids per encounter",
        "scaling": [
            {"area": a, "value": 1, "cursed": 2} for a in range(1, 6)
        ],
    },
    "fox": {
        "name": "Fox",
        "type": "custom",
        "effect_class": "encounter",
        "wiki_page": "Fox",
        "wiki_effect": "Steals money each grid",
        "scaling": [
            {"area": 1, "value": 2, "cursed": 3},
            {"area": 2, "value": 3, "cursed": 5},
            {"area": 3, "value": 4, "cursed": 6},
            {"area": 4, "value": 5, "cursed": 8},
            {"area": 5, "na": True},
        ],
    },
    "hyena": {
        "name": "Hyena",
        "type": "custom",
        "effect_class": "encounter",
        "wiki_page": "Hyena",
        "wiki_effect": "Blocks submissions until a sticker or stamp is sold",
    },
    "cretaceous_meg": {
        "name": "Cretaceous Meg",
        "type": "custom",
        "effect_class": "encounter",
        "wiki_page": "Cretaceous_Meg_(boss)",
        "wiki_effect": (
            "Strips loadout to special shop ($120/$160/$200 by stage); "
            "rebuild before challenge grids"
        ),
    },
    "capybara": {
        "name": "Capybara",
        "type": "shuffle_loadout_order",
        "effect_class": "encounter",
        "game_class": "Capybara",
        "wiki_page": "Capybara",
        "wiki_effect": "Randomizes sticker/stamp order on submit",
        "scaling": [
            {"area": a, "value": 1, "cursed": 2} for a in range(1, 6)
        ],
    },
    "cobra": {
        "name": "Cobra",
        "type": "boss_word_min_length",
        "game_class": "MinWordLength",
        "effect_class": "search_only",
        "wiki_page": "Cobra",
        "scaling": [
            {"area": 1, "min_length": 4, "cursed_min_length": 5},
            {"area": 2, "min_length": 5, "cursed_min_length": 6},
            {"area": 3, "min_length": 6, "cursed_min_length": 7},
            {"area": 4, "min_length": 6, "cursed_min_length": 7},
            {"area": 5, "min_length": 7, "cursed_min_length": 8},
        ],
    },
    "wolf": {
        "name": "Wolf",
        "type": "boss_word_max_length",
        "game_class": "MaxWordLength",
        "effect_class": "search_only",
        "wiki_page": "Wolf",
        "scaling": [
            {"area": 1, "max_length": 5, "cursed_max_length": 4},
            {"area": 2, "max_length": 5, "cursed_max_length": 4},
            {"area": 3, "max_length": 4, "cursed_max_length": 3},
            {"area": 4, "max_length": 4, "cursed_max_length": 3},
            {"area": 5, "max_length": 4, "cursed_max_length": 3},
        ],
    },
    "salamander": {
        "name": "Salamander",
        "type": "boss_tile_penalty",
        "game_class": "ReducedLetterValue",
        "effect_class": "scoring_early",
        "wiki_page": "Salamander",
        "scaling": [
            {"area": 1, "value": 1, "cursed": 2},
            {"area": 2, "value": 3, "cursed": 4},
            {"area": 3, "value": 5, "cursed": 7},
            {"area": 4, "value": 7, "cursed": 9},
            {"area": 5, "value": 9, "cursed": 12},
        ],
    },
    "robo_monkey": {
        "name": "Robo-Monkey",
        "type": "boss_subtract_word_score_money",
        "game_class": "NegativeMoney",
        "effect_class": "scoring_early",
        "wiki_page": "Robo-Monkey",
        "scaling": [
            {"area": 1, "multiplier": 1, "cursed_multiplier": 2},
            {"area": 2, "multiplier": 5, "cursed_multiplier": 7},
            {"area": 3, "multiplier": 9, "cursed_multiplier": 12},
            {"area": 4, "multiplier": 15, "cursed_multiplier": 20},
            {"area": 5, "na": True},
        ],
    },
    "toothed_whale": {
        "name": "Toothed Whale",
        "type": "boss_target_score_multiplier",
        "game_class": "BigBoss",
        "effect_class": "encounter",
        "wiki_page": "Toothed_Whale",
        "scaling": [
            {"area": 1, "multiplier": 1.25, "cursed_multiplier": 1.35},
            {"area": 2, "multiplier": 1.35, "cursed_multiplier": 1.5},
            {"area": 3, "multiplier": 1.5, "cursed_multiplier": 1.75},
            {"area": 4, "multiplier": 1.6, "cursed_multiplier": 2.0},
            {"area": 5, "multiplier": 1.75, "cursed_multiplier": 2.25},
        ],
    },
}

def _pin_entry(
    name: str,
    character: str,
    game_class: str,
    *,
    left: dict | None = None,
    right: dict | None = None,
    orchestration: str | None = None,
    wiki_page: str = "",
    wiki_effect: str = "",
) -> dict:
    """Pin catalog entry: left = grid track, right = scoring track (game UpgradeableComponents)."""
    entry: dict = {
        "name": name,
        "character": character,
        "game_class": game_class,
    }
    if wiki_page:
        entry["wiki_page"] = wiki_page
    if wiki_effect:
        entry["wiki_effect"] = wiki_effect
    if left:
        entry["left"] = left
    if right:
        entry["right"] = right
    if orchestration:
        entry["orchestration"] = orchestration
        entry["type"] = orchestration
    elif right and right.get("type"):
        entry["type"] = right["type"]
        entry.update({k: v for k, v in right.items() if k != "type"})
    return entry


def _pin_left_scatter(wiki_effect: str, *, timing: str = "grid", slug: str = "") -> dict:
    t = "scatter_start_encounter" if timing == "encounter" else "scatter_start_grid"
    out = {"type": t, "effect_class": "scatter", "wiki_effect": wiki_effect}
    if slug:
        out["grid_handler"] = slug
    return out


# Pin rules keyed by art slug (melmod extras.pin_effect).
TUNED_PINS: dict[str, dict] = {
    "abacus": _pin_entry(
        "Abacus",
        "hayley_bayles",
        "Abacus",
        left=_pin_left_scatter(
            "START OF GRID: Scatters unique numbers 1-5", slug="abacus"
        ),
        right={
            "type": "colored_number_tile_bonus",
            "value": 10,
            "value_per_right_upgrade": 10,
            "value_from_component": 1,
        },
        wiki_page="Abacus",
        wiki_effect="Coloured numbers get +N TILE SCORE",
    ),
    "milky_way": _pin_entry(
        "Milky Way",
        "nina_nix",
        "MilkyWay",
        left=_pin_left_scatter(
            "START OF GRID: Scatters VOID tiles; VOID tiles have a 10% chance to go SHINY",
            slug="milky_way",
        ),
        wiki_page="Milky_Way",
    ),
    "rainbow": _pin_entry(
        "Rainbow",
        "beans",
        "Rainbow",
        left=_pin_left_scatter(
            "START OF GRID: Scatters unusually coloured tile", slug="rainbow"
        ),
        right={
            "type": "unique_colour_word_bonus",
            "value": 5,
            "value_per_right_upgrade": 5,
            "value_from_component": 1,
        },
        wiki_page="Rainbow",
        wiki_effect="+5 WORD SCORE per unique tile colour used",
    ),
    "mahjong_red_dragon": _pin_entry(
        "Mahjong Red Dragon",
        "sandy_saguaro",
        "MahjongRedDragon",
        left=_pin_left_scatter(
            "START OF ENCOUNTER: Get red consumable tile(s)",
            timing="encounter",
            slug="mahjong_red_dragon",
        ),
        right={
            "type": "tile_multiply",
            "target": "consumable",
            "scale_by_pin_right": True,
            "factor_base": 2.0,
            "factor_per_pin_right": 1.0,
        },
        wiki_page="Mahjong_Red_Dragon",
        wiki_effect="Consumable tiles get ×N TILE SCORE (N = 2 + right upgrades)",
    ),
    "bucket": _pin_entry(
        "Bucket",
        "octacles",
        "Bucket",
        left=_pin_left_scatter(
            "START OF GRID: Scatters the tiles in your bucket", slug="bucket"
        ),
        wiki_page="Bucket",
    ),
    "random_access_memory": _pin_entry(
        "Random Access Memory",
        "nat_h4",
        "RandomAccessMemory",
        orchestration="pin_memory_replay",
        wiki_page="Random_Access_Memory",
        wiki_effect="Behaves as all items stored in pin memory",
    ),
    "rodman": _pin_entry(
        "Carp Streamers",
        "rodman",
        "CarpStreamers",
        left=_pin_left_scatter(
            "START OF GRID: Scatters 1 RED tile and 1 BLUE tile", slug="rodman"
        ),
        wiki_page="Carp_Streamers",
    ),
    "sam_gambit": _pin_entry(
        "Super 8",
        "sam_gambit",
        "SuperEight",
        left=_pin_left_scatter(
            "START OF GRID: Scatters film/chess items", slug="sam_gambit"
        ),
        right={
            "type": "chess_take_word_bonus",
            "value": 8,
            "value_per_right_upgrade": 8,
            "value_from_component": 1,
            "per_take_from_variable": True,
        },
        wiki_page="Super_8",
        wiki_effect="Takes give +N WORD SCORE",
    ),
    "bones_the_dog": _pin_entry(
        "Bicycle",
        "bones_the_dog",
        "Bicycle",
        left=_pin_left_scatter("START OF GRID: Scatters cards", slug="bones_the_dog"),
        right={
            "type": "cards_submitted_word_bonus",
            "value": 1,
            "value_per_right_upgrade": 1,
            "value_from_component": 1,
            "accumulator_field": "bicycle_word_score_bonus",
        },
        wiki_page="Bicycle",
        wiki_effect="Get +0 WORD SCORE, improved by 1 per submitted card",
    ),
    "cretaceous_meg": _pin_entry(
        "Wad of Cash",
        "cretaceous_meg",
        "WadOfCash",
        left=_pin_left_scatter("START OF GRID: Scatters currency", slug="cretaceous_meg"),
        right={
            "type": "add_tile_score",
            "target": "currency",
            "value": 10,
        },
        wiki_page="Wad_of_Cash",
        wiki_effect="Currencies get +10 TILE SCORE",
    ),
    "human_boy": _pin_entry(
        "Human Hands",
        "human_boy",
        "HumanHands",
        orchestration="human_hands_pin",
        wiki_page="Human_Hands",
        wiki_effect="Boost favourite sticker levels; replay favourite stamp scoring",
    ),
}

ALIASES: dict[str, dict[str, str]] = {
    "stickers": {
        "stickyplaster": "sticky_plaster",
        "sticky_plaster_sticker": "sticky_plaster",
        "voidflip": "void_flip",
        "redrider": "red_rider",
        "doublescore": "double_score",
        "longword": "long_word",
        "shinychain": "shiny_chain",
    },
    "stamps": {
        "beam_me_up": "beam_me_up",
        "pinata": "pi_ata",
    },
    "bosses": {
        "robo_eel_boss": "robo_eel",
        "bosseats": "robo_eel",
        "destroygrid": "robo_eel",
        "destroy_grid": "robo_eel",
        "robo_monkey_boss": "robo_monkey",
        "yeti": "yeti_crab",
        "bossneutralise": "yeti_crab",
        "discolourtiles": "yeti_crab",
        "discolour_tiles": "yeti_crab",
        "bosssmallwords": "wolf",
        "boss_small_words": "wolf",
        "five_letter_maximum": "wolf",
        "bosslongwords": "cobra",
        "boss_long_words": "cobra",
        "five_letter_minimum": "cobra",
        "bosslesspoints": "salamander",
        "bossmoney": "fox",
        "bossfox": "fox",
        "bigboss": "toothed_whale",
        "big_boss": "toothed_whale",
        "bossnegativemoney": "robo_monkey",
        "bossdino": "cretaceous_meg",
        "cretaceous_meg": "cretaceous_meg",
        "meg": "cretaceous_meg",
        "bossfewergrids": "badger",
        "fewergrids": "badger",
        "fewer_grids": "badger",
        "bosssmallgrid": "bat",
        "smallgrid": "bat",
        "4x4_grid": "bat",
        "bosssell": "hyena",
        "forcedsell": "hyena",
        "forced_sell": "hyena",
        "bossaddnumbers": "bison",
        "addnumbers": "bison",
        "add_numbers": "bison",
        "bossqs": "axolotl",
        "extraqs": "axolotl",
        "extra_qs": "axolotl",
        "bossvoids": "mole",
        "extra_voids": "mole",
        "extravoids": "mole",
    },
    "pins": {
        "abacus": "abacus",
        "hayley": "abacus",
        "hayley_bayles": "abacus",
        "milky_way": "milky_way",
        "nina": "milky_way",
        "nina_nix": "milky_way",
        "rainbow": "rainbow",
        "beans": "rainbow",
        "mahjong_red_dragon": "mahjong_red_dragon",
        "mahjong": "mahjong_red_dragon",
        "sandy_saguaro": "mahjong_red_dragon",
        "bucket": "bucket",
        "octacles": "bucket",
        "random_access_memory": "random_access_memory",
        "ram": "random_access_memory",
        "nat_h4": "random_access_memory",
        "rodman": "rodman",
        "carp_streamers": "rodman",
        "sam_gambit": "sam_gambit",
        "sam": "sam_gambit",
        "super_8": "sam_gambit",
        "bones": "bones_the_dog",
        "bones_the_dog": "bones_the_dog",
        "bicycle": "bones_the_dog",
        "cretaceous_meg": "cretaceous_meg",
        "meg": "cretaceous_meg",
        "wad_of_cash": "cretaceous_meg",
        "human_boy": "human_boy",
        "human_hands": "human_boy",
    },
}


def slugify_name(name: str) -> str:
    raw = (name or "").strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "_", raw).strip("_")
    return slug or "unknown"


def load_titles(filename: str) -> list[str]:
    path = WIKI_DIR / filename
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [
        m["title"]
        for m in data["query"]["categorymembers"]
        if not m["title"].startswith("Category:")
    ]


def catalog_entry(name: str, kind: str) -> dict:
    slug = slugify_name(name)
    return {
        "name": name,
        "type": "unmodeled",
        "description": f"Wiki catalog entry ({kind}); scoring not yet modeled",
    }


def build_bucket(
    titles: list[str],
    tuned: dict[str, dict],
    kind: str,
) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for title in sorted(titles, key=str.lower):
        slug = slugify_name(title)
        if slug in tuned:
            out[slug] = dict(tuned[slug])
            if "name" not in out[slug]:
                out[slug]["name"] = title
        else:
            out[slug] = catalog_entry(title, kind)
    for slug, rule in tuned.items():
        if slug not in out:
            out[slug] = dict(rule)
    return out


def classify_wiki_effect(text: str) -> dict:
    """Best-effort rule stub from wiki base-effect line."""
    upper = text.upper()
    if "START OF GRID" in upper or "START OF ENCOUNTER" in upper:
        return {"type": "custom", "wiki_effect": text, "effect_class": "scatter"}
    if "TILE SCORE" in upper and "×" in text:
        return {"type": "tile_multiply", "wiki_effect": text, "effect_class": "tile"}
    if "TILE SCORE" in upper and "+" in text:
        return {"type": "add_tile_score", "wiki_effect": text, "effect_class": "tile"}
    if "WORD SCORE" in upper and "×" in upper:
        return {"type": "multiply", "wiki_effect": text, "effect_class": "mult"}
    if "WORD SCORE" in upper and "+" in upper:
        return {"type": "add_word_score", "wiki_effect": text, "effect_class": "word"}
    return {"type": "unmodeled", "wiki_effect": text}


def build_pins(_char_titles: list[str]) -> dict[str, dict]:
    return dict(TUNED_PINS)


def main() -> int:
    sticker_titles = load_titles("_stickers_raw.json")
    stamp_titles = load_titles("_stamps_raw.json")
    char_titles = load_titles("_chars_raw.json")
    boss_titles = load_titles("_bosses_raw.json")

    existing: dict = {}
    if OUT_PATH.exists():
        existing = json.loads(OUT_PATH.read_text(encoding="utf-8"))

    stickers = dict(existing.get("stickers", {}))
    stickers.update(build_bucket(sticker_titles, TUNED_STICKERS, "sticker"))

    stamps = dict(existing.get("stamps", {}))
    stamps.update(build_bucket(stamp_titles, TUNED_STAMPS, "stamp"))
    enrich_stamps_catalog(stamps)

    stickers = dict(stickers)
    enrich_stickers_orchestration(stickers)

    bosses = build_bucket(boss_titles, TUNED_BOSSES, "boss")

    payload = {
        "_meta": {
            "source": "cursedwords.wiki.gg categories + hand-tuned overrides",
            "regenerate": "python scripts/build_stickers_json.py",
        },
        "aliases": ALIASES,
        "stickers": stickers,
        "stamps": stamps,
        "bosses": bosses,
        "pins": build_pins(char_titles),
    }

    OUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(
        f"Wrote {OUT_PATH.name}: "
        f"{len(payload['stickers'])} stickers, "
        f"{len(payload['stamps'])} stamps, "
        f"{len(payload['bosses'])} bosses, "
        f"{len(payload['pins'])} pins"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
