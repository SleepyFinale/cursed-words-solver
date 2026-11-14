"""Pivot targets: the run starts FREE and, from a pivot stage, re-reads the build the owned items
lean to at each shop entry (targets.lean / pivot_update, play.PivotTracker, ppo.sample_job pivot,
evaluate pivot arms, assistant pivot mode)."""

from __future__ import annotations

import json
import random

import pytest

torch = pytest.importorskip("torch")

from cursed_words_solver.rl import assistant as A  # noqa: E402
from cursed_words_solver.rl import evaluate as E  # noqa: E402
from cursed_words_solver.rl import ppo as P  # noqa: E402
from cursed_words_solver.rl import store  # noqa: E402
from cursed_words_solver.rl import targets as TG  # noqa: E402
from cursed_words_solver.rl.env import CWEnv, potential  # noqa: E402
from cursed_words_solver.rl.targets import FREE, SAMPLE_PLANS, lean, lean_scores, pivot_update  # noqa: E402
from cursed_words_solver.sim.game.encounter import SubmitResult  # noqa: E402
from cursed_words_solver.sim.game.items import make_item  # noqa: E402
from cursed_words_solver.sim.game.player import Node  # noqa: E402
from cursed_words_solver.sim.game.run import Game, RunConfig  # noqa: E402
from cursed_words_solver.sim.game.shop import Shop  # noqa: E402

CARDS_GEN = ("Bicycle", "Joker", "MusicalNotes", "PostalHorn")       # Cards generators only
NUM_GEN = ("BarChart", "PizzaSlice", "PetriDish")                     # Numbers generators only
NUM_FIT = "Abacus"                                                    # fits Numbers only
NEUTRAL = "Dartboard"                                                 # no build


def _game(ch="BonesTheDog", crown=0, seed=1, items=()):
    g = Game(RunConfig(character=ch, ascension=crown, seed=seed))
    own(g, items)
    return g


def own(g: Game, items) -> None:
    """Set the owned items directly: sticker slots first, then stamp slots (lean counts both)."""
    p = g.player
    p.stickers[:] = [None] * len(p.stickers)
    p.stamps[:] = [None] * len(p.stamps)
    slots = [(p.stickers, k) for k in range(len(p.stickers))] + [(p.stamps, k) for k in range(len(p.stamps))]
    for (lst, k), cls in zip(slots, items):
        lst[k] = make_item(cls)


def _shop(g: Game, stage: int, node: Node = Node.SHOP_ONE) -> None:
    p = g.player
    p.run.stage, p.run.node = stage, node
    g.encounter = None
    g.shop = Shop(p, g.rng)


def test_pure_test_items_are_what_the_tests_assume():
    for c in CARDS_GEN:
        assert TG.item_class("Cards", c) == "generator"
    for c in NUM_GEN:
        assert TG.item_class("Numbers", c) == "generator"
    assert TG.item_class("Numbers", NUM_FIT) == "fits"
    for c in (*CARDS_GEN, *NUM_GEN, NUM_FIT, NEUTRAL):
        on = [p for p in SAMPLE_PLANS if TG.item_class(p, c) in ("generator", "fits")]
        assert len(on) <= 1, (c, on)


# ------------------------------------------------------------------ lean

def test_lean_scores_weights_and_pin_ignored():
    g = _game(items=(CARDS_GEN[0], NUM_FIT, NEUTRAL))
    sc = lean_scores(g)
    assert set(sc) == set(SAMPLE_PLANS) and "Colourless" not in sc
    assert sc["Cards"] == 1.5 and sc["Numbers"] == 1.0
    assert sum(sc.values()) == 2.5
    g.player.pin = make_item(CARDS_GEN[1])          # the pin is not counted
    assert lean_scores(g)["Cards"] == 1.5


def test_lean_min_score():
    assert lean(_game()) == FREE                                       # nothing owned
    assert lean(_game(items=CARDS_GEN[:1])) == FREE                    # 1.5 < 2
    assert lean(_game(items=CARDS_GEN[:2])) == "Cards"                 # 3.0
    assert lean(_game(items=CARDS_GEN[:2]), min_score=3.5) == FREE
    assert lean(_game(items=(NUM_FIT, NUM_FIT))) == "Numbers"          # 2.0 == min_score


def test_lean_hysteresis():
    g = _game(items=(*CARDS_GEN[:2], *NUM_GEN[:3]))                    # Cards 3.0, Numbers 4.5
    assert lean(g) == "Numbers"                                        # no current: the best
    assert lean(g, "Cards") == "Cards"                                 # 3.0 >= 4.5 - 2: kept
    assert lean(g, "Cards", margin=1.0) == "Numbers"
    own(g, (*CARDS_GEN[:2], *NUM_GEN[:3], NUM_FIT))                    # Numbers 5.5: 3.0 < 3.5
    assert lean(g, "Cards") == "Numbers"
    own(g, (*CARDS_GEN[:1], NEUTRAL))                                  # current fell below min_score
    assert lean(g, "Cards") == FREE


def test_lean_ties():
    g = _game(items=(*CARDS_GEN[:2], *NUM_GEN[:2]))                    # 3.0 each
    assert lean(g) == "Numbers"                                        # first in PLANS order
    assert TG.PLANS.index("Numbers") < TG.PLANS.index("Cards")
    assert lean(g, "Cards", margin=0.0) == "Cards"                     # current tied for best: kept
    assert lean(g, "Red", margin=0.0) == "Numbers"                     # current not among the best


def test_pivot_update_waits_for_the_stage():
    g = _game(items=CARDS_GEN[:3])
    g.player.run.stage = 1
    assert pivot_update(g, 2, FREE) == FREE
    assert pivot_update(g, 2, "Cards") == FREE                         # before the stage: FREE
    g.player.run.stage = 2
    assert pivot_update(g, 2, FREE) == "Cards"
    assert pivot_update(g, 3, FREE) == FREE


def test_pivot_labels():
    assert TG.pivot_label(3) == "pivot:3"
    assert TG.parse_pivot_label("pivot:3") == 3 and TG.parse_pivot_label("Pivot") == 2
    assert TG.parse_pivot_label("Cards") is None and TG.parse_pivot_label("pivot:x") is None
    assert TG.parse_pivot_label("pivot:0") is None and TG.parse_pivot_label("") is None


# ------------------------------------------------------------------ sample_job

def _jobs(n, **kw):
    rng = random.Random(5)
    out = [P.sample_job(rng, i, 0.25, [1.0] * 8, targets_mix=(0.3, 0.1, 0.1), **kw) for i in range(n)]
    return out, rng.random()


def test_sample_job_pivot_none_is_unchanged():
    base, after = _jobs(300)
    for kw in ({"pivot": None}, {"pivot": (0.0, 2, 4)}):
        jobs, after2 = _jobs(300, **kw)
        assert jobs == base and after2 == after
    assert not any("pivot_stage" in j for j in base)
    assert P.parse_pivot("") is None and P.parse_pivot("0,2,4") is None
    assert P.parse_pivot("0.5,2,4") == (0.5, 2, 4)
    for bad in ("0.5,2", "1.5,2,4", "0.5,0,4", "0.5,4,2"):
        with pytest.raises(ValueError):
            P.parse_pivot(bad)


# sha256 of json(400 jobs from n0 + the rng's next draw), recorded from the pre-pivot sample_job
# (git HEAD 7c99fc3 ppo.sample_job + targets.sample_target), rng Random(5), quest_share 0.25, crowns 1x8
_HEAD_JOBS = {
    (None, 0): "4f18d368204c453294472911e1a53f654efdb7db642ec554266180d775c0f213",
    (None, 123456): "63364a1fcf38b80248b57dfcc3ab4f0d2ea96580bd6ab27312e1d2e8dbbb725b",
    ((0.3, 0.4, 0.3), 0): "373fd03e26d360ff20c59192ccb2daa03fbf7b49211e19c18545dc586a202358",
    ((0.3, 0.4, 0.3), 123456): "f3525d439523b10d034c67bf436c273746e3220e3f9aa01a9093c1606845d1a5",
    ((0.3, 0.1, 0.1), 0): "c98a4310ba8514d3200047a9e004f87d561f0583e24eab01d1d459f14b24b859",
    ((0.3, 0.1, 0.1), 123456): "7bdedbacf137d39bf06cd0e1cc6611dbc75a474239a097163bd83247b3909384",
}


@pytest.mark.parametrize("pivot", [None, (0.0, 2, 4)])
def test_sample_job_matches_pre_pivot_code(pivot):
    import hashlib

    for (mix, n0), want in _HEAD_JOBS.items():
        rng = random.Random(5)
        out = [P.sample_job(rng, i, 0.25, [1.0] * 8, targets_mix=mix, pivot=pivot) for i in range(n0, n0 + 400)]
        out.append(rng.random())
        assert hashlib.sha256(json.dumps(out, sort_keys=True).encode()).hexdigest() == want, (mix, n0)


def test_exit_pivot_arg():
    from cursed_words_solver.rl.exit import own_pivot_arg

    assert own_pivot_arg("") == (False, None)                          # inherit curriculum.json
    assert own_pivot_arg("off") == (True, None) and own_pivot_arg("0,2,4") == (True, None)
    assert own_pivot_arg("0.5,2,4") == (False, (0.5, 2, 4))


def test_pipeline_v2_resume_keeps_old_mix(tmp_path, monkeypatch):
    import argparse

    from cursed_words_solver.rl import pipeline

    monkeypatch.setattr(pipeline, "HOME", tmp_path)
    a = argparse.Namespace(targets_mix=None, pivot=None)
    assert pipeline.v2_target_args(a) == ("0.3,0.1,0.1", "0.5,2,4")    # fresh ppo2
    (tmp_path / "ppo2").mkdir()
    (tmp_path / "ppo2" / "curriculum.json").write_text(json.dumps({"targets_mix": [0.3, 0.4, 0.3]}))
    assert pipeline.v2_target_args(a) == ("0.3,0.4,0.3", "")           # a pre-pivot run resumes unchanged
    (tmp_path / "ppo2" / "curriculum.json").write_text(json.dumps({"targets_mix": [0.3, 0.1, 0.1], "pivot": [0.5, 2, 4]}))
    assert pipeline.v2_target_args(a) == ("0.3,0.1,0.1", "0.5,2,4")
    assert pipeline.v2_target_args(argparse.Namespace(targets_mix="1,0,0", pivot="")) == ("1,0,0", "")


def test_sample_job_pivot_shares():
    base, after = _jobs(4000)
    jobs, after2 = _jobs(4000, pivot=(0.5, 2, 4))
    assert after2 == after                                             # the main stream is untouched
    for a, b in zip(base, jobs):                                       # same character / crown / quest / seed
        assert {k: a[k] for k in ("character", "crown", "quest", "seed")} == \
               {k: b[k] for k in ("character", "crown", "quest", "seed")}
        if "pivot_stage" not in b:
            assert b == a                                              # non-pivot runs: the old target draw
        else:
            assert b["quest"] is None and b["target"] == FREE and 2 <= b["pivot_stage"] <= 4
    plain = [j for j in jobs if not j["quest"]]
    piv = [j for j in plain if j.get("pivot_stage")]
    assert abs(len(piv) / len(plain) - 0.5) < 0.04
    assert {j["pivot_stage"] for j in piv} == {2, 3, 4}
    free = [j for j in plain if not j.get("pivot_stage") and not j["target"]]
    assert abs(len(free) / len(plain) - 0.3) < 0.04                    # 50% pivot, 30% free, 20% targeted
    assert not any(j.get("pivot_stage") for j in jobs if j["quest"])


def test_pivot_stats_and_curriculum():
    rows = [{"character": "BonesTheDog", "crown": 0, "quest": None, "won": True, "target": "Cards", "pivot_stage": 2,
             "pivot_switches": 1, "on_plan": 3},
            {"character": "BonesTheDog", "crown": 0, "quest": None, "won": False, "target": "", "pivot_stage": 3,
             "pivot_switches": 0, "on_plan": 0},
            {"character": "BonesTheDog", "crown": 0, "quest": None, "won": True, "target": "", "on_plan": 0}]
    bt = P.by_target(rows)
    assert bt["pivot"]["n"] == 2 and bt["pivot-Cards"]["n"] == 1 and bt["pivot-free"]["n"] == 1 and bt["free"]["n"] == 1
    assert "Cards" not in bt                                           # pivot runs never fill a fixed-plan bucket
    pv = P.by_pivot(rows)
    assert pv["n"] == 2 and pv["win"] == 0.5 and pv["switches"] == 0.5 and pv["committed"] == 0.5
    assert pv["final"] == {"": 1, "Cards": 1}
    assert pv["stage2"]["n"] == 1 and P.by_pivot(rows[2:]) == {"n": 0}
    c = P.Curriculum()
    for r in rows:
        c.add(r)
    # pivot runs stay out of the target tally (committed ones survived to their pivot stage)
    assert list(c.targets) == [("BonesTheDog", "", 1)]
    assert len(c.chars) == 3


# ------------------------------------------------------------------ play loop

def _clear(game) -> None:
    enc = game.encounter
    enc.remaining_target = 0
    enc._try_next_grid(SubmitResult(0, [], 0, game.player.money, game.player.money))
    game._after_encounter_action()


class _NoWords:
    wordlist = None

    def words(self, game, top_n=5):
        return []

    def with_budget(self, budget):
        return self


@pytest.fixture
def clearing(monkeypatch):
    """Any encounter action wins the encounter (no word engine needed): a run reaches the shops.
    One torch thread (as play workers): many small forwards are slow with thread contention."""
    import cursed_words_solver.rl.env as EN

    n_threads = torch.get_num_threads()
    torch.set_num_threads(1)

    orig = EN.apply

    def fake(g, a):
        if g.phase == "encounter" and g.encounter is not None and g.encounter.michael_draft is None:
            _clear(g)
            return True
        return orig(g, a)

    monkeypatch.setattr(EN, "apply", fake)
    yield
    torch.set_num_threads(n_threads)


def _cycle(monkeypatch):
    """pivot_update -> Red, Blue, Red, ... per shop entry (a switch at every shop), FREE before the stage."""
    seq = iter(["Red", "Blue"] * 50)

    def fake(game, pivot_stage, current=FREE):
        return FREE if game.player.run.stage < pivot_stage else next(seq)

    monkeypatch.setattr(TG, "pivot_update", fake)


def test_tracker_switches_only_at_shop_entry_and_telescopes(clearing, monkeypatch):
    from cursed_words_solver.rl.play import PivotTracker, shaping_bonus

    _cycle(monkeypatch)
    env = CWEnv(_NoWords(), shaping=0.15)
    env.reset(character="BonesTheDog", crown=0, seed=5)
    phi0 = env.phi
    pt = PivotTracker(2, env)
    rew, bon, plain, entries = [], [], [], []
    last = None
    while not env.done:
        g = env.game
        before = env.target
        changed = pt.observe()
        k = (g.player.run.stage, int(g.player.run.node)) if g.phase == "shop" else None
        entry = k is not None and k != last
        if k is not None:
            last = k
        if entry:
            entries.append(k)
        assert changed == (env.target != before)
        if changed:
            assert entry and g.player.run.stage >= 2                    # only at the first decision of a shop visit
        else:
            assert env.target == before
        assert TG.get_target(g) == env.target
        st = env.current()
        acts = [c.action for c in st.cands]
        a = next((x for x in acts if x.kind == "leave"), acts[0])
        bon.append(shaping_bonus(env))
        plain.append(potential(g))
        r, _ = env.step(a)
        rew.append(r)
    res = env.result()
    assert res["outcome"] > 0
    assert pt.switches >= 2 and pt.seen == ["Red", "Blue"][:len(pt.seen)]
    assert all(k[0] >= 2 for k in (e for e in entries[-pt.switches:]))
    assert abs(phi0 + sum(rew) - res["outcome"]) < 1e-6                # potential still telescopes
    g_t = 0.0
    for t in reversed(range(len(rew))):                                # shaped return + bonus = unshaped return
        g_t += rew[t]
        assert abs(g_t + bon[t] - (res["outcome"] - plain[t])) < 1e-6
    assert res["target"] == pt.result()["target"] == env.target


def test_play_pivot_real_lean(clearing, monkeypatch, tmp_path):
    """play() with a net, real lean_scores: the run starts FREE, switches only at shop entries, the
    row carries the pivot fields and the recorded rewards telescope."""
    from cursed_words_solver.rl import play as PL
    from cursed_words_solver.rl.model import Policy, default_config, save_policy

    torch.manual_seed(0)
    path = tmp_path / "w.pt"
    save_policy(Policy(default_config()), path)
    monkeypatch.setattr(PL, "_CANDS", _NoWords())
    calls = []
    orig = PL.PivotTracker.observe

    def spy(self):
        g = self.env.game
        k = (g.player.run.stage, int(g.player.run.node), g.phase)
        ch = orig(self)
        calls.append((k, ch, self.env.target))
        return ch

    monkeypatch.setattr(PL.PivotTracker, "observe", spy)
    job = {"character": "BonesTheDog", "crown": 0, "seed": 5, "quest": None, "policy": str(path), "greedy": True,
           "shaping": 0.15, "record": True, "pivot_stage": 1}
    res = PL.play(job)
    assert not res["error"], res.get("trace")
    assert res["pivot_stage"] == 1 and "targets_seen" in res and "pivot_first_stage" in res
    assert calls and calls[0][2] in (FREE, *SAMPLE_PLANS)
    assert all(k[2] == "shop" for k, ch, _ in calls if ch)
    seen = []
    for (k, ch, t) in calls:
        if ch and t not in seen:
            seen.append(t)
    assert res["targets_seen"] == seen and res["target"] == calls[-1][2]
    assert abs(sum(res["traj"]["reward"]) - res["outcome"]) < 1e-4
    assert len(res["traj"]["bonus"]) == len(res["traj"]["reward"])
    off = PL.play({**job, "pivot_stage": 0, "record": False})           # off: no pivot fields
    assert not off["error"] and "pivot_stage" not in off and off["target"] == FREE


def test_play_pivot_cycle_in_result(clearing, monkeypatch, tmp_path):
    from cursed_words_solver.rl import play as PL
    from cursed_words_solver.rl.model import Policy, default_config, save_policy

    _cycle(monkeypatch)
    torch.manual_seed(0)
    path = tmp_path / "w.pt"
    save_policy(Policy(default_config()), path)
    monkeypatch.setattr(PL, "_CANDS", _NoWords())
    res = PL.play({"character": "BonesTheDog", "crown": 0, "seed": 5, "quest": None, "policy": str(path),
                   "greedy": True, "shaping": 0.15, "record": True, "pivot_stage": 2})
    assert not res["error"], res.get("trace")
    assert res["pivot_switches"] >= 2 and res["targets_seen"] == ["Red", "Blue"]
    assert res["pivot_first_stage"] >= 2 and res["target"] in ("Red", "Blue")
    assert abs(sum(res["traj"]["reward"]) - res["outcome"]) < 1e-4


# ------------------------------------------------------------------ evaluate

def test_eval_pivot_jobs_and_keys():
    jobs = E.eval_jobs(per=1, per_quest=1, crowns=range(1), targets=["", "pivot:2", "Cards"])
    piv = [j for j in jobs if j.get("pivot_stage")]
    assert piv and all(j["target"] == FREE and j["pivot_stage"] == 2 and not j["quest"] for j in piv)
    assert len({E.key(j) for j in jobs}) == len(jobs)
    free = next(j for j in jobs if not j["quest"] and not j["target"] and not j.get("pivot_stage"))
    pj = next(j for j in piv if j["seed"] == free["seed"])
    assert E.key(pj) != E.key(free) and E.key(pj)[:4] == E.key(free)[:4]
    old = {k: free[k] for k in ("character", "crown", "quest", "seed")}   # rows from before targets
    assert E.key(old) == E.key(free) == E.key({**free, "pivot_stage": 0})
    row = {**pj, "target": "Cards", "won": True, "outcome": 16.0}       # final target in the row
    assert E.key(row) == E.key(pj) and E.arm_of(row) == "pivot:2"
    assert E.key({**pj, "pivot_stage": 3}) != E.key(pj)
    assert E.arm_display("pivot:2") == "Pivot from stage 2" and E.arm_display("") == "Free"


def test_eval_vs_free_and_pick_with_pivot_arms():
    rows = []
    for i in range(30):
        base = {"character": "BonesTheDog", "crown": 1, "quest": None, "seed": 100 + i}
        rows.append({**base, "target": "", "won": i < 10, "outcome": 16.0 if i < 10 else 4.0})
        rows.append({**base, "target": "Cards" if i % 2 else "", "pivot_stage": 2, "won": i < 20,
                     "outcome": 16.0 if i < 20 else 4.0})
        rows.append({**base, "target": "Red", "won": i < 12, "outcome": 16.0 if i < 12 else 4.0})
    d = E.vs_free(rows)
    assert d[("pivot:2",)]["n"] == 30 and d[("pivot:2",)]["win_diff"] > 0
    assert set(E.table(rows, "target")) == {"", "pivot:2", "Red"}
    tab = E.pick_table(rows)
    assert tab["BonesTheDog"]["0-3"] == "pivot:2"
    assert E.pivot_report(rows)[0].startswith("Pivot from stage 2: n=30")


def test_run_arm_resumes_pivot_rows(tmp_path):
    jobs = E.eval_jobs(per=1, per_quest=0, crowns=range(1), targets=["", "pivot:2"])[:4]
    rows = [{**j, "target": "Cards" if j.get("pivot_stage") else "", "won": False, "outcome": 1.0, "error": ""}
            for j in jobs]
    for r in rows:
        store.append_jsonl(tmp_path / "arm.jsonl", r)
    got = E.run_arm("arm", "unused.pt", jobs, out_dir=tmp_path, verbose=False)   # all cached: nothing played
    assert len(got) == len(jobs)


# ------------------------------------------------------------------ assistant

@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "RL_HOME", tmp_path)
    monkeypatch.delenv(A.TARGET_ENV, raising=False)
    return tmp_path


def _state(home):
    return json.loads((home / "assistant_run_target.json").read_text(encoding="utf-8"))


def test_assistant_env_and_table_pivot_modes(home, monkeypatch):
    assert A.choose_target("BonesTheDog", 1) == FREE                   # nothing configured: unchanged
    monkeypatch.setenv(A.TARGET_ENV, "pivot")
    assert A.choose_target("BonesTheDog", 1) == "pivot:2"
    monkeypatch.setenv(A.TARGET_ENV, "pivot:3")
    assert A.choose_target("BonesTheDog", 1) == "pivot:3"
    monkeypatch.delenv(A.TARGET_ENV)
    (home / "target_table.json").write_text(json.dumps({"version": 1, "table": {"BonesTheDog": {"0-3": "pivot:3"}}}),
                                            encoding="utf-8")
    assert A.choose_target("BonesTheDog", 1) == "pivot:3"
    g = _game(crown=1)
    assert A.run_target_info(g) == (FREE, {"pivot_stage": 3, "since_stage": None, "first_stage": None,
                                           "switches": 0})
    assert _state(home)["mode"] == "pivot:3"


def test_assistant_pivot_persists_and_reads_at_shop_entries(home, monkeypatch):
    monkeypatch.setenv(A.TARGET_ENV, "pivot:2")
    g = _game(items=CARDS_GEN[:3])
    assert A.run_target_info(g)[0] == FREE                             # stage 1 encounter: start FREE
    _shop(g, 1)
    assert A.run_target(g) == FREE                                     # stage 1 shop: before the pivot stage
    g.player.run.stage, g.player.run.node, g.shop = 2, Node.ENCOUNTER_FIRST, None
    assert A.run_target(g) == FREE                                     # not a shop: no re-read
    _shop(g, 2)
    t, info = A.run_target_info(g)
    assert t == "Cards" and info["since_stage"] == 2 and info["first_stage"] == 2 and info["switches"] == 1
    st = _state(home)
    assert st["target"] == "Cards" and st["last_shop"] == [2, int(Node.SHOP_ONE)]
    own(g, (*CARDS_GEN[:2], *NUM_GEN, NUM_FIT))                         # bought into Numbers in this shop
    assert A.run_target(g) == "Cards"                                  # same shop visit: kept
    _shop(g, 2, Node.SHOP_TWO)
    assert A.run_target(g) == "Numbers"                                # next shop entry: 5.5 vs 3.0 -> pivot
    assert _state(home)["switches"] == 2 and _state(home)["first_stage"] == 2
    g2 = _game(items=CARDS_GEN[:3])                                     # progress went backwards: new run
    assert A.run_target(g2) == FREE and _state(home)["switches"] == 0
    monkeypatch.setenv(A.TARGET_ENV, "Red")                             # an explicit plan still wins
    assert A.run_target_info(g) == ("Red", None)


def test_assistant_pivot_line(home, monkeypatch):
    from pathlib import Path

    from cursed_words_solver.rl.model import Policy, default_config

    m = Policy(default_config()).eval()
    monkeypatch.setattr(A, "_model_entry", lambda path: (m, True))
    monkeypatch.setenv(A.TARGET_ENV, "pivot:2")
    g = _game(items=CARDS_GEN[:3])
    adv = A.advise_game(g, cands=_NoWords(), model_path=Path("unused.pt"), search=False, plan_steps=1)
    assert adv.target == FREE and "Plan" in adv.text() and "Free (pivot from stage 2)" in adv.text()
    _shop(g, 2)
    adv = A.advise_game(g, cands=_NoWords(), model_path=Path("unused.pt"), search=False, plan_steps=1)
    assert adv.target == "Cards" and TG.get_target(g) == "Cards"
    assert "Cards (pivoted at stage 2 - you own 3 Cards items)" in adv.target_line()
    d = adv.as_dict()
    assert d["pivot"]["pivot_stage"] == 2 and "pivoted" in d["target_line"]
    json.dumps(d)
    # unconditioned policy: no plan line, FREE
    monkeypatch.setattr(A, "_model_entry", lambda path: (m, False))
    adv = A.advise_game(g, cands=_NoWords(), model_path=Path("unused.pt"), search=False, plan_steps=1)
    assert adv.target is None and adv.pivot is None


def test_search_rollout_rereads_pivot_target(clearing, monkeypatch):
    """Look-ahead rollouts of a pivot run re-read the target at new shop visits like the real run
    (Searcher.pivot_stage); off (0) they never do. The real game's target is untouched."""
    from cursed_words_solver.rl import play as PL
    from cursed_words_solver.rl.search import SearchConfig, rollout_value

    _cycle(monkeypatch)

    class _Leave:
        def choose(self, pk):
            return 0, 0.0, 0.0

        def evaluate(self, pk):
            return None, 0.0, None

    env = CWEnv(_NoWords())
    env.reset(character="BonesTheDog", crown=0, seed=5)
    seen = []
    orig = PL.PivotTracker.observe

    def spy(self):
        ch = orig(self)
        if ch:
            seen.append(self.env.target)
        return ch

    monkeypatch.setattr(PL.PivotTracker, "observe", spy)
    cfg = SearchConfig(horizon=99, max_steps=5000)
    st = env.current()
    rollout_value(env, st.cands[0].action, _Leave(), "k", cfg)
    assert seen == []
    rollout_value(env, st.cands[0].action, _Leave(), "k", cfg, pivot_stage=1)
    assert seen[:2] == ["Red", "Blue"]
    assert env.target == FREE and TG.get_target(env.game) == FREE
