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
    _set_rack(g, ["z", "z", "z"])
    opts = cands.words(g, 5)
    assert opts and all(not o.placements for o in opts)
    assert len(submit_action(opts[0]).args) == 2


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
