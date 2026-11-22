"""The assistant's search path is the eval's: with search on, advise_game picks what
``Searcher.choose`` picks for the same state and per-decision key (shop, boss draft, pin
reward); the stage knobs of ``SearchConfig`` are off by default."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("torch")

from cursed_words_solver.rl import assistant as A  # noqa: E402
from cursed_words_solver.rl import rules as R  # noqa: E402
from cursed_words_solver.rl import search as S  # noqa: E402
from cursed_words_solver.rl import store  # noqa: E402
from cursed_words_solver.rl.env import CWEnv, pack  # noqa: E402
from cursed_words_solver.rl.model import Actor, Policy, default_config  # noqa: E402
from cursed_words_solver.sim.game.encounter import SubmitResult  # noqa: E402
from cursed_words_solver.sim.game.player import Node  # noqa: E402
from cursed_words_solver.sim.game.run import Game, RunConfig  # noqa: E402

TINY = {"top": 2, "sims": 1, "horizon": 0.5, "max_steps": 10, "margin": 1.0, "min_prob": 0.0}


class _NoWords:
    wordlist = None

    def words(self, game, top_n=5):
        return []


@pytest.fixture
def model(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "RL_HOME", tmp_path)
    monkeypatch.delenv(A.TARGET_ENV, raising=False)
    monkeypatch.delenv(R.BOSS_RULE_ENV, raising=False)
    monkeypatch.delenv(A.CURSED_MARGIN_ENV, raising=False)
    monkeypatch.setattr(A, "SEARCH_DEFAULT", dict(TINY))
    import torch

    torch.manual_seed(0)
    m = Policy(default_config()).eval()
    monkeypatch.setattr(A, "_model_entry", lambda path: (m, False))
    return m


def _shop(seed=5):
    """The first shop (the opening encounter won outright), with money to spend."""
    g = Game(RunConfig(character="BonesTheDog", ascension=1, seed=seed))
    enc = g.encounter
    enc.remaining_target = 0
    enc._try_next_grid(SubmitResult(0, [], 0, g.player.money, g.player.money))
    g._after_encounter_action()
    g.player.money = 12
    assert g.phase == "shop"
    return g


def _boss(seed=3):
    g = Game(RunConfig(character="SockHead", ascension=6, seed=seed))
    g.player.run.node = Node.BOSS_DRAFT
    assert g.phase == "boss_draft"
    return g


def _pin(seed=5):
    g = Game(RunConfig(character="BonesTheDog", ascension=1, seed=seed))
    g.player.run.node = Node.BOSS_REWARD
    assert g.phase == "pin_reward"
    return g


def _advise(g, **kw):
    return A.advise_game(g, cands=_NoWords(), model_path=Path("unused.pt"), plan_steps=1, boss_rule=0, **kw)


def _searcher_pick(model, g) -> tuple[str, str, S.Searcher]:
    """(label of Searcher.choose's pick, policy argmax label, searcher) as play.py decides."""
    env = CWEnv(_NoWords())
    st = env.attach(g)
    assert len(st.cands) >= 2
    sr = S.Searcher(Actor(model, greedy=True), S.SearchConfig(**A.SEARCH_DEFAULT))
    pk = pack(st)
    i = sr.choose(env, st, pk, key=A.decision_key(g, g.phase))
    probs, _, _ = sr.actor.evaluate(pk)
    return A.label(st.cands[i].action), A.label(st.cands[int(np.argmax(probs))].action), sr


def _keyed_rollouts(monkeypatch):
    """Rollout values that depend only on the key and the action: the pick then depends on the key."""
    def roll(env, a, actor, key, cfg, *rest):
        return (S._key_seed(f"{key}|{A.label(a)}") % 1000) / 1000.0

    monkeypatch.setattr(S, "rollout_value", roll)


@pytest.mark.parametrize("make", [_shop, _boss, _pin])
def test_advise_pick_is_searcher_choose(model, monkeypatch, make):
    monkeypatch.setenv(A.CURSED_MARGIN_ENV, "0")   # boss: the Searcher's pick, not the cursed rule
    _keyed_rollouts(monkeypatch)
    adv = _advise(make(), search=True)
    want, _, sr = _searcher_pick(model, make())
    assert sr.last is not None                     # it searched
    assert A.label(adv.pick.action) == want


def test_advise_pick_is_searcher_choose_real_rollouts(model, monkeypatch):
    monkeypatch.setattr(A, "SEARCH_DEFAULT", {**TINY, "max_steps": 2})   # short real rollouts
    adv = _advise(_shop(), search=True)
    want, _, sr = _searcher_pick(model, _shop())
    assert sr.last is not None and A.label(adv.pick.action) == want
    assert any("look-ahead" in o.note for o in adv.options)


def test_decision_key_varies_with_the_state():
    g = _shop()
    k = A.decision_key(g, g.phase)
    assert k.startswith("assist|") and k != "assist|search" and k == A.decision_key(_shop(), "shop")
    g.player.money += 1
    assert A.decision_key(g, "shop") != k
    assert A.decision_key(_shop(), "boss_draft") != k
    assert A.decision_key(_shop(seed=5), "shop") == k


def test_cursed_margin_env_default_on(model, monkeypatch):
    """Default: the boss pick is the cursed-preference rule's even with search on."""
    calls = []
    monkeypatch.setattr(A, "_look_ahead", lambda *a, **k: calls.append(1))
    ruled = _advise(_boss(), search=False)
    adv = _advise(_boss(), search=True)
    assert A.label(adv.pick.action) == A.label(ruled.pick.action) and not calls
    monkeypatch.setenv(A.CURSED_MARGIN_ENV, "0")
    _advise(_boss(), search=True)
    assert calls                                    # env 0 + search: the Searcher decides


def test_cursed_margin_off_without_search_takes_best_p_win(model, monkeypatch):
    monkeypatch.setenv(A.CURSED_MARGIN_ENV, "0")
    adv = _advise(_boss(), search=False)
    bosses = [o for o in adv.options if o.action.kind == "boss" and o.p_win is not None]
    assert adv.pick is max(bosses, key=lambda o: o.p_win)


def test_plain_advice_unchanged_by_search_knobs(model, monkeypatch):
    """search=False never calls the look-ahead (plain advice output as before)."""
    monkeypatch.setattr(A, "_look_ahead", lambda *a, **k: (_ for _ in ()).throw(AssertionError("searched")))
    for make in (_shop, _boss, _pin):
        adv = _advise(make(), search=False)
        assert adv.pick is not None


def test_policy_path_warns_once_on_champion_fallback(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(store, "RL_HOME", tmp_path)
    monkeypatch.setattr(A, "_WARNED_FALLBACK", set())
    (tmp_path / "ppo_x").mkdir()
    ch = tmp_path / "ppo_x" / "champion.pt"
    ch.write_bytes(b"")
    assert A.policy_path() == ch and A.policy_path() == ch
    err = capsys.readouterr().err
    assert err.count("falling back to the newest champion") == 1
    (tmp_path / "assistant_policy.pt").write_bytes(b"")
    assert A.policy_path() == tmp_path / "assistant_policy.pt"
    assert "falling back" not in capsys.readouterr().err


class _St:
    def __init__(self, kinds):
        self.cands = [type("C", (), {"action": type("A", (), {"kind": k})()})() for k in kinds]


class _Env:
    def __init__(self, phase, stage):
        run = type("R", (), {"stage": stage})()
        self.game = type("G", (), {"phase": phase, "encounter": None,
                                   "player": type("P", (), {"run": run})()})()


def test_search_stage_knobs_default_off():
    cfg = S.SearchConfig()
    assert cfg.max_stage == 0 and cfg.shop_margin_stage == 0 and cfg.max_steps == 120
    st = _St(["buy", "leave"])
    clear = np.array([0.9, 0.1])     # outside the margin
    close = np.array([0.5, 0.5])
    assert not S.wants_search(_Env("shop", 1), st, clear, cfg)
    assert S.wants_search(_Env("shop", 7), st, close, cfg)
    # shop_margin_stage: early shops always searched
    c2 = S.SearchConfig(shop_margin_stage=2)
    assert S.wants_search(_Env("shop", 2), st, clear, c2)
    assert not S.wants_search(_Env("shop", 3), st, clear, c2)
    assert not S.wants_search(_Env("encounter", 1), _St(["reroll_grid", "submit"]), clear, c2)
    # max_stage: no shop / encounter search past it; drafts still searched
    c3 = S.SearchConfig(max_stage=3)
    assert S.wants_search(_Env("shop", 3), st, close, c3)
    assert not S.wants_search(_Env("shop", 4), st, close, c3)
    assert not S.wants_search(_Env("encounter", 4), _St(["reroll_grid", "submit"]), close, c3)
    assert S.wants_search(_Env("boss_draft", 6), _St(["boss", "boss"]), clear, c3)
    assert S.wants_search(_Env("pin_reward", 6), _St(["pin", "pin"]), clear, c3)


def test_decision_key_varies_inside_an_encounter():
    from cursed_words_solver.sim.game.run import Game, RunConfig

    g = Game(RunConfig(character="BonesTheDog", ascension=2, seed=3))
    assert g.phase == "encounter"
    k = A.decision_key(g, g.phase)
    g.encounter.remaining_target -= 1
    assert A.decision_key(g, g.phase) != k
