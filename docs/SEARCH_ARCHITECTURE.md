# Search architecture

Every word the solver suggests comes from the game-port engine in
[`cursed_words_solver/engine/`](../cursed_words_solver/engine/) (see
[`game-research/engine.md`](game-research/engine.md)): movement, word validity
and scoring are direct ports of the game's own code, so a suggestion is always
a path the game accepts, ranked by the score the game will give it.

## Entry point

`WordSearcher.find_best_words` ([`search.py`](../cursed_words_solver/search.py))
is a thin wrapper around `engine/solver.py:exact_find_best_words`:

1. `EnginePlan.build` resolves the loadout once (items, bosses, challenge,
   previous words, accumulator words).
2. `ExactSearch` precomputes per-tile move tables (`GetValidNextTiles`: white
   portals, Full Moon groups, chess / arrow / adjacent moves, Hungry Snake wrap,
   Sicilian Defense knights) and runs the search below.
3. Results are distinct words, ranked by exact score (Bullseye: by distance to
   the target; Capybara: expected value over item shuffles).

With `search_workers > 1` the start tiles are spread over a process pool
([`search_parallel.py`](../cursed_words_solver/search_parallel.py)), each
start getting a fair share of the time left.

## Per start tile

| Stage | What it does | When |
| --- | --- | --- |
| Letter DFS (`enumerate`) | Trie-guided DFS over every legal path; superset letter matcher, Honeypot two-word branch | always, to `exhaustive_node_budget` |
| Node-set DFS (`enumerate_subsets`) | Same walk carrying an interned set of trie nodes (`NodeSet`), so a wildcard costs one memoised step instead of 26 branches | when the letter DFS exceeds its node budget, to `subset_path_budget` |
| Accumulator pass | DFS over a tiny trie of item words (Bar Chart numbers, Microphone item names, ...) | when items provide them |
| Beam (`beam_search`) | Grows paths one legal move at a time, scores every extension exactly and keeps the best `width`; widens x2 from 64 | when enumeration cannot finish (chess / wildcard-dense boards) |
| Michael's finale (`enumerate_finale`) | All-wildcard 25-tile tours with per-tile position limits | finale grid only |

Every path enumeration finds is validated exactly (`valid_word`: path-dependent
inventory, Number Go Up, Honeypot split order, accumulator words first) and
scored with `EnginePlan.score`. When there are more paths than can be scored
in time, a value-proxy shortlist is scored first; the beam covers what the
proxy misses on dense boards.

## Node sets (why wildcard boards are fast)

A tile path's set of reachable trie nodes depends only on its parent's set and the
tile's matcher (`_matcher`: wildcard?, letter codes, multi-letter tokens), never on
which tiles produced it. `NodeSets` (one per trie, `node_sets(trie)`) interns every
set it builds and memoises `(set token, matcher) -> set`. On a wildcard board
millions of tile paths share a few thousand sets, so each DFS step, beam extension
and `valid_word` check is a dict lookup. Before this (2026-11-27) every path rebuilt
its set with numpy, ~70 us per path; a 23-wildcard board spent all 60 s enumerating.
The memo resets itself past `NodeSets.max_units` (trie nodes plus a per-set and
per-transition overhead, about 150 MB); sets already handed out stay valid, and a
lock guards misses because the app's F8 and AI look-ahead threads share a trie. The DLC search uses the same idea (`dlc_search._FrontMemo`).

The move tables for a path's inventory are cached by the set of item tiles it holds
(`_tables_for(visited)`), not rebuilt from the path each step.

## Budgets and stopping

Enumeration stops at work budgets shared across start tiles: `exhaustive_node_budget`
for the letter DFS and, for the node-set DFS, `subset_path_budget` without a deadline
(fixed per start, deterministic) or `deadline_subset_path_budget` (3.2M) with one, where
paths a start does not use roll over to later starts. The deadline
(`search_time_budget_sec`) caps both. The beam widens 64 -> 4096 and stops once
`beam_patience` (2) passes at or past `beam_min_width` (512) find nothing better;
its scores are cached across passes. A board that finishes early returns early, and
the parallel pool moves on to the next start tile.

## Native code and GPU (2026-11 review)

- numba (`engine/_jit.py`, optional `fast` extra) compiles the letter DFS and the
  node-set DFS for deterministic searches (no deadline: simulator / training, tests,
  shop probes); results are bit-identical to the Python reference
  (`tests/engine/test_jit_parity.py`). Deadline searches (F8) run the memoised Python
  node-set walk instead: on wildcard-dense boards it is ~50x faster than the kernel,
  while on ordinary simulator boards (tiny node sets) the kernel's lower per-path
  cost wins (measured: training steps/s 12.0 without it vs 18.7 with it).
- Fast scorer (`calc._score_fast`): each `_PlanCache` holds a `Ctx` template, an
  item-identity order key, resolved scattered items (`scr`), cached non-chess selections
  (`sel`) and per-grid facts for the fast Dusty Coffin, Fire Extinguisher, Yellow Glasses and
  Maple Leaf hooks (`items.FAST_HOOKS`, keyed by the reference hook so a patched hook falls
  back). All of it assumes the plan's grid and scattered templates don't change after
  `EnginePlan.build`; call `invalidate_score_cache()` after any such change.
  `tests/engine/test_fastcalc_hooks_parity.py` checks the fast and reference versions against
  each other.
- A C++ scorer was evaluated (2026-11) and not built. Unprofiled, scoring is about 35% of a
  training step, so even an infinitely fast native scorer caps out near 1.5x end to end. It
  would cost a compiler toolchain and a C++ copy of about 240 hooks, re-ported on every update.
  If scoring dominates again, the planned route is a numba batch "score program" per plan
  that hands any unported item back to Python.
- A plan-aware shortlist (rank paths by exact single-tile scores times a fitted per-length
  ratio) was tried and dropped. With the gates needed to be never worse than the current
  shortlist, it fell back on about 90% of large boards and gave about 1–2% training speed.
- A GPU was evaluated and not used. The search is a branchy tree walk with tiny
  per-node work and a Python-side scorer, which suits a GPU poorly.

## Measuring

```bash
python scripts/engine_replay.py                    # scoring + path validity vs real captures
python scripts/search_benchmark.py --latest 30     # re-solve recent rounds vs what was played
```

Round logs (mod) copy the solver's `search` block from `last_suggestion.json`
(`wall_sec`, `enum_sec`, `score_sec`, `paths`, `scored`, `workers`, `exhaustive`,
`f8_sec`) into `solver.search`, so slow solves show up in captured data.

## DLC (2026-11)

Ported from the DLC decompile (`docs/game-research/_decompiled/dlc`, regenerate item data with
`python scripts/generate_engine_item_data.py docs/game-research/_decompiled/dlc`).

- **Scoring** (`engine/calc.py`): `Item.ApplyItemToScore` now runs one tile step over every
  word group's tiles, one `ApplyWordBonus` step per group (uppercase words, then the lowercase
  word), then one `ApplySubmissionBonus` step over the whole path. `EnginePlan.score(path, word,
  words=, groups=)` takes the groups; without them `_default_groups` derives them (lowercase
  letters, or a Honeypot "a b" split). Boards / loadouts with DLC content (`plan.dlc_ref`) and
  multi-word submits use `_score_ref`; the cached fast path is legacy-only.
- **Items**: `engine/dlc_items.py` (113 new scoring items, wire / zodiac / domino / dice
  helpers) plus the changed old items in `engine/items.py` (Ambulance, Birthday Cake, Coin
  Purse, Dartboard, Golden Record, Lucky Dice, Tile Ninja, `IsCursed(wordTiles)` users).
  Dice items roll during scoring: by default the hook applies the roll's expected effect and
  flags the result nondeterministic; set `plan.rng = random.Random(seed)` to sample rolls.
- **Validity** (`engine/dlc_rules.py`): `WordRules` ports `GetValidUpperAndLowerCaseWordsFromTiles`,
  `GetConcatenatedValidWordsFromTiles` (Honeypot), brackets and the new letter / wildcard items
  (`IsDisplayingAsVariableLetter`, `IsWildcard`, `IsTileMatchingChar`).
- **Search** (`engine/dlc_search.py`): `ExactSearch.dlc_mode` (`needs_dlc_search`) switches to a
  path-dependent DFS with wire / domino / zodiac / Strong Signal / Goose / Astronaut / Helicopter
  movement and two trie frontiers (uppercase and lowercase word). Its per-tile matcher is a
  superset; every candidate is validated exactly by `WordRules` and scored with its groups.
  `engine_valid_word` / `engine_path_movement_ok` use the same rules in DLC mode.
- The Human Boy DLC challenge (`DLCHumanBoyUnlock`) requires every available required tile.
- **DLC search budget**: the exhaustive DFS gets 35% of the deadline; when it can't finish
  (bracket / wildcard / dice boards) `DlcSearch.beam` runs to 75%: paths grow one legal move at
  a time, are scored exactly with `plan.score(path, "")` (a word-independent proxy) and the best
  `width` are kept (64 doubling to 4096, stopping after two passes past 512 that find nothing
  better; half the slots shared across non-bracket tile counts so short and long words both
  survive). Both walks step trie frontiers through `_FrontMemo`. Beam finds are validated first, by proxy score, then the
  DFS finds by tile-value sum. Validation stops at the deadline once 256 paths are tried, and at
  the deadline + max(2 s, 10%) in any case.
- **Word validation** (`dlc_rules.match_tiles`): when every tile has one string of at most one
  letter it uses per-length letter matrices built from the CsrTrie's BFS levels
  (`length_matrices`), not the permutation walk. A bracket's string is "" (it never stands for a
  letter, as a satisfied-bracket wildcard or Bagel's "a") unless Queen ("qu") can pay it back.
- **Rack tiles** keep their raw game tile (`game_state.player.consumables` ->
  extras `consumable_rack_game_tiles`), so a simulated placement keeps its DLC glyph (domino,
  chess piece, wire) and its movement.
- **LetterUseCounts keys** are `GetStringRepresentation()` strings; `calc.game_srep_to_engine`
  maps each font tag (NotoSansJPBold wire / lowercase l, Symbols2 dice, Dominoes, zodiac,
  Cuneiform hyper curse, TwemojiMozillaAll scattered-item emoji) to the engine token.
- **v5.15** (2026-11-26 hotfix): only a token-condition label (Lexographer) and Turtle's rarity /
  cost (rare, 16) changed; nothing in scoring, movement or validity.
