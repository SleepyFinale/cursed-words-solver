from pathlib import Path

import pytest

from cursed_words_solver.config import GAME_WORDLIST_PATH
from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.models import Board, CurseType, Loadout, LoadoutItem, Tile, TileColor
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.stamp_behaviors import stamp_search_flags
from tests.helpers.boards import (
    _board_123ifer_fixture,
    _board_1_fraction_245fe_fixture,
    _board_boo4_fixture,
    _board_cat_horizontal,
    _board_fu34s6s_fixture,
    _board_hit_shiny_h_fixture,
    _board_1r3vo_fixture,
    _board_tobiano_fixture,
    _board_v2o4_fixture,
    _board_wildcard_quill_fixture,
    _make_wordlist,
    _wildcard_quill_wordlist,
)

from cursed_words_solver.search import PathValidator, WordSearcher, neighbors_from_tile


def test_finds_cat(tmp_path):
    wl = _make_wordlist(tmp_path)
    d = WordDictionary(wl)
    searcher = WordSearcher(dictionary=d, min_len=3, max_len=8, time_budget=5.0)
    board = _board_cat_horizontal()
    results = searcher.find_best_words(board, top_n=1)
    assert results
    assert results[0].word == "cat"


def test_finds_hit_at_max_len_15_despite_shiny_h_dfs_order():
    """Regression: single max_len=15 pass must not miss hit behind H→M deep branch."""
    from cursed_words_solver.config import GAME_WORDLIST_PATH

    if not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024:
        pytest.skip("game wordlist required")

    d = WordDictionary(GAME_WORDLIST_PATH)
    board = _board_hit_shiny_h_fixture()
    loadout = Loadout()
    searcher = WordSearcher(dictionary=d, min_len=3, max_len=15, time_budget=15.0)
    results = searcher.find_best_words(board, loadout, top_n=100)
    hit = next((r for r in results if r.word == "hit"), None)
    assert hit is not None
    assert hit.path == [7, 8, 9]
    expected = ScoringPipeline().score_total_only(board, [7, 8, 9], "hit", loadout)
    assert hit.score == expected == 52.0


def test_finds_wildcard_start_word_quill_over_ulv(tmp_path):
    """Regression: words using wildcard tiles (e.g. ?u?ll / skull) must not be skipped."""
    wl = _wildcard_quill_wordlist(tmp_path)
    d = WordDictionary(wl)
    board = _board_wildcard_quill_fixture()
    searcher = WordSearcher(dictionary=d, min_len=3, max_len=5, time_budget=5.0)
    results = searcher.find_best_words(board, top_n=5)
    assert results
    # Best path must use a board wildcard (indices 8 or 11).
    assert any(i in {8, 11} for i in results[0].path)
    assert len(results[0].path) >= 4
    pipeline = ScoringPipeline()
    ulv_score = pipeline.score_total_only(board, [18, 13, 14, 8], "ulv?", Loadout())
    assert results[0].score > ulv_score
    # And a wildcard-start candidate should appear in the top set when present.
    wildcard_starts = [r for r in results if r.path and r.path[0] in {8, 11}]
    assert wildcard_starts or results[0].word in ("?u?ll", "quill", "skull", "dull", "null")


def test_finds_boo4_number_word(tmp_path):
    wl = _make_wordlist(tmp_path)
    d = WordDictionary(wl)
    searcher = WordSearcher(dictionary=d, min_len=3, max_len=4, time_budget=5.0)
    board = _board_boo4_fixture()
    results = searcher.find_best_words(board, top_n=50)
    words = [r.word for r in results]
    assert "boo4" in words


def test_v2o4_path_accepted(tmp_path):
    from cursed_words_solver.config import GAME_WORDLIST_PATH

    if not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024:
        return

    d = WordDictionary(GAME_WORDLIST_PATH)
    v = PathValidator(d, min_len=3)
    board = _board_v2o4_fixture()
    assert v.word_ok(board, [17, 22, 18, 19], "v2o4")


def test_finds_1r3vo_number_word(tmp_path):
    from cursed_words_solver.config import GAME_WORDLIST_PATH

    if GAME_WORDLIST_PATH.exists() and GAME_WORDLIST_PATH.stat().st_size >= 1024:
        d = WordDictionary(GAME_WORDLIST_PATH)
    else:
        d = WordDictionary(_make_wordlist(tmp_path))
    searcher = WordSearcher(dictionary=d, min_len=3, max_len=5, time_budget=5.0)
    board = _board_1r3vo_fixture()
    results = searcher.find_best_words(board, top_n=20)
    words = [r.word for r in results]
    assert "1r3vo" in words


def test_12ttee_shiny_e_full_moon_scores_456(tmp_path):
    """Regression: Flamingo + Full Moon must allow shiny E ending (not only blue E)."""
    import json

    from cursed_words_solver.config import GAME_WORDLIST_PATH
    from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
    from cursed_words_solver.rules.pipeline import ScoringPipeline
    from cursed_words_solver.rules.stamp_behaviors import stamp_search_flags

    if not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024:
        pytest.skip("game wordlist required")

    fixture = Path(__file__).resolve().parent / "fixtures" / "12ttee_run_state.json"
    if not fixture.exists():
        pytest.skip("12ttee_run_state.json fixture required")

    data = json.loads(fixture.read_text(encoding="utf-8"))
    board = parse_board_from_run_state(data)
    loadout = parse_run_state(data)
    flags = stamp_search_flags(loadout)
    shiny_path = [5, 11, 7, 21, 17, 0]
    blue_path = [5, 11, 7, 21, 17, 9]
    pipeline = ScoringPipeline()
    shiny_score, _ = pipeline.score(board, shiny_path, "12ttee", loadout)
    blue_score, _ = pipeline.score(board, blue_path, "12ttee", loadout)
    assert shiny_score == 456
    assert blue_score == 308

    d = WordDictionary(GAME_WORDLIST_PATH)
    validator = PathValidator(d, min_len=3)
    assert validator.word_ok(board, shiny_path, "12ttee", flags)
    assert validator.word_ok(board, blue_path, "12ttee", flags)
    prefix = shiny_path[:-1]
    visited = sum(1 << i for i in prefix)
    nbrs = neighbors_from_tile(board, prefix, visited, flags=flags)
    assert 0 in nbrs
    assert shiny_score > blue_score


def test_finds_tobiano_beats_12bier_with_flamingo(tmp_path):
    import json

    from cursed_words_solver.config import GAME_WORDLIST_PATH
    from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state

    if not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024:
        pytest.skip("game wordlist required")

    fixture = Path(__file__).resolve().parent / "fixtures" / "tobiano_run_state.json"
    if fixture.exists():
        data = json.loads(fixture.read_text(encoding="utf-8"))
        board = parse_board_from_run_state(data)
        loadout = parse_run_state(data)
    else:
        board = _board_tobiano_fixture()
        loadout = Loadout(
            stamps=[LoadoutItem(id="flamingo", name="Flamingo", kind="stamp")]
        )

    d = WordDictionary(GAME_WORDLIST_PATH)
    searcher = WordSearcher(dictionary=d, min_len=3, max_len=15, time_budget=30.0)
    results = searcher.find_best_words(board, loadout, top_n=20)
    words = {r.word: r.score for r in results}

    if fixture.exists():
        assert results[0].score > 400
        assert results[0].score > words.get("12bier", 0)
    else:
        assert words.get("12bi56o", 0) > words.get("12bier", 0)


def test_echappe_not_found_with_opposite_color_knight_full_moon():
    """Regression: Full Moon must not chain black/white knights (echappe via invalid teleports)."""
    import json

    from cursed_words_solver.config import GAME_WORDLIST_PATH
    from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state

    if not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024:
        pytest.skip("game wordlist required")

    fixture = (
        Path(__file__).resolve().parent / "fixtures" / "echappe_full_moon_chess.json"
    )
    if not fixture.exists():
        pytest.skip("echappe_full_moon_chess.json fixture required")

    data = json.loads(fixture.read_text(encoding="utf-8"))
    board = parse_board_from_run_state(data)
    loadout = parse_run_state(data)
    d = WordDictionary(GAME_WORDLIST_PATH)
    searcher = WordSearcher(dictionary=d, min_len=3, max_len=15, time_budget=15.0)
    results = searcher.find_best_words(board, loadout, top_n=50)
    words = [r.word for r in results]
    assert "echappe" not in words

    flags = stamp_search_flags(loadout)
    # Full Moon must not link white (4,2) knight to black (1,4) or chain through it.
    nbrs_from_knight = neighbors_from_tile(board, [17, 22], {17, 22}, flags=flags)
    assert 9 not in nbrs_from_knight  # black knight at (1,4); no Full Moon from white (4,2)


def test_red_sticker_bonus(tmp_path):
    wl = _make_wordlist(tmp_path)
    board = _board_cat_horizontal()
    board.tiles[0][0].color = TileColor.RED
    loadout = Loadout(
        stickers=[
            LoadoutItem(id="red_rider", name="Red Rider", level=1, kind="sticker")
        ]
    )
    pipeline = ScoringPipeline()
    score, _ = pipeline.score(board, [0, 1, 2], "cat", loadout)
    assert score > 3


@pytest.mark.skipif(
    not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024,
    reason="game wordlist required",
)
def test_twigloo_extension_beats_short_chess_path():
    """Regression: trailing capture+letter extension must beat 7-tile twigloo (1600 pts)."""
    import json

    from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state

    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "mismatches"
        / "20260524_twigloo_extension.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    run_state = data["run_state_snapshot"]
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    assert board is not None

    short_path = data["short_path"]
    pipeline = ScoringPipeline()
    short_score = pipeline.score_total_only(
        board, short_path, data["short_word"], loadout
    )

    searcher = WordSearcher(
        dictionary=WordDictionary(GAME_WORDLIST_PATH),
        min_len=7,
        max_len=15,
        time_budget=15.0,
    )
    results = searcher.find_best_words(board, loadout, top_n=5)
    assert results
    assert results[0].score > short_score
    assert results[0].score >= 1900.0
    assert len(results[0].path) > len(short_path)


@pytest.mark.skipif(
    not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024,
    reason="game wordlist required",
)
def test_find_best_words_fjelds_beats_aahed():
    """Integration: post-refine extension picks 6-tile fjelds over 5-tile aahed."""
    import json

    from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state

    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "mismatches"
        / "20260615_184801_fjelds.json"
    )
    if not fixture.exists():
        pytest.skip("20260615_184801_fjelds.json fixture required")
    data = json.loads(fixture.read_text(encoding="utf-8"))
    board = parse_board_from_run_state(data["run_state_snapshot"])
    loadout = parse_run_state(data["run_state_snapshot"])
    assert board is not None

    pipeline = ScoringPipeline()
    short_score = pipeline.score_total_only(
        board, data["short_path"], data["short_word"], loadout
    )

    searcher = WordSearcher(
        dictionary=WordDictionary(GAME_WORDLIST_PATH),
        min_len=3,
        max_len=15,
        time_budget=20.0,
    )
    results = searcher.find_best_words(board, loadout, top_n=5)
    assert results
    assert results[0].path == data["expected_path"]
    assert results[0].score > short_score
    assert results[0].score >= data["expected_score"] - 20


@pytest.mark.skipif(
    not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024,
    reason="game wordlist required",
)
def test_find_best_words_buzzsaw_beats_bazz(_parallel_pool_cleanup):
    """Integration: find_best_words reaches buzzsaw on fraction/chess board."""
    import json

    from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state

    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "mismatches"
        / "20260618_120547_snazzier.json"
    )
    if not fixture.exists():
        pytest.skip("20260618_120547_snazzier.json fixture required")
    data = json.loads(fixture.read_text(encoding="utf-8"))
    board = parse_board_from_run_state(data["run_state_snapshot"])
    loadout = parse_run_state(data["run_state_snapshot"])
    assert board is not None

    pipeline = ScoringPipeline()
    short_score = pipeline.score_total_only(
        board, data["short_path"], data["short_word"], loadout
    )
    expected_score = pipeline.score_total_only(
        board, data["expected_path"], data["expected_word"], loadout
    )

    searcher = WordSearcher(
        dictionary=WordDictionary(GAME_WORDLIST_PATH),
        min_len=3,
        max_len=25,
        time_budget=60.0,
        search_workers=8,
    )
    results = searcher.find_best_words(board, loadout, top_n=10)
    assert results
    from cursed_words_solver.suggestion import game_word_for_path

    actual_scores: list[int] = []
    dictionary = WordDictionary(GAME_WORDLIST_PATH)
    for r in results:
        gw = game_word_for_path(board, r.path, r.word, loadout, dictionary)
        actual_scores.append(
            int(pipeline.score_total_only(board, r.path, gw, loadout))
        )
    best_actual = max(actual_scores)
    assert best_actual > short_score
    assert best_actual >= expected_score - 5


def _tile(
    ch: str,
    row: int,
    col: int,
    *,
    was_consumable: bool = False,
) -> Tile:
    meta: dict = {}
    if was_consumable:
        meta["was_consumable"] = True
    return Tile(
        row=row,
        col=col,
        char=ch,
        letter=ch,
        base_score=1,
        color=TileColor.COLORLESS,
        curse=CurseType.LETTER,
        metadata=meta,
    )


def test_was_consumable_does_not_block_without_mandatory_indices(tmp_path):
    wl = tmp_path / "words.txt"
    wl.write_text("cat\n", encoding="utf-8")
    d = WordDictionary(wl)
    v = PathValidator(d, min_len=3)

    tiles = [[_tile("x", r, c) for c in range(5)] for r in range(5)]
    tiles[0][0] = _tile("c", 0, 0)
    tiles[0][1] = _tile("a", 0, 1)
    tiles[0][2] = _tile("t", 0, 2)
    tiles[1][2] = _tile("s", 1, 2, was_consumable=True)
    board = Board(tiles=tiles)

    assert v.word_ok(board, [0, 1, 2], "cat")


def test_path_must_include_placed_consumable_when_required(tmp_path):
    wl = tmp_path / "words.txt"
    wl.write_text("cat\ncast\n", encoding="utf-8")
    d = WordDictionary(wl)
    v = PathValidator(d, min_len=3)
    v.required_consumable_indices = frozenset({7})

    tiles = [[_tile("x", r, c) for c in range(5)] for r in range(5)]
    tiles[0][0] = _tile("c", 0, 0)
    tiles[0][1] = _tile("a", 0, 1)
    tiles[0][2] = _tile("t", 0, 2)
    tiles[1][2] = _tile("s", 1, 2, was_consumable=True)
    board = Board(tiles=tiles)

    assert not v.word_ok(board, [0, 1, 2], "cat")
    assert v.word_ok(board, [0, 1, 7, 2], "cast")


def test_path_must_include_all_required_consumables(tmp_path):
    wl = tmp_path / "words.txt"
    wl.write_text("cats\n", encoding="utf-8")
    d = WordDictionary(wl)
    v = PathValidator(d, min_len=3)
    v.required_consumable_indices = frozenset({2, 7})

    tiles = [[_tile("x", r, c) for c in range(5)] for r in range(5)]
    tiles[0][0] = _tile("c", 0, 0)
    tiles[0][1] = _tile("a", 0, 1)
    tiles[0][2] = _tile("t", 0, 2, was_consumable=True)
    tiles[1][2] = _tile("s", 1, 2, was_consumable=True)
    board = Board(tiles=tiles)

    assert not v.word_ok(board, [0, 1, 2], "cat")
    assert v.word_ok(board, [0, 1, 2, 7], "cats")


def test_searcher_skips_words_missing_required_consumables(tmp_path):
    wl = tmp_path / "words.txt"
    wl.write_text("cat\ncats\n", encoding="utf-8")
    d = WordDictionary(wl)
    tiles = [[_tile("x", r, c) for c in range(5)] for r in range(5)]
    tiles[0][0] = _tile("c", 0, 0)
    tiles[0][1] = _tile("a", 0, 1)
    tiles[0][2] = _tile("t", 0, 2, was_consumable=True)
    tiles[1][2] = _tile("s", 1, 2, was_consumable=True)
    board = Board(tiles=tiles)

    searcher = WordSearcher(dictionary=d, min_len=3, max_len=5, time_budget=3.0)
    searcher.validator.required_consumable_indices = frozenset({2, 7})
    results = searcher.find_best_words(board, top_n=10)
    words = [r.word for r in results]
    assert "cat" not in words
    assert "cats" in words


NAT_H4_RUN_STATE = Path.home() / ".cursed_words_solver" / "run_state.json"
INVALID_EPIDERMIC_PATH = [9, 4, 3, 8, 20, 2, 1, 15, 16]


def _nat_h4_board_and_loadout():
    if not NAT_H4_RUN_STATE.is_file():
        pytest.skip("Nat-H4 run_state.json required (~/.cursed_words_solver/run_state.json)")
    from cursed_words_solver.loadout import (
        load_run_state_raw,
        parse_board_from_run_state,
        parse_run_state,
    )

    data = load_run_state_raw(NAT_H4_RUN_STATE)
    if data.get("character") != "Nat-H4" or data.get("boss_id") != "salamander":
        pytest.skip("run_state is not Nat-H4 salamander board")
    loadout = parse_run_state(data)
    board = parse_board_from_run_state(data)
    assert board is not None
    return board, loadout


def test_path_movement_ok_rejects_epidermic_invalid_step():
    """Regression: step 4→5 (index 8→20) is not a legal neighbor move."""
    from cursed_words_solver.rules.stamp_behaviors import stamp_search_flags_mask
    from cursed_words_solver.search import path_movement_ok

    board, loadout = _nat_h4_board_and_loadout()
    flags = stamp_search_flags_mask(loadout)
    assert not path_movement_ok(board, INVALID_EPIDERMIC_PATH, flags=flags)
    assert path_movement_ok(board, [9, 4, 3, 8], flags=flags)


@pytest.fixture
def _parallel_pool_cleanup():
    from cursed_words_solver.search_parallel import shutdown_search_pool

    shutdown_search_pool(wait=True)
    yield
    shutdown_search_pool(wait=True)


def test_nat_h4_find_best_words_all_paths_movement_valid(_parallel_pool_cleanup):
    """Regression: parallel search must not suggest paths with illegal step 4→5."""
    from cursed_words_solver.rules.stamp_behaviors import stamp_search_flags_mask
    from cursed_words_solver.search import path_movement_ok

    if not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024:
        pytest.skip("game wordlist required")

    board, loadout = _nat_h4_board_and_loadout()
    flags = stamp_search_flags_mask(loadout)
    d = WordDictionary(GAME_WORDLIST_PATH)
    searcher = WordSearcher(
        dictionary=d,
        min_len=3,
        max_len=25,
        time_budget=15.0,
        search_workers=8,
    )
    results = searcher.find_best_words(board, loadout, top_n=10)
    assert results
    for result in results:
        assert path_movement_ok(
            board, list(result.path), flags=flags
        ), f"{result.word} path={result.path}"
    assert not any(list(r.path) == INVALID_EPIDERMIC_PATH for r in results)


def _f8_board_loadout_from_round_log(fixture_name: str):
    """Load F8-time board/loadout from a round-log fixture."""
    import copy
    import json

    from cursed_words_solver.loadout import (
        parse_board_from_run_state,
        parse_run_state,
        prepare_run_state_dict_for_scoring,
    )

    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "round_logs"
        / fixture_name
    )
    if not fixture.exists():
        pytest.skip(f"{fixture_name} fixture required")
    data = json.loads(fixture.read_text(encoding="utf-8"))
    rs = copy.deepcopy(data["run_state"])
    ex = rs.setdefault("extras", {})
    diff = data.get("extras_diff") or {}
    ex["scoring_previous_words_count"] = diff.get(
        "scoring_previous_words_count", {}
    ).get("f8", "0")
    if "historic_words" in diff:
        ex["historic_words"] = diff["historic_words"].get("f8", "[]")
    ex["grid_scattered_items"] = diff.get("grid_scattered_items", {}).get("f8", "")
    ex["red_tiles_used_encounter"] = diff.get("red_tiles_used_encounter", {}).get(
        "f8", "0"
    )
    for key, entry in diff.items():
        if isinstance(entry, dict) and "f8" in entry and entry["f8"] not in (None, ""):
            ex[key] = entry["f8"]
    run_state = prepare_run_state_dict_for_scoring(rs)
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    assert board is not None and loadout is not None
    return data, board, loadout


def _melmod_paths(board, data: dict) -> tuple[list[int], list[int]]:
    from cursed_words_solver.ui.board_geometry import path_from_melmod_indices

    solver = data["solver"]
    actual = data["actual"]
    short_path = path_from_melmod_indices(board, solver["path"])
    expected_path = path_from_melmod_indices(board, actual["path"])
    return short_path, expected_path
