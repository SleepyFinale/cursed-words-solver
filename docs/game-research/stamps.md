# Stamps (game research)

Source: decompiled `Item` subclasses in `Assembly-CSharp.dll`. Stamps are `Item` with **zero** `UpgradeableComponents` ([`Item.IsStamp()`](docs/game-research/_decompiled/Item.decompiled.cs)); stickers have one, pins have two.

Wiki: [List of stamps](https://cursedwords.wiki.gg/wiki/List_of_stamps), [Scoring](https://cursedwords.wiki.gg/wiki/Scoring)

## Inventory order

`Player.GetAllItems()` for word scoring: **pin** → **stickers** (slot order) → **stamps** (slot order). Hourglass (odd count) reverses the combined list before `CalculateOverallScore` loops items.

Capybara / `RandomiseItemOrder` shuffles sticker and stamp arrays on submit (see `Player.RandomiseItemOrder`).

## Per-item loop specials (not plain stamps)

These run inside `ScoreCalculation.CalculateOverallScore` after each `ApplyItemToScore`:

| Mechanism | Kind | Behavior |
| ----------- | ---- | ---------- |
| Random Access Memory | Pin | Replays `ItemsInMemory` |
| Frankenstein | Sticker | Replays each `StitchedItems` sticker |
| Human Hands | Pin | Favourite stamp scored `right.VariableValue - 1` extra times |
| Overhand | Sticker | Target sticker scored `Overhand.VariableValue` extra times |

**Cable Car** (stamp) is **not** in the item scoring loop. In `EncounterController.SubmitWord`, **before** `CalculateOverallScore`, each owned `CableCar` upgrades every on-path sticker (`GetItemsForWordSubmission(..., inventory: false)` where `IsSticker()`) via `Upgrade(0)`. Solver: [`cable_car_stamp_count`](cursed_words_solver/rules/scoring_conditions.py) + bump in [`grid_path_sticker_level`](cursed_words_solver/rules/scoring_conditions.py). Melmod exports scattered sticker **Level** from `UpgradeableComponents[0].Level` (not `VariableValue`).

## Stamp categories (solver)

| Category | Catalog signal | Solver |
| -------- | ---------------- | -------- |
| Word/tile score | `type` ∈ scored taxonomy | [`pipeline._apply_rule`](cursed_words_solver/rules/pipeline.py) |
| Grid scatter | `scatter_start_grid` / `effect_class: scatter` | [`grid_effects`](cursed_words_solver/rules/grid_effects.py) |
| Movement / letters | `effect_class: movement` + `search_flags` | [`stamp_behaviors`](cursed_words_solver/rules/stamp_behaviors.py), [`search.py`](cursed_words_solver/search.py) |
| Shop / encounter | `effect_class: shop` / `encounter` | No score; counted as non-scoring in [`rule_lookup`](cursed_words_solver/rules/rule_lookup.py) |
| Meta scoring | `reverse_scoring_order` (Hourglass) | [`scoring_order.hourglass_reverses_order`](cursed_words_solver/rules/scoring_order.py) |

## Orchestration stamps (high priority)

| Slug | Game class | Notes |
| ---- | ---------- | ----- |
| `hourglass` | `Hourglass` | Odd count reverses item order |
| `cable_car` | `CableCar` | Upgrades on-path stickers once per copy before score |
| `mutating_dna` / similar | Mutating DNA | Historic letter counts → tile/word bonus; melmod `mutating_dna_letter_counts` |
| `bento_box` | `BentoBox` | ×WORD if word starts with same letter as previous; `previous_word_first_letter` extra |
| `newspaper` | `Newspaper` | Often paired with word-history conditions |

## Movement stamps (`search_flags`)

| Slug | Flag |
| ---- | ---- |
| `hungry_snake` | `horizontal_wrap` |
| `full_moon` | `double_letter_teleport` |
| `queenie` | `q_as_qu` |
| `red_envelope` | `red_as_e` |
| `sluggish_zombie` | `z_as_s` |
| `flamingo` | `shiny_as_one` |
| `test_tube` | `number_plus_minus_one` |
| `card_shark` | `card_suit_first_letter` |
| `spicy_pepper` | `red_as_s` |
| `number_go_up` | `number_ascending_free_position` |
| `honeypot` | `word_stitch` |
| `bunch_of_grapes` | `number_roman_ivx` |
| `jellyfish` | `j_as_h_or_y` |
| `suspension_bridge` | `red_letter_plus_minus_one` |
| `king_of_the_bridge` | `chess_allies_can_take` |
| `television` | `chess_king_queen_item_movement` |

## Melmod extras (stamps)

| Extra | Stamps |
| ------- | -------- |
| `previous_word_first_letter` | Bento Box, Limnophila, Chips, … |
| `hourglass_count` | Hourglass |
| `capybara_shuffle` | Capybara sticker (shuffle flag) |
| `mutating_dna_letter_counts` | Mutating DNA |
| `stitched_sticker_ids` | Frankenstein (solver) |
| `overhand_target_sticker_id`, `overhand_level` | Overhand |

Regenerate audit: `python scripts/generate_stamp_audit.py`  
Extract game classes: `python scripts/extract_stamp_types.py`
