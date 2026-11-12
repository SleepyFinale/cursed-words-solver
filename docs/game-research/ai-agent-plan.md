# Self-learning Cursed Words agent + run assistant: plan (2026-11-09)

Goal (user, 2026-11-09): an AI that **learns by itself** to win runs consistently on every
character, crown and quest, beats Michael, uses **only information a human player has**, can
take **every action a human can**, and is then wired into the solver as a live run assistant.
Everything must be **pausable and resumable** with minimal loss. GPU use where it helps.

Companion docs: [ai-roadmap.md](ai-roadmap.md) (levers tried so far), [sim-game.md](sim-game.md)
(simulator + every benchmark), `reports/Learned models for roguelike games.md` (prior research).

---

## 1. Where we start (facts measured 2026-11-09)

| Thing | State |
|---|---|
| Simulator | `sim/game`: decompile-faithful full run, all items, crowns 0-8, 26 quests, Michael phases. 149/149 captures score exactly. |
| Best AI | Rules player + `Curse` build plan (Chess for Sam Gambit / Human Boy) + LightGBM override. **~38% wins** over crowns 0-7 (528 pairs), 43/66 at crown 0 down to 6/66 at crown 7. Rodman 9/48, Sandy 8/48 worst. |
| What failed | On-policy value models, ridge / tree advantage models on one-move randomised trials (≈ level), per-item value tables, pin rollouts. Strength so far came from **whole-run plans**, not learned move scores. |
| Speed | 100-170 s CPU per long run (≈12-13 s wall at 8 workers, ~7k runs/day). **97% is word search, ~85% of searches are policy probes** (shop "power" probes, boss strength, rack placement), not the words actually played. Engine is pure Python + numpy. |
| Hidden-info leaks | (1) `plan_scores` (on in `tuned_config`) applies reroll / next-grid candidates **before reseeding** → peeks at the real next grid. (2) `clone()` carries the **pre-rolled future boss drafts** of floors 2-5 into rollouts. (3) Policies get the whole `Game` object. A human-only agent needs these closed. |
| Possible regression | Wet Dennis c0 seed 8010001: after buying Oden, five submits score ~0 and the run dies at stage 2 (was stage 5 on 2026-10-31 code). Must check before any training. |
| Live data | melmod `game_state/1` already exports almost every input on the user's list (grid, targets, grids left, rerolls, stage/node, boss draft + cursed flags, money, stickers/stamps + levels, consumables, fairies, shop offers + frozen + restock price, frozen items outside the shop, pin levels). **Missing:** Michael draft options, a "decision type" field for boss-draft / pin / Michael screens, and auto-export on freeze / node change. `importer.game_from_game_state` already rebuilds a sim `Game` from a live export. |
| Hardware | Ryzen 9700X 8 cores, 62 GB RAM, **RTX 5070 Ti 16 GB** (PyTorch 2.11+cu128 installed and tested 2026-11-09). No C/Rust compiler; **numba 0.68.1 installs cleanly** on numpy 2.5.1. |

### Why earlier learning stalled, and what changes now
1. **Budget**: ~7k runs/day is 1-2 orders of magnitude below what self-play learners use.
   Removing probes from the learner's hot path plus a numba search should give **10-30× more
   runs/day** (§3). That is the precondition for real self-learning.
2. **One-move labels under a fixed rules continuation can't value a coordinated build.** The
   new learner controls *every* decision in a run, so a strategy is learned as a whole
   (credit flows through the whole run via a learned value function).
3. **Per-class sparse features overfit.** The new model encodes each item as a **token** built
   from shared descriptors + a small class embedding, so knowledge transfers between items.
4. **Start from the best player we have, not from zero** (behaviour cloning), then let RL move
   away from it. That's how strong game agents avoid the "PPO never wins" trap seen in StS /
   Balatro hobby projects.

---

## 2. Architecture

```
            ┌───────────────── training (resumable, ~/.cursed_words_solver/rl/<run>/) ─────────────────┐
 CPU actors │ 7 processes × CWEnv(sim Game) ── obs/legal actions ──► policy (torch CPU, small)         │
            │        ▲ word candidates from engine (numba)          │ trajectories (npz shards)        │
            │        └──────────── action ──────────────────────────┘                                  │
            │                                     │                                                    │
 GPU learner│  PPO + privileged critic + KL-to-teacher, aux heads ◄──┘   ──► checkpoints, weights.pt   │
            │  eval gate (bench seeds, paired vs champion) ──► champion.pt                              │
            └─────────────────────────────────────────────────────────────────────────────────────────┘
 Live:  game ─melmod─► run_state.json ─► importer ─► CWEnv obs ─► champion policy ─► overlay advice
```

### 2.1 Environment `rl/env.py` (`CWEnv`)
- Wraps `sim.game` `Game`; one step = one human action. Phases: encounter, shop, boss_draft,
  pin_reward, michael_draft (+ "anytime" actions: sell, reorder, discard consumable).
- **Action enumeration covers everything a human can do**, built on `agent.legal_actions` +
  `expert.full_shop_candidates`, extended with: reorder stickers/stamps anywhere, sell anywhere,
  discard consumable tile, Twinkle Toes swap, use-consumable placements, word pick from the
  engine's **top-K words** (K≈12, plus diverse picks: best money / best counter-growth / best
  cursed-tile words, so a "worse but better-long-term" word is available), grid reroll, skip,
  freeze/unfreeze, restock, leave, boss pick, pin side (incl. ID Card both), Michael draft.
  Candidates are capped by cheap heuristics (e.g. consumable placements ranked by a 1-tile
  delta score) so a step never needs dozens of searches.
- **Information boundary** (human-visible only): observations are built from a whitelisted view
  (what melmod exports / the screen shows). Never: RNG state, future boss drafts, unrevealed
  shop stock, next grid. Rollouts used by search/advice **resample hidden state**
  (determinisation: reroll future drafts and RNG from the visible state). Unit test: two games
  that differ only in hidden state produce identical observations.
- Reward: run outcome (stages/encounters cleared, win = 16, Michael win = +8 as now) delivered
  as **potential-based shaping** (Φ = learned/handcrafted progress: encounters cleared +
  fraction of target reached), which doesn't change the optimal policy but gives dense credit.
  Small bonus terms only if they're potential-based too (fairies, cursed-boss streak are already
  captured by the outcome via Michael).

### 2.2 Observation → model (`rl/obs.py`, `rl/model.py`)
- **Item tokens**: every owned sticker / stamp / consumable / fairy / pin and every shop offer
  and frozen item becomes a token: shared descriptors (tags, rarity, cost, generator/payoff role,
  curse flags, from `features.item_descriptors`), level, foil, slot position, visible counters,
  + a 16-d learned class embedding, + a "where" type (owned / shop / frozen / rack).
- **Board tokens**: compact grid summary (letters, tile types, cursed/special flags) and the
  **top-K word candidates** with their exact scores and side effects (money, counters).
- **Global vector**: character, pin levels, crown, quest one-hot + rule flags, stage/node,
  targets now & ahead (×3.8 growth), score so far, grids left, rerolls, money, restock cost,
  Michael route state (cursed bosses beaten), boss draft (both options, cursed flags).
- **Network**: per-token MLP → 2-3 layer transformer encoder (d=128, 4 heads, ~0.5-1 M params)
  → (a) **pointer head**: each candidate action is encoded as a token (action type + referenced
  item/word tokens) and scored against the pooled state → softmax over legal candidates
  (masking illegal ones); (b) value head (policy-side); (c) **privileged critic** (training
  only, may also see hidden state — PerfectDou trick; policy never sees it); (d) aux heads:
  P(clear current encounter), P(beat next boss), final stage reached — cheap supervised signal
  that shapes the representation.
- Training on GPU in PyTorch; inference in actors on CPU torch (single small forward per
  decision ≈ 0.2-1 ms, negligible vs search). A GPU inference server isn't worth it at 8 procs.

### 2.3 Learning stages
| Stage | What | Data / cost | Exit criterion |
|---|---|---|---|
| **A. Behaviour cloning** | Imitate the current best AI (Curse/Chess plan + champion) on every decision; the teacher's chosen action is a label, plus outcome-supervised value/aux heads. Gives a ~38% player that runs **without probes**. | ~8-12k teacher runs (~1-1.5 days CPU, resumable shards) → ~1M decisions | BC policy within −3 win points of the teacher on 528 bench seeds while running 5-10× faster |
| **B. RL self-improvement (PPO)** | Actors play with the current policy (sampled actions, entropy bonus), learner does PPO-clip + GAE(λ=0.95, γ=1 per decision with shaping) + KL penalty to the BC policy that is annealed toward 0 so the agent is free to **discover its own strategies**. Privileged critic for low-variance advantages. Curriculum: sample character × crown × quest weighted toward cells where it loses most. | ~5-30k runs/day after §3 speedups; weeks-scale total, resumable | Paired SPRT gate vs champion on single-use seed blocks; champion only replaced on a pass. Track per-character/crown/quest tables + Michael rate + discovered build archetypes |
| **C. Search-boosted expert iteration** | At high-stakes nodes (boss pick, Michael draft, pin, leave-shop-with-money, big buys), run Gumbel sequential halving over the policy's top candidates using **determinised** clones played to stage end with the value net as leaf; distil the improved choice back into the policy. | rare nodes only (≈5-15 per run) | gate as above |
| **D. Coverage** | Quests (26), crown 8, Michael finale already solved by the solver. Fine-tune on quest mixture. | | per-quest win table |

"Consistently wins" targets (stated before training, to judge against): **M1** beat the current
38% AI by ≥ +5 win points on 2,000 fresh seeds; **M2** ≥ 60% at crowns 0-3 and ≥ 35% at 4-7,
every character ≥ 25%; **M3** quests ≥ the crown-0 rate minus 10 points. These are targets, not
forecasts; the gates report honestly whichever way it goes.

### 2.4 User-specified behaviours and how they're produced
| Behaviour | How |
|---|---|
| Pick among top-X words, not just the highest; lower-scoring word if it grows stickers/stamps; play more grids for money builds | word candidates carry their side effects; policy + value decide (finish-early vs keep farming is learned via the $2/grid economy in the reward) |
| When to reroll (e.g. reroll grid 1 when it can't one-shot; Golden Scales first-grid money) | reroll is a candidate action every grid; the value head sees grid index, Golden Scales, target and best-word score |
| Consumable use valued by scarcity | consumable placement candidates + item tokens for rack and generators owned; value of holding vs using is learned |
| Shop buy / sell / freeze / restock / leave with money | all candidate actions; saving money is "leave"; frozen items persist as tokens in every phase so it "remembers" them |
| Boss pick, prefer cursed when risk is similar | value of each option + reward includes Michael path; **advisor rule on top**: pick cursed if its win estimate ≥ uncursed − δ (δ default 5 points, user-tunable), stop preferring once the cursed streak is broken |
| Pin side (both with ID Card) | pin_reward candidates |
| Sort/sell/discard anytime | anytime actions in every phase |
| Michael's three drafts | michael_draft candidates (needs melmod export, §4) |

---

## 3. Speed plan (precondition for B)
| # | Change | Changes play? | Expected |
|---|---|---|---|
| S1 | Learner never calls probes (`_power`, `boss_strength`, `_best_placement` sweeps); only encounter searches remain | n/a (new player) | **5-10×** per run |
| S2 | numba port of the trie walk: `enumerate` DFS, `enumerate_subsets`, `_np_advance`/`step_letter`, beam stepping, `valid_word`; Python fallback for dynamic inventories / chess / Honeypot | no — differential test on seeded runs + `engine_replay` | 2-3× on the remaining search |
| S3 | scoring micro-opts: per-plan precompute of `variable_letter`/`is_cursed`/`selections`, skip `_fresh` clones when no stateful items | no — same tests | 1.3-1.5× |
| S4 | probe search asks for top-N only (no full exact scoring of 833-2,000 paths) | small; teacher only | 1.2× |
| S5 | optional numba scoring core | no | later, if scoring dominates |

Every speed change ships only with an identical-output check (same seeds, action-for-action).

---

## 4. Run assistant integration
1. **melmod**: add `run_state.decision` (`encounter|shop|boss_draft|pin_reward|michael_draft|cursedle|none`),
   export Michael `ModifierDrafts`/`DraftedModifiers`, add node type + shop offers/frozen +
   restock to the auto-export fingerprint, export shop reroll count.
2. **importer**: map Michael drafts; pass `game_words.txt`.
3. **`assistant/` service in app.py**: on every decision change (auto) or F8: `load_game` →
   `CWEnv` observation → champion policy → ranked actions with value / win% and short reasons;
   optional "deep analysis" (F11) runs stage-C search in a worker pool (cancellable).
   Encounter: engine top-X words re-ranked by the AI + reroll/consumable advice. Shop: ordered
   list of steps (sell X, buy Y, freeze Z, restock?, leave). Boss: both options with risk and
   the cursed-preference rule. Pin, Michael draft likewise. Sticker/stamp order shown when the
   AI would reorder. Frozen items + their cost shown on every screen.
4. Overlay: new advice view in `ResultOverlay` (click-through, as now).
5. Latency: first answer ≤ 1 s for all decisions (policy forward + one engine search).

---

## 5. Pause / resume design (applies to every long job)
- One directory per job under `~/.cursed_words_solver/rl/<name>/` with `command.txt`,
  `config.json`, `manifest.json`, `log.txt`.
- Actor data = append-only shards (`shards/it0007_w3_0012.npz`) written atomically
  (tmp + fsync + `os.replace` with retry for Windows locks). Lose at most one in-flight episode
  per actor on a kill.
- Learner checkpoint every N updates and on SIGINT/CTRL-BREAK: model, optimizer, scheduler,
  step counters, all RNG states, config + code fingerprint; keep `last`, `prev`, `champion`.
- `python -m cursed_words_solver.rl.<job> --dir <dir>` **is** the resume command (idempotent:
  counts are absolute, never "N more").
- `rl.status` prints progress, last gate result, ETA; a `STOP` file stops a job cleanly.

---

## 6. Order of work, gates and stop rules
| Phase | Work | Gate before moving on |
|---|---|---|
| 0 | Close info leaks (planner reseed, determinised clones), check the Oden regression, re-baseline the honest teacher | leak test passes; baseline numbers recorded |
| 1 | `rl/env.py` + `rl/obs.py` + full action enumeration + speedups S1-S3 | env self-test: random + teacher policies play 200 runs crash-free on all chars/crowns/quests; S2/S3 identical outputs |
| 2 | `rl/model.py`, teacher data collection (resumable), BC trainer on GPU, numpy/torch actor inference | BC gate (§2.3 A) |
| 3 | PPO actor/learner loop, privileged critic, curriculum, eval gate, champion management | first gate pass vs teacher; then continue training |
| 4 | Advisor service + melmod changes + overlay | live dry-run on recorded journals (`run_journal`) + one real run |
| 5 | Stage C search, quests/crown 8 coverage, long training | M1-M3 tables |

Stop rules: if BC can't get within −5 points of the teacher, fix observation/action coverage
before RL. If PPO is below the BC start after ~100k runs, switch the learner to stage-C expert
iteration only (keeps the env, model and data).

---

## 7. Status and how to run (2026-11-09)

Built (package `cursed_words_solver/rl/`, tests `tests/sim/test_rl.py`, `tests/sim/test_information.py`):

| Piece | File | State |
|---|---|---|
| Information boundary | `sim/game/agent.determinize`, `player.generate_boss_drafts(start_floor)` | planner peek + future-draft leak closed in `plan_scores`, `play_out`, `rollout`; tested |
| Observation (global 208 + tokens × 146) | `rl/obs.py` | human-visible only; test: two hidden states → identical observation |
| Candidates (17 action types incl. anytime sell / reorder / discard, sell→buy swaps, pin offers) | `rl/actions.py` | teacher picks found in the list in >99% of decisions |
| Env, reward = potential increments (sums to the run outcome) | `rl/env.py` | ~5-8 s CPU per full run (vs 80-180 s for the probe-based teacher) |
| Set-transformer policy / value / aux heads (0.6 M params) | `rl/model.py` | PyTorch 2.11 + cu128 on the RTX 5070 Ti |
| Shards, atomic checkpoints, STOP files | `rl/store.py` | every job resumable by rerunning its command |
| Teacher data | `rl/teacher.py` | ~200 runs/h on 7 workers, ~30 KB per run |
| BC trainer | `rl/bc.py` | GPU, rescans new shards each epoch |
| PPO (CPU actors, GPU learner, KL anchor annealed, gate + champion) | `rl/ppo.py`, `rl/play.py`, `rl/evaluate.py` | smoke-tested end to end |
| Whole pipeline | `rl/pipeline.py` | **running since 2026-11-09 18:11** |
| Run assistant | `rl/assistant.py` + `app.py` hooks | F8 on boss draft / pin / Michael draft → AI panel; shop panel gets the AI plan on top; encounter result gets an "AI:" line |
| melmod 1.5 exports | `GameStateSerializer.cs` (`encounter.michael`), `RunStateExportFill.cs` (`extras.decision`, decision fingerprint) | compiles; **not deployed** (run `melmod\build.ps1`) |
| Importer | `importer.py` maps `encounter.michael` → `michael_draft` | checked on a capture |

Commands (from the repo root):

```
python -m cursed_words_solver.rl.pipeline              # start / resume everything
python -m cursed_words_solver.rl.pipeline --status     # progress
type nul > %USERPROFILE%\.cursed_words_solver\rl\STOP  # pause (delete the file, rerun to resume)
python -m cursed_words_solver.rl.evaluate show u100 ...  # tables by crown / character / quest
python -m cursed_words_solver.rl.assistant             # advice for the live run_state.json
```

The assistant uses `rl/assistant_policy.pt` if present, else the newest `rl/ppo*/champion.pt`, else
`rl/bc/best.pt`. Gate results: `rl/ppo1/gates.jsonl` (vs champion and vs the teacher baseline).

### 7.1 Stage C look-ahead and expert iteration (2026-11-10)

`rl/search.py`: at boss / pin / Michael drafts and at close shop or grid calls (top-2 policy
probabilities within 0.35), the top 2 candidates are each played forward on 2 resampled
futures for 1 progress node with the greedy policy, then scored Φ + 8·V. Paired on 125 gate
seeds vs the same champion (u75) without it: **47.2% vs 40.8% wins, +0.76 outcome, t = 2.03**
(+11.2% wins vs the teacher), ~120 s per run (19 searched decisions, 6 changed).

- Assistant: shop / encounter advice shows the plain policy first, then re-emits with the
  look-ahead (`CWS_AI_SEARCH=0` turns it off; 15-25 s per decision while training runs).
- Expert iteration: `rl/exit.py` plays training seeds (block 60M) with the look-ahead on the
  latest `ppo1/weights.pt` and saves every searched decision + pick to `rl/exit/shards`;
  PPO adds `--distill-coef` × cross-entropy on those picks (`--distill-dir`). The pipeline runs
  it beside PPO (`--exit-workers 3`, PPO gets the rest); `--status` shows its win rate.

Gates so far (224 seeds, block 1): BC 35.7% → u50 38.8% → u75 40.6% → **u175 42.4%** (first
champion with distillation; outcome +1.10 vs the teacher, t = 2.8; crowns 0-8 win 18/16/14/10/7/6/6/3/3
of 22, quests 12/26). 57% of losses run out of grids, so training runs are now weighted toward
high crowns (`--crown-weights 0.4,...,1.6`, gates stay uniform) and the distillation batch is 128.

2026-11-11 diagnostics (u225 on fresh block-2 seeds, 125 runs): **40.0% wins** (45.5% on the gate
set it was selected on: ~5 points of selection bias, so judge final strength on fresh blocks).
Word-search effort 0.30 vs 0.05: 40.8% vs 40.0%, t = 0.15, so the engine is not the bottleneck;
losses at crowns 3-8 are spread over stages 2-5 (build / economy falls behind the targets).
u250-u300 did not beat u225 (PPO plateau ~43-45% on gates).
Look-ahead depth on the same fresh seeds (paired vs plain u225, 40.0%): top 2 / 2 futures / horizon 1
= 41.6% (t = 0.44, ~50 s/run); top 3 / 4 futures / horizon 2 = **46.4%** (t = 1.86, lb90 +0.5%,
~180 s/run, 5-36 s per assistant shop call). The deep config is now the assistant default
(`CWS_AI_SEARCH=fast` = shallow, `=0` = off) and the ExIt collector's search, so distillation
targets come from the stronger teacher (collector ~4x slower). Pipeline resumed 2026-11-11 at u301.
Crown 8 dropped 2026-11-11 (u306): only crowns 0-7 are playable (`HighestCrownAvailable = 7`;
level 8 `HarderBosses` = every boss at the next floor's strength, code only). Training weights now
cover crowns 0-7 and the gate set is 202 runs (was 224; earlier gate numbers include 22 crown-8
runs, ~all losses). Same gate on crowns 0-7: champion u225 50.0% (101/202), teacher 39.6%.
Old crown-8 look-ahead shards and teacher shards are skipped; `evaluate compare/show` filter to 0-7.
`rl/pipeline.lock` (OS file lock) stops a second pipeline starting while one still drains after STOP.
Exact speed-ups (2026-11-11, u398; identical words / scores / decisions, parity tests in
tests/engine/test_jit_parity.py, tests/engine/test_fastcalc_parity.py, tests/sim/test_clone_parity.py):
numba letter / subset DFS and trie stepping (engine/_jit.py, `CWS_NO_JIT=1` = Python reference; deadline
searches stay on Python), plan-cached `EnginePlan.score` (`CWS_NO_FASTCALC=1`), pickle `clone()`
(`CWS_DEEPCOPY_CLONE=1`). Six uncontended training games: 108 s -> 47 s (2.27x), same outcomes.
Deep look-ahead games: 746 s -> 278 s (2.68x). Live pipeline: PPO update 170-250 s -> ~79 s,
look-ahead collector ~53 -> ~145 runs/h.
Rejected as not worth it: word-search result cache (~1 repeat per game), gate early stop (exact
version saves 0.3%; statistical one flips promotions), champion-trajectory sharing in gates (~3%).
Gates u325-u375 (crowns 0-7): 47-49.5%, none beat u225's 50.0%.

**v2 training setup (2026-11-11, restart at u601; no promotion u250-u600).** Diagnosis (4 analyses):
distillation dominated the update (grad norm 14x the next term; 83% of look-ahead labels just confirm
the policy's pick), entropy collapsed 0.40 -> 0.06 (2 exploratory decisions per run), 56-run batches
were below the gradient noise scale, 57% of look-ahead rollouts went to single-candidate decisions,
the policy could not see build strength vs targets, weak slices (Human Boy 13%, Rodman 24%, Sam Gambit
28%, 10 quests at 0-5%) got no extra training, and the 202-seed gate could not see < ~6 points. Changes:
- search: < 2 qualifying candidates -> policy argmax, no rollouts, no label.
- distillation: changed labels weight 1, agreeing 0.1, margin-0 dropped, newest 20k, coef 0.15;
  v1 shards kept (zero-padded).
- adaptive entropy coefficient (target 0.2 nats), 112 episodes per update, k3 approx-KL per epoch,
  KL anchor = champion (reloaded on promotion).
- curriculum: character / quest weights inverse to recent win rate (clamp 0.5-2), crown weights
  0.4..1.6,2.0, quest share 0.25; written to ppo1/curriculum.json and followed by the collector.
- gate: 404 runs (per 4 / per-quest 2, old 202 a subset); promote if win_diff > 0, outcome_diff > 0
  and max(outcome t, win z) >= 1.
- obs v2 (global 208 -> 241, token 146 -> 206, new columns zero-initialised so old weights load
  unchanged): last-encounter scores vs target, quest-rule flags, per-instance colours/tags, probe
  strength and per-boss strength (probes OFF by default: +116-249% run time with 1 torch thread;
  CWS_RL_PROBES=1). Draft candidate sets pruned to boss / pin only; sell_buy dropped.
First v2 gate: u625 promoted on the 404-run gate (49.5% vs u225 47.8%, outcome t = 1.63).
Search modes on fresh block 2 (u225, 114 runs, current code): plain 43.0%, deep topk 3/4/2.0
50.9% (+7.9, t = 2.44), "halving" (Gumbel top-3, common random numbers, 4+4 sims, override only at
paired t >= 1) 44.7%: worse than deep (-6.1, t = -2.0). It changes the pick in 24% of searched
decisions vs deep's 45%: acting on the plain mean beats waiting for significance here. Halving stays
opt-in (SearchConfig mode, CWS_AI_SEARCH=halving, --distill-soft); deep stays the default.
Next candidates: learned probe-strength auxiliary head (cheap), privileged critic, deeper topk search.
Paused 2026-11-11 at u636 (champion u625). Unfinished: fresh-seed test of topk 3/8/2.0
(arm u225v2_t3s8h2 in ppo1/eval_fresh, resumable via scratch eval_search.py); entropy only reached
~0.10 with ent_coef at its 0.2 cap: if it stays low, weaken the champion KL anchor / distill coef.

Open items: numba port of the trie search (only if PPO throughput limits), privileged critic, the cursed-margin (5 points) as a user setting, in-game test of
melmod 1.5's Michael draft flag (`awaiting_draft` uses the hidden reroll button as the signal).
