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
| `EncounterController.SubmitWord` | Prefix | Load suggestion; match path/board; set **capture candidate** (no score compare yet) |
| `ScoreCalculation.CalculateOverallScore` | Prefix | `OnScoringContext(previousWords)` — authoritative historic; **activate capture** or block stale F8 |
| `EncounterController.SubmitWord` | Postfix | Match `last_suggestion.json`; export mismatch if capture was active |
| `PuzzleController.SubmitWord` | Prefix/Postfix | Same for puzzle grids |
| `ScoreCalculation.CalculateOverallScore` | Postfix | Always cache `List<ScoreCalcVizInfo>` for round logs; build `actual_trace` only when capture is active |
| `ScoringCaptureSession.EndSubmit` | (internal) | Always export `round_logs/<timestamp>.json`; mismatch export only when capture active |

Workflow stale detection (`historic_words`, `previous_word_first_letter`, etc.) runs in **`OnScoringContext`**, not in `SubmitWord` prefix. `BuildSubmitWorkflowExtras` at submit time can lag one word behind; `previousWords` from `CalculateOverallScore` is authoritative for whether the F8 embed matches score-time extras.

`CachePreviousWordsForExport` runs only during an active submit (`_submitInFlight` or `_captureCandidate`), not on hover/preview `CalculateOverallScore` calls, so preview paths do not overwrite export `previous_word_first_letter`. Capture is blocked on **pre-sync** workflow drift (original F8 embed vs score-time extras) before `TrySyncWorkflowExtrasToProjected` can mask drift; historic **count** lag is blocked separately.

`PopulateValidityAndScore` also calls score calculation for the preview — session flag must be **submit-only** (capture candidate set in `SubmitWord` prefix, `_active` set in `CalculateOverallScore` prefix, cleared in submit postfix).

### Round logs vs mismatch capture

| Feature | When | Output |
|---------|------|--------|
| **Round log** | Every `SubmitWord` (if `RoundLogEnabled`) | `round_logs/<timestamp>.json` + `index.jsonl` |
| **Mismatch bundle** | F8 path + board fingerprint match, scores differ | `scoring_mismatches/<timestamp>.json` |

Round logs include solver prediction (from `last_suggestion.json` when present), actual submit, full `run_state`, consumable rack snapshots, and placement diff since last submit. `match_status` is informational; mismatches still use the dedicated folder for regression tests.

### Suggestion matching (`SuggestionMatcher`)

- **Activate capture** when submitted **path** and **board_fingerprint** match `last_suggestion.json` from F8 (board drift from suggested `consumable_placements` counts as a match), and workflow extras at score time match the F8 embed (checked in `OnScoringContext`).
- **Do not** require the submitted dictionary word to equal `word` / `scoring_word` (e.g. game `settee` vs solver `12ttee`).
- **Do not** gate on `loadout_fingerprint` (board fingerprint already includes money).
- Skip when the path differs (alternate route for the same dictionary word) — `predicted_score` is only for the F8 path.

## Files written on mismatch

`%USERPROFILE%\.cursed_words_solver\scoring_mismatches\<timestamp>.json`

See root `README.md` and `melmod/README.md` for the F8 → play word workflow.

## Snapshot sticker (`Snapshot` class)

Decompiled from `Assembly-CSharp.dll`:

| Member | Type | Role |
|--------|------|------|
| `SnapshottedItem` | `Item` (public field) | Copy target chosen at **start of grid** |
| `SnapshottedDescription` | `string` | Polaroid UI text when equipped |
| `ApplyStartOfGridEffect` | method | Picks a random scattered grid sticker, clones it into `SnapshottedItem`, then delegates grid-start effects |

**Timing:** Copy slug is fixed when `ApplyStartOfGridEffect` runs (board generation), **not** on first word score. The companion patches this method (postfix) and reads `SnapshottedItem` on every export via reflection.

**Export keys:** `extras.snapshot_copy_slug`, `extras.snapshot_copy_level`, `extras.snapshot_copy_export_note` (`ok`, `not_equipped`, `no_copy_yet`, `reflection_failed`), `extras.snapshot_copy_captured_at` (UTC ISO8601 when captured from grid start).

**Trace fallback:** If `SnapshottedItem` is null but a Snapshot scoring step shows additive word bonus `120`, infer `dusty_coffin` (logged as `trace_fallback` in `export_diagnostics.snapshot_copy_source`).
