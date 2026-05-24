# Game scoring hooks (Assembly-CSharp)

Discovered via reflection on `Cursed Words_Data\Managed\Assembly-CSharp.dll` (Mono / MelonLoader net35).

## Primary entry points

| Type | Method | Role |
|------|--------|------|
| `EncounterController` | `SubmitWord(List<TileSelection> tiles, List<string> words)` | Encounter word submit |
| `PuzzleController` | `SubmitWord(List<TileSelection> tiles)` | Michael / puzzle submit |

Harmony prefix parameter names must match the game (`tiles`, not `selections`).
| `TileSelectionManager` | `SelectionSubmittedCallback()` | UI → calls encounter submit |
| `ScoreCalculation` | `CalculateOverallScore(...)` | Builds `List<ScoreCalcVizInfo>` scoring steps |
| `ScoreCalculation` | `GetScoreFromScoreCalcInfo(List<ScoreCalcVizInfo>)` | Final `ScorePacket` from steps |
| `EncounterController` | `DisplayScoreSteps(List<ScoreCalcVizInfo>, HistoricWord, List<ScoreCalcVizInfo>)` | UI animation of steps |

## Scoring pipeline (in-game)

1. Player selects tiles → `TileSelectionManager` holds `List<TileSelection>`.
2. Submit → `EncounterController.SubmitWord(selections, words)`.
3. Inside submit flow, `ScoreCalculation.CalculateOverallScore` runs with:
   - `List<TileSelection> tileSelections`
   - `List<string> words`
   - `List<Item> stickers/stamps` (inventory)
   - `List<HistoricWord> previousWords`
   - `List<BossModifier> bossModifiers`
   - `GridData grid`
   - `int gridNumber`
4. Returns **`List<ScoreCalcVizInfo>`** — one entry per visual/scoring step (companion mod serializes these as `actual_trace`).
5. `GetScoreFromScoreCalcInfo` reduces steps to final **`ScorePacket`** (`Int64 Score` field).

## Key data types

### `ScoreCalcVizInfo` (one trace step)

| Field | Type | Notes |
|-------|------|--------|
| `TileScores` | `List<ScorePacket>` | Per-tile scores after this step |
| `TileScoreMultipliers` | `List<ScorePacket>` | Tile mults |
| `WordBonus` | `WordBonusToken` | `Bonus` (ScorePacket), `IsMultiplicative`, `IsPoison` |
| `RelevantItem` | `Item` | Sticker/stamp; use `Name` / `ArtFileName` |
| `Money` | `int` | Money change this step |
| `PokerHand` | enum | Optional poker step |
| `IsSettlingGlitchTiles` | `bool` | Glitch settlement |

### `HistoricWord` (submitted word record)

| Field | Type |
|-------|------|
| `TileSelections` | `List<TileSelection>` |
| `Score` | `ScorePacket` |
| `GetSubmittedWordString()` | method → word |

### `Tile` coordinates

- `GetCoordinates()` → `Vector2Int` (`x` = column, `y` = row).
- Solver path index: **`row * 5 + col`** (fixed 5-wide storage; matches `Board.is_active_index`).

## Harmony patches (companion mod)

| Patch | When | Action |
|-------|------|--------|
| `EncounterController.SubmitWord` | Prefix | Start capture session; read word + path |
| `EncounterController.SubmitWord` | Postfix | Match `last_suggestion.json`; export mismatch if needed |
| `PuzzleController.SubmitWord` | Prefix/Postfix | Same for puzzle grids |
| `ScoreCalculation.CalculateOverallScore` | Postfix | If session active, append serialized `ScoreCalcVizInfo` list |

`PopulateValidityAndScore` also calls score calculation for the preview — session flag must be **submit-only** (set in `SubmitWord` prefix, cleared in postfix).

### Suggestion matching (`SuggestionMatcher`)

- **Activate capture** when submitted **path** and **board_fingerprint** match `last_suggestion.json` from F8.
- **Do not** require the submitted dictionary word to equal `word` / `scoring_word` (e.g. game `settee` vs solver `12ttee`).
- **Do not** gate on `loadout_fingerprint` (board fingerprint already includes money).
- Skip when the path differs (alternate route for the same dictionary word) — `predicted_score` is only for the F8 path.

## Files written on mismatch

`%USERPROFILE%\.cursed_words_solver\scoring_mismatches\<timestamp>.json`

See root `README.md` and `melmod/README.md` for the F8 → play word workflow.
