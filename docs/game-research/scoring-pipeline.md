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

- **RandomAccessMemory** — replays each item in memory as separate steps (trace shows RAM as `RelevantItem`). Under Hourglass, memory replay order is **reversed** (newest → oldest).
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
| Late bosses | Hourglass active | Single reversed `ApplyBossModifier` pass (all stacked bosses, e.g. Michael) |
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
| Capybara | `RandomiseItemOrder` on submit | `capybara_scoring.py` (permutation EV; not `build_scoring_item_sequence`) |

Fox: grid-start money loss (`fox_grid_steal`) is separate from submit-time `StealsMoney` (`boss_steal_money`).

## Wiki vs game

The [wiki Scoring](https://cursedwords.wiki.gg/wiki/Scoring) page separates pin, stickers, and stamps. In code they share one list (pin first, then stickers, then stamps) unless Hourglass reverses it. **Capybara** shuffles sticker/stamp arrays on submit via `Player.RandomiseItemOrder` (boss `RandomiseItemOrder` is separate).

**GREEN tiles (wiki step 6):** after the full item loop (stickers, stamps, bosses), GREEN path tile scores move into `word_score` via `scoring_order.apply_green_tile_word_transfer` at the end of `ScoringPipeline._compute_state`. Step-7 word multipliers in `_finalize` then apply to `tile_sum + word_score` (green is in the word bucket). Compound Cocktail sessions multiply **non-green** tile sum only during the mid-loop Cocktail pass; GREEN is excluded via `tile_sum_excluding_green`.

## Melmod validation

Harmony postfix on `CalculateOverallScore` captures `List<ScoreCalcVizInfo>` as `actual_trace` for mismatch regression (`tests/fixtures/mismatches/`).

## Solver implementation (Python)

How the Python solver maps the game pipeline above. Full search-side detail: [`../SEARCH_ARCHITECTURE.md`](../SEARCH_ARCHITECTURE.md).

### Item sequence

- `scoring_order.build_scoring_item_sequence` composes path scattered items + inventory refs from `SolveContext.inventory_refs`.
- **Capybara shuffle** is **not** applied in the sequence builder — `capybara_scoring.py` evaluates permutation EV/min/max, rebuilding a per-perm `SolveContext` for each order.
- Hourglass reversal is applied in `ScoringPipeline._compute_state` via `SolveContext.hourglass_reversed` and `sticker_slot_order` / `stamp_slot_order`.

### `_compute_state` flow

`ScoringPipeline._compute_state` receives cached `solve_context`, `graph_ctx`, and `board_scoring_ctx` from the search hot path.

1. Tile init (glitch, bases, currency, pink, poison) — unchanged from game order
2. Early/late bosses per Hourglass state
3. Inventory loop in slot order:
   - When `board_scoring_ctx.use_split_pipeline` is true, board-static rules run first via `apply_static_rule` (O(path)); debug traces may show `detail: "static tile_add"`
   - Dynamic/orchestration rules follow via `apply_*_with_orchestration` (Frankenstein, RAM, Overhand, scaled factors, etc.)
4. GREEN tile transfer and `_finalize` word multipliers

`blocks_split_pipeline()` disables the static fast path when Capybara, Compound Cocktail, Snapshot, Frankenstein, or RAM pin prevent safe interleaving.

### Grid scatter refs

Path scattered items are resolved via `path_grid_item_refs`, cached per path on `WordSearcher._grid_refs_cache` for the duration of a solve. Hourglass reversal of path items is applied inside `_compute_state`, not in the cache key.
