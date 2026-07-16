# Game scoring spec (decompiled truth)

Source of truth: decompiled `Assembly-CSharp.dll` (`ScoreCalculation`, `EncounterController`, `Item`, `PokerHands`, `Hanafuda`, `Tile`).

## End-to-end submit scoring flow

`ScoreCalculation.CalculateOverallScore(...)` builds `List<ScoreCalcVizInfo>` in this order:

1. `SettleGlitchTiles` if any selected tile is glitch.
2. `GetInitialScoreInfo` always.
3. Early bosses (`ApplyBossModifier`) when Hourglass is not active.
4. Bones poker-in-word step (`CalculatePokerHand`) when suited tiles exist.
5. Currency money (`GetMoneyFromCurrencyTiles`) when path contains currency glyph.
6. Pink bank storage (`StoreMoneyInPinkTiles`) when path contains pink tiles.
7. Item loop (`Item.ApplyItemToScore`) over `GetItemsForWordSubmission` list; reverse list when Hourglass odd count.
8. Late bosses (reverse boss list) when Hourglass is active.
9. Lexographer (`ApplyLexographer`) if challenge active.
10. Poison (`ApplyPoisonEffect`) from previous words.

## Item list construction

`EncounterController.GetItemsForWordSubmission(...)` order:

1. Scattered items on path tiles (`GlyphType.ScatteredItem`) in path order.
2. Player inventory list: pin, stickers (L→R), stamps (L→R).
3. Hourglass odd count reverses the whole list before application.

Special orchestration inside the item loop:

- `RandomAccessMemory`: replays each memory item as its own step.
- `Frankenstein`: applies each stitched item.
- Human Hands favorite: repeats target stamp `level-1` extra times.
- `Overhand`: replays target item `Overhand level` extra times.

## Cable Car (pre-score upgrade)

`EncounterController.SubmitWord` upgrades path stickers **before** scoring:

```csharp
int count = player.GetUnpackedItemsOfType(typeof(CableCar)).Count;
foreach CableCar (count times):
  foreach path sticker (GetItemsForWordSubmission(tiles, inventory: false)):
    item.Upgrade(0);  // Level++; VariableValue += increment
```

Then `CalculateOverallScore` runs with the upgraded `VariableValue`. Solver adds `cable_car_stamp_count(loadout)` inside `grid_path_sticker_level` for on-path scatters. Melmod must export `UpgradeableComponents[0].Level` on scattered items (`GetItemStickerLevel`), not reflection on the Item itself.

## Base item scoring contract

`Item.ApplyItemToScore`:

1. Clone previous step via `ScoreCalculation.GetNextStep`.
2. Apply `ApplyTileBonus` for each path tile index.
3. Apply `ApplyWordBonus` once.
4. Mark `RelevantItem` if any tile score changed or `WordBonus` exists.

This is exactly what solver `_apply_rule` must emulate.

## Final score reduction

`ScoreCalculation.GetScoreFromScoreCalcInfo(steps)`:

1. Start from `sum(last_step.TileScores)`.
2. Iterate each step in order:
   - skip when `WordBonus` is null.
   - if conditional bonus and condition is unmet, skip.
   - multiplicative: `score *= bonus; score /= 100` (integer packet math).
   - additive: `score += bonus`.

Solver parity requirement:

- preserve step order and toward-zero integer packet math for multiplicative word effects (`score *= bonus; score /= 100` as C# long division).
- use post-item tile scores (last step), not initial tile scores.

## Card-specific rules extracted

- `Hanafuda.ApplyWordBonus`:
  - hand from `PokerHands.GetXOfAKind(x, tiles)` where x is 2/3/4 by level.
  - unused cards are `gridData.GetAvailableTiles()` where `tile.CardSuit != 0 && !tiles.Contains(tile)`.
  - word bonus is `unused_count * sticker_value`.
- `Bicycle.ApplyWordBonus`:
  - increments `WordScoreBonus` by per-card value for each path tile with `CardSuit != 0`.
  - emits additive word bonus = current accumulator.
- `Wrestlers.ApplyWordBonus`:
  - checks path endpoint tiles and multiplies when both suits exist and differ, or start suit is joker.

## Movie Camera (`MovieCamera.ApplyWordBonus`)

- Counts path tiles in order where `TileSelection.SelectionMethod` is `ChessTake` or `EnPassant` (Full Moon chains and plain `ChessMove` landings do **not** count).
- For the first `VariableValue` (= sticker level) qualifying takes, adds `Alphabet.GetChessValue(tiles[i].PieceType)` to the item’s persistent `WordScoreBonus` field (P=1, N/B=3, R=5, Q=9, K=15).
- Emits an additive `WordBonusToken(WordScoreBonus)` using the **encounter running total** on the sticker instance (same accumulator pattern as Bicycle), not just this word’s increment.
- Solver: use melmod `movie_camera_word_score_bonus` when exported post-score; otherwise `sum(historic chess_take_value) + first-N takes on current path`.

## Telescope (`Telescope.ApplyTileBonus`)

Decompiled from `Assembly-CSharp.dll` (game v0.2.0):

```csharp
// collection = RED tiles in tiles[0..index]
// list = collection + RED tiles from each HistoricWord in previousWords
step.TileScores[index] += level * list.Count;
```

- Only applies on RED path tiles.
- Per path index `i` that is red: `bonus = level × list.Count`, where `list` is every RED tile in `tiles[0..i]` plus every RED tile from each `HistoricWord.Tiles` in the encounter.
- **No gap/separator bonus** in game code — non-red tiles between reds on the path do not add extra count.
- Solver legacy: when `historic_words` is empty, some captures still needed a gap bonus on non-telescope reds separated by ≥3 non-red steps; the scattered Telescope item tile itself never receives that bonus (see `telescope_running_red_count` in `scoring_conditions.py`).
- The multiplier increases for each red tile played on the path (3rd red on path with 2 prior encounter reds → `level × 3`).
- Does not reset across Michael boss phases (encounter-wide historic list).
- Solver: `telescope_running_red_count()` = `encounter_red_tiles_before_current_word()` + prefix reds on path; melmod should export per-word `red_tile_count` and `chess_take_value` on historic entries.

## Tile-value implications

`Tile.GetValue` feeds `GetInitialScoreInfo`; this is where shield/colour/chess/card base-value interactions begin before item effects.

## Solver mapping checkpoints

- Pipeline order: `cursed_words_solver/rules/pipeline.py`
- Item ordering and Hourglass: `cursed_words_solver/rules/scoring_order.py`
- Conditions/cards: `cursed_words_solver/rules/scoring_conditions.py`
- Replay fidelity: `tests/regression/test_scoring_mismatches.py`
