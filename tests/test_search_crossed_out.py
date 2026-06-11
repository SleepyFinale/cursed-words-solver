"""Search must not use crossed-out tiles (SupplyAndDemand / On Cooldown)."""

from __future__ import annotations

from cursed_words_solver.config import resolve_wordlist
from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
from cursed_words_solver.search import WordSearcher
from cursed_words_solver.suggestion import f8_should_block_save


def _user_board_data() -> dict:
    spec: dict[tuple[int, int], tuple] = {
        (0, 0): ("R", "letter"),
        (0, 1): ("U", "letter"),
        (0, 2): ("E", "letter"),
        (0, 3): ("R", "letter"),
        (0, 4): ("F", "letter"),
        (1, 0): ("R", "letter"),
        (1, 1): ("?", "wildcard", True, True),
        (1, 2): ("I", "letter"),
        (1, 3): ("M", "letter"),
        (1, 4): ("L", "letter"),
        (2, 0): ("T", "letter"),
        (2, 1): ("M", "letter"),
        (2, 2): ("E", "letter"),
        (2, 3): ("E", "letter"),
        (2, 4): ("L", "letter"),
        (3, 0): ("?", "wildcard", True, True),
        (3, 1): ("F", "letter"),
        (3, 2): ("I", "letter"),
        (3, 3): ("A", "letter"),
        (3, 4): ("E", "letter"),
        (4, 0): ("O", "letter"),
        (4, 1): ("L", "letter"),
        (4, 2): ("R", "letter"),
        (4, 3): ("T", "letter"),
        (4, 4): ("T", "letter"),
    }
    tiles = []
    for r in range(5):
        for c in range(5):
            entry = {
                "row": r,
                "col": c,
                "char": "x",
                "letter": "X",
                "base_score": 1.0,
                "color": "colorless",
                "curse": "letter",
                "active": True,
                "is_crossed_out": False,
                "is_joker": False,
            }
            if (r, c) in spec:
                v = spec[(r, c)]
                entry["letter"] = v[0]
                entry["char"] = v[0].lower() if v[0] != "?" else "?"
                entry["curse"] = v[1]
                if len(v) > 2 and v[2]:
                    entry["is_joker"] = True
                if len(v) > 3 and v[3]:
                    entry["is_crossed_out"] = True
            tiles.append(entry)
    return {
        "character": "Bones The Dog",
        "money": 2,
        "challenge_game_class": "SupplyAndDemand",
        "stickers": [{"id": "joker", "name": "Joker", "level": 2}],
        "stamps": [],
        "extras": {
            "challenge_game_class": "SupplyAndDemand",
            "grid_number": "2",
            "scoring_previous_words_count": "2",
            "board_from_melmod": "true",
        },
        "board": {
            "rows": 5,
            "cols": 5,
            "row_order": "top_first",
            "tiles": tiles,
        },
    }


def test_find_best_words_skips_crossed_out_jokers() -> None:
    data = _user_board_data()
    board = parse_board_from_run_state(data)
    loadout = parse_run_state(data)
    assert board is not None
    dictionary = WordDictionary(resolve_wordlist("game"))
    searcher = WordSearcher(dictionary=dictionary, min_len=1, time_budget=8, search_workers=1)
    results = searcher.find_best_words(board, loadout=loadout, top_n=5)
    blocked = {6, 15}
    for result in results:
        assert not blocked.intersection(result.path), (
            f"{result.word} uses crossed-out joker path {result.path}"
        )


def test_accept_path_bypass_rejects_crossed_out_wildcard() -> None:
    data = _user_board_data()
    board = parse_board_from_run_state(data)
    loadout = parse_run_state(data)
    assert board is not None
    dictionary = WordDictionary(resolve_wordlist("game"))
    searcher = WordSearcher(dictionary=dictionary, min_len=1)
    searcher.validator.quest_loadout = loadout
    path = [6, 0, 5, 22, 21, 15]
    accepted, _ = searcher._accept_path_for_search(
        board,
        path,
        "grrrls",
        loadout,
        0,
        trie_compatible=True,
        prefix_cursor=dictionary.step_token_cursor(
            dictionary.root_cursor(), "grrrls"
        ),
    )
    assert not accepted


def test_f8_should_block_save_when_path_uses_crossed_out() -> None:
    data = _user_board_data()
    board = parse_board_from_run_state(data)
    blocked, reason = f8_should_block_save(
        gather_succeeded=True,
        board=board,
        path=[6, 0, 5, 22, 21, 15],
    )
    assert blocked
    assert reason == "crossed_out_tile_in_path"
