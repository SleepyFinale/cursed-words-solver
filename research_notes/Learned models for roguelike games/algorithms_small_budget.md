# Learning and search algorithms for a stochastic, long-horizon, single-player game on a very small sample budget

Source caveat for the whole file: many papers were read as arXiv abstracts or through a summarising fetch tool, not in full. Where a number comes from a secondary source, it says so. All "days at this budget" conversions, power calculations and fit ratings are my own arithmetic or judgment and sit under Inferences.

## Overall: which methods fit this budget?

### Takeaway
At about 750k decisions a day and outcome SD of about 4, the budget is 2 to 4 orders of magnitude below what published game agents used. The two best-supported strategies are structured improvement of the rules player (with validation on real play) and buying more budget through variance reduction and caching. Learning a policy from scratch is not supported by the evidence here.

### Cited Findings
- Project speed: about 56 CPU-s per run at about 55 states per run; 512 runs gave 51 wins (about 10%) — [docs/game-research/sim-game.md, line 777](docs/game-research/sim-game.md).
- Project profile, for the `power` policy on one benchmark run: 97% of time in word search, 92% of that in shop probes, with encounters themselves 16 s of 357 s — [docs/game-research/sim-game.md, lines 494-496](docs/game-research/sim-game.md).
- A cheaper play-out policy costs 9.7 s against 34.7 s per run — [docs/game-research/sim-game.md, line 562](docs/game-research/sim-game.md).
- Closest roguelike analogue: symbolic bots beat neural agents in the NetHack Challenge, with the best symbolic median "nearly threefold" the neural one, even with a neural policy trained for 10B steps on 224 cores and 16 V100 GPUs — [Hambro et al. 2022](https://ar5iv.labs.arxiv.org/html/2203.11889). A later paper describes the challenge gap as over fourfold in median score, so the two sources differ — [Piterbarg et al. 2023](https://arxiv.org/abs/2305.19240).

### Inferences
**Budget arithmetic used throughout (mine):**
- CPU per day: 8 × 86,400 = 691,200 CPU-s. At 56 CPU-s per run that is about 12,300 runs a day, or about 750k-925k decisions. This matches the brief's 500k-1M.
- Decision speed: about 10.7 decisions/s across all workers at full policy, about 62/s at the 9.7 s policy.
- Run-level testing, 80% power, two-sided 5%, unpaired, n per arm = 15.68σ²/δ²:

| Test | n per arm | Total runs | Days at 12k/day |
|---|---|---|---|
| +0.15 at σ=2.5 | 4,356 | 8,700 | 0.7 |
| +0.15 at σ=4 | 11,150 | 22,300 | 1.8 |
| +0.15 at σ=5 | 17,422 | 34,800 | 2.9 |
| win rate 10% to 11% | about 15,000 | 30,000 | 2.5 |
| win rate 10% to 12% | about 3,800 | 7,700 | 0.6 |

So "zero extra wins" is only informative if the test had roughly 15k runs per arm. Anything smaller cannot exclude a +1 point gain.

- Label noise ceiling: with single-sample labels of noise SD σ=4 and true advantage SD τ, the best possible Pearson correlation is τ/√(τ²+σ²). That is 0.06 at τ=0.25, 0.12 at τ=0.5, 0.24 at τ=1. If the 0.19 was measured against single noisy labels, it implies a real spread near 0.8, which most likely comes from blunders being easy to spot, not from finding moves better than the rules player. This would explain a respectable offline score with a tiny play gain. Check by computing the metric only on moves where the model disagrees with the rules player, and against the rules player's own move.
- Data capacity: resolving a mean to SE 0.1 at σ=4 needs 1,600 samples, and to SE 0.2 needs 400. So 76,000 labels support about 50-190 independent effects. A LightGBM with hundreds of leaves per tree is far past that without heavy shrinkage.

**Fit ratings (mine):**

| Method | Fit | What it needs | Likely behaviour here |
|---|---|---|---|
| Probe caching and profile-led speedups | Excellent | Engineering days | Multiplies every other method |
| Variance reduction (AIVAT-style control variates, stage-based labels) | Excellent | A usable value model | Could cut needed runs several-fold; unproven here |
| Policy-level factorial tuning of rules-player parameters | Good | 20-200 parameters, 20k runs per round | All main effects to about ±0.06 per round; steady gains |
| Guarded one-step improvement (current advantage model, thresholds, targeted re-testing) | Good | Existing data, 20-50k runs per iteration | Small safe gains; avoids the winner's curse |
| Truncated rollouts on rare high-stakes decisions | Good, narrow | Stage value estimate; 100s of CPU-hours per set of decisions | Worthwhile for boss choice, unaffordable everywhere |
| Classification-based API using rollout labels | Moderate | 10⁷-scale samples in Tetris | Several weeks; best after speedups |
| TD or Monte Carlo with hand features | Moderate after speedups | 200k-1M runs | 17-83 days today, feasible at 10x speed |
| Residual RL, Q-filter, JSRL | Weak to moderate | Well-fitted critic, 10M+ steps | High risk of unlearning the rules player |
| Gumbel AlphaZero | Weak today | Prior + value net; 16 sims is 3-16× per run cost | Only as a late-stage search on top of a good value |
| Offline RL (CQL, IQL) | Weak | Fixed data, deep nets | Solves a problem you don't have: you own a simulator |
| PPO / IMPALA from scratch | Poor | 10⁷-10¹⁰ steps | Plateaus below the rules player |
| BC then PPO | Poor to weak | 10⁷+ steps | Likely trails the rules player, based on analogues |
| Stochastic MuZero, Sampled MuZero | Poor | Same as AlphaZero plus model learning | Pointless with an exact simulator |
| Nested Monte Carlo | Poor live | Deterministic game | Clairvoyant plans under fixed seeds |
| JAX rewrite | Poor | Accelerator, fixed-shape logic | Trie-style word search fits badly; no GPU assumed |

**Suggested order:** (1) re-profile the current default policy, then cache probes; (2) measure variance reduction and move to stage-based labels; (3) run factorial parameter tuning; (4) run guarded override iterations with targeted re-testing; (5) add truncated rollouts for boss choice, which the project's roadmap notes flag as the main gap to the Michael result; (6) revisit TD or deep Monte Carlo only once the simulator is 10x faster.

### Gaps
- No published agent was found working at this exact combination of budget, noise and horizon. All "likely behaviour" entries are extrapolations.

## PPO or IMPALA with invalid action masking: are 500k-1M steps a day enough?

### Takeaway
No, not for learning from scratch. Typical benchmarks need 10M-200M steps on far less noisy, denser tasks, which is 2 weeks to 9 months of this budget, and roguelike evidence suggests even billions of steps may not reach a good rules player. Masking is necessary but does not address noise or horizon.

### Cited Findings
- CleanRL's PPO examples use 10M steps for Atari (multi-GPU example), 25M for Procgen easy, and 8M for DM Control — [CleanRL docs](https://docs.cleanrl.dev/rl-algorithms/ppo/).
- Procgen uses 200M steps on hard and 25M on easy; agents may need up to about 10,000 levels to close the generalization gap — [Cobbe et al.](https://ar5iv.labs.arxiv.org/html/1912.01588).
- Masking on small μRTS harvest tasks: 500k steps with a 200-step episode cap and +1 rewards for harvesting. Masking scales across maps from 4×4 to 24×24, while invalid-action penalties do not scale past 4×4 — [Huang and Ontañón](https://ar5iv.labs.arxiv.org/html/2006.14171).
- DouZero (DouDizhu, 48 cores, four GPUs, 30 days): beat heuristic rules in about half a day, passed its supervised agent in about two days at about 5×10⁸ timesteps, and passed DeltaDou at about 5×10⁹. It uses γ=1 Monte Carlo returns with action features; its authors report policy gradient cannot use action features to generalize to unseen actions, and their actor-critic variant failed — [Zha et al.](https://ar5iv.labs.arxiv.org/html/2106.06135).
- NetHack: Kakao Brain trained for 10B steps at about 100K frames/s; baselines 0.25B-0.5B. Stated reasons symbolic bots win include hard strategy discovery with large action spaces and sparse rewards, and unsolved long-term credit assignment — [Hambro et al.](https://ar5iv.labs.arxiv.org/html/2203.11889).
- Slay the Spire hobby projects (not peer reviewed): a roughly 15k-parameter maskable PPO trained for 1M steps on a combat-focused C++ recreation, with no final win rate in the summary — [mini-spire](https://rhp.bearblog.dev/mini-spire/). AscensionAI's live-game PPO plateaued at about 14.7 floors over about 21,700 games with 0 wins, and search-only combat raised average floor from 14.7 to 26.4 — [AscensionAI](https://justinochan.github.io/AscensionAI/). An earlier search snippet of the same page gave 4,136 rollout games, so its numbers change over time.
- Policy gradient quality: gradient estimates "poorly correlate" with the true gradient, and learned value estimators fail to fit the true value function — [Ilyas et al.](https://arxiv.org/abs/1811.02553).
- Delayed rewards make TD bias and Monte Carlo variance "even more severe" — [RUDDER](https://arxiv.org/abs/1806.07857).
- Uninformed ε-greedy can need about 2^H samples on combination-lock MDPs — [JSRL](https://ar5iv.labs.arxiv.org/html/2204.02372).
- IMPALA decouples acting from learning and scales to thousands of machines — [Espeholt et al.](https://arxiv.org/abs/1802.01561).

### Inferences
Days at 750k steps/day:

| Reference | Steps | Days |
|---|---|---|
| mini-spire PPO, combat only | 1M | 1.3 |
| CleanRL Atari example | 10M | 13 |
| Procgen easy | 25M | 33 |
| DouZero beats rules (my estimate from half of a 2-day, 5×10⁸ mark) | about 1.25×10⁸ | about 170 |
| Procgen hard | 200M | 267 |
| NetHack baseline | 250M | 333 |
| DouZero passes SL | 5×10⁸ | 667 |
| NetHack Kakao | 10¹⁰ | about 36 years |

- Noise per update: a 2,048-step batch is about 27 runs. With outcome SD 4, that batch's mean return has SE about 0.77, five times the +0.15 effect now in play. A good critic reduces this, but this project's critic attempts have already struggled.
- IMPALA's advantage is throughput at scale. Here the simulator, not the learner, is the bottleneck at about 10 steps/s, so it gives nothing. Prefer methods that reuse samples.
- Shop actions vary run to run, so a fixed-output policy head fits poorly. DouZero's lesson of scoring (state, action-features) is the relevant architecture.
- Unlike NetHack, this game has intermediate signals (surviving each encounter), so it is not purely sparse. This softens but does not remove the problem.
- Rating: from scratch Poor. A learned-from-scratch agent will most likely spend weeks climbing to below the rules player.

### Gaps
- IMPALA throughput figures were not in the abstract read; the 250k fps figure I recall is unverified.
- No peer-reviewed PPO benchmark on a shop-and-deck roguelike was found. Balatro-specific work was not searched.

## Policy improvement from a heuristic: how do you get monotonic improvement?

### Takeaway
The only clean guarantee comes from exact rollout, and it is too expensive to run on every decision here. The practical version is: truncate, pick only high-stakes decisions, use rollout results as training labels, default to the base policy, and accept changes only after full-run tests.

### Cited Findings
**Rollouts**
- Rollout policy cost improvement: the rollout policy is guaranteed no worse than the base policy — [Bertsekas lecture notes](https://web.mit.edu/dimitrib/www/RLTopics_2024_Lect5.pdf) (read as excerpts).
- Multi-agent rollout keeps cost improvement while reducing computation from exponential to linear in the number of agents, by optimising one component at a time — [Bertsekas 2020](https://www.mit.edu/~dimitrib/Multiagent_Sinica_2020.pdf).
- Tesauro and Galperin: base players from random to TD-Gammon; error reduction ratios 2.5-3.9 for full rollouts on single-layer players, and 3.5-6.6 for truncated rollouts with multilayer nets. Each full rollout needs about 10K+ trials per candidate, roughly a million base decisions per move decision; they targeted at least 100K base decisions per second. Truncated rollouts of 7-11 steps gave at least an order-of-magnitude speedup and kept much of the gain. Statistical pruning cut trials to several tens of thousands per move — [Tesauro and Galperin](https://arxiv.org/html/2501.05407v1).
- Bertsekas's notes describe TD-Gammon's 1996 truncated rollout as using a neural cost approximation, and as too slow for on-line play — [Bertsekas lecture notes](https://web.mit.edu/dimitrib/www/RLTopics_2024_Lect8.pdf) (excerpts).

**Classification-based API and CPI**
- CBMPI gave the best reported Tetris results on 10×10 and 10×20 boards, matching cross-entropy on the large board with far fewer samples, about 1×10⁷. The saving is stated as almost 1/10 in [the NeurIPS abstract](https://papers.neurips.cc/paper_files/paper/2013/hash/7504adad8bb96320eb3afdd4df6e1f60-Abstract.html) and almost 1/6 in [the HAL version](https://hal.archives-ouvertes.fr/hal-00921250); these conflict. The authors conjecture that good Tetris policies are easier to represent than their value functions. See also [the JMLR follow-up](https://jmlr.org/papers/v16/scherrer15a.html).
- CPI: uses a stochastic mixture of successive greedy policies, with a mixture rate chosen to guarantee improvement — [Kakade and Langford](https://hunch.net/~jl/projects/aoarl/Final.tex_back), [Vieillard et al.](https://web3.arxiv.org/pdf/1906.09784).
- CPI's cost: about 1/ε² iterations and memory proportional to iterations; the original "made very slow progress and took several millions of iterations" on a 100-state problem. A line-search variant, CPI+, converged in under 20 iterations — [Scherrer 2014](https://ar5iv.labs.arxiv.org/html/1405.2878).

**Imitation and residual methods**
- Plain imitation fails because future observations depend on past actions; DAgger's no-regret approach gives performance under the policy's own induced distribution — [Ross et al.](https://arxiv.org/abs/1011.0686).
- Cost-aware interactive imitation is framed as theoretical support for online approximate policy iteration — [Ross and Bagnell](https://arxiv.org/abs/1406.5979).
- THOR: an oracle's accuracy sets the needed planning horizon; a perfect oracle reduces it to one step, and a less accurate one needs a longer horizon — [Sun et al.](https://arxiv.org/abs/1805.11240).
- Residual Policy Learning consistently improves on initial controllers in six MuJoCo tasks, including long-horizon sparse tasks; the abstract gives no sample counts — [Silver et al.](https://arxiv.org/abs/1812.06298).
- Q-filter approach: an order-of-magnitude speedup over RL on simulated robotics, and it often beats the demonstrator — [Nair et al.](https://arxiv.org/abs/1709.10089).
- JSRL: initializing an actor from a pretrained policy with an untrained critic causes performance decay. JSRL instead rolls in with the guide for h steps and shrinks h over time; fine-tuning ran 1M steps on D4RL — [Uchendu et al.](https://ar5iv.labs.arxiv.org/html/2204.02372).
- BC at massive scale: 3.2B transitions from AutoAscend (median 4,918) gave a best BC median of 914 and best APPO+BC median of 972 — [Piterbarg et al.](https://ar5iv.labs.arxiv.org/html/2305.19240).

**Direct policy search**
- ES is "invariant to action frequency and delayed rewards" and "tolerant of extremely long horizons", needing no discounting or value function — [Salimans et al.](https://arxiv.org/abs/1703.03864).
- Factorial designs with ±1 coded factors yield uncorrelated estimates of main effects and interactions from the same runs, and fractional designs keep that orthogonality with fewer runs — [NIST handbook](https://www.itl.nist.gov/div898/handbook/pri/section3/pri3331.htm).

### Inferences
- Rollout cost here: Tesauro's one million base decisions per move decision would take 26 hours at 10.7 decisions/s, or 4.5 hours at 62/s. The system is about 10⁴ below his throughput target.
- Noise-based version: choosing between two moves separated by δ=0.5 at σ=4 needs about 1,000 playouts per move. At about 28 CPU-s (full) or 5 CPU-s (cheap) for a mid-run playout, that gives 12-69 decisions resolved per day; at δ=0.25, 3-17. This agrees with the project's experience that rollouts were slow. Pairing with common seeds helps only until the two lines diverge.
- Exact-rollout guarantees do not survive noisy estimates. With a small sample, argmax over noisy means picks noise, so the "never worse" property only holds with enough samples or a default-to-base rule.
- Practical design, closest to monotonic:
  1. Override the rules player only when the lower confidence bound of advantage exceeds zero.
  2. Treat the override threshold as CPI+'s line search: test 3-4 thresholds in full-run A/B on fresh seeds, keep the best, and keep the old policy if none clear it.
  3. Collect next round's data on the states the new policy reaches, and specifically on its overrides. This is the DAgger/AggreVaTe idea, and it uses samples where they change play.
- Best fresh idea for this project: factorial tuning. Parameterize the rules player with 20-200 multipliers (item-family values, sell thresholds, boss risk), randomize all per run, regress outcome on them. For ±1 factors, main-effect SE = 2σ/√N, so 20,000 runs (under two days) gives ±0.057 per factor at σ=4, for all factors at once. It tests whole-run effect, so it naturally includes downstream consequences that one-step labels miss. Caveats: effect is diluted when a parameter rarely affects decisions, and interactions need a follow-up round.
- Tetris precedent: direct search over a small policy beat value-based ADP for years, and CBMPI closed the gap with about 10⁷ samples. Those 10⁷ samples are about 13 days here, but Tetris is much less noisy per sample, so treat this as a lower bound.
- Residual RL's published wins are in continuous robotics where small corrections are natural. A discrete shop has no natural "small correction", so residual methods reduce to the override scheme above. Rating: Weak.
- Rating for BC then RL: Poor to weak. The rules player is already available without a net, so cloning it has value only as a warm start, and JSRL's decay result plus HiHack's gap warn that the net will be weaker than the source. If a net is used, keep JSRL-style rolling with the rules player so it only has to learn late-run decisions first.

### Gaps
- Bertsekas's book "Rollout, Policy Iteration and Distributed RL" was not read directly; findings come from his lecture notes and papers.
- CBMPI sample details (rollouts per state, iterations) were not extractable from the PDF.
- Safe policy improvement with baseline bootstrapping (SPIBB) and Thomas's high-confidence methods are relevant from my memory, but were not checked this session.

## Model-based search: what is usable when each simulated step is expensive?

### Takeaway
Full-tree search is not affordable. At 0.13-0.75 CPU-s per decision, even 16 simulations per decision cuts training data by 3-16×. An exact simulator already exists, so learned-dynamics methods add cost with no benefit. Short-horizon truncated search with a learned value on rare decisions is the usable part.

### Cited Findings
- Gumbel AlphaZero/MuZero: matches the state of the art on Go, chess and Atari and significantly improves performance with few simulations, using sampling without replacement and sequential halving, with a guarantee of policy improvement for correctly estimated action values — [Danihelka et al.](https://mlanthology.org/iclr/2022/danihelka2022iclr-policy), [ICLR page](https://iclr.cc/virtual/2022/poster/6418).
- Gumbel Zero is reported to work with as few as two simulations — [MiniZero paper](https://arxiv.org/pdf/2310.11305.pdf) (search excerpt only).
- Stochastic MuZero learns a stochastic model with afterstates and tree-searches over chance nodes; it matched or exceeded the state of the art in 2048 and backgammon — [Antonoglou et al.](https://mlanthology.org/iclr/2022/antonoglou2022iclr-planning). A leaderboard-style listing gave 2048 average scores of 500,000 for Stochastic MuZero, 500,000 for AlphaZero with a simulator and 300,000 for MuZero, not checked against the paper — [Papers with Code mirror](https://astro.paperswithcode.com/paper/planning-in-stochastic-environments-with-a).
- Chance nodes increase branching and so yield a shallower search — ["Causally Correct Partial Models", search excerpt only](https://arxiv.org/pdf/2002.02836).
- EfficientZero reaches strong Atari 100k performance with about two hours of game experience; these are visual benchmarks, and the abstract gives no compute — [Ye et al.](https://arxiv.org/abs/2111.00210).
- ISMCTS searches trees of information sets, and addresses determinization's "strategy fusion" error where different states in one information set are wrongly assumed to allow different decisions — [Cowling et al.](https://eprints.whiterose.ac.uk/id/eprint/75048/), [MCTS review](https://arxiv.org/pdf/2103.04931).
- Open-loop search and a Rolling Horizon Evolutionary Algorithm were applied to GVG-AI's real-time stochastic games, with RHEA the best evolutionary technique on the test set — [Perez Liebana et al.](https://repository.essex.ac.uk/14734/) (citation details partial).
- Nested Monte Carlo Search nests random playouts; applied to Morpion Solitaire, SameGame and 16×16 Sudoku — [Cazenave 2009](https://ijcai.org/Abstract/09/083). A level-1 search has complexity n×(n−1) — [author PDF](https://www.lamsade.dauphine.fr/%7Ecazenave/papers/nested.pdf).
- 2048 best known program at time of writing: a three-network, depth-5 expectimax over TD-learned values — [Jaśkowski](https://ar5iv.arxiv.org/html/1604.05085).
- `sts_lightspeed` has a tree search using known RNG state, and lists search without known RNG as planned — [sts_lightspeed](https://github.com/gamerpuppy/sts_lightspeed).
- Learned-value truncation: see Tesauro and Galperin above; 7-11 steps kept 3.5-6.6× error reductions with multilayer nets (10 and 80 hidden units) — [Tesauro and Galperin](https://arxiv.org/html/2501.05407v1).

### Inferences
- Per-decision search cost: 16 simulations × 75 decisions × (0.13 to 0.75 CPU-s per step) is 156-900 CPU-s per run, or 3-16× the current cost, leaving roughly 770-4,400 training runs a day. Also, Gumbel's guarantee depends on correct action values, which is exactly what's missing at this noise level.
- Search's real leverage is low branching and high stakes. Boss choice has few options and a large consequence, so it can afford sequential halving over truncated rollouts to the next boss, with a stage value at the leaf. Shop moves have larger branching and chance nodes (next shop stock) that eat the budget.
- The game's future randomness is simply unobserved dice, not an opponent's hidden hand, so ISMCTS's full machinery is less needed. Closed-loop chance nodes explode, so open-loop or sampled-seed search is the simplest workable form.
- Hindsight caution: any search with a fixed seed sees future shops. It will favour lines that exploit known stock, which is the strategy-fusion error. Nested Monte Carlo inherits this and also relies on replaying a best-found sequence, so it is only sound for deterministic puzzles.
- Rating: expectimax Weak (branching too large beyond 1-ply); Gumbel Weak now, possibly useful later; Stochastic and Sampled MuZero Poor; ISMCTS Weak; open-loop at the root with truncation Moderate on rare decisions.

### Gaps
- Stochastic MuZero training step counts and simulations per move were not found. Sampled MuZero was not researched in sources.
- Whether Gumbel root selection combines with chance-node search well: no direct evidence found.

## Offline RL and data reuse: why does offline ranking overstate play gain?

### Takeaway
Offline RL is designed for settings without a simulator, and near-rules-player data contains information only about one-step changes. Selection on noisy estimates mechanically inflates predicted gains. The fix is not a better offline algorithm. It is shrinkage, independent validation, and re-sampling on the deployed policy's choices.

### Cited Findings
- Standard off-policy methods fail on fixed batches due to extrapolation error — [Fujimoto et al.](https://arxiv.org/abs/1812.02900).
- CQL's rationale: overestimation from distribution shift between data and learned policy; its Q-function lower-bounds true value — [Kumar et al.](https://arxiv.org/abs/2006.04779).
- IQL "never needs to evaluate actions outside of the dataset", then uses advantage-weighted cloning — [Kostrikov et al.](https://arxiv.org/abs/2110.06169).
- One-step offline RL often beats iterative methods on D4RL; iterating causes "iterative error exploitation", and evaluating a different policy "reduces the effective sample size and increases the variance". When behaviour is fairly good but coverage is limited, one-step is preferable; iterative methods pay off with large datasets and good coverage — [Brandfonbrener et al.](https://ar5iv.labs.arxiv.org/html/2106.08909).
- Optimizer's curse named by Smith and Winkler (2006) — [Winkler publications](https://fds.duke.edu/db/aas/stat/faculty/bob.winkler/publications/278471), [Gelman's blog](https://statmodeling.stat.columbia.edu/2026/07/01/the-optimizers-curse/).
- In policy learning: the optimizer selects units with inflated scores, so plain DR overstates the deployed value, and the value of a fixed in-sample policy and of a learning procedure are different estimands — [2026 benchmark preprint](https://arxiv.org/pdf/2608.12489).
- Sample splitting may not fully remove the curse if counterfactual estimates are biased — [2026 preprint](https://arxiv.org/html/2602.08892).
- Bastani and Bastani optimize for the probability of beating the incumbent under later evaluation — [preprint](https://arxiv.org/pdf/2510.18161).
- DQN's overestimation grows with large action spaces — [DouZero](https://ar5iv.labs.arxiv.org/html/2106.06135).

### Inferences
- The existing advantage model is effectively one-step offline RL on randomized data. That is the right offline shape for this data per Brandfonbrener, so CQL or IQL would not extract more.
- Winner's curse size: picking the best of k candidates when all are truly equal and each estimate has SE s gives an apparent gain of about 1.16s (k=5), 1.54s (k=10), 1.87s (k=20). With s=0.2 and k=5 that is 0.23 per override. With 20 overrides per run, the apparent gain would be about 4.6, against a true effect of perhaps 0.15. These multipliers are standard normal order statistics.
- Other causes of optimistic offline results, all likely here:
  - Blunders inflate ranking: easy "bad move" discrimination gives correlation with no play value.
  - Distribution shift: after a few overrides, the run visits states never seen under rules-player play.
  - Baseline leakage: labels include the rules player continuing after the deviation. Gains that rely on future overrides are missing, and overrides that break the rules player's plans are unpenalized.
  - Interactions: two good one-step moves may spend the same money.
- Fixes in order: (1) report offline metrics only on override moves; (2) shrink estimates toward zero by empirical Bayes, the classic fix for the curse (from memory; I did not verify Smith and Winkler's exact prescription in this session); (3) split model-fit data from selection-evaluation data; (4) make the final decision on fresh-seed full-run A/B; (5) spend new data on the model's top overrides.
- Rating: CQL/IQL Weak, since the simulator makes data collection cheap relative to deep offline training's complexity and the noise is unaddressed.

### Gaps
- No numeric comparison of OPE-predicted and realized gains in games was found.
- Levine et al.'s tutorial was read only as an abstract, which does not discuss distribution shift, so it is not cited for this.

## Contextual bandits and causal uplift: how do one-step gains compose?

### Takeaway
The randomization already removes confounding, so DML's main value here is variance reduction and honest intervals, not debiasing. These tools rank one-step deviations well, but one-step gains do not add up. Composition has to be validated through whole-run tests.

### Cited Findings
- DML: plugging ML into causal estimating equations suffers regularization bias; orthogonal scores and K-fold cross-fitting remove it, giving 1/√n inference — [Chernozhukov et al.](https://arxiv.org/abs/1608.00060).
- R-learner: fits marginal effects and propensities first, then optimizes an objective that isolates the causal signal, using any learner. It achieves quasi-oracle error bounds for penalized kernel regression even with inaccurate nuisances — [Nie and Wager](https://arxiv.org/abs/1712.04912).
- Causal forests: pointwise consistent, asymptotically Gaussian effect estimates with practical confidence intervals; better than nearest-neighbour matching, especially with irrelevant covariates — [Wager and Athey](https://arxiv.org/abs/1510.04342).
- Policy learning from a doubly robust score, with constrained policy classes such as simple decision trees — [Athey and Wager](https://arxiv.org/abs/1702.02896).
- Thompson sampling with approximate Bayesian nets: methods good at supervised learning often do worse when decisions are sequential; slowly converging uncertainty estimates are the main difficulty — [Riquelme et al.](https://arxiv.org/abs/1802.09127).
- AIVAT: unbiased, uses an arbitrary heuristic value estimate plus known strategies; reduces poker hands needed by more than 10× — [Burch et al.](https://arxiv.org/abs/1612.06915).
- Composition theory: CPI's analysis is the origin of the mixture-step guarantee — [Kakade and Langford](https://hunch.net/~jl/projects/aoarl/Final.tex_back). One-at-a-time optimisation with others held to the known policy preserves cost improvement in multi-agent rollout — [Bertsekas](https://www.mit.edu/~dimitrib/Multiagent_Sinica_2020.pdf).

### Inferences
- With known randomization probabilities the propensity term is exact, so residualizing (R-learner style with cross-fit baseline) is valid and cheap. The project's outcome-minus-baseline label is close to this; check the baseline is cross-fitted, otherwise it absorbs signal.
- Biggest available lever, unproven here: AIVAT-style chance correction. A state-value baseline at the decision only removes what is known at that point. AIVAT also subtracts, at each later chance event (shop stock, letter draws), the value model's "luck" term, V(after) minus E[V over outcomes]. Poor models stay unbiased. If this reached poker's 10×, σ would fall by about 3.2, and all sample counts in this file would fall 10×. Requires being able to enumerate or sample chance outcomes at those events, plus value evaluation there; even a coarse value could be tested on existing logs if chance details were logged.
- Causal forest intervals suit the "lower bound > 0" override rule. A linear R-learner over item-family × stage features may match LightGBM here, given the data capacity above; the project's ridge and LightGBM results hint at this.
- Bandits fit one thing well: allocating the next 100k deviations. Use top-two Thompson sampling or successive elimination over clusters of override types, so samples go to overrides the model would actually use. Per-state bandits are not viable, as states do not repeat.
- Why one-step gains don't add (my reading of performance-difference reasoning): real gain is the sum over the new policy's visited states of advantage against the old policy. Measured labels are on the old policy's states with the old policy continuing. So the sum is right only for few, non-interacting overrides. Practical rules:
  - Group by resource conflict: money spent on one good override removes the next one.
  - Test k=1, 3, 10 overrides per run as a dose-response A/B; a flat or falling curve reveals interactions directly.
  - Refit after each deployment, on data under the deployed policy.
- Rating: DML/R-learner Good (cheap, but small effect beyond what exists), causal forests Moderate, per-state Thompson Poor, cluster-level Thompson Moderate.

### Gaps
- The performance difference lemma itself was not read verbatim in a source this session; the statement above is from my knowledge of Kakade and Langford's result.
- No published test of AIVAT-style correction outside poker-like games was found.
- No study of composing many randomized one-step gains in games was found.

## Model class: GBDT, neural nets, set encoders and item embeddings

### Takeaway
At 76k noisy labels, GBDT or regularized linear models with good features remain the safe default. Tabular benchmarks favour trees at about 10k samples, with the gap narrowing above that, but none cover this low signal-to-noise. A tiny CPU net with shared item embeddings is viable to run. Its data needs are the unknown, so it should only replace GBDT if it wins on override-only validation.

### Cited Findings
- Trees remain state of the art at about 10K samples on 45 datasets, with about 400 random-search iterations per dataset and 20,000 compute hours. Neural nets struggle with uninformative features and irregular functions — [Grinsztajn et al.](https://ar5iv.labs.arxiv.org/html/2207.08815).
- Train set truncated to 50K gives a narrower gap "in most cases", not rigorously established and on few tasks — [Grinsztajn et al.](https://ar5iv.labs.arxiv.org/html/2207.08815).
- Across 19 algorithms and 176 datasets, the NN vs GBDT gap is often negligible, and light GBDT tuning can matter more than family choice; GBDTs handle skewed features and dataset irregularities better; TabPFN wins on average but is limited to about 3,000 training points — [McElfresh et al.](https://arxiv.org/abs/2305.02997).
- XGBoost beat deep tabular models and needed much less tuning; an ensemble with deep models did better than XGBoost alone — [Shwartz-Ziv and Armon](https://arxiv.org/abs/2106.03253).
- Deep Sets characterises permutation-invariant functions and builds a net for them — [Zaheer et al.](https://arxiv.org/abs/1703.06114).
- Set Transformer models interactions among elements, using inducing points to reduce self-attention cost from quadratic to linear in set size — [Lee et al.](https://arxiv.org/abs/1810.00825).
- Item2Vec learns item embeddings from co-occurrence, without user information, and is competitive with SVD — [Barkan and Koenigstein](https://arxiv.org/abs/1603.04259).
- Action features let knowledge about one action transfer to similar ones — [DouZero](https://ar5iv.labs.arxiv.org/html/2106.06135).
- Small nets exist in this domain: about 15k parameters for mini-spire ([Pitkin](https://rhp.bearblog.dev/mini-spire/)) and about 234k for a Slay the Spire 2 policy-value net ([showcase](https://cmcour.github.io/sts2Showcase/deep-dive/neural-network/)).

### Inferences
- Benchmarks are mostly moderate-to-high signal tasks; here R² on labels is likely under 0.05. In low SNR, model capacity matters less than regularization, and feature design matters more than family. I would expect ridge, GBDT and a small MLP to be close, and the gain from swapping the model to be less than from variance reduction.
- Practical GBDT settings for the data capacity above: learning rate ≤0.02, about 8-16 leaves, min data per leaf ≥500-2,000, early stop by decision-grouped CV (group by run, not by row), monotone constraints where game logic justifies them.
- CPU viability: A 10k-100k parameter MLP or Deep Sets forward pass is trivial compared with about 0.5 CPU-s per decision. Training on 76k rows takes minutes. Compute is not the constraint; statistical power is.
- Sample guess for set encoders: With about 100s of items and 8-dimension embeddings the parameter count is about a few thousand, near the data capacity of about 50-190 "clean" effects only with sharing and strong weight decay. I would not expect Set Transformer's interaction modelling to be identifiable at 76k labels; plain sum pooling or hand-made synergy counts are safer. Revisit at about 1M labels.
- Item embeddings: Item2Vec-style training on run logs uses all runs' item sets with no outcome noise, which is the attraction. The catch is that co-occurrence reflects the rules player's purchases and shop availability, not value. Use as input features or as a prior on item similarity, not as evidence of strength. Hand-written item effect features are a strong competitor at this scale.
- Rating: GBDT/ridge Good; small MLP with action features Moderate; Deep Sets Moderate; Set Transformer Weak at this data; TabPFN not applicable beyond about 3k points.

### Gaps
- None of these sources test tabular models under very low signal-to-noise, and I found no published sample requirements for Deep Sets or Set Transformer on game state.
- Whether the shared-embedding net beats GBDT at 76k labels can only be answered by a project test.

## Value function learning: why do state values pick already-good states, and how is that corrected?

### Takeaway
TD with hand features works well at about 10⁵-10⁶ episodes, which is about 8-83 days here. State values choose states that are already strong because most of their variance is between states, while decisions depend on small differences within a state. The correction is to train and evaluate on within-decision differences, use randomized data and shorten the target horizon.

### Cited Findings
- TD-Gammon: a raw-encoding net with 40 hidden units trained for 200,000 games reached about Neurogammon's level. Absolute errors are often "a tenth of a point or more" but "highly correlated" across candidates, so they "effectively cancel when comparing two candidate plays". Stochastic games have smooth targets, and dice give natural exploration — [Tesauro 1995](https://bkgm.com/articles/tesauro/tdl.html).
- TD-Gammon 2.1 reportedly trained for 1.5M self-play games — [secondary source](https://Www.wikipedia.org/wiki/TD-Gammon), not verified in Tesauro's own text. Backgammon games last 50-60 time steps — [Tesauro and Galperin](https://arxiv.org/html/2501.05407v1).
- 2048: TD(0) over about 1M episodes learned an afterstate n-tuple value (about 23M parameters, 100,178 average at 1-ply); Wu et al. used 5M games and 67M parameters for 142,727. Temporal coherence, multi-stage weights and expectimax produced the then-best player — [Jaśkowski](https://ar5iv.arxiv.org/html/1604.05085), citing [Szubert and Jaśkowski](https://mszubert.github.io/papers/Szubert_2014_CIG.pdf).
- Action gap: value difference between best and second best. A larger gap helps under approximation or estimation error — [Bellemare et al. 2016](https://ar5iv.labs.arxiv.org/html/1512.04860).
- Dueling separates state value and advantage, improving policy evaluation when many actions have similar values — [Wang et al.](https://arxiv.org/abs/1511.06581).
- Distributional RL: modelling the return's distribution matters for approximate RL — [Bellemare et al. 2017](https://arxiv.org/abs/1707.06887).
- Value-based ADP performed poorly on Tetris while policy-space search did well, as noted above — [Gabillon et al.](https://papers.neurips.cc/paper_files/paper/2013/hash/7504adad8bb96320eb3afdd4df6e1f60-Abstract.html).
- In DouDizhu, TD showed no clear benefit over Monte Carlo in a sparse-reward setting, and DMC was slightly faster — [DouZero](https://ar5iv.labs.arxiv.org/html/2106.06135).
- With a limited-data model, a shorter planning horizon can beat the true horizon: horizon acts as complexity control, and the best horizon depends on data size — [Jiang et al.](https://www.ijcai.org/Abstract/16/626), [AAMAS draft](https://web.eecs.umich.edu/~baveja/Papers/gamma-AAMAS-final.pdf).

### Inferences
Why V picks already-strong states, in order of importance here:
1. **Variance structure:** most outcome variance is between states (crown, stage, luck). A high-R² V can be near-useless at ranking within a decision. Action gap reasoning: the signal is 0.1-0.5, while V's range and error are larger.
2. **Confounding in logged data:** "owning item X" is correlated with earlier success. So V credits the purchase for the strength that allowed it. Tesauro's cancellation relies on candidates being similar under a smooth net trained on relevant variation. Comparing "buy" and "skip" changes features whose learned weights are confounded, so errors do not cancel.
3. **Maximization bias:** argmax over afterstates selects V's positive errors, and more candidates mean more selection.
4. **Behaviour-policy dependence:** V is the value under the behaviour policy, not under the new policy that would follow.

Corrections, in rough priority:
- Evaluate on within-decision pair correlation and override-only tests, never on overall R². The project already tracks this column.
- Train on within-decision differences or an advantage head (dueling structure), and use randomized moves as labels. The existing randomized dataset is exactly right for this.
- Use stage-wise win/survival targets. Rather than end-of-run outcome, predict P(survive next boss) and expected stage. This has much lower noise per label, up to about 16 binary events per run against one rare win, and matches Jiang's horizon point. It accepts bias from short-sightedness; chain conditional stage models to reduce it. Multi-stage weights have strong precedent in 2048.
- Distributional output: the outcome is multi-modal (Michael bonus of +8), so an expected-value head may hide useful risk information. Predicting tail probability P(reach Michael) is more useful than C51 proper. I would expect modest gains.
- Monte Carlo over bootstrapping at first (DouZero's experience, and no need to trust a weak V), moving to short n-step or λ small once a stage model exists.
- Rating: TD(λ) with hand features Moderate. 200k-1M runs is 17-83 days at 12k/day. The 9.7 s policy reaches 71k runs a day, making 200k runs about 3 days, but its V reflects the weaker cheap policy. TD-Gammon's game length is similar to this game's, which is encouraging, but backgammon has lower noise relative to decision gaps than I'd expect here, and no strong rules player to beat. N-tuple-style models do not transfer directly since 2048 states have a fixed grid; item-pair tables would be the analogue, and those are limited by data.

### Gaps
- No source directly documents the "picks already-good states" failure as a named phenomenon in games; the ordered list above is my diagnosis, supported by action-gap and confounding arguments.
- Tesauro's game counts for versions 1.0 to 2.1 were not in the fetched article.

## Fast surrogate game: when does a simplified or faster simulator help?

### Takeaway
Profile first: game logic is about 3% of runtime in the only profile available, so porting it alone gives almost nothing. Compiling or caching word search is the real speedup. A low-fidelity scorer is good for screening candidates, and every result must be confirmed on the faithful simulator. JAX is a poor fit here.

### Cited Findings
- Project profile: 97% word search, 92% of that shop probes; of 471 enumerations in 60 actions only 144 were distinct — [docs/game-research/sim-game.md, lines 494-497](docs/game-research/sim-game.md).
- C++ Slay the Spire simulator: "1M random playouts in 5s with 16 threads" — [sts_lightspeed](https://github.com/gamerpuppy/sts_lightspeed). Random playouts with no AI search cost.
- A hobby headless simulator runs about 17k games/hr and enabled a move from a stalled live-game PPO to better results — [AscensionAI](https://justinochan.github.io/AscensionAI/) (not peer reviewed).
- Python's measured execution time is about 71.9× C in the Energy Languages benchmarks, reported in a follow-up that disputes the energy interpretation, not the timing — ["It's Not Easy Being Green"](https://arxiv.org/html/2410.05460v4). These are compute-heavy benchmark programs.
- Pgx: JAX board game simulators are 10x faster on an A100 GPU than existing libraries ([v1 abstract](https://arxiv.org/abs/2303.17503v1)), or 10-100x in a later version ([v4 review page](https://arxiv.deeppaper.ai/papers/2303.17503v4)).
- Multi-fidelity RL: a chain of simulators with decreasing fidelity finds near-optimal real-world policies with fewer expensive samples than transfer or no simulator — [Cutler et al.](https://dspace.mit.edu/entities/publication/459b2f64-1c1f-4064-810b-247356a5a5df).
- PEGASUS: fixed randomness turns policy search into a deterministic problem with bounds polynomial in horizon rather than exponential. The abstract states the deterministic transformation but not the mechanism — [Ng and Jordan](https://arxiv.org/abs/1301.3878).
- Fixed training sets overfit: Procgen needs up to about 10,000 levels to close the gap — [Cobbe et al.](https://ar5iv.labs.arxiv.org/html/1912.01588).

### Inferences
- Amdahl: rewriting only the shop and game logic has a cap of about 3% on that profile. Caveat: this profile is of `power` under a profiler on one run, and Advice-based policies have a different mix (3-50 s per run per [line 125 of sim-game.md](docs/game-research/sim-game.md)). Re-profile the training policy before deciding anything.
- Order of work:
  1. Cache probes across loadouts. The 144/471 distinct ratio suggests up to about 3× on enumeration.
  2. Keep the cheap policy for play-outs where its bias is acceptable, already about 3.6×.
  3. Move word enumeration and scoring to Rust or C++ behind the same API. If that code is plain Python, 10-70× on that hot path is plausible; if it is already NumPy- or compiled-backed, expect far less. The 71.9× figure is an upper-ish reference from benchmark programs, not a promise.
  4. Only then port game logic.
- Overall, I'd guess 3-10× from caching and a hot-path port within weeks, and 30×+ only with a full port. That would be the difference between "TD and rollouts are infeasible" and "TD is feasible".
- A full port also takes on a re-validation cost, since this simulator's value is fidelity. Keep differential tests against the Python version on seeded runs.
- Surrogate scorer: replace word search during shop evaluation with a table or model giving score distribution per build. This is the best low-fidelity option, because word-search cost dominates. Sim-to-real risk is concentrated in the very quantity decisions depend on: how a build scores. Expect surrogate training to overvalue builds the surrogate mispredicts. Use it only to screen: successive halving with low-fidelity first and faithful final tests, never as evidence of gain.
- Learned dynamics (MuZero style) would be slower and worse than a table for this use. Rating Poor.
- JAX: Rating Poor. Needs fixed-shape arrays and pure functions; word search with tries and a large item rule set maps badly, and the 10-100× is GPU-based; none is assumed here.
- Seeds: fixed seed sets with paired tests reduce evaluation noise, but do not train on only a small seed set. Use fresh seeds for acceptance tests.

### Gaps
- No clean published data on speedups from porting a real Python game simulator to Rust was found; the 71.9× is benchmark-based and EnvPool or Rust-specific numbers did not turn up.
- Word search's current implementation language and share under the training policy were not checked in full; the profile cited is one run from 2026-10-30.
