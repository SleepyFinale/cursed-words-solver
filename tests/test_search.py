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

