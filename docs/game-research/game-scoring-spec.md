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

- preserve step order and floor semantics for multiplicative word effects.
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

## Tile-value implications

`Tile.GetValue` feeds `GetInitialScoreInfo`; this is where shield/colour/chess/card base-value interactions begin before item effects.

## Solver mapping checkpoints

- Pipeline order: `cursed_words_solver/rules/pipeline.py`
- Item ordering and Hourglass: `cursed_words_solver/rules/scoring_order.py`
- Conditions/cards: `cursed_words_solver/rules/scoring_conditions.py`
- Replay fidelity: `tests/regression/test_scoring_mismatches.py`
