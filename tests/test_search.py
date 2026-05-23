from pathlib import Path

import pytest

from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.models import Board, CurseType, Loadout, LoadoutItem, Tile, TileColor
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.stamp_behaviors import stamp_search_flags
from cursed_words_solver.search import (
    PathValidator,
    WordSearcher,
    _balanced_start_indices,
    _wildcard_start_indices,
    neighbors_from_tile,
    neighbors_standard,
    resolve_letter,
)


def _make_wordlist(tmp_path: Path) -> Path:
    words = ["cat", "car", "tar", "rat", "art", "the", "buy", "game", "boo", "book"]
    p = tmp_path / "words.txt"
    p.write_text("\n".join(words), encoding="utf-8")
    return p


def _board_cat_horizontal() -> Board:
    tiles = []
    letters = [
        list("catxx"),
        list("xxxxx"),
        list("xxxxx"),
        list("xxxxx"),
        list("xxxxx"),
    ]
    for r in range(5):
        row = []
        for c in range(5):
            ch = letters[r][c] if letters[r][c] != "x" else "Q"
            row.append(
                Tile(
                    row=r,
                    col=c,
                    char=ch,
                    letter=ch,
                    base_score=1,
                    color=TileColor.COLORLESS,
                    curse=CurseType.LETTER,
                )
            )
        tiles.append(row)
    return Board(tiles=tiles)


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


def _board_hit_shiny_h_fixture() -> Board:
    """Melmod-like board: shiny H (50) tempts DFS to depth 15 via M before I."""

    def letter(
        r: int,
        c: int,
        ch: str,
        base_score: float = 1.0,
        color: TileColor = TileColor.COLORLESS,
    ) -> Tile:
        return Tile(
            row=r,
            col=c,
            char=ch,
            letter=ch.upper(),
            base_score=base_score,
            color=color,
            curse=CurseType.LETTER,
            metadata={"source": "melmod"},
        )

    def number(r: int, c: int, ch: str, face: int) -> Tile:
        return Tile(
            row=r,
            col=c,
            char=ch,
            letter=ch,
            base_score=0.0,
            color=TileColor.VOID,
            curse=CurseType.NUMBER,
            number_value=face,
            metadata={"source": "melmod"},
        )

    grid = [[letter(r, c, "Q") for c in range(5)] for r in range(5)]
    grid[0][0] = letter(0, 0, "e")
    grid[0][1] = Tile(
        row=0,
        col=1,
        char="t",
        letter="T",
        base_score=0.0,
        color=TileColor.VOID,
        curse=CurseType.LETTER,
        metadata={"source": "melmod"},
    )
    grid[0][2] = number(0, 2, "9", 9)
    grid[0][3] = number(0, 3, "8", 8)
    grid[0][4] = letter(0, 4, "n")
    grid[1][0] = letter(1, 0, "e")
    grid[1][1] = letter(1, 1, "m", base_score=4.0, color=TileColor.RED)
    grid[1][2] = letter(1, 2, "h", base_score=50.0, color=TileColor.SHINY)
    grid[1][3] = letter(1, 3, "i")
    grid[1][4] = letter(1, 4, "t")
    for r, c, ch in [
        (2, 0, "h"),
        (2, 1, "s"),
        (2, 2, "e"),
        (2, 3, "u"),
        (2, 4, "c"),
        (3, 0, "c"),
        (3, 1, "i"),
        (3, 2, "y"),
        (3, 3, "i"),
        (3, 4, "e"),
        (4, 0, "d"),
        (4, 1, "a"),
        (4, 2, "r"),
        (4, 3, "w"),
        (4, 4, "b"),
    ]:
        grid[r][c] = letter(r, c, ch)
    return Board(tiles=grid)


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


def _board_wildcard_quill_fixture() -> Board:
    """Full 5×5 board: ?u?ll must start on wildcard at index 8."""
    def letter_tile(r, c, ch, score=1, color=TileColor.COLORLESS):
        return Tile(
            row=r,
            col=c,
            char=ch,
            letter=ch,
            base_score=score,
            color=color,
            curse=CurseType.LETTER,
            metadata={"source": "melmod"},
        )

    def wildcard_tile(r, c, score=10):
        return Tile(
            row=r,
            col=c,
            char="?",
            letter="?",
            base_score=score,
            color=TileColor.COLORLESS,
            curse=CurseType.WILDCARD,
            metadata={"source": "melmod"},
        )

    layout = [
        "PDSPL",
        "EYE?N",
        "E?ULV",
        "IAVUL",
        "SESAT",
    ]
    grid = []
    for r, row_chars in enumerate(layout):
        row = []
        for c, ch in enumerate(row_chars):
            if ch == "?":
                row.append(wildcard_tile(r, c))
            else:
                row.append(letter_tile(r, c, ch))
        grid.append(row)
    return Board(tiles=grid)


def _wildcard_quill_wordlist(tmp_path: Path) -> Path:
    words = ["quill", "skull", "ulva", "null", "pull", "full", "gull", "dull", "mull"]
    p = tmp_path / "wildcard_quill.txt"
    p.write_text("\n".join(words), encoding="utf-8")
    return p


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


def _board_boo4_fixture() -> Board:
    """Minimal board: boo4 with number 4 at position 4 (1-indexed)."""
    def tile(r, c, ch, score, curse=CurseType.LETTER, number_value=None):
        return Tile(
            row=r,
            col=c,
            char=ch,
            letter=ch,
            base_score=score,
            color=TileColor.COLORLESS,
            curse=curse,
            number_value=number_value,
            metadata={"source": "melmod"},
        )

    grid = [[tile(r, c, "Q", 1) for c in range(5)] for r in range(5)]
    grid[2][1] = tile(2, 1, "B", 3)
    grid[2][2] = tile(2, 2, "O", 1)
    grid[2][3] = tile(2, 3, "O", 1)
    grid[2][4] = tile(2, 4, "4", 4, CurseType.NUMBER, number_value=4)
    return Board(tiles=grid)


def _board_1r3vo_fixture() -> Board:
    """1 at index 0, r at 1, 3 at index 2, v at 3, o at 4 — number positions 1 and 3."""
    def tile(r, c, ch, score, curse=CurseType.LETTER, number_value=None):
        return Tile(
            row=r,
            col=c,
            char=ch,
            letter=ch,
            base_score=score,
            color=TileColor.COLORLESS,
            curse=curse,
            number_value=number_value,
            metadata={"source": "melmod"},
        )

    grid = [[tile(r, c, "Q", 1) for c in range(5)] for r in range(5)]
    grid[0][0] = tile(0, 0, "1", 1, CurseType.NUMBER, number_value=1)
    grid[0][1] = tile(0, 1, "R", 1)
    grid[0][2] = tile(0, 2, "3", 3, CurseType.NUMBER, number_value=3)
    grid[0][3] = tile(0, 3, "V", 4)
    grid[0][4] = tile(0, 4, "O", 1)
    return Board(tiles=grid)


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


def _board_v2o4_fixture() -> Board:
    """v2o4: V + number 2 at pos 2 + O + number 4 at pos 4 (path along row 3-4)."""
    def tile(
        r,
        c,
        ch,
        score,
        curse=CurseType.LETTER,
        number_value=None,
        color=TileColor.COLORLESS,
    ):
        return Tile(
            row=r,
            col=c,
            char=ch,
            letter=ch,
            base_score=score,
            color=color,
            curse=curse,
            number_value=number_value,
            metadata={"source": "melmod"},
        )

    grid = [[tile(r, c, "Q", 1) for c in range(5)] for r in range(5)]
    grid[3][2] = tile(3, 2, "V", 5, color=TileColor.BLUE)
    grid[4][2] = tile(4, 2, "2", 2, CurseType.NUMBER, number_value=2)
    grid[3][3] = tile(3, 3, "O", 1)
    grid[3][4] = tile(
        3, 4, "4", 5, CurseType.NUMBER, number_value=4, color=TileColor.RED
    )
    return Board(tiles=grid)


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


def _board_fu34s6s_fixture() -> Board:
    """Path [11,17,18,19,14,13,9] → fu34s6s (7 letters); shorter fu34s6 also valid."""
    def tile(
        r,
        c,
        ch,
        score,
        curse=CurseType.LETTER,
        number_value=None,
        color=TileColor.COLORLESS,
    ):
        return Tile(
            row=r,
            col=c,
            char=ch,
            letter=ch,
            base_score=score,
            color=color,
            curse=curse,
            number_value=number_value,
            metadata={"source": "melmod"},
        )

    grid = [[tile(r, c, "Q", 1) for c in range(5)] for r in range(5)]
    grid[2][1] = tile(2, 1, "F", 2)
    grid[3][2] = tile(3, 2, "U", 2)
    grid[3][3] = tile(3, 3, "3", 3, CurseType.NUMBER, number_value=3)
    grid[3][4] = tile(3, 4, "4", 4, CurseType.NUMBER, number_value=4)
    grid[2][4] = tile(2, 4, "S", 2)
    grid[2][3] = tile(2, 3, "6", 6, CurseType.NUMBER, number_value=6)
    grid[1][4] = tile(1, 4, "S", 2)
    return Board(tiles=grid)


def _board_123ifer_fixture() -> Board:
    """Debug board where 123ifer (143) beats a23ifer (107); must start DFS on the 1 tile."""
    from pathlib import Path

    from tests.test_loadout_scoring import _board_from_debug_json

    path = Path.home() / ".cursed_words_solver" / "debug" / "parse_20260522_163602.json"
    if path.exists():
        return _board_from_debug_json(path.name)
    # Minimal inline fallback (same layout as melmod export)
    def tile(r, c, ch, score, *, curse=CurseType.LETTER, nv=None, color=TileColor.COLORLESS):
        return Tile(
            row=r,
            col=c,
            char=ch,
            letter=ch,
            base_score=score,
            color=color,
            curse=curse,
            number_value=nv,
            metadata={"source": "melmod"},
        )

    grid = [[tile(r, c, "Q", 1) for c in range(5)] for r in range(5)]
    grid[0][1] = tile(0, 1, "3", 3, curse=CurseType.NUMBER, nv=3)
    grid[1][4] = tile(1, 4, "2", 2, curse=CurseType.NUMBER, nv=2)
    grid[2][2] = tile(2, 2, "I", 1)
    grid[2][3] = tile(2, 3, "A", 1)
    grid[3][0] = tile(3, 0, "M", 3)
    grid[3][1] = tile(3, 1, "F", 4)
    grid[3][2] = tile(3, 2, "R", 1)
    grid[3][3] = tile(3, 3, "3", 3, curse=CurseType.NUMBER, nv=3)
    grid[3][4] = tile(3, 4, "2", 2, curse=CurseType.NUMBER, nv=2)
    grid[4][0] = tile(4, 0, "E", 1)
    grid[4][1] = tile(4, 1, "R", 1)
    grid[4][3] = tile(4, 3, "1", 1, curse=CurseType.NUMBER, nv=1)
    grid[4][4] = tile(4, 4, "5", 5, curse=CurseType.NUMBER, nv=5)
    return Board(tiles=grid, money=8)


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
    from tests.test_loadout_scoring import _board_from_debug_json

    debug = Path.home() / ".cursed_words_solver" / "debug" / "parse_20260522_170102.json"
    if not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024:
        return
    if not debug.exists():
        return

    d = WordDictionary(GAME_WORDLIST_PATH)
    board = _board_from_debug_json(debug.name)
    board.money = 42
    from tests.test_loadout_scoring import _hayley_loadout

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


def _board_tobiano_fixture() -> Board:
    """Melmod board where T-2-B-I-5-6-O spells TOBIANO (12bi56o with Flamingo T→1)."""
    def tile(
        r,
        c,
        ch,
        score,
        *,
        curse=CurseType.LETTER,
        number_value=None,
        color=TileColor.COLORLESS,
    ):
        return Tile(
            row=r,
            col=c,
            char=ch,
            letter=ch,
            base_score=score,
            color=color,
            curse=curse,
            number_value=number_value,
            metadata={"source": "melmod"},
        )

    grid = [[tile(r, c, "Q", 1) for c in range(5)] for r in range(5)]
    rows = [
        "GPEVE",
        "B2T1T",
        "YI5IR",
        "O6ERI",
        "7ROON",
    ]
    for r, row in enumerate(rows):
        for c, ch in enumerate(row):
            if ch.isdigit():
                grid[r][c] = tile(
                    r,
                    c,
                    ch,
                    0,
                    curse=CurseType.NUMBER,
                    number_value=int(ch),
                    color=(
                        TileColor.VOID
                        if ch in "127"
                        else TileColor.SHINY
                    ),
                )
            else:
                grid[r][c] = tile(r, c, ch, 2)
    grid[1][2] = tile(1, 2, "T", 50, color=TileColor.SHINY)
    grid[2][2] = tile(2, 2, "5", 50, curse=CurseType.NUMBER, number_value=5, color=TileColor.SHINY)
    grid[3][1] = tile(3, 1, "6", 50, curse=CurseType.NUMBER, number_value=6, color=TileColor.SHINY)
    grid[2][1] = tile(2, 1, "I", 1, color=TileColor.VOID)
    grid[4][2] = tile(4, 2, "O", 1, color=TileColor.BLUE)
    return Board(tiles=grid, money=37)


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
    tobiano_path = [7, 6, 5, 11, 12, 16, 22]

    if fixture.exists():
        assert results[0].score > 400
        assert results[0].score > words.get("12bier", 0)
        # T-2-B-I-5-6 prefix of in-game TOBIANO (12bi56o / 12bi56er)
        assert results[0].path[:6] == tobiano_path[:6]
    else:
        assert words.get("12bi56o", 0) > words.get("12bier", 0)


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
