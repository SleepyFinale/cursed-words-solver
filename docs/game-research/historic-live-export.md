# Historic live export parity (2026-06-25)

Source: [`beans-session-parity.md`](beans-session-parity.md), session round logs (`155542`, `155318`), melmod `BuildF8HistoricExtras` / `BuildSubmitWorkflowExtras`, Python `prune_historic_incompatible_with_board`.

## Game behavior (`previousWords`)

| Topic | Game truth |
|-------|------------|
| Authoritative at score | `CalculateOverallScore` `previousWords` list (melmod: scoring hook cache + live reflection) |
| Poison / green tiles | `ApplyPoisonEffect` iterates **all** historic words; uses word/score/green counts — **not** board paths |
| After board reshuffle | Paths in historic entries are stale; word/score/red/green metadata still drives stamps, poison, Bento prev-letter |
| Grid advance | Scoring cache clears or shrinks; grid 2+ must not use prior-grid path-bearing JSON |
| Same grid word 2+ | `scoring_previous_words_count > 0`; historic count matches words played **this grid** |

## Export rule (melmod + Python)

1. **F8 ack export** (`BuildF8HistoricExtras` / `liveOnly`): live player + scoring cache only — never inflate from on-disk `run_state.json`.
2. **Submit** (`BuildScoringContextWorkflowExtras`): same live cache at score time.
3. **Python scoring** may strip **paths** from historic when no path matches the current board, but must keep **metadata rows** and `scoring_previous_words_count` from the live export.
4. **F8 embed** (`last_suggestion.json`) must carry the same historic **count** and metadata as scoring used — not empty when `spc > 0`.

## Failure mode (session)

Grid word 1 `score_match` → word 2 F8 embed `historic_words=""`, `spc=0`, `grid_start_cleared` → submit has 1-word historic → melmod `DescribeF8PredictionHistoricStaleNote` blocks capture.

Root cause: Python `prune_historic` cleared historic (or zeroed `spc`) after reshuffle instead of `historic_metadata_only`.

## Embed shape

| Situation | `historic_words` in embed |
|-----------|----------------------------|
| Grid word 1, `spc=0` | Empty (Telescope grid-start semantics) |
| Same grid word 2+, paths stale | Metadata-only array (word, score, red/green counts; no `path`) |
| Paths still valid | Full JSON from live export |
| Green poison only | `green_poison_only` rows |

Melmod submit check: metadata-only F8 with matching counts/fields is **not** stale vs full-path authoritative JSON.
