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
| `plantest.py` | — | whole-run build plans (`PowerConfig.build_plan`) against the rules player, per character, resumable |
| `expert.py` | — | the learning loop: `NetPolicy`, state-value training on λ-returns (default) or paired full-run rollouts, ridge models, champion gating |
| `buildvalue.py` | — | long-horizon item value: leave-one-out contributions per stage, `ItemGrowth` (class growth model), survival weights |
| `chartune.py` | — | per-character settings (L3): successive-halving search over `PowerConfig` knobs on paired seeds → `char_overrides` table |

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

**Human runs, 2026-10-24/25** (Rodman c1–2, Sam Gambit c0–1, Sandy c0–1, Nat-H4 c1, Beans c1,
Bones c3; 305 captures, `scripts/record_run.py` journals of every export): the engine
now scores all 305 exactly. Two engine fixes came out of them — Mutating DNA's
`LetterUseCounts` keys are `GetStringRepresentation()` with font tags
(`<font=TTNormsPro-Bold SDF>⅖</font>`), now mapped to engine `srep` tokens
(`calc.game_srep_to_engine`), and `ScorePacket.Scale` multiplies its float32 operands in
double precision (poison 181265 × 0.1f → 18127). Through sim state 302/305 (the 3 misses
are Michael's finale puzzle, not modelled). Dynamics, 115 same-encounter pairs: money
115/115, remaining target 109/115 (the 6 misses are Michael phases with Randomise Item
Order), rack 105/115 (Sandy's manual rack placements between submits; the round log's
`placements_this_round` is not per submit, so the check cannot subtract them).

**P2 re-check, 2026-10-31** (`scripts/sim_validate.py`, all 156 shop visits / 454 captures
of the 2026-10-24/25 journals plus the older round logs; run with `PYTHONIOENCODING=utf-8`):

| check | result |
|---|---|
| `scoring` | 451/454 (the 3 misses are Michael's finale) |
| `dynamics` | unchanged from 10-24 (money, rack, target as above) |
| `grids` | in distribution once rack tiles already placed (`was_consumable`) are skipped; the leftovers are the 14 old-export Octacles/Bucket grids of 2026-10-11 and 3 chance outliers |
| `clears` (new) | 156/156: replaying the winning submit from a capture gives the next shop / boss reward's money, rack size, stickers (with RAM memory, money invested, foil), stamps and pin |
| `shops` (new) | base price (`GetCost`) 3566/3566 after the fix below; restock price 149/156 (the 7 are first-shop-of-stage exports taken after a restock) |

- Fixed: Northern Cardinal's −$4 applies when `GetDescription()` contains "red" in any
  case, so "coloured" and "Scattered" count. The sim only looked at colours and tags and
  missed 15 classes (Parrot, Ferris Wheel, Chess Board, Traffic Lights, Rainbow Sprinkles,
  Magnet, Saxophone, …: `items._RED_IN_DESCRIPTION`, from a decompile scan of description
  literals).
- Export notes: the shop offer's `price` is always 0 (not checked); `restock_cost` is
  `_rerollPrice` *before* Fried Shrimp's −1 (the sim's `reroll_price`, as the game does).
- Stock on entry vs 50 sim shops from the same state: 27 items the sim offers ≥ 2.5 times were
  never offered (Sticking Plaster, Black Hole, Dragon, Castle, Ogre, Wriggly Worm, Radio,
  Crystal Ball, Dartboard, Chick, Axe, …). Every one is unlock-gated (achievement, crown
  reward or challenge) and locked on the user's save. The sim stays "everything unlocked" by
  design. The locks also shrink the real tag pools, which plausibly explains the small
  deficits in tag-matched stickers (245 vs 274, z −2.8) and Common stamps (196 vs 211, z −2.9).
- **Closed 2026-11-02: upgrade offers of owned stickers.** The validator counted 17 real vs
  39 simulated (z −4.0), almost all in shops with 5 stickers. The sim was right, and the
  validator's choice of shop entry was wrong:
  - **Selection.** 37 of the 156 "entry" exports came after a buy or sell, and 7 after a
    restock. The game nulls a bought slot, and buys favour upgrade offers, so those exports
    lose exactly the offers being counted. `shops` now compares stock only on clean entries:
    no restock yet, and the same items as the export before. On those 112, stamp Common and
    tag-match deficits vanish (z −0.3, −1.5); sticker upgrades are 15 vs 26.2 (z −2.5).
  - **Ground truth from the game's own log.** `GetRandomBuildBiasedSticker` logs each
    branch, and `ShopItemSlot.Populate` logs "No space" (5 stickers) for each slot.
    `sim_validate.py gamelog` reads Unity's Player.log / Player-prev.log (the last two
    sessions; the 2026-10-25 pair is kept in `~/.cursed_words_solver/game_logs/2026-10-25`, pass `--game-log-dir`):
    - Dependency roll: 64 / 732 = 0.087 (1 in 10 expected, z −1.1).
    - Upgrade roll with 5 stickers: 37 / 427 = 0.087 (z −0.9).
    - A roll finds a non-max sticker 28 / 37 = 0.76 of the time; the sim gives 0.82 on the
      clean entries.
    - All 17 rolls with fewer than 5 stickers stop at "Player stickers not yet full", as
      the code says.
  - **Slot by slot.** I aligned the log's slots with the 23 clean five-sticker entries it
    covers (by item name and index). The game rolled the upgrade 5 times against the sim's
    7.7 expected, and returned 2 offers against 5.7. Each of its 3 empty rolls fell in a
    state where the sim also has no candidate: every sticker maxed, or the one non-max
    sticker frozen in stock. Owned offers from the other branches are 3 vs 2.9.
  - **What's left** of the deficit on clean entries is the dice: fewer upgrade rolls than
    average in these sessions. The sim is unchanged.
- Coverage: the AI buys 227 classes, real data has 107; 144 were never seen. Of the
  AI-frequent ones with < 5 real captures, Radio, Wriggly Worm, Numbers Bunch Of Grapes,
  Dartboard, Chick, Axe, Television, Arrivals and Crystal Ball are locked on this save
  (Radio = Nat crown 4, Wriggly Worm = Sam crown 4, Arrivals = Nat crown 5, Grapes = Hayley
  crown 6, Crystal Ball = Octacles crown 6). Their ports are checked against the decompile only.

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

**Encounter planner from stage 4** (`plan_encounter=True, plan_from_stage=4`, rerun
2026-10-28 after the Michael and engine fixes): −0.02 encounters (t −0.4), wins 140 → 140
of 352, 101 seeds better / 117 worse. Per character −0.26 (Sandy) to +0.30 (Beans); only
Natha Servo is significant (+0.28, t 2.1, 9 → 12 wins), which is what one of 11 should
show by chance. Off; benchmark NetPolicy still runs without the planner.

**Pin side per decision** (2026-10-28/29, 16 seeds × 11 characters, crowns 0/2, paired
with the lower-side rule). `NetPolicy` with `pin_side="rollout"` plays each side forward on
the same keyed futures (`play_out`) and logs every decision (`pin_log`: state, left/right
difference incl. Random Access Memory's offered item and the Bucket's offered tile, both
results) for `pinplan.py`'s learned model.
- Played to the end of the run (`pin_horizon=0`, 2 futures per side): +0.14 (t 0.8), 77 vs
  70 wins. The two futures of one decision agree on the better side at chance (corr −0.006),
  so these picks were coin flips and the model trained on them sits at chance.
- Label study (85 decisions, 4 futures per side): build strength after one stage (Σ score /
  target + progress + alive) is repeatable (split-half corr 0.67; two stages 0.53), and the
  better side flips with the situation inside every character (an Octacles Bucket offer
  +55, Bones stage 3 +13.9 one run, −10.4 another).
- One-stage strength (`pin_horizon=1`): overrides the lower side in 46% of decisions,
  winning that stage by a median 1.1 strength, but −0.05 encounters (t −0.35), 71 vs 70
  wins. Next-stage strength does not convert into run wins, and the model cannot predict
  those labels from the state either (CV agreement 0.54). Default stays `pin_side="lower"`.
- Headroom (same seeds, always one side): always left −0.02 (t −0.09), 73 wins; always
  right −0.21 (t −1.08), 68 wins; no character beyond |t| 1.7. All five pin rules land at
  68–77 wins and 13.65–14.01 mean, inside noise. The pin side as a whole moves a run by less
  than ~0.4 encounters. A max-over-arms "oracle" reaches 121 wins, but that is chaos: any
  changed decision reshuffles the run's future (per-seed sd 1.26 across arms), so it is not
  reachable headroom. With the current policy the pin side is not where wins are, so it stays
  "lower" for now; choosing it per situation should matter once the rest of the play is
  strong enough to use it (revisit then, especially at higher crowns).

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
run-ending; at the stage-5 draft while chasing Michael the cursed boss is taken when
P(survive it) × (1 + `michael_value` × P(beat Michael)) is within `cursed_margin` of
P(survive the uncursed one) (`michael_aware`; Michael's risk comes from the table once it
has 10 simulated fights, else 50%).

**Michael scoring (2026-10-24):** losing to Michael is still a run win — the game records
the crown as beaten when the fifth cursed boss falls (`GoToNextSceneCoroutine`:
`UpdateHighestAscensionBeaten` before the Michael scene). The sim used to end such runs as
losses; now they end `won=True, end_reason="michael_lost"` (outcome 16), and beating him
scores 16 + `features.MICHAEL_BONUS` (8: a full win is worth 1.5 plain wins; was +4).
`michael_value` (0.5) is the same bonus in run wins for the boss draft. `boss_outcomes`
also records Michael fights (`MichaelBoss`, ended the run = lost to him); before, none
were recorded, so the draft always used the 50% prior. The Michael test above predates
this: its 2 Michael losses were counted as lost runs.

**Michael after the fix** (2026-10-29, crowns 1–4, the same 528 seeds, current base,
`michaelbench.py`): 106 wins (45 / 30 / 16 / 15 by crown; 104 before the fix, which
counted Michael losses as lost runs). Only 10 runs reached the stage-5 draft with every
boss cursed. There the rule took the cursed boss 8 times: 6 reached Michael and 3 beat him,
so the 50% prior holds. Each of those 10 decisions was also played both ways to the end of
the run on 3 keyed futures, through stage 6's shops and encounters before Michael:
- cursed better in 5 (+0.1 to +8), worse in 3 (−0.2 to −0.8), tied in 2;
- the rule picked the worse option only twice (Nina Nix −0.8, Sock Head −0.4);
- its picks average +1.8 outcome per decision over always taking the uncursed boss.

The stage-5 rule is sound. The limit is how rarely a run is still all-cursed at stage 5 (2%).

**Rack tiles** (2026-10-29). Base play leaves almost every shop tile alone: 20 bought of
944 offered in 22 runs. A probe lift study (44 offers, 3 runs) put the median offer at
+1.6% to one grid's best word and the 90th percentile at +18%. `tile_buys` buys the
offer with the best probe lift ≥ 10%. `tile_save` places the least valuable rack tile
within 85% of the best placement gain. Both on, 16 seeds per character against base:
−0.30 (t −1.98), 66 wins vs 70, 42 better / 47 worse; Spike +0.70 (t 3.5), Natha Servo
−0.88 (t −2.4), Sock Head −1.78. One likely cause is that the buy keeps only $5 and runs
before spend-down, which keeps $20, so tiles take money that would otherwise buy items.
Each on its own:
- `tile_save` alone: +0.001 (t 0.3), only 5 of 176 runs differ. Base play rarely holds two
  rack tiles at once, so there is seldom a choice.
- `tile_buys` with `tile_reserve` 20 (money above the spend-down floor only): −0.001
  (t −0.01), 10 better / 6 worse; Spike 5 → 9 wins again (+0.35, t 2.1). On all 32
  cached Spike seeds: 13 → 18 wins, +0.24 (t 2.5), 6 better / 0 worse.

`tile_save` stays off. Buying is on for Spike only (`tile_buy_chars`, in the benchmark
policy and `tuned_config`), and `tile_reserve` now defaults to 20.

**Stamp order** (`sort_stamps`, 2026-10-30): the order search also tries stamp swaps (Right
Human Hand boosts the stamp to its right, Underhand targets the sticker in its slot, stamps
apply left to right), up to 4 swaps per shop. 16 seeds per character vs base (Spike vs its
tile-buying base): +0.02 (t 0.2), 69 vs 74 wins, 28 better / 34 worse. Only Sock Head
(Human Boy, whose hands are order effects) stands out: +0.93 (t 1.7). On his 32 cached
seeds: 9 → 15 wins, +1.31 (t 2.4), 13 better / 3 worse, so it goes on for Sock Head only.

**Michael route** (2026-10-30, crowns 1–4, 6 seeds per character × crown = 264 runs of the
Michael bench seeds; base = those runs, Spike rerun with its tile buying; 9 of 10 rerun
check seeds reproduced exactly). `route_value`: in stages 1–4 while every boss was cursed,
the cursed option is worth (1 − risk) × (1 + `michael_value` × P(beat Michael) × P(surviving
the remaining floors at the average cursed risk, 0.20)) against the uncursed one's
(1 − risk) − `cursed_margin`. `ogre`: buy Ogre while chasing (it curses both options of its
floor and the next while held) and never otherwise. Both on:
- all-cursed through five bosses 47 of 264 runs (base ≈ 2%); reached Michael 4 → 23, beat
  him 3 → 5;
- but run wins 57 → 50, outcome −0.12 (t −0.7). About half of the all-cursed runs died at
  the fifth cursed boss. Ogre (bought in 58 runs) held through stage 4 curses the stage-5
  draft, so the stage-5 rule never got to pick the safer boss.
Now `ogre` sells Ogre from stage 4 on and buys it in stage 4 only while that floor still has
an uncursed option. Rerun on the same seeds (base 57 wins, Michael reached 4, beaten 3):

| arm | outcome | wins | reached Michael | beat Michael |
|---|---|---|---|---|
| route + Ogre held | −0.12 (t −0.7) | 50 | 23 | 5 |
| route + Ogre sold in stage 4 | −0.09 (t −0.6) | 51 | 23 | 5 |
| route alone | −0.03 (t −0.2) | 53 | 22 | 5 |

Ogre adds nothing over the route rule (it reaches Michael just as often without it) and
costs a stamp slot, so `ogre` stays off. The route rule is outcome-neutral: about 4 plain
wins (mostly crown 1) traded for 5× the Michael fights and 2 Michael wins. The user chose
more Michael fights: `route_value` is on in the benchmark policy and `tuned_config`; base
caches from before 2026-10-30 predate it (and Sock Head's stamp order).

**Build-aware boss risk** (`bossmodel.py`, `boss_model`, 2026-10-30). The risk table knows
how often a boss ends runs on average, not how the build in hand does against it.
`PowerPolicy.boss_strength` probes the build under each draft option's rules (2 probe
encounters × 3 greedy grids: points per grid × that fight's grids / its target; 0.1 s per
option). Training data (`bossdiag.py`, 352 base runs, crowns 0–7, seeds 9,500,000+): at every
boss draft both options were fought once from the same state, so each option has a label
(2,606 options, 351 fights lost). A logistic regression on log strength, logit table risk,
cursed, stage and crown, 5-fold by run:

| predictor | log loss | AUC | picks the cleared option* |
|---|---|---|---|
| table risk | 0.382 | 0.62 | 80% |
| table + cursed / stage / crown | 0.282 | 0.87 | |
| probe | 0.155 | 0.96 | 88% |
| all | 0.146 | 0.97 | 90% |

\* the 137 drafts where one option's fight was cleared and the other lost; the base
policy's own picks got 63% (the route rule takes riskier cursed bosses on purpose).
`python -m cursed_words_solver.sim.game.bossmodel <logs>` refits and saves
`sim_models/boss_model.json`. First benchmark (264 new seeds, crowns 0–7, vs a fresh base
with `route_value` on): +0.08 (t 0.6), wins 52 → 54, Michael reached 14 → 19. 264 more
seeds: +0.06 (t 0.5). All 528: **+0.07 (t 0.8)**, wins 97 → 104, Michael reached 26 → 37,
beaten 5 → 11, 137 better / 127 worse. Crowns 0–3 +0.12 to +0.34, crowns 4–7 −0.18 to
+0.11; Sock Head +0.57, Octacles +0.29 (wins 16 → 22), Sandy Saguaro −0.26, Sam Gambit
−0.17 (all within noise per character). Small, same sign in both halves, not significant;
runs are ~15% slower (probes at each boss draft). **On by default** (user's choice, 2026-10-30): `tuned_config` and
`NetPolicy` use `sim_models/boss_model.json` when it exists (pass `boss_model=""` for the
table only), so base caches before this predate it.

**Long-horizon item value** (`buildvalue.py`, `build_value`, 2026-10-30). The shop judges a
buy by its gain at the next encounter. `buildvalue collect` (132 base runs, crowns 0–3, seeds
9,700,000+) measured each owned sticker / stamp's leave-one-out contribution (probe with it /
without it − 1, same probe grids) when bought and at every later SHOP_TWO: 2,096 items. The
gain at purchase predicts later contribution weakly (held-out R² 0.17 of log(1 + c)); adding
the item class gives 0.39, and 0.52 (corr 0.72) on all ordered pairs. For 30% of pairs of
items bought at the same stage, the bigger gain at purchase is worth less later. Growers:
Radio, Haunted Mirror, Cursed VHS, Tombstone, Amphora, Rolodex (+0.4 to +2 at purchase,
many × the build later); faders: Briefcase, Ham Sandwich, Candle, Head Trauma (+1 to +1.5,
then ~0). `ItemGrowth` (ridge on log(1 + c_t) ~ log(1 + c_u), t − u, u, class offset and
class × (t − u), λ by CV) turns a gain into the contribution averaged over the stages left;
`build_value` uses it for Advice overrides, fallback buys and swaps. Benchmark (528 seeds,
crowns 0–7, vs the boss-model base): **−0.11 (t −0.8)**, wins 104 → 101, Michael reached
37 → 38, beaten 11 → 11, 225 better / 239 worse; first 264 −0.18, second −0.04. Crowns 0–2
−0.54 (t −2.2, wins 80 → 67), crowns 3–7 +0.15 (t 0.9, wins 24 → 34, Michael reached
10 → 15); that split was found after looking, so treat it as a lead. Bones +0.44 (wins
16 → 22), Nina Nix −0.50 (13 → 8), Wet Dennis −0.49, Hayley Bayles −0.42 (per character all
within noise). The fit's residuals show no crown trend on crowns 0–3, so a crown feature
alone is unlikely to explain it; a likelier reason is that surviving the next fight matters
more where the base already wins often, and a stage-averaged value discounts it. **Off by
default.**

**Survival-weighted** (`build_value_risk`, 2026-10-30): weight each stage's predicted log
contribution by P(losing one of its remaining fights) instead of uniformly (d log P(clear) /
d log strength ∝ P(lose) under a logistic). `buildvalue.stage_weights` takes the probe
strength at the next fight (points per grid × 5 / target), projects it to each later fight
by its target and the usual build growth per stage (×3.25, 2.27, 2.52, 1.67 from SHOP_TWO
to SHOP_TWO, 132 base runs) and uses P(clear) = σ(3.63 log strength − 0.434 stage + 1.94)
(2,606 boss-draft options of bossdiag). In play the weights follow the risk: early in a
run nearly all on stage 5, nearer stages when the build falls behind. Benchmark (528 seeds
vs the boss-model base): **−0.32 (t −2.1)**, wins 104 → 101, Michael reached 37 → 35, 215
better / 271 worse; first 264 −0.47, second −0.17; negative at every crown (crowns 0–2
−0.35, 3–7 −0.31) and −0.21 (t −1.6) against uniform `build_value`. Likely cause: early
in a run it judges items almost entirely by the growth model's stage-5 prediction, the
farthest extrapolation (stage 1 → 5) from the thinnest data (survivors only), so it buys
on the model's least reliable output. **Off.** Both variants say the one-encounter probe
plus Advice beats a class-level growth model; a long-horizon value would need to be
learned on the outcomes of runs (L1), not extrapolated per item.

**Per-character settings** (`chartune.py`, L3, 2026-10-30). `PowerConfig.char_overrides` maps
a character (or "Character@lo-hi" for a crown band, applied after the character's own entry)
to any settings that differ from the base; the policy switches to them at the first action
of a run (`PowerPolicy._tune`), and `NetPolicy(char_tuning=path)` loads a table. With no
overrides play is unchanged (stored base runs reproduce). The tuner tries, per character,
every single-knob change to that character's current settings: `buy_threshold`,
`power_override` (1.0 = follow Advice), `spend_over`, `reroll_reserve`, `money_weight`,
`michael_value`, and flips of `swap_sell`, `final_spend`, `route_value`, rack-tile buys and
stamp sorting. Successive halving on paired seeds (crowns 0–7, seeds 7,000,000+, apart from
the benchmark): 13 arms × 16 runs, the best 5 (if ahead) × 32 more, the best 2 × 48 more;
promote when ahead over all 96 by t ≥ 2 and on the last 48 alone (not used to select it).
A paired difference has sd ~3.3, so one pass detects effects of about +0.7 outcome per
character; each further pass (`--passes`) draws new seeds and re-tests every knob against
the new champion. ~560 runs per character, ~2.9 h; one pass over 11 characters ~32 h,
resumable (`runs.jsonl` in the work dir, table rewritten after each character).

```bash
python -m cursed_words_solver.sim.game.chartune run ~/.cursed_words_solver/chartune --passes 1
python -m cursed_words_solver.sim.game.chartune show
```

**Run speed** (P1, 2026-10-30). Profile of one benchmark run (Nina Nix crown 2, 113 actions,
357 s under the profiler): 97% word search, 92% of it the shop's probes (`power`, 418
builds; sticker sorting and swaps alone ~70%); playing the encounters themselves 16 s.
Enumeration was 2/3 of a search, and probes search the *same* probe grid under many
loadouts: of 471 enumerations in 60 actions only 144 were distinct. Enumeration reads only
the tiles, grid shape, movement / letter items (`_MOVE_CLASSES | _LETTER_CLASSES`) and their
colours, word-length limits, challenge, tries and budgets, not scoring items, money or item
states, so `ExactSearch._enumerate_all` reuses it for an identical `_enum_key` (64 boards
kept per process; deterministic searches only, never with a deadline). The quest rank is
also resolved once per search (`search_rank_function`) instead of per candidate. Three
full runs played identically to the old code (every action equal), CPU 463 s → 262 s
(×1.46 to ×2.2, ×1.77 overall). Left: exact scoring (~40% of a search now), enumeration of
new boards, beam search; cutting further means cheaper probes, which changes play and
needs a benchmark.

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

### Full action space and state features (P3 / P4, 2026-10-31)

**Actions (P3).** `NetPolicy(action_space="full")` (the default) lists shop options with
`full_shop_candidates` instead of the Advice-based `shop_candidates`. The Advice
suggestion comes first, then leave (saving the money) and a restock. After those, five
groups are dealt round-robin up to `SHOP_CANDIDATES` = 16, so no group crowds the others
out:

- every buy (tiles and Hungry Hippo feeds included)
- **sell-then-buy swaps** (`Action("sell_buy", (kind, owned slot, offer))`, one step in
  `agent.apply`), for offers that only fit once an owned item of that kind is sold, when
  the sale pays for them
- freezes and unfreezes
- plain sells
- **reorders** (a swap of two slots; scoring order matters)

Before this, the learner never saw a sell, a swap, a reorder or a freeze it wasn't
suggested. The boss draft, pin reward and Michael's draft already listed every legal
option. Word play inside an encounter (words, skips, grid rerolls, rack tiles) stays
with the search.

- About 13.5 candidates per shop state; candidate listing plus after-states cost ~70 ms
  per shop decision, mostly the Advice suggestion.
- Without a model, play is action-for-action identical to the old space (2 seeds
  checked), so benchmarks of the base policy do not move.
- Training pairs draw their alternative group-first (`sample_alternative`), so the many
  reorders and freezes do not drown the rarer, bigger choices.
- `afterstate` drops an action whose `apply` returns False (a swap whose buy fails).

**Features (P4, `features.py` v4; 1035 → 2088 columns).** Appended, so older pair files pad
with zeros, and saved models read the prefix they were fitted on (`learn.fit_width`; the
pin model splits its `(x, dx)` halves at its own width). Added:

- crown one-hot
- boss targets of the next two stages and the final one; stages and encounters left
- Michael's route (crown ≥ 1 and no uncursed boss faced) and cursed bosses still needed
- economy: free slots, inventory sell value, money invested, and in a shop the restock
  cost, Angel Investment and free pick
- generator present; rare and legendary counts
- build-synergy tag rank and unmet dependency tags
- per class:
  - `pos:` slot position, so reorders are visible
  - `ivar:` signed log of component values (growth)
  - `ictr:` log of the item's state counters (`fields`, transient `_` ones left out)
- **shared per-class descriptors**: `item_descriptors()` is a static vector per class
  (tags, function tags, dependency tags, relevant colours, rarity, sticker / stamp,
  food / animal, unsellable, log cost). `desc:*` is that vector summed over the inventory
  by level, so a rarely seen class is valued through what it shares with common ones.

**No shop stock in the features, on purpose:** a restock's after-state is built on a clone
whose RNG then deals the real next stock. Seeing it would let the model peek at a draw
the game hides until you pay.

### Benchmarks, resumable training, cheap rule tests (P5 / P6 / P8, 2026-10-31)

**Benchmark tool (`bench.py`).** One scoreboard for every policy change, replacing the
scratchpad scripts:

```
python -m cursed_words_solver.sim.game.bench run <arm> --cfg '{"finish_early": 0.75}'
python -m cursed_words_solver.sim.game.bench compare <base> <arm>
python -m cursed_words_solver.sim.game.bench show <arm>
```

- An arm is `NetPolicy` plus `PowerConfig` overrides, an optional model and margin,
  per-character settings and the action space.
- Every arm plays the same 528 runs: 11 characters × crowns 0–7 × 6 seeds, seed
  8,000,000 + 1000 × character + 100 × crown + i.
- `compare` reports, run by run: mean, t, wins, Michael reached / beaten, and better /
  worse. It breaks these down overall, by seed halves (a replication check), by crown and
  by character.
- Runs go to `~/.cursed_words_solver/bench/<arm>.jsonl` as they finish, so rerunning the
  command resumes. `<arm>.json` keeps the arm's settings; reusing a name with other
  settings is refused.
- Each run stores a fingerprint of the package source. `compare` warns when the two arms
  ran on different code. The scratchpad base (`bm_arm.jsonl`) predates the Northern
  Cardinal fix, so it can't be a base any more.

**Resumable training (`expert.py`).**

- Data runs were already checkpointed every 16 runs.
- **Fixed:** an iteration counted as done as soon as its data file existed, so a restart
  between data and benchmark skipped that model's benchmark and promotion altogether. Now
  an iteration is done only once its `history.json` row is written, and a finished data
  file is reused.
- Every benchmark run goes to `evals/<seed set>_<model>_<margin>.jsonl` and is reused.
  Before, a restart lost the whole benchmark. A model is named by a hash of its arrays,
  since `.npz` files carry their write time.
- `history.json` and the chartune table are written atomically.
- Each promoted model is kept as `champion_it<n>.npz`.
- `config.json` refuses a rerun with other characters, crowns or run counts (they would
  change the seed sets).

**Cheap rule tests (P8).** E5 is on by default since 2026-10-31 (`finish_early` 0.75); S3 is off:

- **E5 `finish_early`:** each unused grid pays $2. When the best word doesn't clear, reroll
  the grid for one that does, if the best reaches `finish_early` × what is still needed.
  On the last grid it always rerolls (rerolls left): there the old rule played a word
  that doesn't clear, which loses the run, whenever it reached 0.55 of the need.
- **S3 `late_swaps`:** sell-and-replace swaps allowed per shop from `late_swap_stage` (4).
  Otherwise 1, or 3 in the final shop (`_swap_limit`).

**Results (2026-10-31, 528 paired seeds, same code `00ce3dc755`, against base `{}`):**

| Arm | Mean / run | t | Wins | Michael reached / beaten | Halves (t) |
|---|---|---|---|---|---|
| E5 `finish_early` 0.75 | **+0.245** | +2.02 | 104 → 110 | 37 → 35 / 11 → 9 | +1.15, +1.66 |
| S3 `late_swaps` 3 | −0.047 | −1.26 | 104 → 103 | 37 → 35 / 11 → 9 | −1.66, −0.12 |
| Spike `swap_sell` off (chartune), Spike's 48 runs | −0.195 | −0.48 | 10 → 8 | 1 → 1 / 1 → 0 | −0.36, −0.40 |

- E5 is a small gain that holds in both seed halves. It is strongest at crowns 2 and 5 and
  slightly negative at crown 0. Michael wins don't improve (11 → 9, within noise).
- S3 changes only 62 of 528 runs and doesn't help. It stays off.
- The only setting chartune's first pass promoted (it ran before the Northern Cardinal fix)
  doesn't hold up on current code. The table is not enabled.
- With E5 on by default, a `{}` arm now plays E5, and arms run on earlier code are no longer a
  valid base (`compare` warns on a code mismatch). The chartune `runs.jsonl` and the training
  `evals/` caches don't record the code they ran on. Start a fresh work dir for them after a
  play change.

### State-value training (2026-10-31)

`expert.py --target value` (now the default) learns a **state value** instead of an
advantage. The paired loop above never beat the base: labels were ~21% signal, and every
label cost two full play-outs.

- **Acting.** `NetPolicy` values the after-state of each candidate. It switches from the
  Advice suggestion when one is worth more than a margin (0.1 / 0.3 / 0.6 outcome units are
  benchmarked). Shop stock is not a feature, so a restock only looks like money lost. A
  suggested restock stands, and the model never picks a restock over the suggestion.
- **Data.** The champion plays runs and takes a random alternative at `--epsilon` (0.1) of
  its decisions, group-first like the pairs. The after-state of every run-level decision is
  stored in order (`states_it<n>.npz`: features, run, shop visit, explored, crown, outcome).
  One run costs one run and yields every decision's state.
- **Labels.** λ-returns (`lambda_returns`, `--td-lambda` 0.8):
  - the last state of a run gets the run's `outcome`
  - inside one shop visit, a state takes the next state's label
  - between visits, (1 − λ) × the model's value of the next state + λ × its label
  So the label leans on the model for the far future rather than the noisy final outcome.
  The plain Monte-Carlo value (`learn.py`, R² 0.3) lost to Advice.
- **Fit.** `train_value`: ridge on every state so far, folds grouped by run, with Gram
  matrices per fold (`_FoldGram`), so relabelling costs one solve.
  - Sweep 0 labels with the outcome.
  - Each later sweep (`--sweeps` 3) relabels from the previous fit's out-of-fold values, so
    no label uses a model that saw its own run, and refits.
- **Reported fit.**
  - Out-of-fold R² against the outcome.
  - `r2_within`: R² after removing the (crown, stage, node) means, the part the build has to
    explain. Benchmarks are skipped below 0.01.
  - `pairs_corr`: correlation of the model's predicted difference with the old keyed paired
    play-outs (`--check-pairs`, Carpman crown 0). An independent, causal check of the
    decisions it would make.
- **Gate and resume.** The same as the paired loop: margins on the eval seeds, paired
  promotion test on the confirm seeds, every step resumable. The default directory is
  `sim_models/value`.
- **Caveat.** The value is linear in the features. v4's synergy / unmet-dependency /
  descriptor columns carry some interactions, but a build whose worth depends on item
  combinations beyond those is out of reach of a ridge model. If the pilot shows the fit
  stalling, the next step is an MLP value (many more, less noisy labels than the pairs
  had).
- **Pilot tools.** `--collect-only` plays and stores the iterations' data runs with no fit
  or benchmark. A later normal run in the same directory reuses that data. `--curve
  128,256,512` refits on the first n stored runs for each `--curve-lambdas` value and plays
  nothing, so you can see whether the fit still improves with data and which λ labels best.
  The smoke run used 16 runs (WetDennis / Spike, crowns 0–1): ~75 states and ~115 CPU-s
  per run.

**Pilot (2026-10-31):** 512 runs by the base policy with ε 0.1, all 11 characters, crowns
0–7 (`sim_models/value_pilot`). 28,196 states and 51 wins. Collection took 60 min on
8 workers, ~56 CPU-s per run (~55 states each).

| Runs | λ | R² | R² within crown / stage / node | Pair corr. |
|---|---|---|---|---|
| 128 | 0.8 | 0.51 | 0.156 | 0.015 |
| 128 | 0.95 | 0.54 | 0.180 | 0.019 |
| 128 | 1 (Monte Carlo) | 0.48 | 0.034 | 0.017 |
| 256 | 0.8 | 0.54 | 0.245 | 0.024 |
| 256 | 0.95 | 0.53 | 0.219 | 0.021 |
| 256 | 1 | 0.47 | 0.131 | 0.016 |
| 512 | **0.8** | 0.53 | **0.249** | **0.043** |
| 512 | 0.95 | 0.49 | 0.198 | 0.034 |
| 512 | 1 | 0.48 | 0.155 | 0.029 |

- λ-return labels clearly beat the Monte-Carlo outcome: R² within 0.25 vs 0.16 at 512 runs.
  λ 0.8 is the best setting.
- R² within levels off for the linear model (0.245 → 0.249 from 256 to 512 runs). The
  causal check keeps rising (0.015 → 0.024 → 0.043), but it is small.
  - The pairs are Carpman crown 0, a character the pilot never played.
  - Their labels are 21% signal, so ~0.46 is the most any model could reach.
- Part of R² within is luck that is already visible in the state (money, a run going
  well), not the value of a decision. Only the benchmark can say whether it plays better.

**MLP value (2026-10-31).** `--compare-mlp "64;128,64"` trains ridge and MLPs on the same
80% of runs and scores them on the other 20%. `--value-model 64` trains with an MLP.

- Plain MLPs relabelled by their own sweeps lose to ridge: R² within 0.11–0.16 vs 0.27.
  They over-fit 410 runs of near-duplicate states, and their labels are worse.
- The recipe now in `train_value_mlp`: one hidden layer of 64, weight decay 0.1, trained on
  the ridge's λ-return labels. On 4 held-out splits it is a coin flip against ridge: −0.022,
  +0.030, +0.003, −0.047.
- An earlier quick test looked like a consistent +0.02. It labelled from the ridge's
  in-sample values, a shortcut the trainer doesn't take, so that gain wasn't the network's.
- At 512 runs, model capacity isn't the limit: ridge stays the default. Re-test once
  training has gathered thousands of runs.

**Benchmark of the pilot model (2026-11-01): it loses at every margin.** The ridge model was
fitted on all 512 pilot runs and played the gate's 256 eval seeds (all characters, crowns
0–7). The confirm step was stopped once the outcome was clear.

| Policy | Wins | Mean outcome |
|---|---|---|
| Base (Fast Advice) | **37** | **11.36** |
| Value model, margin 0.6 | 22 | 10.59 |
| Value model, margin 0.3 | 20 | 9.79 |
| Value model, margin 0.1 | 5 | 8.24 |

The more decisions the model makes, the worse the play. One run's overrides (seed
77700001, margin 0.1, 29 overrides) show three failure modes:

1. **Advice's swaps are refused** (7 of 29 were sell → leave). Advice swaps in two steps,
   sell then buy, and the model values the after-state of the sell alone: an item gone,
   nothing in its place. A suggested swap needs to be valued as the `sell_buy` it is.
2. **Confounded features.** The model prefers expensive buys (Rolodex $18 over a probe-
   checked Crystal Ball at $0) and freezes the very item Advice says to buy. In
   on-policy data, money invested, sell value and frozen stock mark runs that were
   already going well. They don't make runs go well.
3. **Churn / optimiser's curse.** A shop visit goes freeze → reorder → freeze → buy, each
   step +0.2–0.3 predicted. The best of up to 16 candidates is the one the model
   overrates most, and most predicted gains (0.2–0.7) are inside the model's error.

The causal check warned of this: a 0.04 pair correlation means the model's differences
between after-states barely point the right way, even though R² within (0.25) looks
fine. R² within measures how well the model recognises good states, not whether it can
rank actions.

**Fixes for those three failure modes (2026-11-01), and the result: closer, still a loss.**

- `VALUE_KINDS`: the model decides only buys, Hippo feeds, swaps, leave, boss picks, pins
  and Michael picks. Freezes, reorders and restocks stay Advice's, which ends the churn.
- Swaps are valued whole: a suggested sell followed by its planned buy (`_pending_buy`) is
  valued as the `sell_buy` it is.
- `VALUE_DROP`: the fit leaves out `frozen_n`, `log_sell_value`, `log_invested`,
  `shop_restock_cost` and every `frozen:` column. Those mark runs already going well; they
  don't make runs go well. The MLP zeroes their input weights.

Refit on the same 512 pilot runs (`model_fixed.npz`): ridge 100, R² within 0.267,
pairs_corr 0.034. Same 256 eval seeds, paired against the base:

| Policy | Wins | Mean outcome | Paired Δ / run |
|---|---|---|---|
| Base (Fast Advice) | **37** | **11.36** | |
| Fixed value model, margin 0.3 | 35 | 10.69 | −0.67 (t −3.26; 89 better, 140 worse) |
| Fixed value model, margin 0.6 | 27 | 10.88 | −0.48 (t −2.84; 83 better, 134 worse) |

At margin 0.3 the fixes cut the win gap from 17 to 2, but the model still loses on outcome at both margins, and the loss is broad.
By crown (margin 0.3): 0 −0.49, 1 +0.81, 2 −1.27, 3 −0.88, 4 −2.38, 5 +0.11, 6 −0.73,
7 −0.38. Only Octacles comes out ahead (+0.38); Prismatic Bean (−1.72), Wet Dennis (−1.32)
and Sock Head (−1.15) lose the most.

**Feature sets don't rescue it** (offline, same states, out-of-fold):

| Feature set | Live columns | Best R² within | pairs_corr |
|---|---|---|---|
| Current (spend / frozen dropped) | 910 | 0.267 | 0.034 |
| − `pos:` | 652 | 0.268 | 0.036 |
| − `pos:` / `foil:` / `ivar:` / `ictr:` | 461 | 0.263 | 0.044 |
| Shared only (no per-class columns) | 201 | 0.245 | 0.011 |

Every variant recognises good states about equally well, and none ranks actions (pair
correlations of 0.01–0.04, against a reliability ceiling of about 0.46). An MLP (64 hidden)
is no better than ridge (see above).

**Conclusion:** a state value fitted to on-policy outcomes can't pick between a shop's
candidates. The after-states of two candidates differ in a handful of columns, and what
those columns are worth is confounded with how the run was already going. Exploration at
ε = 0.1 is too thin to break that confound. Whatever replaces it needs causal labels: paired
play-outs from the same state (the keyed `pairs` target, label noise permitting), a much
larger ε on fewer decisions, or a value trained off-policy on many randomised decisions per
state. The value model stays opt-in (`--target value`); default play is unchanged.

### Randomised decisions (`--target rct`, 2026-11-01)

The value model's failure points to causal labels. The new target collects them at the
cost of one run per run, and needs no paired play-outs:

- **Trials.** In each data run, `--p-random` (default 0.15) of the champion's run-level
  decisions are trials (`NetPolicy._trial`). A trial keeps the champion's own choice
  (`--control`, 25% of trials) or takes a random alternative, picked group-first. Both
  after-states are stored (`rct_it*.npz`: `t_xa` control, `t_xt` taken). Only choices whose
  after-state shows their effect take part (`VALUE_KINDS`), and Advice's swap step counts as
  the whole swap. About 10 trials per run.
- **Label.** The run's final outcome minus a baseline: the λ-return state value (fitted on
  the same runs' after-states, all columns) at the control's after-state, from the fold fit
  that never saw that run (`_FoldGram.predict_folds`). The baseline only cuts noise: the
  choice was random, so it can't bias the label.
- **Model.** Ridge of the label on (taken − control after-state), run-grouped CV
  (`train_rct`, `target = "rct"`). The randomisation makes the difference independent of how
  the run was going, so the coefficients estimate what each change causes, relative to the
  champion. At play time an `rct` model ranks candidates by predicted advantage over the
  suggestion (`_pick_value`; the intercept cancels).
- **Fit report.** `deviation` is the average label of a random deviation minus a control's:
  are effects measurable at all? `oof_corr` / `oof_t` give the out-of-fold correlation
  between predicted advantage and label over deviations: the causal ranking check the
  value model failed. `switch_gain` is the label gain of the deviations the model would
  take, against controls. `by_kind` breaks the deviation effect down by kind, and
  `pairs_corr` is reported as before.
- **Gate.** The same as the other targets: `oof_corr` < 0.03 skips the benchmark; otherwise
  margins 0.1 / 0.3 / 0.6, then a paired confirm.

```
python -m cursed_words_solver.sim.game.expert --target rct --dir ~/.cursed_words_solver/sim_models/rct_pilot \
    --runs 512 --iterations 1 --collect-only --characters <all 11> --crowns 0,1,2,3,4,5,6,7
```

**Pilot (2026-11-01):** 512 runs, all 11 characters, crowns 0–7, 64 min on 8 cores. That gave
4,528 trials (1,117 controls) and 27,280 after-states. Baseline R² is 0.50 on the trials, and
the label SD is 2.18.

*Correction (2026-11-02):* 2,054 of those 4,528 trials are copies (see "Duplicated trials and
lower-noise labels" below). The real count is 2,474 trials (632 controls). The numbers in this
paragraph and the next two are from the inflated set.

- **Effects are measurable.** A random deviation from the champion costs −0.27 / run
  (t −3.8). By kind of alternative taken: boss −0.41 (t −4.5), swap −0.48 (t −3.8), an
  unplanned leave −0.30 (t −3.4), buy −0.07 (n.s.). A random pin side does *better* than the
  lower-side rule: +0.47 (t 2.4, 147 trials). Within pin decisions alone (raw outcome
  against the 65 pin controls) it's +0.67, t 1.4. That fits the user's view that the pin
  side matters, but it's a lead, not proof.
- **Ranking: weak but real.** Out-of-fold correlation of predicted advantage with the label
  is +0.054 / +0.049 / +0.049 (t ≈ 3) over three fold seeds. On half the runs it was −0.076,
  so 256 runs are too few. Holding `pos:`, `frozen:` or all per-class columns equal doesn't
  change it (+0.044 to +0.057).
- **Cut-off.** Every deviation the model rates above 0 does worse than the controls (−0.19).
  Deviation cost the features can't explain sits in the intercept and inflates each predicted
  advantage. At the play margins, the deviations it would take beat the controls out of fold:
  0.3 → +0.12 / +0.35 (n 144 / 136), 0.6 → +0.47 / +0.57 (n 18 / 19). The third seed chose a
  ridge so strong that nothing passes 0.3. `switch_by_margin` now reports this.

| Policy (256 eval seeds) | Wins | Mean outcome | Paired Δ / run |
|---|---|---|---|
| Base (Fast Advice) | **37** | **11.36** | |
| rct model, margin 0.3 | 8 | 9.76 | −1.60 (t −9.55; 49 better, 177 worse) |
| rct model, margin 0.6 | 33 | 10.93 | −0.43 (t −3.38; 45 better, 97 worse, 114 unchanged) |
| rct model, shared columns only, margin 0.3 | 37 | 11.17 | −0.19 (t −1.81; 38 better, 50 worse, 168 unchanged) |

Both margins lose; margin 0.3 loses badly, at every crown and for every character, and margin 0.6 changes fewer runs but still loses. Boss choices barely change
(68–69% cursed picks under both), so the loss is in the shop. The model swaps one buy for
another (more Giraffe, Soaring Kite, Wrestlers, Retro Raider; less Broom, Bunch Of Grapes,
Circus Tent, Cursed VHS, Axe; seed 77700001 has 4 overrides, all buy → buy). Its runs end
earlier (stage 3.61 vs 4.04). Those choices turn on per-class weights estimated from about
600 buy trials spread over about 250 classes, and the best of up to 16 candidates is the
one whose weight is noisiest. The weak out-of-fold ranking (+0.05) must come from coarse
differences, such as which kind of move it is, not from item-level ones. Trial-level
effects can be measured with 4.5k trials, but item-level advantages can't.

Next options: an rct model without per-class columns (the offline variant ranked as well,
+0.044 to +0.057, and can't chase item noise; the data is already collected, so it costs one
benchmark); many more trials (an overnight collection is about 5k runs / 45k trials, still
only ~25 buy trials per class); or item effects through shared item properties instead of
one weight per class. The pin-side lead is cheap to settle with trials on pin decisions only.

**Shared columns only (`--rct-shared`, 2026-11-01).** The per-class columns are left out of
the difference (`per_class_mask`), so the model can't chase item noise. Its top weights are
the boss targets (`log_target_*`, about +1.2 each), then rack and colour columns. Out of fold
it ranks as well as before (+0.046 / +0.057 / +0.044 over three seeds). The switch gain at
margin 0.3 is inconsistent (−0.30 / +0.38 / −0.51, n 24–31). On the eval seeds it ties on
wins (37 vs 37) and costs −0.19 / run (t −1.8). It changes only 88 of 256 runs, with buys per
run and stage reached unchanged and slightly more cursed bosses (68.8% vs 67.6%). Dropping
the per-class weights removes the damage (−1.60 → −0.19) but finds no gain. With ~4.5k trials
the advantage signal is too weak to act on: the effect of a typical choice is a fraction of
the run-to-run noise (label SD 2.2). Not promoted; default play is unchanged.

**Pin side trials (`--p-random 1 --control 0.5 --trial-kinds pin`, 2026-11-01).** These
settle the pilot's pin lead. Every pin decision is randomised 50/50 between the lower side
(the control) and the other side, and nothing else changes. The run took 512 runs (all
characters, crowns 0–7, 78 min) and gave 1,581 pin trials: 810 other side, 771 lower side.
Baseline R² is 0.51.

- **Overall: no effect.** Other side − lower side is +0.18 raw (t 1.0) and **−0.000**
  baseline-adjusted (t 0.0). The adjusted SE is roughly 0.12, so a pin side is worth less
  than about ±0.25 encounters per decision. The pilot's +0.47 (147 trials) was noise.
- **No subgroup holds up.** By stage, adjusted effects run from −0.22 to +0.19, all with
  |t| < 1. By character, the largest is Sandy Saguaro at +0.64 (t 1.6). By crown, crown 5 is
  −1.13 (t −2.9) and crown 2 is +0.63 (t 1.9). That's the extreme of 24 subgroup tests, with
  opposite signs in neighbouring crowns, so it is not a rule.
- **The situation doesn't predict the better side.** Both ridge models give out-of-fold
  correlation within ±0.03 for every λ: +0.011 (t 0.3) with per-class columns, −0.014
  (t −0.4) with shared columns only. They switch about 37% of decisions, for a gain of −0.03
  and −0.05.

These trials, the five fixed and rollout rules (above) and the probe all agree: with the
current policy, the pin side has no measurable effect on a run. `pin_side="lower"` stays.

### Duplicated trials and lower-noise labels (2026-11-02)

**Bug: trials recorded more than once.** `NetPolicy.decide` cleared `trial` only on a
run-level decision. A step without one (an encounter's word, the shop step cap) kept the last
trial, and `_rct_job` stored it again at every such step. Every leave and boss trial was
repeated once per word of the encounter after it. In the pilot, 2,054 of 4,528 trials are
copies, leaving 2,474 real ones: 921 buy, 623 leave, 454 sell → buy, 257 boss, 212 pin, 632 of
them controls. The pin-only run has none, because a shop decision follows each pin.
`decide` now clears `trial` and `explored` on every step, and `load_trials` drops a trial
identical to the one before it in the same run (kind, control, both after-states), so older
files load correctly. On the deduplicated set, the outcome-label model ranks better out of
fold: +0.093 / +0.065 / +0.077 over three fold seeds, against +0.05 before.

**Lower-noise labels (`train_rct(label_lam=…)`, `--rct-label-lam`).** The run's outcome
carries the luck of every later decision and encounter: label SD 2.2, against effects of 0.1–0.3
per decision. The alternative label is the λ-return from the end of the trial's shop visit,
using the out-of-fold state values, minus the same baseline. λ = 0 is the value after the next
visit, and λ = 1 is the outcome. Models are trained on that label, but every check scores them
against the outcome label, which a biased value can't fake.

| label (deduplicated pilot) | label SD | out-of-fold rank corr. vs outcome, 3 fold seeds | half the runs, 2 seeds |
|---|---|---|---|
| run outcome (as before) | 2.18 | +0.093 / +0.065 / +0.077 | −0.012 / +0.050 |
| λ-return, λ = 0.8 | 1.07 | +0.115 / +0.092 / +0.094 | +0.030 / +0.094 |
| λ-return, λ = 0.5 | 0.82 | **+0.128 / +0.099 / +0.086** | +0.045 / +0.097 |
| λ-return, λ = 0.2 | 0.75 | +0.123 / +0.093 / +0.080 | +0.044 / +0.095 |
| value after the next stage | 1.22 | +0.113 / — / — | +0.041 / +0.095 |
| *no advantage model: the state value's own V(taken) − V(control)* | — | +0.109 / +0.129 / +0.111 | +0.065 / +0.165 |

Shared-columns-only models rank lower: +0.099 / +0.084 / +0.054 at λ 0.5, against +0.057 /
+0.037 / +0.037 on the outcome. The smoothed labels give the ranking a consistent gain of about
a third, and half the data already gets most of it. They don't beat the plain state value,
which learns from all 27k after-states and ranks random deviations as well. When V(taken) −
V(control) exceeds 0.3, those random deviations beat the controls by +0.38 / +0.45 (t ≈ 2,
n ≈ 175, with or without the dropped columns).

**In play, they lose** (256 eval seeds, paired against the cached base: 37 wins, mean 11.36):

| Policy | Wins | Mean outcome | Paired Δ / run |
|---|---|---|---|
| rct, λ 0.5 label, all columns, margin 0.1 | 21 | 9.90 | −1.46 (t −7.4; 73 better, 168 worse) |
| rct, λ 0.5 label, all columns, margin 0.3 | 20 | 10.44 | −0.93 (t −5.1; 79 better, 149 worse) |
| rct, λ 0.5 label, shared columns, margin 0.3 | **43** | 11.34 | −0.02 (t −0.1; 82 better, 80 worse) |
| *(for comparison) rct, outcome label, shared columns, margin 0.3, before deduplication* | 37 | 11.17 | −0.19 (t −1.8) |

With all columns, the top weights are per-class position and freeze columns (`pos:TrophyOfWealth` −3.4,
`pos:DownwardTrendingChart` +1.8, `frozen:Supervillain` −0.9, …), each from a handful of
trials. Ranking *random* deviations is not the decision play makes. Play takes the best of up
to 16 candidates, which favours whichever per-class weight is most overestimated (the winner's
curse), and it does so at every decision of the run. Out-of-fold ranking of random deviations
therefore overstates what a model gains in play. Lower label noise doesn't fix that; what's
needed is a choice rule that discounts poorly measured directions (an uncertainty penalty from
the ridge posterior, so a deviation is taken only when its lower bound beats the margin), or
far more trials per class.

The shared-columns model with the smoothed label is the first learned model that doesn't lose
in play. It ties on the mean, and its +6 wins are within noise. Its weights are build-level:
`syn:BigNumbersBuild` +1.6, the colour and rack columns, and the boss targets. It isn't
promoted, but it points to the setup for long training: randomised trials, the λ 0.5 label,
shared columns only (`--target rct --rct-shared --rct-label-lam 0.5`), with the paired
benchmark as the gate.

### Training setup checks (2026-11-02)

**More decisions randomised per run (`--p-random 0.35`, `sim_models/rct_p35`).** The 512
runs use the pilot's run seeds and took 50 min. They gave 5,054 trials against the pilot's
2,474, so 2.0× per run. The runs are weaker (25 wins against 65, mean outcome 9.45 against
10.87), and fewer of the extra trials come from late stages. Stages 1–3 have 2.2× as many,
stage 4 1.9×, stage 5 1.3×.

- **Across datasets.** Each dataset's model ranks the *other* dataset's deviations at about
  half its own out-of-fold figure. The 35% model scores +0.066 on the pilot, and the pilot
  model scores +0.061 on the 35% runs. Heavier randomisation changes what follows a trial, so
  it partly measures a different advantage.
- **Pooled with the pilot, the extra runs help.** The pilot's own deviations are ranked out of
  fold, with folds grouped by game seed so a game's two runs never straddle a fold:

  | columns | pilot alone, 3 fold seeds | pilot + 35% runs |
  |---|---|---|
  | all | +0.128 / +0.087 / +0.086 | **+0.153 / +0.143 / +0.152** |
  | shared | +0.099 / +0.084 / +0.054 | **+0.108 / +0.108 / +0.113** |

  This is the first sign that the ranking keeps improving with data. The 35% runs are cheaper
  per trial and still useful, despite the shift.

**Margins (`--margins`).** Each training iteration benchmarked three margins, about 40 min each
on 8 cores, so with 512 runs per iteration the benchmarks cost more CPU than the data.
`--margins 0.3` benchmarks one margin. With one margin the eval step is skipped and the model
goes straight to the paired confirm test on fresh seeds, which stays the promotion gate.

**Uncertainty-penalised choice (`--rct-penalty k`).** `train_rct` now stores the ridge
posterior covariance of the weights (`Ridge.cov`, `live_idx`, `Ridge.se`). An rct model with
`penalty` k ranks candidates by the advantage minus k × its standard error, and deviates only
when that clears the margin. A change resting on a few trials' weights (a per-class column)
then needs a larger predicted gain, which is the winner's-curse fix. The fit report gains
`lcb_by_margin`: the deviations the penalised rule would take, by k and margin, with their
gain over the controls. On the pilot (λ 0.5 label, all columns), k = 1 at margin 0.1 takes 64
of 1,842 deviations (+0.44, t 1.4); k = 2 at margin 0 takes 18 (+0.57, t 0.9). Shared columns,
k = 1 at margin 0.1: 39 (+0.91, t 2.5).

In play (pilot model, λ 0.5 label, 256 eval seeds, paired against the cached base: 37 wins,
mean 11.36):

| Policy | Wins | Mean outcome | Paired Δ / run | Wins only model / only base |
|---|---|---|---|---|
| all columns, no penalty, margin 0.3 (above) | 20 | 10.44 | −0.93 (t −5.1) | — |
| all columns, k = 1, margin 0.1 | 44 | 11.24 | −0.12 (t −0.7; 90 better, 100 worse) | 23 / 16 (p 0.34) |
| all columns, k = 2, margin 0 | 45 | 11.40 | +0.04 (t 0.3; 51 better, 47 worse) | 13 / 5 (p 0.10) |
| **shared columns, k = 1, margin 0.1** | **51** | 11.39 | +0.03 (t 0.2; 97 better, 88 worse) | 28 / 14 (p 0.044) |

The penalty removes the per-class damage entirely: −0.93 becomes −0.12 / +0.04. Every
penalised model wins more often than the base, while the mean outcome (encounters cleared)
stays flat. The shared model's p 0.044 comes after eight variants were tried on these seeds,
so it is checked on the trainer's fresh confirm seeds (`make_jobs(256, 778, …)`):

| Confirm seeds (256) | Wins | Mean outcome | Paired Δ / run | Wins only model / only base |
|---|---|---|---|---|
| Base | 49 | 11.94 | | |
| shared columns, k = 1, margin 0.1 | 48 | 11.72 | −0.22 (t −1.3; 81 better, 111 worse) | 21 / 22 (p 1.0) |

**It does not hold.** The +14 wins on the eval seeds were the pick of eight tries. Taken
together: the penalty makes a learned model safe (no model loses badly any more, all columns
included), and pooling more trials keeps improving out-of-fold ranking (+0.10 → +0.15). No
model beats the base in play yet. Default play is unchanged.

**Setup for the long run** (what these checks support):

```
python -m cursed_words_solver.sim.game.expert --target rct --dir ~/.cursed_words_solver/sim_models/rct_long     --runs 1024 --iterations 10 --p-random 0.35 --rct-label-lam 0.5 --rct-penalty 1 --margins 0.1     --characters <all 11> --crowns 0,1,2,3,4,5,6,7
```

All columns or `--rct-shared`: both are neutral with the penalty, all columns rank better out
of fold (+0.15 against +0.11 pooled), and per-class weights are the only way the model learns
items. An iteration is about 1 h 40 min of collection plus a 1 h 20 min confirm (the model
and, the first time, the champion, on 256 fresh seeds), so about 3 h, or 8 a day. Each
iteration refits on all trials so far (~10k per 1,024 runs) and promotes only on the paired
confirm (t ≥ 1.65).


```
python -m cursed_words_solver.sim.game.expert --iterations 3 --runs 256 --eval-runs 256 \
    --characters BonesTheDog,HayleyBayles,NathaServo,NinaNix,Octacles,PrismaticBean,SamGambit,SandySaguaro,SockHead,Spike,WetDennis --crowns 0,1,2,3,4,5,6,7
```

### Boosted trees and the first promoted model (2026-11-05)

`learn.TreeAdvantage` (LightGBM) sees the move, the suggestion's after-state and the kind of
move, so a move's worth can depend on the build. It stores its margin in its file.

- **Offline**, ~76k deviations: within-kind ranking 0.19 against 0.156 for ridge. The edge is
  in boss, leave and pin choices; on buys it is no better (0.13 vs 0.14).
- **In play**, margin 0.3 on 1,024 fresh seeds: +0.152 / run (SE 0.078, t 1.96), wins 190 vs
  190, Michael wins 18 vs 22. Lost runs go further; NathaServo is two-thirds of the gain.
- Promoted: `sim_models/rct_nonlinear/champion.npz`, the advisor's AI pick. On 256 seeds it is
  level with the linear model, whose 1,024-seed result is unknown.
- 256 seeds cannot show a true +0.2 reliably (per-seed SD ~2.5): decide such gaps on ~1,000.

### Whole-run build plans (S2, `plantest.py`, 2026-11-05)

The learned models only fine-tune the rules player: their trials change one move of its games,
so they have never seen a run with a different plan. `PowerConfig.build_plan` commits a run to
one of `policy.BUILD_PLANS` from the first shop:

- Items of only another build are never bought (generic points and items with no build still
  are, and Advice goes on choosing among what is left).
- A plan offer is bought first, the best by probe, generators first until two are owned.
- With no room or money, a non-plan item is sold for it (once per shop).
- With no plan offer, up to `build_plan_restocks` (2) restocks per shop, keeping
  `build_plan_reserve` ($5).

Models are not plan-aware yet: test plans without one (a model could pick an off-plan offer).

```
python -m cursed_words_solver.sim.game.plantest --out ~/.cursed_words_solver/sim_models/plans --n 16 --workers 8
python -m cursed_words_solver.sim.game.plantest --out ~/.cursed_words_solver/sim_models/plans --report
```

All 13 plans and the rules player play 16 seeds per character (crowns cycling) = 2,464 runs, ~8 h,
a screen. A plan changes the whole run, so expect a per-seed SD well above the model's ~2.5
(estimate ~5, to measure): ~0.4 per plan, too noisy for one character × plan. Add seeds for the
leaders (`--plans A,B --start 16 --n 48`), then confirm on seeds no choice was based on. Confounded
look at the rules player's 1,024 runs, by the build it bought most of: Curse 47% wins, Cards 36%,
Scattered 33%, Void 30%, Red 10%, Blue 7%, Cash 3%.

**Screen result (2026-11-05, seeds 0-15, 0 crashes; a lead, not yet confirmed on fresh seeds):**

| Plan | Gain | t | Wins of 176 (rules 36) |
|---|---|---|---|
| Curse | +0.49 | 1.22 | 68 (44 only-plan, 12 only-rules, McNemar p 2e-5) |
| Numbers | +0.10 | 0.34 | 43 |
| Chess | +0.01 | 0.05 | 41 |
| ScatteredItems | -1.28 | -4.08 | 39 |
| Cards | -1.13 | -3.77 | 27 |
| Void | -1.82 | -5.08 | 26 |
| Rainbow | -1.62 | -5.78 | 18 |
| Red | -2.19 | -8.12 | 15 |
| Blue | -1.84 | -7.06 | 10 |
| Shiny | -2.87 | -10.13 | 9 |
| Consumable | -3.61 | -12.63 | 7 |
| Blank | -3.60 | -14.32 | 4 |
| Cash | -4.70 | -18.28 | 2 |

Curse wins far more with hardly more mean outcome because it is all or nothing: Michael wins
19 vs 2 and crowns 4-7 wins 19 vs 6, but stage-2 deaths 32 vs 10 (outcome SD 5.7, wins mean 18.2,
losses 8.8 vs 10.8). So mean outcome, the gate's primary test, misses it. Spike is 15/16 on it
(rules 4/16), from one small cell picked out of 143. Plan-vs-rules difference SD is 3.3-5.3, 4.2 pooled.
FoodPoisoning and HauntedMirror match the decompiled game, and Oden's text and rule were read;
no real-game log has Oden, so Curse builds have no real-game check yet.

### Promotion gate (`bench.py gate`, 2026-11-05)

Picking the best of 16 candidates on shared seeds passes t 1.65 about 56% of the time when none
is better, and +0.2 took about 1,000 seeds of a fixed test, so `bench.py` gained:

- **`--keyed`:** the stream restarts before each action from where the run is, as `play_out`
  does. Arms must agree on it. Pool-indexed picks still shift when a pool changes; a second stage
  (per-event streams, hashed ranks) waits for the pilot's result.
- **`--salt`:** other games on the same seeds. Base vs salted base is the A/A check; base vs an
  identical base must differ by exactly zero.
- **`gate <base> <arm>`:** plays one block at a time (one seed per character and crown, 88 runs),
  deciding on LLR = δ / var × (S − nδ / 2) with δ 0.2: accept at 2.77, reject at −1.56, undecided
  at 1.5× a fixed test's runs. Pentanomial modelling adds nothing, since the paired variance
  already holds it.
- **Promoting takes three things:** accept; lower bound on win and Michael win rate change above
  −2 points, which needs about 10 blocks at the usual 12% discordant runs; and single-use seeds.
- **Seeds:** search on 7M (`--first-seed`), 8M is regression only, promotion on `--block K` =
  9,000,000 + 20,000 × K. `seed_blocks.json` refuses a block to a second candidate. A block spans
  11,000 seeds, so a step of 10,000 would overlap.
- **Reported:** raw gain and t, seeds, candidates searched (`--searched`), the gain shrunk with a
  prior SD of 0.15, and a bootstrap interval stratified by character and crown. Figures use every
  complete block; the decision is the first to cross a bound.

**Pilot (`~/.cursed_words_solver/bench2/pilot.py`, 2026-11-05, 1,408 runs, thresholds set before the runs):
keying does not help, so `bench` stays on the legacy stream and keying stays in `play_out` labels only.**

| Check | Stop if | Result |
|---|---|---|
| `k_base` vs `k_repeat` | Any difference | Pass: 88 of 88 identical |
| `k_base` vs `k_salt` | SD outside about 3.1-3.9 | Pass: 3.67 |
| `k_base` vs `k_e5off`, against `l_base` vs `l_e5off` | Keyed SD not clearly below legacy | **Stop:** 2.81 keyed vs 2.55 legacy, ratio 1.10 (95% 0.89-1.36) |
| `k_base` against `l_base` | Mean differs by over 2 SE | Pass: 11.75 vs 11.94, about 0.8 SE |

The per-event streams and hashed picks planned as a second stage are not worth building. `finish_early`
held up on current code in both streams: off is -0.19 keyed, -0.18 legacy. The interval still allows up
to about 20% less variance, but the estimate is 21% more, and this one pair is the only evidence.

Sequential test, 600 replays per row resampling these differences (δ 0.2), against about 1,000 seeds for
a fixed test at SD 2.55:

| True gain | Accepted | Mean seeds, SD 2.55 | Mean seeds, SD 3.67 |
|---|---|---|---|
| 0 | 3.8% | 563 | 1,116 |
| +0.2 | 75% | 788 | 1,518 |
| +0.4 | 100% | 371 | 697 |
| -0.2 | 0% | 244 | 434 |

Power at +0.2 is 75%, below the design's 80%, because of the cap. Mean outcome also misses gains in wins:
the Curse plan above nearly doubled wins at t 1.22, so a wins test is still to add.

## Known gaps

- **Pin side is not really chosen** (next to do when training resumes): the policy upgrades
  the lower side (`pin_side="lower"`), for every character. The pin build steers which items
  are worth buying, so this compounds over a run — e.g. Octacles' crown-8 win (seed
  8004805) alternated Bucket sides and took whatever tile each had queued
  (`Bucket.next_tiles`). The one-encounter probe (`pin_side="power"`) was neutral because it
  misses the long-term effect; the choice needs a longer horizon (play each side out to the
  next boss) and/or fit with the build tags Advice shops for, benchmarked per character.

- Michael's finale puzzle grid (`GridGenerator.GetPuzzleGrid`) is not generated; reaching
  the finale counts as a win (the puzzle always has a 25-tile solution).
- Speedrun quest timing is not modelled.
- RNG is Python's, not Unity's: runs are statistically, not bit-for-bit, faithful.
- `GetValidNextTiles` is only needed for Carousel Horse's knight squares; that uses plain
  knight moves (+ Hungry Snake wrap).
- Unlock profile is "everything unlocked"; `RunConfig.unlocked_characters` controls secret
  bosses and `character_never_won` the Shop Advice starter item. This is on purpose (the AI is
  for the full game); real shops on a partly unlocked save differ only by the locked items
  and the smaller tag pools that follow.

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
