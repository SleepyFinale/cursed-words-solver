"""Policy iteration from self-play: the AI that improves with more runs.

    python -m cursed_words_solver.sim.game.expert --iterations 10 --runs 256            # state value
    python -m cursed_words_solver.sim.game.expert --target pairs --dir <d> ...           # paired play-outs
    python -m cursed_words_solver.sim.game.expert --target rct ...                       # randomised decisions

**State value (``--target value``, the default since 2026-10-31).** The model predicts the
run outcome from the state after a decision; ``NetPolicy`` compares the after-states of the
candidates and switches from the Advice suggestion when one is valued higher by more than a
margin. Each iteration the champion plays runs, taking a random alternative (group-first,
``sample_alternative``) at ``--epsilon`` of its decisions, and every run-level decision's
after-state is stored (~1 run's cost for ~50 labelled states, against two full play-outs
per pair below). Labels are λ-returns across decision points (``lambda_returns``): within one
shop visit the next decision's label, between visits ``(1 − λ)`` × the model's value of the
next state + ``λ`` × its label, ending at the run's ``outcome``. Bootstrapping on the model
cuts the noise of the final outcome, which sank the plain Monte-Carlo value (``learn.py``,
holdout R² 0.3, lost to Advice). The fit is ridge on all states so far (``train_value``:
run-grouped folds, λ-returns recomputed from out-of-fold values for ``--sweeps`` rounds). It
reports R² within (crown, stage, node), the part that has to come from the build, and the
correlation with the keyed paired play-outs of the advantage experiments (``--check-pairs``),
a causal check of the decisions the model would make.

**Randomised decisions (``--target rct``, 2026-11-01).** The state value above recognises
good states but cannot rank a shop's candidates: in the champion's own runs what an
after-state's columns are worth is confounded with how the run was already going (pilot
benchmark: it lost at every margin). Here the champion plays runs in which a share
(``--p-random``) of the run-level decisions is a trial: the champion's own choice (the
control, ``--control`` of trials) or a random alternative, both after-states recorded
(``NetPolicy.trial``). The label is the run's outcome minus a baseline, the out-of-fold
state value of the control's after-state (``train_rct``: a control variate fitted on the same
runs' states). Because the choice was random, the difference of the two after-states is
independent of everything else in the run, so a ridge fit of the label on it estimates what
each change *causes* (the advantage over the champion's choice), however noisy. Every
other decision of the run is the champion's, so this is one step of policy iteration.
The model (``target = "rct"``) plays like a value model, on after-state differences.
``--rct-label-lam`` trains it on the λ-return after the trial's shop visit instead of the
outcome: it ranks about a third better out of fold, but still loses in play (sim-game.md).

**Paired play-outs (``--target pairs``).** The older loop:

The policy (``NetPolicy``) plays the in-game Advice suggestion at every run-level decision
(shop buy / restock / sell / leave, boss draft, pin side, Michael's draft) unless its
learned **advantage model** predicts an alternative is better by more than a margin.

Each iteration:

1. **collect** — the current champion plays runs. At a random subset of decisions the
   suggestion *and* one alternative are each played to the end of the run by the champion,
   with keyed randomness (``play_out(keyed=True)``: both branches draw the same grids and
   shops wherever they reach the same point; test-retest label reliability 0.21 vs ~0 for
   one shared stream). The label is the outcome
   difference (encounters cleared, plus the share of the target reached where the run
   ended; a win scores 16), the input the difference of the two after-state feature
   vectors. Pairs accumulate across iterations (``pairs_it*.npz``).
2. **fit** — ridge regression on every pair so far (input dimension ~1000, labels noisy:
   a linear model generalises; an MLP over-fits).
3. **benchmark** — the new model plays a fixed seed set at several margins; word search is
   deterministic (``Candidates.effort``) and worker hash seeds are pinned, so the
   comparison with the champion is exact on the same seeds. A better model becomes the
   champion, i.e. the policy that generates the next iteration's data.

Data and models live in ``~/.cursed_words_solver/sim_models/expert/`` (``--dir``);
``history.json`` records each iteration and the champion is ``champion.npz`` (each
promoted model is also kept as ``champion_it<n>.npz``).

Resumable at every step (P6): rerun the same command after a restart. Data runs are
checkpointed every 16 runs (``pairs_it<n>.partial.npz``); a finished data file is not
collected again; every benchmark run is appended to ``evals/<seed set>_<model>_<margin>.jsonl``
as it finishes and reused (the model is named by a hash of its file, so a refitted model
never reuses another's runs); an iteration counts as done once its ``history.json`` row is
written (atomically). ``config.json`` keeps the characters / crowns / run counts the
directory was started with; a rerun with others is refused (the seed sets would change).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np

from cursed_words_solver.sim.game.agent import Action, Candidates, apply, clone, determinize, legal_actions, spawn_pool
from cursed_words_solver.sim.game.bossrisk import DEFAULT_PATH as BOSS_RISK_PATH
from cursed_words_solver.sim.game.core import Rng
from cursed_words_solver.sim.game.features import encode, feature_names, outcome, progress
from cursed_words_solver.sim.game.player import Node
from cursed_words_solver.sim.game.itemvalue import RUN_LOG
from cursed_words_solver.sim.game.learn import MLP, Ridge, fit_width, fit_with_holdout, load_model
from cursed_words_solver.sim.game.policy import (DEFAULT_PLAN, DEFAULT_PLAN_CHARS, FastAdvicePolicy, PowerConfig, load_char_tuning,
                                                 offer_class)


DEFAULT_DIR = Path.home() / ".cursed_words_solver" / "sim_models" / "expert"
VALUE_DIR = Path.home() / ".cursed_words_solver" / "sim_models" / "value"
PAIRS_CHECK_DIR = Path.home() / ".cursed_words_solver" / "sim_models" / "keyed_carpman_c0"
RCT_DIR = Path.home() / ".cursed_words_solver" / "sim_models" / "rct"
SHOP_CAP = 14
SHOP_CANDIDATES = 16  # cap on full_shop_candidates per shop state
EFFORT = 0.05  # deterministic word search (load-independent, reproducible benchmarks)
THRESHOLDS = (0.5, 1.0, 2.0)
LCB_PENALTIES = (1.0, 2.0)  # standard errors an rct choice must clear (``lcb_by_margin``)
VALUE_THRESHOLDS = (0.1, 0.3, 0.6)  # value margins (outcome units) a value model is benchmarked at
MIN_R2_WITHIN = 0.01  # skip benchmarking a value model that explains nothing beyond crown / stage / node
# Moves a value model may choose (see NetPolicy._pick_value).
VALUE_KINDS = frozenset({"buy", "hippo", "sell_buy", "leave", "boss", "pin", "michael_pick"})
# Features a value model does not see: money invested / sell value / frozen stock / the
# restock price mark runs that were already going well (they rise with income), so a model
# fitted on its own play learns "spend more, freeze more" (pilot benchmark, 2026-11-01).
VALUE_DROP = frozenset({"frozen_n", "log_sell_value", "log_invested", "shop_restock_cost"})
VALUE_DROP_PREFIXES = ("frozen:",)


RCT_PER_CLASS = ("pos:", "frozen:", "foil:", "ivar:", "ictr:", "item:")  # one column per item class


def per_class_mask() -> np.ndarray:
    """Columns that describe one item class each (``RCT_PER_CLASS``)."""
    return np.array([n.startswith(RCT_PER_CLASS) for n in feature_names()])


def value_drop_mask() -> np.ndarray:
    """Columns of ``features.encode`` left out of value models (``VALUE_DROP``)."""
    return np.array([n in VALUE_DROP or n.startswith(VALUE_DROP_PREFIXES) for n in feature_names()])
ROLL_EFFORT, ROLL_TARGETS = 0.02, 3  # play-out continuation (see _pairs_job)
MIN_CORR = 0.03  # skip benchmarking a model whose cross-validated fit shows no signal
PROMOTE_T = 1.65  # one-sided ~95% on the paired per-seed outcome gain


def same(a: Action, b: Action) -> bool:
    """Same move (labels differ: Advice's suggestion vs the legal-action listing)."""
    return a.kind == b.kind and tuple(a.args) == tuple(b.args)


def _add(out: list[Action], a: Action) -> None:
    if not any(same(a, b) for b in out):
        out.append(a)


def shop_candidates(game, suggestion: Action, max_candidates: int = 4) -> list[Action]:
    """Suggestion first, then buys (upgrades of owned stickers first), a restock, leave —
    each move once."""
    acts = legal_actions(game)
    out = [suggestion]
    owned = {i.game_class for i in game.player.stickers_list(for_comparison=True)}

    def key(a: Action) -> int:
        if a.args[0] == "tile":
            return 2
        stock = game.shop.stickers if a.args[0] == "sticker" else game.shop.stamps
        o = stock[a.args[1]]
        return 0 if (o is not None and o.item.game_class in owned) else 1

    for a in sorted((a for a in acts if a.kind in ("buy", "hippo")), key=key):
        if len(out) >= max_candidates:
            break
        _add(out, a)
    for a in acts:
        if a.kind == "reroll_shop":
            _add(out, a)
            break
    _add(out, Action("leave"))
    return out


# Action groups of the full shop space, in the order they share the candidate cap.
SHOP_GROUPS = ("buy", "sell_buy", "freeze", "sell", "move")


def _group(a: Action) -> str:
    return "buy" if a.kind == "hippo" else a.kind


def full_shop_candidates(game, suggestion: Action, cap: int = SHOP_CANDIDATES) -> list[Action]:
    """Every kind of legal shop move (P3), the suggestion first: leave (saving the money) and
    a restock always, then buys (tiles and Hungry Hippo feeds included), sell-then-buy swaps
    for offers that only fit once an owned item of that kind is sold, freezes / unfreezes,
    plain sells and reorders (a swap of two slots; scoring order matters), dealt round-robin
    across those groups until ``cap`` so no group crowds the others out. A swap is listed
    when the sale would pay for the offer; ``afterstate`` drops the ones that still fail."""
    from cursed_words_solver.sim.game.shop import can_sell

    acts = legal_actions(game)
    out = [suggestion]
    _add(out, Action("leave"))
    for a in acts:
        if a.kind == "reroll_shop":
            _add(out, a)
    groups: dict[str, list[Action]] = {g: [] for g in SHOP_GROUPS}
    for a in acts:
        if _group(a) in groups and a.kind != "move":
            groups[_group(a)].append(a)
    p, s = game.player, game.shop
    for kind, owned, stock in (("sticker", p.stickers, s.stickers), ("stamp", p.stamps, s.stamps)):
        for j, o in enumerate(stock):
            if o is None or s.can_buy(kind, j) or s.slots_hidden(kind):
                continue
            for i, it in enumerate(owned):
                if (it is None or it.game_class == o.item.game_class or not can_sell(p, it)
                        or p.money + max(0, it.sell_value(p)) < s.offer_cost(o)):
                    continue
                groups["sell_buy"].append(Action("sell_buy", (kind, i, j), f"sell {it.game_class}, buy {o.item.game_class}"))
        n = sum(it is not None for it in owned)
        if n >= 2:  # a drag re-inserts the item (shift), so both directions differ
            for src in range(5):
                for dst in range(5):
                    if src != dst and owned[src] is not None:
                        groups["move"].append(Action("move", (kind, src, dst), f"move {kind} {src}->{dst}"))
    pending = [list(groups[g]) for g in SHOP_GROUPS]
    while len(out) < cap and any(pending):
        for q in pending:
            if q and len(out) < cap:
                _add(out, q.pop(0))
    return out


def sample_alternative(rng: random.Random, cands: list[Action]) -> Action:
    """An alternative to ``cands[0]`` for a training pair: a group (buy, swap, freeze, sell,
    reorder, leave, restock, boss / pin option) uniformly, then a move in it, so the many
    reorders and freezes do not drown the rarer, bigger choices."""
    by: dict[str, list[Action]] = {}
    for a in cands[1:]:
        by.setdefault(_group(a), []).append(a)
    return rng.choice(by[rng.choice(sorted(by))])


def _sparse(x: np.ndarray) -> dict[str, float]:
    """Non-zero entries of a feature vector, {index: value} (compact run-log rows)."""
    return {str(i): round(float(x[i]), 4) for i in np.flatnonzero(np.abs(x) > 1e-6)}


def afterstate(game, a: Action) -> np.ndarray | None:
    """Features after ``a``; None when it fails (raises, or a buy / swap returns False)."""
    g = clone(game, light=True)
    try:
        if apply(g, a) is False:
            return None
    except Exception:
        return None
    return encode(g)


class NetPolicy(FastAdvicePolicy):
    """Fast Advice everywhere; run-level choices overridden by a learned model (advantage or
    state value). ``explore`` > 0 takes a random alternative at that share of decisions
    (training data); ``explored`` says whether the last decision was one. ``randomise`` > 0
    turns that share of decisions into trials (``_trial``) and leaves the last one in
    ``trial``."""

    def __init__(self, cands: Candidates, model=None, *, seed: int = 0, threshold: float | None = None,
                 boss_risk: str = "", boss_model: str | None = None, char_tuning: str = "",
                 action_space: str = "full", explore: float = 0.0, randomise: float = 0.0,
                 control: float = 0.25, trial_kinds: frozenset[str] | None = None,
                 build_plan: str | None = None, build_plan_chars: dict | None = None) -> None:
        if boss_model is None:  # build-aware boss risk (on 2026-10-30); only used with a boss_risk table
            from cursed_words_solver.sim.game.bossmodel import DEFAULT_PATH

            boss_model = str(DEFAULT_PATH) if DEFAULT_PATH.is_file() else ""
        cfg = PowerConfig(probe_seeds=1, probe_grids=2, boss_risk=boss_risk or "", boss_model=boss_model,
                          fast_placement=True, placement_targets=8, advice_fallback=True, sort_items=True, spend_over=20,
                          power_override=0.1, swap_sell=True, tile_buy_chars=("Spike",),
                          sort_stamps_chars=("SockHead",), route_value=True,
                          build_plan=DEFAULT_PLAN if build_plan is None else build_plan,
                          build_plan_chars=dict(DEFAULT_PLAN_CHARS if build_plan_chars is None else build_plan_chars))
        if char_tuning:  # chartune.py's per-character settings
            cfg.char_overrides = load_char_tuning(Path(char_tuning))
        super().__init__(cands, cfg, seed=seed)
        self.model = model
        self.action_space = action_space  # "full": full_shop_candidates; "advice": shop_candidates
        self.threshold = threshold if threshold is not None else float(getattr(model, "threshold", 0.5))
        self._steps = 0
        self.explore = explore
        self._explore_rng = random.Random(f"explore|{seed}")
        self.explored = False
        self.randomise, self.control = randomise, control
        self.trial_kinds = VALUE_KINDS if not trial_kinds else VALUE_KINDS & frozenset(trial_kinds)
        self.trial: tuple[np.ndarray, np.ndarray, str, bool] | None = None
        self._playout: NetPolicy | None = None
        self.pin_log: list[dict[str, Any]] = []  # cfg.pin_side == "rollout": one entry per decision

    def candidates(self, game) -> list[Action]:
        """Options at a run-level decision, the base (Advice / heuristic) choice first."""
        ph = game.phase
        if ph == "shop":
            if self.action_space == "full":
                cands = full_shop_candidates(game, self._advice_shop(game))
            else:
                cands = shop_candidates(game, self._advice_shop(game))
            if self.cfg.build_plan:  # the model may not buy what the plan refuses
                cands = cands[:1] + [a for a in cands[1:] if self._offer_ok(game, offer_class(game, a)) and self._reserve_ok(game, a)]
            if game.player.run.challenge_is("TwoWrongs"):  # nor what adds positive score there
                cands = cands[:1] + [a for a in cands[1:] if not self.harmful(game, a)]
            return cands
        if ph == "boss_draft":
            fb = FastAdvicePolicy._boss(self, game)
            return [fb] + [a for a in legal_actions(game) if a.kind == "boss" and not same(a, fb)]
        if ph == "pin_reward":
            fp = self._pin_rollout(game) if self.cfg.pin_side == "rollout" else FastAdvicePolicy._pin(self, game)
            return [fp] + [a for a in legal_actions(game) if a.kind == "pin" and not same(a, fp)]
        if ph == "encounter" and game.encounter.michael_draft is not None:
            first = self.michael_pick(game)
            picks = [a for a in legal_actions(game) if a.kind == "michael_pick"]
            return [a for a in picks if a.args[0] == first] + [a for a in picks if a.args[0] != first]
        return []

    def _pin_rollout(self, game) -> Action:
        """Pin side for this situation: each side is played ``cfg.pin_horizon`` stages on
        the same ``pin_samples`` keyed futures (``play_out``) and the stronger build wins
        (0: the run's outcome); ties keep the lower side. The play-outs use ``cfg.pin_playout_side``, so they do not
        recurse. Every decision is appended to ``pin_log`` (state, both sides' outcomes), the
        training data for a learned pin model."""
        base = FastAdvicePolicy._pin(self, game)  # lower side ("both" with the ID Card)
        opts = [o for o in game.pin_options() if o in ("left", "right")]
        if len(opts) < 2 or base.args[0] not in opts:
            return base
        if self._playout is None:
            self._playout = NetPolicy(self.cands, None, seed=self._probe_rng_seed)
            self._playout.cfg = replace(self.cfg, pin_side=self.cfg.pin_playout_side)
        run, pin = game.player.run, game.player.pin
        tag = f"{self._probe_rng_seed}|pin|{run.stage}|{run.node.name}"
        res = {o: [round(play_out(game, Action("pin", (o,)), self._playout, f"{tag}|{k}", keyed=True,
                                  stages=self.cfg.pin_horizon), 3)
                   for k in range(self.cfg.pin_samples)] for o in opts}
        mean = {o: float(np.mean(v)) for o, v in res.items()}
        best = max(opts, key=lambda o: (mean[o], o == base.args[0]))
        xl, xr = afterstate(game, Action("pin", ("left",))), afterstate(game, Action("pin", ("right",)))
        x = encode(game)  # what pin_side="learned" sees when it decides
        self.pin_log.append({
            "stage": run.stage, "node": run.node.name, "money": game.player.money,
            "levels": [pin.level(0), pin.level(1)], "base": base.args[0], "chosen": best, "outcomes": res,
            "horizon": self.cfg.pin_horizon,
            "x": _sparse(x),
            "dx": None if xl is None or xr is None else _sparse(xr - xl)})
        return Action("pin", (best,))

    def pick(self, game, cands: list[Action]) -> Action:
        """Keep ``cands[0]`` unless the model predicts an alternative beats it by more than
        ``threshold`` (in outcome units: encounters cleared)."""
        if self.model is None or len(cands) == 1:
            return cands[0]
        if getattr(self.model, "target", "advantage") in ("value", "rct", "rct_tree"):
            return self._pick_value(game, cands)
        base = afterstate(game, cands[0])
        if base is None:
            return cands[0]
        rows, acts = [], []
        for a in cands[1:]:
            x = afterstate(game, a)
            if x is not None:
                rows.append(x - base)
                acts.append(a)
        if not rows:
            return cands[0]
        adv = self.model.predict(np.stack(rows))
        i = int(np.argmax(adv))
        return acts[i] if adv[i] > self.threshold else cands[0]

    def _whole(self, a: Action) -> Action:
        """Advice's swap step (a sell, its planned buy next) as the ``sell_buy`` it is."""
        pending = getattr(self, "_pending_buy", None)
        if a.kind == "sell" and pending is not None and pending[0] == a.args[0]:
            return Action("sell_buy", (a.args[0], a.args[1], pending[1]), a.label)
        return a

    def _pick_value(self, game, cands: list[Action]) -> Action:
        """State-value model: the candidate whose after-state is valued highest, if it beats
        the suggestion's by more than ``threshold``. An ``rct`` model predicts the advantage
        from the difference of the two after-states instead.

        Only choices whose after-state shows their effect are compared (``VALUE_KINDS``: buys,
        swaps, leave, boss / pin / Michael picks). A suggested freeze, sell, reorder or
        restock stands, and none is picked over the suggestion. Shop stock is not a feature,
        so a restock only looks like money lost and a freeze like nothing at all. Advice's
        swap (a sell now, the replacement next step) is valued as the whole swap: the sell
        alone looks like an item lost (pilot benchmark, 2026-11-01). An ``rct`` model with a
        ``penalty`` ranks by the advantage minus ``penalty`` × its standard error, so a choice
        resting on a few trials' weights (a per-class column) needs a larger predicted gain.
        An ``rct_tree`` model (``learn.TreeAdvantage``) also sees the suggestion's after-state
        and the move's kind, so a move's worth can depend on the build."""
        first = self._whole(cands[0])
        if first.kind not in VALUE_KINDS:
            return cands[0]
        base = afterstate(game, first)
        if base is None:
            return cands[0]
        rows, acts = [base], []
        for a in cands[1:]:
            if a.kind not in VALUE_KINDS or same(a, first):
                continue
            x = afterstate(game, a)
            if x is not None:
                rows.append(x)
                acts.append(a)
        if not acts:
            return cands[0]
        X = np.stack(rows)
        if self.model.target == "rct":
            adv = self.model.predict(X[1:] - X[0]) - self.model.predict(np.zeros((1, X.shape[1])))[0]
            k = float(getattr(self.model, "penalty", 0.0) or 0.0)
            if k > 0:  # the best of 16 noisy predictions is not trusted: discount each by its SE
                adv = adv - k * self.model.se(X[1:] - X[0])
        elif self.model.target == "rct_tree":
            adv = self.model.advantage(X[0], X[1:], [a.kind for a in acts])
        else:
            v = self.model.predict(X)
            adv = v[1:] - v[0]
        i = int(np.argmax(adv))
        return acts[i] if adv[i] > self.threshold else cands[0]

    def decide(self, game) -> tuple[Action, list[Action]]:
        """(action, candidates) — candidates empty when this is not a run-level decision."""
        self._tune(game)
        self.explored = False
        self.trial = None  # a step without a run-level decision must not repeat the last trial
        ph = game.phase
        if ph != "shop":
            self._steps = 0
        elif self._steps >= SHOP_CAP:
            return self._leave_now(), []
        else:
            self._steps += 1
        if ph == "encounter" and game.encounter.michael_draft is None:
            return FastAdvicePolicy.act(self, game), []
        memo = (set(self._frozen_this_shop), set(self._bought_this_shop), self._sold_this_shop)
        cands = self.candidates(game)
        if not cands:
            return FastAdvicePolicy.act(self, game), []
        a = self.pick(game, cands)
        if self.randomise and len(cands) > 1 and self._explore_rng.random() < self.randomise:
            a = self._trial(game, cands, a)
        elif self.explore and len(cands) > 1 and self._explore_rng.random() < self.explore:
            a = sample_alternative(self._explore_rng, cands)
            self.explored = True
        if ph == "shop" and not same(a, cands[0]):
            self._record_override(game, a, memo)
        if a.kind == "leave":
            self._leave_now()
        return a, cands

    def _trial(self, game, cands: list[Action], a: Action) -> Action:
        """A randomised decision: the champion's choice ``a`` (the control, ``control`` of
        trials) or a random alternative (group-first), ``trial`` = (control after-state, taken
        after-state, kind taken, control?). Only choices whose after-state shows their effect
        (``VALUE_KINDS``, narrowed by ``trial_kinds``) take part; Advice's swap step is the whole swap."""
        first = self._whole(a) if same(a, cands[0]) else a
        if first.kind not in self.trial_kinds:
            return a
        alts = [c for c in cands if c.kind in self.trial_kinds and not same(c, first) and not same(c, a)]
        if not alts:
            return a
        xa = afterstate(game, first)
        if xa is None:
            return a
        if self._explore_rng.random() < self.control:
            self.trial = (xa, xa, first.kind, True)
            return a
        take = sample_alternative(self._explore_rng, [first] + alts)
        xt = afterstate(game, take)
        if xt is None:
            return a
        self.trial = (xa, xt, take.kind, False)
        self.explored = True
        return take

    def _record_override(self, game, a: Action, memo) -> None:
        """Advice books its per-shop plan (bought / sold / frozen) when it *suggests*; on an
        override undo that and book the action actually taken instead."""
        self._frozen_this_shop, self._bought_this_shop, self._sold_this_shop = memo
        self._pending_buy = None  # a swap Advice planned is not happening
        if a.kind in ("buy", "sell_buy") and a.args[0] in ("sticker", "stamp"):
            stock = game.shop.stickers if a.args[0] == "sticker" else game.shop.stamps
            o = stock[a.args[-1]]
            if o is not None:
                self._bought_this_shop.add(o.item.game_class)
        if a.kind in ("sell", "sell_buy"):
            self._sold_this_shop = True
        elif a.kind == "freeze":
            self._frozen_this_shop.add(tuple(a.args))

    def _leave_now(self) -> Action:
        self._steps = 0
        return self._leave()

    def act(self, game) -> Action:
        return self._hoard(game, self.decide(game)[0])


# ---------------------------------------------------------------------------- paired rollouts


def _point(g) -> tuple:
    run = g.player.run
    enc = g.encounter
    grid = (enc.total_grids - enc.remaining_grids, enc.reroll_tracker) if enc is not None else (0, 0)
    return (run.stage, run.node.name, *grid)


def play_out(game, action: Action, policy: NetPolicy, seed: str, max_steps: int = 4000,
             keyed: bool = False, stages: int = 0) -> float:
    """``outcome`` after ``action`` then ``policy`` to the end of the run (own RNG stream).

    ``stages`` > 0 stops after that many more stages and returns build strength instead:
    the summed score / target of every word played, plus ``progress``, plus 5 if still
    alive. Run outcome is too coarse to tell two close choices apart (two futures of the
    same pin decision agreed on the better side no more than chance); one-stage strength
    is repeatable (split-half corr 0.67 over 85 pin decisions).

    ``keyed``: the stream is reseeded before every action from (seed, stage, node, grid,
    grid rerolls, action kind, how many of that kind here), so two branches that reach the
    same point of the run draw the same grids, shops and restocks (leaving a shop after one
    more purchase still deals the same next grid) — the paired difference then measures the
    decision, not which future happened to be sampled."""
    g = determinize(clone(game), f"pair|{seed}")  # fresh RNG + resampled future boss drafts
    policy._leave_now()
    if keyed:
        g.rng.reseed(f"pair|{seed}|decision")
    apply(g, action)
    stage0 = g.player.run.stage
    strength = 0.0
    seen: dict[tuple, int] = {}
    for _ in range(max_steps):
        if g.phase == "done":
            break
        run = g.player.run
        if stages and run.stage >= stage0 + stages and run.node in (Node.SHOP_ZERO, Node.ENCOUNTER_FIRST):
            break
        a = policy.act(g)
        if keyed:
            k = (*_point(g), a.kind)
            seen[k] = seen.get(k, 0) + 1
            g.rng.reseed(f"pair|{seed}|{k}|{seen[k]}")
        target = g.encounter.total_target if (stages and a.kind == "submit" and g.encounter is not None) else 0
        res = apply(g, a)
        if target > 0 and res is not None and hasattr(res, "score"):
            strength += max(0, res.score) / target
    if stages:
        return strength + progress(g) + (0.0 if g.won is False else 5.0)
    return outcome(g)


_CANDS: Candidates | None = None
_MODEL = None


def _init(wordlist: str | None, model_path: str | None, effort: float = EFFORT,
          cheap: bool = False) -> None:
    global _CANDS, _MODEL
    _CANDS = Candidates(Path(wordlist) if wordlist else None, effort=effort, cheap_floor=cheap)
    _MODEL = load_model(Path(model_path)) if model_path else None


def _game(job: dict[str, Any]):
    from cursed_words_solver.sim.game.run import Game, RunConfig

    return Game(RunConfig(character=job["character"], ascension=job["crown"], challenge=job.get("quest"),
                          seed=job["seed"], wordlist=_CANDS.wordlist))


def _pairs_job(job: dict[str, Any]) -> dict[str, Any]:
    """One run by the champion; at sampled decisions, (alternative − suggestion) pairs."""
    t0 = time.time()
    rng = random.Random(job["seed"])
    g = _game(job)
    pol = NetPolicy(_CANDS, _MODEL, seed=job["seed"], threshold=job.get("threshold"), boss_risk=job.get("boss_risk"))
    # Play-outs use a cheaper continuation (3.6x faster: search effort 0.02, 3 placement
    # squares): labels measure the decision under a slightly weaker but same-style policy.
    roll = NetPolicy(_CANDS.with_effort(ROLL_EFFORT, cheap_floor=True), _MODEL, seed=job["seed"] + 1, threshold=job.get("threshold"),
                     boss_risk=job.get("boss_risk"))
    roll.cfg.placement_targets = ROLL_TARGETS
    dX, dy, kinds = [], [], []
    k = 0
    err = ""
    try:
        for _ in range(4000):
            if g.phase == "done":
                break
            a, cands = pol.decide(g)
            if len(cands) > 1 and rng.random() < job["p_sample"]:
                k += 1
                alt = sample_alternative(rng, cands)
                xa, xb = afterstate(g, cands[0]), afterstate(g, alt)
                if xa is not None and xb is not None:
                    seed = f"{job['seed']}|{k}"
                    keyed = bool(job.get("keyed"))
                    ya = play_out(g, cands[0], roll, seed, keyed=keyed)
                    yb = play_out(g, alt, roll, seed, keyed=keyed)
                    dX.append(xb - xa)
                    dy.append(yb - ya)
                    kinds.append(g.phase)
            apply(g, a)
    except Exception as exc:  # pragma: no cover - surfaced in the log
        err = f"{type(exc).__name__}: {exc}"
    width = len(feature_names())
    return {"dX": np.stack(dX).astype(np.float32) if dX else np.zeros((0, width), np.float32),
            "dy": np.array(dy, np.float32), "kind": np.array(kinds, dtype="U12"),
            "won": bool(g.won), "outcome": outcome(g), "err": err, "sec": time.time() - t0, "seed": job["seed"]}


def _states_job(job: dict[str, Any]) -> dict[str, Any]:
    """One run by the champion, exploring at ``job["epsilon"]`` of its decisions; the
    after-state of every run-level decision, in order, with its shop visit / decision point
    (``visit`` = stage × 16 + node) and whether it was a random alternative."""
    t0 = time.time()
    g = _game(job)
    pol = NetPolicy(_CANDS, _MODEL, seed=job["seed"], threshold=job.get("threshold"), boss_risk=job.get("boss_risk"),
                    explore=float(job.get("epsilon", 0.0)))
    X, visit, explored = [], [], []
    err = ""
    try:
        for _ in range(4000):
            if g.phase == "done":
                break
            a, cands = pol.decide(g)
            run = g.player.run
            point = run.stage * 16 + int(run.node)
            apply(g, a)
            if cands:
                X.append(encode(g))
                visit.append(point)
                explored.append(pol.explored)
    except Exception as exc:  # pragma: no cover - surfaced in the log
        err = f"{type(exc).__name__}: {exc}"
    n = len(X)
    out = outcome(g)
    return {"X": np.stack(X).astype(np.float32) if X else np.zeros((0, len(feature_names())), np.float32),
            "visit": np.array(visit, np.int16), "explored": np.array(explored, bool),
            "run": np.full(n, job["seed"], np.int64), "crown": np.full(n, job["crown"], np.int8),
            "outcome": np.full(n, out, np.float32),
            "won": bool(g.won), "err": err, "sec": time.time() - t0, "seed": job["seed"]}


def _rct_job(job: dict[str, Any]) -> dict[str, Any]:
    """One run by the champion with ``job["p_random"]`` of its decisions randomised
    (``NetPolicy._trial``): every trial (control and taken after-states, kind, decision point),
    and every decision's after-state as in ``_states_job`` (the baseline value's data)."""
    t0 = time.time()
    g = _game(job)
    pol = NetPolicy(_CANDS, _MODEL, seed=job["seed"], threshold=job.get("threshold"), boss_risk=job.get("boss_risk"),
                    randomise=float(job["p_random"]), control=float(job.get("control", 0.25)),
                    trial_kinds=frozenset(job.get("trial_kinds") or ()))
    X, visit, explored = [], [], []
    xa, xt, kind, control, tvisit = [], [], [], [], []
    err = ""
    try:
        for _ in range(4000):
            if g.phase == "done":
                break
            a, cands = pol.decide(g)
            run = g.player.run
            point = run.stage * 16 + int(run.node)
            if pol.trial is not None:
                xa.append(pol.trial[0])
                xt.append(pol.trial[1])
                kind.append(pol.trial[2])
                control.append(pol.trial[3])
                tvisit.append(point)
            apply(g, a)
            if cands:
                X.append(encode(g))
                visit.append(point)
                explored.append(pol.explored)
    except Exception as exc:  # pragma: no cover - surfaced in the log
        err = f"{type(exc).__name__}: {exc}"
    width = len(feature_names())
    n, m = len(X), len(xa)
    out = outcome(g)

    def stack(rows):
        return np.stack(rows).astype(np.float32) if rows else np.zeros((0, width), np.float32)

    return {"X": stack(X), "visit": np.array(visit, np.int16), "explored": np.array(explored, bool),
            "run": np.full(n, job["seed"], np.int64), "crown": np.full(n, job["crown"], np.int8),
            "outcome": np.full(n, out, np.float32),
            "t_xa": stack(xa), "t_xt": stack(xt), "t_kind": np.array(kind, dtype="U12"),
            "t_control": np.array(control, bool), "t_visit": np.array(tvisit, np.int16),
            "t_run": np.full(m, job["seed"], np.int64), "t_crown": np.full(m, job["crown"], np.int8),
            "t_outcome": np.full(m, out, np.float32),
            "won": bool(g.won), "err": err, "sec": time.time() - t0, "seed": job["seed"]}


PAIR_FIELDS = ("dX", "dy", "kind")
STATE_FIELDS = ("X", "visit", "explored", "run", "crown", "outcome")
TRIAL_FIELDS = ("t_xa", "t_xt", "t_kind", "t_control", "t_visit", "t_run", "t_crown", "t_outcome")
RCT_FIELDS = ("t_xt", "t_xa") + TRIAL_FIELDS[2:] + STATE_FIELDS  # fields[1] counts the trials


def _eval_job(job: dict[str, Any]) -> dict[str, Any]:
    from cursed_words_solver.sim.game.bossrisk import boss_outcomes

    g = _game(job)
    pol = NetPolicy(_CANDS, _MODEL, seed=job["seed"], threshold=job.get("threshold"), boss_risk=job.get("boss_risk"))
    for k, v in (job.get("cfg") or {}).items():  # PowerConfig overrides (tuning sweeps)
        setattr(pol.cfg, k, v)
    buys: list[list[Any]] = []  # [stage, node, item class] per purchase (item-value data)
    shops: list[list[Any]] = []  # [stage, node] per shop visited
    pins: list[str] = []  # pin reward choices in order
    error = None
    try:
        for _ in range(4000):
            if g.phase == "done":
                break
            a = pol.act(g)
            run = g.player.run
            cls = None
            if g.phase == "shop":
                if not shops or shops[-1] != [run.stage, run.node.name]:
                    shops.append([run.stage, run.node.name])
                cls = offer_class(g, a)
            elif g.phase == "pin_reward" and a.kind == "pin":
                pins.append(str(a.args[0]))
            stage, node = run.stage, run.node.name
            if apply(g, a) and cls:
                buys.append([stage, node, cls])
    except Exception as e:  # a crash ends the run as a loss; logged so it is not mistaken for one
        error = repr(e)
    return {"seed": job["seed"], "won": bool(g.won), "stage": g.player.run.stage, "outcome": outcome(g),
            "character": g.player.character, "crown": g.player.run.ascension, "buys": buys,
            "shops": shops, "pins": pins, "pin_log": pol.pin_log, "bosses": boss_outcomes(g), "error": error}


def atomic_write(path: Path, text: str) -> None:
    """Write via a temporary file and rename, so a restart mid-write never leaves half a file."""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def model_tag(model: str | None) -> str:
    """'base' or a short hash of the model's arrays (eval caches are keyed by it; the file
    bytes would not do, ``.npz`` members carry the time they were written)."""
    if not model:
        return "base"
    h = hashlib.sha1()
    with np.load(model, allow_pickle=False) as d:
        for k in sorted(d.files):
            h.update(k.encode())
            h.update(np.ascontiguousarray(d[k]).tobytes())
    return h.hexdigest()[:10]


def collect(jobs, *, workers, wordlist, model, out: Path, job=_pairs_job, fields=PAIR_FIELDS,
            label: str = "pairs") -> dict[str, Any]:
    """Run the data jobs (``job`` returns one array per name in ``fields``, rows aligned);
    finished runs are checkpointed to ``<out>.partial.npz`` every 16 runs, so an
    interrupted iteration resumes where it stopped. A finished ``out`` is reused as it is."""
    if out.is_file():
        with np.load(out) as d:
            stats = {"runs": int(len(d["seeds"])), "wins": int(d["wins"][0]), label: int(len(d[fields[1]]))}
        print(f"  data already collected: {stats}", flush=True)
        return stats
    partial = out.with_name(out.stem + ".partial.npz")
    cols: dict[str, list[np.ndarray]] = {f: [] for f in fields}
    done: set[int] = set()
    wins = 0
    if partial.is_file():
        with np.load(partial) as d:  # closes the file (Windows cannot delete it while open)
            cols = {f: [d[f]] for f in fields}
            done = set(int(x) for x in d["seeds"])
            wins = int(d["wins"][0])
        print(f"  resuming: {len(done)} runs already collected", flush=True)
    todo = [j for j in jobs if j["seed"] not in done]

    def rows() -> int:
        return int(sum(len(c) for c in cols[fields[1]]))

    def save(path: Path) -> None:
        np.savez_compressed(path, **{f: np.concatenate(cols[f]) for f in fields if cols[f]},
                            seeds=np.array(sorted(done), np.int64), wins=np.array([wins]))

    t0 = time.time()
    if todo:
        with spawn_pool(workers, _init, (wordlist, model)) as pool:
            for i, r in enumerate(pool.imap_unordered(job, todo)):
                for f in fields:
                    cols[f].append(r[f])
                wins += r["won"]
                done.add(r["seed"])
                if r["err"]:
                    print("  error:", r["err"], flush=True)
                if (i + 1) % 16 == 0 or i + 1 == len(todo):
                    save(partial)
                    eta = (time.time() - t0) / (i + 1) * (len(todo) - i - 1)
                    print(f"  run {len(done)}/{len(jobs)}: {rows()} {label}, {wins} wins "
                          f"({time.time() - t0:.0f}s, ~{eta / 60:.0f} min left)", flush=True)
    save(out)
    partial.unlink(missing_ok=True)
    return {"runs": len(jobs), "wins": wins, label: rows()}


def evaluate(jobs, *, workers, wordlist, model, threshold: float | None = None,
             cheap: bool = False, run_log: Path | None = RUN_LOG, cache: Path | None = None) -> dict[str, Any]:
    """Run full games; ``cheap`` uses the faster exact-scoring floor (long benchmarks).
    Every run is appended to ``run_log`` (purchases, shops, bosses, outcome), the data the
    item-value table learns from, so each benchmark also adds training data. With
    ``cache`` (a ``.jsonl``) each finished run is appended there and runs already in it are
    not played again (an interrupted benchmark resumes)."""
    jobs = [{**j, "threshold": threshold if threshold is not None else j.get("threshold")} for j in jobs]
    done: dict[int, dict] = {}
    if cache is not None and Path(cache).is_file():
        for line in Path(cache).read_text().splitlines():
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue  # a line cut short by a restart
            done[r["seed"]] = r
    todo = [j for j in jobs if j["seed"] not in done]
    if done:
        print(f"  resuming benchmark: {len(jobs) - len(todo)} of {len(jobs)} runs done", flush=True)
    if cache is not None:
        Path(cache).parent.mkdir(parents=True, exist_ok=True)
    fresh: list[tuple[dict, dict]] = []
    if todo:
        by_seed = {j["seed"]: j for j in todo}
        with spawn_pool(workers, _init, (wordlist, model, EFFORT, cheap)) as pool:
            for r in pool.imap_unordered(_eval_job, todo):
                done[r["seed"]] = r
                fresh.append((by_seed[r["seed"]], r))
                if cache is not None:
                    with Path(cache).open("a", encoding="utf-8") as f:
                        f.write(json.dumps(r) + "\n")
    res = [done[j["seed"]] for j in jobs]
    errors = [r for r in res if r["error"]]
    if errors:
        print(f"  {len(errors)} runs crashed, e.g. seed {errors[0]['seed']}: {errors[0]['error']}", flush=True)
    if run_log is not None and fresh:
        run_log = Path(run_log)
        run_log.parent.mkdir(parents=True, exist_ok=True)
        with run_log.open("a", encoding="utf-8") as f:
            for j, r in fresh:
                f.write(json.dumps({**r, "cfg": j.get("cfg") or {}, "model": bool(model),
                                    "boss_risk": bool(j.get("boss_risk")), "cheap": cheap}) + "\n")
    return {"runs": len(res), "wins": sum(r["won"] for r in res),
            "win_rate": sum(r["won"] for r in res) / max(1, len(res)),
            "mean_outcome": float(np.mean([r["outcome"] for r in res])),
            "per_seed": [round(r["outcome"], 2) for r in res]}


def paired_test(a: list[float], b: list[float]) -> dict[str, float]:
    """Per-seed outcome differences a − b on the same seeds: mean, SE and t."""
    d = np.asarray(a, float) - np.asarray(b, float)
    se = float(d.std(ddof=1) / np.sqrt(len(d))) if len(d) > 1 else float("inf")
    mean = float(d.mean()) if len(d) else 0.0
    return {"mean": round(mean, 4), "se": round(se, 4), "t": round(mean / se, 2) if se > 0 else 0.0,
            "better": int((d > 0).sum()), "worse": int((d < 0).sum())}


def load_pairs(out: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    width = len(feature_names())
    dXs, dys, ks = [], [], []
    for f in sorted(out.glob("pairs_it*.npz")):
        if f.name.endswith(".partial.npz"):
            continue
        with np.load(f) as d:
            dX, dy, kind = d["dX"], d["dy"], d["kind"]
        if dX.shape[1] < width:
            dX = np.pad(dX, ((0, 0), (0, width - dX.shape[1])))
        dXs.append(dX.astype(np.float32))
        dys.append(dy)
        ks.append(kind)
    if not dXs:
        return np.zeros((0, width), np.float32), np.zeros(0, np.float32), np.zeros(0, "U12")
    return np.concatenate(dXs), np.concatenate(dys), np.concatenate(ks)


def train(dX: np.ndarray, dy: np.ndarray, *, seed: int = 0, lams=(100.0, 1000.0, 1e4, 1e5)) -> tuple[Ridge, dict]:
    """Ridge advantage model; λ by 5-fold CV. Reports holdout correlation and the mean
    realised advantage of the pairs the model would switch to (pred > 0)."""
    rng = np.random.default_rng(seed)
    fold = rng.integers(0, 5, len(dy))
    best = None
    for lam in lams:
        pred = np.zeros(len(dy))
        for f in range(5):
            m = Ridge(dX.shape[1], lam).fit(dX[fold != f], dy[fold != f], center=False)
            pred[fold == f] = m.predict(dX[fold == f])
        corr = float(np.corrcoef(pred, dy)[0, 1]) if len(dy) > 2 and np.std(pred) > 0 else 0.0
        sw = pred > 0
        stats = {"lam": lam, "cv_corr": corr, "switch_rate": float(sw.mean()),
                 "switch_gain": float(dy[sw].mean()) if sw.any() else 0.0}
        if best is None or corr > best[1]["cv_corr"]:
            best = (lam, stats)
    m = Ridge(dX.shape[1], best[0]).fit(dX, dy, center=False)
    return m, {**best[1], "pairs": int(len(dy)), "label_mean": float(dy.mean()), "label_sd": float(dy.std())}


# ---------------------------------------------------------------------------- state values


def load_states(out: Path, pattern: str = "states_it*.npz") -> dict[str, np.ndarray]:
    """Every finished ``states_it*.npz`` (``pattern``) in ``out``, one run's rows kept together
    and in order; older feature widths are zero-padded (features are only ever appended)."""
    width = len(feature_names())
    parts: dict[str, list[np.ndarray]] = {f: [] for f in STATE_FIELDS}
    for f in sorted(out.glob(pattern)):
        if f.name.endswith(".partial.npz"):
            continue
        with np.load(f) as d:
            if "X" not in d.files:
                continue
            for k in STATE_FIELDS:
                parts[k].append(d[k])
        parts["X"][-1] = fit_width(parts["X"][-1], width).astype(np.float32)
    if not parts["X"]:
        return {"X": np.zeros((0, width), np.float32), "visit": np.zeros(0, np.int16), "explored": np.zeros(0, bool),
                "run": np.zeros(0, np.int64), "crown": np.zeros(0, np.int8), "outcome": np.zeros(0, np.float32)}
    return {k: np.concatenate(v) for k, v in parts.items()}


def load_trials(out: Path) -> dict[str, np.ndarray]:
    """The trials of every finished ``rct_it*.npz`` in ``out`` (``TRIAL_FIELDS``, the ``t_``
    dropped: xa, xt, kind, control, visit, run, crown, outcome). Files collected before
    2026-11-02 repeat a leave / boss trial at every encounter step after it; those copies
    (same run, kind, control and after-states as the trial before) are dropped."""
    width = len(feature_names())
    parts: dict[str, list[np.ndarray]] = {f[2:]: [] for f in TRIAL_FIELDS}
    for f in sorted(out.glob("rct_it*.npz")):
        if f.name.endswith(".partial.npz"):
            continue
        with np.load(f) as d:
            if "t_xa" not in d.files:
                continue
            cols = {k: d[k] for k in TRIAL_FIELDS}
        xa, xt = cols["t_xa"], cols["t_xt"]
        copy = np.zeros(len(xa), bool)
        copy[1:] = ((cols["t_run"][1:] == cols["t_run"][:-1]) & (cols["t_kind"][1:] == cols["t_kind"][:-1])
                    & (cols["t_control"][1:] == cols["t_control"][:-1])
                    & (xa[1:] == xa[:-1]).all(1) & (xt[1:] == xt[:-1]).all(1))
        for k, v in cols.items():
            v = v[~copy]
            parts[k[2:]].append(fit_width(v, width).astype(np.float32) if k in ("t_xa", "t_xt") else v)
    if not parts["xa"]:
        return {"xa": np.zeros((0, width), np.float32), "xt": np.zeros((0, width), np.float32),
                "kind": np.zeros(0, "U12"), "control": np.zeros(0, bool), "visit": np.zeros(0, np.int16),
                "run": np.zeros(0, np.int64), "crown": np.zeros(0, np.int8), "outcome": np.zeros(0, np.float32)}
    return {k: np.concatenate(v) for k, v in parts.items()}


def lambda_returns(value: np.ndarray, run: np.ndarray, visit: np.ndarray, final: np.ndarray, lam: float) -> np.ndarray:
    """λ-return label of each state (rows grouped by run, in play order). The last state of a
    run is labelled with the run's outcome; inside one shop visit (same ``visit``) a state
    takes the next state's label (the visit's later moves are part of what it leads to);
    across visits ``(1 − λ)`` × ``value`` of the next state + ``λ`` × its label. λ = 1 is
    the plain Monte-Carlo outcome; smaller λ leans on the model and cuts outcome noise."""
    y = np.empty(len(run), np.float64)
    for i in range(len(run) - 1, -1, -1):
        if i == len(run) - 1 or run[i + 1] != run[i]:
            y[i] = final[i]
        elif visit[i + 1] == visit[i]:
            y[i] = y[i + 1]
        else:
            y[i] = (1.0 - lam) * value[i + 1] + lam * y[i + 1]
    return y


class _FoldGram:
    """Ridge on standardised features with an unpenalised intercept, by Gram matrices per
    run-grouped fold: every fold's fit (and every new set of labels) costs one solve, not
    another pass building ``AᵀA`` over 100k+ rows."""

    def __init__(self, X: np.ndarray, fold: np.ndarray, k: int, chunk: int = 8192,
                 drop: np.ndarray | None = None) -> None:
        self.X, self.fold, self.k, self.chunk = X, fold, k, chunk
        n = len(X)
        s = np.zeros(X.shape[1])
        for i in range(0, n, chunk):
            s += X[i:i + chunk].astype(np.float64).sum(0)
        self.mu = s / max(1, n)
        v = np.zeros(X.shape[1])
        for i in range(0, n, chunk):
            v += ((X[i:i + chunk].astype(np.float64) - self.mu) ** 2).sum(0)
        sd = np.sqrt(v / max(1, n))
        self.live = sd > 1e-6
        if drop is not None:  # columns the model must not use (weight 0)
            self.live &= ~drop
        self.sd = np.where(self.live, sd, 1.0)
        p = int(self.live.sum()) + 1
        self.n = np.bincount(fold, minlength=k)
        self.G = np.zeros((k, p, p))
        for i, A in self._chunks():
            f = fold[i:i + chunk]
            for j in range(k):
                sel = f == j
                if sel.any():
                    self.G[j] += A[sel].T @ A[sel]

    def _chunks(self):
        for i in range(0, len(self.X), self.chunk):
            a = (self.X[i:i + self.chunk, self.live].astype(np.float64) - self.mu[self.live]) / self.sd[self.live]
            yield i, np.hstack([a, np.ones((len(a), 1))])

    def h(self, y: np.ndarray) -> np.ndarray:
        """``Aᵀy`` per fold."""
        out = np.zeros((self.k, self.G.shape[1]))
        for i, A in self._chunks():
            f, yy = self.fold[i:i + self.chunk], y[i:i + self.chunk]
            for j in range(self.k):
                sel = f == j
                if sel.any():
                    out[j] += A[sel].T @ yy[sel]
        return out

    def solve(self, lam: float, h: np.ndarray, exclude: int | None = None) -> np.ndarray:
        G, hh, n = self.G.sum(0), h.sum(0), int(self.n.sum())
        if exclude is not None:
            G, hh, n = G - self.G[exclude], hh - h[exclude], n - int(self.n[exclude])
        P = np.eye(len(G)) * lam * n / 1000.0  # Ridge's penalty scale
        P[-1, -1] = 0.0
        return np.linalg.solve(G + P, hh)

    def out_of_fold(self, lam: float, h: np.ndarray) -> np.ndarray:
        """Each row predicted by the fit that left its fold out."""
        B = np.stack([self.solve(lam, h, j) for j in range(self.k)], 1)
        pred = np.empty(len(self.X))
        for i, A in self._chunks():
            f = self.fold[i:i + self.chunk]
            pred[i:i + self.chunk] = (A @ B)[np.arange(len(A)), f]
        return pred

    def predict_folds(self, X: np.ndarray, fold: np.ndarray, lam: float, h: np.ndarray) -> np.ndarray:
        """Rows of another matrix, each by the fit that left out its ``fold`` (rows from the
        same runs as a fold are never predicted by a fit that saw those runs)."""
        B = np.stack([self.solve(lam, h, j) for j in range(self.k)], 1)
        A = np.hstack([(X[:, self.live].astype(np.float64) - self.mu[self.live]) / self.sd[self.live],
                       np.ones((len(X), 1))])
        return (A @ B)[np.arange(len(X)), fold]

    def cov(self, lam: float, sigma2: float) -> np.ndarray:
        """Posterior covariance of the weights (live columns, intercept marginalised) of the
        all-folds fit at ``lam``, for labels with residual variance ``sigma2``."""
        n = int(self.n.sum())
        P = np.eye(self.G.shape[1]) * lam * n / 1000.0
        P[-1, -1] = 0.0
        return sigma2 * np.linalg.inv(self.G.sum(0) + P)[:-1, :-1]

    def ridge(self, beta: np.ndarray, lam: float) -> Ridge:
        m = Ridge(self.X.shape[1], lam)
        m.mu, m.sd = self.mu.copy(), self.sd.copy()
        m.w = np.zeros(self.X.shape[1])
        m.w[self.live] = beta[:-1]
        m.b = float(beta[-1])
        m.target = "value"
        return m


def _drop_mask(width: int) -> np.ndarray:
    """``value_drop_mask`` cut or padded to ``width`` columns (synthetic data in tests is narrower)."""
    m = value_drop_mask()
    return m[:width] if len(m) >= width else np.pad(m, (0, width - len(m)))


def _r2(pred: np.ndarray, y: np.ndarray, groups: np.ndarray | None = None) -> float:
    """R² of ``pred`` on ``y``; with ``groups``, of both after removing each group's mean
    (what is left once crown / stage / node are known)."""
    if groups is not None:
        _, inv = np.unique(groups, return_inverse=True)
        cnt = np.bincount(inv)
        y = y - (np.bincount(inv, y) / cnt)[inv]
        pred = pred - (np.bincount(inv, pred) / cnt)[inv]
    ss = float(((y - y.mean()) ** 2).sum())
    return 1.0 - float(((y - pred) ** 2).sum()) / ss if ss > 0 else 0.0


def pairs_check(model, pairs_dir: Path | None) -> float | None:
    """Correlation between a linear value model's predicted difference and the keyed paired
    play-out label (``pairs_it*.npz``: same state, two actions, both played to the end): do
    the decisions it would make point the right way? None without pair data."""
    if pairs_dir is None or not Path(pairs_dir).is_dir() or not isinstance(model, Ridge):
        return None
    dX, dy, _ = load_pairs(Path(pairs_dir))
    if len(dy) < 10:
        return None
    pred = (dX.astype(np.float64) / model.sd) @ model.w
    return round(float(np.corrcoef(pred, dy)[0, 1]), 4) if np.std(pred) > 0 else 0.0


def _value_labels(data: dict[str, np.ndarray], *, lam: float, sweeps: int, folds: int, seed: int, lams,
                  drop: np.ndarray | None = None):
    """(Gram, final λ-return labels, ridge λ, out-of-fold values) by ``train_value``'s sweeps."""
    X, run, visit, final = data["X"], data["run"], data["visit"], data["outcome"].astype(np.float64)
    runs, inv = np.unique(run, return_inverse=True)
    run_fold = np.random.default_rng(seed).integers(0, folds, len(runs))
    fold = run_fold[inv]
    gram = _FoldGram(X, fold, folds, drop=drop)
    gram.runs, gram.run_fold = runs, run_fold  # other rows of the same runs (``train_rct``) share the folds
    y = final.copy()
    best_lam, oof = lams[0], np.zeros(len(y))
    for s in range(max(1, sweeps)):
        h = gram.h(y)
        best = None
        for lm in lams:
            pred = gram.out_of_fold(lm, h)
            mse = float(((pred - y) ** 2).mean())
            if best is None or mse < best[0]:
                best = (mse, lm, pred)
        _, best_lam, oof = best
        if s < sweeps - 1:
            y = lambda_returns(oof, run, visit, final, lam)
    return gram, y, best_lam, oof


def train_value(data: dict[str, np.ndarray], *, lam: float = 0.8, sweeps: int = 3, folds: int = 5, seed: int = 0,
                lams=(1.0, 10.0, 100.0, 1000.0, 1e4, 1e5), pairs_dir: Path | None = None,
                drop: bool = True) -> tuple[Ridge, dict]:
    """Ridge state-value model on λ-returns. Sweep 0 labels with the Monte-Carlo outcome;
    each later sweep relabels with ``lambda_returns`` from the out-of-fold values of the
    previous fit (a state's label never uses a model that saw its own run) and refits, the
    ridge λ chosen by run-grouped CV each time. Reports out-of-fold R² against the final
    outcome overall and within (crown, stage, node), and ``pairs_check``."""
    run, visit, final = data["run"], data["visit"], data["outcome"].astype(np.float64)
    mask = _drop_mask(data["X"].shape[1]) if drop else None
    gram, y, best_lam, oof = _value_labels(data, lam=lam, sweeps=sweeps, folds=folds, seed=seed, lams=lams, drop=mask)
    runs = np.unique(run)
    m = gram.ridge(gram.solve(best_lam, gram.h(y)), best_lam)
    group = data["crown"].astype(np.int64) * 10_000 + visit.astype(np.int64)
    stats = {"lam": best_lam, "td_lambda": lam, "sweeps": sweeps, "states": int(len(y)), "runs": int(len(runs)),
             "explored": float(data["explored"].mean()) if len(y) else 0.0,
             "r2": round(_r2(oof, final), 4), "r2_within": round(_r2(oof, final, group), 4),
             "label_sd": round(float(y.std()), 3), "pairs_corr": pairs_check(m, pairs_dir),
             "dropped": int(mask.sum()) if mask is not None else 0}
    return m, stats


def _mean_diff(a: np.ndarray, b: np.ndarray) -> tuple[float, float]:
    """mean(a) − mean(b) and its t (Welch)."""
    if len(a) < 2 or len(b) < 2:
        return 0.0, 0.0
    d = float(a.mean() - b.mean())
    se = float(np.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b)))
    return round(d, 4), round(d / se, 2) if se > 0 else 0.0


def train_rct(states: dict[str, np.ndarray], trials: dict[str, np.ndarray], *, lam: float = 0.8, sweeps: int = 3,
              folds: int = 5, seed: int = 0, lams=(1.0, 10.0, 100.0, 1000.0, 1e4, 1e5),
              pairs_dir: Path | None = None, shared: bool = False,
              label_lam: float | None = None) -> tuple[Ridge, dict]:
    """Advantage over the champion's choice, from randomised decisions (``_rct_job``).

    ``shared``: the per-class columns (``per_class_mask``) are left out of the difference, so
    the model ranks by what all items share (money, counts, tags, targets, …). The pilot's
    per-class weights came from ~600 buy trials over ~250 classes and lost (sim-game.md).

    ``label_lam``: train on the λ-return from the end of the trial's shop visit (the state
    values out of fold, ``lambda_returns`` with this λ; 0 = the value after the next visit)
    instead of the run's outcome. It cuts the label noise (SD 2.2 → 0.8 at 0.5 on the pilot)
    at the price of leaning on the value model. Every ranking check below still scores
    against the outcome label, which a biased value cannot fake.

    Baseline: ``train_value``'s λ-return value on the same runs' states, all columns (it only
    has to predict, not rank), applied to each trial's control after-state by the fold fit
    that never saw that run. Label: the run's outcome minus that baseline. Model: ridge of the
    label on (taken − control after-state), run-grouped CV on the same folds; the advantage
    of a change is its prediction minus the prediction for no change. Reports the average
    effect of a random deviation (``deviation``: label of deviations − label of controls, a
    check that effects are measurable at all), the out-of-fold correlation of the predicted
    advantage with the label over deviations (``oof_corr``, the causal ranking check, with
    its t), the label gain of the deviations the model would take (``switch_gain``; at each
    benchmark margin, ``switch_by_margin``: [count, gain over controls, t]), the
    deviation effect per kind, and ``pairs_check``."""
    gram, y, vlam, oof = _value_labels(states, lam=lam, sweeps=sweeps, folds=folds, seed=seed, lams=lams)
    pos = np.searchsorted(gram.runs, trials["run"])
    assert len(trials["run"]) == 0 or np.array_equal(gram.runs[np.minimum(pos, len(gram.runs) - 1)], trials["run"]), \
        "every trial's run needs its states"
    tfold = gram.run_fold[pos]
    base = gram.predict_folds(trials["xa"], tfold, vlam, gram.h(y))
    out = trials["outcome"].astype(np.float64)
    r = out - base
    fit_label = r
    if label_lam is not None:
        last = {(int(a), int(b)): i for i, (a, b) in enumerate(zip(states["run"], states["visit"]))}
        row = np.array([last.get((int(a), int(b)), -1) for a, b in zip(trials["run"], trials["visit"])], np.int64)
        G = lambda_returns(oof, states["run"], states["visit"], states["outcome"].astype(np.float64), label_lam)
        fit_label = np.where(row >= 0, G[np.maximum(row, 0)], out) - base
    D = trials["xt"] - trials["xa"]
    if shared:
        mask = per_class_mask()
        D[:, mask[:D.shape[1]] if len(mask) >= D.shape[1] else np.pad(mask, (0, D.shape[1] - len(mask)))] = 0.0
    dev, ctl = ~trials["control"], trials["control"]
    g2 = _FoldGram(D, tfold, folds)
    h2 = g2.h(fit_label)
    zero = np.zeros_like(D[:1]).repeat(len(D), 0)
    best, corr_by = None, {}
    for lm in lams:
        pred = g2.out_of_fold(lm, h2)
        adv = g2.predict_folds(D, tfold, lm, h2) - g2.predict_folds(zero, tfold, lm, h2)
        c = float(np.corrcoef(adv[dev], r[dev])[0, 1]) if dev.sum() > 2 and adv[dev].std() > 0 else 0.0
        corr_by[f"{lm:g}"] = round(c, 4)
        mse = float(((pred - fit_label) ** 2).mean())
        if best is None or mse < best[0]:
            best = (mse, lm, adv, c)
    mse, alam, adv, corr = best
    m = g2.ridge(g2.solve(alam, h2), alam)
    m.target = "rct"
    m.cov, m.live_idx = g2.cov(alam, mse), np.flatnonzero(g2.live)
    se = m.se(D)
    n = int(dev.sum())
    sw = dev & (adv > 0)
    kinds = {}
    for k in sorted(set(trials["kind"][dev].tolist())):
        sel = dev & (trials["kind"] == k)
        kinds[k] = [int(sel.sum()), *_mean_diff(r[sel], r[ctl])]
    deviation, deviation_t = _mean_diff(r[dev], r[ctl])
    gain, gain_t = _mean_diff(r[sw], r[ctl])
    stats = {"lam": alam, "value_lam": vlam, "trials": int(len(r)), "deviations": n,
             "runs": int(len(np.unique(trials["run"]))) if len(r) else 0,
             "baseline_r2": round(_r2(base, out), 4) if len(r) else 0.0,
             "label_sd": round(float(r.std()), 3) if len(r) else 0.0, "label_lam": label_lam,
             "fit_label_sd": round(float(fit_label.std()), 3) if len(r) else 0.0,
             "deviation": deviation, "deviation_t": deviation_t,
             "oof_corr": round(corr, 4), "oof_t": round(float(corr * np.sqrt(max(n - 2, 1)) / np.sqrt(max(1e-9, 1 - corr ** 2))), 2),
             "corr_by_lam": corr_by, "switch_rate": round(float(sw.sum()) / max(1, n), 3),
             "switch_gain": gain, "switch_gain_t": gain_t,
             "switch_by_margin": {f"{th:g}": [int((dev & (adv > th)).sum()), *_mean_diff(r[dev & (adv > th)], r[ctl])]
                                  for th in VALUE_THRESHOLDS},
             "by_kind": kinds,
             "lcb_by_margin": {f"{k:g}": {f"{th:g}": [int((dev & (adv - k * se > th)).sum()),
                                                     *_mean_diff(r[dev & (adv - k * se > th)], r[ctl])]
                                          for th in (0.0, *VALUE_THRESHOLDS)} for k in LCB_PENALTIES},
             "pairs_corr": pairs_check(m, pairs_dir), "shared": shared}
    return m, stats


def train_value_mlp(data: dict[str, np.ndarray], *, lam: float = 0.8, sweeps: int = 3, hidden: tuple[int, ...] = (64,),
                    l2: float = 0.1, seed: int = 0, epochs: int = 60,
                    lams=(1.0, 10.0, 100.0, 1000.0, 1e4, 1e5), drop: bool = True) -> tuple[MLP, dict]:
    """A small MLP state value (it can value item combinations a linear model cannot) on
    ``train_value``'s λ-return labels, stopped early on a held-out tenth of the runs.

    Pilot (512 runs, 4 held-out splits of 102 runs): no better than ridge, R² within −0.022,
    +0.030, +0.003, −0.047 against it, with one hidden layer of 64 and weight decay 0.1.
    Weaker decay over-fits (1e-5: 0.13 vs 0.27), and labels from the MLP's own relabelling
    sweeps were worse than the ridge's. Worth re-testing once there are thousands of runs."""
    X, run = data["X"], data["run"]
    mask = _drop_mask(X.shape[1]) if drop else None
    _, y, _, _ = _value_labels(data, lam=lam, sweeps=sweeps, folds=5, seed=seed, lams=lams, drop=mask)
    if mask is not None:  # train on the dropped columns as constant zero
        X = X.copy()
        X[:, mask] = 0.0
    m = MLP(X.shape[1], hidden, seed=seed)
    fit_with_holdout(m, X, y, run, seed=seed, epochs=epochs, verbose=False, l2=l2)
    if mask is not None:
        m.W[0][mask] = 0.0  # live values of a dropped column must not reach untrained weights
    m.target = "value"
    return m, {"hidden": list(hidden), "l2": l2, "td_lambda": lam, "sweeps": sweeps, "states": int(len(y)),
               "runs": int(len(np.unique(run))), "label_sd": round(float(y.std()), 3)}


def compare_values(out: Path, *, lam: float = 0.8, sweeps: int = 3, hiddens=((64,), (128, 64)), share: float = 0.2,
                   seed: int = 0, pairs_dir: Path | None = None, epochs: int = 60, l2: float = 0.1) -> list[dict[str, Any]]:
    """Ridge vs MLP state values on the states in ``out``: each is trained on the same 80% of
    runs and scored on the other 20% against the final outcome (R², and R² within crown /
    stage / node). Plays nothing."""
    data = load_states(out)
    runs = np.unique(data["run"])
    held = np.isin(data["run"], np.random.default_rng(seed).choice(runs, size=max(1, int(len(runs) * share)), replace=False))
    train = {k: v[~held] for k, v in data.items()}
    test = {k: v[held] for k, v in data.items()}
    final = test["outcome"].astype(np.float64)
    group = test["crown"].astype(np.int64) * 10_000 + test["visit"].astype(np.int64)
    print(f"{len(runs)} runs: training on {len(np.unique(train['run']))}, scoring on {len(np.unique(test['run']))}", flush=True)
    rows = []
    fits = [("ridge", lambda: train_value(train, lam=lam, sweeps=sweeps, seed=seed, pairs_dir=pairs_dir))]
    fits += [(f"mlp {h}", lambda h=h: train_value_mlp(train, lam=lam, sweeps=sweeps, hidden=h, seed=seed, epochs=epochs,
                                                       l2=l2))
             for h in hiddens]
    for name, fit in fits:
        t0 = time.time()
        m, stats = fit()
        pred = m.predict(test["X"])
        row = {"model": name, "r2": round(_r2(pred, final), 4), "r2_within": round(_r2(pred, final, group), 4),
               "pairs_corr": stats.get("pairs_corr"), "label_sd": stats["label_sd"], "secs": round(time.time() - t0)}
        print(f"  {name:14s} held-out r2 {row['r2']:+.3f}  within {row['r2_within']:+.3f}  "
              f"pairs {row['pairs_corr']}  ({row['secs']}s)", flush=True)
        rows.append(row)
    return rows


def curve(out: Path, sizes: list[int], lambdas: list[float], *, sweeps: int = 3,
          pairs_dir: Path | None = None) -> list[dict[str, Any]]:
    """Learning curve on the states already collected in ``out``: ``train_value`` on the first
    n runs (n in ``sizes``) for each label λ (λ = 1: Monte Carlo, one sweep). Does the fit
    still improve with more runs, and which λ labels best? No runs are played."""
    data = load_states(out)
    runs = list(dict.fromkeys(data["run"].tolist()))
    print(f"{len(runs)} runs, {len(data['run'])} states in {out}", flush=True)
    rows = []
    for n in sizes:
        if n > len(runs):
            continue
        keep = np.isin(data["run"], runs[:n])
        part = {k: v[keep] for k, v in data.items()}
        for lam in lambdas:
            _, fit = train_value(part, lam=lam, sweeps=1 if lam >= 1 else sweeps, pairs_dir=pairs_dir)
            print(f"  runs {n:5d}  λ {lam:.2f}  r2 {fit['r2']:+.3f}  within {fit['r2_within']:+.3f}  "
                  f"pairs {fit['pairs_corr']}  ridge {fit['lam']:g}  label sd {fit['label_sd']}", flush=True)
            rows.append({"runs": n, **fit})
    return rows


def make_jobs(n: int, seed: int, characters: list[str], crowns: list[int], **extra) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    return [{"character": rng.choice(characters), "crown": rng.choice(crowns), "seed": seed * 100_000 + i, **extra}
            for i in range(n)]


def main(argv: list[str] | None = None) -> int:
    import multiprocessing as mp

    ap = argparse.ArgumentParser(description="policy iteration from self-play (state value or paired play-outs)")
    ap.add_argument("--target", choices=("value", "pairs", "rct"), default="value",
                    help="value: state value on lambda-returns (default); pairs: advantage from paired play-outs; "
                         "rct: advantage from randomised decisions")
    ap.add_argument("--iterations", type=int, default=3)
    ap.add_argument("--runs", type=int, default=256, help="data runs per iteration")
    ap.add_argument("--p-sample", type=float, default=0.3, help="share of decisions turned into pairs")
    ap.add_argument("--epsilon", type=float, default=0.1, help="value: share of decisions taken at random")
    ap.add_argument("--p-random", type=float, default=0.15, help="rct: share of decisions made trials")
    ap.add_argument("--control", type=float, default=0.25, help="rct: share of trials that keep the champion's choice")
    ap.add_argument("--rct-shared", action="store_true", help="rct: leave per-class columns out of the model")
    ap.add_argument("--rct-penalty", type=float, default=0.0,
                    help="rct: a choice must beat the margin by this many standard errors of its predicted advantage")
    ap.add_argument("--rct-label-lam", type=float, default=None,
                    help="rct: train on the lambda-return after the trial's visit (lambda, e.g. 0.5) instead of the run outcome")
    ap.add_argument("--trial-kinds", default="", help="rct: only these decision kinds are trials, e.g. 'pin' "
                                                      "(default: every kind in VALUE_KINDS)")
    ap.add_argument("--td-lambda", type=float, default=0.8, help="value: lambda of the lambda-return labels")
    ap.add_argument("--sweeps", type=int, default=3, help="value: relabel-and-refit rounds per fit")
    ap.add_argument("--check-pairs", default=str(PAIRS_CHECK_DIR),
                    help="value: keyed pair data to check the model's decisions against ('' = none)")
    ap.add_argument("--plain-rng", action="store_true",
                    help="unkeyed play-outs (labels measured ~0 test-retest reliability vs 0.21 keyed)")
    ap.add_argument("--eval-runs", type=int, default=256)
    ap.add_argument("--margins", default="",
                    help="margins to benchmark a model at, e.g. '0.3' (default: 0.1,0.3,0.6 for value / rct); "
                         "with one margin the eval step is skipped and the model goes straight to the confirm test")
    ap.add_argument("--characters", default="WetDennis")
    ap.add_argument("--crowns", default="0")
    ap.add_argument("--workers", type=int, default=max(1, (mp.cpu_count() or 2)))
    ap.add_argument("--dir", default=None, help=f"default {VALUE_DIR} (value) / {DEFAULT_DIR} (pairs) / {RCT_DIR} (rct)")
    ap.add_argument("--wordlist", default=None)
    ap.add_argument("--boss-risk", default=str(BOSS_RISK_PATH),
                    help="bossrisk.py table for the boss draft ('' = Fast Advice's fixed rule)")
    ap.add_argument("--collect-only", action="store_true",
                    help="play and store the iterations' data runs, no fit or benchmark (a pilot; a later "
                         "normal run reuses the data)")
    ap.add_argument("--curve", default="", help="value: learning curve on the stored states at these run counts "
                                                 "(e.g. 128,256,512), then exit")
    ap.add_argument("--curve-lambdas", default="0.8,0.95,1", help="label lambda values for --curve")
    ap.add_argument("--compare-mlp", default="", help="value: ridge vs MLPs of these hidden sizes on held-out runs "
                                                       "of the stored states (e.g. '64;128,64'), then exit")
    ap.add_argument("--value-model", default="ridge", help="value: 'ridge' or MLP hidden sizes, e.g. '64'")
    ap.add_argument("--mlp-l2", type=float, default=0.1, help="value: MLP weight decay")
    args = ap.parse_args(argv)
    risk = args.boss_risk if args.boss_risk and Path(args.boss_risk).is_file() else ""

    value, rct = args.target == "value", args.target == "rct"
    out = Path(args.dir or (VALUE_DIR if value else RCT_DIR if rct else DEFAULT_DIR))
    out.mkdir(parents=True, exist_ok=True)
    pairs_dir = Path(args.check_pairs) if (value or rct) and args.check_pairs else None
    if args.curve:
        curve(out, [int(n) for n in args.curve.split(",")], [float(v) for v in args.curve_lambdas.split(",")],
              sweeps=args.sweeps, pairs_dir=pairs_dir)
        return 0
    if args.compare_mlp:
        hiddens = [tuple(int(v) for v in h.split(",")) for h in args.compare_mlp.split(";")]
        compare_values(out, lam=args.td_lambda, sweeps=args.sweeps, hiddens=hiddens, pairs_dir=pairs_dir, l2=args.mlp_l2)
        return 0
    chars = [c for c in args.characters.split(",") if c]
    crowns = [int(c) for c in args.crowns.split(",") if c]
    setup = {"characters": chars, "crowns": crowns, "runs": args.runs, "eval_runs": args.eval_runs,
             "target": args.target}
    if value:
        setup |= {"epsilon": args.epsilon}
    elif rct:
        setup |= {"p_random": args.p_random, "control": args.control}
        if args.trial_kinds:
            setup["trial_kinds"] = sorted(args.trial_kinds.split(","))
    else:
        setup |= {"p_sample": args.p_sample, "keyed": not args.plain_rng}
    cfg_path = out / "config.json"
    if cfg_path.is_file():
        old = json.loads(cfg_path.read_text())
        old.setdefault("target", "pairs")  # directories from before the value target
        if old != setup:
            raise SystemExit(f"{out} was started with {old}; use those settings or another --dir")
    else:
        atomic_write(cfg_path, json.dumps(setup, indent=1))
    hist_path = out / "history.json"
    history = json.loads(hist_path.read_text()) if hist_path.is_file() else []
    eval_jobs = make_jobs(args.eval_runs, 777, chars, crowns, boss_risk=risk)
    kw = {"workers": args.workers, "wordlist": args.wordlist}

    def ev(jobs, name: str, model: str | None, threshold: float | None = None) -> dict[str, Any]:
        th = "" if threshold is None else f"_th{threshold}"
        return evaluate(jobs, model=model, threshold=threshold, cache=out / "evals" / f"{name}_{model_tag(model)}{th}.jsonl", **kw)
    champ_path = out / "champion.npz"
    champ = str(champ_path) if champ_path.is_file() else None
    if not history and not args.collect_only:
        base = ev(eval_jobs, "eval", None)
        base.pop("per_seed")
        print("baseline (Fast Advice):", base, flush=True)
        history.append({"iteration": "baseline", "eval": base})
        atomic_write(hist_path, json.dumps(history, indent=1))
    confirm_jobs = make_jobs(args.eval_runs, 778, chars, crowns, boss_risk=risk)
    champ_confirm = next((h["confirm"] for h in reversed(history) if h.get("champion")), None)
    if champ and not args.collect_only and not any(h.get("champion") and "paired" in h for h in history):
        # Champion promoted by the old win-count rule: re-check it with the paired test.
        base = ev(confirm_jobs, "confirm", None)
        cur = ev(confirm_jobs, "confirm", champ)
        test = paired_test(cur["per_seed"], base["per_seed"])
        print(f"re-check champion vs Fast Advice on confirm seeds: {test}", flush=True)
        if test["t"] < PROMOTE_T:
            print("  demoted: Fast Advice stays the champion", flush=True)
            champ_path.rename(out / "champion_demoted.npz")
            champ, champ_confirm = None, base
        else:
            champ_confirm = cur
        history.append({"iteration": "recheck", "champion": champ is not None, "paired": test,
                        "confirm": cur if champ else base})
        atomic_write(hist_path, json.dumps(history, indent=1))
    # Iterations with a history row are done; a data file without one is reused by collect().
    start = len([h for h in history if isinstance(h.get("iteration"), int)])
    for it in range(start, start + args.iterations):
        print(f"iteration {it}: {args.runs} runs by {'champion' if champ else 'Fast Advice'}", flush=True)
        if value:
            stats = collect(make_jobs(args.runs, 2000 + it, chars, crowns, epsilon=args.epsilon, boss_risk=risk),
                            model=champ, out=out / f"states_it{it:03d}.npz", job=_states_job, fields=STATE_FIELDS,
                            label="states", **kw)
            if args.collect_only:
                print(f"  stored: {stats}", flush=True)
                continue
            if args.value_model == "ridge":
                m, fit = train_value(load_states(out), lam=args.td_lambda, sweeps=args.sweeps, seed=it, pairs_dir=pairs_dir)
                weak, why = fit["r2_within"] < MIN_R2_WITHIN, f"r2_within < {MIN_R2_WITHIN}"
            else:
                m, fit = train_value_mlp(load_states(out), lam=args.td_lambda, sweeps=args.sweeps, seed=it,
                                         hidden=tuple(int(v) for v in args.value_model.split(",")), l2=args.mlp_l2)
                weak, why = False, ""
        elif rct:
            stats = collect(make_jobs(args.runs, 2000 + it, chars, crowns, p_random=args.p_random, control=args.control,
                                      trial_kinds=sorted(args.trial_kinds.split(",")) if args.trial_kinds else None,
                                      boss_risk=risk),
                            model=champ, out=out / f"rct_it{it:03d}.npz", job=_rct_job, fields=RCT_FIELDS,
                            label="trials", **kw)
            if args.collect_only:
                print(f"  stored: {stats}", flush=True)
                continue
            m, fit = train_rct(load_states(out, "rct_it*.npz"), load_trials(out), lam=args.td_lambda,
                               sweeps=args.sweeps, seed=it, pairs_dir=pairs_dir, shared=args.rct_shared,
                               label_lam=args.rct_label_lam)
            m.penalty = args.rct_penalty
            weak, why = fit["oof_corr"] < MIN_CORR, f"oof_corr < {MIN_CORR}"
        else:
            stats = collect(make_jobs(args.runs, 2000 + it, chars, crowns, p_sample=args.p_sample, boss_risk=risk,
                                      keyed=not args.plain_rng),
                            model=champ, out=out / f"pairs_it{it:03d}.npz", **kw)
            if args.collect_only:
                print(f"  stored: {stats}", flush=True)
                continue
            dX, dy, _ = load_pairs(out)
            m, fit = train(dX, dy, seed=it)
            weak, why = fit["cv_corr"] < MIN_CORR, f"cv_corr < {MIN_CORR}"
        print("  fit:", fit, flush=True)
        if hasattr(m, "top_features"):  # linear models
            print("  top features:", [(n, round(w, 3)) for n, w in m.top_features(12)], flush=True)
        path = out / f"model_it{it:03d}.npz"
        thresholds = VALUE_THRESHOLDS if value or rct else THRESHOLDS
        if args.margins:
            thresholds = tuple(float(v) for v in args.margins.split(","))
        if weak:
            m.threshold = thresholds[-1]
            m.save(path)
            row = {"iteration": it, "model": str(path), "champion": False, "data": stats, "fit": fit,
                   "skipped": f"{why}: collecting more data before benchmarking"}
            print(json.dumps(row), flush=True)
            history.append(row)
            atomic_write(hist_path, json.dumps(history, indent=1))
            continue
        best_ev, best_th = None, thresholds[0]
        for th in thresholds if len(thresholds) > 1 else ():  # one margin: nothing to choose, confirm only
            m.threshold = th
            m.save(path)
            res = ev(eval_jobs, "eval", str(path), th)
            res.pop("per_seed")
            print(f"  margin {th}: {res}", flush=True)
            if best_ev is None or (res["wins"], res["mean_outcome"]) > (best_ev["wins"], best_ev["mean_outcome"]):
                best_ev, best_th = res, th
        m.threshold = best_th
        m.save(path)
        # Margin chosen on the benchmark seeds; promotion is decided on fresh seeds by a
        # paired test (same seeds, deterministic runs): mean per-seed outcome gain > 1.65 SE.
        conf = ev(confirm_jobs, "confirm", str(path))
        if champ_confirm is None or "per_seed" not in champ_confirm:
            champ_confirm = ev(confirm_jobs, "confirm", champ)
        test = paired_test(conf["per_seed"], champ_confirm["per_seed"])
        print(f"  confirm: {conf['wins']} wins / mean {conf['mean_outcome']:.3f} vs champion "
              f"{champ_confirm['wins']} / {champ_confirm['mean_outcome']:.3f}; paired {test}", flush=True)
        promoted = test["t"] >= PROMOTE_T
        if promoted:
            m.save(champ_path)
            shutil.copyfile(champ_path, out / f"champion_it{it:03d}.npz")
            champ, champ_confirm = str(champ_path), conf
        row = {"iteration": it, "model": str(path), "threshold": best_th, "champion": promoted,
               "data": stats, "fit": fit, "eval": best_ev, "confirm": conf, "paired": test}
        print(json.dumps(row), flush=True)
        history.append(row)
        atomic_write(hist_path, json.dumps(history, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
