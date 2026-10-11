# Game-port engine (`cursed_words_solver/engine/`)

The engine is a direct port of the game's scoring and word rules from the
decompiled `Assembly-CSharp.dll` (game 0.2.x). It replaced the rule-table
`ScoringPipeline` (deleted 2026-10-11, with ~1,500 catalog tests that encoded
its representations) as the solver's only scorer, and its exact search replaced the
heuristic search on every board that can be enumerated.

## Why

The old pipeline encoded scoring as JSON rules plus many capture-fitted
special cases (Neapolitan "grid caps", per-mille percents, void-currency
penalty formulas, per-fixture test adjustments). Replaying ~2,400 real game
captures showed where it diverged from the game, and the search spent
1–50 s exploring heuristically while still missing better words.

## Modules

| Module | Game source | Role |
| --- | --- | --- |
| `packet.py` | `ScorePacket` | Checked int64 math, ±infinity, truncating division, float32 `Scale` |
| `model.py` | `Tile`, `TileSelection`, `Item`, `GridData` | Tiles (TileType, GlyphType, suit, chess, value), adjacency incl. Hungry Snake wrap |
| `item_data.py` | every `: Item` class | **Generated**: rarity, cost, food/animal, upgrade components, colours, scatter pools |
| `items.py` | `ApplyTileBonus` / `ApplyWordBonus` | One port per scoring item (~134 classes) |
| `poker.py` | `PokerHands` | Hands, flush/straight (Martini), X-of-a-kind, Scissors pairs |
| `calc.py` | `ScoreCalculation.CalculateOverallScore`, `EncounterController.SubmitWord` | Item order (pin → stickers → stamps, scattered path items first), RAM / Frankenstein / Snapshot / Overhand / Human Boy replays, Hourglass, bosses, Bones Round, currency/pink money, Lexographer, poison, final fold |
| `search.py` | `GridUtility.GetValidNextTiles`, `ChessPieces`, `Arrows`, `Vocabulary` | Exact movement + word validity, trie DFS over every valid path |
| `trie.py` | `WordTrie` | Compact CSR trie (cached under `~/.cursed_words_solver/`) |
| `solver.py` | — | `WordSearcher` adapter: quest ranking, Capybara expected value, per-path checks (movement, submittable, game word, score) |
| `board_paths.py` | — | Movement / spelling / word matching for callers that inspect paths (Cursedle, F8 gates) |

Regenerate `item_data.py` after a game update:

```
ilspycmd -p -o <dir> "<game>/Cursed Words_Data/Managed/Assembly-CSharp.dll"
python scripts/generate_engine_item_data.py <dir>
```

## Search

See [`../SEARCH_ARCHITECTURE.md`](../SEARCH_ARCHITECTURE.md). The engine is the
only search (the legacy heuristic search and its tuning knobs were removed). It
covers every mode:

- **Honeypot** (`GetConcatenatedValidWordsFromTiles`): a path is the whole word,
  else the first split into two words; each part meets the boss length limits on
  its own and positional wildcards restart at the second word. Words are passed
  space-separated (`"cat dog"`) and scored as the game's word list.
- **Accumulator words** (`InventoryCache.PertinentAccumulatorWords`): Bar Chart
  numbers, Book of Openings pieces, Flashy Fountain Pen colours, Michael's Book's
  word, and Microphone's item names (melmod exports the live list) are valid before
  the dictionary is consulted.
- **Michael's finale**: any 25-tile tour whose every tile is a wildcard at its
  position (numbers / fractions / Microscope pin positions); the game submits a
  random 25-letter word.
- **Cursedle** uses the same movement and vocabulary (`engine/board_paths.py`).
- **Playing Favourites** limits the items movement / letter rules see to the
  favourites, like `Player.GetAllItems()`.

`GetValidNextTiles` note: the decompiled chess branch reads
`Exists(t => t.SelectedTile == t.SelectedTile)`; ILSpy reused one name for two
lambda variables. The game de-duplicates, so chess moves are added after white
portal / Full Moon targets (99 captured Full Moon submissions confirm it).

## Oracle

`cursed_words_solver/sim/replay.py:prepare_replay` turns a round log or
mismatch capture into (board, loadout, path). It handles the round-log
conventions found while building the engine:

- paths are melmod bottom-origin since 2026-06-30 (`path_storage` preferred)
- round-log extras are captured **after** the word scored: F8 values come
  from `extras_diff`, and accumulators (Bicycle, Ruler, Neapolitan, Birthday
  Cake, Movie Camera, Michael's Book) are rewound by this word's increment
- the rack count at scoring is `consumables.rack_before`
- Two Wrongs records the negated score

`tests/engine/test_engine_captures.py` locks in every repo capture the
engine reproduces exactly (`engine_exact_captures.txt`).

## Exact melmod export (companion ≥ this change)

Legacy exports lose information the engine needs; the companion now adds:

- `extras.item_states`: 5-slot sticker/stamp arrays (empty slots kept, for
  Overhand / Arrivals / Departures), the pin, and per item the live
  `UpgradeableComponents` levels **and** `VariableValue`s (not
  `TimesUpgraded`, which `Item.Upgrade` never bumps), `RelevantColours`
  (randomised on Colour Swap / Tin of Beans / Beans), and the item's own
  fields (Ruler.Distance, Dartboard._targetNumber, EightBall._selectedPiece,
  CrystalBall.ChosenCurseType, BirthdayCake's float bonus, …), recursing
  into RAM memory, Frankenstein stitches and the Snapshot copy.
- per tile: signed `value_exact` (`GetValue()`; the legacy export clamped
  non-letter void tiles to 0), `value_modifier`, raw `glyph` / `tile_type` /
  `suit`, and `scattered_item_state` (exact scattered level and counters).
- the scatter-level heuristics (Toolbox / equipped tier bleed / tombstone
  sums) were removed — the live component level is exported instead.
- the dictionary export keeps one-letter words ("a", "i", "o").

The engine keeps legacy fallbacks (Retro Raider / Toolbox / Cursed VHS /
Radio scatter pools, Left Hand favourite upgrades, Globe Trotter corner
modifiers, void-value reconstruction) for older captures.

## Exact captures (`game_state/1`, companion 1.4)

`melmod/.../GameStateSerializer.cs` dumps the live game objects:

| Block | Contents |
| --- | --- |
| `grid` | width / height / grid number; per tile: game `x`, `y` (y = 0 bottom row), `glyph`, `type`, `letter`, `number`, `fraction`, `suit`, `piece`, `white`, `value` (`GetValue()`), `value_modifier`, `cactus_growth`, `srep`, `srep_word`, `cursed`, `flags`, scattered `item` |
| `encounter` | `grids_generated` (the GridNumber scoring receives), targets, grids left, rerolls, piggy bank, `bosses` (class + every field), `previous_words` (words, score, skipped, tiles, selection methods) |
| `player` | money, character, sticker / stamp slots (5 each, empty slots kept) and pin with components, colours and fields, consumable rack tiles, `accumulator_words` / `accumulator_pairs` |
| `run` | stage, node type, ascension, cursed bosses, embargo, `challenge` (class + fields) |

`run_state.json` carries it as `game_state`; the solver keeps the legacy board
(overlay layout) but takes item states, accumulator words, previous words and the
grid number from it (`game_state.apply_game_state`), and each board tile gets its
raw tile (`metadata["game_tile"]`) so glyph / type / value are never inferred.

Round logs carry `capture`: `pre_submit` (taken in the `SubmitWord` prefix, i.e.
exactly what the word is scored against), `submission` (tile coordinates, selection
methods, words) and `scoring_call` (grid number, item order and item slots as
`CalculateOverallScore` received them, after Capybara's shuffle). `prepare_replay`
replays these directly (`game_state.replay_from_capture`) -- no post-submit rewind.

Turn captures into tests with `scripts/capture_to_fixture.py`; every file in
`tests/fixtures/captures/` must replay to the game's score
(`tests/engine/test_capture_fixtures.py`). `scripts/engine_replay.py` measures
scoring accuracy and path validity across all captures.
