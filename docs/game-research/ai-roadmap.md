# What wins runs: AI status and what to try next (2026-10-30)

Companion to [sim-game.md](sim-game.md) (all benchmark details live there). The goal is an
AI that beats runs consistently on every character and crown, and that can discover play
of its own beyond the rules given to it.

## Where runs are lost now

Current base policy, crowns 1–4, 528 paired seeds (`michaelbench.py`, 2026-10-29):
106 wins (45 / 30 / 16 / 15 by crown). Across crowns 0–8 (132 seeds each): 70 / 46 / 30 /
16 / 15 / 13 / 5 / 0 / 2 wins.

Lost runs end mostly in stages 4–5, at bosses *and* at normal encounters:

| crown | s2–3 | s4 enc | s4 boss | s5 enc | s5 boss |
|---|---|---|---|---|---|
| 1 | 5 | 11 | 25 | 23 | 23 |
| 2 | 13 | 26 | 20 | 26 | 17 |
| 3 | 22 | 28 | 22 | 31 | 13 |
| 4 | 33 | 31 | 25 | 14 | 14 |

Targets grow ×3.8 per stage (boss ×2, plus up to +40% per crown late in the run), so a
build that clears stage 3 comfortably can still fail stage 4. **The build does not scale
far enough**, and higher crowns start losing earlier.

## Human play vs the AI

12 recorded human runs (`run_journal`, 2026-10-24/25) vs 21 AI runs (`shopdiag.py`):

| | human | AI |
|---|---|---|
| money when leaving a shop | median ≈ $4 | median $4 (p25 2, p75 8) |
| filled slots after stage 2 / 3 / 5 | ≈ 5–7 / 7–9 / 9–10 | 5.0 / 7.4 / 9.2 |
| reorders per run | 5–19 | ~3 (stickers only) |
| restocks | — | in 41% of shops |
| freezes | — | 145 in 263 shops, 85% bought later |
| reached stage 6 (Michael) | **6 of 12** (crowns 1–3) | **6 of 528** |
| took the cursed boss (crown ≥ 1, still all-cursed) | nearly always | 44–57% per floor |

Spending, slot filling, restocks and freezes already look human-like. The biggest
differences are: Michael route commitment, ordering (stamps never), and build quality.

## Inventory: what the AI does, and what could help

Status: ✅ on and measured; ➖ tried, neutral or worse; ⬜ not tried. Impact is a guess.

### Run route (bosses, Michael)

| # | Lever | Now | Idea | Impact |
|---|---|---|---|---|
| R1 | Boss choice | ✅ learned risk table per boss × crown × character; ✅ `boss_model` on (user's choice; build-aware: probe each option, logistic on strength + table, AUC 0.97 vs 0.62) **+0.07 (t 0.8)** on 528 seeds, wins 97 → 104, Michael reached 26 → 37 | refit on runs that used it; long-horizon value (S1) would subsume it | medium (measured small) |
| R2 | Michael commitment | ✅ stage-5 rule validated (+1.8 per decision); ✅ `route_value` on (user's choice) (route value of staying cursed): Michael reached 4 → 22 of 264, beaten 3 → 5, wins 57 → 53, outcome −0.03 (t −0.2) | builds strong enough to survive the fifth cursed boss (half the all-cursed runs die there) | high at crown ≥ 1 |
| R3 | Ogre | ➖ `ogre` (buy while chasing, sell in stage 4): adds nothing over `route_value` | — | none |
| R4 | Pin side | ➖ parked ("lower"); all rules within noise | revisit once builds are strong | later |
| R5 | Michael drafts | ✅ lowest-risk option | build-aware like R1 | low (rare) |

### Shop

| # | Lever | Now | Idea | Impact |
|---|---|---|---|---|
| S1 | What to buy | ✅ Advice + probe check (one encounter); ➖ `build_value` (class growth model, CV R² 0.52 vs 0.17 for the probe gain alone) **−0.11 (t −0.8)** on 528 seeds, wins 104 → 101: crowns 0–2 worse (wins 80 → 67), 3–7 better (24 → 34, post hoc); ➖ survival-weighted (`build_value_risk`, stages weighted by P(losing a fight)) **−0.32 (t −2.1)**, worse at every crown | per-item extrapolation is the weak link (stage 1 → 5 from survivors' data): learn the long-horizon value from run outcomes instead (L1), or test `build_value` at crowns ≥ 3 on new seeds. Original idea: **Long-horizon value**: judge a buy by strength against the next boss / next stage targets, including items that grow (counters, scaling stickers). The one-encounter probe favours flat points now | **highest** |
| S2 | Build direction | Advice tags; shop is biased toward owned tags; `build_plan` under test (`plantest.py`, sim-game.md) | Commit to an archetype early (pick tags, buy toward them); value upgrades (buying an owned sticker levels it, up to 2, foil 4) | high |
| S3 | Sell / replace | ✅ 1 swap per shop | more swaps late; sell economy items once their payoff time is over | medium |
| S4 | Spend-down | ✅ above $20; no-reserve early ➖ (−0.68) | reserve by plan (saving for a specific frozen item) instead of a fixed $20 | low–medium |
| S5 | Freeze | ✅ Advice (85% of freezes get bought) | freeze an unaffordable high-value offer before leaving; freeze before restocking | low–medium |
| S6 | Restock | ✅ Advice + up to 3 in spend-down | restock by expected value of a new offer vs cost (rises +$1 each) | low–medium |
| S7 | Economy | Advice only | economy items (Dragon: +10% of money per clear, Piggy Bank…) early, sold later; $2 per unused grid | medium |
| S8 | Sticker order | ✅ probe swaps (+0.44) | — | done |
| S9 | Stamp order | ➖ `sort_stamps` neutral overall (+0.02, t 0.2); Sock Head 9 → 15 of 32 wins (t 2.4) → on for him only | — | done |
| S10 | Rack tiles | ✅ Spike only (13 → 18 of 32); others neutral | per-character | done |

### Encounters

| # | Lever | Now | Idea | Impact |
|---|---|---|---|---|
| E1 | Word search | ✅ effort 0.05; 3× deeper boss search ➖ | — | done |
| E2 | Word choice beyond score | ➖ planner neutral (money ≈ $0.1 per submit) | matters more once items reward specific words (levels, counters) | low now |
| E3 | Grid reroll | ✅ when best < 0.55 × needed per grid | per crown (crown 7 has one grid fewer) and per boss | low |
| E4 | Tile placement | ✅ when behind pace; saving ➖ no-op | — | done |
| E5 | Finish early | ⬜ | each unused grid pays $2: when ahead, a word that clears now beats a bigger one later | low |

### Learning and per-character play

| # | Lever | Now | Idea | Impact |
|---|---|---|---|---|
| L1 | Learned run decisions | ➖ ridge advantage model on paired play-outs: labels ~21% signal, never beat base | learn a **state value** (build strength vs upcoming targets) instead: one-stage strength is repeatable (split-half 0.67). ✅ built 2026-10-31: `expert.py --target value` (λ-returns, ridge, decisions checked against keyed pairs). Pilot 2026-11-01: fit R² within 0.25, but the model loses at every margin (22 vs 37 wins of 256 at best): swaps valued half-done, confounded spend / freeze features, argmax churn (sim-game.md). Fixed 2026-11-01 (decision kinds limited, swaps valued whole, spend / freeze columns dropped): 35 vs 37 wins, still −0.67 / run (t −3.3); no feature set ranks actions (pairs_corr ≤ 0.044). Randomised-decision trainer built 2026-11-01 (`--target rct`): 512-run pilot, 4.5k trials, deviation effects measurable (−0.27 / run, t −3.8), out-of-fold ranking +0.05 (t 3), but the model loses (margin 0.3: 8 vs 37 wins; 0.6: 33 vs 37, −0.43): per-class buy weights are noise at this data size; shared columns only (`--rct-shared`): 37 vs 37 wins, −0.19 (t −1.8), no gain. Pin-only trials 2026-11-01 (1,581 randomised pin decisions): other side − lower side −0.00 adjusted (t 0.0), situation model out-of-fold corr ≈ 0: the pilot's pin lead was noise. 2026-11-02: half the pilot's trials were copies (leave / boss trials re-recorded at each encounter step; fixed, old files deduplicated on load); smoothed labels (`--rct-label-lam 0.5`, λ-return after the visit, SD 2.2 → 0.8) rank a third better out of fold, all columns still lose in play (−0.93, t −5.1; per-class weights + best-of-16 = winner's curse), **shared columns tie: 43 vs 37 wins, −0.02 (t −0.1)**, the first learned model that doesn't lose → the setup for long training. Same day: 35% randomised runs (2× trials per run) pooled with the pilot raise out-of-fold ranking +0.10 → +0.15 (ranking still grows with data); uncertainty penalty (`--rct-penalty 1`, ridge posterior SE) makes every model safe (all columns −0.93 → −0.12 / +0.04), shared k = 1 got 51 vs 37 wins on the eval seeds but **fails on fresh confirm seeds (48 vs 49, −0.22, t −1.3)**: no learned model beats the base yet; `--margins` cuts benchmark cost; long-run command in sim-game.md "Training setup checks" | high |
| L2 | Item value | ➖ table from logged runs (confounded) | causal: exploration buys or paired play-outs | medium |
| L3 | Per-character / per-crown settings | ✅ any setting per character or crown band (`char_overrides`); `chartune.py` successive-halving search over 13 knob changes per character, paired seeds, promote at t ≥ 2 + fresh half; first pass done 2026-10-31: only Spike `swap_sell` off promoted, and it fails on the benchmark (−0.20, t −0.5); table not enabled | validate the table on the 528 benchmark seeds; more passes; crown bands once a character has enough runs; the same overrides are the search space for L1 training | medium |
| L4 | Human imitation | 12 journals, no shop offers in them | record shop offers too; compare "what would the AI buy here" | low–medium |

## Suggested order

1. **S9 stamp order**: done, neutral except possibly Sock Head.
2. **R2 + R3**: Michael route commitment and Ogre. Cheap to test, and it targets the
   largest human/AI difference.
3. **R1**: build-aware boss choice (reuses the probe machinery).
4. **S1 + L1**: long-horizon build value. This is the core of "the AI finds its own
   play". A learned evaluator of build strength against future targets replaces the
   one-encounter probe in every shop decision. It is trained by self-play on the sim, with
   exploration, so it can value things no rule mentions (scaling items, archetypes,
   economy).
5. **L3**: per-character tuning (first pass running), then the pre-training work below,
   then **long training sessions** on S1 + L1.

## Before long training (added 2026-10-30)

| # | Item | Why | Done when | Priority |
|---|---|---|---|---|
| P1 | **Run speed** — ✅ ×1.77 with identical play (enumeration reused across probes of one grid, quest rank once per search; 3 runs action-for-action equal); next: cheaper probes (changes play, benchmark) | A run costs ~130–180 s CPU, so 8 workers manage ~4,600 runs a day; a state-value model needs tens of thousands, and every promotion test another 528. Profile one run; cut repeated work in word search and probes (cache probes across actions, cheaper search inside training play-outs) | a profile, and benchmark runs ×2 or more faster with stored results unchanged (or the difference measured) | **highest** |
| P2 | **Sim fidelity re-check** — ✅ 2026-10-31 (see sim-game.md "P2 re-check"): all checks pass, new `clears` 156/156 and `shops` checks; fixed Northern Cardinal's "red" discount; upgrade offers 17 vs 39 (z −4) closed 2026-11-02: the validator counted exports taken after a buy or restock as entries; the game's Player.log branch rates match the port (`sim_validate.py gamelog`), sim unchanged; 9 AI-frequent items locked on the user's save | A self-taught AI exploits sim bugs. The last full validation was 2026-10-16 and many items were ported since; growers a learned value leans on (Radio, Haunted Mirror, Cursed VHS, Tombstone) matter most | replay comparison on recent captures re-run; mismatches fixed or listed | **highest** |
| P3 | **Full action space for the learner** — ✅ 2026-10-31 (see sim-game.md "Full action space and state features"): `full_shop_candidates` adds sell-then-buy swaps, freezes, sells and reorders to the buys / restock / leave, ≤ 16 per state, round-robin by group; play unchanged without a model; training alternatives drawn group-first | `NetPolicy` chooses among Advice-based `shop_candidates`; finding play no rule makes needs any legal buy, sell, freeze, restock, move or saving money | `shop_candidates` checked against `legal_actions`, gaps filled (with a cap on candidates per state) | high |
| P4 | **State features for the value model** — ✅ 2026-10-31: v4 features (2088 columns): crown, targets ahead, Michael route, economy, tag synergy / unmet dependencies, per-class slot position, growth and counters, shared per-class descriptors; old models read their prefix | The value must see item counters and levels, upcoming targets per stage, crown, character, distance to Michael, build tags, economy items; rare items need a learned per-class summary | `features.py` audited, gaps added, a per-class item representation | high |
| P5 | **Benchmark tool in the repo** — ✅ 2026-10-31: `bench.py` (run / compare / show; 528 fixed seeds, resumable, settings guard, code fingerprint per run) | Paired comparisons live in scratchpad scripts; every trained version needs the same scoreboard | a module that plays an arm on fixed held-out seeds and reports overall / halves / crown / character / wins / Michael, resumable | medium |
| P6 | **Resumable, checkpointed training** — ✅ 2026-10-31: `expert.py` resumes data, every benchmark run and each iteration (fixed: a restart after the data skipped that model's benchmark); atomic history; champion snapshots; config guard | Multi-day jobs must survive restarts like `chartune` does | model snapshots, champion and its results, data log all resumable | medium |
| P7 | **Commit before training** | A clean point to compare against and roll back to | user's commit of the current work | — (user) |
| P8 | **Cheap rule tests first** — ✅ benchmarked 2026-10-31: E5 `finish_early` 0.75 +0.245 / run (t 2.0, both halves +), wins 104 → 110, **on by default**; S3 `late_swaps` −0.05 (t −1.3), stays off | E5 (finish an encounter early when ahead, $2 per unused grid) and S3 (more swaps late) are quick to test; S2 (archetypes) and S7 (economy) are left for the training to discover, provided P4 exposes tags and economy items | E5 and S3 benchmarked | low–medium |

Order: P1 and P2 first (whether training is fast enough, and learns the real game), then
P3–P6 as the training setup, P8 alongside when CPU is free; L3's tuning pass occupies the
CPU until it finishes, so benchmarks for P1/P8 wait for it or run with fewer workers.

## Training environment for discovery

Everything needed for self-play exists: an exact, deterministic, resumable simulator,
the full legal action set (`agent.Action`), keyed randomness for fair comparisons, and a
run log. What changes for long training:

- **Target:** predict build strength / win chance from a state (low noise), not the
  outcome difference of two actions (high noise).
- **Acting:** at each run decision, score the after-state of every candidate with the
  value model, with a small search (top few candidates played out a stage) where it is
  cheap.
- **Exploration:** a share of decisions taken at random or by the model's uncertainty, so
  it sees choices the base rules never make.
- **Gate:** keep the paired-seed promotion test, per character and crown band, so a new
  model replaces the champion only when it wins.
