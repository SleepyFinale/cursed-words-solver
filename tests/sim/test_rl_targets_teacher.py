"""Build-conditioned RL, teacher + BC side: themed teacher jobs (targets per run), the teacher's
plan for a target, shard target fields, BC multi-dir data, the FREE anchor KL and ``--init``."""

from __future__ import annotations

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from cursed_words_solver.rl import bc  # noqa: E402
from cursed_words_solver.rl import obs as O  # noqa: E402
from cursed_words_solver.rl import store  # noqa: E402
from cursed_words_solver.rl import targets as T  # noqa: E402
from cursed_words_solver.rl import teacher as TE  # noqa: E402
from cursed_words_solver.rl.env import CWEnv, pack  # noqa: E402
from cursed_words_solver.rl.model import Policy, ModelConfig, conditioned, default_config, save_policy  # noqa: E402
from cursed_words_solver.sim.game import policy as P  # noqa: E402
from cursed_words_solver.sim.game.run import Game, RunConfig  # noqa: E402

V2_G, V2_T = O.LEGACY_GLOBAL[1], O.LEGACY_TOKEN[1]


class _NoWords:
    """Candidates stand-in: no engine search (fast; the run ends at the first encounter)."""

    wordlist = None
    effort = 0.0

    def words(self, game, top_n=5):
        return []

    def with_budget(self, *a, **k):
        return self

    def with_effort(self, *a, **k):
        return self


# ------------------------------------------------------------------------- teacher jobs


def test_themed_jobs_deterministic_prefix_stable_no_crown8():
    a = TE.jobs(400, themed=True)
    assert a == TE.jobs(400, themed=True)
    assert TE.jobs(150, themed=True) == a[:150]
    assert all(j["seed"] == TE.FIRST_SEED2 + j["i"] for j in a)
    assert all(j["crown"] in range(8) for j in a) and {j["crown"] for j in a if not j["quest"]} == set(range(8))
    names = [TE.shard_name(j) for j in a]
    assert len(set(names)) == len(names)
    assert all("_c8_" not in n for n in names)
    for j, n in zip(a, names):
        T.parse(j["target"])   # valid
        assert j["target"] == T.teacher_plan(j["target_req"], j["character"], j["quest"])
        assert j["target_req"] != T.FREE   # mix (0, .5, .5): never FREE
        assert n.endswith(f"_{T.file_tag(j['target'])}.npz") and "+" not in n
    themes = sum(j["target_req"] in T.THEMES[j["character"]] for j in a)
    assert themes > len(a) * 0.45   # half theme draws + any-plan draws that hit a theme
    quests = [j for j in a if j["quest"]]
    assert quests and abs(len(quests) / len(a) - 0.1) < 0.06
    for j in quests:
        if P.QUEST_PLANS.get(j["quest"]):
            assert j["target"] == P.QUEST_PLANS[j["quest"]]


def test_plain_jobs_unchanged():
    """The default mode keeps its seeds, crowns and names (the old teacher dir resumes as before)."""
    a = TE.jobs(30)
    assert all(j["seed"] == TE.FIRST_SEED + j["i"] for j in a)
    assert all("target" not in j for j in a)
    j = a[0]
    assert TE.shard_name(j) == f"{j['i']:06d}_{j['character']}_c{j['crown']}_{j['quest'] or 'none'}_{j['seed']}.npz"


def test_target_drawn_after_existing_draws():
    """Themed jobs keep the quest / crown draws of the same rng; the target comes after them."""
    import random

    from cursed_words_solver.sim.game.challenges import QUESTS

    plain = TE.jobs(40)
    for j in TE.jobs(40, themed=True):
        r = random.Random(j["seed"])
        if r.random() < 0.1:
            assert j["quest"] == sorted(QUESTS)[r.randrange(len(QUESTS))]
        else:
            assert j["quest"] is None and j["crown"] == TE.THEMED_CROWNS[(j["i"] // len(TE.CHARS)) % 8]
        assert T.sample_target(r, j["character"], mix=TE.THEMED_MIX) == j["target_req"]
        assert j["character"] == plain[j["i"]]["character"]


def test_job_policy_plays_the_target_and_quest_plan():
    TE._TEACHER_MODEL = None
    cands = _NoWords()
    plain = TE.job_policy(cands, {"seed": 1})
    assert plain.cfg.build_plan == P.DEFAULT_PLAN and plain.cfg.build_plan_chars == P.DEFAULT_PLAN_CHARS
    pol = TE.job_policy(cands, {"seed": 1, "target": "Cards", "character": "SockHead"})
    assert pol.cfg.build_plan == "Cards" and pol.cfg.build_plan_chars == {}
    pol._tune(Game(RunConfig(character="SockHead", ascension=1, seed=2, target_build="Cards")))
    assert pol.cfg.build_plan == "Cards"   # no per-character Chess override
    rules = TE.job_policy(cands, {"seed": 1, "target": ""})
    assert rules.cfg.build_plan == ""
    # a quest with a plan: teacher_plan already maps it, and the policy agrees at _tune
    q = next(q for q, p in P.QUEST_PLANS.items() if p)
    eff = T.teacher_plan("Red", "WetDennis", q)
    assert eff == P.QUEST_PLANS[q]
    pq = TE.job_policy(cands, {"seed": 1, "target": eff})
    pq._tune(Game(RunConfig(character="WetDennis", ascension=0, seed=2, challenge=q, target_build=eff)))
    assert pq.cfg.build_plan == eff


def test_tiny_teacher_run_writes_target_shard(tmp_path, monkeypatch):
    j = next(j for j in TE.jobs(60, themed=True) if not j["quest"] and "+" not in j["target"])
    monkeypatch.setattr(TE, "_CANDS", _NoWords())
    monkeypatch.setattr(TE, "_TEACHER_MODEL", None)
    (tmp_path / "shards").mkdir()
    r = TE.play_teacher(j, str(tmp_path))
    assert r["error"] == "", r.get("trace")
    assert r["target"] == j["target"]
    path = tmp_path / "shards" / TE.shard_name(j)
    assert path.is_file()
    ep = store.load_episode(path)
    assert TE.shard_target(ep) == j["target"]
    assert bytes(ep["target_req"].item()).decode() == j["target_req"]
    assert int(ep["obs_version"]) == O.OBS_VERSION
    cols = O.global_columns()
    g = ep["glob"].astype(np.float32)
    assert g.shape[1] == O.n_global_features()
    assert np.all(g[:, cols["target_set"]] == 1)
    for p in T.PLANS:
        assert np.all(g[:, cols[f"target:{p}"]] == (p in T.parse(j["target"])))
    # BC loads it and flags it as themed
    ds = bc.Dataset(str(tmp_path))
    assert ds.refresh() == 1
    key = next(iter(ds.eps))
    assert int(ds.eps[key]["themed"]) == 1
    assert TE.shard_target({}) == ""


# ------------------------------------------------------------------------- BC


def _steps(n=6, target="Red"):
    env = CWEnv(_NoWords())
    out = []
    for s in range(n):
        st = env.reset(character="WetDennis", crown=1, seed=10 + s, target=target)
        out.append(pack(st))
    return out


def _batch(items):
    from cursed_words_solver.rl.model import collate

    b = collate(items)
    b["chosen"] = torch.zeros(len(items), dtype=torch.long)
    b["rtg"] = torch.zeros(len(items))
    b["won"] = torch.zeros(len(items))
    b["michael"] = torch.zeros(len(items))
    b["n_act"] = torch.tensor([len(it["act_type"]) for it in items])
    b["themed"] = torch.ones(len(items))
    return b


def test_free_copy_zeroes_only_target_columns():
    b = _batch(_steps(3, "Curse+Cash"))
    g, t = bc.target_columns()
    assert len(g) == 1 + len(T.PLANS) and len(t) == len(O.PLAN_CLASSES)
    assert b["glob"][:, g].abs().sum() > 0
    fb = bc.free_copy(b)
    assert fb["glob"][:, g].abs().sum() == 0 and fb["tok_feat"][..., t].abs().sum() == 0
    keep = [i for i in range(b["glob"].shape[1]) if i not in g]
    assert torch.equal(fb["glob"][:, keep], b["glob"][:, keep])
    assert b["glob"][:, g].abs().sum() > 0   # the original is untouched
    # the FREE copy equals the same states observed without a target
    free = _batch(_steps(3, T.FREE))
    assert torch.equal(fb["glob"], free["glob"]) and torch.equal(fb["tok_feat"], free["tok_feat"])
    # a v2-width (legacy) batch passes through
    legacy = _batch([{**s, "glob": s["glob"][:V2_G], "tok_feat": s["tok_feat"][:, :V2_T]} for s in _steps(2)])
    assert torch.equal(bc.free_copy(legacy)["glob"], legacy["glob"])


def test_anchor_kl_zero_for_same_policy_positive_otherwise():
    b = _batch(_steps(6))
    assert (b["n_act"] > 1).any()
    torch.manual_seed(0)
    student = Policy(default_config()).eval()
    anchor = Policy(default_config()).eval()
    anchor.load_state_dict(student.state_dict())
    assert bc.anchor_kl(student, anchor, b).item() == pytest.approx(0.0, abs=1e-6)
    _, st = bc.losses(student, b, anchor=anchor, anchor_coef=1.0)
    assert st["anchor_kl"] == pytest.approx(0.0, abs=1e-6)
    torch.manual_seed(1)
    other = Policy(default_config()).eval()
    kl = bc.anchor_kl(other, anchor, b)
    assert kl.item() > 1e-4
    l0, st0 = bc.losses(other, b)
    l1, st1 = bc.losses(other, b, anchor=anchor, anchor_coef=2.0)
    assert "anchor_kl" not in st0
    assert l1.item() == pytest.approx(l0.item() + 2.0 * st1["anchor_kl"], rel=1e-4)
    # gradients reach the student only
    l1.backward()
    assert any(p.grad is not None and p.grad.abs().sum() > 0 for p in other.parameters())
    assert all(p.grad is None for p in anchor.parameters())


def test_masked_kl_ignores_illegal_actions():
    p = torch.tensor([[1.0, 2.0, 50.0]])
    q = torch.tensor([[1.0, 2.0, -50.0]])
    mask = torch.tensor([[1.0, 1.0, 0.0]])
    assert bc.masked_kl(p, q, mask).item() == pytest.approx(0.0, abs=1e-6)


def test_data_dirs_parsing(tmp_path):
    a, b2 = tmp_path / "a", tmp_path / "b"
    assert bc.data_dirs([f"{a},{b2}", str(a)]) == [a, b2]
    assert bc.data_dirs(str(a)) == [a]


def _v2_checkpoint(path, monkeypatch):
    cfg2 = ModelConfig(**{**default_config().__dict__, "n_global": V2_G, "n_tok_feat": V2_T, "d": 32, "layers": 1,
                          "ff": 64, "heads": 2, "cls_dim": 8})
    monkeypatch.setattr(O, "LEGACY_GLOBAL", ())
    monkeypatch.setattr(O, "LEGACY_TOKEN", ())
    torch.manual_seed(0)
    v2 = Policy(cfg2)
    monkeypatch.undo()
    assert v2.cfg.n_global == V2_G
    save_policy(v2, path)
    return v2


def _write_shards(d, steps, *, target=""):
    (d / "shards").mkdir(parents=True)
    for i in range(2):   # run 0 -> validation, run 1 -> train
        extra = {"chosen": np.zeros(len(steps), np.int16), "reward": np.zeros(len(steps), np.float32),
                 "outcome": np.float32(0), "won": np.int8(0), "michael": np.int8(0)}
        if target:
            extra["target"] = np.bytes_(target.encode())
        store.atomic_write_bytes(d / "shards" / f"{i:06d}_WetDennis_c1_none_{i}.npz", store.pack_episode(steps, extra))


def test_bc_init_widens_v2_checkpoint_and_trains_with_anchor(tmp_path, monkeypatch):
    init = tmp_path / "v2.pt"
    _v2_checkpoint(init, monkeypatch)
    assert not conditioned(torch.load(init, weights_only=False)["config"])
    steps = [s for s in _steps(6) if len(s["act_type"]) > 1]
    assert steps
    # one legacy (v2-width, no target) dir + one themed dir
    legacy = [{**s, "glob": s["glob"][:V2_G], "tok_feat": s["tok_feat"][:, :V2_T]} for s in _steps(6, T.FREE)
              if len(s["act_type"]) > 1]
    _write_shards(tmp_path / "old", legacy)
    _write_shards(tmp_path / "themed", steps, target="Red")
    out = tmp_path / "bc"
    bc.main(["--data", f"{tmp_path / 'old'},{tmp_path / 'themed'}", "--dir", str(out), "--epochs", "1", "--steps", "2",
             "--bs", "4", "--lr", "1e-4", "--init", str(init), "--anchor", str(init), "--anchor-coef", "0.5"])
    ck = torch.load(out / "last.pt", weights_only=False)
    assert ck["config"]["n_global"] == O.n_global_features() and ck["config"]["n_tok_feat"] == O.n_token_features()
    assert ck["config"]["d"] == 32   # architecture from --init, not --d
    assert conditioned(ck["config"])
    from cursed_words_solver.rl.store import read_jsonl

    row = read_jsonl(out / "history.jsonl")[-1]
    assert "train_anchor_kl" in row and "val_anchor_kl" in row
    assert "val_ce_free" in row and "val_ce_themed" in row
    assert "--init" in (out / "command.txt").read_text()
    # resume (last.pt exists): --init ignored, one more epoch
    bc.main(["--data", str(tmp_path / "themed"), "--data", str(tmp_path / "old"), "--dir", str(out), "--epochs", "2",
             "--steps", "1", "--bs", "4", "--init", str(tmp_path / "missing.pt")])
    assert torch.load(out / "last.pt", weights_only=False)["epoch"] == 2
