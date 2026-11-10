"""Information boundary: search / rollouts must not see what a human player can't."""

from __future__ import annotations

from cursed_words_solver.sim.game.agent import clone, determinize
from cursed_words_solver.sim.game.run import Game, RunConfig


def _draft_classes(g: Game) -> list[tuple[str, ...]]:
    return [tuple(b.game_class for b in d.options) for d in g.player.run.boss_drafts]


def _game(seed: int, crown: int = 2) -> Game:
    return Game(RunConfig(character="BonesTheDog", ascension=crown, seed=seed))


def test_full_regeneration_is_unchanged_rng_use():
    """``start_floor=0`` keeps the game's draw order (same drafts for the same seed)."""
    a, b = _game(11), _game(11)
    assert _draft_classes(a) == _draft_classes(b)


def test_determinize_keeps_visible_draft_and_resamples_later_floors():
    g = _game(5)
    stage = max(g.player.run.stage, 1)
    real = _draft_classes(g)
    seen_later = set()
    for k in range(12):
        h = determinize(clone(g), f"t|{k}")
        d = _draft_classes(h)
        assert d[:stage] == real[:stage]          # shown to the player: kept
        assert d[-1] == ("MichaelBoss",)
        assert len(d) == len(real)
        seen_later.add(tuple(d[stage:-1]))
        # no boss class repeats across floors (the game removes drafted classes)
        flat = [c for opts in d[:-1] for c in opts]
        assert len(flat) == len(set(flat))
        # crown >= 1: exactly one cursed option per future floor
        for draft in h.player.run.boss_drafts[stage:-1]:
            assert sum(bool(b.cursed) for b in draft.options) == 1
    assert len(seen_later) > 1                    # later floors really are resampled


def test_determinize_same_key_same_future():
    g = _game(7)
    a = determinize(clone(g), "same")
    b = determinize(clone(g), "same")
    assert _draft_classes(a) == _draft_classes(b)
    assert a.rng.range(0, 10**9) == b.rng.range(0, 10**9)


def test_determinize_rebinds_one_stream():
    g = _game(9)
    h = determinize(clone(g), "x")
    if h.encounter is not None:
        assert h.encounter.rng is h.rng
    if h.shop is not None:
        assert h.shop.rng is h.rng


def test_secret_boss_swap_stays_excluded():
    """A class a secret boss replaced was drawn at generation: resampled floors never reuse it."""
    g = _game(21, crown=0)
    run = g.player.run
    draft = run.boss_drafts[1]
    removed = draft.options[0].game_class
    draft.options.pop(0)   # what check_secret_bosses does to the next floor's draft
    run.stage = 2
    for k in range(25):
        h = determinize(clone(g), f"s|{k}")
        later = [b.game_class for d in h.player.run.boss_drafts[2:-1] for b in d.options]
        assert removed not in later


def test_michael_future_pairs_resampled_visible_kept():
    from types import SimpleNamespace

    from cursed_words_solver.sim.game.agent import _resample_michael_drafts
    from cursed_words_solver.sim.game.core import Rng
    from cursed_words_solver.sim.game.encounter import populate_michael_drafts
    from cursed_words_solver.sim.game.player import BossModifier

    m = BossModifier("MichaelBoss")
    m.floor_mod = 3
    populate_michael_drafts(m, Rng("michael"))
    real = [[b.game_class for b in p] for p in m.drafts]
    m.drafted = [m.drafts[0][1]]
    enc = SimpleNamespace(michael_draft=list(m.drafts[1]))
    futures = set()
    for k in range(20):
        mm = BossModifier("MichaelBoss")
        mm.floor_mod = 3
        mm.drafts = [list(p) for p in m.drafts]
        mm.drafted = list(m.drafted)
        _resample_michael_drafts(mm, enc, Rng(f"k{k}"))
        got = [[b.game_class for b in p] for p in mm.drafts]
        assert got[:2] == real[:2]
        seen = set(real[0]) | set(real[1])
        assert not (set(got[2]) & seen) and len(got[2]) == 2
        futures.add(tuple(got[2]))
    assert len(futures) > 1
