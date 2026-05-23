"""Default-unlocked stamp scoring and search (wiki: Unlocked by default)."""

from pathlib import Path

from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.models import (
    Board,
    CurseType,
    Loadout,
    LoadoutItem,
    Tile,
    TileColor,
)
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.rule_lookup import count_scoring_items, get_rule, slugify_name
from cursed_words_solver.rules.stamp_behaviors import stamp_search_flags
from cursed_words_solver.search import (
    PathValidator,
    WordSearcher,
    neighbors_from_tile,
    neighbors_standard,
    resolve_letter,
)

DEFAULT_STAMP_NAMES = [
    "Avocado",
    "Bento Box",
    "Bubble Tea",
    "Downward Trending Chart",
    "Efficient Recycler",
    "Family Ticket",
    "Full Moon",
    "Golden Record",
    "Golden Scales",
    "Hungry Snake",
    "Kimono",
    "Limnophila",
    "Nest Egg",
    "Paper Lantern",
    "Parachute",
    "Piñata",
    "Queenie",
    "Red Envelope",
    "Saxophone",
    "Slot Machine",
    "Sluggish Zombie",
    "Teapot",
    "Tile Ninja",
    "Waxy Vizor",
    "Weekly Shop",
    "Window",
    "Xray",
    "Young Cardinal",
]

GRID_ONLY_SLUGS = {
    "downward_trending_chart",
    "efficient_recycler",
    "family_ticket",
    "full_moon",
    "golden_record",
    "golden_scales",
    "hungry_snake",
    "kimono",
    "nest_egg",
    "paper_lantern",
    "parachute",
    "pi_ata",
    "red_envelope",
    "saxophone",
    "slot_machine",
    "sluggish_zombie",
    "teapot",
    "waxy_vizor",
    "weekly_shop",
    "window",
    "xray",
    "young_cardinal",
}


def _tile(
    row: int,
    col: int,
    ch: str,
    score: int,
    *,
    color=TileColor.COLORLESS,
    curse=CurseType.LETTER,
) -> Tile:
    return Tile(
        row=row,
        col=col,
        char=ch,
        letter=ch,
        base_score=score,
        color=color,
        curse=curse,
        metadata={"source": "melmod"},
    )


def _empty_board() -> Board:
    grid = [[_tile(r, c, "X", 1) for c in range(5)] for r in range(5)]
    return Board(tiles=grid, money=0)


def _stamp_loadout(slug: str, name: str) -> Loadout:
    return Loadout(stamps=[LoadoutItem(id=slug, name=name, level=1, kind="stamp")])


def _make_wordlist(tmp_path: Path, words: list[str]) -> Path:
    p = tmp_path / "words.txt"
    p.write_text("\n".join(words), encoding="utf-8")
    return p


def test_all_default_stamps_catalogued():
    pipeline = ScoringPipeline()
    for name in DEFAULT_STAMP_NAMES:
        slug = slugify_name(name)
        _key, rule = get_rule(pipeline.rules, "stamps", slug, name)
        assert rule is not None, slug
        assert rule.get("type") != "unmodeled", slug


def test_count_scoring_vs_grid_only_all_defaults():
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stamps=[
            LoadoutItem(id=slugify_name(n), name=n, level=1, kind="stamp")
            for n in DEFAULT_STAMP_NAMES
        ]
    )
    scoring, total, grid_only = count_scoring_items(pipeline.rules, loadout)
    assert total == 28
    assert grid_only == len(GRID_ONLY_SLUGS)
    assert scoring == 28 - len(GRID_ONLY_SLUGS)


def test_avocado_doubles_word_score():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 5)
    board.tiles[0][1] = _tile(0, 1, "B", 5)
    pipeline = ScoringPipeline()
    loadout = _stamp_loadout("avocado", "Avocado")
    score, bd = pipeline.score(board, [0, 1], "ab", loadout)
    base, _ = pipeline.score(board, [0, 1], "ab", Loadout())
    assert bd["multiplier"] == 2.0
    assert score == base * 2


def test_avocado_mushy_negative_multiplier():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 5)
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stamps=[LoadoutItem(id="avocado", name="Avocado", kind="stamp")],
        extras={"avocado_mushy": True},
    )
    score, bd = pipeline.score(board, [0], "a", loadout)
    assert bd["multiplier"] == -2.0
    assert score == 5 * -2


def test_bento_box_same_first_letter():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "C", 4)
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stamps=[LoadoutItem(id="bento_box", name="Bento Box", kind="stamp")],
        extras={"previous_word_first_letter": "c"},
    )
    score, bd = pipeline.score(board, [0], "cat", loadout)
    assert bd["multiplier"] == 1.5
    assert score == 4 * 1.5


def test_limnophila_alphabet_progression():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "C", 4)
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stamps=[LoadoutItem(id="limnophila", name="Limnophila", kind="stamp")],
        extras={"previous_word_first_letter": "a"},
    )
    score, bd = pipeline.score(board, [0], "cat", loadout)
    assert bd["multiplier"] == 1.5


def test_bubble_tea_letter_count_multiply():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "B", 2)
    board.tiles[0][1] = _tile(0, 1, "B", 2)
    board.tiles[0][2] = _tile(0, 2, "A", 2)
    pipeline = ScoringPipeline()
    loadout = _stamp_loadout("bubble_tea", "Bubble Tea")
    score, _ = pipeline.score(board, [0, 1, 2], "bba", loadout)
    assert score == 2 * 2 + 2 * 2 + 2


def test_queenie_q_tile_multiply():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "Q", 2)
    board.tiles[0][1] = _tile(0, 1, "A", 2)
    pipeline = ScoringPipeline()
    loadout = _stamp_loadout("queenie", "Queenie")
    score, _ = pipeline.score(board, [0, 1], "qa", loadout)
    assert score == 2 * 5 + 2


def test_tile_ninja_base_and_bonus():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 10)
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stamps=[LoadoutItem(id="tile_ninja", name="Tile Ninja", kind="stamp")],
        extras={"tile_ninja_bonus": 0.06},
    )
    score, bd = pipeline.score(board, [0], "a", loadout)
    assert bd["multiplier"] == 1.26
    assert score == int(10 * 1.26)  # game floors fractional totals


def test_hungry_snake_horizontal_wrap_neighbors():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 1)
    loadout = _stamp_loadout("hungry_snake", "Hungry Snake")
    flags = stamp_search_flags(loadout)
    nbrs = neighbors_standard(board, [0], {0}, flags=flags)
    assert 4 in nbrs


def test_red_envelope_red_as_e_resolve():
    board = _empty_board()
    tile = _tile(0, 0, "X", 1, color=TileColor.RED)
    loadout = _stamp_loadout("red_envelope", "Red Envelope")
    flags = stamp_search_flags(loadout)
    assert resolve_letter(tile, 0, flags=flags) == "e"


def test_sluggish_zombie_z_as_s_resolve():
    board = _empty_board()
    tile = _tile(0, 0, "Z", 1)
    loadout = _stamp_loadout("sluggish_zombie", "Sluggish Zombie")
    flags = stamp_search_flags(loadout)
    assert resolve_letter(tile, 0, flags=flags) == "s"


def test_queenie_q_resolves_as_qu():
    board = _empty_board()
    tile = _tile(0, 0, "Q", 1)
    loadout = _stamp_loadout("queenie", "Queenie")
    flags = stamp_search_flags(loadout)
    assert resolve_letter(tile, 0, flags=flags) == "qu"


def test_full_moon_double_letter_teleport(tmp_path):
    words = ["bee", "bed"]
    wl = _make_wordlist(tmp_path, words)
    d = WordDictionary(wl)
    tiles = []
    letters = [
        list("bxxxx"),
        list("xxxxx"),
        list("xxxxx"),
        list("xxxxx"),
        list("bxxxx"),
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
    board = Board(tiles=tiles)
    loadout = _stamp_loadout("full_moon", "Full Moon")
    flags = stamp_search_flags(loadout)
    nbrs = neighbors_from_tile(board, [0], {1 << 0}, flags=flags)
    assert 20 in nbrs  # second 'b' at row 4 col 0


def test_full_moon_flamingo_shiny_e_teleport_matches_physical_letter():
    """Flamingo shiny-as-1 is word-position only; Full Moon matches tile glyph."""
    grid = [[_tile(r, c, "X", 1) for c in range(5)] for r in range(5)]
    grid[0][0] = _tile(0, 0, "E", 50, color=TileColor.SHINY)
    grid[1][4] = _tile(1, 4, "E", 2, color=TileColor.BLUE)
    grid[3][2] = _tile(3, 2, "E", 2, color=TileColor.BLUE)
    board = Board(tiles=grid)
    loadout = Loadout(
        stamps=[
            LoadoutItem(id="flamingo", name="Flamingo", level=1, kind="stamp"),
            LoadoutItem(id="full_moon", name="Full Moon", level=1, kind="stamp"),
        ]
    )
    flags = stamp_search_flags(loadout)
    assert resolve_letter(grid[0][0], 0, flags=flags) == "1"
    path = [5, 11, 7, 21, 17]
    visited = sum(1 << i for i in path)
    nbrs = neighbors_from_tile(board, path, visited, flags=flags)
    assert 0 in nbrs  # shiny E at (0,0)
    assert 9 in nbrs  # blue E at (1,4)


def test_red_envelope_finds_word_with_red_as_e(tmp_path):
    words = ["the", "tee"]
    wl = _make_wordlist(tmp_path, words)
    d = WordDictionary(wl)
    grid = [[_tile(r, c, "Q", 1) for c in range(5)] for r in range(5)]
    grid[0][0] = _tile(0, 0, "T", 1)
    grid[0][1] = _tile(0, 1, "H", 1, color=TileColor.RED)
    grid[0][2] = _tile(0, 2, "E", 1)
    board = Board(tiles=grid)
    loadout = _stamp_loadout("red_envelope", "Red Envelope")
    validator = PathValidator(d, min_len=3)
    assert validator.word_ok(board, [0, 1, 2], "the")


def test_sluggish_zombie_finds_zoo_as_soo(tmp_path):
    words = ["soo", "zoo"]
    wl = _make_wordlist(tmp_path, words)
    d = WordDictionary(wl)
    grid = [[_tile(r, c, "Q", 1) for c in range(5)] for r in range(5)]
    grid[2][0] = _tile(2, 0, "Z", 1)
    grid[2][1] = _tile(2, 1, "O", 1)
    grid[2][2] = _tile(2, 2, "O", 1)
    board = Board(tiles=grid)
    loadout = _stamp_loadout("sluggish_zombie", "Sluggish Zombie")
    searcher = WordSearcher(dictionary=d, min_len=3, max_len=5, time_budget=3.0)
    results = searcher.find_best_words(board, loadout, top_n=5)
    words_found = {r.word for r in results}
    assert "soo" in words_found


def test_hungry_snake_finds_wrapped_word(tmp_path):
    words = ["arc", "car"]
    wl = _make_wordlist(tmp_path, words)
    d = WordDictionary(wl)
    grid = [[_tile(r, c, "Q", 1) for c in range(5)] for r in range(5)]
    grid[0][0] = _tile(0, 0, "A", 1)
    grid[0][4] = _tile(0, 4, "R", 1)
    grid[1][4] = _tile(1, 4, "C", 1)
    board = Board(tiles=grid)
    loadout = _stamp_loadout("hungry_snake", "Hungry Snake")
    searcher = WordSearcher(dictionary=d, min_len=3, max_len=5, time_budget=3.0)
    results = searcher.find_best_words(board, loadout, top_n=5)
    assert any(r.word == "arc" for r in results)
