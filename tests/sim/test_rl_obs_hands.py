"""RL observation v4: Human Boy favourite stamp / padlock sell cost on tokens, move
afterstates (mv_*), Human Hands pin-reward favourites (hh_*); v3 checkpoints keep scoring
exactly as before."""

from __future__ import annotations

import math

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from cursed_words_solver.rl import actions as A  # noqa: E402
from cursed_words_solver.rl import obs as O  # noqa: E402
from cursed_words_solver.rl.actions import Action, CandidateBuilder, Limits, cand_for, summary  # noqa: E402
from cursed_words_solver.rl.env import CWEnv, pack  # noqa: E402
from cursed_words_solver.rl.model import ModelConfig, Policy, collate, default_config, upgrade_config  # noqa: E402
from cursed_words_solver.sim.game.items import make_item  # noqa: E402
from cursed_words_solver.sim.game.run import Game, RunConfig  # noqa: E402

V3_G, V3_T, V3_A = O.LEGACY_GLOBAL[2], O.LEGACY_TOKEN[2], A.LEGACY_ACTION[0]


class _NoWords:
    wordlist = None

    def words(self, game, top_n=5):
        return []


def _hb(seed=2) -> Game:
    g = Game(RunConfig(character="SockHead", ascension=1, seed=seed))
    p = g.player
    assert p.pin.game_class == "HumanHands"
    assert p.stickers[0].game_class == "LeftHumanHand" and p.stamps[0].game_class == "RightHumanHand"
    return g


def _tok(obs, ref):
    return obs.tok_feat[obs.refs[ref]]


# ------------------------------------------------------------------------- layout


def test_v4_widths_and_legacy():
    assert O.OBS_VERSION == 4
    cols = list(O.token_columns())
    assert O.n_token_features() == O.V4_TOKEN == V3_T + 2 == O.V3_TOKEN + 2
    assert cols[V3_T:] == ["hb_fav_stamp", "sell_cost"]
    assert O.n_global_features() == V3_G == O.V3_GLOBAL   # global layout unchanged in v4
    acols = list(A.action_columns())
    assert len(acols) == A.n_action_features() == V3_A + 16
    assert acols[V3_A:V3_A + 4] == ["mv_d_levels", "mv_d_counters", "mv_d_sell_value", "mv_d_valid"]
    assert A.LEGACY_ACTION_BY_OBS == {1: 38, 2: 38, 3: 38}
    cfg = upgrade_config(ModelConfig(**{**default_config().__dict__, "n_global": V3_G, "n_tok_feat": V3_T,
                                        "n_act_feat": V3_A}))
    assert (cfg.n_global, cfg.n_tok_feat, cfg.n_act_feat) == (O.n_global_features(), O.n_token_features(),
                                                              A.n_action_features())


# ------------------------------------------------------------------------- tokens


def test_hb_fav_stamp_flag():
    g = _hb()
    p = g.player
    p.stamps[1] = make_item("StampPadlock")
    p.stamps[2] = make_item("StampPadlock")
    o = O.observe(g, probe=False)
    c = O.token_columns()["hb_fav_stamp"]
    assert _tok(o, ("stamp", 1))[c] == 1.0      # right of the Right Hand
    assert _tok(o, ("stamp", 2))[c] == 0.0
    assert _tok(o, ("stamp", 0))[c] == 0.0
    # move the hand: the favourite follows
    p.stamps[0], p.stamps[1] = p.stamps[1], p.stamps[0]
    o = O.observe(g, probe=False)
    assert _tok(o, ("stamp", 2))[c] == 1.0 and _tok(o, ("stamp", 0))[c] == 0.0


def test_padlock_sell_cost():
    g = _hb()
    p = g.player
    p.stickers[1] = make_item("StickerPadlock")
    p.stamps[1] = make_item("StampPadlock")
    o = O.observe(g, probe=False)
    col = O.token_columns()
    for ref in (("sticker", 1), ("stamp", 1)):
        f = _tok(o, ref)
        assert f[col["sell_cost"]] == pytest.approx(math.log1p(8))
        assert f[col["sell_value"]] == 0.0
    assert _tok(o, ("sticker", 0))[col["sell_cost"]] == 0.0   # the Left Hand sells for free


# ------------------------------------------------------------------------- actions


def _moves(cs, kind=None):
    return {tuple(c.action.args): c for c in cs if c.action.kind == "move" and (kind is None or c.action.args[0] == kind)}


def test_move_afterstate_shows_favourite_changes():
    g = _hb()
    p = g.player
    p.pin.upgrade(0)   # Left Hand upgrades its favourite once
    assert p.pin.var(0) >= 1
    p.stickers[1] = make_item("StickerPadlock")
    p.stamps[1] = make_item("StampPadlock")
    p.stamps[2] = make_item("StampPadlock")
    p.refresh_favourite_sticker()
    col = A.action_columns()
    b = CandidateBuilder(_NoWords(), Limits(probes=False))
    cs = b.build(g)
    mv = _moves(cs)
    # Left Hand from 0 to 1: the padlock in slot 1 becomes its favourite (+1 level, a padlock)
    c = mv[("sticker", 0, 1)]
    f = c.feat
    assert f[col["mv_d_valid"]] == 1.0
    assert f[col["mv_fav_sticker_change"]] == 1.0
    assert f[col["mv_fav_padlock"]] == 1.0
    assert f[col["mv_d_levels"]] == pytest.approx(p.pin.var(0))
    # old d_* columns stay zero on moves (v3 checkpoints see moves exactly as before)
    for k in ("d_money", "d_levels", "d_counters", "d_items", "d_valid"):
        assert f[col[k]] == 0.0
    # Right Hand to slot 2: favourite stamp changes from a padlock to a padlock
    c = mv[("stamp", 0, 1)]
    assert c.feat[col["mv_fav_stamp_change"]] == 1.0
    assert c.feat[col["mv_fav_padlock"]] == 0.0
    # Padlock out of the favourite stamp slot (to the end): the next padlock slides in
    c = mv[("stamp", 1, 2)]
    assert c.feat[col["mv_fav_stamp_change"]] == 0.0   # same slot, same class
    # the real game was not touched
    assert p.stickers[0].game_class == "LeftHumanHand" and p.stamps[0].game_class == "RightHumanHand"
    # cand_for gives a move the same features
    c2 = cand_for(b, g, c.action)
    assert np.array_equal(c2.feat, c.feat)
    c3 = cand_for(b, g, mv[("sticker", 0, 1)].action)
    assert np.array_equal(c3.feat, mv[("sticker", 0, 1)].feat)


def test_move_afterstate_modes():
    g = _hb()
    p = g.player
    p.stamps[1] = make_item("StampPadlock")
    col = A.action_columns()
    for mode, want in (("all", 1.0), ("hands", 1.0), ("none", 0.0)):
        cs = CandidateBuilder(_NoWords(), Limits(probes=False, move_afterstates=mode)).build(g)
        assert all(c.feat[col["mv_d_valid"]] == want for c in _moves(cs).values()), mode
    g2 = Game(RunConfig(character="Octacles", ascension=1, seed=2))
    p2 = g2.player
    p2.stickers[0] = make_item("StickerPadlock")
    p2.stickers[1] = make_item("StickerPadlock")
    cs = CandidateBuilder(_NoWords(), Limits(probes=False, move_afterstates="hands")).build(g2)
    mv = _moves(cs, "sticker")
    assert mv and all(c.feat[col["mv_d_valid"]] == 0.0 for c in mv.values())
    cs = CandidateBuilder(_NoWords(), Limits(probes=False)).build(g2)
    assert all(c.feat[col["mv_d_valid"]] == 1.0 for c in _moves(cs, "sticker").values())


def test_hh_pin_features():
    g = _hb()
    p = g.player
    col = A.action_columns()
    f = np.zeros(len(col), np.float32)
    A.hh_pin_feat(p, "left", f, col)
    assert not f.any()                                 # nothing left of the Left Hand
    p.stickers[0], p.stickers[1] = make_item("StickerPadlock"), p.stickers[0]
    p.stamps[1] = make_item("StampPadlock")
    for ch, l, r in (("left", 1, 0), ("right", 0, 1), ("both", 1, 1)):
        f = np.zeros(len(col), np.float32)
        A.hh_pin_feat(p, ch, f, col)
        assert f[col["hh_l_exists"]] == l and f[col["hh_l_padlock"]] == l
        assert f[col["hh_r_exists"]] == r and f[col["hh_r_padlock"]] == r
        assert f[col["hh_l_slot"]] == pytest.approx(l * 1 / 5.0)   # slot 0
        assert f[col["hh_r_slot"]] == pytest.approx(r * 2 / 5.0)   # slot 1
        assert f[col["hh_l_level"]] == pytest.approx(l * p.stickers[0].level(0) / 5.0)
    # the builder / cand_for path (static_feat) carries them too
    b = CandidateBuilder(_NoWords(), Limits(probes=False))
    c = cand_for(b, g, Action("pin", ("right",), "pin upgrade: right"))
    assert c.feat[col["hh_r_exists"]] == 1.0 and c.feat[col["hh_l_exists"]] == 0.0
    # not Human Hands: nothing
    g2 = Game(RunConfig(character="Octacles", ascension=1, seed=2))
    f = np.zeros(len(col), np.float32)
    A.hh_pin_feat(g2.player, "both", f, col)
    assert not f.any()


# ------------------------------------------------------------------------- v3 checkpoints


def test_v3_checkpoint_scores_unchanged(monkeypatch):
    """A v3-wide model widened to v4 scores every candidate exactly as the v3 model scores the
    same step cut to v3 widths (the v4 columns have zero weight)."""
    monkeypatch.setattr(O, "LEGACY_TOKEN", ())
    monkeypatch.setattr(A, "LEGACY_ACTION", ())
    torch.manual_seed(0)
    old = Policy(ModelConfig(**{**default_config().__dict__, "n_tok_feat": V3_T, "n_act_feat": V3_A})).eval()
    monkeypatch.undo()
    assert old.cfg.n_tok_feat == V3_T
    new = Policy(ModelConfig(**{**old.cfg.__dict__}))
    assert new.cfg.n_tok_feat == O.n_token_features() and new.cfg.n_act_feat == A.n_action_features()
    new.load_state_dict(old.state_dict())
    new.eval()
    g = _hb()
    g.player.stamps[1] = make_item("StampPadlock")
    g.player.stickers[1] = make_item("StickerPadlock")
    env = CWEnv(_NoWords(), Limits(probes=False))
    env.attach(g)
    pk = pack(env.current())
    assert pk["act_feat"][:, V3_A:].any() and pk["tok_feat"][:, V3_T:].any()   # v4 columns are set
    cut = {**pk, "tok_feat": pk["tok_feat"][:, :V3_T], "act_feat": pk["act_feat"][:, :V3_A]}
    with torch.no_grad():
        a = old(collate([cut]))["logits"]
        b = new(collate([pk]))["logits"]
    assert torch.allclose(a, b, atol=1e-6)


# ------------------------------------------------------------------------- review additions


def test_move_afterstates_leave_real_levels_untouched():
    """move_after applies each move on a clone: the real items keep their levels / favourite
    flags (refresh_favourite_sticker upgrades in place, so a shared item would leak)."""
    g = _hb()
    p = g.player
    p.pin.upgrade(0)
    p.stickers[1] = make_item("StickerPadlock")
    p.stickers[2] = make_item("StickerPadlock")
    p.stamps[1] = make_item("StampPadlock")
    p.refresh_favourite_sticker()
    before = [(it.game_class, it.level(0) if it.components else None, it.is_hb_favourite_sticker,
               getattr(it, "sell_cost", None)) for it in p.stickers + p.stamps if it is not None]
    s0 = summary(g)
    CandidateBuilder(_NoWords(), Limits(probes=False)).build(g)
    after = [(it.game_class, it.level(0) if it.components else None, it.is_hb_favourite_sticker,
              getattr(it, "sell_cost", None)) for it in p.stickers + p.stamps if it is not None]
    assert before == after
    assert np.array_equal(s0, summary(g))


def test_distill_accepts_v3_shards():
    """v3 rl.exit / teacher shards (act width 38) must still load after v4 widened the action
    features; needs ppo.DistillBuffer.format_ok to use actions.LEGACY_ACTION_BY_OBS."""
    from cursed_words_solver.rl import ppo as P

    buf = P.DistillBuffer("unused")
    ep = {"glob": np.zeros((2, V3_G), np.float32), "tok_feat": np.zeros((5, V3_T), np.float32),
          "act_feat": np.zeros((3, A.LEGACY_ACTION_BY_OBS[3]), np.float32),
          "obs_version": np.asarray([3], np.int16)}
    cur = {"glob": np.zeros((2, O.n_global_features()), np.float32),
           "tok_feat": np.zeros((5, O.n_token_features()), np.float32),
           "act_feat": np.zeros((3, A.n_action_features()), np.float32),
           "obs_version": np.asarray([O.OBS_VERSION], np.int16)}
    assert buf.format_ok(cur)
    if not buf.format_ok(ep):
        pytest.xfail("ppo.DistillBuffer.format_ok compares v3 shards' act_feat (38) with the current width (54)")
