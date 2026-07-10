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

from cursed_words_solver.search import (
    PathValidator,
    WordSearcher,
    _CandidateHeap,
    _balanced_start_indices,
    _wildcard_start_indices,
    neighbors_from_tile,
    neighbors_standard,
    resolve_letter,
)






def test_neighbors_standard():
    board = _board_cat_horizontal()
    nbrs = neighbors_standard(board, [0], {0})
    assert 1 in nbrs
    assert 5 in nbrs  # down-left from (0,0) is (1,0) idx 5


def test_resolve_letter_scattered_item_is_wildcard():
    tile = Tile(
        1,
        1,
        "🥧",
        "Z",
        0.0,
        TileColor.RED,
        CurseType.ITEM,
        metadata={"scattered_item_id": "cherry_pie"},
    )
    assert resolve_letter(tile, 0) == "?"


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






def test_wildcard_starts_ordered_first():
    board = _board_wildcard_quill_fixture()
    wild = set(_wildcard_start_indices(board))
    assert wild == {8, 11}
    starts = _balanced_start_indices(board)
    assert starts[0] in wild
    assert starts[1] in wild


def test_finds_wildcard_start_word_quill_over_ulv(tmp_path):
    """Regression: words starting on wildcard tiles (e.g. ?u?ll) must not be skipped."""
    wl = _wildcard_quill_wordlist(tmp_path)
    d = WordDictionary(wl)
    board = _board_wildcard_quill_fixture()
    searcher = WordSearcher(dictionary=d, min_len=3, max_len=5, time_budget=5.0)
    results = searcher.find_best_words(board, top_n=5)
    assert results
    assert results[0].word == "?u?ll"
    assert results[0].path[0] in {8, 11}
    assert len(results[0].path) == 5
    pipeline = ScoringPipeline()
    ulv_score = pipeline.score_total_only(board, [18, 13, 14, 8], "ulv?", Loadout())
    assert results[0].score > ulv_score






def test_prefix_ok_allows_digit_suffix(tmp_path):
    wl = _make_wordlist(tmp_path)
    d = WordDictionary(wl)
    v = PathValidator(d, min_len=3)
    assert v.prefix_ok("boo4")
    board = _board_boo4_fixture()
    assert v.prefix_ok("boo", board, [11, 12, 13], steps_remaining=1)
    assert v.prefix_ok("bo", board, [11, 12], steps_remaining=2)


def test_finds_boo4_number_word(tmp_path):
    wl = _make_wordlist(tmp_path)
    d = WordDictionary(wl)
    searcher = WordSearcher(dictionary=d, min_len=3, max_len=4, time_budget=5.0)
    board = _board_boo4_fixture()
    results = searcher.find_best_words(board, top_n=50)
    words = [r.word for r in results]
    assert "boo4" in words




def test_number_word_wildcard_validation(tmp_path):
    """Number tiles validate as ? wildcards against the dictionary (wiki rules)."""
    from cursed_words_solver.config import GAME_WORDLIST_PATH

    if not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024:
        return

    d = WordDictionary(GAME_WORDLIST_PATH)
    v = PathValidator(d, min_len=3)
    assert v._wildcard_valid("?r?hv") is False
    assert v._wildcard_valid("?r?vo") is True
    assert v._wildcard_valid("v?o?") is True
    assert v._wildcard_valid("boo?") is True


def test_v2o4_path_accepted(tmp_path):
    from cursed_words_solver.config import GAME_WORDLIST_PATH

    if not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024:
        return

    d = WordDictionary(GAME_WORDLIST_PATH)
    v = PathValidator(d, min_len=3)
    board = _board_v2o4_fixture()
    assert v.word_ok(board, [17, 22, 18, 19], "v2o4")






def test_finds_123ifer_when_search_starts_on_number_tiles(tmp_path):
    """2s budget used to explore A.. before the 1 tile; 123ifer was missed."""
    from cursed_words_solver.config import GAME_WORDLIST_PATH

    if not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024:
        return

    d = WordDictionary(GAME_WORDLIST_PATH)
    board = _board_123ifer_fixture()
    loadout = Loadout(
        stickers=[
            LoadoutItem(id="alembic_flask", name="Alembic Flask", level=1, kind="sticker"),
            LoadoutItem(id="birthday_cake", name="Birthday Cake", level=1, kind="sticker"),
            LoadoutItem(id="brain", name="Brain", level=3, kind="sticker"),
        ],
        extras={"birthday_cake_bonus": "39"},
        money=8,
    )
    searcher = WordSearcher(dictionary=d, min_len=3, max_len=12, time_budget=2.0)
    results = searcher.find_best_words(board, loadout, top_n=10)
    words = {r.word: r.score for r in results}
    assert "123ifer" in words
    assert words["123ifer"] > words.get("a23ifer", 0)
    assert results[0].word == "123ifer" or words[results[0].word] >= words["123ifer"]


def test_finds_a2345lt_from_void_letter_start(tmp_path):
    """Words like a2345lt start on void A; number-first DFS never reaches that cell in 2s."""
    from pathlib import Path

    from cursed_words_solver.config import GAME_WORDLIST_PATH
    from tests.integration.test_loadout_scoring import _board_from_debug_json

    debug = Path.home() / ".cursed_words_solver" / "debug" / "parse_20260522_170102.json"
    if not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024:
        return
    if not debug.exists():
        return

    d = WordDictionary(GAME_WORDLIST_PATH)
    board = _board_from_debug_json(debug.name)
    board.money = 42
    from tests.integration.test_loadout_scoring import _hayley_loadout

    loadout = _hayley_loadout(birthday_cake_bonus="76")
    loadout.stickers = [
        LoadoutItem(id="alembic_flask", name="Alembic Flask", level=2, kind="sticker"),
        *loadout.stickers,
    ]
    loadout.money = 42
    searcher = WordSearcher(dictionary=d, min_len=3, max_len=12, time_budget=2.0)
    results = searcher.find_best_words(board, loadout, top_n=10)
    words = {r.word: r.score for r in results}
    assert "a2345lt" in words
    assert words["a2345lt"] >= 790.0
    assert words["a2345lt"] > words.get("1a345lt", 0)


def test_finds_seven_letter_number_word_not_capped_at_six(tmp_path):
    """Digit-focused search must use max_len, not 6, or fu34s6s is missed."""
    from cursed_words_solver.config import GAME_WORDLIST_PATH

    if not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024:
        return

    d = WordDictionary(GAME_WORDLIST_PATH)
    searcher = WordSearcher(dictionary=d, min_len=3, max_len=12, time_budget=12.0)
    board = _board_fu34s6s_fixture()
    results = searcher.find_best_words(board, top_n=20)
    words = {r.word: r.score for r in results}
    assert "fu34s6" in words
    assert "fu34s6s" in words
    assert words["fu34s6s"] > words["fu34s6"]


def test_finds_v2o4_number_word(tmp_path):
    from cursed_words_solver.config import GAME_WORDLIST_PATH

    if not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024:
        return

    d = WordDictionary(GAME_WORDLIST_PATH)
    searcher = WordSearcher(dictionary=d, min_len=3, max_len=6, time_budget=5.0)
    board = _board_v2o4_fixture()
    results = searcher.find_best_words(board, top_n=20)
    words = [r.word for r in results]
    assert "v2o4" in words
    assert "1r3hv" not in words


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


def test_finds_1_fraction_245fe_above_134pebra(tmp_path):
    """Regression: digit+fraction words with legal fraction slots beat 134pebra."""
    from cursed_words_solver.config import GAME_WORDLIST_PATH
    from cursed_words_solver.rules.pipeline import ScoringPipeline
    from cursed_words_solver.rules.stamp_behaviors import stamp_search_flags
    from cursed_words_solver.search import PathValidator

    if not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024:
        pytest.skip("game wordlist required")

    board = _board_1_fraction_245fe_fixture()
    loadout = Loadout(
        stickers=[
            LoadoutItem(id="traffic_lights", name="Traffic Lights", level=3, kind="sticker"),
            LoadoutItem(id="alembic_flask", name="Alembic Flask", level=2, kind="sticker"),
            LoadoutItem(id="birthday_cake", name="Birthday Cake", level=3, kind="sticker"),
            LoadoutItem(id="lab_coat", name="Lab Coat", level=2, kind="sticker"),
            LoadoutItem(id="brain", name="Brain", level=3, kind="sticker"),
        ],
        stamps=[
            LoadoutItem(id="hungry_snake", name="Hungry Snake", level=1, kind="sticker"),
            LoadoutItem(id="flamingo", name="Flamingo", level=1, kind="sticker"),
            LoadoutItem(id="test_tube", name="Test Tube", level=1, kind="sticker"),
            LoadoutItem(id="full_battery", name="Full Battery", level=1, kind="sticker"),
            LoadoutItem(id="limnophila", name="Limnophila", level=1, kind="sticker"),
        ],
        extras={
            "pin_effect": "abacus",
            "pin_left_level": "4",
            "pin_right_level": "1",
            "birthday_cake_bonus": "106",
        },
        money=3,
    )
    d = WordDictionary(GAME_WORDLIST_PATH)
    scoring = ScoringPipeline()
    flags = stamp_search_flags(loadout)
    validator = PathValidator(d, min_len=3)

    # Old path placed 3/5 at word position 2 (illegal); search must use num/den slots.
    illegal_path = [9, 13, 17, 21, 22, 16, 10]
    assert not validator.word_ok(board, illegal_path, "1?245fe", flags)

    searcher = WordSearcher(dictionary=d, min_len=3, max_len=15, time_budget=30.0)
    results = searcher.find_best_words(board, loadout, top_n=10)
    assert results
    pebra_score = scoring.score_total_only(
        board, [9, 3, 2, 6, 12, 18, 23, 24], "134pebra", loadout
    )
    best = results[0]
    assert validator.word_ok(board, best.path, best.word, flags)
    assert best.score > pebra_score




def test_tobiano_path_valid_with_flamingo(tmp_path):
    """Flamingo must not force shiny NUMBER tiles to word position 1 (TOBIANO regression)."""
    from cursed_words_solver.config import GAME_WORDLIST_PATH

    if not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024:
        pytest.skip("game wordlist required")

    board = _board_tobiano_fixture()
    path = [7, 6, 5, 11, 12, 16, 22]
    loadout = Loadout(
        stamps=[LoadoutItem(id="flamingo", name="Flamingo", kind="stamp")]
    )
    flags = stamp_search_flags(loadout)
    letters = ""
    for i, idx in enumerate(path):
        t = board.get_by_index(idx)
        letters += resolve_letter(t, len(letters), flags=flags)
    word = letters.lower()
    assert word == "12bi56o"

    d = WordDictionary(GAME_WORDLIST_PATH)
    validator = PathValidator(d, min_len=3)
    assert validator.word_ok(board, path, word, flags)


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


def test_candidate_heap_evicts_worst_not_best():
    """Regression: mid-score candidates must replace the worst heap entry, not the best."""
    heap = _CandidateHeap(2)
    heap.consider(100.0, "low", [1])
    heap.consider(200.0, "high", [2])
    heap.consider(150.0, "mid", [3])
    kept = {word for _, word, _ in heap.best_sorted()}
    assert kept == {"high", "mid"}


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
def test_extension_from_short_chess_item_prefix():
    """Regression: item-aware extension finds 9-tile path from 8-tile prefix (20260529)."""
    import json

    from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
    from cursed_words_solver.search import (
        _CandidateHeap,
        search_word_from_path,
    )
    from cursed_words_solver.rules.stamp_behaviors import stamp_search_flags

    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "mismatches"
        / "20260529_hemiolias_extension.json"
    )
    if not fixture.exists():
        pytest.skip("20260529_hemiolias_extension.json fixture required")
    data = json.loads(fixture.read_text(encoding="utf-8"))
    board = parse_board_from_run_state(data["run_state_snapshot"])
    loadout = parse_run_state(data["run_state_snapshot"])
    assert board is not None

    short_path = data["short_path"]
    expected_path = data["expected_path"]
    pipeline = ScoringPipeline()
    short_score = pipeline.score_total_only(
        board, short_path, data["short_word"], loadout
    )
    expected_score = pipeline.score_total_only(
        board, expected_path, data["expected_word"], loadout
    )

    flags = stamp_search_flags(loadout)
    searcher = WordSearcher(
        dictionary=WordDictionary(GAME_WORDLIST_PATH),
        min_len=3,
        max_len=15,
        time_budget=10.0,
    )
    candidates = _CandidateHeap(200)
    sw = search_word_from_path(board, short_path, flags=flags)
    sc = searcher._rank_score_for_candidate(board, short_path, sw, loadout)
    candidates.consider(sc or 0, sw, short_path)
    searcher._extend_top_candidates(
        board, loadout, candidates, top_paths=30, max_rounds=16
    )
    extended = [
        (rank_sc, word, list(path))
        for rank_sc, word, path in candidates.best_sorted()
        if list(path) == expected_path
    ]
    assert extended
    assert extended[0][0] >= expected_score - 1
    assert extended[0][0] > short_score


@pytest.mark.skipif(
    not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024,
    reason="game wordlist required",
)
def test_extension_from_aahed_prefix_finds_fjelds():
    """Regression: +1 tile from aahed prefix finds fjelds (20260615 path_extension)."""
    import json

    from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
    from cursed_words_solver.search import (
        _CandidateHeap,
        search_word_from_path,
    )

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

    short_path = data["short_path"]
    expected_path = data["expected_path"]
    pipeline = ScoringPipeline()
    short_score = pipeline.score_total_only(
        board, short_path, data["short_word"], loadout
    )

    flags = stamp_search_flags(loadout)
    searcher = WordSearcher(
        dictionary=WordDictionary(GAME_WORDLIST_PATH),
        min_len=3,
        max_len=15,
        time_budget=10.0,
    )
    candidates = _CandidateHeap(200)
    sw = search_word_from_path(board, short_path, flags=flags)
    sc = searcher._rank_score_for_candidate(board, short_path, sw, loadout)
    candidates.consider(sc or 0, sw, short_path)
    searcher._extend_top_candidates(
        board, loadout, candidates, top_paths=30, max_rounds=3
    )
    extended = [
        (rank_sc, word, list(path))
        for rank_sc, word, path in candidates.best_sorted()
        if list(path) == expected_path
    ]
    assert extended
    assert extended[0][0] > short_score
    assert extended[0][0] >= data["expected_score"] - 20


@pytest.mark.skipif(
    not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024,
    reason="game wordlist required",
)
def test_extension_from_lanugos_prefix_finds_latigoes():
    """Regression: +1 tile from lanugos prefix finds latigoes (20260618 path_extension)."""
    import json

    from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
    from cursed_words_solver.search import (
        _CandidateHeap,
        search_word_from_path,
    )

    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "round_logs"
        / "20260618_230147_latigoes_path_extension.json"
    )
    if not fixture.exists():
        pytest.skip("20260618_230147_latigoes_path_extension.json fixture required")
    data = json.loads(fixture.read_text(encoding="utf-8"))
    board = parse_board_from_run_state(data["run_state"])
    loadout = parse_run_state(data["run_state"])
    assert board is not None

    solver = data["solver"]
    actual = data["actual"]
    short_path = solver["path"]
    expected_path = actual["path"]
    short_word = solver["word"]
    pipeline = ScoringPipeline()
    short_score = pipeline.score_total_only(board, short_path, short_word, loadout)

    flags = stamp_search_flags(loadout)
    searcher = WordSearcher(
        dictionary=WordDictionary(GAME_WORDLIST_PATH),
        min_len=3,
        max_len=15,
        time_budget=10.0,
    )
    candidates = _CandidateHeap(200)
    sw = search_word_from_path(board, short_path, flags=flags)
    sc = searcher._rank_score_for_candidate(board, short_path, sw, loadout)
    candidates.consider(sc or 0, sw, short_path)
    resolve_seeds = searcher._dictionary_resolve_extension_seeds(
        board, loadout, candidates
    )
    searcher._extend_top_candidates(
        board,
        loadout,
        candidates,
        top_paths=30,
        max_rounds=3,
        extra_seeds=resolve_seeds,
    )
    extended = [
        (rank_sc, word, list(path))
        for rank_sc, word, path in candidates.best_sorted()
        if list(path) == expected_path
    ]
    assert extended
    assert extended[0][0] > short_score
    assert extended[0][0] >= int(actual["score"]) - 5


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
def test_extension_from_aahs_prefix_finds_eelskin():
    """Regression: +3 tiles from aahs wildcard prefix finds eelskin (20260617 path_extension)."""
    import json

    from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
    from cursed_words_solver.search import (
        _CandidateHeap,
        search_word_from_path,
    )

    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "mismatches"
        / "20260617_142738_eelskin.json"
    )
    if not fixture.exists():
        pytest.skip("20260617_142738_eelskin.json fixture required")
    data = json.loads(fixture.read_text(encoding="utf-8"))
    board = parse_board_from_run_state(data["run_state_snapshot"])
    loadout = parse_run_state(data["run_state_snapshot"])
    assert board is not None

    short_path = data["short_path"]
    expected_path = data["expected_path"]
    pipeline = ScoringPipeline()
    short_score = pipeline.score_total_only(
        board, short_path, data["short_word"], loadout
    )

    flags = stamp_search_flags(loadout)
    searcher = WordSearcher(
        dictionary=WordDictionary(GAME_WORDLIST_PATH),
        min_len=3,
        max_len=15,
        time_budget=10.0,
    )
    candidates = _CandidateHeap(200)
    sc = searcher._rank_score_for_candidate(
        board, short_path, data["short_word"], loadout
    )
    candidates.consider(sc or 0, data["short_word"], short_path)
    searcher._extend_top_candidates(
        board, loadout, candidates, top_paths=30, max_rounds=4
    )
    extended = [
        (rank_sc, word, list(path))
        for rank_sc, word, path in candidates.best_sorted()
        if list(path) == expected_path
    ]
    assert extended
    assert extended[0][0] > short_score
    assert extended[0][0] >= data["expected_score"] - 5


@pytest.mark.skipif(
    not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024,
    reason="game wordlist required",
)
def test_solve_extension_picks_eelskin_over_aahs():
    """Integration: extension passes (incl. post-extend) beat aahs prefix on chess/fraction board."""
    import json

    from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state

    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "mismatches"
        / "20260617_142738_eelskin.json"
    )
    if not fixture.exists():
        pytest.skip("20260617_142738_eelskin.json fixture required")
    data = json.loads(fixture.read_text(encoding="utf-8"))
    board = parse_board_from_run_state(data["run_state_snapshot"])
    loadout = parse_run_state(data["run_state_snapshot"])
    assert board is not None

    pipeline = ScoringPipeline()
    short_path = data["short_path"]
    expected_path = data["expected_path"]
    short_score = pipeline.score_total_only(
        board, short_path, data["short_word"], loadout
    )

    searcher = WordSearcher(
        dictionary=WordDictionary(GAME_WORDLIST_PATH),
        min_len=3,
        max_len=15,
        time_budget=10.0,
    )
    from cursed_words_solver.search import _CandidateHeap

    candidates = _CandidateHeap(200)
    sc = searcher._rank_score_for_candidate(
        board, short_path, data["short_word"], loadout
    )
    candidates.consider(sc or 0, data["short_word"], short_path)
    searcher._extend_top_candidates(
        board,
        loadout,
        candidates,
        top_paths=120,
        max_rounds=16,
    )
    searcher._extend_top_candidates(
        board,
        loadout,
        candidates,
        top_paths=60,
        max_rounds=3,
    )
    extended = [
        (rank_sc, word, list(path))
        for rank_sc, word, path in candidates.best_sorted()
        if list(path) == expected_path
    ]
    assert extended, f"expected eelskin path {expected_path}"
    assert extended[0][0] > short_score
    assert extended[0][0] >= data["expected_score"] - 5


@pytest.mark.skipif(
    not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024,
    reason="game wordlist required",
)
def test_extension_from_bazz_prefix_finds_buzzsaw():
    """Regression: +3 tiles from bazz wildcard prefix finds buzzsaw (20260618 path_extension)."""
    import json

    from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
    from cursed_words_solver.search import _CandidateHeap

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

    short_path = data["short_path"]
    expected_path = data["expected_path"]
    pipeline = ScoringPipeline()
    short_score = pipeline.score_total_only(
        board, short_path, data["short_word"], loadout
    )

    searcher = WordSearcher(
        dictionary=WordDictionary(GAME_WORDLIST_PATH),
        min_len=3,
        max_len=25,
        time_budget=10.0,
    )
    candidates = _CandidateHeap(200)
    sc = searcher._rank_score_for_candidate(
        board, short_path, data["short_word"], loadout
    )
    candidates.consider(sc or 0, data["short_word"], short_path)
    # Decoy paths outrank bazz but share no extendable prefix.
    for decoy_score, decoy_word, decoy_path in (
        (105, "x", [2, 1, 3, 7, 11, 22, 23]),
        (84, "y", [2, 1, 3, 7, 11, 0]),
    ):
        candidates.consider(decoy_score, decoy_word, decoy_path)
    resolve_seeds = searcher._dictionary_resolve_extension_seeds(
        board, loadout, candidates
    )
    assert any(list(entry[2]) == short_path for entry in resolve_seeds)
    searcher._extend_top_candidates(
        board,
        loadout,
        candidates,
        top_paths=30,
        max_rounds=16,
        extra_seeds=resolve_seeds,
    )
    extended = [
        (rank_sc, word, list(path))
        for rank_sc, word, path in candidates.best_sorted()
        if list(path) == expected_path
    ]
    assert extended
    assert extended[0][0] > short_score
    assert extended[0][0] >= data["expected_score"] - 5


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


def test_iter_expansion_neighbors_not_corrupted_by_recursion():
    """Regression: lazy yield from _NEIGHBOR_SCRATCH must snapshot before nested DFS."""
    from cursed_words_solver.rules.stamp_behaviors import stamp_search_flags_mask
    from cursed_words_solver.search import _iter_expansion_neighbors, neighbors_mask

    board, loadout = _nat_h4_board_and_loadout()
    flags = stamp_search_flags_mask(loadout)
    path = [9, 4, 3, 8]
    visited = sum(1 << i for i in path)
    cell_id = 8
    nbr_mask = neighbors_mask(board, visited, cell_id=cell_id, flags=flags)
    collected: list[int] = []
    for idx in _iter_expansion_neighbors(
        board,
        visited,
        cell_id=cell_id,
        path=path,
        flags=flags,
        nbr_mask=nbr_mask,
    ):
        collected.append(idx)
        nested_path = path + [idx]
        nested_visited = visited | (1 << idx)
        list(
            _iter_expansion_neighbors(
                board,
                nested_visited,
                cell_id=idx,
                path=nested_path,
                flags=flags,
            )
        )
    for idx in collected:
        assert nbr_mask & (1 << idx), f"neighbor {idx} not in mask for cell {cell_id}"


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


def test_find_best_words_wall_sec_includes_refine_and_finalize(tmp_path):
    import time

    board = _board_cat_horizontal()
    d = WordDictionary(_make_wordlist(tmp_path))
    searcher = WordSearcher(
        dictionary=d,
        min_len=3,
        max_len=5,
        time_budget=5.0,
        search_workers=1,
    )
    loadout = Loadout()
    original_refine = searcher._refine_provisional_heap

    def slow_refine(board, loadout, candidates, **kwargs):
        time.sleep(0.05)
        original_refine(board, loadout, candidates, **kwargs)

    searcher._refine_provisional_heap = slow_refine
    searcher.find_best_words(board, loadout=loadout, top_n=1)
    timing = searcher.last_search_timing
    assert timing is not None
    assert timing.wall_sec >= timing.refine_sec
    assert timing.refine_sec >= 0.04


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


@pytest.mark.skipif(
    not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024,
    reason="game wordlist required",
)
def test_extension_from_nizams_prefix_finds_nightcap():
    """Regression: +2 tiles from nizams prefix finds nightcap (20260709 path_extension)."""
    import time

    from cursed_words_solver.search import search_word_from_path

    data, board, loadout = _f8_board_loadout_from_round_log(
        "20260709_nightcap_path_extension.json"
    )
    short_path, expected_path = _melmod_paths(board, data)
    short_word = data["solver"]["word"]
    pipeline = ScoringPipeline()
    short_score = pipeline.score_total_only(board, short_path, short_word, loadout)

    flags = stamp_search_flags(loadout)
    searcher = WordSearcher(
        dictionary=WordDictionary(GAME_WORDLIST_PATH),
        min_len=3,
        max_len=25,
        time_budget=10.0,
    )
    candidates = _CandidateHeap(200)
    sw = search_word_from_path(board, short_path, flags=flags)
    sc = searcher._rank_score_for_candidate(board, short_path, sw, loadout)
    candidates.consider(sc or 0, sw, short_path)
    resolve_seeds = searcher._dictionary_resolve_extension_seeds(
        board, loadout, candidates
    )
    extend_deadline = time.monotonic() + 30.0
    searcher._extend_top_candidates(
        board,
        loadout,
        candidates,
        top_paths=30,
        max_rounds=8,
        extra_seeds=resolve_seeds or None,
        deadline=extend_deadline,
    )
    extended = [
        (rank_sc, word, list(path))
        for rank_sc, word, path in candidates.best_sorted()
        if list(path) == expected_path
    ]
    assert extended, f"expected nightcap path {expected_path}"
    assert extended[0][0] > short_score


@pytest.mark.skipif(
    not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024,
    reason="game wordlist required",
)
def test_extension_from_itched_prefix_finds_labrador():
    """Regression: +2 tiles from itched prefix finds labrador (20260709 path_extension)."""
    import time

    from cursed_words_solver.search import search_word_from_path

    data, board, loadout = _f8_board_loadout_from_round_log(
        "20260709_labrador_path_extension.json"
    )
    short_path, expected_path = _melmod_paths(board, data)
    short_word = data["solver"]["word"]
    pipeline = ScoringPipeline()
    short_score = pipeline.score_total_only(board, short_path, short_word, loadout)

    flags = stamp_search_flags(loadout)
    searcher = WordSearcher(
        dictionary=WordDictionary(GAME_WORDLIST_PATH),
        min_len=3,
        max_len=25,
        time_budget=10.0,
    )
    candidates = _CandidateHeap(200)
    sw = search_word_from_path(board, short_path, flags=flags)
    sc = searcher._rank_score_for_candidate(board, short_path, sw, loadout)
    candidates.consider(sc or 0, sw, short_path)
    resolve_seeds = searcher._dictionary_resolve_extension_seeds(
        board, loadout, candidates
    )
    extend_deadline = time.monotonic() + 30.0
    searcher._extend_top_candidates(
        board,
        loadout,
        candidates,
        top_paths=30,
        max_rounds=8,
        extra_seeds=resolve_seeds or None,
        deadline=extend_deadline,
    )
    searcher._extend_dictionary_resolve_boundaries(
        board, loadout, candidates, deadline=extend_deadline
    )
    extended = [
        (rank_sc, word, list(path))
        for rank_sc, word, path in candidates.best_sorted()
        if list(path) == expected_path
    ]
    assert extended, f"expected labrador path {expected_path}"
    assert extended[0][0] > short_score


@pytest.mark.skipif(
    not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024,
    reason="game wordlist required",
)
def test_scatter_augment_dust_finds_ayenbites():
    """Regression: augment dust prefix finds ayenbites (20260709 path_mismatch)."""
    import time

    from cursed_words_solver.search import search_word_from_path

    data, board, loadout = _f8_board_loadout_from_round_log(
        "20260709_ayenbites_path_mismatch.json"
    )
    short_path, expected_path = _melmod_paths(board, data)
    short_word = data["solver"]["word"]

    flags = stamp_search_flags(loadout)
    searcher = WordSearcher(
        dictionary=WordDictionary(GAME_WORDLIST_PATH),
        min_len=3,
        max_len=25,
        time_budget=10.0,
    )
    candidates = _CandidateHeap(200)
    sw = search_word_from_path(board, short_path, flags=flags)
    sc = searcher._rank_score_for_candidate(board, short_path, sw, loadout)
    candidates.consider(sc or 0, sw, short_path)
    searcher._augment_scattered_item_leaders(
        board, loadout, candidates, deadline=time.monotonic() + 30.0
    )
    augmented = [
        (rank_sc, word, list(path))
        for rank_sc, word, path in candidates.best_sorted()
        if list(path) == expected_path
    ]
    assert augmented, f"expected ayenbites path {expected_path}"
