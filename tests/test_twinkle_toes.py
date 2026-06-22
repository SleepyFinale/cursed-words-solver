import time

import pytest

from cursed_words_solver.consumable_placement import (
    apply_consumable_placements,
    search_consumable_score_boost,
)
from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.models import Board, CurseType, Loadout, LoadoutItem, Tile, TileColor
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.search import WordSearcher, physical_word_for_path
from cursed_words_solver.rules.twinkle_toes import (
    format_swap_instructions,
    iter_swap_pairs,
    search_with_twinkle_toes_swap,
    swap_tile_contents,
    swap_to_record,
    twinkle_swap_eligible_indices,
    twinkle_toes_swap_pending,
)
from tests.test_consumable_placement import _mahjong_loadout_with_red_rack
from tests.test_search import _tile


def _full_board(tiles_by_rc: dict[tuple[int, int], Tile]) -> Board:
    tiles = [[_tile(".", r, c) for c in range(5)] for r in range(5)]
    for (row, col), tile in tiles_by_rc.items():
        tiles[row][col] = tile
    return Board(tiles=tiles)


def _letter_tile(ch: str, row: int, col: int, *, color=TileColor.COLORLESS, score: float = 1) -> Tile:
    return Tile(
        row=row,
        col=col,
        char=ch,
        letter=ch,
        base_score=score,
        color=color,
        curse=CurseType.LETTER,
    )


def test_swap_tile_contents_preserves_coordinates_and_swaps_fields():
    board = _full_board(
        {
            (0, 0): _letter_tile("a", 0, 0, color=TileColor.RED, score=3),
            (2, 3): _letter_tile("z", 2, 3, color=TileColor.BLUE, score=7),
        }
    )
    out = swap_tile_contents(board, 0, 13)
    a = out.tiles[0][0]
    z = out.tiles[2][3]
    assert (a.row, a.col) == (0, 0)
    assert (z.row, z.col) == (2, 3)
    assert a.letter == "z"
    assert z.letter == "a"
    assert a.color == TileColor.BLUE
    assert z.color == TileColor.RED
    assert a.base_score == 7
    assert z.base_score == 3


def test_swap_tile_contents_swaps_metadata():
    board = _full_board(
        {
            (1, 1): Tile(
                row=1,
                col=1,
                char="?",
                letter="?",
                base_score=4,
                color=TileColor.SHINY,
                curse=CurseType.CHESS_ROOK,
                metadata={"card_suit": "hearts", "chess_color": "white"},
            ),
            (3, 4): Tile(
                row=3,
                col=4,
                char="k",
                letter="k",
                base_score=2,
                color=TileColor.COLORLESS,
                curse=CurseType.LETTER,
                metadata={"scattered_item_id": "lucky_dice"},
            ),
        }
    )
    out = swap_tile_contents(board, 1 * 5 + 1, 3 * 5 + 4)
    t_a = out.tiles[1][1]
    t_b = out.tiles[3][4]
    assert t_a.metadata.get("scattered_item_id") == "lucky_dice"
    assert t_b.metadata.get("card_suit") == "hearts"
    assert t_a.curse == CurseType.LETTER
    assert t_b.curse == CurseType.CHESS_ROOK


def test_double_swap_restores_board():
    board = _full_board({(0, 1): _letter_tile("m", 0, 1), (4, 2): _letter_tile("x", 4, 2)})
    once = swap_tile_contents(board, 1, 22)
    twice = swap_tile_contents(once, 1, 22)
    assert twice.tiles[0][1].letter == "m"
    assert twice.tiles[4][2].letter == "x"


def test_twinkle_swap_eligible_indices_excludes_inactive_and_crossed_out():
    tiles = [[_tile(".", r, c) for c in range(5)] for r in range(5)]
    tiles[0][0] = _letter_tile("a", 0, 0)
    tiles[0][1] = _letter_tile("b", 0, 1)
    crossed = _letter_tile("c", 0, 2)
    crossed.metadata["is_crossed_out"] = True
    tiles[0][2] = crossed
    active = [False] * 25
    active[0] = True
    active[1] = True
    board = Board(tiles=tiles, active=active)
    eligible = twinkle_swap_eligible_indices(board)
    assert eligible == [0, 1]
    assert len(list(iter_swap_pairs(board))) == 1


def test_twinkle_toes_swap_pending():
    loadout = Loadout(
        stamps=[LoadoutItem(id="twinkle_toes", name="Twinkle Toes", kind="stamp")],
        extras={"twinkle_toes_swap_available": "true"},
    )
    assert twinkle_toes_swap_pending(loadout)
    loadout.extras["twinkle_toes_swap_available"] = "false"
    assert not twinkle_toes_swap_pending(loadout)
    loadout.extras.pop("twinkle_toes_swap_available")
    assert not twinkle_toes_swap_pending(loadout)


def test_format_swap_instructions():
    swap = swap_to_record(20, 13)
    assert format_swap_instructions(swap) == "Twinkle Toes: swap (4,0) \u2194 (2,3)"


def test_swap_unlocks_better_word(tmp_path):
    wl = tmp_path / "words.txt"
    wl.write_text("cat\n", encoding="utf-8")
    d = WordDictionary(wl)
    tiles = [[_tile(".", r, c) for c in range(5)] for r in range(5)]
    tiles[0][0] = _letter_tile("c", 0, 0)
    tiles[0][1] = _letter_tile("t", 0, 1)
    tiles[0][2] = _letter_tile("a", 0, 2)
    active = [False] * 25
    for idx in (0, 1, 2):
        active[idx] = True
    board = Board(tiles=tiles, active=active)
    loadout = Loadout(
        stamps=[LoadoutItem(id="twinkle_toes", name="Twinkle Toes", kind="stamp")],
        extras={"twinkle_toes_swap_available": "true"},
    )
    searcher = WordSearcher(dictionary=d, min_len=3, max_len=5, time_budget=3.0)
    swapped_board, swap_record, results = search_with_twinkle_toes_swap(
        searcher,
        board,
        loadout,
        time_budget=3.0,
        top_n=1,
    )
    assert swap_record is not None
    assert results
    assert results[0].word == "cat"
    assert swapped_board.tiles[0][0].letter == "c"
    assert swapped_board.tiles[0][1].letter == "a"
    assert swapped_board.tiles[0][2].letter == "t"


def test_search_picks_winning_swap_among_pairs(tmp_path):
    wl = tmp_path / "words.txt"
    wl.write_text("cat\ndog\n", encoding="utf-8")
    d = WordDictionary(wl)
    tiles = [[_tile(".", r, c) for c in range(5)] for r in range(5)]
    tiles[0][0] = _letter_tile("c", 0, 0)
    tiles[0][1] = _letter_tile("t", 0, 1)
    tiles[0][2] = _letter_tile("a", 0, 2)
    tiles[1][0] = _letter_tile("d", 1, 0)
    tiles[1][1] = _letter_tile("o", 1, 1)
    tiles[1][2] = _letter_tile("g", 1, 2)
    active = [False] * 25
    for idx in range(6):
        active[idx] = True
    board = Board(tiles=tiles, active=active)
    loadout = Loadout(
        stamps=[LoadoutItem(id="twinkle_toes", name="Twinkle Toes", kind="stamp")],
    )
    searcher = WordSearcher(dictionary=d, min_len=3, max_len=5, time_budget=4.0)
    _board, swap_record, results = search_with_twinkle_toes_swap(
        searcher,
        board,
        loadout,
        time_budget=4.0,
        top_n=1,
    )
    assert results
    assert swap_record is not None
def test_twinkle_toes_screen_uses_meaningful_search_budget(tmp_path):
    """Swap screening must not run 0.25s micro-searches (placement_screen_pass)."""
    wl = tmp_path / "words.txt"
    wl.write_text("cat\ndog\n", encoding="utf-8")
    d = WordDictionary(wl)
    tiles = [[_tile(".", r, c) for c in range(5)] for r in range(5)]
    for idx, ch in enumerate("catdog"):
        row, col = divmod(idx, 3)
        tiles[row][col] = _letter_tile(ch, row, col)
    active = [False] * 25
    for idx in range(6):
        active[idx] = True
    board = Board(tiles=tiles, active=active)
    loadout = Loadout(
        stamps=[LoadoutItem(id="twinkle_toes", name="Twinkle Toes", kind="stamp")],
    )
    searcher = WordSearcher(dictionary=d, min_len=3, max_len=5, time_budget=60.0)
    captured_budgets: list[float] = []
    original_find = searcher.find_best_words

    def _spy_find(*args, **kwargs):
        captured_budgets.append(searcher.time_budget)
        return original_find(*args, **kwargs)

    searcher.find_best_words = _spy_find
    deadline = time.monotonic() + 20.0
    _board, _swap, results = search_with_twinkle_toes_swap(
        searcher,
        board,
        loadout,
        time_budget=20.0,
        top_n=1,
        solve_deadline=deadline,
    )
    assert results
    assert captured_budgets
    assert min(captured_budgets) >= 2.0
    assert getattr(searcher, "_placement_screen_pass", False) is False


def test_twinkle_toes_grid5_nanas_round_log_regression():
    """Regression: grid 5 / cherries board must not return empty after swap screening."""
    import json
    from pathlib import Path

    from cursed_words_solver.config import GAME_WORDLIST_PATH
    from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
    from cursed_words_solver.rules.stamp_behaviors import stamp_search_flags

    if not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024:
        pytest.skip("game wordlist required")

    fixture = Path(__file__).resolve().parent / "fixtures/boards/20260621_grid5_twinkle_nanas.json"
    data = json.loads(fixture.read_text(encoding="utf-8"))
    board = parse_board_from_run_state(data)
    loadout = parse_run_state(data)
    assert board is not None
    loadout.extras["twinkle_toes_swap_available"] = "true"

    nanas_path = [17, 18, 12, 16, 11]
    flags = stamp_search_flags(loadout)
    d = WordDictionary(GAME_WORDLIST_PATH)
    searcher = WordSearcher(
        dictionary=d, min_len=1, max_len=25, time_budget=60.0, search_workers=8
    )
    searcher.scoring = ScoringPipeline()
    searcher.validator.quest_loadout = loadout
    assert searcher.validator.word_ok(board, nanas_path, "nanas", flags)

    deadline = time.monotonic() + 60.0
    swapped_board, swap_record, results = search_with_twinkle_toes_swap(
        searcher,
        board,
        loadout,
        time_budget=60.0,
        top_n=3,
        solve_deadline=deadline,
    )
    assert swap_record is not None
    assert results
    assert results[0].word


def _result_rank_score(result) -> float:
    if result.rank_score > 0:
        return result.rank_score
    return result.score + result.setup_bonus


def test_consumable_boost_after_twinkle_uses_swapped_board(tmp_path):
    """Consumable boost must search on the post-swap board, not the original."""
    wl = tmp_path / "words.txt"
    wl.write_text("cat\n", encoding="utf-8")
    d = WordDictionary(wl)
    tiles = [[_tile(".", r, c) for c in range(5)] for r in range(5)]
    tiles[0][0] = _letter_tile("c", 0, 0)
    tiles[0][1] = _letter_tile("t", 0, 1)
    tiles[0][2] = _letter_tile("a", 0, 2)
    active = [False] * 25
    for idx in (0, 1, 2):
        active[idx] = True
    board = Board(tiles=tiles, active=active)
    loadout = _mahjong_loadout_with_red_rack()
    loadout.stamps = [
        LoadoutItem(id="twinkle_toes", name="Twinkle Toes", kind="stamp"),
    ]
    loadout.extras["twinkle_toes_swap_available"] = "true"
    loadout.extras["consumable_rack"] = [
        {
            "rack_index": 0,
            "letter": "T",
            "color": "red",
            "curse": "letter",
            "base_score": 5,
        },
    ]
    rules = ScoringPipeline().rules
    searcher = WordSearcher(dictionary=d, min_len=3, max_len=5, time_budget=4.0)

    swapped_board, swap_record, twinkle_results = search_with_twinkle_toes_swap(
        searcher,
        board,
        loadout,
        time_budget=4.0,
        top_n=1,
    )
    assert swap_record is not None
    assert twinkle_results
    assert twinkle_results[0].word == "cat"
    baseline_rank = _result_rank_score(twinkle_results[0])

    rack = [
        Tile(
            -1,
            -1,
            "T",
            "T",
            5,
            color=TileColor.RED,
            curse=CurseType.LETTER,
            metadata={"rack_index": 0},
        ),
    ]
    wrong_board, wrong_records, wrong_results = search_consumable_score_boost(
        searcher,
        board,
        loadout,
        rack,
        baseline_score=twinkle_results[0].score,
        baseline_rank_score=baseline_rank,
        time_budget=4.0,
        top_n=1,
        rules=rules,
    )
    right_board, right_records, right_results = search_consumable_score_boost(
        searcher,
        swapped_board,
        loadout,
        rack,
        baseline_score=twinkle_results[0].score,
        baseline_rank_score=baseline_rank,
        time_budget=4.0,
        top_n=1,
        rules=rules,
    )

    search_board = swapped_board
    placement_records = []
    results = twinkle_results
    if right_results and _result_rank_score(right_results[0]) > baseline_rank:
        search_board = right_board
        placement_records = right_records
        results = right_results

    assert results
    assert results[0].word == "cat"
    path_word = physical_word_for_path(search_board, results[0].path)
    assert path_word == "cat"

    if wrong_results and wrong_records:
        user_board = apply_consumable_placements(swapped_board, wrong_records)
        wrong_path_word = physical_word_for_path(user_board, wrong_results[0].path)
        assert wrong_path_word != "cat"


def test_twinkle_swap_time_budget_caps_when_rack_placement_pending():
    from cursed_words_solver.app import RACK_RESERVE_FRAC, twinkle_swap_time_budget

    assert twinkle_swap_time_budget(
        search_budget=60.0,
        rack_placement_pending=True,
        solve_remaining_sec=44.0,
    ) == pytest.approx(60.0 * (1.0 - RACK_RESERVE_FRAC))


def test_twinkle_swap_time_budget_uses_remaining_without_rack():
    from cursed_words_solver.app import twinkle_swap_time_budget

    assert twinkle_swap_time_budget(
        search_budget=60.0,
        rack_placement_pending=False,
        solve_remaining_sec=44.0,
    ) == pytest.approx(44.0)


def test_twinkle_swap_deadline_reserves_rack_budget():
    from cursed_words_solver.app import twinkle_swap_deadline

    started = 1000.0
    solve_deadline = started + 60.0
    twinkle_budget = 29.25
    assert twinkle_swap_deadline(
        search_started=started,
        solve_deadline=solve_deadline,
        twinkle_budget=twinkle_budget,
    ) == pytest.approx(started + twinkle_budget)


def test_twinkle_plus_rack_orchestration_leaves_consumable_boost_time():
    """App solve path must cap Twinkle and leave rack budget for score boost."""
    from cursed_words_solver.app import (
        RACK_RESERVE_FRAC,
        twinkle_swap_deadline,
        twinkle_swap_time_budget,
    )
    from cursed_words_solver.consumable_placement import (
        rack_placement_search_active,
        remaining_rack_tiles,
    )

    search_budget = 60.0
    search_started = time.monotonic()
    solve_deadline = search_started + search_budget

    board = Board(tiles=[[_tile("a", r, c) for c in range(5)] for r in range(5)])
    loadout = _mahjong_loadout_with_red_rack()
    loadout.stamps = [
        LoadoutItem(id="twinkle_toes", name="Twinkle Toes", kind="stamp"),
    ]
    loadout.extras["twinkle_toes_swap_available"] = "true"
    rules = ScoringPipeline().rules

    rack_pending = rack_placement_search_active(loadout, board, rules)
    assert rack_pending
    assert twinkle_toes_swap_pending(loadout)

    twinkle_budget = twinkle_swap_time_budget(
        search_budget=search_budget,
        rack_placement_pending=rack_pending,
        solve_remaining_sec=search_budget,
    )
    twinkle_deadline = twinkle_swap_deadline(
        search_started=search_started,
        solve_deadline=solve_deadline,
        twinkle_budget=twinkle_budget,
    )
    remaining_after_twinkle = solve_deadline - twinkle_deadline
    assert remaining_after_twinkle >= search_budget * RACK_RESERVE_FRAC - 0.01

    # Mirrors app.py consumable boost gate after capped Twinkle search.
    assert remaining_after_twinkle >= 1.0
    assert (
        rack_placement_search_active(loadout, board, rules)
        and remaining_rack_tiles(loadout, board)
    )
