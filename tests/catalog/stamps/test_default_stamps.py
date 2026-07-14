"""Default-unlocked stamp scoring and search (wiki: Unlocked by default)."""

import json
from pathlib import Path

import pytest

from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.models import (
    Board,
    CurseType,
    Loadout,
    LoadoutItem,
    Tile,
    TileColor,
)
from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.rule_lookup import get_rule, slugify_name

from tests.catalog.stamps._coverage import assert_loadout_stamp_coverage
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
    pipeline = ScoringPipeline()
    for name in DEFAULT_STAMP_NAMES:
        slug = slugify_name(name)
        _key, rule = get_rule(pipeline.rules, "stamps", slug, name)
        assert rule is not None, slug
        assert rule.get("type") != "unmodeled", slug


def test_count_scoring_vs_grid_only_all_defaults():
    pipeline = ScoringPipeline()
    assert_loadout_stamp_coverage(pipeline.rules, DEFAULT_STAMP_NAMES)


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
        extras={"previous_word_first_letter": "c", "grid_number": "2"},
    )
    score, bd = pipeline.score(board, [0], "cat", loadout)
    assert bd["multiplier"] == 1.5
    assert score == 4 * 1.5


def test_bento_box_skipped_on_first_grid():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "Y", 4)
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stamps=[LoadoutItem(id="bento_box", name="Bento Box", kind="stamp")],
        extras={"previous_word_first_letter": "y", "grid_number": "1"},
    )
    score, bd = pipeline.score(board, [0], "yaccas", loadout)
    assert bd["multiplier"] == 1.0
    assert score == 4.0


def test_bento_box_skipped_when_stale_grid_number_but_first_grid_flag():
    """Stale grid_number export must not trigger Bento on encounter grid 1."""
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "D", 2)
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stamps=[LoadoutItem(id="bento_box", name="Bento Box", kind="stamp")],
        extras={
            "previous_word_first_letter": "d",
            "grid_number": "2",
            "is_first_grid_of_encounter": True,
        },
    )
    score, bd = pipeline.score(board, [0], "debilities", loadout)
    assert bd["multiplier"] == 1.0
    assert score == 2.0


def test_bento_box_path_first_letter_not_dictionary_word():
    """When path-first matches previous but dictionary word does not, Bento still applies."""
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "$", 0, curse=CurseType.CURRENCY)
    board.tiles[0][1] = _tile(0, 1, "E", 1)
    pipeline = ScoringPipeline()
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


def test_yegg_bento_box_with_previous_word_letter():
    """Regression: Bento Box ×1.5 when current word matches previous first letter (yegg)."""
    from tests.regression.test_scoring_mismatches import (
        _adjust_bento_previous_word_extras,
        _run_state_for_replay,
    )

    fixture = (
        Path(__file__).resolve().parents[2]
        / "fixtures"
        / "mismatches"
        / "20260525_032753.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    run_state = _run_state_for_replay(data)
    _adjust_bento_previous_word_extras(run_state, data)
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    pipeline = ScoringPipeline()
    score, _bd = pipeline.score(board, data["path"], data["word"], loadout)
    assert score == 108


def test_woo_bento_box_with_previous_word_letter():
    """Regression: Bento Box ×1.5 when current word matches previous first letter (woo)."""
    from tests.regression.test_scoring_mismatches import (
        _adjust_bento_previous_word_extras,
        _run_state_for_replay,
    )

    fixture = (
        Path(__file__).resolve().parents[2]
        / "fixtures"
        / "mismatches"
        / "20260525_035046.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    run_state = _run_state_for_replay(data)
    _adjust_bento_previous_word_extras(run_state, data)
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    pipeline = ScoringPipeline()
    score, _bd = pipeline.score(board, data["path"], data["word"], loadout)
    assert score == 594


def test_vielles_bento_box_with_previous_word_letter():
    """Regression: Bento Box ×1.5 when current word matches previous first letter (vielles)."""
    from tests.regression.test_scoring_mismatches import (
        _adjust_bento_previous_word_extras,
        _run_state_for_replay,
    )

    fixture = (
        Path(__file__).resolve().parents[2]
        / "fixtures"
        / "mismatches"
        / "20260525_033903.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    run_state = _run_state_for_replay(data)
    _adjust_bento_previous_word_extras(run_state, data)
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    pipeline = ScoringPipeline()
    score, _bd = pipeline.score(board, data["path"], data["word"], loadout)
    assert score == 111


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


def test_chips_path_first_letter_not_dictionary_word():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "$", 0, curse=CurseType.CURRENCY)
    board.tiles[0][1] = _tile(0, 1, "E", 1)
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[LoadoutItem(id="chips", name="Chips", level=1)],
        extras={"previous_word_first_letter": "a"},
    )
    score, bd = pipeline.score(board, [0, 1], "weep", loadout)
    assert bd["multiplier"] == 1.5
    assert score == int(1 * 1.5)


def test_limnophila_alphabet_progression():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "C", 4)
    pipeline = ScoringPipeline()
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


def test_limnophila_not_any_later_letter():
    """soz capture: s > o but Limnophila needs exactly p after o."""
    from cursed_words_solver.rules.scoring_conditions import explain_sticker_condition

    board = _empty_board()
    board.tiles[0][1] = _tile(0, 1, "S", 16, color=TileColor.COLORLESS)
    board.tiles[0][2] = _tile(0, 2, "O", 17, color=TileColor.BLUE)
    board.tiles[1][2] = _tile(
        1, 2, "?", 1, color=TileColor.BLUE, curse=CurseType.WILDCARD
    )
    loadout = Loadout(
        stamps=[LoadoutItem(id="limnophila", name="Limnophila", kind="stamp")],
        extras={
            "grid_number": "2",
            "scoring_previous_words_count": "2",
            "previous_word_first_letter": "o",
        },
    )
    met, detail = explain_sticker_condition(
        "word_starts_after_previous",
        board,
        [1, 2, 7],
        "soz",
        loadout,
        applying_sticker_id="limnophila",
    )
    assert met is False
    assert "need 'p'" in detail
    assert "'o'" in detail


def test_limnophila_rejects_owner_after_e():
    """owner after e: o > e but Limnophila needs exactly f."""
    from cursed_words_solver.rules.scoring_conditions import explain_sticker_condition

    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "O", 1)
    loadout = Loadout(
        stamps=[LoadoutItem(id="limnophila", name="Limnophila", kind="stamp")],
        extras={
            "grid_number": "2",
            "scoring_previous_words_count": "2",
            "previous_word_first_letter": "e",
        },
    )
    met, detail = explain_sticker_condition(
        "word_starts_after_previous",
        board,
        [0],
        "owner",
        loadout,
        applying_sticker_id="limnophila",
    )
    assert met is False
    assert "need 'f'" in detail


def test_limnophila_exact_plus_one_titfers():
    from cursed_words_solver.rules.scoring_conditions import explain_sticker_condition

    board = _empty_board()
    board.tiles[0][1] = _tile(0, 1, "T", 11, color=TileColor.COLORLESS)
    loadout = Loadout(
        stamps=[LoadoutItem(id="limnophila", name="Limnophila", kind="stamp")],
        extras={
            "grid_number": "3",
            "scoring_previous_words_count": "2",
            "previous_word_first_letter": "s",
        },
    )
    met, detail = explain_sticker_condition(
        "word_starts_after_previous",
        board,
        [1],
        "titfers",
        loadout,
        applying_sticker_id="limnophila",
    )
    assert met is True
    assert "one letter after" in detail


def test_limnophila_wildcard_leading_uses_word_first_letter():
    """ayus capture: path ? Y U ? — game uses word-first 'a', not path-first 'y'."""
    from cursed_words_solver.rules.scoring_conditions import explain_sticker_condition

    board = _empty_board()
    board.tiles[2][2] = _tile(2, 2, "?", 0, curse=CurseType.WILDCARD)
    board.tiles[3][1] = _tile(3, 1, "Y", 15, color=TileColor.BLUE)
    board.tiles[3][2] = _tile(3, 2, "U", 17, color=TileColor.RED)
    board.tiles[4][3] = _tile(
        4, 3, "?", 1, color=TileColor.BLUE, curse=CurseType.WILDCARD
    )
    loadout = Loadout(
        stamps=[LoadoutItem(id="limnophila", name="Limnophila", kind="stamp")],
        extras={
            "grid_number": "3",
            "scoring_previous_words_count": "2",
            "previous_word_first_letter": "s",
        },
    )
    met, detail = explain_sticker_condition(
        "word_starts_after_previous",
        board,
        [12, 16, 17, 23],
        "ayus",
        loadout,
        applying_sticker_id="limnophila",
    )
    assert met is False
    assert "'a'" in detail
    assert "need 't'" in detail


def test_bubble_tea_letter_count_multiply():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "B", 2)
    board.tiles[0][1] = _tile(0, 1, "B", 2)
    board.tiles[0][2] = _tile(0, 2, "A", 2)
    pipeline = ScoringPipeline()
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
    pipeline = ScoringPipeline()
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
    pipeline = ScoringPipeline()
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
    pipeline = ScoringPipeline()
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


def test_tile_ninja_two_consumable_placements_bonus():
    """Encounter bonus after two consumable placements: ×1.24 (120% + 4%)."""
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 10)
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stamps=[LoadoutItem(id="tile_ninja", name="Tile Ninja", kind="stamp")],
        extras={"tile_ninja_bonus": 0.04},
    )
    score, bd = pipeline.score(board, [0], "a", loadout)
    assert bd["multiplier"] == 1.24
    assert score == int(10 * 1.24)


def test_tile_ninja_path_consumable_bump_when_export_missing():
    """F8-before-submit: count was_consumable tiles on path when bonus export is 0."""
    from cursed_words_solver.rules.scoring_conditions import tile_ninja_multiplier_bonus

    board = _empty_board()
    for idx, ch in enumerate("ab"):
        tile = _tile(0, idx, ch, 10)
        tile.metadata["was_consumable"] = True
        board.tiles[0][idx] = tile
    loadout = Loadout(
        stamps=[LoadoutItem(id="tile_ninja", name="Tile Ninja", kind="stamp")],
        extras={},
    )
    assert tile_ninja_multiplier_bonus(loadout, board=board, path=[0, 1]) == 0.04


def test_tile_ninja_last_known_when_live_export_zero():
    """Stale F8 export zero: use tile_ninja_bonus_last_known from prior submit."""
    from cursed_words_solver.rules.scoring_conditions import tile_ninja_multiplier_bonus

    loadout = Loadout(
        stamps=[LoadoutItem(id="tile_ninja", name="Tile Ninja", kind="stamp")],
        extras={"tile_ninja_bonus": 0, "tile_ninja_bonus_last_known": 0.16},
    )
    assert tile_ninja_multiplier_bonus(loadout) == 0.16


def test_tile_ninja_consumables_used_when_live_export_zero():
    from cursed_words_solver.rules.scoring_conditions import tile_ninja_multiplier_bonus

    loadout = Loadout(
        stamps=[LoadoutItem(id="tile_ninja", name="Tile Ninja", kind="stamp")],
        extras={
            "tile_ninja_bonus": 0,
            "tile_ninja_bonus_last_known": 0,
            "tile_ninja_consumables_used": 10,
        },
    )
    assert tile_ninja_multiplier_bonus(loadout) == pytest.approx(0.2)


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


def test_tile_ninja_adds_on_path_bump_when_export_lags_board():
    """parathas-style: committed export 0.14 + two new on-path placements → 0.18."""
    from cursed_words_solver.rules.scoring_conditions import tile_ninja_multiplier_bonus

    board = _empty_board()
    # Seven prior-grid placements (already in export) plus two new on-path tiles.
    for idx, ch in enumerate("abcdefgxy"):
        row, col = divmod(idx, 5)
        tile = _tile(row, col, ch, 10)
        tile.metadata["was_consumable"] = True
        board.tiles[row][col] = tile
    loadout = Loadout(
        stamps=[LoadoutItem(id="tile_ninja", name="Tile Ninja", kind="stamp")],
        extras={"tile_ninja_bonus": 0.14},
    )
    path = [7, 8]
    assert tile_ninja_multiplier_bonus(loadout, board=board, path=path) == pytest.approx(
        0.18
    )


def test_tile_ninja_committed_uses_max_of_live_and_last_known():
    """F8 export: committed bonus is max(tile_ninja_bonus, last_known), not first key."""
    from cursed_words_solver.rules.scoring_conditions import tile_ninja_multiplier_bonus

    loadout = Loadout(
        stamps=[LoadoutItem(id="tile_ninja", name="Tile Ninja", kind="stamp")],
        extras={
            "tile_ninja_bonus": 0.28,
            "tile_ninja_bonus_last_known": 0.24,
            "tile_ninja_bonus_at_grid_start": 0.24,
        },
    )
    assert tile_ninja_multiplier_bonus(loadout) == 0.28


def test_tile_ninja_pending_bump_uses_enriched_base_baseline():
    """On-path bump baseline uses enriched export (not raw grid_start alone)."""
    from cursed_words_solver.rules.scoring_conditions import tile_ninja_multiplier_bonus

    board = _empty_board()
    for col in range(4):
        board.tiles[0][col] = _tile(0, col, "A", 1)
        board.tiles[0][col].metadata["was_consumable"] = True
    loadout = Loadout(
        stamps=[LoadoutItem(id="tile_ninja", name="Tile Ninja", kind="stamp")],
        extras={
            "tile_ninja_bonus": 0.08,
            "tile_ninja_bonus_at_grid_start": 0.04,
        },
    )
    # live 0.08 already covers 4 board placements — no extra on-path bump
    assert tile_ninja_multiplier_bonus(loadout, board=board, path=[0]) == pytest.approx(
        0.08
    )

    lag_board = _empty_board()
    for col in range(3):
        lag_board.tiles[0][col] = _tile(0, col, "A", 1)
        lag_board.tiles[0][col].metadata["was_consumable"] = True
    lag_loadout = Loadout(
        stamps=[LoadoutItem(id="tile_ninja", name="Tile Ninja", kind="stamp")],
        extras={
            "tile_ninja_bonus": 0,
            "tile_ninja_consumables_used": 2,
        },
    )
    # used 2 -> base 0.04; 3 on board -> 1 pending; one on path -> +0.02
    assert tile_ninja_multiplier_bonus(
        lag_loadout, board=lag_board, path=[0]
    ) == pytest.approx(0.06)


def test_tile_ninja_no_double_count_when_export_matches_board():
    """Post-submit export already includes board placements — no extra bump."""
    from cursed_words_solver.rules.scoring_conditions import tile_ninja_multiplier_bonus

    board = _empty_board()
    for idx, ch in enumerate("ab"):
        tile = _tile(0, idx, ch, 10)
        tile.metadata["was_consumable"] = True
        board.tiles[0][idx] = tile
    loadout = Loadout(
        stamps=[LoadoutItem(id="tile_ninja", name="Tile Ninja", kind="stamp")],
        extras={"tile_ninja_bonus": 0.18},
    )
    assert tile_ninja_multiplier_bonus(loadout, board=board, path=[0, 1]) == 0.18


def test_tile_ninja_missing_export_single_on_path_floor():
    """olearias-style: no export, one on-path placement → 0.02."""
    from cursed_words_solver.rules.scoring_conditions import tile_ninja_multiplier_bonus

    board = _empty_board()
    tile = _tile(0, 0, "a", 10)
    tile.metadata["was_consumable"] = True
    board.tiles[0][0] = tile
    loadout = Loadout(
        stamps=[LoadoutItem(id="tile_ninja", name="Tile Ninja", kind="stamp")],
        extras={},
    )
    assert tile_ninja_multiplier_bonus(loadout, board=board, path=[0]) == 0.02


def test_sequoia_skips_currency_glyph_mapped_vowel():
    """€ currency resolves to E for scoring but must not match Sequoia vowel target."""
    from cursed_words_solver.rules.scoring_conditions import tile_matches_target

    board = _empty_board()
    board.tiles[2][1] = _tile(2, 1, "E", 0, curse=CurseType.CURRENCY)
    board.tiles[2][1].char = "€"
    tile = board.get_by_index(11)
    assert tile.letter == "E"
    assert not tile_matches_target(tile, "vowel")


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
    pipeline = ScoringPipeline()
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
    pipeline = ScoringPipeline()
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
    pipeline = ScoringPipeline()
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
    pipeline = ScoringPipeline()
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
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stamps=[LoadoutItem(id="bento_box", name="Bento Box", kind="stamp")],
        extras={"previous_word_first_letter": "c", "grid_number": "3"},
    )
    path = [12, 13, 14, 19, 24, 23, 22]
    score, bd = pipeline.score(board, path, "sclerae", loadout)
    assert bd["multiplier"] == 1.0
    assert int(score) == 6


def test_tile_ninja_fourteen_percent_on_high_subtotal():
    """Seven consumable placements: ×1.34 on pre-Ninja subtotal (woozier-style)."""
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "W", 10)
    board.tiles[0][1] = _tile(0, 1, "O", 10)
    board.tiles[0][2] = _tile(0, 2, "O", 10)
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stamps=[LoadoutItem(id="tile_ninja", name="Tile Ninja", kind="stamp")],
        extras={"tile_ninja_bonus": 0.14},
    )
    score, bd = pipeline.score(board, [0, 1, 2], "woo", loadout)
    assert bd["multiplier"] == pytest.approx(1.34)
    assert score == int(30 * 1.34)


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


def test_golden_record_word_only_when_full_rack_short_word():
    from cursed_words_solver.rules.scoring_conditions import (
        golden_record_multiplies_word_score_only,
    )

    loadout = Loadout(
        stamps=[LoadoutItem(id="golden_record", name="Golden Record", kind="stamp")],
        extras={"consumable_rack_count": "5"},
    )
    board = Board(tiles=[[_tile(0, 0, "A", 1)]])
    state = {"tile_scores": [0.0, 1.0, 4.0, 9.0], "word_score": 23.0}
    assert golden_record_multiplies_word_score_only(
        loadout, board, [0, 1, 2, 3], state
    )
    assert not golden_record_multiplies_word_score_only(
        loadout, board, [0, 1, 2, 3, 4, 5], state
    )
    loadout.extras["consumable_rack_count"] = "3"
    assert not golden_record_multiplies_word_score_only(
        loadout, board, [0, 1, 2, 3], state
    )
