"""Deployment rules: the uncursed-boss rule (rl.rules) in play() / evaluate / the assistant, and
target tables (targets.table_target, evaluate table / run --target-table)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")

from cursed_words_solver.rl import assistant as A  # noqa: E402
from cursed_words_solver.rl import evaluate as E  # noqa: E402
from cursed_words_solver.rl import rules as R  # noqa: E402
from cursed_words_solver.rl import store  # noqa: E402
from cursed_words_solver.rl.model import Policy, default_config, save_policy  # noqa: E402
from cursed_words_solver.rl.targets import FREE, table_target  # noqa: E402
from cursed_words_solver.sim.game.agent import Action, legal_actions  # noqa: E402
from cursed_words_solver.sim.game.encounter import SubmitResult  # noqa: E402
from cursed_words_solver.sim.game.player import Node  # noqa: E402
from cursed_words_solver.sim.game.run import Game, RunConfig  # noqa: E402


class _NoWords:
    wordlist = None

    def words(self, game, top_n=5):
        return []

    def with_budget(self, budget):
        return self


def _draft(crown=6, ch="SockHead", seed=3) -> Game:
    """A game at its first boss draft (crown >= 1: one cursed option at stage 1)."""
    g = Game(RunConfig(character=ch, ascension=crown, seed=seed))
    g.player.run.node = Node.BOSS_DRAFT
    assert g.phase == "boss_draft"
    return g


def _cursed_uncursed(g):
    acts = legal_actions(g)
    opts = g.boss_options()
    cur = [a for a in acts if opts[a.args[0]].cursed]
    unc = [a for a in acts if not opts[a.args[0]].cursed]
    assert cur and unc
    return acts, cur[0], unc


# ------------------------------------------------------------------ rules

def test_parse_boss_rule(monkeypatch):
    assert [R.parse_boss_rule(x) for x in (None, "", "0", 0, "off", "x", -3, True, "6", 6, " 5 ")] == \
        [0, 0, 0, 0, 0, 0, 0, 0, 6, 6, 5]
    monkeypatch.delenv(R.BOSS_RULE_ENV, raising=False)
    assert R.env_boss_rule() == 0                                        # default off
    monkeypatch.setenv(R.BOSS_RULE_ENV, "6")
    assert R.env_boss_rule() == 6


def test_override_only_cursed_pick_at_or_above_the_crown():
    g = _draft(crown=6)
    acts, cursed, unc = _cursed_uncursed(g)
    assert R.uncursed_boss_override(g, cursed, acts, 6, risk=None) is unc[0]
    assert R.uncursed_boss_override(g, cursed, acts, 7, risk=None) is None      # crown below N
    assert R.uncursed_boss_override(g, cursed, acts, 0, risk=None) is None      # off
    assert R.uncursed_boss_override(g, unc[0], acts, 6, risk=None) is None      # already uncursed
    assert R.uncursed_boss_override(g, cursed, [cursed], 6, risk=None) is None  # no alternative
    assert R.uncursed_boss_override(g, Action("leave", (), "x"), acts, 6) is None
    # index form (env candidates carry .action)
    cands = [type("C", (), {"action": a})() for a in acts]
    i = acts.index(cursed)
    j = R.boss_rule_index(g, cands, i, 6, risk=None)
    assert cands[j].action is unc[0]
    assert R.boss_rule_index(g, cands, i, 0) == i
    # action form (teacher): built from the draft's legal actions
    b = R.boss_rule_action(g, cursed, 6, risk=None)
    assert b.kind == "boss" and not g.boss_options()[b.args[0]].cursed
    assert R.boss_rule_action(g, cursed, 0) is cursed
    # outside a boss draft: never
    g.player.run.node = Node.SHOP_ONE
    assert R.uncursed_boss_override(g, cursed, acts, 6) is None


class _Boss:
    def __init__(self, name, cursed):
        self.game_class, self.cursed = name, cursed


class _FakeGame:
    phase = "boss_draft"

    def __init__(self, opts, crown=6):
        self._opts = opts
        self.player = type("P", (), {"character": "SockHead",
                                     "run": type("Run", (), {"ascension": crown})()})()

    def boss_options(self):
        return self._opts


class _Risk:
    def __init__(self, r):
        self.r = r

    def risk(self, boss, crown, character):
        return self.r[boss.game_class]


def test_several_uncursed_prefers_lowest_risk_else_first():
    g = _FakeGame([_Boss("A", True), _Boss("B", False), _Boss("C", False)])
    acts = [Action("boss", (i,), f"b{i}") for i in range(3)]
    assert R.uncursed_boss_override(g, acts[0], acts, 6, risk=None) is acts[1]
    assert R.uncursed_boss_override(g, acts[0], acts, 6, risk=_Risk({"A": 0, "B": .5, "C": .2})) is acts[2]
    assert R.uncursed_boss_override(g, acts[0], acts, 6, risk=_Risk({"A": 0, "B": .2, "C": .2})) is acts[1]


# ------------------------------------------------------------------ play()

def _clear(game) -> None:
    enc = game.encounter
    enc.remaining_target = 0
    enc._try_next_grid(SubmitResult(0, [], 0, game.player.money, game.player.money))
    game._after_encounter_action()


@pytest.fixture
def cursed_net(monkeypatch, tmp_path):
    """Encounters always clear; the net picks a cursed boss whenever one is offered. Records each
    boss fought as (cursed, an uncursed option was offered)."""
    import cursed_words_solver.rl.env as EN
    from cursed_words_solver.rl import play as PL
    from cursed_words_solver.rl.model import Actor

    n_threads = torch.get_num_threads()
    torch.set_num_threads(1)
    fought: list[tuple[bool, bool]] = []
    orig_apply = EN.apply

    def fake_apply(g, a):
        if g.phase == "encounter" and g.encounter is not None and g.encounter.michael_draft is None:
            _clear(g)
            return True
        if a.kind == "boss":
            opts = g.boss_options()
            fought.append((bool(opts[a.args[0]].cursed), any(not b.cursed for b in opts)))
        return orig_apply(g, a)

    monkeypatch.setattr(EN, "apply", fake_apply)
    last = {}
    orig_current = EN.CWEnv.current

    def current(self):
        st = orig_current(self)
        last["st"], last["g"] = st, self.game
        return st

    monkeypatch.setattr(EN.CWEnv, "current", current)
    orig_choose = Actor.choose

    def choose(self, pk):
        i, lp, v = orig_choose(self, pk)
        g, st = last["g"], last["st"]
        if g.phase == "boss_draft":
            opts = g.boss_options()
            i = next((k for k, c in enumerate(st.cands) if c.action.kind == "boss" and opts[c.action.args[0]].cursed), i)
        return i, lp, v

    monkeypatch.setattr(Actor, "choose", choose)
    torch.manual_seed(0)
    path = tmp_path / "w.pt"
    save_policy(Policy(default_config()), path)
    monkeypatch.setattr(PL, "_CANDS", _NoWords())
    yield PL, str(path), fought
    torch.set_num_threads(n_threads)


def test_play_boss_rule(cursed_net):
    PL, path, fought = cursed_net
    job = {"character": "SockHead", "crown": 6, "seed": 7, "quest": None, "policy": path, "greedy": True}
    off = PL.play(job)
    assert not off["error"], off.get("trace")
    assert "boss_rule" not in off and "boss_overrides" not in off       # off: rows unchanged
    assert fought and all(c for c, alt in fought if alt)                 # the net takes cursed bosses
    fought.clear()
    on = PL.play({**job, "boss_rule": 6, "record": True})
    assert not on["error"], on.get("trace")
    assert fought and not any(c and alt for c, alt in fought)            # never cursed when uncursed offered
    assert on["boss_rule"] == 6 and on["boss_overrides"] == sum(alt for _, alt in fought) >= 1
    assert all(lp <= 0 for lp in on["traj"]["logp"])
    fought.clear()
    hi = PL.play({**job, "boss_rule": 7})                                # crown 6 < 7: no override
    assert not hi["error"] and hi["boss_overrides"] == 0
    assert all(c for c, alt in fought if alt)


# ------------------------------------------------------------------ evaluate

def test_run_arm_cache_separates_boss_rule(tmp_path):
    jobs = E.eval_jobs(per=1, per_quest=0, crowns=range(1))[:3]
    for j in jobs:
        store.append_jsonl(tmp_path / "arm.jsonl", {**j, "target": "", "won": False, "outcome": 1.0, "error": ""})
        store.append_jsonl(tmp_path / "arm.jsonl", {**j, "target": "", "boss_rule": 6, "won": True,
                                                   "outcome": 16.0, "error": ""})
    plain = E.run_arm("arm", "unused.pt", jobs, out_dir=tmp_path, verbose=False)
    ruled = E.run_arm("arm", "unused.pt", jobs, out_dir=tmp_path, verbose=False, boss_rule=6)
    assert len(plain) == len(ruled) == 3
    assert not any(r["won"] for r in plain) and all(r["won"] and r["boss_rule"] == 6 for r in ruled)
    assert E.key(plain[0]) == E.key(ruled[0]) and E.cache_key(plain[0]) != E.cache_key(ruled[0])
    assert E.paired(ruled, plain)["n"] == 3                              # pairs across arms


def test_run_arm_boss_rule_reaches_play(tmp_path, monkeypatch):
    seen = []

    class _Pool:
        def imap_unordered(self, fn, jobs):
            for j in jobs:
                seen.append(j)
                yield {**{k: j[k] for k in ("character", "crown", "seed", "quest")}, "target": j.get("target", ""),
                       "boss_rule": j.get("boss_rule"), "won": False, "outcome": 0.0, "error": ""}

    jobs = E.eval_jobs(per=1, per_quest=0, crowns=range(1))[:2]
    got = E.run_arm("a", "unused.pt", jobs, out_dir=tmp_path, pool=_Pool(), verbose=False, boss_rule=6)
    assert len(got) == 2 and all(j["boss_rule"] == 6 for j in seen)
    seen.clear()
    E.run_arm("a", "unused.pt", jobs, out_dir=tmp_path, pool=_Pool(), verbose=False, boss_rule=6)
    assert not seen                                                      # cached
    E.run_arm("a", "unused.pt", jobs, out_dir=tmp_path, pool=_Pool(), verbose=False)
    assert len(seen) == 2 and all("boss_rule" not in j for j in seen)    # off: plays again, no key


def test_parse_set_and_make_table():
    assert E.parse_set("SockHead:4-7=Curse") == ("SockHead", "4-7", "Curse")
    assert E.parse_set("SamGambit:5=Chess-Curse") == ("SamGambit", "5", "Chess+Curse")
    assert E.parse_set("NinaNix:all=pivot:3") == ("NinaNix", "0-7", "pivot:3")
    assert E.parse_set("Spike:6-7=free") == ("Spike", "6-7", "")
    for bad in ("SockHead=Curse", "Nobody:4-7=Curse", "SockHead:7-4=Curse", "SockHead:x=Curse",
                "SockHead:4-7=NotAPlan"):
        with pytest.raises(ValueError):
            E.parse_set(bad)
    base = {"version": 1, "table": {"SockHead": {"0-3": "Chess", "4-7": ""}, "Octacles": {"0-3": "Curse"}}}
    tab = E.make_table(["SockHead:4-7=Curse", "SamGambit:4-7=Curse"], base)
    assert tab["table"]["SockHead"] == {"0-3": "Chess", "4-7": "Curse"}
    assert tab["table"]["SamGambit"] == {"4-7": "Curse"} and tab["table"]["Octacles"] == {"0-3": "Curse"}
    assert base["table"]["SockHead"]["4-7"] == ""                        # base not mutated
    # a rule's band goes first, so it is not shadowed by an overlapping base band
    tab = E.make_table(["SockHead:5-7=Curse"], base)
    assert list(tab["table"]["SockHead"]) == ["5-7", "0-3", "4-7"]
    assert table_target(tab, "SockHead", 5) == "Curse" and table_target(tab, "SockHead", 4) == FREE
    # later rules win where they overlap
    tab = E.make_table(["SockHead:4-7=Curse", "SockHead:6=Chess"])
    assert table_target(tab, "SockHead", 6) == "Chess" and table_target(tab, "SockHead", 7) == "Curse"


def test_table_cli_and_target_table_jobs_match_the_assistant(tmp_path, monkeypatch):
    monkeypatch.setattr(E, "EVAL_HOME", tmp_path / "eval")
    out = tmp_path / "deploy.json"
    E.main(["table", "--set", "SockHead:5-7=Curse", "--set", "SamGambit:5-7=Curse", "--set", "NinaNix:0=pivot:2",
            "--out", str(out)])
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["version"] == 1 and data["table"]["SockHead"] == {"5-7": "Curse"}
    jobs = E.table_jobs(E.eval_jobs(per=1, per_quest=1), E.load_table(out))
    # the assistant reading the same file as its target_table.json chooses the same targets
    monkeypatch.setattr(store, "RL_HOME", tmp_path)
    monkeypatch.delenv(A.TARGET_ENV, raising=False)
    (tmp_path / "target_table.json").write_text(out.read_text(encoding="utf-8"), encoding="utf-8")
    for j in jobs:
        if j["quest"]:
            assert j["target"] == FREE and "pivot_stage" not in j
            continue
        want = A.choose_target(j["character"], j["crown"])
        got = f"pivot:{j['pivot_stage']}" if j.get("pivot_stage") else j["target"]
        assert got == want, j
    by = {(j["character"], j["crown"]): j for j in jobs if not j["quest"]}
    assert by[("SockHead", 4)]["target"] == FREE and by[("SockHead", 5)]["target"] == "Curse"
    assert by[("SamGambit", 7)]["target"] == "Curse" and by[("Octacles", 6)]["target"] == FREE
    assert by[("NinaNix", 0)]["target"] == FREE and by[("NinaNix", 0)]["pivot_stage"] == 2
    assert len({E.key(j) for j in jobs}) == len(jobs)


def test_table_target_first_matching_key_wins():
    data = {"table": {"SockHead": {"6": "Chess", "4-7": "Curse"}}}
    assert table_target(data, "SockHead", 6) == "Chess"
    assert table_target(data, "SockHead", 7) == "Curse"
    assert table_target(data, "SockHead", 2) == FREE and table_target(data, "Nobody", 6) == FREE
    assert table_target({}, "SockHead", 6) == FREE


def test_run_cli_target_table_and_boss_rule(tmp_path, monkeypatch):
    tab = tmp_path / "t.json"
    tab.write_text(json.dumps({"version": 1, "table": {"SockHead": {"4-7": "Curse"}}}), encoding="utf-8")
    calls = {}

    def fake_run_arm(arm, pol, jobs, workers, **kw):
        calls.update(arm=arm, jobs=jobs, **kw)
        return []

    monkeypatch.setattr(E, "run_arm", fake_run_arm)
    monkeypatch.setattr(E, "EVAL_HOME", tmp_path / "eval")
    E.main(["run", "--arm", "x", "--policy", "teacher", "--per", "1", "--per-quest", "0",
            "--target-table", str(tab), "--boss-rule", "6", "--out-dir", str(tmp_path)])
    assert calls["boss_rule"] == 6
    sh = [j for j in calls["jobs"] if j["character"] == "SockHead"]
    assert {j["crown"]: j["target"] for j in sh} == {c: ("Curse" if c >= 4 else FREE) for c in range(8)}
    E.main(["run", "--arm", "x", "--policy", "teacher", "--per", "1", "--per-quest", "0", "--out-dir", str(tmp_path)])
    assert calls["boss_rule"] == 0 and all("target" not in j for j in calls["jobs"])   # defaults unchanged
    with pytest.raises(SystemExit):
        E.main(["run", "--arm", "x", "--policy", "teacher", "--targets", "own", "--target-table", str(tab)])


# ------------------------------------------------------------------ assistant

@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "RL_HOME", tmp_path)
    monkeypatch.delenv(A.TARGET_ENV, raising=False)
    monkeypatch.delenv(R.BOSS_RULE_ENV, raising=False)
    m = Policy(default_config()).eval()
    monkeypatch.setattr(A, "_model_entry", lambda path: (m, False))

    def cursed_pick(adv, actor, game, cands):   # the assistant's own rule picks the cursed boss
        opts = game.boss_options()
        adv.pick = next(o for o in adv.options if o.action.kind == "boss" and opts[o.action.args[0]].cursed)

    monkeypatch.setattr(A, "_boss_rule", cursed_pick)
    return tmp_path


def _advise(g, **kw):
    return A.advise_game(g, cands=_NoWords(), model_path=Path("unused.pt"), search=False, **kw)


def _cursed(g, adv) -> bool:
    return bool(g.boss_options()[adv.pick.action.args[0]].cursed)


def test_assistant_boss_rule_env_default_off(home, monkeypatch):
    g = _draft(crown=6)
    adv = _advise(g)
    assert _cursed(g, adv) and "Boss rule" not in adv.text()             # default: off
    monkeypatch.setenv(R.BOSS_RULE_ENV, "6")
    adv = _advise(_draft(crown=6))
    assert not _cursed(g, adv)
    assert "boss rule" in adv.pick.note and "Boss rule" in adv.text()
    d = adv.as_dict()
    assert d["pick"] == A.label(adv.pick.action) and "boss rule" in d["pick_note"]
    assert "boss rule" in adv.html()
    monkeypatch.setenv(R.BOSS_RULE_ENV, "7")
    assert _cursed(g, _advise(_draft(crown=6)))                          # crown 6 < 7
    assert not _cursed(g, _advise(_draft(crown=6), boss_rule=6))         # explicit argument wins
    monkeypatch.setenv(R.BOSS_RULE_ENV, "6")
    assert _cursed(g, _advise(_draft(crown=6), boss_rule=0))
