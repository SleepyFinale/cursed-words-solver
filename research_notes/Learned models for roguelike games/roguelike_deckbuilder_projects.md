# Learned and search-based bots for roguelike deckbuilders and run-based build games

Researched 2026-11-05. Evidence grades used throughout:

- **[3P]** measured by a third party (a benchmark or paper that ran the bot, or tested models itself).
- **[AR]** author-reported, with artefacts that make it checkable (fixed seed lists, weights, run reports). Nobody independent has replicated these, as far as I could find.
- **[AC]** author claim with no evidence I could inspect.

Most numbers came through a page-summarising fetch tool, not my own reading of the code. The exception is the AscensionAI write-up and the Malmo thesis, whose text I extracted and read directly. I did not run any of these projects.

## Slay the Spire: which bots exist, how strong are they, and did learning beat rules?

### Takeaway
The strongest non-LLM result is sts-ironclad-agent: 50.1% A20 Heart wins over 501 real-game runs (author-reported, unreplicated). It uses a distilled network for all out-of-combat choices and simulator search for combat. End-to-end PPO, by contrast, has no recorded wins at A0 after 16,900+ games, and six attempts to replace combat search with a learned model all failed. Learning has helped when it sat on top of a strong search engine and handled only run-level choices.

### Cited Findings

**Strength table** (win rate means a full run win; check the difficulty column, because these are not comparable across rows)

| Project | Game / difficulty / character | Method | Result | n | Grade | Date |
|---|---|---|---|---|---|---|
| [sts-ironclad-agent](https://github.com/destire-mio/sts-ironclad-agent) | StS1 A20 + Heart, Ironclad, real game | Frozen network distilled from a teacher, search for combat | 50.1% (95% CI 45.7-54.5) | 501 | AR | Reports dated 2026-10-01 |
| same, simulator | StS1 A20 + Heart | Distilled student | 50.2%; teacher 50.1% (dev block), 49.5% (fresh block) | 1,000; 2,000; 1,000 | AR | 2026 |
| [sts-rl-agent](https://github.com/Jialeiv/sts-rl-agent) | StS1 A0 Ironclad, simulator | REINFORCE out of combat, MCTS combat | 14% and floor 42.5 at 50,000 sims; 4% and floor 38.5 at 2,000 | 50 seeds | AR | Undated |
| same, baseline | StS1 A0 Ironclad | Stock heuristics, MCTS combat | 6% and floor 31.2 at 50,000 sims; 2% and floor 22.8 at 2,000 | 50 seeds | AR | Undated |
| [bottled_ai](https://raw.githubusercontent.com/xaved88/bottled_ai/main/docs/winrates.md) | StS1, ascension not stated | Rules plus combat graph search | Watcher 52%, Silent 40%, Defect 33%, Ironclad 20% | 48-52 per character | AR | Oct 2024 |
| bottled_ai at A20 | StS1 A20 Ironclad | Same | Act 1 win 20%, 0.20 acts cleared, mean floor 11.3 | 10 | 3P ([SpireBench](https://arxiv.org/html/2610.12596v1)) | Oct 2026 |
| [AscensionAI](https://justinochan.github.io/AscensionAI/AscensionAI_Technical_Writeup.pdf) | StS1 A0 Ironclad, live game | BC then PPO for everything except shops | No recorded victory; best eval floor 42; PPO 15.44 avg floor vs heuristic 15.78 | 200-game eval, 16,900+ training games | AR | June 2026 |
| [sts2-rl-research](https://github.com/shuchi-lab/sts2-rl-research) | StS2 A2 Ironclad, emulator | Two learned agents (battle, choice) | 26.6% (68/256); replay 26.95% (69/256) | 256 seeds | AR | Undated |
| [STS2FableBot](https://slaythespire.dev/projects/sts2-fable-bot/) | StS2 A0, A1, real game | Search plus hand-coded scoring | 20.7% (CI 16-25); 19.4% (CI 14-25) | 343; 175 | AR | Undated |
| [sts2-rl-agent](https://slaythespire.dev/projects/sts2-rl-agent/) | StS2 Act 1 combats only, Ironclad | MaskablePPO | "about 92%" combat win rate, no baseline or n | not stated | AC | Undated |
| [Epoch SpireClimb](https://epoch.ai/publications/ai-systems-are-improving-rapidly-at-slay-the-spire-and-its-sequel) | StS1 A20 Heart, all characters | LLMs via computer use | GPT-6.1 Sol 20%, GPT-6 Astra 17%, Claude models 0% | 15 per character | 3P | 2026-10-14 |
| [SpireBench](https://arxiv.org/html/2610.12596v1) | StS1 A20 Ironclad | 20 LLMs | Best 1.60 acts cleared; one Heart kill across models (GPT-5.6 Sol) | 10 seeds each | 3P | Oct 2026 |

**Projects with no reported strength**
- [AlphaStS](https://github.com/MANGO1234/AlphaStS): AlphaZero for single fights, default Gremlin Nob with the starter deck. It reports no win rates, and its training section reads "Todo".
- [AutoClad](https://github.com/benmuth/AutoClad): supervised imitation of a baseline agent on Jaw Worm fights, with no metrics.
- [STS-AI-Master](https://slaythespire.dev/projects/sts-ai-master/): RL with headless multi-process training, no results.
- [conquer-the-spire and decapitate-the-spire](https://slaythespire.dev/projects/): simulators for RL. The second is Exordium only and a work in progress.
- [Spire Pilot](https://www.spirepilot.com/): an A20 Ironclad review mod. The landing page gives no method or win rate. A search snippet described a win-probability network and a "card joins only if the run wins more often with it" rule, which I could not confirm on the page.

**Did learning beat rules?**
- Yes, against a weak baseline: sts-rl-agent's learned out-of-combat layer gained "~11 floors" over stock heuristics, and those heuristics chose the map at random ([sts-rl-agent](https://github.com/Jialeiv/sts-rl-agent)).
- No: AscensionAI's strongest published checkpoint (5,146 PPO games, 15.44 avg floor, 31.1% boss conversion) "nearly matched" the heuristic's 15.78 floor but trailed it on boss conversion. The 12,088-game checkpoint regressed to 14.83 floor and 21.7% boss conversion ([AscensionAI](https://justinochan.github.io/AscensionAI/AscensionAI_Technical_Writeup.pdf)).
- Unclear: sts-ironclad-agent never says whether its P300 teacher was hand-written or learned. Only the "reinforcement-learning" topic tag and the fork lineage hint at it. The README names "stage value tables the teacher reads" ([sts-ironclad-agent](https://github.com/destire-mio/sts-ironclad-agent)). An index page does say the teacher was trained in the simulator ([slaythespire.dev](https://slaythespire.dev/projects/sts-ironclad-agent/)), but that is not stated in the README text I saw.

**Caveats the authors state themselves**
- sts-ironclad-agent: parity with the real game is marked `INCOMPLETE`, the locked 1,024-unseen-seed acceptance run "has not been run", and fresh builds should be treated as unmeasured until re-run. The 501 games include 28 terminal results from rerunning 34 bridge-faulted seeds, and 6 seeds still faulted ([sts-ironclad-agent](https://github.com/destire-mio/sts-ironclad-agent)).
- sts-rl-agent: its numbers apply only to the original A0 Ironclad track, on single runs with no confidence intervals. Its difficulty ladder falls to floor 25.7 and 0% wins at A20 ([sts-rl-agent](https://github.com/Jialeiv/sts-rl-agent)).
- bottled_ai: the docs say samples are small, for example Ironclad's 20% has a 95% CI of about 8.9-31.1%, and ±3% would take about 1,000 games per character ([bottled_ai winrates](https://raw.githubusercontent.com/xaved88/bottled_ai/main/docs/winrates.md)).

**Hidden information in combat search**
- sts-rl-agent says its MCTS rollouts use the true future draw order, so the search teacher effectively sees the future, which a one-frame policy cannot. Its real-game path uses a companion mod that exports exact RNG state and restores it into the simulator ([sts-rl-agent](https://github.com/Jialeiv/sts-rl-agent)).
- sts-ironclad-agent's README contains no mention of RNG, draw order or hidden information, so its stance is undocumented in what I read ([sts-ironclad-agent README](https://raw.githubusercontent.com/destire-mio/sts-ironclad-agent/main/README.md)).
- Two projects explicitly exclude this. STS2FableBot has no hidden map content, RNG or save-scumming ([slaythespire.dev](https://slaythespire.dev/projects/sts2-fable-bot/)). sts2-rl-research aims to play "without knowing the future" ([sts2-rl-research](https://github.com/shuchi-lab/sts2-rl-research)).

**Human and LLM reference points**
- All-player Mega Crit telemetry at A20 Ironclad: 0.73 acts cleared, Act 1 win 47%, over 206,082 runs. Baalorlord: 2.98 acts over 687 runs ([SpireBench](https://arxiv.org/html/2610.12596v1)).
- Top human win-rate lines are 85% on StS1 A20 Heart and 95% on StS2 A10. XecnaR reportedly reaches 80-95% depending on character ([Epoch](https://epoch.ai/publications/ai-systems-are-improving-rapidly-at-slay-the-spire-and-its-sequel)).
- Earlier LLM work includes Orak (Gemini 2.5 Pro beat the second boss in 2 of 3 runs, per [Epoch](https://epoch.ai/publications/ai-systems-are-improving-rapidly-at-slay-the-spire-and-its-sequel)) and AgenticSTS (StS2 A0, 3/10 wins rising to 6/10 with a skill library, per [slaythespire.dev](https://slaythespire.dev/projects/)).

### Inferences
- The sts-ironclad-agent result is the most important item here and also the one most in need of checking. If its combat search reads the true RNG, as its parent project's did, then 50.1% is not an honest-information result. The bots that explicitly refuse hidden information sit near 20-27%, though at much lower difficulty and in StS2. That difference could be the game, the method, or the information.
- sts-rl-agent's 14% vs 6% is weak on win rate alone. My Wilson intervals on 7/50 and 3/50 are about 7-26% and 2-16%. The floor gain (42.5 vs 31.2) is the stronger signal. The seeds are paired, but no paired test is reported.
- Search budget was as large a lever as the learned layer in sts-rl-agent: 2,000 to 50,000 sims took wins from 4% to 14%, and floors from 38.5 to 42.5.
- sts-ironclad-agent's stated speed of about 1 minute per game per core works out to roughly 11,500 games a day on 8 cores. That is the same order as this project's 5,000-20,000 runs a day. Its training volume is unknown (the "cloud runs c5-c52" suggest it was large), so this shows evaluation is affordable, not that training is.
- bottled_ai's ascension is unstated, but SpireBench's A20 numbers are far below its doc figures, so the 20-52% range is very likely a low-ascension result.

### Gaps
- Whether sts-ironclad-agent's combat search sees future draws or RNG state, how its teacher was built, and how many games training took. The README does not say; the repo's `combat_engine/combat4r` and `sim_patch` code would answer the first question.
- I found no independent replication of any non-LLM win rate other than SpireBench's 10-run bottled_ai test.
- AlphaStS has no published strength, and I could not find a write-up or date for it.
- Reddit could not be fetched at all, so r/slaythespire claims are not covered. I did not watch the [YouTube video](https://www.youtube.com/watch?v=PgFjo4RL6kA) that came up in search.

## Balatro: which RL or search agents exist, what did they reach, and what was learned versus scripted?

### Takeaway
No pure RL agent has beaten Balatro reliably: leaving aside an unverified 20% claim, the best figure with any evidence is 2.35% wins at peak, with an unspecified stake. A non-learning planner reached about 20% on White Stake, and an LLM with exact numeric tools has two documented Black Deck / Gold Stake wins but no measured rate. The authors who diagnose the problem point at the shop and economy, and at exploration rather than network size.

### Cited Findings

| Project | Setting | Method | Result | n | Grade |
|---|---|---|---|---|---|
| [balatro-gym](https://github.com/roshantaneja/balatro-gym) | White Stake, Red Deck | Planner (no learning) | 20% (47/240), mean ante 6.2, about 60 s/episode | 240 | AR |
| same | White Stake, Red Deck | Lookahead planner | 20% (24/120), mean ante 5.9, about 480 s/episode | 120 | AR |
| same | White Stake, Red Deck | Strategist; greedy heuristic; random | 5% (ante 4.5); 0% (ante 3.5); 0% (ante 1.0) | 100 | AR |
| [taggarttufte/balatro-rl](https://github.com/taggarttufte/balatro-rl) | Stake not reported | Hierarchical PPO (V7), custom sim | Peak 2.35% (last-50 window); V6 1.9% on random seeds; random under 0.01% | 32.8M steps | AR |
| [Balatron](https://github.com/jarmstrong158/Balatron) | White Stake target, live game | PPO, planner, heuristics | About 0.5%; "competent through the early antes", wall at antes 5-8 | about 500-game sample | AR |
| [balatro_rl](https://github.com/stratosfearwashere-create/balatro_rl) | Gold Stake, Red Deck | BC + DAgger + PPO | 5.94 of 24 blinds, mean ante 2.56, 0 wins; rules 5.52 and 2.39; BC 5.47 and 2.41 | 100 seeds | AR (old sim, "need retraining") |
| [Attol8/balatro-ai](https://github.com/Attol8/balatro-ai) | Black Deck, Gold Stake | LLM plus exact Python tools | Two fresh-seed wins (435,408/400,000 and 420,305/400,000); "not a measured win rate" | 2 published wins | AR |
| same, baselines | Red/White, fixed panel | Non-model policies | Best won 3 of 20 | 20 | AR |
| Fruit fly brain model | "Easiest difficulty", standard deck | RL via a trainer algorithm, on Google's connectome | 20% success rate, training ongoing | not stated | AC ([Tom's Hardware](https://www.tomshardware.com/tech-industry/artificial-intelligence/balatro-fan-claims-they-trained-google-fruit-fly-brain-simulation-to-beat-the-game-reinforcement-learning-currently-has-the-model-at-20-percent-success-rate), only the headline loaded; details are from a search summary of a Reddit post) |
| [BalatroBench](https://balatrobench.com/about.html) | Leaderboard | LLM tool-calling via BalatroBot | Ranked on average final round; about page has no numbers | not stated | Not checked |
| [Lihao Zhu thesis, ULL](https://riull.ull.es/xmlui/handle/915/42694) | Prototype | PPO (SB3), screenshots vs mod APIs | No results in the abstract | none | No results (2025) |
| [jackdaw-balatro](https://github.com/TylerFlar/jackdaw-balatro) | Simulator | Rust engine, MaskablePPO demo | No agent results in README | none | No results |
| [balatro-rl-project](https://github.com/ANaughton04/balatro-rl-project), [balatro-run-analysis](https://github.com/WilliamMorgan73/balatro-run-analysis) | Jackdaw-based | RL; shop-only RL dashboard | No numbers seen (the second page timed out) | none | No results seen |

**What failed, in the authors' words**
- balatro-rl: V5's dual agents starved the shop, whose head got under 0.1% of steps, and the result was 0%. Reward retuning and a 5.5x network (13.6M params) both stayed near 2.0-2.35%. Self-play gave about 0%. The author concludes the ceiling is exploration or search-bound rather than capacity-bound, and suggests MCTS with a learned prior ([balatro-rl](https://github.com/taggarttufte/balatro-rl)).
- Balatron: a reactive policy "reaches ~ante 4 and stalls", and exploration, curriculum, reward shaping and a relational encoder did not push past it. The current system adds a build planner, but still wins only about 0.5% ([Balatron](https://github.com/jarmstrong158/Balatron)).
- balatro_rl: PPO "started getting worse after about 125 iterations" because of a too-strong entropy bonus. Nothing there "beats Gold Stake out of the box". An AlphaZero-style unified agent with a Monte Carlo round solver exists but has no reported results ([balatro_rl](https://github.com/stratosfearwashere-create/balatro_rl)).
- balatro-gym: about half of planner losses never found a multiplicative joker, and losing runs averaged pair level 4.6 vs 10.5 for winners. Starting with $100 instead of $4, the same agent wins 57% ([balatro-gym](https://github.com/roshantaneja/balatro-gym)).

**Reference points**
- balatro-rl and Balatron cite skilled human clear rates of about 70% and about 85% respectively. These are author reference points, not measurements ([balatro-rl](https://github.com/taggarttufte/balatro-rl), [Balatron](https://github.com/jarmstrong158/Balatron)).
- Attol8 used an all-unlocked profile and says reliability "remains unmeasured". Tom's Hardware covered the bot, but only its headline loaded for me ([Attol8](https://github.com/Attol8/balatro-ai), [Tom's Hardware](https://tomshardware.com/tech-industry/artificial-intelligence/ai-enthusiast-builds-gpt-6-astra-powered-bot-to-take-on-balatros-gold-stake-black-deck-bot-leverages-python-for-numerical-tools-beats-hardest-difficulty-repeatedly)).

### Inferences
- In Balatro, hand-built planning beat tens of millions of RL steps: 20% vs 2.35%. The settings differ (the sims differ and balatro-rl reports no stake), so this is suggestive rather than a clean comparison.
- The $4 vs $100 result (20% vs 57%) suggests much of the loss is an economy and build-order problem. This resembles the shop and item decisions in Cursed Words, though the mapping is my own judgement.
- balatro_rl's pattern (BC roughly equals its teacher, PPO adds a small gain, zero wins) looks very like this project's +0.15 score with no extra wins.

### Gaps
- BalatroBench's actual leaderboard numbers. A search snippet attributed to a Hacker News comment says one model beat ante 8 in 9 of 15 attempts, but I did not verify this.
- Jackdaw's MaskablePPO demo results sit in its `examples/` folder and [RL guide](https://tylerflar.github.io/jackdaw-balatro/rl-guide), which I did not open.
- `balatro-shop-rl` returned 404, so the fork's Q-learning shop agent and its "hand-written shops for the play-policy ceiling test" ([PR #20](https://github.com/WilliamMorgan73/jackdaw-balatro/pull/20)) have no results I could read. This is the closest project to a shop-versus-play decomposition and is worth a direct look.
- I found no peer-reviewed Balatro RL paper. The fruit fly claim has no replication.

## Others: Monster Train, Inscryption, Griftlands, Luck be a Landlord, Vampire Survivors-style, research environments and theses

### Takeaway
Almost nothing with results exists outside StS and Balatro. Inscryption has one battle-only PPO agent with a real held-out test, Super Auto Pets has several projects with no published strength, and I found nothing for Monster Train, Griftlands, Luck be a Landlord or Vampire Survivors.

### Cited Findings
- **Inscryption (Kaycee's Mod):** PPO against a hand-written engine. v1.1 won 87% of 54 trained encounters and 73% of 12 held-out ones, against 9.9% and 7.4% for random, after 20,000 batches. v1.0's 95.7% was measured on its own training set. Map traversal is out of scope, called "a much harder problem" ([Inscryption-ML-Model](https://github.com/Andre-PSa/Inscryption-ML-Model)). AR, undated.
- **Super Auto Pets:**
  - [sap-agent](https://github.com/endodod/sap-agent): Maskable PPO with a pool of 500 opponent teams. Evaluates over 10,000 episodes, but the README shows no values.
  - [esterRozen/SuperAutoPetsAI](https://github.com/esterRozen/SuperAutoPetsAI): DQN complete, others in progress, no results.
  - [augustomklee/super-auto-pets-ai](https://github.com/augustomklee/super-auto-pets-ai): RL plus vision, no numbers seen.
- **Research environments (StS):** [sts_lightspeed](https://slaythespire.dev/projects/) is the shared base for several projects, with 1M playouts in 5 s on 16 threads; it fully implements only Ironclad ([sts-rl-agent](https://github.com/Jialeiv/sts-rl-agent)). [sts2-cli and sts2-sim](https://slaythespire.dev/projects/) target StS2.
- **Benchmarks:** [Orak](https://arxiv.org/pdf/2506.03610) covers 12 games including StS. [typed-decision](https://slaythespire.dev/projects/typed-decision/) fine-tuned small models on 39,884 search-bot decisions, raising mean floor from 14.1 to 19.5 and from 10.4 to 17.1 on 200 A0 seeds.
- **Theses:** [Porenius and Hansson, Malmo 2021](https://www.diva-portal.org/smash/get/diva2:1565751/FULLTEXT02) (details in the community data section), and [Zhu, ULL 2025](https://riull.ull.es/xmlui/handle/915/42694) (no results).
- **Adjacent CCG drafting:** Vieira et al. studied RL for arena drafting in Legends of Code and Magic, reporting learned drafts that outperformed the game's best agents ([SBGames 2020](https://www.sbgames.org/proceedings2020/ComputacaoFull/209690.pdf)). Search summary only; I did not read the paper.

### Inferences
- The absence is informative: anyone starting on these games would have no strength reference, and a simulator is the main barrier. This project's faithful simulator already puts it ahead of most of the efforts surveyed.

### Gaps
- Monster Train, Griftlands, Luck be a Landlord and Vampire Survivors: no learned or search bots found in two searches. Absence from search is not proof, since mod forums and Discords were not reachable.
- Inscryption's state/action design, sample count and speed are in `1.0/README.md` and `1.1/DESIGN.md`, which I did not open.

## Per-project details: state, action, simulator speed, samples, compute, measurement

### Takeaway
Live-game training runs hundreds to thousands of times slower than simulators (7 steps/s at best for Balatron vs 1,000-180,000 for Balatro simulators) and has produced no strong agent. The best-documented learned run-level layer is a small candidate scorer, while bigger networks did not break plateaus where they were tried. The strongest project does not document its representation.

### Cited Findings

| Project | State | Action | Speed | Samples and compute | How measured |
|---|---|---|---|---|---|
| [sts-rl-agent](https://github.com/Jialeiv/sts-rl-agent) | 412-d sim obs + 368-d candidate descriptor | Scores each legal candidate, takes argmax; MLP [128,128], about 100k params, under 2 MB | Not stated | 12-worker REINFORCE; example run "~10 min on a laptop, 12 cores"; weights file labelled `15k`, meaning not stated | 50 fixed held-out seeds, single runs, no CIs |
| [sts-ironclad-agent](https://github.com/destire-mio/sts-ironclad-agent) | Not stated | Not stated | About 1 minute per game per core | Not stated; "cloud runs c5-c52" | Fixed seeds, no reseeding or retries, fresh block for real game |
| [AscensionAI](https://justinochan.github.io/AscensionAI/AscensionAI_Technical_Writeup.pdf) | 717-d flat | 134 discrete, masked; 571K params | 30-100 s/game; 110-200 games/hour on 4 workers (live game) | 16,900+ PPO games, 1,856+ updates; about 200 BC games (30k-60k transitions); Ryzen 9800X3D, then 22 vCPU GCP spot VM | 200-game fixed-seed greedy eval |
| [sts2-rl-research](https://github.com/shuchi-lab/sts2-rl-research) | Semantic card encoding, hand lethality, mechanism features | Not stated | Not stated | Not stated; cloud infra omitted from release | 256 retained seeds, replayable |
| [sts2-rl-agent](https://slaythespire.dev/projects/sts2-rl-agent/) | 131-d | Masked | About 1,200 combats/s | Not stated | Not stated |
| [bottled_ai](https://github.com/xaved88/bottled_ai) | Hand features; "about 40 different values" in a combat scorer | Prioritised lists, combat graph traversal | Live game | No training | About 50 random seeds per character |
| [balatro-rl](https://github.com/taggarttufte/balatro-rl) | 434-d (V7) | Intent head, then 218 card subsets scored from 8 card scores; Discrete(17) elsewhere | About 1,000-1,535 steps/s | 32.8M steps for the best run; 6 V7 runs about 80 hours; 7950X + 3080 Ti | Last-50 window (very noisy) |
| [Balatron](https://github.com/jarmstrong158/Balatron) | 842-d (blurb says 850), attention over jokers | 14 action types x 19 targets | 196-433 steps/min (live game; README also says about 5,000 steps/hour) | Log line at step 814,922; 9800X3D CPU | Conditional advance rates with Wilson CIs, unpublished |
| [balatro_rl](https://github.com/stratosfearwashere-create/balatro_rl) | Pointer network input, about 0.4M params | 476 | Not stated; about 250 decisions per run | Demo on 2 CPU cores (27 min BC, 22 min PPO) | 100 unseen seeds, greedy |
| [balatro-gym](https://github.com/roshantaneja/balatro-gym) | Cloneable JSON state | Flat Discrete(3519), masked | About 6,000 engine steps/s, about 1,000 env steps/s per core | No trained-policy results | 100-240 seeds |
| [jackdaw](https://github.com/TylerFlar/jackdaw-balatro) | Gym wrapper | Masked | About 180,000 steps/s single; over 1M/s on 8 threads (self-reported, no hardware given) | None | Lockstep validated on 200 organic games |

**Stated failures in the StS projects**
- sts-rl-agent's six learned-combat attempts: BC of MCTS (accuracy conflicting at 0.44 and 0.59, floor about 12), DAgger (no gain), REINFORCE fine-tune (floor about 12), attention scorer (floor about 14), value net with 1-ply lookahead (floor about 8), and policy/value-guided PUCT (loses to blind MCTS at equal budget, "26.7 vs 33 @100 sims") ([sts-rl-agent](https://github.com/Jialeiv/sts-rl-agent)).
- sts-rl-agent's author explains this by saying judgment decisions compress into small networks, while planning-type combat needs an AlphaZero-style loop ([sts-rl-agent](https://github.com/Jialeiv/sts-rl-agent)).
- AscensionAI: exploration valley after boss shaping, PPO forgetting BC, and a reversed BC-anchor decision. Its Path 2 diagnosis was that the policy could not observe its actual deck (only a 20-d aggregate) and did not control removals or upgrades: "reward shaping alone was the wrong lever" ([AscensionAI](https://justinochan.github.io/AscensionAI/AscensionAI_Technical_Writeup.pdf)).
- AscensionAI after adding the deck vector: avg floor about 12-13, with no behaviour improvement yet as of the write-up ([AscensionAI](https://justinochan.github.io/AscensionAI/AscensionAI_Technical_Writeup.pdf)).
- SpireBench: LLMs misjudge risk by preserving HP rather than spending it to grow stronger, reaching the Act 1 boss at a median 90% HP vs 53% for streamers. Memory banks did not help, and 17% of stored memories were false ([SpireBench](https://arxiv.org/html/2610.12596v1)).

### Inferences
- Candidate scoring (one score per legal option, about 100k params) is the design of sts-rl-agent, whose successor reached the best result, although that successor's own network design is not documented. Flat 134-way (AscensionAI) action heads have no comparable result, and balatro-gym's 3519-way space has no trained results at all. This is a pattern across few projects, not a controlled test.
- Network size has not been the constraint anywhere it was tested: balatro-rl's 5.5x network and AscensionAI's upgrade both failed to break their plateaus.
- At 5,000-20,000 runs a day, this project passes AscensionAI's total of 16,900 games within days. sts-rl-agent's example training run took about 10 minutes on a laptop, and its weights file is labelled `15k` (meaning not stated). Run count alone is unlikely to be the main limit, though sts-ironclad-agent's unknown training volume could change that view.

### Gaps
- Most projects give no total sample count or cost. sts-ironclad-agent's silence here matters most.
- Few projects report per-decision-type results, so the value of each lever is rarely isolated.

## Combat or tactical play versus run-level decisions: which was learned and which scripted?

### Takeaway
The only strong StS hybrids keep combat as search and learn run-level choices. In Balatro the split is close to the reverse: exact scoring is scripted and the build (the shop) is the hard part, and planners do better there than policies.

### Cited Findings

| Project | Combat / tactical | Run-level (card, shop, path, rest) | Result |
|---|---|---|---|
| [sts-ironclad-agent](https://github.com/destire-mio/sts-ironclad-agent) | Search (`sims32`, extra boss budget, subtree reuse) | One frozen distilled network for all of it | 50.1% A20 Heart |
| [sts-rl-agent](https://github.com/Jialeiv/sts-rl-agent) | MCTS | Learned scorer | 14% A0 |
| [sts2-rl-research](https://github.com/shuchi-lab/sts2-rl-research) | Learned battle agent | Learned choice agent | 26.6% StS2 A2 |
| [AscensionAI](https://justinochan.github.io/AscensionAI/AscensionAI_Technical_Writeup.pdf) | PPO | PPO, with shops heuristic and removal/upgrade learned only from June 2026 | No wins at A0 |
| [bottled_ai](https://github.com/xaved88/bottled_ai) | Graph search and hand-tuned scorer | Priority lists | 20-52%, ascension unstated |
| [STS2FableBot](https://slaythespire.dev/projects/sts2-fable-bot/) | Search + hand scoring | Search + hand scoring; ML only as offline evaluators | 20.7% StS2 A0 |
| [AlphaStS](https://github.com/MANGO1234/AlphaStS), [AutoClad](https://github.com/benmuth/AutoClad), [Inscryption](https://github.com/Andre-PSa/Inscryption-ML-Model) | Learned | Not handled | No full-run results |
| [Balatron](https://github.com/jarmstrong158/Balatron) | Exact scoring and legality scripted; PPO for play vs discard | Planner proposes builds; PPO for tempo, reroll, skip, and distils planner picks | About 0.5% |
| [balatro-rl](https://github.com/taggarttufte/balatro-rl) | Learned, including discard timing (about 30% of hand actions) | Learned under an engineered shop reward; locked into one joker combo | 2.35% peak |
| [balatro-gym](https://github.com/roshantaneja/balatro-gym) | Planner scoring on cloned boards | Planner | 20% White |
| [Attol8](https://github.com/Attol8/balatro-ai) | Python scoring advice, LLM chooses | LLM | 2 Gold Stake wins |

- On run-level vs combat importance, SpireBench's top models were strong in combat (never missed lethal, 8.2 damage per hallway fight vs 14.0 for the bottom tier) but still fell well short of streamers in Acts 2-3, which the authors tie to run-level risk calibration ([SpireBench](https://arxiv.org/html/2610.12596v1)).
- sts-ironclad-agent's largest single loss point is the Heart at 21.3% death among those reaching it, followed by Act 2 path at 10.3%, Act 3 bosses at 9.3% and Act 1 path at 9.1% ([sts-ironclad-agent](https://github.com/destire-mio/sts-ironclad-agent)).
- Its README describes combat search as the only part that stays classical ([sts-ironclad-agent](https://github.com/destire-mio/sts-ironclad-agent)).

### Inferences
- The StS evidence supports a hybrid split of fixed tactical engine plus learned run-level layer. The closest analogue here is that Cursed Words' word-play solver is the tactical engine and the shop, item and pin choices are the run-level layer, which is my mapping and not something any source tests.
- As described in the brief, the current move-override model acts on the tactical layer, which is the layer these projects found hardest to improve by learning. That is a direct reason to test a run-level layer next. This is an inference from other games, and the Cursed Words word solver may leave different room for improvement.
- sts2-rl-research is the one counter-example with both layers learned and a respectable result. Its method, sample count and cloud compute are withheld, so it cannot yet be used as a recipe.

### Gaps
- No project isolates run-level value by swapping layers at high difficulty. sts-rl-agent did this only at A0 on 50 seeds. The jackdaw fork's "play-policy ceiling test" with hand-written shops looks designed for this, but no results were available.

## Community data: did anyone use human run logs, and how useful was it?

### Takeaway
Yes, but only for predictors and small advisors, never as the basis of a strong bot. Every strong or improving agent I found learned from its own simulator or from a search teacher, not from human logs.

### Cited Findings
- **Slay-I fight predictor:** trained on "over 325,000 fights" from Spire Logs and Jorbs. It predicts damage "generally within +/- 7 HP" and scores card changes by average damage saved. It has no reported validation split and no measured effect on win rate ([SlayTheSpireFightPredictor](https://github.com/alexdriedger/SlayTheSpireFightPredictor)).
- **Porenius and Hansson (Malmo, 2021):** ANN predicting victory from a path, deck and relics, trained on 172,203 rows of developer-gathered player data, with 43,051 validation and 53,814 test rows. Accuracy 0.8052, loss 0.2455, one epoch. A separate analysis of 1,008,636 runs (10.186% wins) examined room types ([thesis](https://www.diva-portal.org/smash/get/diva2:1565751/FULLTEXT02)).
- The thesis's paired user study claims the ANN "outperform[ed]" unassisted humans in all three cases, on one run per participant at Ironclad A0. One participant called the AI "too reckless", because it never routed around elites at low HP ([thesis](https://www.diva-portal.org/smash/get/diva2:1565751/FULLTEXT02)).
- **LearnTheSpire (2018):** card-pick network on the author's own 42 runs, with 79.5% accuracy measured on the training set. The author warns about overfitting ([LearnTheSpire](https://github.com/kaijchang/LearnTheSpire)).
- **Fox Row (2020-12-14):** analysed about 18 million 2020 runs from a 75M+ run, 380 GB developer dump. It found a 9% overall win rate and enemy lethality, but no card-level results ([Fox Row](https://foxrow.com/slay-the-spire-statistical-analysis)).
- **Telemetry as a yardstick:** SpireBench uses 206,082 Mega Crit runs for human baselines. It also found that agreement with human card picks barely rises with model strength (Spearman ρ = 0.16), and human games are not seed-matched ([SpireBench](https://arxiv.org/html/2610.12596v1)).
- **Community stats sites:** [Spire Codex and better-run-logs](https://slaythespire.dev/projects/) offer run statistics and logs for simulator test cases. No bot is reported as using them for strength.
- **Bot-generated data worked in one case:** typed-decision's 39,884 search-bot decisions lifted small models by 5.4 and 6.7 floors ([typed-decision](https://slaythespire.dev/projects/typed-decision/)).

### Inferences
- The thesis's 0.8052 accuracy sits below the 90% you would get by always predicting "loss" on a set that is 10% wins, if the test set kept that mix. So it may be no better than the base rate. That, plus a sample of three pairs, means the study does not show strength.
- SpireBench's ρ = 0.16 is a warning against using agreement with human picks as a proxy for strength.
- This project's own simulator data, with randomised decisions, is likely worth more than human logs for causal questions, because logs carry strong selection effects. Fox Row's note that play time correlates with winning without causing it is one example. This is a judgement call, and no source tests it directly.

### Gaps
- I found no Balatro project trained on human logs.
- No project measures how much human-derived priors or tier lists add to a bot's win rate. I found no test of tier-list statistics as a bot prior.
- Whether Spire Logs data is still accessible was not checked.
