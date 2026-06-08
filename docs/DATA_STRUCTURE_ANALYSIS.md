# Data Structure Analysis Results

Generated from `scripts/analyze_data_structures.py` (12.0s budget, game/game_words.txt, workers=1).
Run at: 2026-06-08 03:16 UTC

## 1. Hot-path profile: scoring vs DFS

| Fixture | Category | Wall | Score % | DFS % | Extend % | Chess % | Score calls | DFS expansions | Dominant |
|---------|----------|------|---------|-------|----------|---------|-------------|----------------|----------|
| 20260525_172555 | chess | 24.7s | 30.5% | 25.8% | 14.9% | 8.1% | 3,099 | 183,070 | dfs_exploration |
| 20260529_styrofoams_king_check | chess | 7.8s | 1.9% | 0.9% | 97.8% | 0.9% | 84 | 1,906 | dfs_exploration |
| 20260527_hayley_abacus | sticker | 11.1s | 0.5% | 95.0% | 4.8% | 0.0% | 126 | 34,890 | dfs_exploration |
| 20260526_231923 | sticker | 10.8s | 0.4% | 84.6% | 1.7% | 0.0% | 136 | 387,982 | dfs_exploration |
| 20260526_231158 | hanafuda | 10.6s | 0.9% | 99.3% | 0.0% | 0.0% | 310 | 70,765 | dfs_exploration |
| 20260607_131029 | number | 12.2s | 4.7% | 86.8% | 12.9% | 0.0% | 1,517 | 341,097 | dfs_exploration |
| 20260524_235240 | boss | 10.6s | 1.5% | 100.0% | 0.0% | 0.0% | 526 | 91,932 | dfs_exploration |

**Finding:** Wall time is split across DFS exploration, extension passes, chess/number work, and `score_total_only`. `SearchTiming.score_sec` tracks only `score_total_only` on the search hot path; other phase fields are separate.

See also [`SEARCH_ARCHITECTURE.md`](SEARCH_ARCHITECTURE.md) for the full context stack and optimization gating.

### 1b. Tier-2 screening and DFS branch-and-bound

| Fixture | t2 skips | t2 calls | phase1 | phase2 | deferred | bb prunes | bb calls |
|---------|----------|----------|--------|--------|----------|-----------|----------|
| 20260525_172555 | 14 | 17094 | 4991 | 3099 | 4991 | 6598 | 10573 |
| 20260529_styrofoams_king_check | 2177 | 2177 | 0 | 84 | 0 | 1439 | 1439 |
| 20260527_hayley_abacus | 0 | 35 | 0 | 126 | 0 | 36 | 100 |
| 20260526_231923 | 846 | 54182 | 2463 | 136 | 2463 | 22638 | 50094 |
| 20260526_231158 | 5970 | 6438 | 380 | 310 | 380 | 0 | 12575 |
| 20260607_131029 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 20260524_235240 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

| Counter | Meaning |
| ------- | ------- |
| `tier2_screen_skips` | Candidates whose upper bound cannot beat the heap |
| `tier2_rank_screen_skips` | Additional rank-bound skips in phase 1 |
| `tier2_phase1_calls` | Candidates screened in phase 1 |
| `tier2_phase2_calls` | Deferred candidates fully scored in phase 2 |
| `tier2_phase2_deferred` | Candidates deferred from phase 1 |
| `dfs_bb_prunes` | DFS branches pruned by prefix upper bound |
| `dfs_bb_calls` | Prefix bound evaluations during DFS |

## 2. Cache hit rates

| Fixture | Score cache | Dict path cache | Chess attack cache | Grid refs cache | Board.flat calls |
|---------|-------------|-----------------|--------------------|-----------------|------------------|
| 20260525_172555 | 4.1% | 94.9% | 0.0% | 85.6% | 6 |
| 20260529_styrofoams_king_check | 9.5% | 98.0% | 94.7% | 88.2% | 6 |
| 20260527_hayley_abacus | 78.4% | 0.0% | 0.0% | 27.6% | 4 |
| 20260526_231923 | 7.6% | 0.0% | 0.0% | 45.1% | 4 |
| 20260526_231158 | 26.5% | 0.0% | 0.0% | 51.4% | 4 |
| 20260607_131029 | 49.4% | 46.6% | 0.0% | 71.9% | 5 |
| 20260524_235240 | 91.8% | 0.0% | 0.0% | 1.9% | 540 |

*Chess boards use once-per-solve `board_fingerprint` in attack cache keys; Hanafuda scoring uses precomputed `hanafuda_suit_mask`.*

## 3. Per-solve vs per-candidate recomputations

| Item | When | Notes |
|------|------|-------|
| `loadout_mult_rules + build_mult_neighbor_hints` | per_solve | Already precomputed once per F8 |
| `effective_board_for_loadout` | per_solve | Scatter/grid simulation skipped when board_from_melmod |
| `stickers.json catalog` | per_process | Loaded once per Python process |
| `build_solve_context(loadout)` | per_solve | Precomputes stamp flags, hourglass, shield blue, boss rules, inventory_refs, sticker/stamp slot order, grid_tile_multiply_first |
| `build_board_graph_context(board)` | per_solve | Precomputes hanafuda_suit_mask, grid_base_score, coloured_tile_count, chess masks |
| `build_board_scoring_context(...)` | per_solve | Cell target bitmasks, static sticker/stamp specs, use_split_pipeline |
| `ScoringPipeline._compute_state` | per_candidate | Full wiki-order pipeline (receives cached SolveContext + BoardGraphContext + BoardScoringContext) |
| `path_grid_item_refs` | per_path_cached | Grid scatter refs cached per path; hourglass reversal applied in _compute_state |
| `build_scoring_item_sequence` | per_solve / tests | Inventory from SolveContext; grid refs from per-path cache; not _compute_state hot path |
| `Tier-2 two-phase scoring` | per_candidate | Phase 1 bounds screen/defer; phase 2 _compute_state only for survivors |
| `board_fingerprint(board)` | per_solve (chess boards) | Computed once; skipped when BoardGraphContext.has_chess_pieces is false |
| `unused_cards_on_board` | per_candidate | Uses hanafuda_suit_mask bitmask + path-only edge cases (no board.flat) |
| `rank_score_for_word + optimistic_mult_factor` | per_candidate_miss | Extra work after score_total_only on cache miss |

### Per-fixture context build timings

| Fixture | Total | Solve ctx | Graph ctx | Board scoring | Mult rules | Inventory refs | Static rules | Cell masks | Split pipeline |
|---------|-------|-----------|-----------|---------------|------------|----------------|--------------|------------|----------------|
| 20260525_172555 | 0.002s | 0.001s | 0.000s | 0.000s | 0.000s | 11 | 0 | 19 | False |
| 20260529_styrofoams_king_check | 0.001s | 0.001s | 0.000s | 0.000s | 0.000s | 11 | 0 | 19 | False |
| 20260527_hayley_abacus | 0.001s | 0.001s | 0.000s | 0.000s | 0.000s | 10 | 0 | 22 | False |
| 20260526_231923 | 0.001s | 0.001s | 0.000s | 0.000s | 0.000s | 10 | 0 | 24 | False |
| 20260526_231158 | 0.001s | 0.001s | 0.000s | 0.000s | 0.000s | 10 | 0 | 28 | False |
| 20260607_131029 | 0.001s | 0.001s | 0.000s | 0.000s | 0.000s | 10 | 0 | 24 | False |
| 20260524_235240 | 0.001s | 0.001s | 0.000s | 0.000s | 0.000s | 10 | 0 | 26 | False |

## 4. Board.flat access cost

`Board.get_by_index()` indexes `tiles[row][col]` directly. `board_flat_calls` tracks direct `.flat` property access only.

| Fixture | Board.flat calls | cProfile flat sec |
|---------|------------------|-------------------|
| 20260525_172555 | 6 | — |
| 20260529_styrofoams_king_check | 6 | — |
| 20260527_hayley_abacus | 4 | — |
| 20260526_231923 | 4 | — |
| 20260526_231158 | 4 | — |
| 20260607_131029 | 5 | — |
| 20260524_235240 | 540 | — |

## 5. Optimization gating

| Fixture | fast_rank | tier2_screen | tier2_two_phase | dfs_bb | Stickers+stamps | Chess | Number | Hanafuda lvl | Boss |
|---------|-----------|--------------|-----------------|--------|-----------------|-------|--------|--------------|------|
| 20260525_172555 | False | True | True | True | 10 | True | False | 0 | — |
| 20260529_styrofoams_king_check | False | True | True | True | 10 | True | False | 0 | — |
| 20260527_hayley_abacus | False | True | True | True | 9 | False | True | 0 | — |
| 20260526_231923 | False | True | True | True | 9 | False | False | 2 | fox |
| 20260526_231158 | False | True | True | True | 9 | False | False | 2 | fox |
| 20260607_131029 | False | False | False | False | 9 | True | True | 0 | hyena |
| 20260524_235240 | False | False | False | False | 9 | False | False | 0 | cobra |

## 6. Instrumentation

`SearchTiming` reports score/dict/chess/grid_refs cache hits/misses, board_flat_calls, trie steps/prunes/fast_accepts, tier-2 counters, and dfs_bb prunes/calls.

Run analysis:

```bash
python scripts/analyze_data_structures.py --budget 12
python scripts/analyze_data_structures.py --write-doc
python scripts/profile_search.py tests/fixtures/mismatches/20260526_231923.json --budget 12
```

## 7. Summary

Chess-heavy avg score time: 16.2% of wall
Sticker-heavy avg score time: 0.4% of wall
Hanafuda-heavy avg score time: 0.9% of wall
Number-heavy avg score time: 4.7% of wall
Boss-heavy avg score time: 1.5% of wall
Board.flat: use board_flat_calls counter (run --profile-flat for cProfile share)
-> Chess-heavy boards: DFS dominates; chess cache + neighbor gen matter
