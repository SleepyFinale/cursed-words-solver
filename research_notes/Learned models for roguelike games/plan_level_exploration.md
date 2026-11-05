# Plan-level exploration, build archetypes and curricula for Cursed Words

Notation used below: "outcome" is the project's run score. A cell is one character × crown (11 × 8 = 88 cells). A band is one of the three crown groups in `plantest.py` (0–2, 3–5, 6–7), so character × band = 33 units. "Runs/day" uses the project's estimate of 2,464 runs in about 8 h, roughly 7.4k/day, inside the stated 5–20k range. All Monte Carlo figures are my own, labelled as inference, and depend on stated assumptions.

Project measurements come from a live snapshot of `~/.cursed_words_solver/sim_models/plans/runs.jsonl` taken on 2026-11-05 at 368 of 2,464 runs (about 15% complete, not yet balanced by crown or character). Treat them as early signals.

## Hierarchical RL and options: what works in practice, including run-level goals (z, UVFA, build-order conditioning)

### Takeaway
The approaches with real strategy-game results use hand-chosen, domain-specific strategy variables (build-order statistics, macro-actions, symbolic sub-goals). Learned options are not what produced those results. A run-level plan variable that conditions every shop choice is well supported, while option-critic, feudal and unsupervised skill discovery are poor bets at 5–20k runs/day.

### Cited Findings
- AlphaStar's z encodes the first 20 buildings and units built plus cumulative statistics of units, buildings, effects and upgrades. The policy is conditioned on z in both supervised and RL phases, and z is zeroed 10% of the time in supervised training — [Vinyals et al., AlphaStar](https://storage.googleapis.com/deepmind-media/research/alphastar/AlphaStar_unformatted.pdf)
- AlphaStar's motivation matches this project's problem: a policy good at ground units gets worse under any naive deviation toward air units, so random exploration almost never finds the alternative strategy — [AlphaStar](https://storage.googleapis.com/deepmind-media/research/alphastar/AlphaStar_unformatted.pdf)
- During RL, main agents get pseudo-rewards for following a sampled z (edit distance on build orders, Hamming distance on cumulative statistics). Each pseudo-reward is active with probability 25% and has its own value function and loss, and agents are also penalised for diverging from the supervised policy. The authors call human data critical to performance — [AlphaStar](https://storage.googleapis.com/deepmind-media/research/alphastar/AlphaStar_unformatted.pdf)
- The authors say using a latent z to induce exploration is not specific to StarCraft, but choosing the statistics required domain knowledge. They also fixed z to 17 hand-curated strategies to build validation agents. Scale was 12 agents × 32 TPUs × 44 days, with almost 900 players created, and the Battle.net evaluation used the unconditional policy — [AlphaStar](https://storage.googleapis.com/deepmind-media/research/alphastar/AlphaStar_unformatted.pdf)
- UVFA: a single model V(s, g; θ) generalises over states and goals, learned through separate state and goal embeddings — [Schaul et al.](https://proceedings.mlr.press/v37/schaul15.html). A later paper says UVFAs can be trained with TD on random goals but work best with dense reward — [Universal Value Density Estimation](https://arxiv.org/pdf/2002.06473)
- Nachum et al. attribute most of the observed benefit of hierarchy to better exploration, not to hierarchical structure or easier learning. Their simple temporally extended exploration methods were competitive with HRL, on locomotion, navigation and manipulation tasks — [Why Does Hierarchy (Sometimes) Work So Well](https://arxiv.org/abs/1909.10618)
- Option-critic updates can produce degenerate solutions. Feudal methods depend on informative environment reward, because a poorly trained high level emits goals that don't drive the low level — [HRL overview, 2025](https://arxiv.org/pdf/2506.14045). Feudal policies can also be suboptimal compared with flat ones — [Murphy, RL overview](https://arxiv.org/pdf/2412.05265)
- FeUdal Networks scored significantly better than Option-Critic on Atari — [FuN](https://typeset.io/pdf/feudal-networks-for-hierarchical-reinforcement-learning-er4xki7z2s.pdf). This is Atari and DeepMind Lab evidence, not strategy-game evidence.
- Two-level HRL in StarCraft II, with macro-actions extracted from expert trajectories (about an order of magnitude smaller action space), won over 93% against the level-7 built-in AI using curriculum transfer. Training took under 2 days on 48 CPU cores and 8 GPUs — [Pang et al.](https://arxiv.org/abs/1809.09095)
- NetHack Challenge 2021: the best symbolic bot's median score was about 3× the best neural agent's, the top three overall were symbolic, and the winning neural entry was a hybrid. The organisers call HRL an open problem and say neural agents struggled to discover strategy-type behaviour with sparse reward — [NetHack Challenge report](https://nethackchallenge.com/report.html), [Hambro et al.](https://arxiv.org/pdf/2203.11889)
- DIAYN learns diverse skills with no reward function, and those skills can be composed hierarchically; its evidence is simulated robotics and RL benchmarks — [Eysenbach et al.](https://arxiv.org/abs/1802.06070). In NetHack, LLM-annotated skill rewards reached a 46% Gnomish Mines success rate against 9% for the Motif baseline, which shows hand-specified skill semantics doing the work — [MaestroMotif summary](https://alphaxiv.org/overview/2412.08542v1)
- Closest game analogue: a small MLP (hidden [128,128], about 100k parameters) scoring candidates for all non-combat Slay the Spire decisions, trained with REINFORCE over 15,000 games, gave 14% wins against 6% for stock heuristics, with combat handled by MCTS. Evaluation was 50 seeds with no confidence intervals, A0 Ironclad only, and it is unreviewed — [sts-rl-agent](https://huggingface.co/Jialeiv/sts-rl-agent)

### Inferences
- **Inference:** `build_plan` is already this project's z, hand-specified as tags. The AlphaStar pattern maps cleanly: condition on z, add a pseudo-reward (or plan-match bonus) that is switched on only some of the time, and also train a z-free policy that picks its own direction.
- **Inference:** the cheapest experiment is to randomise the plan per run and pass the plan ID as a feature to the existing RCT learner. This is a linear or tree UVFA. It costs no extra runs and addresses the logged weakness that models have never seen a run with a different plan ([sim-game.md](../../docs/game-research/sim-game.md)).
- **Inference:** Nachum's result suggests whole-run plan randomisation may deliver most of what options would offer here, because the gain is temporally coherent exploration.
- **Inference:** I would not spend budget on option-critic, FuN or DIAYN. All the cited successes use far more experience or domain structure than 5–20k runs/day provides. The sts-rl-agent result is the one exception worth a pilot (15–30k runs), and its baseline heuristics may be much weaker than this project's rules player.

### Gaps
- I found no published deckbuilder or roguelike with a controlled comparison of plan-conditioned against unconditioned policies.
- I found no reported AlphaStar ablation figure for z alone that I could read as a number; the paper's Fig. 3E was not legible in the extracted text.
- I searched for no League of Legends item-build work or Legends of Code and Magic results (the search returned nothing relevant).

## Bandits over plans: arms per character and difficulty, and how many runs at outcome SD about 5

### Takeaway
Screening 13 plans per character takes about 6–12k runs (1–2 days) with adaptive elimination, and per-band takes about 17–34k. Per-cell (88) conclusions are not worth buying directly and should come from a shrinkage model. Pairing helps less for whole-run plans than for small knobs (measured paired SD about 4.25 versus 3.3).

### Cited Findings
- Top-two sampling rules (probability, value and a modified Thompson sampling) drive the posterior probability of a wrong best arm to zero at an exponentially fast rate, with the best possible exponent among allocation rules — [Russo](https://arxiv.org/abs/1602.08448)
- Vanilla Thompson sampling under-samples suboptimal arms for this purpose. TTTS and T3C have fixed-confidence guarantees for Gaussian bandits with a Bayesian stopping rule, and T3C removes TTTS's computational burden — [Shang et al.](https://arxiv.org/abs/1910.10945)
- Karnin et al. give parameter-free best-arm algorithms for fixed-confidence and fixed-budget settings, with a gap from the lower bound that is only doubly logarithmic — [Karnin, Koren, Somekh](https://proceedings.mlr.press/v28/karnin13.html). Sequential Halving is described as near-optimal for fixed budget under homogeneous variances, and variance-adaptive variants were built because that assumption can fail — [SHVar](https://arxiv.org/pdf/2306.07549)
- Hierarchical Thompson sampling (HierTS) shares knowledge across related bandit tasks, with regret falling as the prior gets more informative — [Hong et al.](https://arxiv.org/pdf/2111.06929). AdaTS learns the task prior over time — [Basu et al.](https://arxiv.org/pdf/2107.06196)
- Project: `chartune.py` already runs successive halving on paired seeds (13 arms × 16, best 5 × 32, best 2 × 48), with paired SD about 3.3 and about 560 runs per character — [sim-game.md](../../docs/game-research/sim-game.md)
- Project, snapshot of 368 runs: overall outcome SD 3.81; residual SD within character × crown 2.88; paired plan-minus-rules SD 4.25 with correlation 0.24 (44 pairs). Within-plan SD runs from 2.0 (Cash) to 6.48 (Curse) — [runs.jsonl, computed by me](../../cursed_words_solver/sim/game/plantest.py)

### Inferences
- **Inference:** SD about 5 is a safe planning number. Early data is lower on average, but Curse is at 6.5, so variance differs about 10× between arms (6.48² / 2.0²). This favours variance-aware allocation: an arm with Curse's SD needs about 10× Cash's runs for the same precision.
- **Inference:** pairing buys only about 23% fewer runs for plans (paired variance 18.1 against 23.5 unpaired, from those 44 pairs), since seeds stop being shared once the runs' actions diverge. Keep pairing, but do not rely on it as strongly as for small knobs.

**Runs per arm for a fixed comparison (my arithmetic: two-sided α = 0.05, 80% power).**

| Assumption | Δ = 2 | Δ = 1 | Δ = 0.5 | Δ = 0.3 |
|---|---|---|---|---|
| Unpaired, SD 5, single comparison | 98 | 392 | 1,568 | 4,356 |
| Unpaired, SD 5, Bonferroni over 13 plans | 174 | 695 | 2,780 | 7,722 |
| Paired, SD 4.25, Bonferroni over 13 | 63 | 251 | 1,005 | 2,789 |

Win-rate contrasts near p = 0.3, single comparison: about 329 per arm for 10 points, about 1,317 for 5 points. At the highest crowns, where the win rate is about 1–2%, resolving 1% against 3% takes about 770 per arm, so use outcome or stage reached as the signal there.

**Uniform full design (14 arms including rules, paired, Bonferroni; my arithmetic, days at 7.4k/day).**

| Unit | Units | Δ = 1 | Δ = 0.5 |
|---|---|---|---|
| Global | 1 | 3.5k (0.5 d) | 14k (2 d) |
| Character | 11 | 39k (5 d) | 155k (21 d) |
| Character × band | 33 | 116k (16 d) | 464k (63 d) |
| Character × crown | 88 | 309k (42 d) | 1.24M (167 d) |

**Monte Carlo, best of K = 13 with SD 5, unpaired (my simulation; 300 worlds for uniform and halving, 100 for TTTS; arm means drawn from N(0, τ²)).** Each entry is regret in outcome points / probability the true best was chosen.

| Budget per unit | τ = 0.5: Uniform | SH | TTTS | τ = 1.0: Uniform | SH | TTTS |
|---|---|---|---|---|---|---|
| 130 | .63 / .15 | .47 / .20 | .52 / .21 | .72 / .31 | .64 / .31 | .63 / .34 |
| 520 | .41 / .25 | .29 / .30 | .31 / .37 | .38 / .45 | .22 / .61 | .09 / .73 |
| 1,040 | .26 / .36 | .19 / .45 | .19 / .44 | .20 / .58 | .12 / .68 | .07 / .76 |
| 2,080 | .18 / .45 | .11 / .56 | .08 / .62 | .14 / .61 | .07 / .74 | .05 / .85 |

- **Inference:** Sequential Halving cuts regret by roughly 25–50% compared with uniform at the same budget from 260 runs up (only 11–25% at 130). TTTS and SH are close, within Monte Carlo noise at many budgets, and my TTTS was fully sequential, which flatters it compared with batched workers. SH is the simpler choice and already exists in `chartune.py`.
- **Inference:** the per-unit budget of about 520–1,040 gives these totals: character 5.7–11.4k (about 1–2 d); character × band 17–34k (2–5 d); character × crown 46–92k (6–12 d). Reaching P(best) above 0.8 needs about 2,000+ per unit and is rarely worth it, since regret is already below 0.1.
- **Inference:** add a confirmation on fresh seeds for each promoted unit: to confirm Δ = 0.7 paired, about 289 seeds × 2 arms = 578 runs per unit, or about 6.4k for 11 characters.

**How finely to split (my simulation, 200 worlds).** Assumed effect SDs: plan 1.2, plan × character 0.7, plan × band 0.4, residual 0.3. These are guesses to be replaced after the screen. Values are mean outcome gain over the average plan, with SE of roughly 0.05 (estimated, not computed).

| Total runs | One global plan | Per character (SH) | Per char × band (SH) | Shrinkage, uniform | Oracle |
|---|---|---|---|---|---|
| 10k | 2.05 | 2.25 | 2.15 | 2.25 | 2.43 |
| 30k | 1.99 | 2.29 | 2.33 | 2.32 | 2.42 |
| 70k | 2.07 | 2.35 | 2.42 | 2.39 | 2.45 |

- **Inference:** under these assumptions, one global plan is found very quickly and most of the gain comes from it. Per-character choice adds about 0.2–0.3, and band adds under 0.1, only past 30k runs. A shrinkage model matches SH at low budgets and also gives an estimate for every cell. Fit it on the 2,464-run screen to replace the guessed variances.
- **Inference:** the current screen (16 seeds per character per plan) has SE of about 0.38 per plan globally and about 1.25 per character × plan, which is enough only to rank plans globally. The sensible next step is SH within characters, seeded by the shrunk screen.
- **Inference (contextual):** once plans are randomised, a ridge or logistic model on plan × (character, band, first-shop offers) can be fitted off-policy from the same logs. That has about 200–400 coefficients and I would expect it to need 30–60k runs, a rough guess that I have not simulated.

### Gaps
- I did not find an empirical head-to-head of TTTS and Sequential Halving at these noise levels; the table above is my own.
- The β = 1/2 "within a factor 2 of optimal" result for top-two sampling is something I recall but could not verify in the abstract I fetched.
- I did not fetch combinatorial-bandit work (plans as tag subsets). Plans here are single tags, so it matters only if pairs like Curse + Cards are added.

## Parameter search over a rules player: CMA-ES, BO, SPSA, TPE, paired seeds, Texel, CLOP, Stockfish, direct policy search versus value learning

### Takeaway
There is strong evidence that direct policy search over a small, well-featured linear scorer can beat value-based learning when returns are noisy and delayed. Good features and low dimension matter more than the optimiser. At this budget, expect search to work for about 10–30 parameters with about 20–80k runs and a gain only if headroom is at least about 1 outcome point.

### Cited Findings
- Tetris, lines cleared: value-based and policy-gradient methods reached 2,800 (Bertsekas & Tsitsiklis), 1,000–3,000 (Lagoudakis et al.), 6,800 (Kakade) and about 4,500 (Farias & Van Roy). Noisy cross-entropy reached 350,000, and with added features 35,000,000 (Thiery & Scherrer). CMA-ES also reached 35,000,000 — [Algorta & Şimşek review](https://arxiv.org/pdf/1905.01652)
- Szita and Lőrincz's abstract reports beating earlier RL methods by almost two orders of magnitude — [abstract listing](https://data.zhenzhi.com/details/1/896104129)
- Crucial caveat: Dellacherie's hand-written linear rule cleared 660,000 lines, more than Szita and Lőrincz's 350,000, and the review says that figure understates it because its game rules ended games sooner. The jump to 35M came with better features — [Algorta & Şimşek review](https://arxiv.org/pdf/1905.01652)
- Counter-evidence: CBMPI, an approximate DP method searching in policy space, matched CE on the large board with far fewer samples. The authors conjecture that good policies are easier to represent than good value functions — [Adobe listing, about 1/6 of the samples](https://research.adobe.com/publication/approximate-dynamic-programming-finally-performs-well-in-the-game-of-tetris); the [NeurIPS abstract](https://papers.neurips.cc/paper_files/paper/2013/hash/7504adad8bb96320eb3afdd4df6e1f60-Abstract.html) gives almost 1/10, so the two disagree. One reviewer said it did not equal CE's final performance — [NeurIPS reviews](https://papers.nips.cc/paper_files/paper/2013/file/7504adad8bb96320eb3afdd4df6e1f60-Reviews.html)
- The review warns that the best Tetris learners still need hundreds of thousands of samples and have a noisy learning process — [Algorta & Şimşek review](https://arxiv.org/pdf/1905.01652)
- Salimans ES: 3–10× the data of A3C to match final Atari performance, better on 23 of 51 games and worse on 28 (1 billion frames against 320 million, about 1 hour on 720 CPUs). It needed no more than 10× TRPO's data on MuJoCo. Variance of the ES gradient does not grow with episode length, unlike policy gradients, so ES has an advantage when the return correlates weakly with individual actions — [Salimans et al.](https://arxiv.org/pdf/1703.03864)
- Random search over static linear policies matched state-of-the-art sample efficiency on MuJoCo and was at least 15× more compute-efficient, while evaluation over hundreds of seeds showed high performance variability — [Mania et al.](https://arxiv.org/abs/1803.07055)
- Texel tuning: 64,000 games gave about 8.8M positions for about 400 parameters, measured over 32,000 games, for a total of +99.6 Elo. The largest steps were +39.4 from changing position selection and +24.6 from exposing parameters to the optimiser. The author warns it can learn spurious correlations and cannot learn knowledge the engine lacks — [Chess Programming Wiki](https://www.chessprogramming.org/Texel%27s_Tuning_Method)
- SPSA uses two measurements per iteration regardless of dimension; Stockfish's version plays a game pair Θ+ against Θ− (introduced 2011) — [CPW SPSA](https://www.chessprogramming.org/SPSA). Fishtest counts one iteration as two games, and advises stopping a tune if values barely move after a few thousand games — [Fishtest docs](https://official-stockfish.github.io/docs/fishtest-wiki/Creating-my-first-test.html)
- The chess-tuning-tools FAQ suggests at least 30,000 × n_params games, and more when parameters are well optimised and potential gains are single-digit Elo — [FAQ](https://chess-tuning-tools.readthedocs.io/en/latest/faq.html). Engines may have over 100 search parameters, and SPSA is preferred because cost doesn't depend on parameter count (forum comment) — [HN thread](https://hn.svelte.dev/item/47049845)
- CLOP is a local-regression tuner for very noisy outputs; its wiki reports no game counts or gains, and notes a 2014 thread about moving from CLOP to SPSA — [CPW CLOP](https://www.chessprogramming.org/CLOP)
- PEGASUS fixes randomness as scenarios so the objective becomes deterministic — [Ng & Jordan](https://arxiv.org/pdf/1301.3878). Strens & Moore report overfitting to those scenarios, that pairing helps stochastic methods such as differential evolution, and that adapting trials per comparison speeds learning — [Strens & Moore](https://www.jmlr.org/papers/v3/strens02a.html)
- CMA-ES averages noise implicitly by sampling many nearby solutions, and UH-CMA-ES raises population variance when ranking uncertainty is high — [Chatzilygeroudis et al.](https://arxiv.org/pdf/1703.07261)
- Hearthstone policy search (a six-neuron network over game-state features): in 50,000 policy evaluations at 200 games each, max win rate was 44.8% for CMA-ES, 45.2% for MAP-Elites, 50.5% for ME (line) and 65.9% for CMA-ME. CMA-ES converged quickly to one solution, on 500 8-core CPUs for 12 h per trial — [Fontaine et al., CMA-ME](https://arxiv.org/abs/1912.02400)
- Learned rules can lose to hand ones: a logistic "tier list" trained on 334 A20 Slay the Spire runs lost to a hand-crafted card list — [Part 3: Good Models Finish Last](https://dev.to/doronsinger/part-3-good-models-finish-last-2n6a)
- Rules-only Balatro bot JackPotts lists 7% wins, and a claimed fruit-fly-connectome RL agent reaches about 20% at the lowest stake; both are self-reported and neither is verified — [JackPotts](https://github.blesdmm.dns-dynamic.net/DrLatBC/JackPotts), [Tom's Hardware](https://www.tomshardware.com/tech-industry/artificial-intelligence/balatro-fan-claims-they-trained-google-fruit-fly-brain-simulation-to-beat-the-game-reinforcement-learning-currently-has-the-model-at-20-percent-success-rate)
- Project: `build_value` had CV R² 0.52 and lost in play (−0.11, t −0.8); learned models fine-tune rather than transform play (+0.152, t 1.96 on 1,024 seeds) — [ai-roadmap.md](../../docs/game-research/ai-roadmap.md), [sim-game.md](../../docs/game-research/sim-game.md)

### Inferences
- **Inference:** the project's pattern (good offline fit, weak in play) resembles the Tetris story, where good policies are easier to find than good value functions. That supports trying direct search, with the win-rate metric or outcome as the objective.
- **Inference:** the Tetris history says features determine the ceiling. Before tuning weights, add features that describe the plan: owned tag count, generators owned, scaling items, stage. A search over a poor feature set will reach a poor optimum.
- **Inference:** Salimans' variance argument fits here: effects of 0.1–0.3 against a label SD of 2.2 is exactly low correlation between action and return.

**Budget toy (my own simulation, not evidence for one method over another).** A smooth sphere is the friendliest possible landscape, so this is an upper bound, and I set the step sizes by hand. Start at 0, optimum at unit distance, gain H at the optimum, paired per-run SD 3.3, 32 candidates per generation, 8 seeds each, 40 trials. Values are final true gain.

| Headroom H | d | Runs | CEM | Antithetic ES |
|---|---|---|---|---|
| 1.0 | 10 | 20k | +0.68 | +0.85 |
| 1.0 | 30 | 20k | +0.10 | +0.32 |
| 1.0 | 30 | 80k | +0.18 | +0.78 |
| 1.0 | 100 | 80k | −1.74 | +0.22 |
| 2.0 | 10 | 20k | +1.70 | +1.94 |
| 2.0 | 30 | 20k | +1.03 | +1.02 |
| 2.0 | 30 | 80k | +1.18 | +1.89 |
| 2.0 | 100 | 80k | −1.02 | +0.79 |
| 0.5 | 30 | 80k | −0.32 | +0.27 |

- **Inference:** about 10 parameters is workable in 1–3 days, about 30 needs 3–11 days, and about 100 is out of reach. A plain elite-averaging CEM at low H can move backwards by selecting on noise, so gate every candidate on fresh seeds.
- SPSA is left out of the table: my gain schedule was unstable in both attempts, which reflects my tuning and says nothing about SPSA. Fishtest's long use of it counts in its favour.
- **Inference:** per-character weight searches (11 × 20–80k = 220–880k runs) are too expensive. Search shared weights, then search per-plan weights for the top 2–3 plans only. Keep per-character tuning to the existing `chartune` table.
- **Inference (gain estimate):** published analogues gain from "no tuning" more than from "already-tuned". Texel's +99.6 Elo started with parameters not yet exposed to the optimiser. The rules player here is heavily hand-tuned, so I would expect +0.2 to +0.8 outcome from weights alone, and more only with new plan features. This is a judgement call with no direct source.

### Gaps
- No credible source gave a total Elo gain from Stockfish SPSA across fishtest. A figure of 35k games for about +1.9 Elo appeared in a search summary but I could not trace it to a URL, so it is not used here.
- I found no noise-robust BO or TPE comparison on a game heuristic at this noise level. With 5–20k noisy runs/day, BO's model overhead is not the limit, but its usual low-dimension range (my recollection, roughly under 20) is not verified here.
- Szita and Lőrincz's exact population, games per candidate and iterations were not retrievable, so the Tetris CE sample cost is unconfirmed here.
- Direct translation from Elo to outcome points is not possible.

## Quality-diversity and population methods: MAP-Elites, Go-Explore, novelty, PBT, Fictitious Co-Play, for builds and small budgets

### Takeaway
The Hearthstone QD results are the best fit to build search, but they used 2–10M games, which is 100–2,000 days at this budget. Use the QD idea in reduced form: keep a small archive of elites per plan and use a surrogate model. PBT below 10 members is unreliable, and Go-Explore's idea of restarting from saved mid-run states is the most directly usable part.

### Cited Findings
- MESB (Hearthstone decks): 10,000 evaluations × 200 games per experiment, which is 2M games; 2D behaviour space of mana-cost mean and variance. Fitness was health difference over games, not win rate — [Fontaine et al., MESB](https://arxiv.org/abs/1904.10656)
- Fontaine et al. found recurring card patterns across evolved decks and used the method to examine balance changes — [MESB](https://arxiv.org/abs/1904.10656)
- CMA-ME: 50,000 policies × 200 games = 10M games per trial; more than doubled MAP-Elites' QD-score (63,296 against 25,936) with 29.17% of cells filled against 21.72% — [CMA-ME](https://arxiv.org/abs/1912.02400)
- DSA-ME (online deep surrogate over 180 cards): 10,000 evaluations × 200 games on 200 CPUs for 10–12 h per trial. QD-score 338.5 against 136.9 for MAP-Elites, max win 98.4% against 90.6%, and cells filled 31.9% against 14.4%. A linear surrogate alone reached 276.2 — [Zhang et al., DSA-ME](https://arxiv.org/html/2112.03534v4)
- Go-Explore names two failure modes: detachment (stopping returning to promising areas) and derailment (failing to return to a state before exploring from it). It archives visited states, returns with minimal exploration, then explores — [First return, then explore](https://arxiv.org/abs/2004.12919). Results: Montezuma mean over 43k, about 4× the prior state of the art; over 650k with domain knowledge — [Ecoffet et al.](https://arxiv.org/abs/1901.10995)
- PBT: populations of 10 or fewer gave higher variance and could give poorer results because PBT is greedy; 20–40 was sufficient for strong and consistent improvement, with diminishing returns beyond that — [Jaderberg et al.](https://arxiv.org/pdf/1711.09846). A 2024 study found 8 best balanced exploration and cost in its setting, with little gained at 16 — [Simultaneous optimizer training](https://arxiv.org/pdf/2408.15421)
- Fictitious Co-Play used N = 32 partners with three checkpoints each. Performance rose from 8.4 deliveries at N = 4 to 10.6 at N = 32, then levelled off. Past checkpoints come at no extra training cost, and removing them significantly reduced performance — [Strouse et al.](https://ar5iv.labs.arxiv.org/html/2110.08176)

### Inferences
- **Inference (budget):** 200 games per evaluation is unaffordable. At 16–32 runs per candidate and 10k runs/day, you can evaluate 300–600 candidates/day. A grid of dominant tag × secondary tag (about 156 cells, or a coarser 13 × 3 commitment-strength grid at 39 cells) would get about 2–15 evaluations per cell per day. So a 10,000-evaluation run takes 160–320k runs (16–32 days at 10k/day), which is too much, while 1,000–2,000 evaluations on a coarse grid (16–64k runs, 2–6 days at 10k/day) is plausible.
- **Inference:** noise makes elites look better than they are, since a cell's elite at SE about 1 is largely the luckiest candidate. Re-evaluate elites on fresh seeds before replacing them.
- **Inference:** the simulator supports `clone()` ([agent.py](../../cursed_words_solver/sim/game/agent.py)), so Go-Explore style restarts are feasible: save the state at stage 3 for runs that have a clear build direction and play forward many variants. This avoids paying for stages 1–2 again and tests whether a build scales. Survivor selection must be handled (see the item-value section).
- **Inference:** the surrogate result is the most useful number here. The linear surrogate alone doubled QD-score (276 against 137), and logs from every run are free training data, so fit a surrogate early and spend real runs only on what it ranks highly.
- **Inference:** PBT at 8 workers is at or below the size the evidence supports, and its main benefit (schedules for neural training) doesn't apply to a rules player. FCP's partner diversity targets co-operation with others, which doesn't apply to a solo game. Its checkpoint idea could carry over by keeping past champions as baselines.

### Gaps
- I found no QD work on a roguelike or on a budget near 10⁴–10⁵ game plays. All cited QD results use over 2M game plays.
- I did not retrieve numbers for novelty search in games, or for noise-robust MAP-Elites variants. These exist in the literature, I believe, but I did not verify them.

## Learning item values: Elo or TrueSkill style, logistic pick order, 17lands GIH WR, synergy, and debiasing survivor and pick bias

### Takeaway
Pick-based Elo measures what the current player likes, not what wins, so it would copy the rules player's habits. The strong approach is a main-effects logistic or outcome model from randomised purchases at a fixed decision point, with a low-rank factorisation for synergy. About 10k runs resolve common-item effects to about ±0.2, while pairs need about 50k+ and shrinkage.

### Cited Findings
- 17lands GIH WR is described as the least biased of its statistics but still favours cards in controlling decks because longer games see more cards. OH WR favours aggressive, cheap cards, and IWD is volatile. The same writer warns against reading win rates as a tier list and against a 50% baseline, since drafters average about 56% — [MTG Arena Zone](https://mtgazone.com/17lands-in-defense-of-the-data/)
- CubeCobra's Elo scores each pick against every card passed in the pack, and per-cube Elo moves ten times faster and is noisier than global Elo — [CubeCobra developer blog](https://cubecobra.com/cube/blog/blogpost/6074d961c9dcfd109cbdc101). A community guide says this Elo reflects how early drafters take a card, not its power — [cube resource hub](https://cal1.lr.ggtyler.dev/r/mtgcube/comments/k77dyr/beginner_resource_hub)
- Slay the Spire card-pick experiment (50 seeds against an expert list): the best offline predictor of human picks (55.8% accuracy) ranked last in play (12–23–15), and a mechanical-features-only model (53.5%) ranked first (16–16–18). The propensity-weighted models were 15–22–13 and 14–21–15, so weighting did not beat mechanical features. The author attributes this to learning human biases. Data was 358,870 picks from 34,210 Silent runs at a 1.5% A20 win rate — [Part 3: Good Models Finish Last](https://dev.to/doronsinger/part-3-good-models-finish-last-2n6a)
- Draft bots trained on over 100,000 human drafts: a deep network beat Naive Bayes and an expert heuristic at matching human picks, and those beat simple heuristics — [Ward et al.](https://arxiv.org/abs/2009.00655). Saxe's bot clusters drafts by archetype with K-means and fits a linear model for each, because a global pick order breaks down given colour and archetype context — [Draftsim](https://draftsim.com/ryan-saxe-bot-model/)
- Dota 2 draft prediction: factorisation machines gave the best results over Naive Bayes, logistic regression and boosted trees — [Semenov et al.](https://rd.springer.com/chapter/10.1007/978-3-319-52920-2_3). Draft-stage AUC was 0.66–0.7 by skill level, and the authors note hero pairs and triples matter but overfit easily — [Yashkov slides](https://dtai.cs.kuleuven.be/events/MLSA16/slides/05_Daniil_Yashkov.pdf)
- Slay the Spire's developers tracked card pick rate and win rate, and grew from three metric graphs to at least 90 — [Game Developer](https://gamedeveloper.com/design/how-i-slay-the-spire-i-s-devs-use-data-to-balance-their-roguelike-deck-builder), [Mechanics of Magic](https://mechanicsofmagic.com/2022/05/22/critical-play-is-this-game-balanced-10/). I did not find quantified bias corrections from them.
- Immortal time bias: analyses that assign groups based on an event during follow-up implicitly condition on surviving to that event, and this inflates the apparent benefit — [Bond University abstract](https://research.bond.edu.au/en/publications/immortal-time-bias-in-observational-studies-of-time-to-event-outc/). The fix is a time-dependent exposure or a landmark analysis, which only counts outcomes after a fixed point. Exposure fixed at baseline by randomisation is not subject to it — [Pulmonary Chronicles review](https://pulmonarychronicles.com/index.php/pulmonarychronicles/article/download/991/2133?inline=1). Landmark analysis may still carry some bias — [Gleiss et al. via science.gov](https://www.science.gov/topicpages/t/time+dependent+analysis)
- Project: ε = 0.1 randomisation was too thin to break the confound, and the project reached the same conclusion on causal labels — [sim-game.md](../../docs/game-research/sim-game.md). Across 438 runs of the plan test: 256 distinct items bought, 13.4 buys per run — computed from the same runs.jsonl.

### Inferences
- **Inference:** the confounded build table (Curse 47%, Cards 36%, Red 10%, Cash 3%) is the immortal-time pattern at run level, because "the build it bought most of" is only known at the end, and longer runs buy more. It may also reflect that the rules player plays Curse well, and that Curse fits route choices. Treat it as a hypothesis only.
- **Inference:** use landmark analysis by shop. At each shop, compare only runs alive at that shop, with randomised purchase within that shop, and measure the outcome from there on. 17lands' GIH WR has the same limitation in another form: longer games see more cards, as longer runs here see more shops.
- **Inference:** randomise offers as well as picks. Random picks among offered items fix pick bias, but offers are biased toward owned tags, so random offers give item effects outside the current build. Plan randomisation does part of this cheaply.

**Sample sizes (my arithmetic, SD 5).** SE of an item effect when owned in fraction f of n runs is 5/√(n f(1−f)).

| n | f = 0.1 (common item) | f = 0.01 (common pair or rare item) |
|---|---|---|
| 10k | 0.17 | 0.50 |
| 50k | 0.075 | 0.22 |

- **Inference:** with 256 items there are 32,640 pairs, so direct pair estimates are out of reach. A factorisation machine with k = 4–8 needs about 1,000–2,000 parameters plus shrinkage. Run a tag-pair model first (13 × 13), which is far smaller, and fit item-level factors only if tag-level synergy shows gain.
- **Inference:** model a three-part structure: value(item) + item × plan + item × stage. The Part 3 result suggests limiting the model to mechanical features rather than giving it an embedding for each item, at least for sparse items. Keep expected in-play gain as the only pass/fail metric, and treat offline accuracy as a diagnostic.
- **Inference:** TrueSkill-style ratings add little here, since they target skill estimation when teams or opponents vary, and this is a solo game with a continuous score. A logistic or outcome regression is the same idea with fewer assumptions.

### Gaps
- I could not fetch 17lands' own metric documentation (the page came back empty) or a blog post on bias, so the bias notes rest on a third-party writer.
- I found no quantified estimate of survivor or pick bias in a roguelike, and no attention or set-based synergy result with in-play gains. Evidence for FM comes from draft win prediction, not from play.
- No source was found that tests randomised offers on a game item-value model.

## Curriculum and difficulty transfer: low to high, all at once, per character or shared with embedding

### Takeaway
Evidence favours a shared model conditioned on character and difficulty, with both randomised during training, and with light curricula based on where learning is happening. Few sources directly compare starting low with mixing all difficulties. At this budget per-character separate models are too expensive, and crowns 6–8 give too few wins to learn from win rate.

### Cited Findings
- OpenAI Five used one parameter set for all heroes and sampled heroes randomly in training. Growing the pool from 17 to 80 heroes slowed early training only by a speedup factor of about 0.8. Roshan's health and initial hero stats were also randomised. Twenty surgeries saved an estimated 30 months against retraining — [Berner et al.](https://ar5iv.labs.arxiv.org/html/1912.06680)
- AlphaStar kept per-race agents: one main, one main exploiter and two league exploiters for each of three races — [AlphaStar](https://storage.googleapis.com/deepmind-media/research/alphastar/AlphaStar_unformatted.pdf)
- Pang et al. reached over 99% against level 1 and over 93% against level 7 using curriculum transfer from easier to harder opponents — [Pang et al.](https://arxiv.org/abs/1809.09095)
- Prioritized Level Replay improves sample efficiency and generalisation on Procgen by sampling levels with high estimated learning potential (TD errors); its emergent curriculum moves from easier to harder levels — [Jiang et al.](https://arxiv.org/pdf/2010.03934)
- Automatic Domain Randomization creates distributions of ever-increasing difficulty, and improved sim-to-real transfer — [OpenAI](https://arxiv.org/abs/1910.07113). Reverse curricula start near the goal and move outward, without demonstrations or reward shaping — [Florensa et al.](https://arxiv.org/abs/1707.05300)
- Surveys frame curricula as ordering experience, and describe automatic curricula as central to several deep RL successes — [Narvekar et al.](https://jmlr.org/papers/v21/20-212.html), [Portelas et al.](https://www.ijcai.org/proceedings/2020/671)
- Project: wins per 132 seeds over crowns 0–8 were 70 / 46 / 30 / 16 / 15 / 13 / 5 / 0 / 2. `build_value` was worse at crowns 0–2 (80 → 67 wins) and better at crowns 3–7 (24 → 34, post hoc), and the Sock Head stamp and Spike tile effects were character-specific — [ai-roadmap.md](../../docs/game-research/ai-roadmap.md)

### Inferences
- **Inference:** use one shared model with character and crown as inputs (one-hot, or a small embedding), plus plan interactions, and estimate character offsets by shrinkage. Dota's 0.8 factor suggests that adding variety is cheap for a shared model, though Dota has far more training data.
- **Inference (per-character samples):** by the SE formula, a character × plan offset to ±0.25 at SD 5 takes 400 runs per pair, or about 57k for 13 × 11. A per-character separate model of hundreds of parameters would need several times that for each character, so about 500k+ total, which is a month or more. Shrinkage avoids this.
- **Inference (crowns):** train on crowns 0–5, where wins and stage-reached both carry signal, and oversample the middle. Crowns 6–8 win so rarely that win rate carries almost no signal, so use stage reached or outcome and evaluate there without training primarily there. Interaction evidence (`build_value`) means a crown-free model is risky, so the crown must be an input.
- **Inference (low to high):** starting only at crown 0 risks teaching plans that win because the targets are low. The target gap grows with crown and the scaling need appears at stage 4+ (×3.8 per stage), so low crowns may reward non-scaling builds. I would use a mix weighted by learning progress (a PLR-style rule on recent gain or model error) over strict low-to-high order. This has no direct test in a roguelike.
- **Inference (reverse curriculum):** with `clone()`, start training on stage 4 and 5 shop decisions from saved mid-run states, then move earlier. This targets the losses at stages 4–5 described in the roadmap.

### Gaps
- I found no direct controlled comparison of low-to-high against mixed difficulty for a roguelike or deckbuilder.
- I found no published minimum samples per character. The figures above are my arithmetic.

## What fails: over-commitment, exploration running out, and early deaths hiding strong builds

### Takeaway
Hard commitment already shows a large measured cost in the live test (mean −2.6 outcome against the rules player), so "no plan is better" could be a false verdict from a poor commitment mechanism. The main failures to guard against are premature convergence, a low-level player tuned against the plan, winner's curse across many arms, and survivor bias.

### Cited Findings
- Project, snapshot of 368 runs: plans average −2.59 outcome against rules on matching seeds (44 pairs, SD 4.25, t about −4.0). Mean outcome: Cash 6.29, Blank 8.48, Consumable 8.37, Cards 10.41, Numbers 11.48, rules 11.47, Curse 12.52. Curse won 9 of 21 and rules 4 of 21, with unbalanced crowns and no multiplicity correction — [runs.jsonl via plantest.py](../../cursed_words_solver/sim/game/plantest.py). The plan rule never buys items of only another build, restocks up to twice per shop and keeps $5 — [sim-game.md](../../docs/game-research/sim-game.md)
- CMA-ES in Hearthstone converged quickly to one solution and was surpassed later by MAP-Elites. The authors suggest a deceptive trap: aggro strategies are found early, so CMA-ES keeps converging to the best aggro deck and doesn't learn more complex control strategies (their hypothesis, not a tested result). This is close to a flat-points build crowding out a scaling one here — [CMA-ME](https://arxiv.org/abs/1912.02400)
- Detachment and derailment are explicit failure modes of exploration — [Ecoffet et al.](https://arxiv.org/abs/2004.12919)
- Naive deviations toward a new strategy lose until supporting tactics exist, as AlphaStar's air-unit example says — [AlphaStar](https://storage.googleapis.com/deepmind-media/research/alphastar/AlphaStar_unformatted.pdf)
- PBT's greediness gets stuck in local optima at small sizes — [Jaderberg et al.](https://arxiv.org/pdf/1711.09846)
- N = 3 populations were suggested as a cause of diversity collapse — [Strouse et al.](https://ar5iv.labs.arxiv.org/html/2110.08176)
- Better offline prediction ranked worst in play — [Part 3](https://dev.to/doronsinger/part-3-good-models-finish-last-2n6a). Evaluating over hundreds of seeds showed high performance variability, and the authors argue common sample-efficiency estimates may not evaluate RL algorithms adequately — [Mania et al.](https://arxiv.org/abs/1803.07055)
- Fixing all randomness can overfit search to specific scenarios — [Strens & Moore](https://www.jmlr.org/papers/v3/strens02a.html)
- Project: lost runs end mostly in stages 4–5 because the build does not scale far enough — [ai-roadmap.md](../../docs/game-research/ai-roadmap.md)

### Inferences
- **Inference: over-commitment.** A −2.6 average is big compared with any effect the project has measured. Likely causes: the first-shop commitment ignores offers, off-plan items are refused even when strong, and restocks and $5 reserves spend money. Test commitment as a dial, not a switch: plan score bonus w ∈ {0, small, medium, hard}, and commit time ∈ {first shop, end of stage 1, end of stage 2}. The rules player is the w = 0 end. Keep "generic points always allowed".
- **Inference: exploration running out / plan unfairly eliminated.** SH might kill a plan whose payoff needs its own tuning, because the rules player's heuristics were tuned for the current mix. AlphaStar's air-unit example is the same issue. Mitigation: before dropping any plan with plausible upside, give it a small within-plan weight search, or check it at stage 3 restarts. Keep at least two plans per character alive through round 2.
- **Inference: early deaths.** A build whose payoff arrives at stage 4 gets no credit if the run dies at stage 3. Mitigation: use stage-3 restarts with the same state across plans, record per-stage survival as well as final outcome, and test commit timing at end of stage 2.
- **Inference: winner's curse.** With 13 × 11 = 143 arm-character estimates at SE 1.25, a naive top pick would look about +3 to +4 better by luck alone (expected maximum of 143 normals is about 2.7 SE). Always confirm on new seeds. The plantest doc already says so.
- **Inference: plan-offer availability.** If a plan's items aren't offered, the run has no way to follow it. Log "plan offers seen per shop", as low counts mean a plan's failure is bad luck and not weak synergy. Curse's SD of 6.5 suggests such a bimodal result: either it comes together and wins, or it does not.
- **Inference: seed overfitting.** Keep rotating seeds. Fixed seeds across generations will overfit search per PEGASUS's known risk. Using fresh paired seeds per generation (paired within a generation, not across) is cheap.

### Gaps
- I found no published measurement of how much hard commitment costs in a deckbuilder bot.
- The cause of the −2.6 is my hypothesis. It has not been tested and could shift as the sample fills out.

## Decision: how to make the AI learn its own play style at this budget

### Takeaway
Do a staged programme totalling about 100–200k runs (2–4 weeks at 7.4k/day): soft plans and a plan bandit first, plan-aware learner next, direct weight search third, and a learned plan picker last. Stop any step that doesn't clear a paired gate on fresh seeds. Avoid deep HRL and full QD for now.

### Cited Findings
- Supporting evidence is in the sections above: plan variables with pseudo-rewards ([AlphaStar](https://storage.googleapis.com/deepmind-media/research/alphastar/AlphaStar_unformatted.pdf)), temporally extended exploration as the main HRL gain ([Nachum et al.](https://arxiv.org/abs/1909.10618)), and direct policy search with good features ([Tetris review](https://arxiv.org/pdf/1905.01652)).

### Inferences
All of this section is my inference. Run counts come from the estimates above.

| Step | What | Runs | Days at 7.4k/day | Pass criterion |
|---|---|---|---|---|
| 0 | Finish the 2,464-run screen; fit shrinkage model; report SD by plan | 2.1k left | 0.3 | Replaces the guessed variances |
| 1 | Commitment dial: w and commit time on top 4 plans and rules, across all characters | 6–12k | 1–2 | Finds a commit mode with mean gap ≥ −0.5 against rules |
| 2 | SH over plans within each character, using best dial, seeded by shrunk screen | 6–12k | 1–2 | Top plan beats rules on 578 fresh runs per character (+6.4k) |
| 3 | Randomise plan per run, pass plan to RCT learner (UVFA-style), and offer randomisation | 20–40k | 3–6 | Paired gain ≥ +0.3 on 1,024 seeds |
| 4 | ES or CMA-ES on 10–30 plan features and item weights, shared, per top plan | 20–80k | 3–11 | Gate every 5–10k runs on fresh seeds |
| 5 | Plan picker: model chooses plan at first and second shop from logged randomised data | 30–60k (mostly reuses logs) | 0–4 extra | Beats best per-character fixed plan |
| 6 | Optional: coarse MAP-Elites with surrogate on 39 cells, or a whole-run REINFORCE pilot | 15–60k | 2–8 | Only if steps 3–5 stall |

- **Why this order:** step 1 protects against rejecting plans because of a poor commit rule. Step 3 is free once plans are logged. Step 5 is where the AI starts to choose its own style, though only among hand-named tags at first. Step 6 is the first where it could find a style nobody named.
- **Metric:** use continuous outcome, which Hearthstone QD work also preferred (health difference over win rate), and report wins and Michael reached. Note that outcome reflects the Michael +8 bonus and should be checked for how it weights risk.
- **Decision rule to skip plans entirely:** if step 2 shows no plan beating rules by more than +0.3 on any character after the dial, plan commitment is not the bottleneck, and effort should go to scaling features (S1 long-horizon value) instead.
- **Stated risk:** all headroom numbers here are assumed. No source tells how much better a plan-based Cursed Words AI can be. The human comparison (6 of 12 human runs reached stage 6 against 6 of 528 for an earlier AI at crowns 1–4, and 37 of 528 after later route settings, from the [roadmap](../../docs/game-research/ai-roadmap.md)) suggests real headroom exists, though the small human sample, its different crown range and route choice all muddy it.

### Gaps
- There is no direct evidence on what total gain a plan-level approach can deliver in this game; that is what steps 0–2 measure.
- Runtime assumptions depend on plan-mode runs taking the same time as those in the 2,464-run estimate.
