# Data Structure Analysis Results

Generated from `scripts/analyze_data_structures.py` (12s budget, game/ENABLE1 wordlist, workers=1).

## 1. Hot-path profile: scoring vs DFS

| Fixture | Category | Wall | Score % | Score calls | DFS expansions | Dominant |
|---------|----------|------|---------|-------------|----------------|----------|
| 20260525_172555 | chess | 12.0s | 2.1% | 276 | 582 | DFS |
| 20260529_styrofoams_king_check | chess | 12.1s | 3.1% | 274 | 354 | DFS |
| 20260527_hayley_abacus | sticker | 11.9s | 0.8% | 166 | 7,457 | DFS |
| 20260526_231923 | sticker | 12.0s | 15.0% | 4,057 | 7,630 | DFS |

**Finding:** On these representative fixtures, wall time is dominated by DFS exploration, neighbor generation, chess/number extension passes, and prefix validation — not `score_total_only`. The sticker-heavy mismatch `20260526_231923` is the outlier with meaningful scoring share (15%, 4k pipeline calls).

`SearchTiming.score_sec` only tracks time inside `score_total_only` on the search hot path; `setup_rank_sec`, `mult_rank_sec`, `chess_sec`, and `extend_sec` are separate. Sticker-heavy loadouts with many scored candidates will shift the balance toward scoring.

**Implication:** Optimizing search coverage (dictionary pruning, curse neighbor cost, chess checks) helps chess-heavy boards first. Sticker-heavy boards with high `score_calls` benefit more from pipeline precompute and two-phase scoring (Tier-2).

## 2. Cache hit rates

| Fixture | Score cache | Dict path cache | Chess attack cache | Board.flat calls |
|---------|-------------|-----------------|--------------------|------------------|
| 20260525_172555 | 86.4% | **97.0%** | 0.0% | 5 |
| 20260529_styrofoams_king_check | 5.6% | **98.0%** | **98.3%** | 9,135 |
| 20260527_hayley_abacus | 65.1% | 45.8% | 0.0% | 4 |
| 20260526_231923 | 39.7% | 0.0% | 0.0% | 86,025 |

*Post trie-state traversal refactor (linguistic cache + trie fast-accept for resolved wildcards). Chess boards keep spatial path keys; sticker/wildcard boards use linguistic `(pattern, tile_sig)` keys.*

### Score cache (`_score_cache`)

- Keys: `(path_tuple, word)` → `(immediate, setup_bonus, rank)`
- Hit rate 6–86% on tested boards; wildcards and alternate spellings reduce hits (dual keys help)
- Cleared each F8; high value when heap revisits top paths during extension

### Dict path cache (`_dict_path_cache`)

- Keys: `tuple(path)` on chess/item boards; `(pattern, tile_constraint_sig)` elsewhere
- Hit rate **45–98%** after trie-state refactor (was 7–45%); chess fixture improved from 6.7% to 97.0%
- Misses invoke `dictionary_word_for_path` (expensive); many wildcard-resolved paths now use `trie_fast_accepts` instead

### Trie fast accept (`trie_fast_accepts`)

- Wildcard branches with fully alpha `join(chars)` and valid `prefix_cursor` skip dict resolve entirely
- Chess fixture: 1,290 fast accepts vs negligible before; sticker fixture: 13,939 fast accepts

### Chess attack cache (`_attack_cache`)

- LRU `OrderedDict`, max 8,192 entries; key includes `board_fingerprint(board)`
- **98.7% hit rate** on king-check fixture — cache is effective when chess DFS is active
- 0% on non-chess boards (cache unused)

## 3. Per-solve vs per-candidate recomputations

| Item | When | Notes |
|------|------|-------|
| `loadout_mult_rules`, `build_mult_neighbor_hints` | per solve | Already precomputed at `find_best_words` start |
| `effective_board_for_loadout` | per solve | Skipped when melmod `source=melmod` |
| `stickers.json` via `@lru_cache` | per process | Not per candidate |
| `build_solve_context(loadout)` | **per solve** | Precomputes `stamp_search_flags_mask`, hourglass, shield blue, boss rules, inventory refs once |
| `ScoringPipeline._compute_state` | **per candidate** | Full wiki-order pipeline (receives cached `SolveContext`) |
| `path_grid_item_refs` | **per path (cached)** | Grid scatter refs cached on `WordSearcher._grid_refs_cache` per solve |
| `build_scoring_item_sequence` | **per candidate** | Inventory portion from `SolveContext`; grid refs from per-path cache |
| Tier-2 two-phase scoring | **per candidate** | Phase 1 bounds screen/defer; phase 2 `_compute_state` only for survivors |
| `stamp_search_flags_mask`, `hourglass_reverses_order`, `shield_blue_base_from_loadout` | **per solve** | Via `build_solve_context` at `find_best_words` / parallel worker init |
| `board_fingerprint(board)` | **per chess cache miss** | Builds string via `Board.flat` |
| `rank_score_for_word`, `optimistic_mult_factor` | per cache miss | After `score_total_only` |

**Remaining per-candidate cost (sticker-heavy):**

1. Full `_compute_state` wiki-order pipeline (Tier-2 screen skips some calls when enabled)
2. Path-dependent `build_scoring_item_sequence` grid-path refs
3. Consider further two-phase scoring when `score_pct >= 55%` and `sticker_count > 0`

## 4. Board.flat access cost

**Fixed:** `Board.get_by_index()` now indexes `tiles[row][col]` via `divmod(idx, 5)` (no list allocation). `Board.flat` returns a cached `_flat_cache` built once per board (rebuilt after consumable tile replacement). Re-run the analysis script to refresh the numbers below.

| Fixture | Board.flat calls | cProfile cumtime | % of wall |
|---------|------------------|------------------|-----------|
| 20260525_172555 | 5 | ~0.000s | ~0% |
| 20260529_styrofoams_king_check | 9,135 | ~0.021s | ~0.2% |
| 20260527_hayley_abacus | 4 | ~0.000s | ~0% |
| 20260526_231923 | 86,025 | ~0.048s | ~0.5% |

*Historical baseline (pre-fix):* `get_by_index` routed through `Board.flat`, reallocating a 25-element list on every call. The `board_flat_calls` counter now tracks direct `.flat` property access only, not `get_by_index`.

`board_fingerprint()` calls `board.flat` on chess attack cache misses; with 98.7% chess cache hits, fingerprint cost is secondary.

## 5. Instrumentation added

`SearchTiming` now reports:

- `score_cache_hits` / `score_cache_misses`
- `dict_path_cache_hits` / `dict_path_cache_misses`
- `chess_attack_cache_hits` / `chess_attack_cache_misses`
- `board_flat_calls`
- `trie_fast_accepts`
- `trie_steps` / `trie_prunes`

Run analysis:

```bash
python scripts/analyze_data_structures.py --budget 12
python scripts/profile_search.py tests/fixtures/mismatches/20260526_231923.json --budget 12
```
