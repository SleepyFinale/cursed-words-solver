"""Achievement stamp TUNED_STAMPS entries (82). Merged into build_stickers_json.TUNED_STAMPS."""

from __future__ import annotations


def _grid_scatter(
    name: str,
    wiki_effect: str,
    wiki_page: str,
    *,
    grid_timing: str = "start",
) -> dict:
    entry = {
        "name": name,
        "type": "custom",
        "effect_class": "scatter",
        "grid_effect": wiki_effect,
        "wiki_effect": wiki_effect,
        "wiki_page": wiki_page,
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


ACHIEVEMENT_STAMPS: dict[str, dict] = {
    "akoya_pearl": _grid_scatter(
        "Akoya Pearl",
        "START OF GRID: If there is a central tile, it becomes SHINY",
        "Akoya_Pearl",
    )
    | {"shop_price": 12},
    "bank": _grid_scatter(
        "Bank",
        "START OF GRID: Convert letters to currencies where possible",
        "Bank",
    )
    | {"shop_price": 14},
    "bar_chart": _custom_effect(
        "Bar Chart",
        "Do nothing (Submit a number's name to improve this)",
        "meta",
        "Bar_Chart",
    )
    | {"shop_price": 10},
    "beam_me_up": _grid_scatter(
        "Beam Me Up",
        "START OF GRID: Scatters a copy of any consumable tile below this",
        "Beam_Me_Up",
    )
    | {"shop_price": 16},
    "beefeater": _grid_scatter(
        "Beefeater",
        "START OF GRID: Scatters a RED randomly suited J, Q and K",
        "Beefeater",
    )
    | {"shop_price": 15},
    "big_bang": _grid_scatter(
        "Big Bang",
        "If your word starts with a RED tile, scatters the word's length of RED tiles onto the next grid",
        "Big_Bang",
        grid_timing="on_submit",
    )
    | {"shop_price": 14},
    "black_hole": _grid_scatter(
        "Black Hole",
        "START OF GRID: Double the number of VOID tiles on the grid",
        "Black_Hole",
    )
    | {"shop_price": 18},
    "blessing_of_the_fairies": {
        "name": "Blessing of the Fairies",
        "type": "multiply_word_scaled",
        "condition": "always",
        "base": 1,
        "upgrade": 0,
        "scale_from_extras": "cursed_bosses_defeated_count",
        "scale_per_extra": 0.5,
        "wiki_effect": "Get ×1 WORD SCORE (+0.5 per cursed boss defeated this run)",
        "wiki_page": "Blessing_of_the_Fairies",
        "shop_price": 20,
    },
    "blessing_of_the_shopkeeper": _custom_effect(
        "Blessing Of The Shopkeeper",
        "Items in the shop cost $10",
        "shop",
        "Blessing_Of_The_Shopkeeper",
    )
    | {"shop_price": 35},
    "bomb": _grid_scatter(
        "Bomb",
        "START OF GRID: Scatters a patch of 3-7 VOID tiles",
        "Bomb",
    )
    | {"shop_price": 16},
    "book_of_openings": _custom_effect(
        "Book Of Openings",
        "Do nothing (Submit a chess piece name to improve this)",
        "meta",
        "Book_Of_Openings",
    )
    | {"shop_price": 12},
    "briefcase": _grid_scatter(
        "Briefcase",
        "START OF GRID: Scatters a generally helpful multiplier item for each empty Sticker slot",
        "Briefcase",
    )
    | {"shop_price": 18},
    "builder": {
        "name": "Builder",
        "type": "tile_multiply",
        "target": "consumable",
        "scale_by_consumable_count_on_path": True,
        "wiki_effect": "Consumable tiles get TILE SCORE × number of consumable tiles in the word",
        "wiki_page": "Builder",
        "shop_price": 16,
    },
    "bunch_of_grapes": _custom_effect(
        "Bunch Of Grapes",
        "START OF GRID: Scatters a 1, a 5 and a 10. 1s, 5s and 10s can be used as I, V and X respectively",
        "letter_behavior",
        "Bunch_Of_Grapes",
    )
    | {"shop_price": 14, "letter_behavior": "number_roman_ivx"},
    "cable_car": _custom_effect(
        "Cable Car",
        "Stickers in your word are upgraded when your word is submitted",
        "meta",
        "Cable_Car",
    )
    | {"shop_price": 18},
    "cartwheeler": {
        "name": "Cartwheeler",
        "type": "multiply_word_per_path_tile",
        "factor": -1.1,
        "wiki_effect": "For each tile in your word get ×-1.1 WORD SCORE",
        "wiki_page": "Cartwheeler",
        "shop_price": 15,
    },
    "chess_board": _grid_scatter(
        "Chess Board",
        "START OF GRID: Checkerboards the grid with VOID tiles and random non-VOID coloured tiles",
        "Chess_Board",
    )
    | {"shop_price": 16},
    "disco_ball": _custom_effect(
        "Disco Ball",
        "Your consumable tiles are SHINY",
        "consumable",
        "Disco_Ball",
    )
    | {"shop_price": 14},
    "diya": _custom_effect(
        "Diya",
        "Get 1 extra grid per encounter",
        "encounter",
        "Diya",
    )
    | {"shop_price": 20},
    "dove": {
        "name": "Dove",
        "type": "add_money_on_condition",
        "condition": "chess_balanced_colors",
        "amount_mode": "chess_piece_count_on_path",
        "wiki_effect": "If your word has the same number of black and white pieces, get $ equal to the number of chess pieces in the word",
        "wiki_page": "Dove",
        "shop_price": 18,
    },
    "dragon": _custom_effect(
        "Dragon",
        "END OF ENCOUNTER: Earn $1 interest for each $10",
        "encounter",
        "Dragon",
    )
    | {"shop_price": 22},
    "eclipse": _grid_scatter(
        "Eclipse",
        "START OF GRID: 1 E becomes SHINY, the rest become VOID",
        "Eclipse",
    )
    | {"shop_price": 16},
    "empty_jar": {
        "name": "Empty Jar",
        "type": "multiply_word_scaled",
        "condition": "money_eq:0",
        "base": 2,
        "upgrade": 0,
        "wiki_effect": "If you have $0, get ×2 WORD SCORE",
        "wiki_page": "Empty_Jar",
        "shop_price": 12,
    },
    "error": {
        "name": "Error",
        "type": "multiply",
        "factor": 1,
        "wiki_effect": "Get ×1 WORD SCORE. Using a GLITCH tile improves this by 1 but has a 10% chance to break the item",
        "wiki_page": "Error",
        "shop_price": 14,
    },
    "erupting_volcano": {
        "name": "Erupting Volcano",
        "type": "multiply",
        "factor": 1.5,
        "wiki_effect": "Get ×1.5 WORD SCORE. Items cannot be frozen",
        "wiki_page": "Erupting_Volcano",
        "shop_price": 18,
        "items_cannot_freeze": True,
    },
    "falling_leaf": _custom_effect(
        "Falling Leaf",
        "Consumable tiles cost $1",
        "shop",
        "Falling_Leaf",
    )
    | {"shop_price": 12},
    "fan": _custom_effect(
        "Fan",
        "SHINY tiles do not get rerolled",
        "shop",
        "Fan",
    )
    | {"shop_price": 10},
    "flashy_fountain_pen": _custom_effect(
        "Flashy Fountain Pen",
        "Do nothing (Submit a tile colour name to improve this)",
        "meta",
        "Flashy_Fountain_Pen",
    )
    | {"shop_price": 10},
    "fleur_de_lis": _grid_scatter(
        "Fleur De Lis",
        "START OF GRID: Convert all RED and BLUE tiles into PURPLE tiles",
        "Fleur_De_Lis",
    )
    | {"shop_price": 14},
    "food_poisoning": _grid_scatter(
        "Food Poisoning",
        "START OF GRID: Convert all cursed tiles into GREEN tiles",
        "Food_Poisoning",
    )
    | {"shop_price": 12},
    "fortune_cookie": _custom_effect(
        "Fortune Cookie",
        "Foil Stickers show up 5× more often",
        "shop",
        "Fortune_Cookie",
    )
    | {"shop_price": 16},
    "fraction_frog": _grid_scatter(
        "Fraction Frog",
        "START OF GRID: Get a fraction consumable tile equal to previous WORD SCORE / target",
        "Fraction_Frog",
    )
    | {"shop_price": 18},
    "fried_shrimp": _custom_effect(
        "Fried Shrimp",
        "Restocking the shop costs $1 less",
        "shop",
        "Fried_Shrimp",
    )
    | {"shop_price": 12},
    "genie": _custom_effect(
        "Genie",
        "Rare and Legendary items are 3× as likely to appear in the shop",
        "shop",
        "Genie",
    )
    | {"shop_price": 25},
    "giraffe": {
        "name": "Giraffe",
        "type": "tile_multiply",
        "target": "number",
        "scale_by_path_position": True,
        "wiki_effect": "Numbers get TILE SCORE × position in word",
        "wiki_page": "Giraffe",
        "shop_price": 16,
    },
    "globe_trotter": _grid_scatter(
        "Globe Trotter",
        "START OF GRID: Convert corner tiles into currencies and give them +10 BASE SCORE",
        "Globe_Trotter",
    )
    | {"shop_price": 18},
    "haunted_house": _grid_scatter(
        "Haunted House",
        "START OF GRID: Scatters a cursed Full House",
        "Haunted_House",
    )
    | {"shop_price": 20},
    "head_in_the_clouds": {
        "name": "Head In The Clouds",
        "type": "multiply_word_scaled",
        "condition": "path_all_non_adjacent",
        "base": 1.5,
        "upgrade": 0,
        "wiki_effect": "START OF GRID: Scatters 2 WHITE tiles. Get ×1.5 WORD SCORE if your word contains no adjacent moves",
        "wiki_page": "Head_In_The_Clouds",
        "grid_effect": "START OF GRID: Scatters 2 WHITE tiles",
        "shop_price": 16,
    },
    "heart_on_fire": {
        "name": "Heart On Fire",
        "type": "multiply_word_by_longest_red_run",
        "wiki_effect": "Get WORD SCORE × longest consecutive run of RED tiles",
        "wiki_page": "Heart_On_Fire",
        "shop_price": 18,
    },
    "hourglass": {
        "name": "Hourglass",
        "type": "reverse_scoring_order",
        "effect_class": "meta",
        "game_class": "Hourglass",
        "wiki_effect": "Items and boss effects trigger backwards",
        "wiki_page": "Hourglass",
        "shop_price": 20,
    },
    "id_card": _custom_effect(
        "ID Card",
        "You can upgrade both sides of your pin after boss encounters",
        "meta",
        "ID_Card",
    )
    | {"shop_price": 22},
    "jellyfish": _custom_effect(
        "Jellyfish",
        "START OF GRID: Js become SHINY. They can behave as an H or a Y",
        "letter_behavior",
        "Jellyfish",
    )
    | {"shop_price": 14, "letter_behavior": "j_as_h_or_y"},
    "jolly_roger": _custom_effect(
        "Jolly Roger",
        "Get the first taken chess piece in your word as a consumable tile",
        "consumable",
        "Jolly_Roger",
    )
    | {"shop_price": 16},
    "king_of_the_bridge": _custom_effect(
        "King Of The Bridge",
        "Chess pieces can take their allies",
        "movement",
        "King_Of_The_Bridge",
    )
    | {"shop_price": 14, "letter_behavior": "chess_allies_can_take"},
    "kokeshi_dolls": {
        "name": "Kokeshi Dolls",
        "type": "add_money_on_condition",
        "condition": "currency_on_path",
        "amount_mode": "currency_value_on_path",
        "wiki_effect": "Currency tiles give $ equal to their letter value",
        "wiki_page": "Kokeshi_Dolls",
        "shop_price": 14,
    },
    "magnet": _grid_scatter(
        "Magnet",
        "Scattered numbers huddle together",
        "Magnet",
    )
    | {"shop_price": 12},
    "microphone": _custom_effect(
        "Microphone",
        "Submit the name of an item to get it",
        "meta",
        "Microphone",
    )
    | {"shop_price": 18},
    "mushroom_upgrade": _grid_scatter(
        "Mushroom Upgrade",
        "START OF ENCOUNTER: Scatters 0 RED tiles onto the grid (Use 5 more RED tiles to improve)",
        "Mushroom_Upgrade",
    )
    | {"shop_price": 12},
    "mutating_dna": _custom_effect(
        "Mutating DNA",
        "Each time you use a letter, tiles with that letter get +1 TILE SCORE whilst you have this item",
        "meta",
        "Mutating_DNA",
    )
    | {"shop_price": 18, "type": "mutating_dna_tile_bonus"},
    "neapolitan": {
        "name": "Neapolitan",
        "type": "multiply_word_scaled",
        "condition": "unique_colours_gte:3",
        "base": 1,
        "upgrade": 0,
        "wiki_effect": "Get ×1 WORD SCORE (Submit a word with 3 or more unique colours to improve)",
        "wiki_page": "Neapolitan",
        "shop_price": 14,
    },
    "number_factory": _grid_scatter(
        "Number Factory",
        "START OF GRID: Get the grid number as a consumable tile",
        "Number_Factory",
    )
    | {"shop_price": 16},
    "ogre": _custom_effect(
        "Ogre",
        "Curse all bosses, they give double reward money",
        "meta",
        "Ogre",
    )
    | {"shop_price": 25},
    "piece_of_cake": _custom_effect(
        "Piece of Cake",
        "50% chance to not consume a tile on use",
        "meta",
        "Piece_Of_Cake",
    )
    | {"shop_price": 14},
    "piggy_bank": {
        "name": "Piggy Bank",
        "type": "multiply_word_scaled",
        "condition": "always",
        "base": 1,
        "upgrade": 0,
        "scale_from_extras": "money_lost_encounter",
        "scale_per_extra": 0.01,
        "wiki_effect": "START OF GRID: Scatters 2 PINK tiles. Get ×1 WORD SCORE. Improved by 0.01 each time you lose $",
        "wiki_page": "Piggy_Bank",
        "grid_effect": "START OF GRID: Scatters 2 PINK tiles",
        "shop_price": 16,
    },
    "pizza_slice": _grid_scatter(
        "Pizza Slice",
        "START OF GRID: Convert your numbers into random fractions",
        "Pizza_Slice",
    )
    | {"shop_price": 14},
    "pocket_money": _custom_effect(
        "Pocket Money",
        "Get $ equal to the first number in the word submitted on the first grid of each encounter",
        "encounter",
        "Pocket_Money",
    )
    | {"shop_price": 12},
    "receipt": _custom_effect(
        "Receipt",
        "Your other items sell for their full purchase price",
        "shop",
        "Receipt",
    )
    | {"shop_price": 16},
    "red_balloon": _grid_scatter(
        "Red Balloon",
        "START OF GRID: Scatters a RED 99",
        "Red_Balloon",
    )
    | {"shop_price": 14},
    "rollercoaster": _custom_effect(
        "Rollercoaster",
        "10% chance to upgrade a Sticker when you reroll the grid or restock the shop",
        "shop",
        "Rollercoaster",
    )
    | {"shop_price": 18},
    "saguaro_seedling": _grid_scatter(
        "Saguaro Seedling",
        "START OF GRID: Scatters 2 CACTUS tiles. CACTUS tiles grow twice as fast as normal",
        "Saguaro_Seedling",
    )
    | {"shop_price": 14},
    "sewing_needle": _custom_effect(
        "Sewing Needle",
        "Sell to stitch two stickers together",
        "sell",
        "Sewing_Needle",
    )
    | {"shop_price": 16},
    "shaved_ice": {
        "name": "Shaved Ice",
        "type": "multiply_word_scaled",
        "condition": "always",
        "base": 1,
        "upgrade": 0,
        "scale_from_extras": "shaved_ice_freezes",
        "scale_per_extra": 0.2,
        "wiki_effect": "Get ×1 WORD SCORE (While frozen, improved by 0.2 for each shop visited)",
        "wiki_page": "Shaved_Ice",
        "shop_price": 12,
    },
    "silly_puppy": {
        "name": "Silly Puppy",
        "type": "multiply_word_scaled",
        "condition": "always",
        "base": 1,
        "upgrade": 0,
        "scale_from_extras": "animal_stamp_count",
        "wiki_effect": "Get ×1 WORD SCORE (Increased by your other animals)",
        "wiki_page": "Silly_Puppy",
        "shop_price": 14,
    },
    "snail": _custom_effect(
        "Snail",
        "Rare and Legendary items are ×1 as likely to appear in the shop. Improved each time you restock the shop",
        "shop",
        "Snail",
    )
    | {"shop_price": 14},
    "spouting_whale": _grid_scatter(
        "Spouting Whale",
        "START OF GRID: Get a BLUE ? consumable tile",
        "Spouting_Whale",
    )
    | {"shop_price": 12},
    "stack_of_pancakes": _custom_effect(
        "Stack Of Pancakes",
        "Stickers can be upgraded 1 additional time",
        "meta",
        "Stack_Of_Pancakes",
    )
    | {"shop_price": 18},
    "stadium": _custom_effect(
        "Stadium",
        "You can have up to 10 consumable tiles",
        "meta",
        "Stadium",
    )
    | {"shop_price": 16},
    "statue_of_liberty": _grid_scatter(
        "Statue Of Liberty",
        "START OF GRID: Scatters BLUE tiles or ?s until there are the same number of both",
        "Statue_Of_Liberty",
    )
    | {"shop_price": 16},
    "stethoscope": _grid_scatter(
        "Stethoscope",
        "START OF GRID: Convert a single-digit number into a Sticker of that level from the number pool",
        "Stethoscope",
    )
    | {"shop_price": 18},
    "stiletto": {
        "name": "Stiletto",
        "type": "tile_multiply",
        "target": "red",
        "scale_from_extras": "grid_number_half",
        "wiki_effect": "RED tiles get TILE SCORE × half of grid number",
        "wiki_page": "Stiletto",
        "shop_price": 16,
    },
    "supervillain": _grid_scatter(
        "Supervillain",
        "START OF GRID: Scatters a cursed tile of each type that isn't on the grid",
        "Supervillain",
    )
    | {"shop_price": 20},
    "surprise_delivery": _custom_effect(
        "Surprise Delivery",
        "When you leave the shop get a random common Sticker",
        "shop",
        "Surprise_Delivery",
    )
    | {"shop_price": 14},
    "suspension_bridge": _custom_effect(
        "Suspension Bridge",
        "RED letters can behave as a letter one earlier or later in the alphabet",
        "letter_behavior",
        "Suspension_Bridge",
    )
    | {"shop_price": 14, "letter_behavior": "red_letter_plus_minus_one"},
    "takeout_box": _custom_effect(
        "Takeout Box",
        "START OF ENCOUNTER: Removes all your consumable tiles and gives you $1 for each tile removed",
        "encounter",
        "Takeout_Box",
    )
    | {"shop_price": 12},
    "television": _custom_effect(
        "Television",
        "START OF GRID: Scatters an item from the chess pool. King and Queen can always move to any item",
        "movement",
        "Television",
    )
    | {"shop_price": 18, "letter_behavior": "chess_king_queen_item_movement"},
    "torii_gate": _custom_effect(
        "Torii Gate",
        "START OF ENCOUNTER: The left and right edges of the grid become RED",
        "encounter",
        "Torii_Gate",
    )
    | {"shop_price": 14},
    "trophy_of_wealth": _grid_scatter(
        "Trophy Of Wealth",
        "START OF GRID: Scatters 0 GOLD tiles (One for each $15 you have)",
        "Trophy_Of_Wealth",
    )
    | {"shop_price": 18},
    "twinkle_toes": _custom_effect(
        "Twinkle Toes",
        "After a grid is generated, choose a pair of tiles to swap positions",
        "tile_swap",
        "Twinkle_Toes",
    )
    | {"shop_price": 16},
    "underhand": _custom_effect(
        "Underhand",
        "Levels up the Sticker above this 3 times",
        "meta",
        "Underhand",
    )
    | {"shop_price": 20},
    "unicorn": _custom_effect(
        "Unicorn",
        "Sell to make one of your Stickers foil",
        "sell",
        "Unicorn",
    )
    | {"shop_price": 22},
    "wheel": _custom_effect(
        "Wheel",
        "Grid rerolls cost $1. +3 rerolls per encounter",
        "shop",
        "Wheel",
    )
    | {"shop_price": 14},
    "work_of_art": _grid_scatter(
        "Work of Art",
        "START OF GRID: Colour your tiles according to their suits",
        "Work_of_Art",
    )
    | {"shop_price": 16},
}

assert len(ACHIEVEMENT_STAMPS) == 82
