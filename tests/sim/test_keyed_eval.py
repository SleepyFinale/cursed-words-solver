"""Keyed-RNG evals (``RunConfig.keyed_rng``) and sampled reps (``actor_seed`` / ``rep``).

A keyed real game draws from ``core.KeyedRng(f"run|{seed}")``: every node entry, encounter
setup, grid (and reroll), shop stock (and restock) and the run-start rolls (starting items,
every floor's boss draft) restart from a sub-key of their position, so two policies on one
keyed seed see the same grids / shops wherever they reach the same position. Everything is off
by default: plain games, rows and cache keys are unchanged."""

from __future__ import annotations

import random

import pytest

from cursed_words_solver.sim.game.core import KeyedRng, Rng
from cursed_words_solver.sim.game.run import Game, RunConfig


def _game(seed: int = 7, keyed: bool = True, ch: str = "BonesTheDog", crown: int = 2) -> Game:
    return Game(RunConfig(character=ch, ascension=crown, seed=seed, keyed_rng=keyed))


def _tile_fp(t) -> tuple:
    return (*(getattr(t, f) for f in t.__dataclass_fields__ if f != "item"),
            t.item.game_class if t.item is not None else None)


def _grid_fp(g: Game) -> tuple:
    return tuple(_tile_fp(t) for t in g.encounter.grid.tiles)


def _shop_fp(g: Game) -> tuple:
    s = g.shop
    items = tuple((o.item.game_class, o.item.is_foil, o.cost) if o is not None else None
                  for o in (*s.stickers, *s.stamps))
    tiles = tuple(_tile_fp(o.tile) if o is not None else None for o in s.tiles)
    return items, tiles


def _items_fp(g: Game) -> tuple:
    p = g.player
    return tuple(i.game_class if i is not None else None for i in (*p.stickers, *p.stamps))


def _drafts_fp(g: Game) -> tuple:
    return tuple(tuple((b.game_class, b.cursed, b.floor_mod) for b in d.options) for d in g.player.run.boss_drafts)


def _to_shop(g: Game) -> Game:
    """Skip the rest of the encounter (no word engine in CI) and walk to the next shop."""
    for _ in range(10):
        g._advance()
        if g.phase == "shop":
            return g
    raise AssertionError("no shop reached")


def _to_encounter(g: Game) -> Game:
    for _ in range(10):
        g._advance()
        if g.phase == "encounter":
            return g
    raise AssertionError("no encounter reached")


class _NoWords:
    """Candidates stand-in: no engine search (the word list may be missing in CI)."""

    wordlist = None

    def words(self, game, top_n=5):
        return []


def _random_run(seed: int, keyed: bool, policy_seed: int = 0, ch: str = "BonesTheDog", crown: int = 1):
    from cursed_words_solver.rl.env import CWEnv

    env = CWEnv(_NoWords())
    st = env.reset(character=ch, crown=crown, seed=seed, keyed=keyed)
    rng = random.Random(policy_seed)
    picks = []
    while not env.done:
        assert st.cands, env.game.phase
        i = rng.randrange(len(st.cands))
        picks.append(st.cands[i].label if hasattr(st.cands[i], "label") else str(st.cands[i].action))
        env.step(st.cands[i].action)
        if not env.done:
            st = env.current()
    return env, [(e.kind, sorted(e.data.items())) for e in env.game.events], picks


# ------------------------------------------------------------------ the game


def test_default_is_the_plain_stream():
    assert RunConfig().keyed_rng is False
    g = Game(RunConfig(character="BonesTheDog", ascension=2, seed=7))
    assert type(g.rng) is Rng
    k = _game(7, keyed=True)
    assert isinstance(k.rng, KeyedRng) and k.rng.key == "run|7"
    # explicit False == the default, draw for draw
    a, b = Game(RunConfig(character="BonesTheDog", ascension=2, seed=7)), _game(7, keyed=False)
    assert _grid_fp(a) == _grid_fp(b) and _drafts_fp(a) == _drafts_fp(b)
    assert a.rng.getstate() == b.rng.getstate()


def test_keyed_same_seed_is_identical():
    a, b = _game(11), _game(11)
    assert _grid_fp(a) == _grid_fp(b)
    assert _drafts_fp(a) == _drafts_fp(b)
    assert _items_fp(a) == _items_fp(b)
    assert _shop_fp(_to_shop(a)) == _shop_fp(_to_shop(b))
    # a whole (random-policy) run replays exactly
    ea, eva, pa = _random_run(5, True, policy_seed=3)
    eb, evb, pb = _random_run(5, True, policy_seed=3)
    assert pa == pb and eva == evb and ea.result() == eb.result()


def test_keyed_differs_from_plain_but_both_play():
    diff = 0
    for seed in (1, 2, 3):
        diff += _grid_fp(_game(seed, keyed=True)) != _grid_fp(_game(seed, keyed=False))
    assert diff >= 2
    for keyed in (False, True):
        env, events, _ = _random_run(9, keyed, policy_seed=1)
        assert env.done and env.game.won is not None
        assert events[-1][0] == "end"
        assert len(env.game.player.run.boss_drafts) == len(_game(9, keyed=keyed).player.run.boss_drafts)


def test_keyed_boss_drafts_pre_rolled_from_their_own_key():
    """The real game pre-rolls every floor's draft at run start: keyed, they come from the
    ("boss_drafts", 0) sub-key, so they don't depend on how much the starting-item roll drew."""
    g = _game(13)
    drafts = _drafts_fp(g)
    assert drafts and all(drafts)
    from cursed_words_solver.sim.game.player import Player, resolve_character

    p = Player(resolve_character("BonesTheDog"), 2, None)
    rng = KeyedRng("run|13")
    rng.range(0, 1000)   # a different amount drawn before the drafts
    rng.mark("boss_drafts", 0)
    p.run.generate_boss_drafts(rng, p)
    assert tuple(tuple((b.game_class, b.cursed, b.floor_mod) for b in d.options) for d in p.run.boss_drafts) == drafts


def test_keyed_streams_are_isolated_between_policies():
    """Two 'policies' on one keyed seed: one rerolls its first grid and burns extra draws (another
    word's procs), the other doesn't. Both see the same first grid, the same first shop, and the
    same next encounter's first grid; on the plain stream the extra draws move the shop."""
    a, b = _game(21), _game(21)
    assert _grid_fp(a) == _grid_fp(b)
    a.reroll_grid()
    for _ in range(41):
        a.rng.range(0, 1000)
    assert _items_fp(a) == _items_fp(b)   # same owned items when they reach the shop
    sa, sb = _shop_fp(_to_shop(a)), _shop_fp(_to_shop(b))
    assert sa == sb
    # a restock is keyed too: the 2nd stock matches when both restock
    a.player.money = b.player.money = 50
    assert a.reroll_shop() and b.reroll_shop()
    assert _shop_fp(a) == _shop_fp(b)
    assert _grid_fp(_to_encounter(a)) == _grid_fp(_to_encounter(b))

    # contrast: the game's own single stream is shifted by the extra draws
    pa, pb = _game(21, keyed=False), _game(21, keyed=False)
    for _ in range(41):
        pa.rng.range(0, 1000)
    assert _shop_fp(_to_shop(pa)) != _shop_fp(_to_shop(pb))


# ------------------------------------------------------------------ play / evaluate


@pytest.fixture
def fake_play(monkeypatch):
    torch = pytest.importorskip("torch")
    from cursed_words_solver.rl import play as P
    from cursed_words_solver.rl.model import Policy, default_config

    torch.manual_seed(0)
    m = Policy(default_config()).eval()
    monkeypatch.setattr(P, "_CANDS", _NoWords())
    monkeypatch.setattr(P, "_model", lambda path: m)
    return P


def _job(**kw):
    return {"character": "BonesTheDog", "crown": 1, "quest": None, "seed": 40_000_101, "policy": "x.pt",
            "greedy": False, **kw}


_PLAIN_ROW_KEYS = {"character", "crown", "seed", "quest", "won", "reason", "outcome", "stage", "steps", "michael",
                   "cursed", "target", "on_plan", "off_plan", "secs", "error", "tag"}


def test_play_plain_rows_unchanged(fake_play):
    r = fake_play.play(_job())
    assert not r["error"], r.get("trace")
    assert set(r) == _PLAIN_ROW_KEYS
    # actor_seed defaults to the game seed: an explicit one equal to it plays the same run
    r2 = fake_play.play(_job(actor_seed=40_000_101))
    assert r2["actor_seed"] == 40_000_101
    assert {k: v for k, v in r2.items() if k not in ("secs", "actor_seed")} == {k: v for k, v in r.items() if k != "secs"}


def test_play_keyed_and_actor_seed_rows(fake_play):
    a = fake_play.play(_job(keyed=True))
    b = fake_play.play(_job(keyed=True))
    assert not a["error"], a.get("trace")
    assert a["keyed"] is True and "actor_seed" not in a and "rep" not in a
    assert {k: v for k, v in a.items() if k != "secs"} == {k: v for k, v in b.items() if k != "secs"}
    c = fake_play.play(_job(keyed=True, rep=1, actor_seed=1_234_567_891))
    assert c["rep"] == 1 and c["actor_seed"] == 1_234_567_891 and c["keyed"] is True


def test_eval_keys_only_grow_when_set():
    from cursed_words_solver.rl.evaluate import cache_key, key

    row = {"character": "BonesTheDog", "crown": 3, "quest": None, "seed": 5, "target": ""}
    assert key(row) == ("BonesTheDog", 3, "", 5, "", 0)
    assert cache_key(row) == ("BonesTheDog", 3, "", 5, "", 0, 0)
    assert cache_key({**row, "keyed": False}) == cache_key(row)
    assert key({**row, "keyed": True}) == key(row)          # pairs with a plain row's key
    assert cache_key({**row, "keyed": True}) != cache_key(row)
    assert key({**row, "rep": 2}) != key(row) and key({**row, "rep": 2})[:6] == key(row)
    assert key({**row, "rep": 0}) != key({**row, "rep": 1})
    assert cache_key({**row, "actor_seed": 9}) != cache_key({**row, "actor_seed": 10})


def test_rep_jobs_distinct_actor_seeds():
    from cursed_words_solver.rl.evaluate import eval_jobs, key, rep_jobs

    jobs = eval_jobs(per=1, per_quest=0, crowns=range(2))
    assert rep_jobs(jobs, 0) == jobs
    reps = rep_jobs(jobs, 4)
    assert len(reps) == 4 * len(jobs)
    for j in jobs:
        mine = [r for r in reps if r["seed"] == j["seed"] and r["character"] == j["character"]]
        assert [r["rep"] for r in mine] == [0, 1, 2, 3]
        seeds = [r["actor_seed"] for r in mine]
        assert len(set(seeds)) == 4 and seeds[0] == j["seed"]
        assert all(0 <= s < 2**31 for s in seeds)
    assert len({key(r) for r in reps}) == len(reps)
    assert rep_jobs(jobs, 3) == rep_jobs(jobs, 3)   # stable


class _InlinePool:
    def imap_unordered(self, fn, jobs):
        return map(fn, jobs)


def _echo_play(job):
    """``play``'s row shape without playing (run_arm plumbing only; rows are tested above)."""
    extra = {**({"keyed": True} if job.get("keyed") else {}),
             **{k: job[k] for k in ("actor_seed", "rep") if job.get(k) is not None}}
    return {**{k: job[k] for k in ("character", "crown", "seed")}, "quest": job.get("quest"), "won": False,
            "outcome": float(job.get("actor_seed", job["seed"]) % 7), "error": "", **extra, "tag": ""}


def test_run_arm_keyed_caches_separately(monkeypatch, tmp_path):
    from cursed_words_solver.rl import evaluate as E
    from cursed_words_solver.rl import play as P

    monkeypatch.setattr(P, "play", _echo_play)

    jobs = [{"character": "BonesTheDog", "crown": 1, "quest": None, "seed": 40_000_102}]
    plain = E.run_arm("a", "x.pt", jobs, pool=_InlinePool(), out_dir=tmp_path, verbose=False, greedy=False)
    keyed = E.run_arm("a", "x.pt", jobs, pool=_InlinePool(), out_dir=tmp_path, verbose=False, greedy=False,
                      keyed=True)
    assert len(plain) == len(keyed) == 1
    assert "keyed" not in plain[0] and keyed[0]["keyed"] is True
    rows = (tmp_path / "a.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(rows) == 2
    # cached: nothing replayed
    again = E.run_arm("a", "x.pt", jobs, pool=None, out_dir=tmp_path, verbose=False, keyed=True)
    assert again == keyed
    reps = E.run_arm("a", "x.pt", E.rep_jobs(jobs, 2), pool=_InlinePool(), out_dir=tmp_path, verbose=False,
                     greedy=False, keyed=True)
    assert [r["rep"] for r in reps] == [0, 1]
    assert len((tmp_path / "a.jsonl").read_text(encoding="utf-8").splitlines()) == 4


def test_cli_keyed_and_reps_flags(monkeypatch, tmp_path):
    from cursed_words_solver.rl import evaluate as E

    seen = {}

    def fake_run_arm(arm, policy, jobs, workers, **kw):
        seen.update(kw, jobs=jobs)
        return []

    monkeypatch.setattr(E, "run_arm", fake_run_arm)
    monkeypatch.setattr(E, "EVAL_HOME", tmp_path)
    E.main(["run", "--arm", "k", "--policy", "teacher", "--per", "1", "--per-quest", "0", "--keyed", "--reps", "2",
            "--out-dir", str(tmp_path)])
    assert seen["keyed"] is True
    assert {j["rep"] for j in seen["jobs"]} == {0, 1}
    seen.clear()
    E.main(["run", "--arm", "p", "--policy", "teacher", "--per", "1", "--per-quest", "0", "--out-dir", str(tmp_path)])
    assert seen["keyed"] is False and all("rep" not in j for j in seen["jobs"])


def test_vs_free_pairs_reps_rep_by_rep():
    from cursed_words_solver.rl import evaluate as E

    def row(rep, target, out):
        return {"character": "BonesTheDog", "crown": 2, "quest": None, "seed": 9, "rep": rep,
                "target": target, "won": out > 0, "outcome": float(out)}

    rows = [row(0, "", 1), row(1, "", 2), row(0, "Red", 4), row(1, "Red", 4)]
    res = E.vs_free(rows)
    (k, v), = res.items()
    assert v["n"] == 2   # rep 0 vs rep 0, rep 1 vs rep 1 (not both against the last FREE rep)
    plain = [{**r, "rep": None} for r in rows[1:3]]
    assert E.vs_free(plain)[k]["n"] == 1
