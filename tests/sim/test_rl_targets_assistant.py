"""Run assistant + target builds: target choice precedence, per-run persistence, and that
the target reaches the game / every env the assistant builds (only for conditioned policies)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")

from cursed_words_solver.rl import assistant as A  # noqa: E402
from cursed_words_solver.rl import obs as O  # noqa: E402
from cursed_words_solver.rl import store  # noqa: E402
from cursed_words_solver.rl.env import CWEnv  # noqa: E402
from cursed_words_solver.rl.model import ModelConfig, Policy, default_config, save_policy  # noqa: E402
from cursed_words_solver.rl.targets import FREE, get_target  # noqa: E402
from cursed_words_solver.sim.game.player import Node  # noqa: E402
from cursed_words_solver.sim.game.run import Game, RunConfig  # noqa: E402


class _NoWords:
    """Candidates stand-in: no engine search."""

    wordlist = None

    def words(self, game, top_n=5):
        return []


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "RL_HOME", tmp_path)
    monkeypatch.delenv(A.TARGET_ENV, raising=False)
    return tmp_path


def _table(home: Path, table: dict) -> None:
    (home / "target_table.json").write_text(json.dumps({"version": 1, "table": table}), encoding="utf-8")


def _game(ch="BonesTheDog", crown=2, seed=1):
    return Game(RunConfig(character=ch, ascension=crown, seed=seed))


def test_choose_target_precedence(home, monkeypatch):
    assert A.choose_target("BonesTheDog", 2) == FREE                     # nothing configured
    _table(home, {"BonesTheDog": {"0-3": "Cards", "4-7": "Curse"}, "NinaNix": {"0-3": "Void+Rainbow"}})
    assert A.choose_target("BonesTheDog", 2) == "Cards"
    assert A.choose_target("BonesTheDog", 5) == "Curse"
    assert A.choose_target("NinaNix", 0) == "Void+Rainbow"
    assert A.choose_target("NinaNix", 6) == FREE                         # no bucket
    assert A.choose_target("Octacles", 1) == FREE                        # no row
    monkeypatch.setenv(A.TARGET_ENV, "Red")
    assert A.choose_target("BonesTheDog", 2) == "Red"
    monkeypatch.setenv(A.TARGET_ENV, "Red-Blue")
    assert A.choose_target("BonesTheDog", 2) == "Red+Blue"
    monkeypatch.setenv(A.TARGET_ENV, "free")
    assert A.choose_target("BonesTheDog", 2) == FREE
    monkeypatch.setenv(A.TARGET_ENV, "auto")
    assert A.choose_target("BonesTheDog", 2) == "Cards"
    monkeypatch.setenv(A.TARGET_ENV, "NotAPlan")
    assert A.choose_target("BonesTheDog", 2) == "Cards"                  # invalid -> auto
    (home / "target_table.json").write_text("{corrupt", encoding="utf-8")
    monkeypatch.delenv(A.TARGET_ENV)
    assert A.choose_target("BonesTheDog", 2) == FREE


def test_run_target_persists_until_a_new_run(home, monkeypatch):
    _table(home, {"BonesTheDog": {"0-3": "Cards"}, "NinaNix": {"0-3": "Void"}})
    g = _game()
    run = g.player.run
    assert A.run_target(g) == "Cards"
    st = json.loads((home / "assistant_run_target.json").read_text(encoding="utf-8"))
    assert st["character"] == "BonesTheDog" and st["crown"] == 2 and st["target"] == "Cards" and st["started"]

    _table(home, {"BonesTheDog": {"0-3": "Numbers"}})                   # table changes mid-run
    assert A.run_target(g) == "Cards"                                    # same run: kept
    run.stage, run.node = 3, Node.SHOP_TWO
    assert A.run_target(g) == "Cards"                                    # progressed: kept
    run.stage, run.node = 3, Node.SHOP_ONE
    assert A.run_target(g) == "Numbers"                                  # went backwards: new run
    run.stage, run.node = 3, Node.SHOP_TWO
    assert A.run_target(g) == "Numbers"

    run.stage, run.node = 1, Node.SHOP_ZERO                              # new run's first shop
    _table(home, {"BonesTheDog": {"0-3": "Chess"}, "NinaNix": {"0-3": "Void"}})
    assert A.run_target(g) == "Chess"
    assert A.run_target(_game("NinaNix", 2)) == "Void"                   # character changed
    assert A.run_target(_game("NinaNix", 5)) == FREE                     # crown changed -> re-chosen
    assert json.loads((home / "assistant_run_target.json").read_text(encoding="utf-8"))["crown"] == 5

    (home / "assistant_run_target.json").write_text("not json", encoding="utf-8")
    assert A.run_target(g) == "Chess"                                    # corrupt file: fresh choice

    monkeypatch.setenv(A.TARGET_ENV, "Red")                              # explicit override wins
    assert A.run_target(g) == "Red"


def test_run_target_meg_shop_is_before_the_boss(home):
    _table(home, {"Spike": {"0-3": "Cash"}})
    g = _game("Spike", 1)
    run = g.player.run
    run.stage, run.node = 2, Node.MEG_SHOP
    assert A.run_target(g) == "Cash"
    _table(home, {"Spike": {"0-3": "Curse"}})
    run.node = Node.BOSS                                                 # Meg shop -> boss: same run
    assert A.run_target(g) == "Cash"
    run.node = Node.BOSS_DRAFT                                           # earlier than the Meg shop: new run
    assert A.run_target(g) == "Curse"


def test_run_target_quest_run_is_free(home):
    from cursed_words_solver.sim.game.challenges import QUESTS, make_challenge

    _table(home, {"BonesTheDog": {"0-3": "Cards"}})
    g = _game()
    g.player.run.challenge = make_challenge(sorted(QUESTS)[0])
    assert A.run_target(g) == FREE
    assert not (home / "assistant_run_target.json").exists()


def _patch_model(monkeypatch, conditioned: bool):
    m = Policy(default_config()).eval()
    monkeypatch.setattr(A, "_model_entry", lambda path: (m, conditioned))


def _attach_spy(monkeypatch) -> list[str]:
    seen: list[str] = []
    orig = CWEnv.attach

    def spy(self, game):
        seen.append(get_target(game))
        return orig(self, game)

    monkeypatch.setattr(CWEnv, "attach", spy)
    return seen


def test_unconditioned_model_is_free_without_plan_line(home, monkeypatch):
    _table(home, {"BonesTheDog": {"0-3": "Cards"}})
    monkeypatch.setenv(A.TARGET_ENV, "Red")
    _patch_model(monkeypatch, False)
    seen = _attach_spy(monkeypatch)
    g = _game()
    adv = A.advise_game(g, cands=_NoWords(), model_path=Path("unused.pt"), search=False, plan_steps=3)
    assert adv.target is None and get_target(g) == FREE
    assert "Target build" not in adv.text() and "Target build" not in adv.html()
    assert adv.as_dict()["target"] is None
    assert seen and set(seen) == {FREE}
    assert not (home / "assistant_run_target.json").exists()


def test_conditioned_model_sets_target_everywhere(home, monkeypatch):
    _table(home, {"BonesTheDog": {"0-3": "Cards"}})
    _patch_model(monkeypatch, True)
    seen = _attach_spy(monkeypatch)
    g = _game()
    adv = A.advise_game(g, cands=_NoWords(), model_path=Path("unused.pt"), search=False, plan_steps=3)
    assert get_target(g) == "Cards" and adv.target == "Cards"
    # sub-envs (shop plan, after-state values) work on clones of the game: they carry the target
    from cursed_words_solver.rl.model import Actor

    actor = Actor(A._model_entry(None)[0], greedy=True)
    A._shop_plan(actor, g, _NoWords(), 1)
    A._value_after(actor, g, adv.options[0].action, _NoWords(), "t")
    assert len(seen) >= 3 and set(seen) == {"Cards"}
    line = adv.text().splitlines()[1]
    assert "Target build for " in line and line.endswith(": Cards") and "BonesTheDog" not in line
    assert "Target build" in adv.html()
    d = adv.as_dict()
    assert d["target"] == "Cards" and d["target_display"] == "Cards"
    json.dumps(d)                                                        # app-friendly
    # explicit argument wins over the persisted choice; FREE is shown as such
    adv = A.advise_game(_game(), cands=_NoWords(), model_path=Path("unused.pt"), search=False, plan_steps=1,
                        target="")
    assert adv.target == FREE and "Free" in adv.text() and "AI chooses" in adv.text()


def test_model_entry_reads_saved_width(tmp_path, monkeypatch):
    v2_g, v2_t = O.LEGACY_GLOBAL[1], O.LEGACY_TOKEN[1]
    with monkeypatch.context() as mp:   # build a v2-width policy as an old checkpoint
        mp.setattr(O, "LEGACY_GLOBAL", ())
        mp.setattr(O, "LEGACY_TOKEN", ())
        cfg2 = ModelConfig(**{**default_config().__dict__, "n_global": v2_g, "n_tok_feat": v2_t})
        save_policy(Policy(cfg2).eval(), tmp_path / "v2.pt")
    save_policy(Policy(default_config()).eval(), tmp_path / "v3.pt")
    m2, c2 = A._model_entry(tmp_path / "v2.pt")
    m3, c3 = A._model_entry(tmp_path / "v3.pt")
    assert (c2, c3) == (False, True)
    assert m2.cfg.n_global == m3.cfg.n_global == O.n_global_features()   # widened on load
    assert A._load(tmp_path / "v3.pt") is m3                             # cached
    # the widened v2 model saved again is v3 wide but has zero weight on the target columns
    save_policy(m2, tmp_path / "v2_resaved.pt")
    ck = torch.load(tmp_path / "v2_resaved.pt", weights_only=False)
    from cursed_words_solver.rl.model import conditioned

    assert conditioned(ck["config"]) and not conditioned(ck["config"], ck["state"])
    assert A._model_entry(tmp_path / "v2_resaved.pt")[1] is False
