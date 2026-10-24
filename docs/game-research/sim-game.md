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

`policy.tuned_config()` holds these settings; the live advisor's rollouts use it, and
`advise` prints an instant **AI pick** (tuned policy + boss risk + the newest
`sim_models/*/champion.npz`) before the rollout ranking (`--mode quick` for only that).

**All characters** (48 seeds each at crowns 0 and 2, paired on the same seeds; mean
encounters cleared):

| Character | fixed boss rule | + boss risk | + Advice fallback |
| --- | --- | --- | --- |
| Bones The Dog | 12.91 | 13.94 | 14.01 |
| Hayley Bayles | 12.40 | 12.75 | 12.53 |
| Nat-H4 | 6.46 | 6.90 | **10.40** |
| Nina Nix | 13.32 | 13.49 | 13.65 |
| Octacles | 12.34 | 12.45 | 13.21 |
| Beans | 11.82 | 12.14 | 12.14 |
| Sam Gambit | 6.33 | 7.26 | **10.70** |
| Sandy Saguaro | 10.27 | 10.75 | 10.62 |
| Human Boy | 5.60 | 6.03 | **8.82** |
| Cretaceous Meg | 11.81 | 12.32 | 12.42 |
| Rodman / Carpman | 11.65 | 12.22 | 12.28 |
| all (paired) | | +0.49 (t 5.0) | +0.96 (t 8.9) |

Then **sticker ordering** (`sort_items`: before leaving a shop, up to two swaps that add
probe-encounter points — Human Boy's hands boost the neighbouring sticker, Overhand /
Underhand and left-to-right effects depend on order): +0.44 overall (t 5.1); Human Boy
+1.48, Sandy Saguaro +1.20, Beans +0.67, Hayley +0.64. A probe-based pin side
(`pin_side="power"`) was neutral overall (+0.05, t 0.6) and stays off.

Then **spend-down** (`spend_over=20`: when Advice says leave with more than $20, buy the
item with the best probe gain or restock up to 3 times): +0.12 overall (t 3.7), wins
132 → 151 / 1,056; Bones (died with $62 unspent on average) 21 → 27, Cretaceous Meg 6 → 11.
A $40 reserve gained less (+0.04).

Then **probe-checked purchases** (`power_override=0.1`: when Advice buys, every
affordable sticker / stamp is tried in a probe encounter; Advice is overridden when an
alternative adds 10 points-percent more than Advice's pick): +0.93 encounters (t 7.0), wins
151 → 184 / 1,056; Nat-H4 +1.67, Human Boy +1.72 (3 → 11 wins), Octacles +1.61, Beans
+1.26. A 0.3 margin gained +0.78.

A 0.03 margin was slightly worse (−0.11, t −1.2) and a 4× deeper probe (4 grids × 2
seeds) no better (+0.05, t 0.4) on 8 characters.

**Speed:** probe encounters dominate run time once purchases are probe-checked (52% in the
sticker-order search, 31% in purchase checks). `PowerPolicy.power` is memoised per build
signature (items in order with levels / foil / colours / counters, rack, money, position —
identical decisions verified), the order search is skipped when the line-up has not
changed since a search found nothing. `Candidates(cheap_floor=True)` also scales the
exact-scoring floor (`max_exact_paths`) with search effort below 0.05: 279 s → 141 s per
late-crown run, for a small cost in play (−0.12 encounters, t −1.6, 24 of 96 seeds differ).
So it is opt-in: play-out continuations and long benchmarks (`expert.evaluate(cheap=True)`)
use it; live advice and decision probes keep the full floor.

**Sell-and-replace** (`swap_sell`, on by default): with every slot of a kind full no
purchase is possible, so neither Advice nor the probe check ever upgraded a full build;
the policy tries selling each owned item for each shop offer and makes the best swap
that adds more than `power_override` probe points (at most one per shop). 352 paired
seeds (32 per character, crown 0 or 2 each): +0.23 encounters (t 2.1; 135 seeds better,
111 worse), wins 134 → 141 of 352. Sam Gambit gained most (+0.87, t 2.4), Natha Servo
+0.58; Prismatic Bean −0.42 (t −1.3) is the only notable loss.

**Chasing cursed bosses** (crowns 1–8, 1,056 paired seeds): the cursed preference with the
Michael-aware stage-5 rule won 108 vs 106 never chasing (−0.07 encounters, t −1.0), so
the preference costs nothing and stays.

**By crown** (12 seeds × 11 characters per crown, all of the above): wins 52 / 132 at
crown 0, 40 at crown 1, 20 at 2, 12 / 16 / 11 at 3 / 4 / 5, 6 at 6, 1 at 7, 0 at 8.

After the shop work (fallback, probe-checked buys, sort, spend-down, sell-and-replace;
same seeds, cheap floor) the total rose from 156 to 197 of 1,188:

| crown | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|---|
| wins / 132 | 70 | 46 | 30 | 16 | 15 | 13 | 5 | 0 | 2 |
| mean outcome | 14.5 | 13.8 | 12.6 | 11.8 | 11.2 | 10.8 | 10.2 | 7.9 | 7.9 |

By character (all crowns): Octacles 35, Bones 35, Nina Nix 24, Hayley 24, Spike 17,
Sock Head 16, Prismatic Bean 15, Natha Servo 11, Sandy 11, Sam Gambit 6, Wet Dennis 3.
No run reached Michael: with no simulated Michael fights the stage-5 rule assumes 50%
Michael risk and always takes the uncursed boss (see below). Checked on the crown 1–4
seeds with `michael_prior_risk=0` (take the fifth cursed boss on the usual margin): 14 of
528 runs reached stage 5 with every boss cursed, 4 fought Michael and 2 beat him, and run
wins fell 107 → 104. Michael is roughly a coin flip for a build that got there, so the
50% prior is about right and stays; going for him trades wins for the Michael bonus.

**Carp Streamers pin side** (Rodman): one side ≥ 2 levels ahead turns the pin's build tags
mono-colour (red or blue generator), which steers Advice. Always-left (+0.16, t 0.6) and
always-right (−0.10, t −0.4) vs upgrading the lower side, 96 paired seeds at crowns 0 / 2:
no effect, so Rodman's weakness is elsewhere. Stage-5 losses across characters are mostly
near misses (median 52–87% of the final boss target reached).

**Final-shop spend-down** (`final_spend`, off): at the stage-5 X-2 shop money is worthless
afterwards, so spend to $0 (any +0.5% probe gain, up to 8 restocks, 3 swaps). 352 paired
seeds: +0.01 encounters (t 0.8), wins 141 → 145; only 54 seeds changed at all. The final
boss is not lost for want of the last purchases.

**Deeper boss search** (`boss_effort=0.15`, 3× the search in boss encounters): −0.01
(t −0.4), 35 of 352 seeds changed. Effort 0.05 already finds the boss words; the
bottleneck is the build, not word search.

**No reserve early** (spend-down with a $0 floor in stages 1–2): −0.68 encounters
(t −4.5), wins 141 → 108 of 352. Logged winners buy more in stage 1 (3.0 vs 2.3 items),
but forcing it fills slots with items that only just clear the 2% probe threshold; the
$20 reserve keeps money for the items Advice wants later. Reverted. The opposite —
spend-down buys only above 6% probe gain (`spend_threshold=0.06`) — changed 9 of 352
seeds (+0.03, t 1.4; wins 141 → 144): spend-down rarely fires, so it is not the lever.

**Losses now** (crown 0, 16 seeds per character, current base): 87 / 176 won. Losers
die with little money ($1–20, was $10–62 before spend-down) and fewer item levels than
winners (e.g. Rodman 12.1 vs 17.0, Natha Servo 13.5 vs 17.8).

**Run log and learned item value** (`itemvalue.py`): `expert.evaluate` appends every run
to `~/.cursed_words_solver/sim_models/runs.jsonl` (character, crown, config, purchases
with stage / node, shops visited, bosses fought, outcome, and any crash — crashes used to
be swallowed and counted as plain losses), so every benchmark adds training data. The
item-value table scores each purchase as the run's outcome minus the mean outcome of the
runs (same character) that reached a shop in that stage, and shrinks per key (item →
item@stage → item@stage#character; a child adds its shrunk deviation from the parent's
raw mean, so a purchase is not counted twice). `PowerConfig.item_value` /
`item_value_weight` add it to probe gains in purchase checks, fallback buys and
sell-and-replace, as a long-term prior the one-encounter probe misses. Rebuild with
`python -m cursed_words_solver.sim.game.itemvalue`. The boss-risk table learns from the
same log: `python -m cursed_words_solver.sim.game.bossrisk --from-log` counts the bosses
of lines added since its last read (`logged` in `boss_risk.json` marks the offset).

First table: 990 runs (90 per character, crowns 0–4, seeds 9,000,000+, ~4.5 h with the
cheap floor). Top: Dango, Ruler, Rex, Oden, Cursed VHS, Queen Bee, Castle (+0.8–1.0
encounters); bottom: Fried Shrimp, Piggy Bank, Pear, Automobile, Sunflower, Chips
(−0.4–0.8). Economy items rank low because the policy buys them when it is short of power.
Played as a prior (`item_value_weight=0.03`, ±3% probe gain per encounter of value) on the
352 charbench seeds: −0.07 encounters (t −1.0; 59 seeds better, 61 worse; wins 141 → 146),
so it stays off. The table mostly learns what the policy already buys when things go well;
a causal estimate needs exploration (random buys) or paired play-outs, not more of the
same runs.

**Boss draft extras:** Michael's three drafts take the option the risk table rates least
run-ending; at the stage-5 draft while chasing Michael the cursed boss is taken only if
P(survive it) × P(beat Michael) is within `cursed_margin` of P(survive the uncursed one)
(`michael_aware`; Michael's risk comes from the table once it has 10 simulated fights,
else 50%).

**Advice fallback** (`advice_fallback`): the game's own Advice (`ShopRecommendation`)
returns "no build" — no recommendation at all — until an owned item carries a build tag.
Human Boy, Sam Gambit and Nat-H4 start with none, so following Advice never bought
anything. When Advice is silent the policy buys the affordable sticker / stamp that adds
the most points to a probe encounter.

**Boss risk** (`bossrisk.py`): counts of (boss faced, run ended there) per boss, per crown
and per crown × character from simulated runs, Beta-smoothed down the chain average boss →
boss → boss at this crown → boss at this crown for this character. The draft takes the
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
4. **Gate:** each model is benchmarked at margins 0.5 / 1 / 2 on 256 fixed seeds, then
   the best margin is compared with the champion on 256 *different* seeds by a paired
   test (same seeds, deterministic runs): promoted only if the mean per-seed outcome gain
   exceeds 1.65 standard errors. (Iteration 1 was promoted by the earlier "more wins"
   rule on 56 vs 54; the loop re-checks such champions with the paired test.)

Collection checkpoints every 16 runs (`pairs_itNNN.partial.npz`), so a restart resumes
mid-iteration. Candidate lists hold each move once — Advice's suggestion and the
legal-action listing carry different labels, and comparing `Action`s with labels had put
the suggestion in the list twice (wasted pairs with an exactly-zero label).

```bash
python -m cursed_words_solver.sim.game.expert --iterations 10 --runs 256 --characters WetDennis --crowns 0
```

Resumable; `history.json` tracks every iteration, `champion.npz` is the current best.

Play-outs continue with a cheaper copy of the policy (search effort 0.02, 3 placement
squares: 9.7 s instead of 34.7 s per run; tile-placement probes dominate the cost).

### Status (2026-10-22)

Three keyed iterations (15,840 pairs) never produced a model that beats the base policy:
CV correlation fell from 0.11 to 0.06 as data grew, and the iteration-2 model lost on the
confirm seeds (−0.27 encounters, t −2.1). A linear advantage model over after-state
feature differences cannot express what makes one shop choice better (it depends on the
build, not on fixed per-item values). The loop is parked; the measurable gains came from
diagnosing specific gaps (boss risk, tile use, planner, Advice fallback, sticker order).

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
