"""Quests whose grids hold no board word: Empty Grid (blank) and Advent Calendar (``Sudoku``).

``GenerateBasicGridData`` leaves every Empty Grid tile empty and fills Advent Calendar grids
with the numbers 1-25 (a number only counts as the letter at its own position), so play
comes from consumable rack tiles placed first (``ApplyConsumableTile``). ``Candidates``
falls back to placement words when the board alone has none.
"""

from __future__ import annotations

import pytest

from cursed_words_solver.sim.game.agent import Action, Candidates, apply, legal_actions, submit_action
from cursed_words_solver.sim.game.core import Tile
from cursed_words_solver.sim.game.run import Game, RunConfig

WORDS = ("cat", "act", "tact", "zzz")


@pytest.fixture(scope="module")
def wordlist(tmp_path_factory):
    p = tmp_path_factory.mktemp("words") / "words.txt"
    p.write_text("\n".join(WORDS) + "\n", encoding="utf-8")
    return p


@pytest.fixture(scope="module")
def cands(wordlist):
    from cursed_words_solver.dictionary import WordDictionary

    return Candidates(wordlist, dictionary=WordDictionary(wordlist), effort=0.05)


def _game(quest: str, wordlist, character="BonesTheDog", seed=7) -> Game:
    return Game(RunConfig(character=character, ascension=0, challenge=quest, seed=seed, wordlist=wordlist))


def _set_rack(g: Game, faces) -> None:
    rack: list = [None] * len(g.player.consumables)
    for i, f in enumerate(faces):
        t = Tile()
        if isinstance(f, int):
            t.set_number(f)
        else:
            t.set_letter(f)
        t.was_consumable = True
        rack[i] = t
    g.player.consumables = rack


def _board_only(cands: Candidates, g: Game) -> list:
    from cursed_words_solver.sim.game.bridge import board_and_loadout

    board, loadout = board_and_loadout(g.encounter)
    return cands._find(board, loadout, 5)


def test_empty_grid_board_is_blank_and_forces_sandy(wordlist):
    g = _game("EmptyGrid", wordlist)
    assert g.phase == "encounter"
    assert g.player.character == "SandySaguaro"
    assert all(t.empty for t in g.encounter.grid.available())


def test_empty_grid_words_come_from_rack_placements(cands, wordlist):
    g = _game("EmptyGrid", wordlist)
    _set_rack(g, ["c", "a", "t"])
    assert _board_only(cands, g) == []
    opts = cands.words(g, 5)
    assert opts, "no word offered on an empty grid with c/a/t in the rack"
    assert {o.word for o in opts} <= {"cat", "act"}
    best = opts[0]
    assert len(best.placements) == len(best.path) == 3
    assert [(x, y) for _, x, y in best.placements] == best.path  # placed in path order
    a = submit_action(best)
    assert a.kind == "submit" and len(a.args) == 3
    assert any(x.args == a.args for x in legal_actions(g, cands))
    used = g.player.run.stats_consumables_used
    res = apply(g, a)
    assert res.score > 0
    # rack tiles were spent (Sandy refills the rack for the next grid, so count uses)
    assert g.player.run.stats_consumables_used == used + 3


def test_rack_words_may_repeat_a_letter(cands, wordlist):
    g = _game("EmptyGrid", wordlist)
    _set_rack(g, ["t", "a", "c", "t"])
    opts = cands.words(g, 5)
    assert opts and opts[0].word == "tact"
    assert sorted(ri for ri, _, _ in opts[0].placements) == [0, 1, 2, 3]


def test_advent_calendar_numbers_chain_as_positional_wildcards(cands, wordlist):
    g = _game("Sudoku", wordlist)
    grid = g.encounter.grid
    assert sorted(t.number for t in grid.tiles) == list(range(1, 26))
    _set_rack(g, [1, 2, 3, 4, 5])
    if _board_only(cands, g):
        pytest.skip("this seed has a board word")
    opts = cands.words(g, 5)
    assert opts and opts[0].placements
    best = opts[0]
    rack = g.player.consumables
    nums = [rack[ri].number for ri, _, _ in best.placements]
    path_pos = [best.path.index((x, y)) + 1 for _, x, y in best.placements]
    assert nums == path_pos  # number N sits at word position N
    res = apply(g, submit_action(best))
    assert res.score > 0


def test_no_fallback_when_board_has_a_word(cands, wordlist):
    g = _game("EmptyGrid", wordlist)
    tiles = g.encounter.grid.tiles
    for t, ch in zip(tiles[:3], "cat"):
        t.set_letter(ch)
    _set_rack(g, ["q", "q", "q"])  # spells nothing
    opts = cands.words(g, 5)
    assert opts and all(not o.placements for o in opts)
    assert len(submit_action(opts[0]).args) == 2


def test_rack_word_beating_the_board_word_is_offered(cands, wordlist):
    g = _game("EmptyGrid", wordlist)
    for t, ch in zip(g.encounter.grid.tiles[:3], "cat"):
        t.set_letter(ch)
    _set_rack(g, ["z", "z", "z"])
    opts = cands.words(g, 5)
    board = [o for o in opts if not o.placements]
    rack = [o for o in opts if o.placements]
    assert board and rack and rack[0].word == "zzz" and rack[0].score > board[0].score
    assert opts[0] is rack[0]  # merged by score


def test_rl_env_offers_rack_word_and_reaches_shop(cands, wordlist):
    from cursed_words_solver.rl.env import CWEnv

    env = CWEnv(cands)
    env.reset(character="WetDennis", crown=0, seed=41501000, quest="EmptyGrid")
    _set_rack(env.game, ["t", "a", "c", "t"])
    st = env.current()
    subs = [c for c in st.cands if c.action.kind == "submit"]
    assert subs and all(len(c.action.args) == 3 for c in subs)
    for _ in range(10):
        if env.game.phase != "encounter":
            break
        st = env.current()
        sub = next((c for c in st.cands if c.action.kind == "submit"), None)
        if sub is None:
            break
        env.step(sub.action)
    # "tact" alone may not clear the target; any word is progress, and a cleared grid
    # set goes to the shop
    assert env.game.player.run.stats.words_submitted


def test_assistant_says_where_to_place_rack_tiles(cands, wordlist):
    pytest.importorskip("torch")
    from cursed_words_solver.rl.assistant import placement_note

    g = _game("EmptyGrid", wordlist)
    _set_rack(g, ["c", "a", "t"])
    opt = cands.words(g, 1)[0]
    note = placement_note(g, submit_action(opt))
    assert note.startswith("first place ") and note.count(" at row ") == 3
    for (ri, x, y), part in zip(opt.placements, note[len("first place "):].split(", ")):
        assert part == f"{g.player.consumables[ri].srep()} at row {g.encounter.grid.height - y} col {x + 1}"
    assert placement_note(g, Action("skip")) == ""


def test_two_wrongs_word_score_counts_toward_target(cands, wordlist):
    """Two Wrongs negates the engine score (EncounterController ``*= -1``): a word option's
    score is the target progress, so a negative-raw word is the one that clears."""
    g = _game("TwoWrongs", wordlist)
    for t, ch in zip(g.encounter.grid.tiles[:3], "cat"):
        t.set_letter(ch)
    opts = cands.words(g, 5)
    assert opts
    o = opts[0]
    assert o.raw is not None and o.score == -o.raw
    a = submit_action(o)
    assert f"raw {o.raw}" in a.label and a.label.endswith(f"({o.score})")
    before = g.encounter.remaining_target
    res = apply(g, a)
    assert res.score == o.score
    assert g.player.run.stats.words_submitted[-1].score == o.score
    assert before - o.score == g.player.run.stats.words_submitted[-1].remainder


def test_bullseye_candidates_one_per_score_exact_hit_first(cands, wordlist):
    from cursed_words_solver.sim.game.agent import bullseye_key, clears

    g = _game("Bullseye", wordlist, character="HayleyBayles")
    for t, ch in zip(g.encounter.grid.tiles[:4], "tact"):
        t.set_letter(ch)
    opts = cands.words(g, 8)
    assert opts
    scores = [o.score for o in opts]
    assert len(scores) == len(set(scores))  # no score repeated
    rem = g.encounter.remaining_target
    keys = [bullseye_key(rem, s) for s in scores]
    assert [k[0] for k in keys] == sorted(k[0] for k in keys)  # an exact hit would come first
    hit = opts[0].score
    g.encounter.remaining_target = hit
    assert clears(g, hit) and not clears(g, hit + 1)
    best = cands.words(g, 8)[0]
    assert best.score == hit


def test_microphone_item_names_are_offered(tmp_path):
    """Microphone (In The Beginning's only item source): an un-owned item's name is offered
    even when it scores below every dictionary word, and submitting it adds the item."""
    from cursed_words_solver.dictionary import WordDictionary

    wl = tmp_path / "words.txt"
    wl.write_text("fanatic\nfan\n", encoding="utf-8")
    c = Candidates(wl, dictionary=WordDictionary(wl), effort=0.05)
    g = _game("InTheBeginning", wl, character="NathaServo")
    assert g.player.unpacked_of("Microphone")
    for t, ch in zip(g.encounter.grid.tiles[:4], "fans"):
        t.set_letter(ch)
    opts = c.words(g, 1)
    named = [o for o in opts if o.grants_item]
    assert named and named[0].word == "fan" and named[0].grants_item == "Fan"
    assert "adds Fan" in submit_action(named[0]).label
    apply(g, submit_action(named[0]))
    assert any(i.game_class == "Fan" for i in g.player.all_items())


def test_honeypot_pair_item_names_are_offered(tmp_path):
    """Honeypot + Microphone: a two-word item name ("gold fish") spelled across the path is
    offered as two words, and submitting it adds the item."""
    from cursed_words_solver.dictionary import WordDictionary
    from cursed_words_solver.sim.game.items import make_item

    wl = tmp_path / "words.txt"
    wl.write_text("goldfish\ngold\nfish\n", encoding="utf-8")
    c = Candidates(wl, dictionary=WordDictionary(wl), effort=0.05)
    g = _game("InTheBeginning", wl, character="NathaServo")
    assert g.player.add_item(make_item("Honeypot"), g.rng, acquire=False)
    assert g.player.unpacked_of("Microphone") and g.player.unpacked_of("Honeypot")
    at = {(t.x, t.y): t for t in g.encounter.grid.tiles}
    for xy, ch in zip([(0, 0), (1, 0), (2, 0), (3, 0), (4, 0), (4, 1), (3, 1), (2, 1)], "goldfish"):
        at[xy].set_letter(ch)
    opts = c.words(g, 1)
    assert not any(o.grants_item for o in opts if o.words == ["goldfish"])  # one word: not the name
    named = [o for o in opts if o.grants_item == "GoldFish"]
    assert named and named[0].words == ["gold", "fish"]
    assert "adds" in submit_action(named[0]).label
    apply(g, submit_action(named[0]))
    assert any(i.game_class == "GoldFish" for i in g.player.all_items())


def test_drag_reorder_shifts_slots_not_swaps(wordlist):
    """``ItemReorderController``: RemoveAt(from) then Insert(to) — slots in between shift."""
    from cursed_words_solver.sim.game.items import make_item

    g = _game("PlayingFavourites", wordlist, character="SockHead")
    p = g.player
    for cls in ("Candle", "Fan", "Ogre"):
        assert p.add_item(make_item(cls), g.rng, acquire=False)
    before = [it.game_class if it else None for it in p.stickers]
    filled = [i for i, it in enumerate(p.stickers) if it is not None]
    src, dst = filled[0], filled[-1]
    assert g.move("sticker", src, dst)
    want = list(before)
    want.insert(dst, want.pop(src))
    assert [it.game_class if it else None for it in p.stickers] == want


def test_playing_favourites_ignores_non_favourite_hourglass(wordlist):
    """Under Playing Favourites ``GetUnpackedItemsOfType`` only sees favourites, so a
    non-favourite Hourglass must not reverse scoring order."""
    from cursed_words_solver.engine.calc import EnginePlan
    from cursed_words_solver.sim.game.bridge import board_and_loadout

    from cursed_words_solver.sim.game.items import make_item

    g = _game("PlayingFavourites", wordlist, character="SockHead")
    p = g.player
    assert p.add_item(make_item("Hourglass"), g.rng, acquire=False)
    kind, arr = next((k, a) for k, a in (("sticker", p.stickers), ("stamp", p.stamps))
                     if any(it is not None and it.game_class == "Hourglass" for it in a))
    hg = next(i for i, it in enumerate(arr) if it is not None and it.game_class == "Hourglass")
    hand = "LeftHumanHand" if kind == "sticker" else "RightHumanHand"
    h = next(i for i, it in enumerate(arr) if it is not None and it.game_class == hand)
    fav = h - 1 if kind == "sticker" else h + 1
    if hg == fav:  # make sure it is not the favourite
        assert g.move(kind, hg, 4 if fav != 4 else 0)
        hg = next(i for i, it in enumerate(arr) if it is not None and it.game_class == "Hourglass")
        h = next(i for i, it in enumerate(arr) if it is not None and it.game_class == hand)
        assert hg != (h - 1 if kind == "sticker" else h + 1)
    board, loadout = board_and_loadout(g.encounter)
    plan = EnginePlan.build(board, loadout)
    assert not plan.hourglass_odd
    assert "Hourglass" not in plan.item_classes


@pytest.mark.parametrize("quest,kind", [("Masochist", "sticker"), ("InTheBeginning", "sticker"),
                                        ("InTheBeginning", "stamp"), ("Antiphilatelist", "stamp")])
def test_hidden_shop_slots_cannot_be_used(wordlist, quest, kind):
    """``ShopController`` hides these slots, so an offer generated there (e.g. the
    first-shop character starter sticker) can't be bought or frozen, and isn't offered."""
    for seed in range(1, 6):
        g = Game(RunConfig(character="NinaNix", ascension=0, challenge=quest, seed=seed,
                           wordlist=wordlist, character_never_won=True))
        from cursed_words_solver.sim.game.shop import Shop

        from cursed_words_solver.sim.game.player import Node

        g.player.run.node = Node.SHOP_ONE
        s = g.shop = Shop(g.player, g.rng, character_never_won=True)
        g.encounter = None
        stock = s.stickers if kind == "sticker" else s.stamps
        for k, o in enumerate(stock):
            assert not s.can_buy(kind, k)
            if o is not None:
                assert not s.toggle_freeze(kind, k)
        acts = legal_actions(g)
        assert not any(a.kind in ("buy", "freeze", "hippo") and a.args[0] == kind for a in acts)


def test_money_word_offered_when_best_word_clears(tmp_path):
    """Do Not Pass Go pays nothing for a clear, so a non-clearing word over currency tiles
    (in-grid money) is offered next to the clearing words while grids remain."""
    from cursed_words_solver.dictionary import WordDictionary

    wl = tmp_path / "words.txt"
    wl.write_text("tacts\nsat\n", encoding="utf-8")
    c = Candidates(wl, dictionary=WordDictionary(wl), effort=0.05)
    g = Game(RunConfig(character="Spike", ascension=0, challenge="DoNotPassGo", seed=3, wordlist=wl))
    tiles = g.encounter.grid.tiles
    for t, ch in zip(tiles[:5], "tacts"):
        t.set_letter(ch)
    tiles[5].set_letter("a")
    tiles[6].set_letter("t")
    tiles[10].set_currency("$")  # reads as "s": $-a-t spells "sat"
    best = c.words(g, 1)[0]
    g.encounter.remaining_target = best.score  # the best word just clears
    opts = c.words(g, 1)
    money = [o for o in opts if o.money]
    assert money and money[0].word == "sat" and money[0].score < g.encounter.remaining_target
    assert "no clear" in submit_action(money[0]).label
    m0 = g.player.money
    apply(g, submit_action(money[0]))
    assert g.player.money - m0 == money[0].money and g.encounter.remaining_target > 0


def test_chromaphobia_normal_rack_tile_unlocks_coloured_square(tmp_path):
    """Chromaphobia blocks words with coloured tiles; a Normal rack tile placed on a coloured
    square replaces it (``ApplyConsumableTile`` copies the rack tile), so that square is usable."""
    from cursed_words_solver.dictionary import WordDictionary
    from cursed_words_solver.sim.game import core as C

    wl = tmp_path / "words.txt"
    wl.write_text("cat\ncats\n", encoding="utf-8")
    c = Candidates(wl, dictionary=WordDictionary(wl), effort=0.05)
    g = Game(RunConfig(character="WetDennis", ascension=0, challenge="Chromaphobia", seed=4, wordlist=wl))
    grid = g.encounter.grid
    for t in grid.tiles:
        t.set_letter("q")
        t.tile_type = C.NORMAL
    for x, ch in enumerate("cats"):
        grid.at(x, 4).set_letter(ch)
    grid.at(3, 4).tile_type = C.RED  # the s is unusable
    _set_rack(g, ["s"])
    opts = c.words(g, 5)
    assert any(o.word == "cat" and not o.placements for o in opts)  # board word kept
    rack = [o for o in opts if o.placements and o.word == "cats"]
    assert rack and rack[0].placements[0][1:] == (3, 4)


def test_two_wrongs_shortlist_keeps_most_negative_paths():
    """Two Wrongs wins with the most negative word: when there are too many paths to score,
    the value shortlist keeps the lowest-value tail too (not only the highest)."""
    from types import SimpleNamespace

    from cursed_words_solver.engine.search import ExactSearch

    tiles = [SimpleNamespace(value=v) for v in range(-20, 20)]
    items = [((i,), f"w{i}") for i in range(40)] + [((i, i), f"w{i}") for i in range(40)]

    def short(challenge):
        fake = SimpleNamespace(tiles=tiles, max_exact_paths=8, challenge=challenge)
        return {p for p, _ in ExactSearch._shortlist(fake, items)}

    assert (0, 0) not in short("")  # value -40: dropped normally
    assert (0, 0) in short("TwoWrongs") and (39, 39) in short("TwoWrongs")


def _shop_game(quest, wordlist, character="WetDennis", seed=3) -> Game:
    from cursed_words_solver.sim.game.player import Node
    from cursed_words_solver.sim.game.shop import Shop

    g = Game(RunConfig(character=character, ascension=0, challenge=quest, seed=seed, wordlist=wordlist))
    g.player.run.node = Node.SHOP_ONE
    g.shop = Shop(g.player, g.rng)
    g.encounter = None
    return g


def test_rack_tile_rank_prefers_wildcards_then_missing_letters():
    from cursed_words_solver.sim.game.policy import rack_tile_rank

    joker, a, s, eight = Tile(), Tile(), Tile(), Tile()
    joker.set_glyph("chess")
    a.set_letter("a")
    s.set_letter("s")
    eight.set_number(8)
    assert rack_tile_rank(joker, []) > rack_tile_rank(a, []) > rack_tile_rank(s, [])  # no vowels yet
    assert rack_tile_rank(s, ["a", "e", "o"]) > rack_tile_rank(a, ["a", "e", "o"])  # vowels covered
    assert rack_tile_rank(eight, []) is None  # 8 is only a wildcard as an 8th letter


@pytest.mark.parametrize("quest", ["Sudoku", "EmptyGrid"])
def test_rack_quest_shop_buys_rack_tiles_first(wordlist, cands, quest):
    """Advent Calendar / Empty Grid: the board spells nothing, so with an empty rack the
    shop's first move is a rack tile."""
    from cursed_words_solver.sim.game.policy import AdvicePolicy, PowerConfig

    g = _shop_game(quest, wordlist)
    g.player.consumables = [None] * len(g.player.consumables)
    g.player.money = 30
    pol = AdvicePolicy(cands, PowerConfig(rack_floor=6))  # off by default (see PowerConfig)
    a = pol._shop_move(g)
    assert a.kind == "buy" and a.args[0] == "tile" and a.label.startswith("rack quest")


def test_free_item_not_forfeited_by_plan_restock(wordlist, cands):
    """The stage-1 free item (``free_item_active``) is lost on a restock: a committed build
    plan neither restocks past it nor refuses it as off-plan."""
    from cursed_words_solver.sim.game.policy import AdvicePolicy, PowerConfig

    g = _shop_game(None, wordlist, character="BonesTheDog")
    assert g.shop.free_item_active
    g.player.money = 20
    pol = AdvicePolicy(cands, PowerConfig(probe_seeds=1, probe_grids=1, build_plan="Curse"))
    for o in (*g.shop.stickers, *g.shop.stamps):
        if o is not None:
            assert pol._offer_ok(g, o.item.game_class)
    step = pol._build_plan_step(g)
    assert step is None or step.kind != "reroll_shop"


def test_clearing_word_spares_rack_tiles(wordlist, cands):
    """When several words clear, the one placing the fewest rack tiles is submitted."""
    from cursed_words_solver.sim.game.agent import WordOption
    from cursed_words_solver.sim.game.policy import PowerPolicy

    g = _game("Sudoku", wordlist)
    big = WordOption(word="aahed", words=["aahed"], path=[(0, 0)], score=10 ** 6, placements=[(0, 0, 0)] * 5)
    small = WordOption(word="aah", words=["aah"], path=[(0, 0)], score=10 ** 6 - 1, placements=[(0, 0, 0)] * 2)
    pol = PowerPolicy(cands)
    pol.enc_cands = lambda game: type("C", (), {"words": staticmethod(lambda game, n: [big, small])})()
    a = pol._encounter(g)
    assert a.args[1] == ("aah",) or list(a.args[1]) == ["aah"]


@pytest.mark.parametrize("quest,plan", [("Cursophobia", ""), ("TwoWrongs", ""), ("PlayingFavourites", ""),
                                        ("Chromaphilia", "Rainbow"), ("Chromaphobia", "Colourless"), (None, "Curse")])
def test_quest_plans_override_the_default_plan(wordlist, cands, quest, plan):
    from cursed_words_solver.sim.game.policy import FastAdvicePolicy, PowerConfig

    pol = FastAdvicePolicy(cands, PowerConfig(probe_seeds=1, probe_grids=1, build_plan="Curse"))
    g = _game(quest, wordlist, character="WetDennis")
    pol._tune(g)
    assert pol.cfg.build_plan == plan
    rules = FastAdvicePolicy(cands, PowerConfig(probe_seeds=1, probe_grids=1, build_plan=""))
    rules._tune(g)
    assert rules.cfg.build_plan == ""  # the rules player stays plan-free


def test_forced_sell_keeps_the_strongest_items(wordlist, cands):
    """Hyena's forced sell: the sale that keeps the most probe power, not stamps first."""
    from cursed_words_solver.sim.game.items import make_item
    from cursed_words_solver.sim.game.policy import FastAdvicePolicy, PowerConfig

    g = _game(None, wordlist, character="WetDennis")
    p = g.player
    p.stickers = [None] * len(p.stickers)
    p.stamps = [None] * len(p.stamps)
    assert p.add_item(make_item("Avocado"), g.rng, acquire=False)
    assert p.add_item(make_item("Broom"), g.rng, acquire=False)
    pol = FastAdvicePolicy(cands, PowerConfig(probe_seeds=1, probe_grids=1))
    pol.power = lambda game, **kw: 100.0 * any(i.game_class == "Avocado" for i in game.player.all_items()) + 1
    a = pol._cheapest_sell(g)
    sold = (p.stickers if a.args[0] == "sticker" else p.stamps)[a.args[1]]
    assert sold.game_class == "Broom"


def test_microphone_name_rejected_when_its_item_zeroes_scores(tmp_path):
    """Oden multiplies by the curse types in the word (x0 with none): spelling its name
    would zero every later word, so it is not submitted as a name."""
    from cursed_words_solver.dictionary import WordDictionary
    from cursed_words_solver.sim.game.agent import WordOption
    from cursed_words_solver.sim.game.policy import PowerPolicy

    wl = tmp_path / "words.txt"
    wl.write_text("fans\noden\n", encoding="utf-8")
    c = Candidates(wl, dictionary=WordDictionary(wl), effort=0.05)
    g = _game("InTheBeginning", wl, character="NathaServo")
    for t, ch in zip(g.encounter.grid.tiles[:4], "fans"):
        t.set_letter(ch)
    ref = WordOption(word="fans", words=["fans"], path=[(0, 0), (1, 0), (2, 0), (3, 0)], score=8)
    oden = WordOption(word="oden", words=["oden"], path=[(0, 0)], score=1, grants_item="Oden")
    fan = WordOption(word="fan", words=["fan"], path=[(0, 0)], score=1, grants_item="Fan")
    pol = PowerPolicy(c)
    assert pol._best_name(g, [ref, oden]) is None
    assert pol._best_name(g, [ref, oden, fan]) is fan
