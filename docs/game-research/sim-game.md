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
| `learn.py` | — | self-play value learning: parallel collection, numpy MLP and `Ridge` (+ `load_model`), `ValuePolicy` (ε-greedy over learned values; shop rerolls valued by sampled restocks) |
| `advise.py` | — | live advisor: `run_state.json` → simulator → ranked actions (encounter options by rollout P(clear)) |
| `evaluate.py` | — | parallel seeded runs → win rate + JSONL decision logs (`--policy power / greedy / advice / value:<model>`, `--effort` for deterministic search) |
| `expert.py` | — | the learning loop: `NetPolicy`, paired full-run rollouts, ridge advantage model, champion gating |

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

## Tuned base policy (deterministic benchmarks, 2026-10-16)

Every change was measured on the same 2 × 256 seeds (Carpman crown 0 unless noted;
wins out of 512; runs are exactly reproducible, see *Reproducibility* below):

| Change | Wins | Notes |
| --- | --- | --- |
| Fast Advice (fixed boss rule: uncursed, avoid Big Boss) | 60 | |
| + learned boss risk (`bossrisk.py`) | 92 | Negative Money ends 27% of runs that face it, Steals Money 5.5% |
| grid reroll ratio 0.4 / 0.55 / 0.7 / 0.85 / 1.0 | 88 / **92** / 89 / 84 / 84 | default 0.55 confirmed |
| + rack-tile placement when behind pace | 105 | Advice buys tiles; the fast policy never used them |
| placement target squares 2 / 3 / 5 / 8 / 16 | 105 / 105 / 110 / **112** / 112 | 8 |
| + encounter planner (`plan_encounter`) | **121** | top 4 words / reroll / placement played out to the encounter end; ~4× slower runs |
| pin side: lower / always left / always right (without planner) | **112** / 92 / 90 | balanced upgrades win for Carpman |

Crowns 1–8 (Carpman, mixed): the old "always take the cursed boss while chasing Michael"
rule won 1 / 512 (mean 8.2 encounters); learned risk with a 0.05 cursed margin won 9
(mean 8.9) — cursed bosses vary from 10% (Small Grid*) to 47% (Negative Money*) run-ending.

`policy.tuned_config()` holds these settings; the live advisor's rollouts use it.

**Boss risk** (`bossrisk.py`): counts of (boss faced, run ended there) per boss and per
crown from simulated runs, Beta-smoothed (crown → boss → average boss). The draft takes the
lowest-risk boss, but a cursed one while chasing Michael unless it is more than
`cursed_margin` riskier (or slightly riskier with Blessing of the Fairies). It improves as
more runs are added: `python -m cursed_words_solver.sim.game.bossrisk --runs 1024 --crowns 1,2,3`.

**Encounter planner** (`FastAdvicePolicy.plan_scores`): candidates are the top words, a
grid reroll and the best placement; a word that clears is valued exactly, others by two
greedy play-outs to the encounter end. Value = loss (−1000) or money + $3 per item level
gained + $2 per rack tile kept. A non-clearing word is considered while the best word
clears only if it earns more than the $2 an unused grid pays (money-per-grid builds).

## Machine learning: policy iteration from paired rollouts (`expert.py`)

The learning loop that improves with more runs:

1. **Policy:** `NetPolicy` plays the in-game Advice suggestion at every run-level decision
   (shop buy / restock / sell / leave, boss, pin side, Michael's draft) unless a learned
   advantage model predicts an alternative is better by more than a margin.
2. **Data:** the current champion plays runs. At ~30% of decisions the suggestion and one
   random alternative are both played **to the end of the run** by the champion with
   *keyed* randomness (the RNG is reseeded before every action from the run position and
   action kind, so both branches see the same grids / shops wherever they meet); label = outcome difference (`features.outcome`: encounters cleared
   + share of the target reached in the losing encounter; a win = 16), input = difference
   of the two after-state feature vectors. Pairs accumulate across iterations.
3. **Model:** ridge regression (`learn.Ridge`, λ by 5-fold CV). With ~1000 features and
   noisy labels an MLP could not even recover a one-feature synthetic signal; the linear
   model does.
4. **Gate:** each model is benchmarked at margins 0.5 / 1 / 2 on 256 fixed seeds,
   then the best margin is compared with the champion on 256 *different* seeds; only a
   better model becomes the champion that generates the next iteration's data.

```bash
python -m cursed_words_solver.sim.game.expert --iterations 10 --runs 256 --characters WetDennis --crowns 0
```

Resumable; `history.json` tracks every iteration, `champion.npz` is the current best.

Play-outs continue with a cheaper copy of the policy (search effort 0.02, 3 placement
squares: 9.7 s instead of 34.7 s per run; tile-placement probes dominate the cost).

### What went wrong with the first keyed model

Iteration 0 (2,235 keyed pairs) reached CV correlation 0.11, but playing it lost 58 → 33
wins. Measured with keyed play-outs at the 124 decisions where it actually overrode Advice,
its switches were worth −0.20 ± 0.10 encounters each (swapping Advice's item for another:
−0.32) — with ~1,000 features and labels ~21% signal, 2k pairs mostly fit noise, and
taking the max over candidates selects the noisiest predictions. Fixes: 5× more pairs per
hour (cheap play-outs, 30% sampling, 512 runs / iteration) and, on override, Advice's
per-shop bookkeeping (bought / sold / frozen) now follows the action actually taken.

### Label noise

Test-retest on 188 decisions (same pair labelled twice with independent seeds): with one
shared random stream the two labels were uncorrelated (r ≈ −0.2, sd 2.0 encounters) — once
the branches diverge every later grid differs, so the first loop iteration (2,121 pairs)
had nothing to learn. Keyed reseeding gives r = 0.21: about a fifth of each label is the
decision's real effect, and a third of alternatives give exactly the same outcome.

### Reproducibility

Benchmarks are exactly repeatable: word search runs at a fixed effort
(`Candidates(effort=0.05)`: the engine's node / path / beam limits scaled, no deadline —
≈0.25 s per grid and better words than a 0.6 s deadline), and `agent.spawn_pool` pins
`PYTHONHASHSEED` so set iteration order (which breaks Advice ties) is identical in every
worker. Before this, the same seeds gave 8 vs 13 / 128 wins between two runs, and timed
search made results depend on machine load.

Fast Advice baseline (deterministic, Carpman crown 0, 256 seeds): 26 wins (10.2%). Losses:
91 of 227 in ordinary stage 4–5 encounters, at ~69% of the target on average; runs ending
with Telescope / Toolbox / Blueberries win ~30%, Ornate Key 6% — shop choice is the lever.

The earlier attempts (Monte-Carlo value net `learn.py`; rollouts to one stage ahead as
expert labels with an MLP) are kept for reference; their labels correlated only ~0.14 with
a held-out fit, and the trained networks lost to Fast Advice.

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
