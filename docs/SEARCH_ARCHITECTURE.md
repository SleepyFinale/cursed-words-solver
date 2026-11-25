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
| Letter DFS (`enumerate`) | Trie-guided DFS over every legal path; superset letter matcher, Honeypot two-word branch | always |
| Subset tier (`enumerate_subsets`) | Same walk with numpy sets of trie nodes, so wildcard chains cost one step instead of 26 | when the DFS exceeds its node budget |
| Accumulator pass | DFS over a tiny trie of item words (Bar Chart numbers, Microphone item names, ...) | when items provide them |
| Beam (`beam_search`) | Grows paths one legal move at a time, scores every extension exactly and keeps the best `width`; widens x2 while time remains | when enumeration cannot finish (chess / wildcard-dense boards) |
| Michael's finale (`enumerate_finale`) | All-wildcard 25-tile tours with per-tile position limits | finale grid only |

Every path enumeration finds is validated exactly (`valid_word`: path-dependent
inventory, Number Go Up, Honeypot split order, accumulator words first) and
scored with `EnginePlan.score`. When there are more paths than can be scored
in time, a value-proxy shortlist is scored first; the beam covers what the
proxy misses on dense boards.

## Measuring

```bash
python scripts/engine_replay.py                    # scoring + path validity vs real captures
python scripts/search_benchmark.py --latest 30     # re-solve recent rounds vs what was played
```

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
