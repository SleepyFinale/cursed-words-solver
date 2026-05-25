# Effect taxonomy (game → catalog JSON)

## `ItemFunction` (game enum)

| Value | Role |
|-------|------|
| `Build` | Grid / encounter setup |
| `Scoring` | Word submit |
| `Additive` | +tile / +word |
| `Multiplier` | ×word / ×tile |
| `Scatterer` | `ApplyStartOfGridEffect` |
| `Other` | Meta / shop |
| `Tile` | Consumable tiles |

## Catalog `type` field (solver)

| `type` | Game hook | Notes |
|--------|-----------|-------|
| `add_tile_score` | `ApplyTileBonus` | Per-path-index |
| `add_word_score` | `ApplyWordBonus` | Many `word_mode`s |
| `multiply_word_scaled` | `WordBonusToken` multiplicative | Queued or immediate |
| `tile_multiply` | `TileScoreMultiplier` | |
| `scatter_start_grid` | `ApplyStartOfGridEffect` | Was `custom` + `scatter` |
| `scatter_start_encounter` | `StartOfEncounterSetUp` + grid | |
| `reverse_scoring_order` | Hourglass | Odd count reverses item + boss order |
| `shuffle_loadout_order` | Capybara / `RandomiseItemOrder` | Submit-time shuffle |
| `blue_tile_base_override` | Shield in `Tile.GetValue` | Init only |
| `meta` | Shop / sell price | No score |

## `search_flags` (catalog, stamps/stickers)

Boolean keys consumed by `stamp_behaviors.flags_from_catalog()`:

| Flag | Game item (examples) |
|------|----------------------|
| `horizontal_wrap` | Hungry Snake |
| `double_letter_teleport` | Full Moon |
| `q_as_qu` | Queenie |
| `red_as_e` | Red Envelope |
| `z_as_s` | Sluggish Zombie |
| `shiny_as_one` | Flamingo |
| `number_plus_minus_one` | Test Tube |
| `card_suit_first_letter` | Card Shark |
| `red_as_s` | Spicy Pepper |
| `number_ascending_free_position` | Number Go Up |
| `word_stitch` | Honeypot |
| `number_roman_ivx` | Bunch of Grapes |
| `j_as_h_or_y` | Jellyfish |
| `red_letter_plus_minus_one` | Suspension Bridge |
| `chess_allies_can_take` | King of the Bridge |
| `chess_king_queen_item_movement` | Television |

## `game_class` field

Optional PascalCase `Item` subclass name from `Assembly-CSharp` (e.g. `AprilShower`, `Blueberries`) for audit scripts. Generated list: `data/game/item_subclasses.json`.
