# Data Structure Analysis Results

Generated from `scripts/analyze_data_structures.py` (8s budget, game/ENABLE1 wordlist, workers=1).

## 1. Hot-path profile: scoring vs DFS

| Fixture | Category | Wall | Score % | Score calls | DFS expansions | Dominant |
|---------|----------|------|---------|-------------|----------------|----------|
| 20260525_172555 | chess | 8.6s | 4.0% | 304 | 1,054 | DFS |
| 20260529_styrofoams_king_check | chess | 8.0s | 1.7% | 80 | 2,343 | DFS |
| 20260527_hayley_abacus | sticker | 8.0s | 0.9% | 132 | 5,346 | DFS |
| 20260526_231923 | sticker | 7.4s | 0.5% | 108 | 67,001 | DFS |

**Finding:** On these representative fixtures, wall time is dominated by DFS exploration, neighbor generation, chess/number extension passes, and prefix validation — not `score_total_only`.

`SearchTiming.score_sec` only tracks time inside `score_total_only` on the search hot path; `setup_rank_sec`, `mult_rank_sec`, `chess_sec`, and `extend_sec` are separate.

**Implication:** Optimizing search coverage (dictionary pruning, curse neighbor cost, chess checks) helps chess-heavy boards first. Sticker-heavy boards benefit from precomputed `BoardGraphContext` scoring fields and tier-2 screening.

## 2. Cache hit rates

| Fixture | Score cache | Dict path cache | Chess attack cache | Board.flat calls |
|---------|-------------|-----------------|--------------------|------------------|
| 20260525_172555 | 41.5% | **90.3%** | 0.0% | 6 |
| 20260529_styrofoams_king_check | 10.2% | **95.7%** | **98.7%** | 6 |
| 20260527_hayley_abacus | 65.9% | 42.3% | 0.0% | 4 |
| 20260526_231923 | 11.4% | **91.9%** | 0.0% | 4 |

*Post Board.flat fast-path refactor: chess boards use once-per-solve `board_fingerprint` in attack cache keys; sticker/Hanafuda scoring uses precomputed `hanafuda_suit_mask` instead of per-candidate `board.flat` scans.*

### Score cache (`_score_cache`)

- Keys: `(path_tuple, word)` → `(immediate, setup_bonus, rank)`
- Hit rate 6–86% on tested boards; wildcards and alternate spellings reduce hits (dual keys help)
- Cleared each F8; high value when heap revisits top paths during extension

### Dict path cache (`_dict_path_cache`)

- Keys: `tuple(path)` on chess/item boards; `(pattern, tile_constraint_sig)` elsewhere
- Hit rate **42–96%** after trie-state refactor
- Misses invoke `dictionary_word_for_path` (expensive); many wildcard-resolved paths now use `trie_fast_accepts` instead

### Trie fast accept (`trie_fast_accepts`)

- Wildcard branches with fully alpha `join(chars)` and valid `prefix_cursor` skip dict resolve entirely

### Chess attack cache (`_attack_cache`)

- LRU `OrderedDict`, max 8,192 entries; key uses once-per-solve `board_fingerprint` (not rebuilt per lookup)
- **`is_square_attacked` returns immediately** when `BoardGraphContext.has_chess_pieces` is false (no fingerprint, no cache traffic)
- **98.7% hit rate** on king-check fixture — cache is effective when chess DFS is active
- 0% on non-chess boards (cache unused)

## 3. Per-solve vs per-candidate recomputations

| Item | When | Notes |
|------|------|-------|
| `loadout_mult_rules`, `build_mult_neighbor_hints` | per solve | Already precomputed at `find_best_words` start |
| `effective_board_for_loadout` | per solve | Skipped when melmod `source=melmod` |
| `stickers.json` via `@lru_cache` | per process | Not per candidate |
| `build_solve_context(loadout)` | **per solve** | Precomputes stamp flags, hourglass, shield blue, boss rules, inventory refs once |
| `build_board_graph_context(board)` | **per solve** | Precomputes `hanafuda_suit_mask`, `grid_base_score`, `coloured_tile_count`, chess masks |
| `ScoringPipeline._compute_state` | **per candidate** | Full wiki-order pipeline (receives cached `SolveContext` + `BoardGraphContext` via state) |
| `path_grid_item_refs` | **per path (cached)** | Grid scatter refs cached on `WordSearcher._grid_refs_cache` per solve |
| `build_scoring_item_sequence` | **per candidate** | Inventory portion from `SolveContext`; grid refs from per-path cache |
| Tier-2 two-phase scoring | **per candidate** | Phase 1 bounds screen/defer; phase 2 `_compute_state` only for survivors |
| `board_fingerprint(board)` | **per solve (chess boards)** | Computed once in `clear_chess_attack_cache`; skipped when no chess pieces |
| `unused_cards_on_board` | **per candidate** | Uses `hanafuda_suit_mask` bitmask + path-only edge cases (no `board.flat`) |
| `rank_score_for_word`, `optimistic_mult_factor` | per cache miss | After `score_total_only` |

## 4. Board.flat access cost

**Fixed (indexing):** `Board.get_by_index()` indexes `tiles[row][col]` via `divmod(idx, 5)` (no list allocation). `Board.flat` returns a cached `_flat_cache` built once per board.

**Fixed (hot paths):**

- Chess: O(1) bypass in `is_square_attacked` when no chess pieces; once-per-solve fingerprint otherwise
- Scoring: Hanafuda `unused_cards_on_board` uses precomputed suit bitmask from `BoardGraphContext`

| Fixture | Board.flat calls | Notes |
|---------|------------------|-------|
| 20260525_172555 | 6 | solve-start scans + one fingerprint |
| 20260529_styrofoams_king_check | 6 | was ~9,135 (per-lookup fingerprint) |
| 20260527_hayley_abacus | 4 | solve-start only |
| 20260526_231923 | 4 | was ~86,025 (Hanafuda `board.flat` per candidate) |

*Historical baseline (pre-fix):* `get_by_index` routed through `Board.flat`, reallocating a 25-element list on every call. The `board_flat_calls` counter tracks direct `.flat` property access only, not `get_by_index`.

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
