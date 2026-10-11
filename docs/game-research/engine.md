# Game-port engine (`cursed_words_solver/engine/`)

The engine is a direct port of the game's scoring and word rules from the
decompiled `Assembly-CSharp.dll` (game 0.2.x). It replaced the rule-table
`ScoringPipeline` as the solver's scorer, and its exact search replaced the
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
| `solver.py` | — | `WordSearcher` adapter: quest ranking, Capybara expected value, legacy fallback |

Regenerate `item_data.py` after a game update:

```
ilspycmd -p -o <dir> "<game>/Cursed Words_Data/Managed/Assembly-CSharp.dll"
python scripts/generate_engine_item_data.py <dir>
```

## Search

1. `EnginePlan.build` resolves the loadout once per solve.
2. `ExactSearch` precomputes per-tile move tables (portal, Full Moon group,
   chess / arrow / adjacent moves, king safety) and runs a trie DFS.
3. Each distinct valid path is scored once; a path's score never depends on
   which letters its wildcards spell.
4. If the DFS exceeds `exhaustive_node_budget` (wildcard- or chess-dense
   boards, ~20% of captures, mostly Full Moon + Hungry Snake builds), the
   legacy heuristic search runs on the remaining time and its candidates are
   re-scored exactly; the best of both wins.

Unsupported (falls back to the legacy search): Cursedle, Michael's 25-tile
finale, Honeypot two-word submits.

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
