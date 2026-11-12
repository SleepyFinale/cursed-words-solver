"""Plan-cached ``EnginePlan.score`` (``calc._score_fast``) vs the reference port
(``_score_ref``, the same as CWS_NO_FASTCALC=1): every ``EngineResult`` must be
bit-identical (score and its type, every step, nondeterministic flag, final states).

Inputs are real finds from seeded CWEnv games (every score call the search makes is
recorded, then replayed old vs new) plus random heavy-item loadouts on those boards
(containers, Scissors, Overhand / Human Boy, Hourglass, challenges, Capybara and other
bosses). Finds themselves are also compared end to end.
"""

from __future__ import annotations

import copy
import json
import pickle
import random

import pytest

from cursed_words_solver.engine import calc as C
from cursed_words_solver.engine import items as I
from cursed_words_solver.engine.calc import EnginePlan
from cursed_words_solver.engine.item_data import ITEMS
from cursed_words_solver.engine.search import ExactSearch

# (character, crown, seed): a spread of pins / starting items.
GAMES = [("Spike", 4, 77000001), ("Octacles", 7, 5002), ("SamGambit", 0, 5003), ("HayleyBayles", 5, 5004),
         ("PrismaticBean", 1, 6002), ("SockHead", 4, 6003)]
FINDS_PER_GAME = 12
MAX_CALLS = 15000  # score calls replayed per test (evenly sampled)


def _key(res) -> str:
    # repr keeps int vs float (5 vs 5.0) and dict order apart.
    return repr((res.score, type(res.score).__name__, res.steps, res.nondeterministic, res.final_states))


def _norm(found) -> list:
    return [(r.word, list(r.path), repr(r.score), repr(r.rank_score), repr(sorted(r.breakdown.items(), key=str)))
            for r in found]


@pytest.fixture(autouse=True)
def _restore_fastcalc():
    yield
    C.use_fastcalc(C.FASTCALC)


@pytest.fixture(scope="module")
def cands():
    from cursed_words_solver.sim.game.agent import Candidates

    return Candidates(effort=0.05, cheap_floor=True)


def _record(cands, finds):
    """Run ``cands._find`` on each (board, loadout, top_n) with the reference scorer;
    returns the find outputs and every score call (plan, path, word, words)."""
    calls = []
    outs = []
    C.use_fastcalc(False)
    ref = EnginePlan._score_ref

    def spy(self, path, word="", *, words=None):
        calls.append((self, list(path), word, words))
        return ref(self, path, word, words=words)

    EnginePlan.score = spy
    try:
        for board, loadout, top_n in finds:
            ExactSearch._enum_cache.clear()
            outs.append(_norm(cands._find(copy.deepcopy(board), copy.deepcopy(loadout), top_n)))
    finally:
        C.use_fastcalc(False)
    return outs, calls


@pytest.fixture(scope="module")
def game_finds(cands):
    """(board, loadout, top_n) of the first finds of each seeded game (reference scorer)."""
    from cursed_words_solver.rl.actions import Limits
    from cursed_words_solver.rl.env import CWEnv
    from cursed_words_solver.sim.game.agent import Candidates

    finds = []
    orig = Candidates._find

    def rec(self, board, loadout, top_n):
        finds.append((copy.deepcopy(board), copy.deepcopy(loadout), top_n))
        return orig(self, board, loadout, top_n)

    C.use_fastcalc(False)
    Candidates._find = rec
    try:
        env = CWEnv(cands, Limits(afterstates=False))
        for ch, crown, seed in GAMES:
            rng = random.Random(seed)
            st = env.reset(character=ch, crown=crown, seed=seed)
            n0 = len(finds)
            while not env.done and len(finds) - n0 < FINDS_PER_GAME:
                subs = [c for c in st.cands if c.action.kind == "submit"]
                if subs and rng.random() < 0.9:
                    a = subs[0 if rng.random() < 0.7 else rng.randrange(len(subs))].action
                else:
                    a = rng.choice(st.cands).action
                env.step(a)
                if not env.done:
                    st = env.current()
    finally:
        Candidates._find = orig
        C.use_fastcalc(C.FASTCALC)
    assert len(finds) >= len(GAMES) * 3
    return finds


# --- heavy-item loadouts -----------------------------------------------------------

_POOL_EXTRA = ("Overhand", "Hourglass", "CableCar", "FullMoon", "KingOfTheBridge", "HungrySnake", "Martini",
               "KokeshiDolls", "RightHumanHand", "LeftHumanHand")
_SPECIAL = ["overhand", "hourglass", "scissors", "snapshot", "frankenstein", "random_access_memory", "cable_car",
            "ruler", "mutating_dna", "stiletto", "human_hands", "right_human_hand", "left_human_hand", "full_moon",
            "bicycle", "birthday_cake", "movie_camera", "nest_egg", "error"]
_CHALLENGES = ["", "", "", "TheBonesRound", "Lexographer", "PlayingFavourites", "SicilianDefense", "Cursophobia"]


def _item_row(rng, pool, slug, depth=0):
    info = ITEMS[slug]
    row = {"id": slug, "levels": [rng.randint(1, 3) for _ in info.components],
           "values": [rng.choice([0, 1, 2, 3, 5, 10, 25, 150]) for _ in info.components],
           "colours": [rng.choice(["Red", "Blue", "Void", "Shiny", "Normal"])] if info.colours or rng.random() < 0.2 else [],
           "fields": {}}
    if info.cls in ("LuckyDice", "Dartboard"):
        row["fields"]["_targetNumber"] = rng.randint(1, 20)
    if info.cls == "CrystalBall":
        row["fields"]["ChosenCurseType"] = rng.choice(["Blank", "Number", "Chess", "Card", "Wobbly", "Currency"])
    if info.cls == "EightBall":
        row["fields"]["_selectedPiece"] = rng.choice(["Pawn", "Knight", "Rook", "Queen"])
    if depth == 0 and info.cls in ("RandomAccessMemory", "Frankenstein", "Snapshot"):
        k = 1 if info.cls == "Snapshot" else rng.randint(1, 3)
        row["nested"] = [_item_row(rng, pool, rng.choice(pool), 1) for _ in range(k)]
    return row


def _heavy(finds, seed: int, every: int):
    from cursed_words_solver.engine.items import SCORING_CLASSES

    rng = random.Random(seed)
    pool = sorted(s for s, i in ITEMS.items() if i.cls in SCORING_CLASSES or i.cls in _POOL_EXTRA)
    special = [s for s in _SPECIAL if s in ITEMS]
    out = []
    for board, loadout, top_n in finds[::every]:
        b, lo = copy.deepcopy(board), copy.deepcopy(loadout)
        ex = dict(lo.extras or {})
        st = ex.get("item_states")
        st = json.loads(st) if isinstance(st, str) else dict(st or {})

        def slots():
            return [_item_row(rng, pool, rng.choice(special if rng.random() < 0.3 else pool))
                    if rng.random() < 0.85 else None for _ in range(5)]

        st["stickers"], st["stamps"] = slots(), slots()
        if rng.random() < 0.3:
            st["pin"] = _item_row(rng, pool, rng.choice(["random_access_memory", "human_hands"] + pool[:20]))
        ex["item_states"] = json.dumps(st)
        ex["challenge_game_class"] = rng.choice(_CHALLENGES)
        if rng.random() < 0.3:
            ex["hourglass_count"] = 1
        r = rng.random()
        if r < 0.15:
            ex["boss_modifiers"] = json.dumps(["capybara"])
            ex["boss_modifier_floor_mods"] = json.dumps({"capybara": rng.choice([1, 2])})
        elif r < 0.35:
            ex["boss_modifiers"] = json.dumps([rng.choice(["salamander", "fox", "robo_monkey"])])
            ex["boss_floor_modification"] = rng.randint(1, 3)
        lo.extras = ex
        out.append((b, lo, top_n))
    return out


# --- comparisons -------------------------------------------------------------------


def _replay_calls(calls) -> int:
    """Score every call reference-then-fast on the same plan (fast caches go cold -> warm)."""
    step = max(1, len(calls) // MAX_CALLS)
    n = 0
    for plan, path, word, words in calls[::step]:
        C.use_fastcalc(False)
        a = plan.score(list(path), word, words=words)
        C.use_fastcalc(True)
        b = plan.score(list(path), word, words=words)
        assert _key(a) == _key(b), (path, word, a.score, b.score)
        n += 1
    return n


def _compare_finds(cands, finds, outs_ref):
    C.use_fastcalc(True)
    for (board, loadout, top_n), ref in zip(finds, outs_ref):
        ExactSearch._enum_cache.clear()
        assert _norm(cands._find(copy.deepcopy(board), copy.deepcopy(loadout), top_n)) == ref


def test_game_finds_score_parity(cands, game_finds):
    outs, calls = _record(cands, game_finds)
    assert len(calls) > 1000
    assert _replay_calls(calls) > 500
    _compare_finds(cands, game_finds, outs)


def test_heavy_loadout_parity(cands, game_finds):
    finds = _heavy(game_finds, seed=1, every=2) + _heavy(game_finds, seed=2, every=3)
    outs, calls = _record(cands, finds)
    assert calls
    _replay_calls(calls)
    _compare_finds(cands, finds, outs)


def test_capybara_orderings_and_cache_lifecycle(cands, game_finds):
    """``solver._expected_score`` swaps plan.stickers / stamps (identity-keyed order cache);
    copies / pickles drop the cache; ``invalidate_score_cache`` rebuilds it."""
    from cursed_words_solver.engine.solver import _orderings, capybara_score_range

    _, calls = _record(cands, _heavy(game_finds, seed=3, every=4))
    plans = list({id(p): (p, path, word) for p, path, word, _ in calls}.values())[:4]
    assert plans
    for plan, path, word in plans:
        C.use_fastcalc(False)
        ref = capybara_score_range(plan, path, word, 1)
        orderings = _orderings(plan, 2, random.Random(0), limit=60)
        ref_each = [_key(_swap_score(plan, o, path, word)) for o in orderings]
        C.use_fastcalc(True)
        assert capybara_score_range(plan, path, word, 1) == ref
        assert [_key(_swap_score(plan, o, path, word)) for o in orderings] == ref_each
        assert "_fastcalc" in plan.__dict__
        for clone in (copy.deepcopy(plan), pickle.loads(pickle.dumps(plan)), copy.copy(plan)):
            assert "_fastcalc" not in clone.__dict__
            assert _key(clone.score(list(path), word)) == _key(plan._score_ref(list(path), word))
        plan.invalidate_score_cache()
        assert "_fastcalc" not in plan.__dict__
        assert _key(plan.score(list(path), word)) == _key(plan._score_ref(list(path), word))


def _swap_score(plan, ordering, path, word):
    saved = (plan.stickers, plan.stamps)
    try:
        plan.stickers, plan.stamps = ordering
        return plan.score(list(path), word)
    finally:
        plan.stickers, plan.stamps = saved


def test_chess_selection_parity():
    """Take / en passant / slide distance selections (shared and cached on the fast path)
    under items that read them, with Full Moon / King of the Bridge / Sicilian variants."""
    from cursed_words_solver.models import CurseType, Loadout, Tile

    from tests.engine.test_engine_units import _board

    pieces = {(0, 0): (CurseType.CHESS_ROOK, "white"), (0, 3): (CurseType.CHESS_KING, "black"),
              (1, 1): (CurseType.CHESS_BISHOP, "black"), (1, 4): (CurseType.CHESS_QUEEN, "white"),
              (2, 2): (CurseType.CHESS_PAWN, "white"), (2, 3): (CurseType.CHESS_PAWN, "black"),
              (3, 1): (CurseType.CHESS_PAWN, "black"), (3, 2): (CurseType.CHESS_PAWN, "white"),
              (4, 0): (CurseType.CHESS_KNIGHT, "white"), (4, 4): (CurseType.CHESS_ROOK, "black")}

    def board():
        b = _board(["catdo", "xqzex", "sjxxa", "xxrxk", "xexxs"])
        for (r, c), (curse, colour) in pieces.items():
            b.tiles[r][c] = Tile(r, c, "?", "?", 5.0, curse=curse, metadata={"source": "melmod", "chess_color": colour})
        return b

    def slots(slugs):
        return [{"id": s, "levels": [2 for _ in ITEMS[s].components], "values": [c[2] + 1 for c in ITEMS[s].components],
                 "fields": {}} for s in slugs] + [None] * (5 - len(slugs))

    rng = random.Random(7)
    pairs = [[a, b] for a in range(25) for b in range(25) if a != b]
    triples = [rng.sample(range(25), 3) for _ in range(400)]
    for extra, challenge in (([], ""), (["full_moon"], ""), (["king_of_the_bridge"], ""), ([], "SicilianDefense"),
                             (["crystal_ball", "oden"], "Lexographer")):
        states = {"stickers": slots(["zebra", "jolly_roger", "kangaroo", "dagger", "magic_8_ball"]),
                  "stamps": slots(["creaky_chair", "broom", "ruler", "lollipop"] + extra[:1]),
                  "pin": slots(extra[1:2] or ["poker_face"])[0]}
        lo = Loadout(extras={"item_states": json.dumps(states), "challenge_game_class": challenge})
        plan = EnginePlan.build(board(), lo)
        for path in pairs + triples:
            C.use_fastcalc(False)
            a = plan.score(path)
            C.use_fastcalc(True)
            assert _key(a) == _key(plan.score(path)), (extra, challenge, path)


def test_is_cursed_and_curse_type_memo(game_finds):
    for board, loadout, _ in _heavy(game_finds, seed=4, every=3):
        plan = EnginePlan.build(board, loadout)
        assert [_is_cursed(plan, t, True) for t in plan.grid.tiles] == [_is_cursed(plan, t, False) for t in plan.grid.tiles]
    C.use_fastcalc(True)
    assert I._selection_curse_types is I._selection_curse_types_memo
    C.use_fastcalc(False)
    assert I._selection_curse_types is I._selection_curse_types_ref and EnginePlan.score is EnginePlan._score_ref


def _is_cursed(plan, t, fast: bool) -> bool:
    C.use_fastcalc(fast)
    return plan.is_cursed(t)
