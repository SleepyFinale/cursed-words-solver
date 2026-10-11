"""Unit tests for the game-port engine: ScorePacket math, item hooks, exact search."""

from __future__ import annotations

import json
import time

from cursed_words_solver.engine import EnginePlan, packet as P
from cursed_words_solver.engine.calc import final_score
from cursed_words_solver.engine.search import ExactSearch
from cursed_words_solver.engine.state import Step, WordBonus
from cursed_words_solver.engine.trie import CsrTrie
from cursed_words_solver.models import Board, CurseType, Loadout, LoadoutItem, Tile, TileColor


def _board(rows: list[str], colors: dict[tuple[int, int], TileColor] | None = None) -> Board:
    """5x5 board of letter tiles ("?" = blank wildcard, digits = number tiles)."""
    colors = colors or {}
    from cursed_words_solver.engine.model import LETTER_VALUES

    grid = []
    for r, line in enumerate(rows):
        row = []
        for c, ch in enumerate(line):
            color = colors.get((r, c), TileColor.COLORLESS)
            if ch == "?":
                t = Tile(r, c, "?", "?", 0.0, color=color, curse=CurseType.WILDCARD)
            elif ch.isdigit():
                t = Tile(r, c, ch, ch, float(int(ch)), color=color, curse=CurseType.NUMBER, number_value=int(ch))
            else:
                bonus = 1 if color in (TileColor.RED, TileColor.BLUE) else 0
                t = Tile(r, c, ch, ch.upper(), float(LETTER_VALUES[ch] + bonus), color=color)
            t.metadata["source"] = "melmod"
            row.append(t)
        grid.append(row)
    return Board(tiles=grid, money=0)


# ---------------------------------------------------------------- ScorePacket


def test_packet_division_truncates_toward_zero() -> None:
    assert P.div(-7, 2) == -3
    assert P.div(7, -2) == -3
    assert P.div(7, 2) == 3


def test_packet_overflow_becomes_infinite() -> None:
    assert P.mul(P.INT64_MAX, 2) == P.INF
    assert P.add(P.INF, P.NEG_INF) == 0


def test_packet_scale_uses_bankers_rounding() -> None:
    assert P.scale(25, 0.1) == 2  # 2.5 -> 2
    assert P.scale(35, 0.1) == 4  # 3.5 -> 4


def test_final_score_applies_word_bonuses_in_step_order() -> None:
    steps = [
        Step(ts=[5, 5], money=0, consumables=0),
        Step(ts=[5, 5], money=0, consumables=0, wb=WordBonus(20, False)),
        Step(ts=[5, 5], money=0, consumables=0, wb=WordBonus(150, True)),
    ]
    assert final_score(steps) == (10 + 20) * 150 // 100


# ---------------------------------------------------------------- items


def _score(rows, path, stickers=(), stamps=(), colors=None, extras=None) -> int:
    board = _board(rows, colors)
    loadout = Loadout(
        stickers=[LoadoutItem(i, i, lvl) for i, lvl in stickers],
        stamps=[LoadoutItem(i, i, 1, "stamp") for i in stamps],
        extras=dict(extras or {}),
    )
    return EnginePlan.build(board, loadout).score(path).int_score


ROWS = ["cates", "bxxxx", "xxxxx", "xxxxx", "xxxxx"]


def test_neapolitan_counts_any_three_non_normal_colours() -> None:
    # Void counts as a colour (the old solver excluded white/void).
    colors = {(0, 0): TileColor.RED, (0, 1): TileColor.BLUE, (0, 2): TileColor.VOID}
    base = _score(ROWS, [0, 1, 2], colors=colors)
    with_neo = _score(ROWS, [0, 1, 2], stamps=["neapolitan"], colors=colors, extras={"neapolitan_percent": "100"})
    assert with_neo == base * 105 // 100


def test_bento_box_uses_last_word_of_encounter() -> None:
    extras = {"previous_word_first_letter": "c", "historic_words": json.dumps([{"word": "cat", "score": 5}])}
    plain = _score(ROWS, [0, 1, 2])
    assert _score(ROWS, [0, 1, 2], stamps=["bento_box"], extras=extras) == plain * 150 // 100


def test_down_under_multiplies_every_tile() -> None:
    assert _score(ROWS, [0, 1, 2], stickers=[("down_under", 1)]) == -3 * _score(ROWS, [0, 1, 2])


def test_item_states_export_gives_exact_levels_and_slots() -> None:
    # Retro-upgraded sticker: exported TimesUpgraded level says 1, components say 3.
    states = {
        "stickers": [None, {"id": "axe", "levels": [3], "values": [250], "fields": {}}, None, None, None],
        "stamps": [None] * 5,
    }
    rows = ["cat" + "xx", "xxxxx", "xxxxx", "xxxxx", "xxxxx"]
    base = _score(rows, [0, 1, 2])
    exact = _score(rows, [0, 1, 2], stickers=[("axe", 1)], extras={"item_states": json.dumps(states)})
    assert exact == base * 250 // 100


# ---------------------------------------------------------------- search


def _search(rows, words, loadout=None, colors=None) -> ExactSearch:
    board = _board(rows, colors)
    plan = EnginePlan.build(board, loadout or Loadout())
    return ExactSearch(plan, CsrTrie.from_words(words))


def test_exact_search_finds_best_adjacent_word() -> None:
    rows = ["catxx", "xxxxx", "xxxxx", "xxxxx", "xxxxq"]
    xs = _search(rows, {"cat", "at", "act"})
    best = xs.run(top_n=1)[0]
    assert best.word == "cat"
    assert best.path == (0, 1, 2)


def test_exact_search_rejects_non_adjacent_paths() -> None:
    rows = ["cxxxx", "xxxxx", "xxaxx", "xxxxx", "xxxxt"]
    assert _search(rows, {"cat"}).run(top_n=0) == []


def test_number_tile_is_wildcard_only_at_its_position() -> None:
    # "1" is a wildcard as the first tile, "2" as the second (IsNumericWildcard).
    rows = ["12txx", "xxxxx", "xxxxx", "xxxxx", "xxxxx"]
    found = {(c.word, c.path) for c in _search(rows, {"cat", "at"}).run(top_n=0)}
    assert ("cat", (0, 1, 2)) in found
    assert ("at", (0, 1)) in found  # "1" at index 0, "2" at index 1
    assert ("at", (1, 2)) not in found  # "2" at index 0 is not a wildcard


def test_white_tile_portals_anywhere() -> None:
    rows = ["caxxx", "xxxxx", "xxxxx", "xxxxx", "xxxxt"]
    colors = {(0, 1): TileColor.WHITE}
    found = {c.path for c in _search(rows, {"cat"}, colors=colors).run(top_n=0)}
    assert (0, 1, 24) in found


def test_number_go_up_requires_whole_path_ascending() -> None:
    # Number Go Up: numbers are wildcards only when every number on the path ascends.
    rows = ["123xx", "xx5xx", "xxxxx", "xxxxx", "xxxxx"]
    loadout = Loadout(stamps=[LoadoutItem("number_go_up", "Number Go Up", 1, "stamp")])
    xs = _search(rows, {"cat", "cats"}, loadout=loadout)
    found = {c.path for c in xs.run(top_n=0)}
    assert (0, 1, 2) in found  # 1, 2, 3 ascend -> "cat"
    assert (1, 2, 7) in found  # 2, 3, 5 ascend too
    assert xs.valid_word((0, 1, 2, 7)) == "cats"  # 1, 2, 3, 5 ascend
    assert xs.valid_word((0, 1, 7, 2)) is None  # 1, 2, 5, 3 does not ascend


_SPLIT_ROWS = ["catsx", "atexx", "stack", "xtacs", "acats"]
_SPLIT_WORDS = {"cat", "cats", "act", "acts", "tea", "teas", "sat", "eat", "eats", "stack", "tacks", "at", "as"}


def test_start_tile_split_covers_the_same_paths() -> None:
    # Parallel workers run one start tile each; together they must equal the full search.
    full = {(c.path, c.word) for c in _search(_SPLIT_ROWS, _SPLIT_WORDS).run(top_n=0)}
    xs = _search(_SPLIT_ROWS, _SPLIT_WORDS)
    split: set = set()
    for start in xs._available_allowed:
        part = {(c.path, c.word) for c in _search(_SPLIT_ROWS, _SPLIT_WORDS).run(top_n=0, starts=[start])}
        assert all(p[0] == start for p, _ in part)
        split |= part
    assert full and split == full


def test_letter_dfs_overflow_keeps_exhaustive_result_via_subset_tier() -> None:
    full = {c.path for c in _search(_SPLIT_ROWS, _SPLIT_WORDS).run(top_n=0)}
    xs = _search(_SPLIT_ROWS, _SPLIT_WORDS)
    xs.exhaustive_node_budget = xs.min_start_node_budget = 1  # every start overflows the letter DFS
    got = {c.path for c in xs.run(top_n=0, deadline=time.perf_counter() + 30)}
    assert xs.stats.extra.get("exhaustive") is True
    assert xs.stats.extra.get("tier") == "subset"
    assert got == full


def test_expired_deadline_returns_partial_not_crash() -> None:
    xs = _search(_SPLIT_ROWS, _SPLIT_WORDS)
    xs.run(top_n=0, deadline=time.perf_counter() - 1)
    assert xs.stats.extra.get("exhaustive") is False


def test_parallel_exact_search_matches_serial(tmp_path, monkeypatch) -> None:
    from concurrent.futures import ThreadPoolExecutor

    from cursed_words_solver import search_parallel
    from cursed_words_solver.dictionary import WordDictionary
    from cursed_words_solver.engine.solver import ParallelSpec, exact_find_best_words
    from cursed_words_solver.rules.quest_scoring import search_rank_for_quest

    wordlist = tmp_path / "words.txt"
    wordlist.write_text("\n".join(sorted(_SPLIT_WORDS)), encoding="utf-8")
    dictionary = WordDictionary(wordlist)
    monkeypatch.setattr(search_parallel, "_mp_dictionary", dictionary)
    board, loadout = _board(_SPLIT_ROWS), Loadout()

    def rank(s):
        return search_rank_for_quest(float(s), loadout)

    serial, _ = exact_find_best_words(dictionary, board, loadout, top_n=5, min_len=2, rank=rank)
    # One thread stands in for the process pool (tasks never overlap on the worker cache).
    with ThreadPoolExecutor(max_workers=1) as pool:
        par, info = exact_find_best_words(
            dictionary, board, loadout, top_n=5, min_len=2, rank=rank,
            deadline=time.perf_counter() + 30, parallel=ParallelSpec(pool, 4),
        )
    assert info.get("parallel_workers") == 4 and info.get("exhaustive") is True
    # Equal scores may come back in either order.
    assert [r.score for r in par] == [r.score for r in serial]
    assert sorted((r.score, r.word) for r in par) == sorted((r.score, r.word) for r in serial)


def test_numpy_trie_views_not_shared_between_tries() -> None:
    # Regression: views were cached by id(trie); a new trie reusing a freed trie's id
    # got its arrays, so the subset tier found nothing yet reported exhaustive.
    from cursed_words_solver.engine.search import _numpy_trie

    other = CsrTrie.from_words({"zzz"})
    _numpy_trie(other)
    xs = _search(_SPLIT_ROWS, _SPLIT_WORDS)
    assert _numpy_trie(xs.trie) is not _numpy_trie(other)
    assert len(_numpy_trie(xs.trie)[0]) == xs.trie.node_count
