"""DLC search (engine/dlc_search.py): movement and upper/lower-case words."""

from __future__ import annotations

from cursed_words_solver.engine import EnginePlan
from cursed_words_solver.engine.search import ExactSearch
from cursed_words_solver.engine.trie import CsrTrie
from cursed_words_solver.models import Loadout

from tests.engine.test_dlc_items import _put
from tests.engine.test_engine_units import _board


def _search(board, words, loadout=None) -> ExactSearch:
    plan = EnginePlan.build(board, loadout or Loadout())
    return ExactSearch(plan, CsrTrie.from_words(words))


def _words(search: ExactSearch) -> set[str]:
    return {c.word for c in search.run(top_n=0)}


def test_lowercase_letters_form_a_second_word() -> None:
    # Uppercase C-A-T and lowercase d-o on one path: "cat" + "do".
    b = _board(["catdo", "zzzzz", "zzzzz"])
    _put(b, 0, 3, "Letter", "d", 2, flags=["lowercase"])
    _put(b, 0, 4, "Letter", "o", 1, flags=["lowercase"])
    s = _search(b, ["cat", "do", "catdo"])
    assert s.dlc_mode
    found = _words(s)
    assert "cat do" in found or "do cat" in found
    best = s.run(top_n=1)[0]
    assert len(best.path) == 5


def test_wire_carries_the_path_in_a_straight_line() -> None:
    # c ║ t in a column with a wire in the middle: entering from above, the I wire
    # exits straight down (wires are wildcards, so "cat" is spelled c-?-t).
    b = _board(["czz", "zzz", "tzz"])
    _put(b, 1, 0, "Wire", "║", 1)
    s = _search(b, ["cat"])
    paths = {c.path for c in s.run(top_n=0)}
    assert (0, 3, 6) in paths


def test_wire_cannot_be_entered_diagonally() -> None:
    b = _board(["czz", "zzz", "zzt"])
    _put(b, 1, 1, "Wire", "║", 1)
    s = _search(b, ["cat"])
    assert (0, 4, 8) not in {c.path for c in s.run(top_n=0)}


def test_zodiac_moves_in_its_element_direction() -> None:
    # Fire signs (Aries) move right: from the sign only the three tiles to its right.
    from cursed_words_solver.engine.model import ZODIAC_ORDER

    b = _board(["zcz", "zat", "zzz"])
    _put(b, 1, 0, "Zodiac", ZODIAC_ORDER[0], 1)
    s = _search(b, ["cat", "zat"])
    tiles = s.plan.grid.tiles
    from cursed_words_solver.engine.dlc_search import DlcSearch, Sel

    ds = DlcSearch(s)
    nxt = {tiles[m.idx].x for m in ds.moves([3], [Sel(3)])}
    assert nxt == {1}


def test_engine_valid_word_and_movement_use_dlc_rules() -> None:
    from cursed_words_solver.engine.solver import engine_path_movement_ok

    b = _board(["czz", "zzz", "tzz"])
    _put(b, 1, 0, "Wire", "║", 1)
    s = _search(b, ["cat"])
    assert s.valid_word((0, 3, 6)) == "cat"
    assert engine_path_movement_ok(b, [0, 3, 6], None)
    b2 = _board(["czz", "zzz", "zzt"])
    _put(b2, 1, 1, "Wire", "║", 1)
    assert not engine_path_movement_ok(b2, [0, 4, 8], None)
