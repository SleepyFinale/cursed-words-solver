# Beans/Michael session parity checklist (2026-06-25)

Source: decompiled `Assembly-CSharp.dll` (`ScoreCalculation`, `Dango`, `HistoricWord`) + session captures.

## Historic / green poison (`enjoinments`)

| Layer | Expected |
| ----- | -------- |
| Game | `ApplyPoisonEffect` iterates **all** `previousWords`; each green tile on historic word → additive `word_score × 10%` (`WordBonusToken`, `IsPoison=true`) |
| Melmod | Export live `previousWords` via `PickBestHistoricWordList`; do not treat encounter as fresh when `scoring_previous_words_count > 0` |
| Python | `green_poison_from_historic_words` must not return 0 when `spc > 0` or historic rows have scores |

**Gap:** `encounter_score_earned: 0` with `remaining == total` while `spc > 0` made `_fresh_encounter_grid_one` / `IsFreshEncounterGridOne` suppress poison.

## Grid scatter / dango (`aggiornamenti`)

| Layer | Expected |
| ----- | -------- |
| Game | `Dango.ApplyWordBonus` applies ×WORD only when `unique_colour_count != 1` (`100 × count` multiplicative) |
| Python | One grid-scatter dango flush per path in snapshot-phased sessions; stamp dango skipped after grid dango flush |

**Gap:** Two grid `dango` items on path may each fire in game; solver must not stack stamp + grid dango twice after flush.

## Michael finale (`microcrystallographically`)

| Layer | Expected |
| ----- | -------- |
| Game | Finale after `SummonedBossesDefeated`; 25-tile word; `PuzzleController` submit; poison still from `previousWords` |
| Melmod | `ApplyMichaelFinaleExport` sets `michael_min_word_length`, `michael_phase=4`, exports `grid_scattered_items` |
| Python | Score with historic poison + grid scattered items; empty sticker rack is valid on finale |

**Gap:** Poison suppressed by fresh-encounter heuristic; grid boomerang correctly skipped (`word_starts_ends_number` false on chess endpoints).

## F8 / submit historic lag (stale F8)

| Layer | Expected |
| ----- | -------- |
| Game | `CalculateOverallScore` `previousWords` authoritative at submit |
| Melmod | F8 uses `BuildF8HistoricExtras` → `BuildSubmitWorkflowExtras`; **no** disk `run_state.json` historic merge |
| Python | Block save when embed historic empty but submit projection has words; re-export from game on gather gap |
