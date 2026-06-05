# In-game scoring pipeline

Source: decompiled `ScoreCalculation.CalculateOverallScore` and `EncounterController.GetItemsForWordSubmission`.

## Item order for a submitted word

`GetItemsForWordSubmission(selections, includeInventory: true)`:

1. **Path order** — each selected tile with `GlyphType.ScatteredItem` adds `tile.ScatteredItem` to the list.
2. **Inventory** — `Player.GetAllItems()`:
   - Character pin item (`MyCharacter.GetCharacterItem()`)
   - All stickers (array order, left → right)
   - All stamps (array order, left → right)

`CalculateOverallScore` then iterates that list. If the player has an odd count of **Hourglass** stamps, the list is **reversed** before the loop (stickers/stamps/pin order flip; path scattered items reverse too).

Special cases in the item loop:

- **RandomAccessMemory** — replays each item in memory as separate steps (trace shows RAM as `RelevantItem`).
- **Frankenstein** — applies each stitched sticker in order.
- **Human Hands** favourite — extra applications of favourite stamp (level − 1 times).
- **Overhand** — extra applications of target sticker (Overhand level times).

## `CalculateOverallScore` step sequence

| Step | Condition | Game method |
| ---- | ----------- | ------------- |
| Glitch settle | Path has glitch tiles | `SettleGlitchTiles` |
| Init tile values | Always | `GetInitialScoreInfo` (uses `Tile.GetValue()`) |
| Early bosses | No Hourglass | `ApplyBossModifier` per boss |
| Poker in word | Bones challenge + suited tiles | `CalculatePokerHand` |
| Currency tiles | Path has currency glyph | `GetMoneyFromCurrencyTiles` |
| Pink piggy bank | Path has pink tiles | `StoreMoneyInPinkTiles` |
| Apply items | Hourglass may reverse order | `Item.ApplyItemToScore` each |
| Late bosses | Hourglass active | Reversed boss list |
| Lexographer | Challenge | `ApplyLexographer` |
| Poison | Previous words with green tiles | `ApplyPoisonEffect` |

Final score: `GetScoreFromScoreCalcInfo` — sum of **last step** tile scores, then add/multiply each step’s `WordBonus` (multiplicative bonuses divide by 100).

## Tile init (before items)

| Step | Game method | Solver (`tile_scoring.py`) |
| ---- | ------------- | --------------------------- |
| Glitch settle | `SettleGlitchTiles` | `settle_glitch_tiles` — deterministic when colour still `glitch` |
| Init tile values | `GetInitialScoreInfo` / `Tile.GetValue` | `_init_state` + `initial_tile_scores` |
| Currency money | `GetMoneyFromCurrencyTiles` | `currency_money_from_path` → `money_bonus` |
| Pink piggy bank | `StoreMoneyInPinkTiles` | `pink_store_money` — −$1 per pink while money > 0 |
| Poison (later words) | `ApplyPoisonEffect` | `poison_from_previous_words` — from `extras.green_poison_bonus` |

Cactus ([wiki Tiles — CACTUS](https://cursedwords.wiki.gg/wiki/Tiles)): grid tiles gain +1 BASE SCORE at each grid start. Melmod `base_score` is the post-growth packet (`GetValue`); do not add `cactus_growth` metadata again. `apply_cactus_grid_growth` runs only for OCR/simulated boards (not `board_from_melmod`). [Sandy Saguaro](https://cursedwords.wiki.gg/wiki/Sandy_Saguaro_(boss)) consumables placed mid-round use rack/board `base_score` as-is and skip grid growth. Purple: `IsTileType(Red|Blue)` via `tile_counts_as_color`.

## Boss modifiers

| Timing | Game | Solver |
| ------ | ---- | ------ |
| Early (no Hourglass) | `ApplyBossModifier` each boss | `boss_scoring.apply_early_boss_scoring` — Salamander, Robo-Monkey, Fox steal |
| Late (Hourglass) | Reversed boss list after items | `_apply_late_boss_rules` + trace `boss_late` |
| Grid start | Fox per-grid steal, Axolotl/Mole/etc. | `boss_grid_effects.apply_boss_grid_mutations` |
| Capybara | `RandomiseItemOrder` on submit | `scoring_order._maybe_shuffled_loadout` |

Fox: grid-start money loss (`fox_grid_steal`) is separate from submit-time `StealsMoney` (`boss_steal_money`).

## Wiki vs game

The [wiki Scoring](https://cursedwords.wiki.gg/wiki/Scoring) page separates pin, stickers, and stamps. In code they share one list (pin first, then stickers, then stamps) unless Hourglass reverses it. **Capybara** shuffles sticker/stamp arrays on submit via `Player.RandomiseItemOrder` (boss `RandomiseItemOrder` is separate).

**GREEN tiles:** tile scores from green tiles are folded into word score at finalize (solver: `scoring_order.apply_green_tile_word_transfer`).

## Melmod validation

Harmony postfix on `CalculateOverallScore` captures `List<ScoreCalcVizInfo>` as `actual_trace` for mismatch regression (`tests/fixtures/mismatches/`).
