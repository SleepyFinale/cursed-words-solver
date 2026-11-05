# Cheap and trustworthy evaluation of game-playing agents under noisy outcomes

Conventions used throughout:

- **Project measurements** were computed on 2026-11-05 from `~/.cursed_words_solver/bench/{base,e5,s3,spike_tuned}.jsonl` (528 paired seeds, 11 characters x 8 crowns x 6 seeds). `spike_tuned` has only 48 seeds. The scripts are in the session scratchpad and are not part of the repo.
- **"Own estimate" or "own simulation"** means my calculation, not a published result.
- **Hours** assume 6 runs per minute, which is 360 runs per hour. The measured mean of 69 to 73 CPU seconds per run on 8 workers gives about 6.9 runs per minute.
- **Fixed-sample size** is `n = (1.645 + 0.842)^2 * (SD_D / delta)^2 = 6.18 * (SD_D / delta)^2`, for a one-sided t >= 1.65 at 80% power.

## Objective: what is the best overall practice, and how much does it save?

### Takeaway
Combine a cached base arm, a sequential stop on balanced seed blocks, keyed RNG in the benchmark, and one-time confirmation seeds. My estimate is that this cuts a +0.2 comparison from about 5.4 hours to about 1 to 1.5 hours. It should also cut false promotions after a many-candidate search from about 56% to about 5%. Only the keyed RNG saving is uncertain, and a 1.5-hour pilot settles it.

### Cited Findings
- **Bench does not use keyed RNG (project code).** `bench.job` plays `apply(g, pol.act(g))` on one shared stream, and shop, encounter and grid generation all hold the same `Rng`. A keyed mode already exists, but only for training labels (`expert.py` `play_out(keyed=...)`) — `cursed_words_solver/sim/game/bench.py`, `expert.py`, `core.py`.
- **Keyed reseeding has already changed label quality here.** Test-retest correlation of decision labels went from about -0.2 on one stream to 0.21 with keyed reseeding, and a third of alternatives gave exactly the same outcome — `docs/game-research/sim-game.md`.
- **The whole-run SD of about 5 looks too pessimistic (project measurement).**
  - Within character x crown, base SD is 2.57 (variance 6.59, against 14.61 overall, so the cell explains 55%).
  - Fully independent runs in the same cell therefore give a paired SD of only about 3.4 to 3.6.
  - An SD of about 5.4 appears only if crown and character are not matched, since sqrt(2 * 14.61) = 5.4.
- **Measured paired SDs (project measurement):**

| Arm | Change | SD of D | Identical outcome | SD of non-zero D | Within-cell rho |
|---|---|---|---|---|---|
| `e5` | `finish_early` 0.75 | 2.80 | 19% | 3.11 | 0.42 |
| `s3` | `late_swaps` 3 | 0.85 | 88% | 2.47 | 0.95 |
| `spike_tuned` | per-character tuning | 2.83 | 19% | not computed | 0.16 (n = 48) |

- **Run cost varies by crown (project measurement).** Crown 1 takes 151 s per run and crown 7 takes 16 s.

### Inferences
Own estimates for detecting +0.2, using SD_D 2.5. All of them are in the table below.

| Step | Seeds | Runs | Hours | Basis |
|---|---|---|---|---|
| Today: fixed n, both arms played | 966 | 1,932 | 5.4 | formula above |
| + cached base arm | 966 | 966 | 2.7 | a pair costs 1 run while base and code are stable |
| + GSPRT on balanced blocks | 520 to 770 for typical cases | 520 to 770 | 1.4 to 2.1 | own simulation, see the sequential testing section |
| + keyed RNG in bench (15 to 40% lower Var D, low confidence) | 310 to 650 | 310 to 650 | 0.9 to 1.8 | needs the pilot |
| + first-deviation reuse, small changes only | same n | up to 80% fewer simulated | under 1 | `s3` has 88% identical runs |

- **One-off costs.** Extending base from 528 to 2,000 seeds takes 1,472 runs, or about 4.1 hours, and pays for itself in two comparisons. Each promotion or engine code change invalidates the cache, so batch promotions together.
- **The savings do not fully multiply.** Keying and luck adjustment both target the same noise.
- **Recommended order, cheapest first:**
  1. Cache base on 2,000 seeds and make `compare` report the block-balanced GSPRT.
  2. Reserve one-time confirmation seeds and add reporting of shrunk estimates.
  3. Run the keyed pilot: base and `e5` on 264 seeds each under keyed bench (528 runs, 1.5 hours). Compare SD_D with the legacy 2.80. The SE of the SD is about 4% before heavy tails. Keep keying if SD_D falls below about 2.5.
  4. Add first-deviation reuse if small knob tests remain common.
  5. Add luck adjustment only if a value model reaches a useful R-squared.

### Gaps
- I did not run a keyed benchmark, so the 15 to 40% figure is a judgement, not a measurement.
- The SDs rest on only three arms. They may not hold for learned models that override many decisions.

## Common random numbers: keying randomness so that a change at one decision does not desynchronise later events

### Takeaway
Derive each draw from `hash(seed, stable event identity)`, not from a position in one stream. Choose items with per-item hashed scores, so that changing the eligible pool does not change the other picks. The literature gives the method but almost no game-specific variance numbers, so measure it.

### Cited Findings
- CRN only helps when a given random number serves the same purpose in both configurations, and multiple streams, one per event type, are the standard way to keep synchronisation. One shared stream loses sync — [CS590M lecture notes, search excerpt](https://people.cs.umass.edu/~phaas/CS590M/slides/slecture11a.pdf).
- CRN can backfire. If it induces negative correlation, variance rises — [Wikipedia: Variance reduction](https://en.wikipedia.org/wiki/Variance_reduction).
- Buffalo, Pearson and Klein (2026) recommend counter-based generators keyed by a stable event ID, with the seed selecting the "world". Each event's noise then depends on the seed and its ID, not on execution history — [arXiv 2603.11084](https://arxiv.org/html/2603.11084v1).
- That paper names the same failure modes this project has. Conditional draws and variable-count rejection sampling shift all later draws, which makes paired covariance zero or even negative — [arXiv 2603.11084](https://arxiv.org/html/2603.11084v1).
- Key-design rules from the same paper — [arXiv 2603.11084](https://arxiv.org/html/2603.11084v1):
  - Slot keys such as `(t, i, r)` share noise even if the partner changes, which assumes partners are exchangeable.
  - Run-dependent quantities must never enter a key, because they reintroduce history dependence.
  - Identifiers for created entities should come from lineage, not global creation order.
  - Events with no counterpart simply go unqueried, which is harmless.
- That paper reports no empirical variance reduction. Its speed note is that Philox is about 2x slower than Mersenne Twister and Threefry about 5% faster, before key computation — [arXiv 2603.11084](https://arxiv.org/html/2603.11084v1).
- PEGASUS (Ng and Jordan) is the classic RL example: it fixes random numbers as explicit scenario inputs, so policy search becomes a deterministic comparison — [arXiv 1301.3878](https://arxiv.org/pdf/1301.3878).
- Trigger-dilute analysis in online experiments reduces variance by roughly the inverse of the trigger rate, for example about 20x at a 5% rate — [Deng et al., Zero to Hero](https://arxiv.org/abs/2112.13299); [Deng and Hu](https://exp-platform.com/dilution/).
- Oberst and Sontag define counterfactual stability for categorical draws, and show the Gumbel-max construction satisfies it. If a draw's probabilities change, the outcome only moves in a way consistent with those changes — [ICML 2019](https://proceedings.mlr.press/v97/oberst19a.html).
- The Mahjong competition format is CRN applied to players: 24 games with seats exchanged and each seat dealt the same tiles, which removes lucky hands and seat order — [IJCAI 2024](https://ijcai.org/Proceedings/2024/1020.pdf).
- Suphx says initial private tiles strongly affect win or loss, and its offline evaluation generated one million games to reduce this. One agent's evaluation took 20 GPUs for two days — [Suphx](https://arxiv.org/abs/2003.13590).

### Inferences
Design for this simulator (own proposal):

- **Fidelity is not at risk from the generator.** `core.Rng` is Unity semantics on Python's `random`, not a replica of Unity's sequence. Keying only has to keep each draw's distribution the same. Check `importer` and any replay tool for reliance on the sequence.
- **Reuse the existing key.** Move `expert.play_out`'s scheme into `bench.job`: reseed before each action from `(seed, stage, node, grid, grid rerolls, action kind, count of that kind here)`. This is about 10 lines.
- **Finer streams to add next**, because draws inside one action are still sequential:

```
shop stock : hash(seed, stage, node, reroll_idx, slot)
grid deal  : hash(seed, stage, encounter_idx, grid_idx, cell)
refill     : hash(seed, stage, encounter_idx, submit_idx, cell)
item effect: hash(seed, item_lineage_id, trigger_count)
boss draft : hash(seed, stage, "boss")
```

- **Fix pool-indexed picks.** `cands[rng.range(0, len(cands))]` gives a different item whenever the pool changes size or order. Replace it with stable-rank selection, as `shop.py` and `items.py` use this pattern:

```
unweighted: pick argmax over eligible items of hash(key, item_id)
weighted  : pick argmax over eligible items of  log(w_i) + Gumbel(hash(key, item_id))
```

  An item that wins stays the winner when other items drop out, and the marginal distribution is unchanged. This is the Gumbel-max property above.
- **Do not key on the policy's RNG or on run state.** Keep policy randomness separate. Never put gold, score or hand contents in a key.
- **Verify before trusting.** Test that key collisions do not reuse the same grid twice in one run, that the marginals of stock and letters match the legacy mode, and run base keyed against base legacy for mean and win rate.
- **Expected effect (own estimate, low confidence).**
  - `Var(D) = 2 * sigma^2 * (1 - rho)`, averaged over deviated seeds.
  - Currently rho on deviated seeds is about 0.2 to 0.3 for `e5` and about 0.5 for `s3`.
  - Moving those to about 0.5 to 0.7 would lower Var D by about 15 to 40%.
  - That is worth about 0.4 to 1 hour per comparison at cached-base rates.
- **First-deviation reuse (own proposal).** Exactly identical pairs have D = 0, so simulating them twice is waste. Cache the search and probe results by state hash from the base run, so a candidate run on identical states costs almost nothing. For `s3`-like changes this could skip up to about 80% of the compute. It does nothing for variance. It helps little for `e5`-like changes, though the prefix before deviation is still saved.
- **Triggered analysis does not improve t here.** The online 20x figure above comes from removing the noise of unaffected users. Pairing already removes it here, because unaffected seeds have D = 0 exactly, so restricting to triggered seeds leaves t about the same. The benefit is compute, not power.

### Gaps
- I found no published variance-reduction number for keyed streams in a game or roguelike. No source I read measures how much later correlation survives a deviation in a run-based game.
- A search excerpt attributed to Strens and Moore (ICML 2001) suggests changing scenarios during learning can generalise better than fixed PEGASUS scenarios. I could not tie it to a page I read, so treat it as unverified.
- Whether a run's luck persists across a deviation is game specific, since a different build reacts differently to the same grids. Only the pilot can answer this.

## Control variates and luck-adjusted scoring: AIVAT, DIVAT, MIVAT, Mahjong, CUPED and baseline value functions

### Takeaway
Luck adjustment is unbiased if the value function is fixed beforehand, but the gain scales with how good that value function is. Poker reports up to about 44x fewer games, and Mahjong reports about 14% lower variance. With this project's within-cell value R-squared near 0.25, expect a modest gain until the value model improves.

### Cited Findings
- AIVAT adds zero-expectation correction terms at chance events and at decisions of agents with known strategy, using any heuristic value function, and it stays unbiased — [Burch et al.](https://ar5iv.labs.arxiv.org/html/1612.06915).
- Reported per-game SDs in no-limit self-play — [Burch et al.](https://ar5iv.labs.arxiv.org/html/1612.06915):

| Estimator | SD (HUNL self-play) | SD reduction |
|---|---|---|
| Raw chips | 25.96 | none |
| MIVAT | 21.29 | about 18% |
| MIVAT + imaginary observations | 16.07 | about 38% |
| AIVAT | 8.10 | about 69% |

- The AIVAT abstract says more than a factor of 10 fewer hands in no-limit poker — [arXiv 1612.06915](https://arxiv.org/abs/1612.06915).
- With dissimilar strategies in Leduc the SD reduction was 48 to 75%, and with self-play in Leduc about 99.9% — [Burch et al.](https://ar5iv.labs.arxiv.org/html/1612.06915).
- In the DeepStack match, AIVAT cut SD by 85%, enough for significance in as few as 3,000 games. Search excerpts give the AIVAT paper's figure of 44 times fewer games, and a change from 492 +/- 220 to 486 +/- 40 mbb/g — [DeepStack](https://arxiv.org/pdf/1701.01724); [AAAI version](https://ojs.aaai.org/index.php/AAAI/article/view/11481).
- DIVAT needs a strategy for all players, and MIVAT generalises it to arbitrary value functions but only corrects chance events — [Burch et al.](https://ar5iv.labs.arxiv.org/html/1612.06915).
- Pluribus used AIVAT and reported 48 mbb/game with SE 25 — [secondary source](https://analyticsindiamag.com/how-this-ai-defeated-elite-poker-players/). Its raw result was negative — [Kim and Sandholm](https://arxiv.org/pdf/2605.14261).
- Kim and Sandholm (2026) warn that optimising the heuristic can push sample variance unrealistically low and can p-hack a test statistic. They conclude the heuristic must be fixed before seeing evaluation data. Their uncertainty propagation cut hands needed by 43%, on 10,000 poker hands, but can give up unbiasedness — [arXiv 2605.14261](https://arxiv.org/abs/2605.14261).
- Mahjong luck adjustment: MJ-DLVAT gives an unbiased rank estimate with lower variance — [U Tokyo thesis, search excerpt](https://repository.dl.itc.u-tokyo.ac.jp/record/2013721/files/48236414.pdf). A related workshop paper subtracts per-game luck from rank and reports variance 14% lower than the mean rank's — [IPSJ, search excerpt only, page returned 503](https://ipsj.ixsq.nii.ac.jp/records/229348).
- Suphx's global reward prediction is a training technique, not an evaluation method. For evaluation it resampled 2,000-game subsets 5,000 times to compare players, and said at least a few thousand games are needed for a reliable stable rank — [Suphx](https://arxiv.org/abs/2003.13590).
- CUPED on Bing cut variance by about 50%, the same power with half the users or half the duration, and the same metric from the pre-period was usually the best covariate — [Deng et al. 2013](https://exp-platform.com/cuped/).
- CUPED does not work where no pre-exposure data exists — [Statsig docs](https://doc.statsig.com/stats-engine/variance_reduction). In-experiment data can extend gains without bias under stated conditions — [Lin and Crespo](https://arxiv.org/pdf/2410.09027v2).

### Inferences
- **Simple form of luck adjustment for this game (own, MIVAT-style, single player):**

```
L = sum over chance events e of [ V(state after e) - mean_k V(state after an independent resample of e) ]
Y_adj = Y - L
D_adj = Y_adj(candidate) - Y_adj(base)
```

  Each bracket has zero expectation when the resamples are independent of the realised draw, so a small k stays unbiased. V must be frozen before the evaluation and must not be fitted on these seeds.
- **Expected size (own estimate).** Variance reduction is at most about the share of chance-driven variance that V explains. With the project's value fit of within-cell R-squared near 0.25, expect at most about 25% lower Var D. Compute time goes up by k value evaluations per chance node. Keying removes part of the same noise, so test the two together, not additively.
- **What to do first.** Value-based adjustment is priority 5. Value models here have had poor decision ranking (`pairs_corr` at most 0.044 in the roadmap), though luck adjustment only needs V to predict outcomes, not to rank actions.
- **CUPED equivalent.** With `theta = Cov(Y, X) / Var(X)`, then `Y_cv = Y - theta * (X - mean X)`, and variance falls by a factor `1 - rho^2`. This is the standard formula, but the page I could read shows only the abstract.
- **Paired seeds are already a covariate with theta = 1.** Crown and character are matched too, so adding them to D gives almost nothing.
- **The useful addition is a base pool (own derivation).** When the candidate plays n seeds, nested in N >= n seeds of cached base:

```
T = mean_n(Y_c) - rho * mean_n(Y_b) - (1 - rho) * mean_N(Y_b)
Var(T) = sigma^2 * (1 - rho^2) / n + sigma^2 * (1 - rho)^2 / N
```

  This reduces to the paired estimator when N = n. For `e5`-type values (sigma^2 = 6.59, rho = 0.42, n = 500), variance falls by 14% at N = 1,000, 22% at N = 2,000 and 25% at N = 4,000. For `s3`-type changes, with rho = 0.95, the gain is negligible. Fix rho in advance from earlier arms.
- **Covariates that are not valid.** `stage`, `lead_cursed` and anything else recorded after the policy acts are affected by the treatment, so do not adjust on them. Base-arm values are valid, because they are functions of the seed.
- **Stratified allocation (own estimate).** Using the `e5` SD by crown and the time per run by crown, cost-aware allocation `n_h proportional to sigma_h / sqrt(c_h)` saves about 11% over equal allocation for an equal-weight crown average. The inputs are noisy, so treat this as low priority.

### Gaps
- I found no DIVAT-only numbers. The AIVAT paper covers MIVAT, not DIVAT.
- I could not read the full MJ-DLVAT or IPSJ text, so the 14% figure needs checking. A poker paper's 30x claim appeared only in a search excerpt ([arXiv 2605.30094](https://arxiv.org/pdf/2605.30094)), so I would not rely on it.
- I found no published luck adjustment for a single-player roguelike.

## Sequential testing: SPRT, GSPRT, fishtest, OpenBench, always-valid inference, pentanomial, racing and successive halving

### Takeaway
A GSPRT on paired differences saved about 20 to 77% in my simulation on real difference data, with false positive rates near nominal (5.3% on `e5`-shaped differences and 5.7% on the sparse `s3` shape). The pentanomial model will add no saving, because the paired t already captures it. Successive halving reaches the same pick probability with about 37% fewer runs, but it cannot rescue very small budgets.

### Cited Findings
- Fishtest uses a GSPRT, replacing unknown parameters with maximum likelihood estimates. It treats the test as an SPRT on the drift of a Brownian motion, with infinitesimal variance estimated from the sample — [Fishtest Mathematics](https://official-stockfish.github.io/docs/fishtest-wiki/Fishtest-Mathematics.html).
- Fishtest's pentanomial model analyses paired games with reversed colours as five outcomes rather than three. The page says this saves substantial resources but gives no percentage. Bounds in normalised Elo make expected duration depend only on the bounds — [Fishtest Mathematics](https://official-stockfish.github.io/docs/fishtest-wiki/Fishtest-Mathematics.html).
- The correlation within pairs is reported as real and fairly strong in a forum post by Fishtest's statistician — [Talkchess, search excerpt](https://talkchess.com/viewtopic.php?p=785503).
- Stockfish-style gainer bounds such as [0, 2] pair with non-regression bounds such as [-1.75, 0.25], and looser bounds such as [0, 5] and [-5, 0] are listed for weaker engines. The source table is flattened, so the pairing of labels to rows is uncertain — [Chessprogramming wiki](https://www.chessprogramming.org/Sequential_Probability_Ratio_Test).
- OpenBench says 0.05 is generally a good value for alpha and beta — [OpenBench wiki](https://github.com/AndyGrant/OpenBench/wiki/SPRT-and-Fixed%E2%80%90Game-Workloads).
- Uncorrected continuous monitoring can raise Type I error about fivefold at 10,000 samples. mSPRT p-values stay valid under any stopping rule. Mis-setting the mixing scale by one order of magnitude costs under 5% power and about 10% run length — [Johari et al.](https://ar5iv.arxiv.org/html/1512.04922).
- Vendor documents claim 30 to 60% savings from SPRT, without a worst-case bound — [MetricGate](https://metricgate.com/docs/power-sprt-sequential/). Treat that as weak evidence.
- A model mismatch can make a sequential test need more samples on average than the fixed test — [search excerpt, likely Fading Boundaries](https://arxiv.org/pdf/2010.12094). The Kiefer-Weiss problem is about minimising that worst case — same source.
- Sequential halving, from Karnin et al. 2013, is a near-optimal fixed-budget method under homogeneous variances — [search excerpt](https://arxiv.org/pdf/1609.02606). Hyperband wraps it in a loop over the trade-off between configurations and budget per configuration — [Li et al.](https://arxiv.org/pdf/1603.06560).
- Iterated racing evaluates configurations on a first set of instances, then tests after each further instance using a paired test such as Friedman or t, optionally with multiplicity correction — [irace guide](https://search.r-project.org/CRAN/packages/irace/vignettes/irace-package.pdf); [Bischl et al.](https://arxiv.org/pdf/2107.05847).

### Inferences
Formula a solo developer can implement (own, the Brownian form):

```
Choose delta0 = 0, delta1 = target gain, alpha = 0.05, beta = 0.2
A = ln((1 - beta) / alpha) = 2.77     B = ln(beta / (1 - alpha)) = -1.56
After each balanced block:
  S_n = sum D_i        var = sample variance of D
  LLR = (delta1 - delta0) / var * (S_n - n * (delta0 + delta1) / 2)
  LLR >= A: accept | LLR <= B: reject | otherwise continue
At cap (1.5 x fixed n): use the ordinary t test at 1.65
```

Wald's expected sample size (standard approximation, calculated by me; see Gaps on the source):

- `E[N | H1] = ((1-beta) * A + beta * B) / D`, where `D = delta1^2 / (2 * SD^2)`
- `E[N | H0] = ((1-alpha) * (-B) - alpha * A) / D`
- `E[N | midpoint] = A * (-B) * (SD / delta1)^2`

| SD | delta1 | Fixed n (80% power) | E[N] H1 | E[N] H0 | E[N] midpoint |
|---|---|---|---|---|---|
| 2.5 | 0.2 | 966 | 596 | 419 | 675 |
| 2.5 | 0.3 | 430 | 265 | 186 | 300 |
| 5 | 0.2 | 3,866 | 2,383 | 1,677 | 2,700 |

Own simulation, resampling the actual `e5` differences (SD 2.8) with looks every 66 seeds, a cap of 1.5x fixed n, 4,000 repeats, alpha 0.05 and beta 0.2. Hours assume cached base.

| True effect, for delta1 = 0.2 (fixed n = 1,208, 3.4 h) | Mean seeds | 90th pct | P(accept) | Saving | Hours |
|---|---|---|---|---|---|
| 0 (null) | 650 | 1,386 | 5.3% | 46% | 1.8 |
| +0.1 (midpoint) | 963 | 1,848 | 40% | 20% | 2.7 |
| +0.2 (target) | 866 | 1,716 | 84% | 28%, with more power | 2.4 |
| +0.4 (twice target) | 415 | 660 | 99.7% | 66% | 1.2 |
| -0.2 (harmful, 88-seed looks) | 276 | not recorded | 0% | 77% | 0.8 |

Scale seeds and hours by 0.8 for SD 2.5. A rerun with 88-seed looks gave 656 seeds at the null (5.3% accepted) and 906 at +0.2 (84.7% accepted), so look size barely matters between 66 and 88.

Practical rules (own):

- **Look only at complete blocks.** One block is 88 seeds, one for each character x crown cell. Stopping mid-block unbalances crowns.
- **Sparse differences need no special rule.** On `s3`'s shape (88% zeros, delta1 = 0.1, fixed n = 446, 88-seed looks, zeros kept at zero), the false positive rate was 5.7%, with 254 seeds at the null (43% saving) and 359 at +0.1 (20% saving, 85.5% power). A minimum of 100 non-zero differences before stopping used up the whole cap and removed the saving, so I do not recommend one. An earlier run that shifted the zeros as well gave 10.3%, which was an artefact of that shift.
- **Use the same rule for a non-regression check on wins.** Use bounds such as [-delta, 0] with the order reversed.
- **Pentanomial mapping.** In chess the pair is two colours on one opening. Here the pair is two arms on one seed, and D is continuous. The empirical variance of D already does what the pentanomial model does, so expect no extra saving. The trinomial analogue is treating arms as independent, which `compare` does not do.
- **Mixture alternative.** With `V = SD^2` and normal mixing variance tau^2, `Lambda_n = sqrt(V / (V + n * tau^2)) * exp(n^2 * tau^2 * mean^2 / (2 * V * (V + n * tau^2)))`. Reject when Lambda_n >= 1/alpha. Use it when delta1 is hard to choose. It is my rescaling of a closed form worked out from the paper's mixture integral, not printed in the paper, and it is two-sided, so it is more conservative than the one-sided GSPRT.
- **Successive halving with `K` candidates and budget `B`.** There are `R = ceil(log2 K)` rounds. Each round splits `B / R` evenly among survivors and drops the worse half.

Own simulation, 16 candidates with one true +0.3 and SD 2.8. "Budget" means candidate runs, with base cached.

| Budget (hours) | SH P(pick best) | Uniform P(pick best) | SH true gain / reported | Uniform true gain / reported |
|---|---|---|---|---|
| 1,600 (4.4) | 0.41 | 0.28 | 0.12 / 0.28 | 0.09 / 0.54 |
| 3,200 (8.9) | 0.58 | 0.42 | 0.18 / 0.26 | 0.13 / 0.41 |
| 6,400 (17.8) | 0.78 | 0.64 | 0.23 / 0.26 | 0.19 / 0.34 |

- SH reaches uniform's 0.64 at about 4,000 runs instead of 6,400, which saves about 37%, or about 6.7 hours per search. The 4,000 is my interpolation.
- Even SH's reported gain overstates the truth, so always follow with confirmation on fresh seeds.
- With Delta/SD near 0.1, the first round of a small budget mostly drops candidates by chance. Below about 100 seeds per candidate in round 1, cut K rather than spread the budget thin.

### Gaps
- I could not obtain a published fishtest figure for the pentanomial saving or expected games. Its `sprta.py` script and linked PDFs would give them, and the [fishtest page](https://official-stockfish.github.io/docs/fishtest-wiki/Fishtest-Mathematics.html) only points to them.
- Two pages that should state Wald's formula failed to load, so I give it as a standard result that I computed from. Its pattern matches my simulation.
- `compare` and `chartune.py` were not altered or tested for any of this.

## Multiple comparisons and selection bias: winner's curse, optimizer's curse, FDR, holdout seeds and shrinkage

### Takeaway
At t >= 1.65, picking the best of 16 nulls passes about 56% of the time. The fix is a selection stage on one seed block, then a single test on seeds never used before, then reporting a shrunk estimate. This matches the project's own history of leads that failed on fresh seeds.

### Cited Findings
- Smith and Winkler show that choosing the highest estimate produces expected disappointment that may be substantial, and they propose Bayesian adjustment of value estimates — [Duke record](https://fds.duke.edu/db/aas/stat/faculty/bob.winkler/publications/278471); [paper](https://www.gwern.net/doc/statistics/decision/2006-smith.pdf).
- Conventional intervals can severely under-cover after selecting a winner, and winner's-curse corrections matter but still leave informative inference — [Andrews, Kitagawa and McCloskey](https://econpapers.repec.org/RePEc:oup:qjecon:v:139:y:2024:i:1:p:305-358.).
- Type M error (exaggeration given significance) rises as power falls. It reaches about 3.5 at 10% power in a two-sided example — [secondary source on Gelman and Carlin](https://td.jcx.au/interpreting-trial-results/type-m-and-type-s-errors).
- Kohavi cites success priors of about 8 to 33% for ideas in industry, and says false positive risk depends on that prior — [Kohavi, informal document](https://docs.google.com/document/d/1sRKParLv0UdOsdAJDTKxPRJstkEDP2Rg/export?format=pdf). He estimated one published lift was inflated about 4.6x and recommended replication — [Kohavi, informal document](https://docs.google.com/document/d/1IDcLEr58QoQU2VJPc-TefLMLegdQMnh3/mobilebasic?pli=1).
- Meta researchers report selection inflating launched effects, and use a local empirical Bayes shrinkage to resist a mis-specified prior — [Mudd et al.](https://arxiv.org/pdf/2603.12867).
- Reusing a holdout adaptively can overfit it. The reusable holdout limits access through a differentially private mechanism — [Google Research](https://www.research.google/blog/the-reusable-holdout-preserving-validity-in-adaptive-data-analysis/); [Dwork et al.](https://ar5iv.labs.arxiv.org/html/1506.02629).
- BH: find the largest k with `P(k) <= (k/m) * alpha`, then reject the first k. It controls FDR under independence and positive dependence. Benjamini-Yekutieli divides by `c(m) = sum 1/i` for arbitrary dependence — [Wikipedia](https://en.wikipedia.org/wiki/False_discovery_rate).
- **Project history.**
  - `shared k=1` scored 51 vs 37 wins on evaluation seeds, then 48 vs 49 on fresh seeds.
  - Spike `swap_sell` was promoted by `chartune` and scored -0.20 on the benchmark.
  - Best-of-16 on per-class weights was labelled winner's curse — `docs/game-research/ai-roadmap.md`.

### Inferences
Own calculations with independent normals:

| K candidates | E[max z] under null | P(any t >= 1.65) under null | Sidak z for 5% overall |
|---|---|---|---|
| 4 | 1.03 | 18% | 2.23 |
| 8 | 1.42 | 33% | 2.49 |
| 13 | 1.67 | 48% | 2.66 |
| 16 | 1.76 | 56% | 2.73 |
| 32 | 2.07 | 80% | 2.95 |
| 64 | 2.35 | 96% | 3.16 |

- **Quick check.** Under the null, the best-of-K is expected to show about `E[max z] * SD_D / sqrt(n)`. At K = 16, SD 2.8 and n = 528, that is +0.21. A +0.2 result from a search of this size is what no effect looks like.
- **False discovery risk**, `FDR = alpha * (1-p) / (alpha * (1-p) + power * p)`, at alpha 0.05:

| Prior true fraction p | Power 0.3 | Power 0.8 |
|---|---|---|
| 10% | 60% | 36% |
| 20% | 40% | 20% |
| 33% | 25% | 11% |

  Given this project's run of failed candidates, p is probably at the low end, so a lone t of 1.65 is weak evidence.
- **Exaggeration at the 1.65 threshold**, own calculation: 2.7x at 20% power, 2.0x at 30%, 1.5x at 50%, 1.14x at 80%.
- **Seed policy:**
  - Search on the 7M block and let it be used up.
  - Treat the 8M benchmark block as shared and increasingly contaminated, since each decision made on it leaks. It suits regression checks and racing only.
  - Promote only on a new block used once by one candidate, for example 9M + 10,000 x k.
  - A pass after selection on fresh seeds has a false promotion rate of about alpha (5%) per search, regardless of K, against 56% at K = 16 with no fresh seeds.
- **Multiple tests on one fresh block.** Use BH at q = 0.1 for exploratory cells such as character x crown, and Holm or Sidak for promotions. Paired results on shared seeds and a shared base are positively correlated, so BH is reasonable, and BY is the fallback.
- **Shrinkage for one estimate:** `shrunk = B * observed`, where `B = tau^2 / (tau^2 + SE^2)`.

| tau (true effect SD) | n | SE | Observed at t 1.65 | Shrunk |
|---|---|---|---|---|
| 0.1 | 1,000 (SD 2.5) | 0.079 | 0.13 | 0.08 |
| 0.1 | 528 (SD 2.8) | 0.122 | 0.20 | 0.08 |
| 0.2 | 528 (SD 2.8) | 0.122 | 0.20 | 0.15 |
| 0.3 | 528 (SD 2.8) | 0.122 | 0.20 | 0.17 |

- **Hierarchical model for character x plan or crown cells:**

```
d_ij = mu + a_i + b_j + c_ij + noise_ij,   noise SE = s_ij
a_i ~ N(0, tau_a^2), b_j ~ N(0, tau_b^2), c_ij ~ N(0, tau_c^2)
Quick method of moments for one factor:
  tau^2 = max(0, Var(d_j) - mean(s_j^2))
  theta_j = mean_d + (tau^2 / (tau^2 + s_j^2)) * (d_j - mean_d)
```

  Each of the 88 cells has six seeds, so SE is about 2.8 / sqrt(6) = 1.14. If true cell effects have SD 0.5, B is about 0.16. Cell-level differences at this sample size are mostly noise, and a per-character table will not be trustworthy without pooling. Report `theta` for per-character tuning, not the raw value. This fits the `chartune` result.
- **Estimate tau from past arms.** Using the log of all benchmarked arms gives the prior, and also an honest empirical p. The roadmap records many past comparisons, though I did not count them or their sample sizes.
- **Report line for each promotion:** raw mean and t, seeds used, candidates searched (K), shrunk estimate, 90% bootstrap interval, and result on fresh seeds. The confirmation estimate alone is free of selection bias only when no optional stopping occurred. A sequential stop still inflates the estimate modestly at early stops.

### Gaps
- I did not read the full Andrews et al. or Mudd et al. papers, so their corrections are not reduced to formulas here. Shrinkage plus fresh seeds is the simpler alternative.
- I could not find a game-AI source that measured selection bias from repeated seed reuse. The closest are the project's own history and the RL literature below.

## Better metrics: which metric is most sensitive, is a surrogate safe, and how to evaluate rare wins

### Takeaway
Keep mean outcome as the primary sequential metric, and require wins to pass a non-inferiority check. No alternate metric reliably beat it on the data available. Decomposing wins into stage survival adds no precision unless a shared effect is assumed. Use surrogates and stage probes for screening only, never for promotion.

### Cited Findings
- Surrogate index: regress the long-term outcome on intermediate outcomes, then compare arms on the predicted value. A job-training experiment using six quarters of employment reached a 35% reduction in standard errors. This relies on the outcome being independent of treatment given the surrogates — [Athey, Chetty, Imbens and Kang](https://www.nber.org/papers/26463).
- That paper characterises the bias from violations and gives simple validation methods — [same paper](https://www.nber.org/papers/26463).
- The surrogate paradox: treatment can improve the surrogate, the surrogate can correlate positively with the outcome, and treatment can still harm the outcome — [Chen, Geng and Jia 2007](https://econpapers.repec.org/RePEc:bla:jorssb:v:69:y:2007:i:5:p:919-932); [PMC review](https://pmc.ncbi.nlm.nih.gov/articles/PMC4366594).
- The Prentice criterion cannot guarantee exclusion of the paradox — [Individual Surrogate Paradox](https://arxiv.org/pdf/1712.08732). VanderWeele lists conditions under which it can occur, including a direct effect in the opposite direction — [VanderWeele](https://statistics.fas.harvard.edu/resource/vanderweele14pdf).
- Ordinal analysis versus binary: a stroke-trial analysis found ordinal methods cut sample size by about 28% on average, but raised it for thrombolysis, where treatment both helps and harms — [OAST 2008](https://nectar.northampton.ac.uk/id/eprint/1427/). Whitehead's formula assumes proportional odds, and power can suffer when this fails — [Hmisc docs](https://www.rdocumentation.org/packages/Hmisc/versions/5.1-2/topics/popower); [arXiv 2108.06568](https://pdf.arxiv.org/pdf/2108.06568).
- **Project history of surrogates failing.**
  - `build_value` had CV R-squared 0.52 and lost -0.11.
  - `build_value_risk` lost -0.32 (t -2.1).
  - One-stage strength is repeatable, with split-half correlation 0.67 — `docs/game-research/ai-roadmap.md`.
- **Metric sensitivity on available arms (project measurement, 528 seeds).** These two arms are illustrative only. Any metric could win on a pair of arms by chance.

| Metric | `e5` mean | `e5` SD | `e5` t | `s3` mean | `s3` SD | `s3` t |
|---|---|---|---|---|---|---|
| Outcome | +0.245 | 2.80 | +2.02 | -0.047 | 0.85 | -1.26 |
| Outcome capped at 16 | +0.276 | 2.44 | +2.60 | -0.016 | 0.49 | -0.77 |
| Stage | +0.078 | 0.82 | +2.17 | -0.006 | 0.14 | -0.90 |
| Signed-rank z | | | +1.89 | | | -1.19 |
| Crown-weighted z | | | +2.03 | | | -1.49 |
| Won | +0.011 | 0.38 | +0.69 | -0.002 | 0.18 | -0.24 |
| Lead cursed | +0.049 | 0.91 | +1.24 | -0.004 | 0.15 | -0.58 |
| Reached Michael | -0.004 | 0.25 | -0.34 | -0.004 | 0.06 | -1.42 |

- **Base win rate by crown (project measurement):** 56%, 39%, 26%, 15%, 9%, 6%, 4.5%, 1.5% for crowns 0 to 7. Runs end as 424 out of grids, 67 final boss, 26 Michael lost, 11 Michael won. Win pairs for `e5`: 41 gained and 35 lost out of 528, so 14.4% are discordant.

### Inferences
- **Win comparison rule (McNemar).** Only discordant pairs matter. With `b` gained, `c` lost and discordant rate `pi = (b+c)/n`:
  - `z = (b - c) / sqrt(b + c)`
  - `n = (z_a + z_b)^2 * pi / delta_win^2`
- **Cost of wins (own estimate).** For `e5`-type changes, +2 percentage points of wins needs about 6.18 * 0.144 / 0.02^2 = 2,225 seeds. That is 6.2 hours cached and 12.4 hours with both arms, with sequential saving of about 30 to 45% on top. `e5` at n = 528 had z = 0.69, so 528 seeds cannot resolve wins for any effect of this size.
- **A recommended two-metric gate.**
  - The primary test is the GSPRT on outcome, or on capped outcome if it validates.
  - The second test is a non-inferiority check on wins: the lower confidence bound on win-rate difference should be above about -2 points.
  - Michael has a separate pass/fail, since its +8 is a heavy tail. Capping removes 24% of `e5` Var D and 67% of `s3`, but in `s3` the t also fell, because the mean shrank too. This shows the risk that capping hides a real effect at Michael.
- **Survival decomposition.** Without censoring, Kaplan-Meier equals the empirical proportion, so `product(1 - h_s)` estimates exactly the same number as raw wins, with the same variance. Precision comes only from an added assumption.
  - The useful assumption is a discrete-time model: `logit h(s | crown, char, arm) = a_s,crown + b_char + beta * arm`.
  - A single beta uses every stage's survival, so it has far more events than wins. It is a good test where the effect is similar across stages.
  - It fails when a change helps early but costs later, such as `build_value`: crowns 0 to 2 fell (wins 80 to 67) and 3 to 7 rose (24 to 34), though that split was post hoc.
  - Always check for stage x arm interaction.
- **Pooling across crowns for rare wins.** Fit `logit P(win) = a_crown + b_char + beta * arm`, or use Cochran-Mantel-Haenszel by crown. Information per seed on the logit scale is `p(1-p)`: 0.246 at crown 0, 0.129 at crown 3, 0.015 at crown 7. Per CPU-second this is fairly flat, 0.0025 at crown 0 and 0.0010 at crown 7, since high crowns run cheaply. So pooling helps and no crown is wasted.
- **Rare high-crown wins.** Report per-crown win differences only after shrinkage. Crown 7 has one win in 66 runs. To evaluate high crowns directly, split the run: replay many continuations from saved final-stage entry states drawn from each arm, and multiply by the arm's reach rate. This is a form of multilevel splitting, which needs clones and has not been tried here.
- **Stage-level strength probes.** With repeatability of 0.67 against run-outcome test-retest near 0.21, probes are likely much more sensitive for build strength. They are a surrogate though, and `build_value` is the warning.
  - Use them for round 1 of racing only.
  - Check trial-level surrogacy: over 10 to 20 past arms, regress realised run-level D on the probe's D. Only trust a probe with a clear slope.
  - A Prentice-style check: regress D on delta S, and look for an intercept significantly different from 0.
- **Surrogate index gain.** A 35% reduction in SE equals about 58% lower variance, if surrogacy holds. In this project such an index could cut screening time by half. It must not be the promotion test.

### Gaps
- Two arms cannot rank metrics. The comparison needs every arm from the roadmap's history, including stage trajectories, which `bench` does not record beyond the final stage. Recording encounter-by-encounter survival is cheap and would allow this.
- I found no game-AI study comparing mean score, win rate and survival models for sensitivity.
- I did not fetch multilevel splitting sources, so that suggestion rests on my own reasoning.

## Off-policy evaluation: where IS, doubly robust and fitted Q work and fail, why offline ranking overstates play gain, and how to calibrate

### Takeaway
OPE is not reliable enough to promote a policy here. It may be useful for low-cost ordering and for single-decision effects measured with randomised trials. Whole-policy importance sampling has an impractically small effective sample. Offline gains overstate play because of selection on noisy predictions, distribution shift and interactions, so calibrate on played decisions by decile.

### Cited Findings
- IS weights multiply along a trajectory, so variance can grow exponentially with horizon. Liu et al. use stationary-distribution ratios to remove the horizon dependence, though estimating these ratios is the hard part. A reviewer notes the scope seems limited to average reward — [Liu et al.](https://arxiv.org/pdf/1810.12429); [reviews](https://papers.neurips.cc/paper_files/paper/2018/file/dda04f9d634145a9c68d5dfe53b21272-Reviews.html).
- The DOPE benchmark found no evaluated algorithm near oracle performance on any metric, and no method consistently good across tasks. Average rank correlation was 0.69 on RL Unplugged and 0.25 on D4RL — [Fu et al.](https://ar5iv.labs.arxiv.org/html/2103.16596).
- Median rank correlations on RL Unplugged were: model-based AR 0.90, FQE 0.70, DR 0.55, VPM 0.01, IS -0.17. Task spread is wide, with FQE ranging from 0.96 to -0.48 and IS from 0.91 to -0.72 — [Fu et al.](https://ar5iv.labs.arxiv.org/html/2103.16596).
- One FQE variant severely overestimates poor policies — [Fu et al.](https://ar5iv.labs.arxiv.org/html/2103.16596).
- Voloshin et al. studied OPE methods across varied conditions, and their results challenge common beliefs about which class works. A survey says FQE performed surprisingly well despite its simplicity — [Voloshin et al.](https://arxiv.org/pdf/1911.06854); [survey](https://arxiv.org/pdf/2203.01387).
- FQE plus ranking on estimated initial value was reported sufficient for offline hyperparameter selection in some settings, under policy-constraint algorithms — [survey on Paine et al.](https://arxiv.org/pdf/2203.01387).
- **Project history.**
  - Out-of-fold ranking was +0.05 (t 3), and later +0.15, while play stayed at or below zero.
  - Per-class buy weights with all columns lost -0.93 in play.
  - Fit R-squared within 0.25 lost at every margin.
  - The `--rct-penalty` uncertainty penalty made every model safe — `docs/game-research/ai-roadmap.md`.
- The Smith and Winkler disappointment result applies directly to taking the maximum over noisy predictions — [paper](https://www.gwern.net/doc/statistics/decision/2006-smith.pdf).

### Inferences
- **Effective sample of whole-policy IS (own calculation).** With a logging policy that randomises with probability epsilon at each of T decisions, only a share of about `(1 - epsilon)^T` of runs matches a deterministic target throughout. That is 2.8% at epsilon 0.3, T = 10, and 0.002% at epsilon 0.3, T = 30. With T = 100 and epsilon = 0.05, it is 0.6%. Estimate it with `ESS = (sum w)^2 / sum w^2`, and do not trust IS if ESS is under about 100.
- **Where IS works here.** It can work for one decision kind changed at one point with randomised logging, which is what the existing RCT trainer does. Doubly robust adds a baseline to the same weights. It only lowers the variance by as much as the value model is accurate, and with a value R-squared near 0.25 it does not rescue long horizons.
- **Why offline ranking overstates play (own explanation):**
  - Picking the top of K noisy predictions gives an upward bias of about `SE_pred * E[max z over K]`. Project data has small true advantages, with labels about 21% signal.
  - The labels assume base continues after the decision, but a policy with many overrides visits other states and has other continuations.
  - Overrides interact, so gains do not add up. Earlier gains can undo later ones.
  - Rank correlation is an average over all decisions, while play only uses the extreme predictions.
- **A gain model that gives early warning (own, analogous to the breeder's equation).** Expected true gain per override is about `i * r * SD_true`, where `i` is the selection intensity, `r` is the correlation of prediction with true advantage, and `SD_true` is the SD of true advantages. Multiply by overrides per run. Compare the result to realised play gain. If play is far below this, interaction or distribution shift is the cause, not ranking accuracy.
- **Decile calibration protocol (own).**
  1. Freeze the model.
  2. On fresh seeds, at each decision where the model would override, randomise whether to apply the override, with probability 0.5 and at most a few per run. Keep the rest of the run under the model policy.
  3. Bin by predicted advantage into deciles.
  4. For each bin, compute realised D with keyed continuation, and a bootstrap interval.
  5. Fit `realised = a + beta * predicted`. Use `beta * predicted` as the margin input and only keep overrides where the shrunk prediction beats cost.
  6. Report beta in every training run. A beta below about 0.3 means offline accuracy is not a reliable guide.
- **Cost.** The roadmap's 512-run pilot recorded 4,500 trials, half of them copies, and the later 35% randomised setting doubled trials per run. So I assume about 4 to 9 usable trials per run. That makes 512 runs (1.4 hours) worth about 2,000 to 4,500 trials, or 200 to 450 per decile. With a label SD of 2.2 to 0.8, the SE per decile is about 0.04 to 0.16, which is enough to see a slope. Smoothed labels are subject to the same surrogate concerns as above.
- **Using OPE as a filter.** FQE or the existing model can reject clearly bad candidates before any play. Treat it as round 0 of racing. Do not count it as evidence for promotion. The DOPE result suggests a ranking correlation that may be near 0.25 to 0.7 and is unstable across tasks.

### Gaps
- I did not find a game-AI paper that publishes predicted against realised gain by decile. The protocol is my adaptation of standard calibration.
- A search for Levine et al.'s offline RL tutorial returned nothing on distribution shift, so that explanation is my own reasoning here.
- DOPE used control benchmarks, not a stochastic discrete game with hundreds of decisions, so its numbers may be optimistic or pessimistic here.

## Reproducibility checks: Agarwal et al. 2021, Henderson et al., and applying them to game AI

### Takeaway
Adopt stratified bootstrap intervals, A/A runs, and split-half replication. Do not adopt IQM as the primary metric, since it would discard the win tail that the user cares about.

### Cited Findings
- Agarwal et al. show point estimates can mislead, and recommend interval estimates, performance profiles and robust aggregates such as IQM, which they say gives much smaller CIs than the median. It received an Outstanding Paper Award at NeurIPS 2021 — [arXiv abstract](https://arxiv.org/abs/2108.13264); [full text](https://ar5iv.labs.arxiv.org/html/2108.13264).
- IQM discards the top and bottom 25% of runs and averages the rest. Stratified bootstrap CIs are recommended, and percentile CIs are good from about N = 10 runs — [Agarwal et al.](https://ar5iv.labs.arxiv.org/html/2108.13264).
- Medians from 3 to 10 runs, which are common, showed substantial bias. For one algorithm, the difference between 5 and 100 runs was about 36% of its claimed improvement. Reliable medians in Atari 100k needed about 50 to 100 runs — [Agarwal et al.](https://ar5iv.labs.arxiv.org/html/2108.13264).
- Probability of improvement estimates how likely X outperforms Y on a random task. In Procgen, some reported improvements were only 50 to 70% likely — [Agarwal et al.](https://ar5iv.labs.arxiv.org/html/2108.13264).
- Henderson et al. showed that ten runs of one algorithm, split into two groups of five, can look like two different distributions, and the papers they reviewed used 5 seeds or fewer — [via Colas et al.](https://arxiv.org/pdf/1806.08295).
- Colas et al. give a power analysis for choosing seed counts, and warn that violating test assumptions can make error estimates inaccurate — [Colas et al.](https://arxiv.org/pdf/1806.08295).
- **Project practice already includes** seed-halves replication, code fingerprints and per-crown and per-character reports — `cursed_words_solver/sim/game/bench.py`.

### Inferences
Applied checks (own):

- **IQM.** Roughly 20% of runs win and they form the top of the score distribution, so a 25% trim removes almost exactly the outcome of interest. Use IQM only as a secondary robust check for mid-game strength. It may be useful within a crown, not across crowns.
- **Stratified bootstrap.** Resample seed indices within character x crown cells, 10,000 times, on `D`. Report mean, 90% interval, and P(D mean > 0). This is about 15 lines and takes seconds. It handles heavy tails and zero inflation better than t.
- **Probability of improvement across cells.** Compute the fraction of crowns or characters improved after shrinkage. Do not use raw per-cell signs on six seeds.
- **A/A runs.**
  - Run base against base with a different RNG salt. This is 528 runs, about 1.5 hours, once.
  - That gives the true null SD with no shared randomness, and tests the t and GSPRT false positive rates. Expected SD_D is about 3.4 to 3.6.
  - Base against the same base with identical seeds must give D = 0 everywhere. One 88-seed block (about 15 minutes) is enough for this determinism check.
- **Split-half.** Keep reporting the first and second halves. A pass is only worth believing if both have the same sign and neither depends on one crown. Since halves are from a block already used for selection, this does not replace fresh seeds.
- **Test the pipeline itself.** Feed synthetic differences with known effects and the real shape into the whole stage-gate process, then check false promotion and true-gain recovery. It takes seconds, and my scripts for this could be adapted.
- **Periodic drift audit.** Rerun the current base on a new seed block when the base is promoted. A base mean that falls by more than about 2 SE shows contamination in the seed block.
- **Crash and fingerprint rules.** `bench` counts a crash as a loss and records it. Report the crash count per arm, and refuse the GSPRT if counts differ between arms, since a sudden difference would dominate a small effect.
- **Sample size note.** `bench.py` says paired SD is about 3.3. Measured SDs of 2.8 and 0.85 show that this figure should be reported per change, since `n` varies by more than 10x across changes.

### Gaps
- The published RL recommendations are about training-seed variance across tasks. This project's noise is episode noise within one trained policy, so sample-size numbers do not transfer directly. Only the methods do.
- The number of runs at which IQM matches the median is not stated as a figure in the portion of the paper I read.
