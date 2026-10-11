"""Default-unlocked stamp scoring and search (wiki: Unlocked by default)."""

import json
from pathlib import Path


from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.models import Board, CurseType, Loadout, LoadoutItem, Tile, TileColor
from cursed_words_solver.engine.scorer import EngineScorer
from cursed_words_solver.rules.rule_lookup import get_rule, slugify_name

from tests.catalog.stamps._coverage import assert_loadout_stamp_coverage
from cursed_words_solver.rules.stamp_behaviors import stamp_search_flags
from cursed_words_solver.search import PathValidator, WordSearcher, neighbors_from_tile

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
    "golden_record",
    "golden_scales",
    "kimono",
    "nest_egg",
    "paper_lantern",
    "parachute",
    "pi_ata",
    "saxophone",
    "slot_machine",
    "teapot",
    "waxy_vizor",
    "weekly_shop",
    "window",
    "xray",
    "young_cardinal",
}
SEARCH_ONLY_SLUGS = {
    "full_moon",
    "hungry_snake",
    "queenie",
    "red_envelope",
    "sluggish_zombie",
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
    pipeline = EngineScorer()
    for name in DEFAULT_STAMP_NAMES:
        slug = slugify_name(name)
        _key, rule = get_rule(pipeline.rules, "stamps", slug, name)
        assert rule is not None, slug
        assert rule.get("type") != "unmodeled", slug


def test_count_scoring_vs_grid_only_all_defaults():
    pipeline = EngineScorer()
    assert_loadout_stamp_coverage(pipeline.rules, DEFAULT_STAMP_NAMES)


def test_avocado_doubles_word_score():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 5)
    board.tiles[0][1] = _tile(0, 1, "B", 5)
    pipeline = EngineScorer()
    loadout = _stamp_loadout("avocado", "Avocado")
    score, bd = pipeline.score(board, [0, 1], "ab", loadout)
    base, _ = pipeline.score(board, [0, 1], "ab", Loadout())
    assert bd["multiplier"] == 2.0
    assert score == base * 2


def test_avocado_mushy_negative_multiplier():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 5)
    pipeline = EngineScorer()
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
    pipeline = EngineScorer()
    loadout = Loadout(
        stamps=[LoadoutItem(id="bento_box", name="Bento Box", kind="stamp")],
        extras={"previous_word_first_letter": "c", "grid_number": "2"},
    )
    score, bd = pipeline.score(board, [0], "cat", loadout)
    assert bd["multiplier"] == 1.5
    assert score == 4 * 1.5


def test_bento_box_path_first_letter_not_dictionary_word():
    """When path-first matches previous but dictionary word does not, Bento still applies."""
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "$", 0, curse=CurseType.CURRENCY)
    board.tiles[0][1] = _tile(0, 1, "E", 1)
    pipeline = EngineScorer()
    loadout = Loadout(
        stamps=[LoadoutItem(id="bento_box", name="Bento Box", kind="stamp")],
        extras={"previous_word_first_letter": "e", "grid_number": "2"},
    )
    score, bd = pipeline.score(board, [0, 1], "weep", loadout)
    assert bd["multiplier"] == 1.5
    assert score == 1.0

    loadout_no_match = Loadout(
        stamps=[LoadoutItem(id="bento_box", name="Bento Box", kind="stamp")],
        extras={"previous_word_first_letter": "w", "grid_number": "2"},
    )
    score2, bd2 = pipeline.score(board, [0, 1], "weep", loadout_no_match)
    assert bd2["multiplier"] == 1.0
    assert score2 == 1.0


def test_historic_words_fallback_previous_letter():
    from cursed_words_solver.loadout import _normalize_pin_extras

    extras = _normalize_pin_extras(
        {
            "historic_words": json.dumps(
                [{"word": "yarn", "path": [0]}, {"word": "yodel", "path": [1]}]
            )
        }
    )
    assert extras.get("previous_word_first_letter") == "y"


def test_limnophila_alphabet_progression():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "C", 4)
    pipeline = EngineScorer()
    loadout = Loadout(
        stamps=[LoadoutItem(id="limnophila", name="Limnophila", kind="stamp")],
        extras={
            "grid_number": "2",
            "scoring_previous_words_count": "1",
            "previous_word_first_letter": "b",
        },
    )
    score, bd = pipeline.score(board, [0], "cat", loadout)
    assert bd["multiplier"] == 1.5


def test_bubble_tea_letter_count_multiply():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "B", 2)
    board.tiles[0][1] = _tile(0, 1, "B", 2)
    board.tiles[0][2] = _tile(0, 2, "A", 2)
    pipeline = EngineScorer()
    loadout = _stamp_loadout("bubble_tea", "Bubble Tea")
    score, _ = pipeline.score(board, [0, 1, 2], "bba", loadout)
    assert score == 2 * 2 + 2 * 2 + 2


def test_bubble_tea_banana_chess_knight_faces():
    """Chess knights count by face char (j), not letter=? (zebrinny 28→69 math)."""
    board = _empty_board()
    # z(10) j j j i(1) n(1) n(1) y(4) — three knights share face j
    faces = [
        ("z", "Z", CurseType.LETTER, 10),
        ("j", "?", CurseType.CHESS_KNIGHT, 3),
        ("j", "?", CurseType.CHESS_KNIGHT, 3),
        ("j", "?", CurseType.CHESS_KNIGHT, 3),
        ("i", "I", CurseType.LETTER, 1),
        ("n", "N", CurseType.LETTER, 1),
        ("n", "N", CurseType.LETTER, 1),
        ("y", "Y", CurseType.LETTER, 4),
    ]
    path = []
    for i, (char, letter, curse, score) in enumerate(faces):
        row, col = divmod(i, 5)
        board.tiles[row][col] = Tile(
            row=row,
            col=col,
            char=char,
            letter=letter,
            base_score=score,
            color=TileColor.COLORLESS,
            curse=curse,
            metadata={"source": "melmod"},
        )
        path.append(row * 5 + col)
    pipeline = EngineScorer()
    loadout = Loadout(
        stamps=[
            LoadoutItem(id="bubble_tea", name="Bubble Tea", level=1, kind="stamp"),
            LoadoutItem(id="banana", name="Banana", level=1, kind="stamp"),
        ]
    )
    score, _ = pipeline.score(board, path, "zebrinny", loadout)
    # Bubble Tea: 10 + 9+9+9 + 1 + 2+2 + 4 = 46; Banana ×1.5 → 69
    assert score == 69


def test_banana_counts_item_emoji_faces():
    """ITEM display glyphs group for Banana (comitadji ghosts → ×1.5)."""
    board = _empty_board()
    # a(1) + 👻×3 (0) + b(3) = 4 base; three ghosts → Banana ×1.5 → 6
    specs = [
        ("a", "A", CurseType.LETTER, 1),
        ("👻", "?", CurseType.ITEM, 0),
        ("👻", "?", CurseType.ITEM, 0),
        ("👻", "?", CurseType.ITEM, 0),
        ("b", "B", CurseType.LETTER, 3),
    ]
    path = []
    for i, (char, letter, curse, score) in enumerate(specs):
        row, col = divmod(i, 5)
        board.tiles[row][col] = Tile(
            row=row,
            col=col,
            char=char,
            letter=letter,
            base_score=score,
            color=TileColor.COLORLESS,
            curse=curse,
            metadata={"source": "melmod"},
        )
        path.append(row * 5 + col)
    pipeline = EngineScorer()
    loadout = Loadout(
        stamps=[LoadoutItem(id="banana", name="Banana", level=1, kind="stamp")]
    )
    score, bd = pipeline.score(board, path, "a???b", loadout)
    assert bd["multiplier"] == 1.5
    assert score == 6


def test_bubble_tea_banana_currency_and_chess_rook_faces():
    """Currency maps via CURRENCY_MAP; rooks use char=r (cippus 24→46 math)."""
    board = _empty_board()
    # ₱ P, I, ₱ P, ₱ P, rook r, rook r — with Wrestlers ×1.5
    specs = [
        ("₱", "₱", CurseType.CURRENCY, 0, {"card_suit": "clubs"}),
        ("i", "I", CurseType.LETTER, 1, {}),
        ("₱", "₱", CurseType.CURRENCY, 0, {"card_suit": "clubs"}),
        ("₱", "₱", CurseType.CURRENCY, 0, {"card_suit": "spades"}),
        ("r", "?", CurseType.CHESS_ROOK, 5, {"card_suit": "diamonds"}),
        ("r", "?", CurseType.CHESS_ROOK, 5, {"card_suit": "diamonds"}),
    ]
    path = []
    for i, (char, letter, curse, score, meta) in enumerate(specs):
        row, col = divmod(i, 5)
        board.tiles[row][col] = Tile(
            row=row,
            col=col,
            char=char,
            letter=letter,
            base_score=score,
            color=TileColor.COLORLESS,
            curse=curse,
            metadata={"source": "melmod", **meta},
        )
        path.append(row * 5 + col)
    pipeline = EngineScorer()
    loadout = Loadout(
        stickers=[
            LoadoutItem(id="wrestlers", name="Wrestlers", level=1, kind="sticker"),
        ],
        stamps=[
            LoadoutItem(id="bubble_tea", name="Bubble Tea", level=1, kind="stamp"),
            LoadoutItem(id="banana", name="Banana", level=1, kind="stamp"),
        ],
    )
    score, _ = pipeline.score(board, path, "cippus", loadout)
    # Bubble Tea: 0+1+0+0+10+10 = 21; Wrestlers ×1.5 then Banana ×1.5 floors → 46
    assert score == 46


def test_queenie_q_tile_multiply():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "Q", 2)
    board.tiles[0][1] = _tile(0, 1, "A", 2)
    pipeline = EngineScorer()
    loadout = _stamp_loadout("queenie", "Queenie")
    score, _ = pipeline.score(board, [0, 1], "qa", loadout)
    assert score == 2 * 5 + 2


def test_merge_tile_ninja_consumables_used_backfill():
    from cursed_words_solver.loadout import merge_tile_ninja_extras_into

    dest = {
        "tile_ninja_bonus": "0",
        "tile_ninja_bonus_last_known": "0",
        "tile_ninja_consumables_used": "10",
    }
    merge_tile_ninja_extras_into(dest, dest)
    assert dest["tile_ninja_bonus"] == "0.2"
    assert dest["tile_ninja_bonus_last_known"] == "0.2"


def test_merge_tile_ninja_extras_monotonic_ignores_zero_live():
    """F8 embed must not downgrade when live run_state exports stale zero."""
    from cursed_words_solver.loadout import merge_tile_ninja_extras_into

    dest = {
        "tile_ninja_bonus": "0.24",
        "tile_ninja_bonus_last_known": "0.24",
        "tile_ninja_bonus_at_grid_start": "0.24",
    }
    merge_tile_ninja_extras_into(
        dest,
        {
            "tile_ninja_bonus": "0",
            "tile_ninja_bonus_last_known": "0",
            "tile_ninja_bonus_at_grid_start": "0",
        },
    )
    assert dest["tile_ninja_bonus"] == "0.24"
    assert dest["tile_ninja_bonus_last_known"] == "0.24"
    assert dest["tile_ninja_bonus_at_grid_start"] == "0.24"


def test_merge_tile_ninja_at_grid_start_backfill_from_last_known():
    """F8 embed seeds at_grid_start when live export leaves it at zero."""
    from cursed_words_solver.loadout import merge_tile_ninja_extras_into

    dest = {
        "tile_ninja_bonus": "0.24",
        "tile_ninja_bonus_last_known": "0.24",
        "tile_ninja_bonus_at_grid_start": "0",
    }
    merge_tile_ninja_extras_into(
        dest,
        {
            "tile_ninja_bonus": "0.24",
            "tile_ninja_bonus_last_known": "0.24",
            "tile_ninja_bonus_at_grid_start": "0",
        },
    )
    assert dest["tile_ninja_bonus_at_grid_start"] == "0.24"


def test_bento_skipped_wootzes_style_won_leading_prev_o():
    """wootzes-style: ₩→W matches dictionary 'w'; prev 'o' must not trigger Bento."""
    board = _empty_board()
    board.tiles[2][1] = _tile(2, 1, "₩", 0, curse=CurseType.CURRENCY)
    board.tiles[2][1].metadata["was_consumable"] = True
    board.tiles[1][1] = _tile(1, 1, "O", 1)
    board.tiles[1][2] = _tile(1, 2, "O", 1)
    board.tiles[1][3] = _tile(1, 3, "T", 1)
    board.tiles[2][3] = _tile(2, 3, "Z", 10)
    board.tiles[2][4] = _tile(2, 4, "E", 1)
    board.tiles[2][2] = _tile(2, 2, "S", 1)
    pipeline = EngineScorer()
    loadout = Loadout(
        stamps=[LoadoutItem(id="bento_box", name="Bento Box", kind="stamp")],
        extras={"previous_word_first_letter": "o", "grid_number": "3"},
    )
    path = [11, 6, 7, 8, 13, 12]
    score, bd = pipeline.score(board, path, "wootzes", loadout)
    assert bd["multiplier"] == 1.0
    assert int(score) == 14


def test_bento_skipped_benelux_style_baht_leading_prev_e():
    """benelux-style: ฿ at path[0] maps to word 'b'; prev 'e' must not trigger Bento."""
    board = _empty_board()
    board.tiles[1][3] = _tile(1, 3, "฿", 0, curse=CurseType.CURRENCY)
    board.tiles[1][3].metadata["was_consumable"] = True
    board.tiles[0][2] = _tile(0, 2, "E", 1)
    board.tiles[0][3] = _tile(0, 3, "N", 1)
    board.tiles[0][4] = _tile(0, 4, "E", 1)
    board.tiles[1][4] = _tile(1, 4, "L", 1)
    board.tiles[2][4] = _tile(2, 4, "U", 1)
    board.tiles[2][3] = _tile(2, 3, "X", 1)
    pipeline = EngineScorer()
    loadout = Loadout(
        stamps=[LoadoutItem(id="bento_box", name="Bento Box", kind="stamp")],
        extras={"previous_word_first_letter": "e", "grid_number": "3"},
    )
    path = [8, 2, 3, 4, 9, 14, 13]
    score, bd = pipeline.score(board, path, "benelux", loadout)
    assert bd["multiplier"] == 1.0
    assert int(score) == 6


def test_bento_skipped_when_currency_maps_to_word_first_letter():
    """boluses-style: ฿→B matches dictionary 'b'; game uses word-first, not path 'o'."""
    board = _empty_board()
    board.tiles[2][3] = _tile(2, 3, "฿", 0, curse=CurseType.CURRENCY)
    board.tiles[2][3].metadata["was_consumable"] = True
    board.tiles[1][3] = _tile(1, 3, "O", 1)
    board.tiles[2][2] = _tile(2, 2, "L", 1)
    board.tiles[2][4] = _tile(2, 4, "U", 1)
    board.tiles[3][4] = _tile(3, 4, "S", 1)
    board.tiles[3][3] = _tile(3, 3, "E", 1)
    board.tiles[3][2] = _tile(3, 2, "S", 1)
    pipeline = EngineScorer()
    loadout = Loadout(
        stamps=[LoadoutItem(id="bento_box", name="Bento Box", kind="stamp")],
        extras={"previous_word_first_letter": "o", "grid_number": "3"},
    )
    path = [13, 8, 12, 17, 18, 22]
    score, bd = pipeline.score(board, path, "boluses", loadout)
    assert bd["multiplier"] == 1.0
    assert int(score) == 5


def test_bento_skipped_sauteed_style_dollar_leading_prev_a():
    """sauteed-style: $ at path[0] maps to word 's'; prev 'a' must not trigger Bento."""
    board = _empty_board()
    board.tiles[2][3] = _tile(2, 3, "$", 0, curse=CurseType.CURRENCY)
    board.tiles[2][3].metadata["was_consumable"] = True
    board.tiles[2][2] = _tile(2, 2, "A", 1)
    board.tiles[3][2] = _tile(3, 2, "U", 1)
    board.tiles[3][3] = _tile(3, 3, "T", 1)
    board.tiles[2][4] = _tile(2, 4, "E", 1)
    board.tiles[0][1] = _tile(0, 1, "E", 1)
    board.tiles[1][0] = _tile(1, 0, "D", 2)
    pipeline = EngineScorer()
    loadout = Loadout(
        stamps=[LoadoutItem(id="bento_box", name="Bento Box", kind="stamp")],
        extras={"previous_word_first_letter": "a", "grid_number": "4"},
    )
    path = [13, 12, 17, 18, 14, 1, 5]
    score, bd = pipeline.score(board, path, "sauteed", loadout)
    assert bd["multiplier"] == 1.0
    assert int(score) == 7


def test_bento_skipped_when_word_first_letter_differs_from_path_leading_tile():
    """sclerae-style: currency/path tile 'c' must not trigger Bento when word starts 's'."""
    board = _empty_board()
    board.tiles[2][2] = _tile(2, 2, "?", 0, curse=CurseType.CURRENCY)
    board.tiles[2][2].metadata["was_consumable"] = False
    board.tiles[2][3] = _tile(2, 3, "S", 1)
    board.tiles[2][4] = _tile(2, 4, "C", 1)
    board.tiles[3][4] = _tile(3, 4, "L", 1)
    board.tiles[4][4] = _tile(4, 4, "E", 1)
    board.tiles[4][3] = _tile(4, 3, "R", 1)
    board.tiles[4][2] = _tile(4, 2, "A", 1)
    board.tiles[4][1] = _tile(4, 1, "E", 1)
    pipeline = EngineScorer()
    loadout = Loadout(
        stamps=[LoadoutItem(id="bento_box", name="Bento Box", kind="stamp")],
        extras={"previous_word_first_letter": "c", "grid_number": "3"},
    )
    path = [12, 13, 14, 19, 24, 23, 22]
    score, bd = pipeline.score(board, path, "sclerae", loadout)
    assert bd["multiplier"] == 1.0
    assert int(score) == 6


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


def test_full_moon_no_teleport_between_letter_and_currency_e():
    """€ maps to E for words but Full Moon matches physical glyph only."""
    grid = [[_tile(r, c, "X", 1) for c in range(5)] for r in range(5)]
    grid[0][0] = _tile(0, 0, "E", 1)
    grid[0][1] = Tile(
        row=0,
        col=1,
        char="€",
        letter="E",
        base_score=0,
        curse=CurseType.CURRENCY,
    )
    board = Board(tiles=grid)
    loadout = _stamp_loadout("full_moon", "Full Moon")
    flags = stamp_search_flags(loadout)
    nbrs = neighbors_from_tile(board, [0], {1 << 0}, flags=flags)
    assert 1 not in nbrs


def test_full_moon_no_letter_teleport_to_chess_rook_with_same_char():
    """Melmod keeps underlying letter in char; rook must not match letter T via Full Moon."""
    grid = [[_tile(r, c, "X", 1) for c in range(5)] for r in range(5)]
    grid[3][1] = _tile(3, 1, "T", 2)
    grid[3][3] = Tile(
        row=3,
        col=3,
        char="t",
        letter="?",
        base_score=5,
        color=TileColor.COLORLESS,
        curse=CurseType.CHESS_ROOK,
        metadata={"chess_color": "white"},
    )
    board = Board(tiles=grid)
    loadout = _stamp_loadout("full_moon", "Full Moon")
    flags = stamp_search_flags(loadout)
    nbrs = neighbors_from_tile(board, [16], {1 << 16}, flags=flags)
    assert 18 not in nbrs


def test_full_moon_chess_rook_teleport_to_identical_rook():
    grid = [[_tile(r, c, "X", 1) for c in range(5)] for r in range(5)]
    grid[3][1] = Tile(
        row=3,
        col=1,
        char="t",
        letter="?",
        base_score=5,
        color=TileColor.COLORLESS,
        curse=CurseType.CHESS_ROOK,
        metadata={"chess_color": "white"},
    )
    grid[3][3] = Tile(
        row=3,
        col=3,
        char="t",
        letter="?",
        base_score=5,
        color=TileColor.COLORLESS,
        curse=CurseType.CHESS_ROOK,
        metadata={"chess_color": "white"},
    )
    board = Board(tiles=grid)
    loadout = _stamp_loadout("full_moon", "Full Moon")
    flags = stamp_search_flags(loadout)
    nbrs = neighbors_from_tile(board, [16], {1 << 16}, flags=flags)
    assert 18 in nbrs


def test_full_moon_no_teleport_between_opposite_color_knights():
    """Wiki: filled black and outlined white knights are not identical for Full Moon."""
    grid = [[_tile(r, c, "X", 1) for c in range(5)] for r in range(5)]
    grid[1][1] = Tile(
        row=1,
        col=1,
        char="h",
        letter="?",
        base_score=3,
        color=TileColor.COLORLESS,
        curse=CurseType.CHESS_KNIGHT,
        metadata={"chess_color": "black"},
    )
    grid[1][4] = Tile(
        row=1,
        col=4,
        char="h",
        letter="?",
        base_score=3,
        color=TileColor.COLORLESS,
        curse=CurseType.CHESS_KNIGHT,
        metadata={"chess_color": "white"},
    )
    board = Board(tiles=grid)
    loadout = _stamp_loadout("full_moon", "Full Moon")
    flags = stamp_search_flags(loadout)
    nbrs = neighbors_from_tile(board, [6], {1 << 6}, flags=flags)
    assert 9 not in nbrs


def test_full_moon_teleport_between_same_color_knights():
    grid = [[_tile(r, c, "X", 1) for c in range(5)] for r in range(5)]
    grid[1][1] = Tile(
        row=1,
        col=1,
        char="h",
        letter="?",
        base_score=3,
        color=TileColor.COLORLESS,
        curse=CurseType.CHESS_KNIGHT,
        metadata={"chess_color": "white"},
    )
    grid[1][4] = Tile(
        row=1,
        col=4,
        char="h",
        letter="?",
        base_score=3,
        color=TileColor.COLORLESS,
        curse=CurseType.CHESS_KNIGHT,
        metadata={"chess_color": "white"},
    )
    board = Board(tiles=grid)
    loadout = _stamp_loadout("full_moon", "Full Moon")
    flags = stamp_search_flags(loadout)
    nbrs = neighbors_from_tile(board, [6], {1 << 6}, flags=flags)
    assert 9 in nbrs


def test_full_moon_joker_teleports_to_joker_not_blank():
    """Game: BespokeCard+Joker emoji ≠ GlyphType.Blank '?' (GridUtility Full Moon)."""
    grid = [[_tile(r, c, "X", 1) for c in range(5)] for r in range(5)]
    grid[0][0] = Tile(
        row=0,
        col=0,
        char="🃏",
        letter="?",
        base_score=0,
        curse=CurseType.WILDCARD,
        metadata={"is_joker": True, "card_suit": "joker"},
    )
    grid[4][4] = Tile(
        row=4,
        col=4,
        char="🃏",
        letter="?",
        base_score=0,
        curse=CurseType.WILDCARD,
        metadata={"is_joker": True, "card_suit": "joker"},
    )
    grid[0][4] = Tile(
        row=0,
        col=4,
        char="?",
        letter="?",
        base_score=0,
        curse=CurseType.WILDCARD,
        metadata={"card_suit": "hearts"},
    )
    board = Board(tiles=grid)
    loadout = _stamp_loadout("full_moon", "Full Moon")
    flags = stamp_search_flags(loadout)
    nbrs = neighbors_from_tile(board, [0], {1 << 0}, flags=flags)
    assert 24 in nbrs
    assert 4 not in nbrs


def test_full_moon_blank_teleports_to_blank():
    """Game GlyphType.Blank GetStringRepresentation is '?'."""
    grid = [[_tile(r, c, "X", 1) for c in range(5)] for r in range(5)]
    grid[0][0] = Tile(
        row=0,
        col=0,
        char="?",
        letter="?",
        base_score=0,
        curse=CurseType.WILDCARD,
    )
    grid[4][0] = Tile(
        row=4,
        col=0,
        char="?",
        letter="?",
        base_score=0,
        curse=CurseType.WILDCARD,
    )
    board = Board(tiles=grid)
    loadout = _stamp_loadout("full_moon", "Full Moon")
    flags = stamp_search_flags(loadout)
    nbrs = neighbors_from_tile(board, [0], {1 << 0}, flags=flags)
    assert 20 in nbrs


def test_full_moon_number_teleports_to_same_number():
    """Game Number glyph uses Number.ToString() for Full Moon matching."""
    grid = [[_tile(r, c, "X", 1) for c in range(5)] for r in range(5)]
    grid[0][0] = Tile(
        row=0,
        col=0,
        char="2",
        letter="2",
        base_score=2,
        curse=CurseType.NUMBER,
        number_value=2,
    )
    grid[4][4] = Tile(
        row=4,
        col=4,
        char="2",
        letter="2",
        base_score=2,
        curse=CurseType.NUMBER,
        number_value=2,
    )
    grid[0][4] = Tile(
        row=0,
        col=4,
        char="7",
        letter="7",
        base_score=7,
        curse=CurseType.NUMBER,
        number_value=7,
    )
    board = Board(tiles=grid)
    loadout = _stamp_loadout("full_moon", "Full Moon")
    flags = stamp_search_flags(loadout)
    nbrs = neighbors_from_tile(board, [0], {1 << 0}, flags=flags)
    assert 24 in nbrs
    assert 4 not in nbrs


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
