# Simulator traceability matrix (Stage 1)

Maps decompiled game types → Python `cursed_words_solver/sim/` → wiki → fixtures.

Regenerate decompiles: `scripts/decompile_sim_types.ps1` or see [README.md](README.md).

## Encounter loop

| Game (decompile) | Python | Wiki | Fixture |
| ---------------- | ------ | ---- | ------- |
| `EncounterController.SubmitWord` | `EncounterEngine.step` + `RewardEngine` | [Scoring](https://cursedwords.wiki.gg/wiki/Scoring) | `tests/fixtures/round_logs/` |
| `ScoreCalculation.CalculateOverallScore` | `RewardEngine` → `ScoringPipeline` | Scoring | `tests/regression/test_scoring_mismatches.py` |
| `_remainingTarget -= score` | `EffectEngine.apply_post_submit` → `encounter_remaining_target` | — | round log `extras_diff` |
| `HistoricWord` / `_previousWords` | `extras.historic_words` | — | `stale_f8_*_extras_diff.json` |
| `GenerateGrid` / `_remainingGrids--` | `EffectEngine.apply_grid_start` | — | round logs (grid transition) |
| `GridUtility.GenerateGrid` | `effective_board_for_loadout` | [Tiles](https://cursedwords.wiki.gg/wiki/Tiles) | boss/grid catalog tests |
| `Item.ApplyStartOfGridEffect` | `grid_effects.apply_start_of_grid_mutations` | Items | sticker catalog |
| `Item.StartOfEncounterSetUp` | `grid_effects.apply_start_of_encounter_mutations` | — | encounter fixtures |

## Post-submit extras (EffectEngine v0)

| Game class | Extra key | Python |
| ---------- | --------- | ------ |
| `BirthdayCake` | `birthday_cake_bonus` | `setup_value.project_setup_delta` |
| `Bicycle` / pin | `bicycle_word_score_bonus` | `setup_value.project_setup_delta` |
| `HiVisJacket` | `consumable_rack_count` | `setup_value.project_setup_delta` |
| `RedRider` | `red_tiles_used_encounter` | `setup_value.project_setup_delta` |
| `TileNinja` | `tile_ninja_bonus` | `setup_value.project_setup_delta` |
| `Neapolitan` | `neapolitan_percent` | scoring pipeline (submit sim) |
| Historic | `previous_word_first_letter` | `scoring_conditions._effective_word_start_letter` |

## Stage 5 (full run)

| Game | Python | Fixture |
| ---- | ------ | ------- |
| `ShopController` | `sim/run.py` + `game_shop/recommendation.py` | `tests/fixtures/shops/` |
| `Player.CurrentRunProgress` | melmod `run_state.extras` | integration tests |

## Divergence protocol

1. Failing `sim/replay.py` or `tests/sim/`
2. Decompile relevant type
3. Cross-check wiki (trust code on conflict)
4. Fix `EffectEngine` / `RewardEngine`
5. Promote capture via `scripts/round_log_to_test.py`
