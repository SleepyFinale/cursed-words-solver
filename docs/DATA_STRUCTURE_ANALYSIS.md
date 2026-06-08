# Data Structure Analysis Results

Generated from `scripts/analyze_data_structures.py` (8.0s budget, game/game_words.txt, workers=1).
Run at: 2026-06-08 03:12 UTC

## 1. Hot-path profile: scoring vs DFS

| Fixture | Category | Wall | Score % | DFS % | Extend % | Chess % | Score calls | DFS expansions | Dominant |
|---------|----------|------|---------|-------|----------|---------|-------------|----------------|----------|
| 20260525_172555.json | chess | 15.9s | 29.5% | 26.6% | 14.7% | 12.6% | 2,502 | 126,336 | dfs_exploration |
| 20260529_styrofoams_king_check.json | chess | 7.0s | 1.9% | 0.9% | 97.8% | 1.0% | 84 | 1,906 | dfs_exploration |
| 20260527_hayley_abacus | sticker | 7.4s | 0.6% | 94.7% | 5.1% | 0.0% | 119 | 30,094 | dfs_exploration |
| 20260526_231923.json | sticker | 7.3s | 0.6% | 83.7% | 2.6% | 0.0% | 142 | 244,042 | dfs_exploration |
| 20260526_231158.json | hanafuda | 7.1s | 1.3% | 99.0% | 0.1% | 0.0% | 310 | 55,831 | dfs_exploration |
| 20260607_131029.json | number | 8.2s | 4.4% | 87.7% | 11.8% | 0.0% | 926 | 191,026 | dfs_exploration |
| 20260524_235240.json | boss | 7.0s | 2.4% | 99.9% | 0.0% | 0.0% | 526 | 71,714 | dfs_exploration |

**Finding:** Wall time is split across DFS exploration, extension passes, chess/number work, and `score_total_only`. `SearchTiming.score_sec` tracks only `score_total_only` on the search hot path; other phase fields are separate.

See also [`SEARCH_ARCHITECTURE.md`](SEARCH_ARCHITECTURE.md) for the full context stack and optimization gating.

### 1b. Tier-2 screening and DFS branch-and-bound

| Fixture | t2 skips | t2 calls | phase1 | phase2 | deferred | bb prunes | bb calls |
|---------|----------|----------|--------|--------|----------|-----------|----------|
| 20260525_172555.json | 24 | 15424 | 3935 | 2502 | 3935 | 7260 | 10180 |
| 20260529_styrofoams_king_check.json | 2177 | 2177 | 0 | 84 | 0 | 1439 | 1439 |
| 20260527_hayley_abacus | 0 | 46 | 0 | 119 | 0 | 36 | 100 |
| 20260526_231923.json | 846 | 36119 | 2436 | 142 | 2436 | 10614 | 25598 |
| 20260526_231158.json | 4699 | 5167 | 380 | 310 | 380 | 0 | 9879 |
| 20260607_131029.json | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 20260524_235240.json | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

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
| 20260525_172555.json | 2.6% | 0.0% | 0.0% | 86.6% | 6 |
| 20260529_styrofoams_king_check.json | 9.5% | 98.0% | 94.7% | 88.2% | 6 |
| 20260527_hayley_abacus | 78.0% | 0.0% | 0.0% | 29.2% | 4 |
| 20260526_231923.json | 9.6% | 0.0% | 0.0% | 45.3% | 4 |
| 20260526_231158.json | 27.0% | 0.0% | 0.0% | 51.9% | 4 |
| 20260607_131029.json | 48.8% | 41.8% | 0.0% | 71.3% | 5 |
| 20260524_235240.json | 89.8% | 0.0% | 0.0% | 2.2% | 542 |

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
| 20260525_172555.json | 0.002s | 0.001s | 0.001s | 0.000s | 0.000s | 11 | 0 | 19 | False |
| 20260529_styrofoams_king_check.json | 0.001s | 0.001s | 0.000s | 0.000s | 0.000s | 11 | 0 | 19 | False |
| 20260527_hayley_abacus | 0.001s | 0.001s | 0.000s | 0.000s | 0.000s | 10 | 0 | 22 | False |
| 20260526_231923.json | 0.001s | 0.001s | 0.000s | 0.000s | 0.000s | 10 | 0 | 24 | False |
| 20260526_231158.json | 0.001s | 0.001s | 0.000s | 0.000s | 0.000s | 10 | 0 | 28 | False |
| 20260607_131029.json | 0.001s | 0.001s | 0.000s | 0.000s | 0.000s | 10 | 0 | 24 | False |
| 20260524_235240.json | 0.001s | 0.001s | 0.000s | 0.000s | 0.000s | 10 | 0 | 26 | False |

## 4. Board.flat access cost

`Board.get_by_index()` indexes `tiles[row][col]` directly. `board_flat_calls` tracks direct `.flat` property access only.

| Fixture | Board.flat calls | cProfile flat sec |
|---------|------------------|-------------------|
| 20260525_172555.json | 6 | — |
| 20260529_styrofoams_king_check.json | 6 | — |
| 20260527_hayley_abacus | 4 | — |
| 20260526_231923.json | 4 | — |
| 20260526_231158.json | 4 | — |
| 20260607_131029.json | 5 | — |
| 20260524_235240.json | 542 | — |

## 5. Optimization gating

| Fixture | fast_rank | tier2_screen | tier2_two_phase | dfs_bb | Stickers+stamps | Chess | Number | Hanafuda lvl | Boss |
|---------|-----------|--------------|-----------------|--------|-----------------|-------|--------|--------------|------|
| 20260525_172555.json | False | True | True | True | 10 | True | False | 0 | — |
| 20260529_styrofoams_king_check.json | False | True | True | True | 10 | True | False | 0 | — |
| 20260527_hayley_abacus | False | True | True | True | 9 | False | True | 0 | — |
| 20260526_231923.json | False | True | True | True | 9 | False | False | 2 | fox |
| 20260526_231158.json | False | True | True | True | 9 | False | False | 2 | fox |
| 20260607_131029.json | False | False | False | False | 9 | True | True | 0 | hyena |
| 20260524_235240.json | False | False | False | False | 9 | False | False | 0 | cobra |

## 6. Instrumentation

`SearchTiming` reports score/dict/chess/grid_refs cache hits/misses, board_flat_calls, trie steps/prunes/fast_accepts, tier-2 counters, and dfs_bb prunes/calls.

Run analysis:

```bash
python scripts/analyze_data_structures.py --budget 12
python scripts/analyze_data_structures.py --write-doc
python scripts/profile_search.py tests/fixtures/mismatches/20260526_231923.json --budget 12
```

## 7. Summary

Chess-heavy avg score time: 15.7% of wall
Sticker-heavy avg score time: 0.6% of wall
Hanafuda-heavy avg score time: 1.3% of wall
Number-heavy avg score time: 4.4% of wall
Boss-heavy avg score time: 2.4% of wall
Board.flat: use board_flat_calls counter (run --profile-flat for cProfile share)
-> Chess-heavy boards: DFS dominates; chess cache + neighbor gen matter
