import json
from pathlib import Path

from cursed_words_solver.loadout import parse_board_from_run_state
from cursed_words_solver.models import Board, CurseType, Loadout, Tile, TileColor
from cursed_words_solver.rules.base_scoring import score_word_base, tile_base_contribution
from cursed_words_solver.rules.scoring_conditions import is_red_note_tile

DEBUG_DIR = Path.home() / ".cursed_words_solver" / "debug"


def _board_from_letters(rows: list[str]) -> Board:
    tiles = []
    for r, row in enumerate(rows):
        row_tiles = []
        for c, ch in enumerate(row):
            row_tiles.append(
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
        tiles.append(row_tiles)
    return Board(tiles=tiles)


def test_shiny_tile_flat_50_ocr():
    """OCR boards without melmod metadata use wiki flat 50 shiny base."""
    t = Tile(0, 0, "A", "A", 1, TileColor.SHINY, CurseType.LETTER)
    assert tile_base_contribution(t) == 50


def test_melmod_shiny_uses_packet_score():
    t = Tile(
        0,
        0,
        "A",
        "A",
        1,
        TileColor.SHINY,
        CurseType.LETTER,
        metadata={"source": "melmod"},
    )
    assert tile_base_contribution(t) == 1


def test_melmod_red_no_extra_color_bonus_when_base_equals_scrabble():
    """Melmod packet.Score on colored tile must not get +1 again (BOOH-style bug)."""
    t = Tile(
        0,
        0,
        "H",
        "H",
        4,
        TileColor.RED,
        CurseType.LETTER,
        metadata={"source": "melmod"},
    )
    assert tile_base_contribution(t) == 4


def test_void_negates_letter():
    t = Tile(0, 0, "E", "E", 1, TileColor.VOID, CurseType.LETTER)
    assert tile_base_contribution(t) == -1


def test_melmod_void_letter_zero_base_score():
    t = Tile(
        0,
        0,
        "O",
        "O",
        0,
        TileColor.VOID,
        CurseType.LETTER,
        metadata={"source": "melmod"},
    )
    assert tile_base_contribution(t) == -1


def test_melmod_void_number_zero_base_score():
    t = Tile(
        0,
        0,
        "9",
        "9",
        0,
        TileColor.VOID,
        CurseType.NUMBER,
        number_value=9,
        metadata={"source": "melmod"},
    )
    assert tile_base_contribution(t) == -9


def test_melmod_void_chess_queen_zero_base_score():
    t = Tile(
        0,
        0,
        "w",
        "?",
        0,
        TileColor.VOID,
        CurseType.CHESS_QUEEN,
        metadata={"source": "melmod", "chess_color": "black"},
    )
    assert tile_base_contribution(t) == -9


def test_melmod_void_chess_king_zero_base_score():
    t = Tile(
        0,
        0,
        "k",
        "?",
        0,
        TileColor.VOID,
        CurseType.CHESS_KING,
        metadata={"source": "melmod", "chess_color": "white"},
    )
    assert tile_base_contribution(t) == -15


def test_red_bonus():
    t = Tile(0, 0, "A", "A", 1, TileColor.RED, CurseType.LETTER)
    assert tile_base_contribution(t) == 2  # 1 + 1


def test_red_note_excludes_scattered_item_tiles():
    item = Tile(
        0,
        4,
        "🎸",
        "G",
        0,
        TileColor.RED,
        CurseType.ITEM,
        metadata={"scattered_item_id": "electric_guitar"},
    )
    letter = Tile(0, 0, "G", "G", 3, TileColor.RED, CurseType.LETTER)
    assert not is_red_note_tile(item)
    assert is_red_note_tile(letter)


def test_red_r_baked_in_base_score_virge():
    """Melmod exports packet.Score; red bonus already included (virge R)."""
    t = Tile(0, 0, "R", "R", 2, TileColor.RED, CurseType.LETTER)
    assert tile_base_contribution(t) == 2


def test_blue_r_baked_in_base_score_foxtrot():
    """Melmod exports packet.Score; blue bonus already included (foxtrot R)."""
    t = Tile(0, 0, "R", "R", 2, TileColor.BLUE, CurseType.LETTER)
    assert tile_base_contribution(t) == 2


def test_consumable_rack_blue_wildcard_no_color_bonus():
    """Placed rack consumable base_score is final; no synthetic +1 blue (swivets)."""
    t = Tile(
        0,
        0,
        "?",
        "?",
        1,
        TileColor.BLUE,
        CurseType.WILDCARD,
        metadata={"source": "consumable_rack"},
    )
    assert tile_base_contribution(t) == 1


def test_was_consumable_blue_wildcard_no_color_bonus():
    """Submit-board placed consumable (was_consumable) scores base 1, not 2."""
    t = Tile(
        0,
        0,
        "?",
        "?",
        1,
        TileColor.BLUE,
        CurseType.WILDCARD,
        metadata={"was_consumable": True},
    )
    assert tile_base_contribution(t) == 1


def test_red_m_manipulated_and_color_baked():
    t = Tile(0, 0, "M", "M", 4, TileColor.RED, CurseType.LETTER)
    assert tile_base_contribution(t) == 4


def test_score_word_path():
    board = _board_from_letters(["cat", "xxx", "xxx", "xxx", "xxx"])
    # c at 0,0 -> index 0; a at 0,1 -> 1; t at 0,2 -> 2
    score, _ = score_word_base(board, [0, 1, 2], "cat")
    assert score == 3.0


def _void_currency_tile(
    row: int,
    col: int,
    char: str,
    *,
    letter: str = "",
) -> Tile:
    return Tile(
        row,
        col,
        char,
        letter or char,
        0,
        TileColor.VOID,
        CurseType.CURRENCY,
        metadata={"source": "melmod"},
    )


def _axolotl_loadout(grid_number: int) -> Loadout:
    return Loadout(
        boss_id="axolotl",
        extras={
            "boss_floor_modification": "10",
            "boss_modifiers": ["axolotl"],
            "boss_modifier_floor_mods": {"axolotl": 10},
            "grid_number": str(grid_number),
        },
    )


def test_void_currency_grid1_axolotl_full_penalty():
    """Melmod void currency on path scores 0 (export base_score is final)."""
    loadout = _axolotl_loadout(1)
    tile = _void_currency_tile(0, 4, "€", letter="E")
    assert tile_base_contribution(tile, loadout=loadout) == 0


def test_void_currency_grid3_axolotl_row1_waived():
    """yappy: grid 2–3, row < 3 → void currency penalty 0."""
    loadout = _axolotl_loadout(3)
    tile = _void_currency_tile(1, 4, "₱", letter="P")
    assert tile_base_contribution(tile, loadout=loadout) == 0


def test_void_currency_grid4_axolotl_row3_full_penalty():
    """Melmod void currency stays 0 regardless of axolotl row/grid."""
    loadout = _axolotl_loadout(4)
    tile = _void_currency_tile(3, 4, "$", letter="S")
    assert tile_base_contribution(tile, loadout=loadout) == 0


def test_void_currency_grid5_axolotl_row1_full_penalty():
    """Melmod void currency stays 0 regardless of axolotl row/grid."""
    loadout = _axolotl_loadout(5)
    tile = _void_currency_tile(1, 2, "฿", letter="B")
    assert tile_base_contribution(tile, loadout=loadout) == 0


def test_void_currency_cedilla_full_penalty():
    """Melmod void ₡ on path scores 0 (no synthetic letter-value penalty)."""
    tile = _void_currency_tile(3, 2, "₡", letter="₡")
    loadout = Loadout(extras={"grid_number": "1"})
    assert tile_base_contribution(tile, loadout=loadout) == 0


def test_void_currency_mole_grid3_path_row2_not_waived():
    """Melmod void currency on path scores 0 even with mole boss modifiers."""
    tile = _void_currency_tile(2, 3, "€", letter="E")
    loadout = Loadout(
        extras={
            "boss_floor_modification": "7",
            "boss_modifiers": ["mole", "toothed_whale"],
            "boss_modifier_floor_mods": {"mole": 7, "toothed_whale": 175},
            "grid_number": "3",
        }
    )
    assert tile_base_contribution(tile, loadout=loadout) == 0


def test_void_currency_offcast_path_dollar():
    """Round log 20260530_160654: void $ on offcast path scores 0 not -15."""
    tile = _void_currency_tile(3, 3, "$", letter="$")
    assert tile_base_contribution(tile, loadout=Loadout(extras={"grid_number": "1"})) == 0


def test_void_currency_axolotl_grid1_multi_boss_bottom_row_waived():
    """kaases: axolotl+mole grid 1 top_first row 4 void $ → penalty 0."""
    tile = _void_currency_tile(4, 2, "$", letter="S")
    loadout = Loadout(
        extras={
            "boss_floor_modification": "7",
            "boss_modifiers": ["axolotl", "mole", "toothed_whale"],
            "boss_modifier_floor_mods": {
                "mole": 7,
                "toothed_whale": 175,
                "axolotl": 5,
            },
            "grid_number": "1",
        }
    )
    assert tile_base_contribution(tile, loadout=loadout) == 0


def test_void_currency_axolotl_grid1_multi_boss_mid_row_waived():
    """kaases: axolotl+mole on grid 1, row < 3 → void currency penalty 0."""
    tile = _void_currency_tile(1, 4, "₭", letter="K")
    loadout = Loadout(
        extras={
            "boss_floor_modification": "7",
            "boss_modifiers": ["axolotl", "mole", "toothed_whale"],
            "boss_modifier_floor_mods": {
                "mole": 7,
                "toothed_whale": 175,
                "axolotl": 5,
            },
            "grid_number": "1",
        }
    )
    assert tile_base_contribution(tile, loadout=loadout) == 0


def _board_from_debug_parse(name: str) -> Board | None:
    path = DEBUG_DIR / name
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    tiles = data.get("tiles", [])
    if len(tiles) != 25:
        return None
    run_state = {
        "board": {
            "source": "melmod",
            "row_order": "top_first",
            "money": 6,
            "tiles": [
                {
                    "row": t["row"],
                    "col": t["col"],
                    "char": t["char"],
                    "letter": t["letter"],
                    "base_score": t["base_score"],
                    "color": t["color"],
                    "curse": t["curse"],
                }
                for t in tiles
            ],
        }
    }
    return parse_board_from_run_state(run_state)


def test_foxtrot_word_score_from_debug_board():
    board = _board_from_debug_parse("parse_20260521_155907.json")
    if board is None:
        return
    score, _ = score_word_base(board, [10, 6, 11, 12, 13, 19, 24], "foxtrot")
    assert score == 18.0


def test_virge_word_score_from_debug_board():
    board = _board_from_debug_parse("parse_20260521_160425.json")
    if board is None:
        return
    score, _ = score_word_base(board, [21, 16, 17, 18, 24], "virge")
    assert score == 10.0


def test_melmod_void_currency_first_on_path_penalty_only():
    """Void $ at path start: no penalty; first void $ at path_index > 0 gets -10."""
    from cursed_words_solver.rules.tile_scoring import initial_tile_scores

    def _cell(r: int, c: int) -> Tile:
        if (r, c) == (0, 0) or (r, c) == (1, 0):
            return Tile(
                r,
                c,
                "$",
                "S",
                0,
                TileColor.VOID,
                CurseType.CURRENCY,
                metadata={"source": "melmod"},
            )
        return Tile(
            r,
            c,
            "a",
            "A",
            1,
            TileColor.COLORLESS,
            CurseType.LETTER,
            metadata={"source": "melmod"},
        )

    board = Board(tiles=[[_cell(r, c) for c in range(5)] for r in range(5)], money=10)
    path_start_dollar = [0, 1, 2]
    scores_start, total_start = initial_tile_scores(board, path_start_dollar, money=10)
    assert scores_start == [0.0, 1.0, 1.0]
    assert total_start == 2.0

    path = [1, 0, 5]
    scores, total = initial_tile_scores(board, path, money=10)
    assert scores == [1.0, -10.0, 0.0]
    assert total == -9.0


def test_pissers_round_log_void_currency_wad_tombstone_cocktail():
    """Round log 20260605_132641: stale F8 embed predicted 188; game scored 168."""
    from cursed_words_solver.loadout import (
        parse_run_state,
        prepare_run_state_dict_for_scoring,
    )
    from cursed_words_solver.rules.pipeline import ScoringPipeline

    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "round_logs"
        / "20260605_132641_801.json"
    )
    if not fixture.exists():
        return
    data = json.loads(fixture.read_text(encoding="utf-8"))
    run_state = prepare_run_state_dict_for_scoring(data["run_state"])
    loadout = parse_run_state(run_state)
    board = parse_board_from_run_state(run_state)
    path = data["actual"]["path"]
    word = data["actual"]["word"]
    pipeline = ScoringPipeline()
    score, _ = pipeline.score(board, path, word, loadout)
    assert score == data["actual"]["score"]
    assert score == 168


def _score_mismatch_fixture(fixture_name: str, expected_score: int) -> None:
    from cursed_words_solver.loadout import (
        parse_run_state,
        prepare_run_state_dict_for_scoring,
    )
    from cursed_words_solver.rules.pipeline import ScoringPipeline

    fixture = (
        Path(__file__).resolve().parent / "fixtures" / "mismatches" / fixture_name
    )
    if not fixture.exists():
        return
    data = json.loads(fixture.read_text(encoding="utf-8"))
    run_state = prepare_run_state_dict_for_scoring(data["run_state_snapshot"])
    loadout = parse_run_state(run_state)
    board = parse_board_from_run_state(run_state)
    path = data["path"]
    word = data["word"]
    pipeline = ScoringPipeline()
    score, _ = pipeline.score(board, path, word, loadout)
    assert score == data["actual_score"]
    assert score == expected_score


def test_fegs_mismatch_void_currency_not_at_path_start():
    """Mismatch 20260605_134008: void ₣ at path start — no init penalty; game 332."""
    _score_mismatch_fixture("20260605_134008.json", 332)


def test_recrafts_mismatch_void_currency_not_dollar():
    """Mismatch 20260605_134100: void ₡ mid-path — no init penalty; game 556."""
    _score_mismatch_fixture("20260605_134100.json", 556)


def test_owsen_mismatch_wad_deferred_sequential_floor():
    """Mismatch 20260605_142843: Wad-deferred grid word bonuses floor per step; game 1758."""
    _score_mismatch_fixture("20260605_142843.json", 1758)


def test_gyrene_mismatch_void_currency_path_start():
    """Mismatch 20260605_143044: void ₲ at path start init -10; game 1196."""
    _score_mismatch_fixture("20260605_143044.json", 1196)


def test_bannerettes_mismatch_mole_grid3_electric_guitar_tier():
    """Mismatch 20260608_153556: mole floor mod must not cap scatter tier; game 3393."""
    _score_mismatch_fixture("20260608_153556.json", 3393)


def test_badger_velveteened_mismatch_electric_guitar_tile_level():
    """Mismatch 20260608_232304: badger must not override path scattered_item_level; game 4479."""
    _score_mismatch_fixture("20260608_232304.json", 4479)


def test_melmod_void_non_dollar_currency_top_row_path_start_penalty():
    """Void ₲ on row 0 at word start gets -10 init; void $ at word start stays 0."""
    from cursed_words_solver.models import Board, CurseType, Tile, TileColor
    from cursed_words_solver.rules.tile_scoring import initial_tile_scores

    def _void_currency_cell(r: int, c: int, glyph: str) -> Tile:
        return Tile(
            r,
            c,
            glyph,
            glyph,
            0,
            TileColor.VOID,
            CurseType.CURRENCY,
            metadata={"source": "melmod"},
        )

    board = Board(
        tiles=[[_void_currency_cell(0, c, "₲" if c == 0 else "a") for c in range(5)] for _ in range(5)],
        money=5,
    )
    for r in range(1, 5):
        for c in range(5):
            board.tiles[r][c] = Tile(
                r, c, "a", "A", 1, TileColor.COLORLESS, CurseType.LETTER,
                metadata={"source": "melmod"},
            )
    path_start = [0, 1, 2, 3, 4, 5]
    scores, _ = initial_tile_scores(board, path_start, money=5)
    assert scores[0] == -10.0

    board2 = Board(
        tiles=[[_void_currency_cell(0, c, "$" if c == 0 else "a") for c in range(5)] for _ in range(5)],
        money=5,
    )
    for r in range(1, 5):
        for c in range(5):
            board2.tiles[r][c] = Tile(
                r, c, "a", "A", 1, TileColor.COLORLESS, CurseType.LETTER,
                metadata={"source": "melmod"},
            )
    scores_d, _ = initial_tile_scores(board2, path_start, money=5)
    assert scores_d[0] == 0.0

    board3 = Board(
        tiles=[[Tile(2, c, "a", "A", 1, TileColor.COLORLESS, CurseType.LETTER,
                   metadata={"source": "melmod"}) for c in range(5)] for _ in range(5)],
        money=5,
    )
    board3.tiles[2][0] = _void_currency_cell(2, 0, "₣")
    path_fegs = [10, 11, 12, 13]
    scores_f, _ = initial_tile_scores(board3, path_fegs, money=5)
    assert scores_f[0] == 0.0
