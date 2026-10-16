# Game-faithful run simulator (`cursed_words_solver/sim/game/`)

A Python port of the game's run loop, built from the decompiled `Assembly-CSharp.dll`
(`ilspycmd -p -o docs/game-research/_decompiled/full <dll>`; gitignored). Scoring and word
search stay in the engine (`cursed_words_solver/engine/`); the simulator hands the engine
its state as melmod `game_state/1`, the same format real captures replay from exactly.

## Modules

| Module | Game classes | Notes |
| --- | --- | --- |
| `core.py` | `Tile`, `GridData`, `Alphabet`, `Currency`, `ChessPieces`, `PlayingCardUtility`, `UnityEngine.Random` | `Tile.GetValue`, curse / wobbly rules, `RandomlyCurseTile`, serialisation to `game_state` tiles |
| `grid_util.py` | `GridUtilitySingleton` helpers, `ConsumableTileUtility`, `BoardGenVizInfo` | `GetTileForItemScatter` (Saxophone / Magnet tiers), boss scatter, rack add/remove (Brick, Luffing Jib Crane, Erupting Volcano), `Player.Shuffle` |
| `gridgen.py` | `GenerateGrid`, `GenerateBasicGridData`, `MakeStartOfGrid{Item,Challenge,Boss}Adjustments` | crown-5 letter weights, quest grids (Red Letter / Pepper Day, Empty Grid, Sudoku, Call of the Void, Munch Time, Supply and Demand, Up and Up), Hourglass reversal, cactus growth, RAM / Frankenstein / Human Boy / Overhand repeats |
| `items.py` | `Item` + every subclass hook the engine does not score | 124 `ApplyStartOfGridEffect`, `FinalStartOfGridEffect` (Milky Way), `StartOfEncounterSetUp`, `OnAcquire`, overridden `Upgrade` / `Downgrade`, `GetSellValue` (Nest Egg), `RandomiseRelevantColours`, `GetCost`; scattered-item pools |
| `pools.py` | `ItemPools` | rarity rolls (Genie ×3, Snail), build-biased stock (dependency → upgrade → synergy tags → generator → uniform) |
| `player.py` | `Player`, `RunProgress`, `BossModifier`, `BossDraft`, `HistoricWord`, `MichaelBoss` data | fixed 5/5/10 slots, Human Boy favourites, Underhand / Overhand, Capybara shuffle, targets (float32), boss drafts, Ogre curses, secret bosses (`CheckSecretBossesConditions`), Meg's stored inventory |
| `encounter.py` | `EncounterController` | grid counts (Badger, Diya, crown 7), rerolls (Wheel, Fan, Rollercoaster, Slot Machine), Toothed Whale target, Hyena forced sell, consumable placement, Twinkle Toes, submit (Capybara → glitch settle → engine → Cable Car), per-step money / piggy bank / rack (Hi-Vis Jacket, Bar of Soap, Golden Record, Jolly Roger) / Microphone, accumulators (Bar Chart, Book of Openings, Fountain Pen, Michael's Book), payouts (Dragon interest, Do Not Pass Go, Embargo refund), Michael's phases + finale |
| `shop.py` | `ShopController`, `ItemInStock`, `TileInStock`, sell flow | first free pick, Angel Investment, foil (Fortune Cookie / Snail quirk), Avocado / Northern Cardinal / Blessing prices, Downward Trending Chart, Eraser, Delivery Truck, Efficient Recycler restocks, Hungry Hippo feeding, freezes, sell effects (Mystery Gift, Sewing Needle → Frankenstein, Signal Receiver, Stadium, Unicorn, padlocks), quest shop rules |
| `challenges.py` | `ChallengeRun` + 26 quests | forced characters, starting items / upgrades / tiles, banned bosses |
| `run.py` | `RunProgress.AdvanceToNextNodeType`, `BossDraftController`, `BossRewardController` | `Game`: node flow, Meg shop detour, Michael stage, pin upgrades (ID Card both) |
| `bridge.py` | — | sim → `game_state/1` → `Board` / `Loadout` |
| `importer.py` | — | `game_state/1` (live run or capture) → sim objects; infers crown ≥ 3 on old exports |
| `agent.py` | — | `Action`, `legal_actions`, `apply`, `clone`, `Candidates` (engine top-K words) |
| `policy.py` | — | `GreedyPolicy`, `PowerPolicy` (simulated next-encounter points drive shop / boss / pin / Michael draft choices), `AdvicePolicy` (shop by the ported in-game Advice button) |
| `features.py` | — | state → 1000+-dim feature vector (position, economy, inventory levels / foils, pin, rack, boss options, frozen stock) and the `progress` training target |
| `learn.py` | — | self-play value learning: parallel collection, numpy MLP, `ValuePolicy` (ε-greedy over learned values; shop rerolls valued by sampled restocks) |
| `advise.py` | — | live advisor: `run_state.json` → simulator → ranked actions (encounter options by rollout P(clear)) |
| `evaluate.py` | — | parallel seeded runs → win rate + JSONL decision logs (`--policy power / greedy / advice / value:<model>`) |

## Validation (2026-10-16)

- **Scoring through sim state:** every melmod 1.4 capture (149 in the local round logs, 14
  fixtures) reproduces the game score exactly after import → sim `GetValue` → export.
- **Within-encounter dynamics:** 52 consecutive capture pairs (same encounter): money 52/52,
  rack 52/52, item counters 52/52, remaining target 51/52 (the miss is a Capybara round whose
  real item order came from the game's RNG).
- **Targets:** the 15 targets of a real Carpman crown-0 win match `RunProgress.GetEncounterTarget`.
- Crash sweep: all 11 characters × crowns 0–8 and all 26 quests run to completion.

- **Grid generation statistics:** 94 real first grids vs 100 simulated grids each from the
  same inventory: tile-type / glyph / suit counts sit inside the simulated distribution
  except for one Octacles run whose Bucket contents the old melmod export dropped (fixed in
  the mod; needs redeploy).

Tests: `tests/sim/test_game_sim.py`, `tests/sim/test_game_rules.py`.

## Policies so far (Carpman, crown 0, 16 seeds)

| Policy | Wins | Notes |
| --- | --- | --- |
| `greedy` (never shops) | 0/16 | dies at the stage-2 boss |
| `power` | 3/16 | reaches stage 5 but hoards money; 3–30 min per run |
| `advice` | 29/128 (23%) | in-game Advice shopping (+ pin counted, no sell churn); 3–50 s per run |
| `advice --cfg reroll_ratio=0.8` | 32/128 (25%) | within noise |

Losses with `advice` cluster at stages 4–5 with full 5-sticker builds: item choice, not
spending, is the bottleneck.

**Value learning (learn.py), run 2:** 2,000 self-play runs over all characters / crowns
(92k decisions). The MLP reaches holdout R² ≈ 0.3 on final progress; acting greedily on it
did *worse* than the Advice exploration it learned from (mean encounters cleared 6–7 vs
7.9), so the noisy Monte-Carlo value is not yet usable as a policy.

**Rollouts (rollout.py):** `RolloutPolicy` re-ranks the Advice suggestion against other buys
/ leave (and boss / pin options) by playing each choice out with the Advice policy to the end
of the next two stage bosses, scoring survival, then points-per-word relative to targets.
Slow (minutes per run) — best suited to the live advisor and to generating expert data.

## Known gaps

- Michael's finale puzzle grid (`GridGenerator.GetPuzzleGrid`) is not generated; reaching
  the finale counts as a win (the puzzle always has a 25-tile solution).
- Speedrun quest timing is not modelled.
- RNG is Python's, not Unity's: runs are statistically, not bit-for-bit, faithful.
- `GetValidNextTiles` is only needed for Carousel Horse's knight squares; that uses plain
  knight moves (+ Hungry Snake wrap).
- Unlock profile is "everything unlocked"; `RunConfig.unlocked_characters` controls secret
  bosses and `character_never_won` the Shop Advice starter item.

## Usage

```python
from cursed_words_solver.sim.game.run import Game, RunConfig
from cursed_words_solver.sim.game.agent import Candidates
from cursed_words_solver.sim.game.policy import PowerPolicy, play

cands = Candidates()
g = Game(RunConfig(character="Carpman", ascension=0, seed=1))
play(g, PowerPolicy(cands))
print(g.won, g.end_reason)
```

```bash
python -m cursed_words_solver.sim.game.evaluate --character Carpman --crown 0 --runs 16
```
