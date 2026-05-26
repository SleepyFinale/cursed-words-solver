# Tile.GetValue research notes

This document captures practical parity constraints from decompiled `Tile` usage in scoring.

## Where tile values enter scoring

- `ScoreCalculation.GetInitialScoreInfo` reads tile values before stickers/stamps.
- `ScoreCalculation.CalculateOverallScore` then layers bosses, item bonuses, and word bonuses.

Therefore, tile base parity is a prerequisite for all later score parity.

## Relevant tile state in decompiled Tile class

Key fields that influence value/behavior before item bonuses:

- `MyGlyphType` (`Letter`, `Number`, `Fraction`, `BespokeCard`, `Chess`, etc.)
- `CardSuit`
- `PieceType` / `IsWhitePiece`
- `MyTileType` (colour)
- `ValueModifier`
- `CactusGrowth`
- `WasGlitchTile`

## Practical solver parity checklist

1. Parse and preserve card/chess metadata from melmod board snapshots.
2. Keep glitch settlement before base-score init.
3. Apply shield/colour/base overrides during tile-init phase only (before item loop).
4. Keep pink/currency effects as separate pre-item steps.
5. Validate tile-init traces against `actual_trace` tile score arrays, not only final totals.

## Related files

- `cursed_words_solver/rules/tile_scoring.py`
- `cursed_words_solver/rules/base_scoring.py`
- `cursed_words_solver/rules/pipeline.py` (`apply_tile_init` call site)
