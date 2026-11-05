# Strong agents in games adjacent to roguelike deckbuilders

Provenance: figures marked "paper text" were read directly from the paper's PDF text. Figures marked "fetch summary" came from an automated page summary and were not re-read against the source, so check them before quoting. Budget conversions use the project's 5,000-20,000 full runs per day.

## NetHack and other true roguelikes: what strength, why did rules win, what closed the gap?

### Takeaway
Rules won in 2021 because hand-written strategies supplied the hierarchy, memory and long-horizon credit that deep RL could not discover. Scaling imitation of the rules bot did not close the gap. The only claims of closure date from Sept-Nov 2026 and are single-source or self-reported: a depth-rewarded RL agent, an LLM ascension (1 of 3 runs, human-supervised) and coding agents evolving bots.

### Cited Findings
**2021 challenge (paper text)**
- The challenge ran 144 days with 483 entrants and 631 submissions. The top three overall places all went to symbolic agents, and the winning "neural" agent (RAPH) was really a hybrid. The best symbolic median was nearly 3x the neural-track winner's, and the top-episode lead was about 5x — [Hambro et al. 2022](https://arxiv.org/abs/2203.11889)
- The winner's median of 5,300 is only just above "Beginner" (under 2,000 is Beginner). 1 in 20 of its Valkyries exceeded 30,000. Performance was heavily role-dependent and heavy-tailed — [Hambro et al. 2022](https://arxiv.org/abs/2203.11889)
- The organisers' explanation for the rules win has three parts: strategy-like subroutines such as "Find Minetown" were easy to write; hierarchical RL is unsolved under large action spaces and sparse reward; and long-term credit assignment is an open problem — [Hambro et al. 2022](https://arxiv.org/abs/2203.11889)
- AutoAscend has two parts: state parsing and memory, including non-current levels and inventory; and an interruptible behaviour tree (exploration yields to combat, which yields to emergency healing). Combat is a hand-written scoring function over a reduced 34-action space. Its authors name RL on that reduced action space as the obvious future upgrade — [Hambro et al. 2022](https://arxiv.org/abs/2203.11889)
- RAPH used a rule-based first-fit skill selector, hard-coded skills and one learned skill, combat, trained on hand-crafted features. Non-combat steps were "fast-forwarded" out of its episodes — [Hambro et al. 2022](https://arxiv.org/abs/2203.11889)
- KakaoBrain (neural) used IMPALA-style RL with a separated action space and role-specific shaped policies. Each policy took 10B steps on 224 CPU cores and 16 V100 GPUs at 100K frames per second — [Hambro et al. 2022](https://arxiv.org/abs/2203.11889)
- Score as a metric caused misbehaviour: agents stayed on upper levels or terminated early, and starvation deaths followed. The organisers recommended achievement-based metrics — [Hambro et al. 2022](https://arxiv.org/abs/2203.11889)

**Offline and imitation (paper text)**
- NLD-AA holds about 3B transitions from 100,000 AutoAscend games, and NLD-NAO about 10B from 1.5M human games. Mean returns: DQN-Offline 0, CQL 33, IQL 160, BC 554, APPO 868, APPO+BC 1,282, against a dataset average of 10,105. The runs took about 1 day on 20 CPUs and one GPU — [Hambro et al. 2022b](https://arxiv.org/abs/2211.00539)
- AutoAscend sits only in the top 15% of NAO players by mean score, or the top 33% among "competent" players — [Hambro et al. 2022b](https://arxiv.org/abs/2211.00539)
- HiHack, with single-GPU 48-hour runs and 3.2B transitions: BC LSTM scored 658 mean / 403 median, hierarchical BC LSTM 931 / 614, and the best BC 1,318 / 914 (non-hierarchical transformer-LSTM). The best overall, hierarchical LSTM with APPO+BC, scored 1,551 / 972. AutoAscend scored 8,556 / 4,918. Doubling the transformer from 50.8M to 98.9M parameters made it worse. Data scaling from 10 to 100,000 games was sub-log-linear, levelling off around mean 1,000 — [Piterbarg et al. 2023](https://arxiv.org/abs/2305.19240)
- Scaling laws: NLD-AA was extended to about 55B samples and a compute-optimal model of about 45M parameters, trained for 5-6.5 days. Human Monk (an easy role) reached 7,784 against the expert's 17,274. The next-best offline method scored 4,504, and BC plus fine-tuning with kickstarting scored 10,588. Scaling curves converge to the expert's return as a ceiling, and context up to 4,096 steps plus inventory features both mattered — [Tuyls et al. 2024](https://arxiv.org/abs/2307.09423)

**Other learned approaches**
- Motif (paper text, figure-only scores): Llama 2 70B ranked pairs of in-game messages from an observation-only dataset. An agent trained only on that intrinsic reward out-scored agents trained directly on game score, and combining the two did better still. Its base RL agent was the Chaotic Dwarven GPT-5 baseline on Sample Factory — [Klissarov et al. 2023](https://arxiv.org/abs/2310.00166)
- BALROG: o1-preview reached 1.5% NetHack progression in 2024, with a "knowing-doing gap" (models state the right strategy and fail to act on it) — [Paglieri et al. 2024](https://arxiv.org/abs/2411.13543). The live leaderboard now shows GPT-6-Astra-Max 13.2 ± 2.7, Claude-Opus-5-Max 7.3 ± 1.6, Gemini-3-Pro 6.8 ± 3.2 — [BALROG leaderboard](https://balrogai.com/)

**2026 claims (treat as unconfirmed)**
- A search snippet of the NetHackers site says an RL agent beat AutoAscend in Sept 2026 for the first time since 2021, with 11.78% progression when score-trained and 16.98% when depth-trained, against AutoAscend's 7.8%. The landing page I fetched no longer displayed this text. No paper, method or compute found — [NetHackers](https://nethackers.dunnolab.ai/)
- The NetHackers snapshot (2026-11-05) shows 1,772 programs, 27 "hackers", 0 ascensions, best progression 0.807, and AutoAscend floor 0.077 (public) and 0.078 (private) — [NetHackers](https://nethackers.dunnolab.ai/). The top five board rows average about 0.394 progression, but are self-reported, list no method, and all belong to one owner — [NetHackers board](https://nethackers.dunnolab.ai/board?scope=generalist)
- The site's `evolve` loop gives a bot to a coding agent, asks for one focused change per iteration, and keeps improvements. Bots are re-scored on private seeds because a bot can influence its self-reported score — [dunnolab/nethackers](https://github.com/dunnolab/nethackers)
- A GPT-6 Astra run ascended on NetHack 3.6.7 on a public server. It was 1 of 3 documented runs (the others died at Dlvl 51 and at the Castle), with unrestricted spoiler access, an agent-built harness, Python movement guards, on-disk journals, and a $200/month plan plus about $300 in credits. The author says it does not establish reliability — [Vaguely Aligned blog](https://kenforthewin.github.io/blog/posts/llm-nethack-ascension/). The NetHackers maintainers checked the server dump and note it was open-book and human-supervised, and that the harness changed mid-game — [PR #114](https://github.com/dunnolab/nethackers/pull/114)

**Rogue-Gym, Angband, Brogue**
- Rogue-Gym (paper text): over about 32M training frames, in a setup without enemies or items, only PPO+L2 and beta-VAE PPO clearly beat random on unseen dungeons, and both were much worse than on training seeds — [Kanagawa & Kaneko 2019](https://arxiv.org/abs/1904.08129)
- Angband: Borg is described as the premier bot, and its success partly relies on level-scumming — [Earlham student paper](https://portfolios.cs.earlham.edu/wp-content/uploads/2018/12/crawl-o-matic2.pdf)

### Inferences
- Budget: 55B samples is roughly 1.9M AutoAscend-length games (29.5k transitions per game), which is 93-370 days of this project's budget, for a clone at 45% of its source on the easiest role. Cloning the rules player is a warm start, not a route past it.
- The best learned systems added knowledge rather than replacing it: reduced action spaces, parsed features, skill hierarchies, or a different objective. The 11.78% vs 16.98% claim, if it holds, suggests the objective mattered as much as the learner.
- Procedural generation is the common failure mode. Agents that look fine on seen seeds collapse on new ones, so private-seed evaluation is not optional.

### Gaps
- No primary source for the Sept 2026 RL result. I could not determine whether the top NetHackers programs are rule-based, learned or hybrid, or how they compare on private seeds.
- BALROG and NetHackers both report "progression", but I did not confirm the two metrics are the same, so 13.2% should not be compared with 7.8%.
- Nothing found on "diplomat-style" agents. No Brogue RL work found. Angband hierarchical RL (Mariusdottir et al. 2015) and Rogue A3C ([arXiv 1804.08685](https://arxiv.org/abs/1804.08685)) were seen only as snippets. NetPlay ([arXiv 2403.00690](https://arxiv.org/pdf/2403.00690)) was not read for numbers.
- Motif's exact scores and compute are in figures I did not extract. The Challenge's Figure 1 leaderboard values were not extractable as text.

## MTG draft and deckbuilding: 17lands, Bertram, Draftsim, Ward, Hearthstone, LOCM, Dominion

### Takeaway
Pick-prediction work is cheap and mostly measures imitation of humans, not wins. The results that actually moved win rate come from simulators: a draft-only RL swap, evolved buy lists, and quality-diversity deck search. All of these held play policy fixed or heuristic, which is the closest published analogue to a rules player plus a learned build layer.

### Cited Findings
**MTG draft**
- Ward et al. used 107,949 M19 drafts from Draftsim (86,359 train). Human-pick accuracy: random 22.15%, rarest-card 30.53%, Naive Bayes 43.35%, expert heuristic 44.54%, deep net 48.67%. Decks were never played and no win rates were measured. The architecture section quotes about 64.7% for the final model, which the paper does not reconcile with Table II (fetch summary) — [Ward et al. 2020](https://ar5iv.labs.arxiv.org/html/2009.00655)
- Bertram et al. (paper text) trained a Siamese ranker on the same data, with k-1 pairwise comparisons per pick. Accuracy was 53.69% at embedding size 2 and 83.78% at 256, and their card ratings differ from expert lists. Again this measures imitation, not wins — [Bertram et al. 2021](https://arxiv.org/abs/2105.11864)
- 17lands is purely observational. GIH WR is confounded with game length and deck composition, so it is a biased estimate of the causal value of a pick, although it is useful in practice — [Ramos 2026](https://arxiv.org/abs/2604.18314)
- A community discussion suggests about 5,000 games are needed for confidence in extreme card win rates (forum claim, not a study) — [MTGA_Draft_17Lands issue](https://github.com/bstaple1/MTGA_Draft_17Lands/issues/5)

**Legends of Code and Magic (paper text unless marked)**
- Vieira et al. modelled drafting as an MDP and trained PPO with a fixed battler. Training took about 30 minutes with the max-attack battler and 3 hours with greedy. Trained drafters won up to 83.5% against the original drafter. Swapping only the draft in the CoG 2019 tournament moved max-attack from 34.0% and 10th to 46.1% and 4th, over about 350,000 matches. The memoryless "Immediate" model beat the LSTM and History variants — [Vieira et al. 2020](https://www.sbgames.org/proceedings2020/ComputacaoFull/209690.pdf)
- ByteRL trains draft and battle end to end (V-trace, UPGO, optimistic smooth fictitious self-play, no search), and won COG 2022 — [Xi et al. 2023](https://arxiv.org/abs/2303.04096)
- ByteRL proved exploitable. Cloning from 125,000 matches (about 3.5M pairs) gave an agent that won about 42.4% against it, and in small fixed-deck-pool settings BC warm start at least halved the time PPO needed to reach 75% — [Haluska & Schmid 2024](https://arxiv.org/abs/2404.16689)

**Hearthstone deck building**
- EvoSabber (paper text): 10,000 evaluations of 200 games each per class-strategy pair, on 500 CPU nodes. Fitness was health difference rather than win rate, specifically to keep the magnitude of wins and losses — [Fontaine et al. 2019](https://arxiv.org/abs/1904.10656)
- DSA-ME (fetch summary): 10,000 evaluations at 200 games each. Each trial took 10-12 hours on 200 Xeon CPUs. Best deck win rate 98.4% vs 90.6% for MAP-Elites; QD-score 338.5 vs 136.9. The surrogate was an MLP (128/32/16) on bag-of-cards counts over 180 cards. It was imprecise (only 3% of surrogate elites landed in the same true cell), yet still useful. An offline surrogate trained on random decks did significantly worse, and the differences among surrogate methods on best win rate were not significant — [Zhang et al. 2022](https://ar5iv.labs.arxiv.org/html/2112.03534)
- The same study needed a playable fixed agent first: default heuristics struggled, so the authors tuned a 109-parameter network with 50,000 CMA-ME evaluations — [Zhang et al. 2022](https://ar5iv.labs.arxiv.org/html/2112.03534)

**Dominion (fetch summary)**
- Provincial (one author) evolves readable ordered buy menus against 5 leaders with a pool of about 100. It runs about 40,000 games per second on 8 cores, hundreds of thousands of games per generation, and 32+ generations. Play is heuristic. It needs retraining per kingdom and plays essentially randomly on untrained ones. Strength claims ("competitive with experienced players") are the author's own, with no controlled study — [Fisher](https://graphics.stanford.edu/~mdfisher/DominionAI.html)
- A Rainbow DQN with two 256-unit layers, learning only gain decisions while Provincial's heuristics handle action cards, trained on about 7,000 self-play games in about 45 minutes on a 1080 Ti. It went 575-62-363 against the Provincial menu and 912-27-61 against Big Money, but 418-24-558 against a Village/Smithy engine, attributed to never exploring that combo. No multi-kingdom results — [Dominion paper 2024](https://arxiv.org/html/2405.06846v1)
- A geometric deep learning agent with SAC is claimed as the first learning agent making all Dominion decisions without heuristics — [AIIDE paper](https://ojs.aaai.org/index.php/AIIDE/article/download/27518/27291/31569)

### Inferences
- The LOCM tournament swap is the best published evidence that a learned build layer alone can move a fixed-play agent a long way. Caveat: this is one game and a weak base agent, and the top agents stayed far ahead.
- Budget: EvoSabber or DSA-ME at 2M games per configuration is 100-400 days here. Provincial at several million games is about a year or more. Both require a cheaper fitness, heavy data reuse or a far smaller search. Dominion's 7,000 games (about 0.4-1.4 days) is affordable, but its engine loss shows the exploration risk at that budget.
- A simulator gives this project something MTG draft research lacks: it can measure win rate directly, so human-pick accuracy need not be a proxy.
- GIH WR's bias applies directly to "win rate when item was bought" statistics from logs. The project's randomised-decision data avoids it, which draft researchers cannot do.

### Gaps
- I found no published model trained on 17lands outcomes with a reported win-rate gain. DraftFM ([arXiv 2608.19568](https://arxiv.org/pdf/2608.19568)) reports no out-of-sample results yet.
- No peer-reviewed Hearthstone Arena drafting win-rate study found. HearthArena appeared only as a community-curated helper.
- ByteRL's training scale was not captured. The claim that it beat a top-10 Hearthstone player comes from the Haluska abstract, not checked at source. A Bertram/COG24 follow-up was not read.

## Autobattlers, team building and Pokémon

### Takeaway
Rigorous evidence for autobattlers is thin: most projects are simulators and hobby repos with no measured strength. Pokémon battling is well measured, but it succeeds by using human replays and fixed teams, and team building itself is still called open. The notable exception, AutoTavern, is a new unverified preprint.

### Cited Findings
- TFTMuZeroAgent is a tested TFT Set 4 simulator with PettingZoo and Gym environments, but its README reports no trained agent or strength ("Bring your own model") — [silverlight6/TFTMuZeroAgent](https://github.com/silverlight6/TFTMuZeroAgent)
- Super Auto Pets repos use Maskable PPO and DQN/A2C, and those seen state no headline win rate. One reports continued training beat fine-tuning — [sap-agent](https://github.com/endodod/sap-agent); [SuperAutoPetsAI](https://github.com/CallThemHunter/SuperAutoPetsAI)
- A Python-simulator MCTS assistant for Battlegrounds claims 56% of turns won vs 46.92% for a rank-1 player, and 9.56% lost vs 26.26%. This is a per-turn replay comparison of 128 minions, not full-game strength (paper text) — [CATA 2022](https://easychair.org/publications/open/Kftf)
- AutoTavern (preprint, abstract): LLM research agents built a Battlegrounds simulator (TavernGym) and 23 PPO agent versions in 20 days, with live games feeding back and a human settling ambiguous rules. Rating rose from about 6,000 to about 15,000. The last 20 games averaged placement 1.60 with 80% firsts. Its conclusion: "LLM agents build far better than they play." No compute reported — [Ma & Wang 2026](https://arxiv.org/abs/2610.33845). Aggregator metadata lists no verified code and no independently verified numbers — [OpenTrain listing](https://www.opentrain.ai/papers/build-don-t-play-self-improving-llm-research-agents-develop-a-hearthstone-battle--arxiv-2610.33845/)
- Metamon (fetch summary): about 475k reconstructed human battles gave about 950k point-of-view trajectories and 38M timesteps, with transformers of 15-200M parameters. Offline RL beat pure BC. Estimated win rate against a random ladder opponent was 41-58% before self-play data and 64-80% after, reaching the top 10% of active usernames, with no search or dynamics model. Self-play on realistic teams alone gave inconsistent gains against humans; adding unrealistic teams and IL opponents helped. Value filters became over-pessimistic as critics improved — [Grigsby et al. 2025](https://arxiv.org/html/2504.04395v2)
- PokéChamp uses minimax with an LLM for action sampling, opponent modelling and leaf evaluation, without game-specific training. It won 76% against the best prior LLM bot and 84% against the strongest rule bot, with a projected Elo of 1300-1500 (top 30-10%) — [Karten et al. 2025](https://arxiv.org/abs/2503.04094)
- VGC-Bench has 700,000+ battle logs. Single-team RL reaches strong win rates, generalising across teams is unsolved, and team building is explicitly left open — [Angliss et al. 2025](https://arxiv.org/abs/2506.10326)

### Inferences
- AutoTavern's 20-game placement figure is far too small to support "rivals top players" in a game this noisy. Its useful content is the workflow: invest agent effort in the simulator and opponents, then train cheaply.
- Calibrated fixed opponents, not self-play, are the part of AutoTavern closest to a single-player game. Metamon's experience suggests variety in training scenarios beat more self-play on realistic data.
- Team generalisation failure is the warning for 11 characters and 8 difficulties. A model tuned on one configuration may not transfer.

### Gaps
- I found no peer-reviewed TFT, Dota Auto Chess or Underlords agent with measured strength, and no published evidence on Riot's or Valve's internal bots. A USP undergraduate monograph on auto-chess IRL gives no benchmarks. Absence from my searches is not proof none exists.
- Metamon's compute is in an appendix I did not read. The 3.5M figure is a later dataset, not the size used in the reported experiments.

## Stochastic imperfect-information games on low sample budgets: Mahjong, poker, 2048, backgammon, Yahtzee, solitaire

### Takeaway
These are the most transferable results. Suphx shows how to turn a noisy long-run outcome into a per-segment reward, and TD-Gammon shows that about 1.5M games with hand features reaches expert level. Heuristic-plus-rollouts multiplies win rate. 2048's cheap reputation depends on 10M-200M very fast episodes, which this simulator cannot match.

### Cited Findings
**Mahjong (paper text)**
- Global reward prediction: a 2-layer GRU plus 2 dense layers, trained on top-human logs, predicts final game reward from rounds so far. The RL reward for round k is the predictor's change, Φ(x_k) − Φ(x_k−1). This exists because the game reward cannot separate good and bad rounds, and round score can misstate a good defensive sacrifice — [Li et al. 2020](https://arxiv.org/abs/2003.13590)
- Oracle guiding: train with perfect-information features (hidden hands, wall), Bernoulli-drop them with probability decaying from 1 to 0, then continue at one-tenth learning rate with importance-weight rejection, without which training was unstable — [Li et al. 2020](https://arxiv.org/abs/2003.13590)
- Compute: SL used 15M/5M/10M/10M/4M human state-action pairs for the five models, with 76.7% discard accuracy. Each RL agent took 1.5M games, 44 GPUs and 2 days. Evaluating one agent took 1M games on 20 K80 GPUs for 2 days. The deployed agent trained on about 2.5M games — [Li et al. 2020](https://arxiv.org/abs/2003.13590)
- Measured strength: 10 dan record and 8.74 stable rank over 5,760 games, vs 7.46 top humans (8,031 games), and 6.59 and 6.64 for the prior AIs. Above 99.99% of ranked Tenhou players. Component gains SL < RL-basic < RL-1 < RL-2 appear only in a figure — [Li et al. 2020](https://arxiv.org/abs/2003.13590)
- Knowledge kept: a rule-based win declaration model, 100+ hand-crafted look-ahead features from depth-first search, and RL applied only to the discard model, with the other four inherited from SL to save training time — [Li et al. 2020](https://arxiv.org/abs/2003.13590)
- Run-time adaptation (pMCPA): 100K simulated trajectories per fixed private hand followed by policy-gradient fine-tuning. It beat the unadapted agent 66%, but was tested on only hundreds of rounds and was too slow for routine use — [Li et al. 2020](https://arxiv.org/abs/2003.13590)
- Mortal, by an individual developer: up to 40K hanchans per hour on an RTX 4090 and Ryzen 7950X, using a Rust emulator — [Mortal docs](https://mortal.ekyu.moe/). It measures progress with duplicate 1v3 sets (same seed across four seats). Reported rank-point gaps between versions go down to 0.25-0.42 — [Mortal strength page](https://mortal.ekyu.moe/perf/strength.html). The FAQ says true strength is unknown because Tenhou refused an individual's AI account — [mjai-reviewer FAQ mirror](https://worker-github.shheric.workers.dev/Equim-chan/mjai-reviewer/blob/master/faq.md)

**Poker**
- Pluribus's blueprint took about 8 days on a 64-core server, about 12,400 core-hours, under 512GB and no GPUs, for an estimated $144 or under $150 cloud cost. Play used two CPUs. AIVAT subtracts a baseline from luck-driven outcomes, and it won 48 ± 25 mbb/game against elites (secondary sources) — [InfoQ](https://www.infoq.com/news/2019/07/AI-beat-poker-facebook-cmu); [The Register](https://www.theregister.com/2019/07/12/pluribus_ai_poker_human_pros)

**2048**
- Jaśkowski (fetch summary): a typical budget of 10^10 actions, about 10^7 episodes, on 24 cores for 0.26-5.47 days. Best scores: 324,710 at 1-ply and 609,104 at 1 s/move, with 70% reaching 32768. Prior results: Szubert-Jaśkowski 99,916 at 1-ply, hand-feature CMA-ES expectimax 442,419 — [Jaśkowski 2016](https://arxiv.org/abs/1604.05085)
- Guei et al. (paper text): optimistic initialisation took 8x6-tuple 1-ply from 309,208 to 361,471 and the 32768 rate from 0% to 21.75%. TC fine-tuning reached 370,194, two stages 404,288, 6-ply search 586,583, and tile downgrading 625,377 (72%, over only 100 episodes). The 200M training episodes took 66 hours on one Xeon E5-2698 v4 using afterstate values and designed tuple shapes — [Guei et al. 2021](https://arxiv.org/abs/2111.11090)
- The original TD result reached the 2048 tile in over 97% of games with 860,625 weights (search-result text; the page itself returned 403) — [Szubert & Jaśkowski](https://www.cs.put.poznan.pl/mszubert/projects/2048.html). A later paper describes that work as using about 1M episodes (search-result text) — [Jaśkowski 2016](https://arxiv.org/abs/1604.05085)

**Backgammon**
- TD-Gammon versions: raw features, 0.2M games, intermediate level; hand features 0.3M games, -0.25 points/game against grandmasters; 2.1 at 1.5M games with 2-ply, near parity with Robertie (-1 point over 40 games); 3.0 at 1.5M with 3-ply — [Wikipedia table](https://en.wikipedia.org/wiki/TD-Gammon) (secondary)
- Tesauro credits dice variability for exploration, quick game termination for feasibility, a smooth value function, and correlated errors between similar moves, so ranking stays accurate even though absolute equity errors can exceed 0.1 points (fetch summary) — [Tesauro 1995](https://www.bkgm.com/articles/tesauro/tdl.html)

**Yahtzee and solitaire**
- Yahtzee: the best agent reached median 241.78 over 100,000 games, within 5% of optimal DP's 254.59. REINFORCE and PPO were hyperparameter-sensitive and A2C robust. Upper bonus was achieved at only 24.9%, attributed to long-horizon credit and exploration (abstract; note the median-vs-mean comparison) — [Pape 2025](https://arxiv.org/abs/2601.00007)
- Thoughtful solitaire (perfect information; paper text): win rate went from heuristic 13.05% to 31.20%, 47.60%, 56.83%, 60.51% and 70.20% across 1-5 rollout levels, at 0.021 s, 0.67 s, 7.13 s, 1m36s, 18m07s and 1h45m per game. A human expert won 36.6% in 2,000 games — [Yan et al. 2004](https://papers.nips.cc/paper_files/paper/2004/file/48c3ec5c3a93a9e294a8a6392ccedeb4-Paper.pdf)

### Inferences
- Throughput comparison at this project's budget (my arithmetic): Suphx about 750k games/day is 37-150x, Mortal about 960k/day is 48-192x, 2048 about 73M/day is 3,600-14,500x, and Provincial about 3.5B/day is roughly 170,000-690,000x.
- Budget reach: TD-Gammon 0.0's 200k games takes 10-40 days. Suphx's and TD-Gammon 2.1's 1.5M takes 75-300 days. 2048 at 10^7 takes 500-2,000 days. So "TD-Gammon scale" is reachable; "n-tuple scale" is not, unless decision samples per run are far higher than per-game comparisons imply.
- Statistical power at a 19% win rate, unpaired, 80% power (my arithmetic): about 24,000 runs per arm to detect +1 point, 6,000 for +2, 1,000 for +5. A ±1-point A/B test costs 2.4-10 days of the whole budget. Same-seed pairing, as Mortal does, should be the default where the simulator allows it, and its benefit should be measured.
- Yan's table is the strongest case for rollouts on a weak heuristic, but the game is deterministic with perfect information. With hidden randomness, each rollout needs sampling, so the multiplier will be smaller.

### Gaps
- Suphx's per-component stable-rank numbers exist only in a figure. Mortal's training compute and its method docs were not read, and its Hugging Face or third-party strength claims were not used.
- Yahtzee's training budget was not on the abstract page. I did not retrieve Szubert-Jaśkowski's score at specific game counts (their page returned 403), or Tesauro's training hardware.

## Cross-game comparison: method, samples, compute, strength, knowledge kept, what failed

### Takeaway
Every strong entry whose details I captured kept substantial hand-crafted knowledge or human data. The only ones cheap in this project's terms restrict learning to one decision type.

### Cited Findings
Sources are those cited in the sections above.

| Agent | Method | Samples | Compute | Strength | Knowledge kept | Failed or limited |
|---|---|---|---|---|---|---|
| [AutoAscend](https://arxiv.org/abs/2203.11889) | Behaviour tree | None learned | Eval only | Median 5,300; 4,918 re-run | All | Far from ascension; top 15% of humans by mean |
| [RAPH](https://arxiv.org/abs/2203.11889) | Rules + RL combat | Not captured | Not captured | Top "neural" entry | Selector, features, most skills | About 1/3 of AutoAscend |
| [KakaoBrain](https://arxiv.org/abs/2203.11889) | IMPALA-style | 10B per policy | 224 CPU, 16 V100 | Below hybrid | Action space, shaping | Lab scale, still behind |
| [HiHack](https://arxiv.org/abs/2305.19240) | BC + APPO | 3.2B | 1 GPU, 48h | 1,551 mean | Strategy labels from rules | Sub-log data scaling |
| [Suphx](https://arxiv.org/abs/2003.13590) | SL + RL + GRP + oracle | 44M pairs, 1.5-2.5M games | 44 GPUs, 2 days | Above 99.99% | Win rule, look-ahead | pMCPA too slow |
| [Mortal](https://mortal.ekyu.moe/) | Deep RL | Not captured | Desktop eval | Unknown vs humans | Not captured | No ranked access |
| [Vieira](https://www.sbgames.org/proceedings2020/ComputacaoFull/209690.pdf) | PPO, draft only | Not captured | 0.5-3 hours | 34.0% to 46.1% in tournament | Battle agent | Trained per battler |
| [Provincial](https://graphics.stanford.edu/~mdfisher/DominionAI.html) | Coevolved buy menus | Millions | Minutes at 40k/s | Author claim only | Play logic, menu template | Per-kingdom retraining |
| [Dominion DQN](https://arxiv.org/html/2405.06846v1) | Rainbow, gains only | About 7,000 | 1080 Ti, 45 min | 637/1000 win-or-tie vs Provincial | All action plays | Lost to unseen engine |
| [EvoSabber](https://arxiv.org/abs/1904.10656) / [DSA-ME](https://ar5iv.labs.arxiv.org/html/2112.03534) | QD deck search | 2M games per run | 500 nodes / 200 CPUs | Up to 98.4% vs fixed decks | Play agent, operators | Depends on fixed opponents |
| [Metamon](https://arxiv.org/html/2504.04395v2) | Offline RL | 475k battles | Not captured | 64-80% vs humans | Replay reconstruction | Rare teams, self-play |
| [TD-Gammon 2.1](https://en.wikipedia.org/wiki/TD-Gammon) | TD self-play | 1.5M | 1990s workstation (not sourced) | Near grandmaster parity | Features | Cube, endgames |
| [2048](https://arxiv.org/abs/2111.11090) | TD n-tuple | 10-200M | 1 CPU box, days | 625,377 | Tuple shapes, stages | Exploration without OI |
| [Solitaire rollouts](https://papers.nips.cc/paper_files/paper/2004/file/48c3ec5c3a93a9e294a8a6392ccedeb4-Paper.pdf) | Heuristic + nested rollouts | None | Minutes-hours per game | 70.2% | Heuristic | Deterministic only |

### Inferences
- Among measured entries, end-to-end learning at solo budget worked only in small or very fast games (TD-Gammon, 2048, Yahtzee). Mortal is a possible exception, but its strength against humans is unmeasured. Metamon relied on a large human corpus and KakaoBrain on cluster compute; ByteRL's scale is unconfirmed.

### Gaps
- Empty cells reflect what I did not capture, not what does not exist. Compute for ByteRL, RAPH and Metamon remains open.

## Which were achievable by one person on a desktop?

### Takeaway
Most cheap wins came from one or two people using a narrow scope and a fast simulator. The barrier was usually simulator speed or training data, not model size.

### Cited Findings
- Individual or very small: Provincial (one author, 8 cores, minutes) — [Fisher](https://graphics.stanford.edu/~mdfisher/DominionAI.html); Mortal (individual; emulator benchmarked on one high-end desktop, training hardware not found) — [Mortal docs](https://mortal.ekyu.moe/); the LLM ascension (individual, about $500 of subscriptions and credits) — [Vaguely Aligned blog](https://kenforthewin.github.io/blog/posts/llm-nethack-ascension/)
- Desktop-sized small-group work: 2048 best agent in 66 hours on one CPU — [Guei et al. 2021](https://arxiv.org/abs/2111.11090); Dominion DQN in 45 minutes on a 1080 Ti — [Dominion paper](https://arxiv.org/html/2405.06846v1); LOCM draft in 0.5-3 hours — [Vieira et al. 2020](https://www.sbgames.org/proceedings2020/ComputacaoFull/209690.pdf); HiHack BC at 48 GPU-hours, given the data — [Piterbarg et al. 2023](https://arxiv.org/abs/2305.19240)
- Pluribus's blueprint is cheap in dollars but needs a server-class 64-core machine and up to 512GB — [InfoQ](https://www.infoq.com/news/2019/07/AI-beat-poker-facebook-cmu)
- Lab or cluster scale: KakaoBrain — [Hambro et al. 2022](https://arxiv.org/abs/2203.11889); Suphx — [Li et al. 2020](https://arxiv.org/abs/2003.13590); EvoSabber — [Fontaine et al. 2019](https://arxiv.org/abs/1904.10656); DSA-ME — [Zhang et al. 2022](https://ar5iv.labs.arxiv.org/html/2112.03534)

### Inferences
- Suphx's total is 88 GPU-days per agent on 2020-era K80s, and a modern desktop GPU might be equivalent to many of them, but its throughput depended on a fast simulator. For this project the limit is simulated runs, so the Suphx pipeline fits only if the 75-300 day game count is cut with log reuse.
- Speeding up the simulator may be the highest-return "ML" investment. Mortal and the 2048 work both use native-code engines (Rust, C++). Each 10x in simulator speed moves a whole class of methods into range.

### Gaps
- AutoAscend's team size was not confirmed. Mortal's actual training hardware and duration were not found.

## What transfers to a run-based single-player build game, and where the analogy breaks

### Takeaway
The current architecture (rules plus a learned override) matches the class that has held up best. The next steps with the best evidence are a Suphx-style floor-value reward, a learned build layer on top of fixed play, paired-seed evaluation and agent-driven rule improvement. These are inferences across games, and none has been tested on Cursed Words.

### Cited Findings
- Fixed play with a learned build layer moved tournament win rate in LOCM — [Vieira et al. 2020](https://www.sbgames.org/proceedings2020/ComputacaoFull/209690.pdf)
- A value-difference reward was the first RL enhancement Suphx added, ahead of the oracle — [Li et al. 2020](https://arxiv.org/abs/2003.13590)
- Smoothed fitness (health difference) was chosen over win rate in deck search — [Fontaine et al. 2019](https://arxiv.org/abs/1904.10656)
- BC warm start helps but caps at the source without further training — [Tuyls et al. 2024](https://arxiv.org/abs/2307.09423); [Haluska & Schmid 2024](https://arxiv.org/abs/2404.16689)
- An optimistic initial value unlocked rare high-value outcomes in stochastic 2048 — [Guei et al. 2021](https://arxiv.org/abs/2111.11090)

### Inferences
Ranked by fit to the budget (my judgement):
1. **Floor-value reward.** Train P(win | end of floor k) on existing logged runs and use its change across each floor as the reward for item decisions. If per-floor logs already exist it needs no new simulation to fit, and it targets the noise problem directly. Risk: Suphx trained on stronger human logs, whereas bot logs give values specific to the bot's policy, so refit as the policy improves.
2. **Afterstate value for shop choices.** Evaluate the build after each purchase option, as 2048 and TD-Gammon do, with hand features. Correlated errors in similar options, Tesauro's point, suggest ranking may be good even when absolute win probability is poor.
3. **Build surrogate.** A bag-of-items network predicting outcome, as in DSA-ME, fed by logged and randomised runs. Warning: the offline-on-random surrogate did significantly worse, so keep collecting data near good builds.
4. **Evaluation discipline.** Paired seeds, baseline-subtracted outcomes (AIVAT-style), fixed holdout seeds, and a power calculation before every A/B test.
5. **Coding-agent rule patches** evaluated on fixed seeds, per AutoTavern and NetHackers. By raw win rate the statistical limit is about 1-3 patches a day at about ±2 points and under one a day at ±1 point, so a lower-variance proxy is needed.
6. **Rollouts at a few high-value item decisions only.** The cost per decision is high at this simulator speed.
7. **Oracle guiding.** The simulator can reveal future shops and bosses from the seed, which is a natural analogue. But it adds training stages and is justified only once the base RL loop is working.
8. **Optimism for rarely bought items**, to counter value underestimates on builds seldom tried, as with Dominion's unexplored engine.

Lessons about what not to do: whole-game end-to-end RL, more parameters on the same data (HiHack got worse), cloning alone, and offline RL on narrow bot data (CQL and IQL collapsed on NLD-AA). The NetHack and Yahtzee results both show long-horizon bonuses are where plain RL fails, and the project's long-horizon item effects look like the same problem.

Where the analogy breaks:
- **Self-play has no analogue.** TD-Gammon, ByteRL, Pluribus and Metamon's later stages use opponents that improve automatically. Here the opponent is fixed, which removes non-stationarity but also the automatic curriculum. Difficulty levels could partly stand in, as a guess.
- **No human corpus.** Suphx (44M expert pairs), Metamon, and 17lands all rely on large human data. Logs from the rules player cap imitation at the rules player.
- **Throughput.** 2048 and Dominion results assume a simulator thousands of times faster.
- **Rating versus win rate.** Ladder results include matchmaking effects. This project's direct win rate is cleaner but needs more runs to detect small gains than a rating system suggests.
- **Perfect information.** The solitaire rollout result is not stochastic in the relevant sense. Suphx's hidden hands differ from hidden future shops, since no opponent model is needed here.
- **Configuration spread.** 11 characters and 8 difficulties mean up to 88 cells. NetHack roles and Dominion kingdoms both show strength varying widely by configuration, and per-configuration training would divide an already small budget.

### Gaps
- None of these methods has been tested on Cursed Words, and I did not inspect the project's code for this note. Decisions per run, which determine how far a run budget stretches for TD-style updates, were not measured here.
