"""Chess piece movement, blocking, en passant, and king-in-check (wiki: Curses — Chess pieces)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cursed_words_solver.config import GAME_WORDLIST_PATH
from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
from cursed_words_solver.models import Board, CurseType, Loadout, LoadoutItem, Tile, TileColor
from cursed_words_solver.rules.chess_tiles import (
    chess_neighbors,
    chess_side,
    chess_side_known,
    index_of,
    is_chess_capture_step,
    is_square_attacked,
    king_neighbors,
    missing_chess_color_warnings,
)
from cursed_words_solver.rules.scoring_conditions import chess_balanced_colors, chess_take_strict_mode
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.stamp_behaviors import StampSearchFlags, stamp_search_flags
from cursed_words_solver.search import WordSearcher, neighbors_from_tile, path_movement_ok, resolve_letter


def _tile(
    row: int,
    col: int,
    *,
    curse: CurseType = CurseType.LETTER,
    letter: str = "?",
    metadata: dict | None = None,
    color=TileColor.COLORLESS,
) -> Tile:
    return Tile(
        row=row,
        col=col,
        char=letter,
        letter=letter,
        base_score=1.0,
        color=color,
        curse=curse,
        metadata=dict(metadata or {}),
    )


def _chess(
    row: int,
    col: int,
    piece: CurseType,
    side: str,
    *,
    letter: str = "?",
) -> Tile:
    return _tile(
        row,
        col,
        curse=piece,
        letter=letter,
        metadata={"chess_color": side},
    )


def _empty_board() -> Board:
    return Board(tiles=[[_tile(r, c, letter="A") for c in range(5)] for r in range(5)])


def _nbrs(board: Board, start: int, *, flags: StampSearchFlags | None = None) -> list[int]:
    return neighbors_from_tile(board, [start], {start}, flags=flags or StampSearchFlags())


def test_rook_blocked_by_same_color():
    board = _empty_board()
    board.tiles[2][2] = _chess(2, 2, CurseType.CHESS_ROOK, "black")
    board.tiles[2][4] = _chess(2, 4, CurseType.CHESS_PAWN, "black")
    nbrs = _nbrs(board, index_of(2, 2))
    assert index_of(2, 3) in nbrs
    assert index_of(2, 4) not in nbrs


def test_rook_can_take_opposite_color():
    board = _empty_board()
    board.tiles[2][2] = _chess(2, 2, CurseType.CHESS_ROOK, "black")
    board.tiles[2][4] = _chess(2, 4, CurseType.CHESS_PAWN, "white")
    nbrs = _nbrs(board, index_of(2, 2))
    assert index_of(2, 4) in nbrs


def test_rook_passes_through_letters():
    board = _empty_board()
    board.tiles[2][0] = _chess(2, 0, CurseType.CHESS_ROOK, "black")
    nbrs = _nbrs(board, index_of(2, 0))
    assert index_of(2, 4) in nbrs


def test_bishop_blocked_by_visited_same_color():
    board = _empty_board()
    bishop_idx = index_of(0, 3)
    knight_idx = index_of(2, 1)
    beyond_idx = index_of(3, 0)
    board.tiles[0][3] = _chess(0, 3, CurseType.CHESS_BISHOP, "white")
    board.tiles[2][1] = _chess(2, 1, CurseType.CHESS_KNIGHT, "white")
    board.tiles[3][0] = _chess(3, 0, CurseType.CHESS_KNIGHT, "black")
    visited = {bishop_idx, knight_idx}
    nbrs = neighbors_from_tile(board, [bishop_idx], visited)
    assert beyond_idx not in nbrs


def test_bishop_blocked_by_visited_opposite_color():
    board = _empty_board()
    bishop_idx = index_of(0, 0)
    enemy_idx = index_of(2, 2)
    beyond_idx = index_of(4, 4)
    board.tiles[0][0] = _chess(0, 0, CurseType.CHESS_BISHOP, "white")
    board.tiles[2][2] = _chess(2, 2, CurseType.CHESS_PAWN, "black")
    visited = {bishop_idx, enemy_idx}
    nbrs = neighbors_from_tile(board, [bishop_idx], visited)
    assert beyond_idx not in nbrs


def test_knight_blocked_by_same_color_destination():
    board = _empty_board()
    board.tiles[2][2] = _chess(2, 2, CurseType.CHESS_KNIGHT, "black")
    board.tiles[0][3] = _chess(0, 3, CurseType.CHESS_PAWN, "black")
    nbrs = _nbrs(board, index_of(2, 2))
    assert index_of(0, 3) not in nbrs


def test_knight_can_take_opposite_color():
    board = _empty_board()
    board.tiles[2][2] = _chess(2, 2, CurseType.CHESS_KNIGHT, "black")
    board.tiles[0][3] = _chess(0, 3, CurseType.CHESS_PAWN, "white")
    nbrs = _nbrs(board, index_of(2, 2))
    assert index_of(0, 3) in nbrs


def test_pawn_forward_from_home_rank():
    board = _empty_board()
    board.tiles[3][2] = _chess(3, 2, CurseType.CHESS_PAWN, "black")
    nbrs = _nbrs(board, index_of(3, 2))
    assert index_of(4, 2) in nbrs
    assert index_of(2, 2) not in nbrs


def test_pawn_at_top_row_no_double_move():
    """Regression: black pawn on row 0 is not on home rank — no 2-square jump to X."""
    board = _empty_board()
    board.tiles[0][3] = _chess(0, 3, CurseType.CHESS_PAWN, "black")
    board.tiles[1][3] = _tile(1, 3, curse=CurseType.NUMBER, letter="7")
    board.tiles[2][3] = _tile(2, 3, letter="X")
    nbrs = _nbrs(board, index_of(0, 3))
    assert index_of(1, 3) in nbrs
    assert index_of(2, 3) not in nbrs


def test_oxo_path_invalid_after_home_rank_fix():
    """Regression: oxo path [3,13,18] used illegal pawn double-move from melmod board."""
    from cursed_words_solver.rules.stamp_behaviors import stamp_search_flags_mask
    from cursed_words_solver.search import path_movement_ok

    fixture = Path(__file__).parent / "fixtures" / "boards" / "oxo_pawn_double_move.json"
    data = json.loads(fixture.read_text(encoding="utf-8"))
    board = parse_board_from_run_state(data)
    loadout = parse_run_state(data)
    assert board is not None
    flags = stamp_search_flags_mask(loadout)
    assert not path_movement_ok(board, [3, 13, 18], flags=flags)


def test_pawn_no_diagonal_without_capture():
    board = _empty_board()
    board.tiles[2][2] = _chess(2, 2, CurseType.CHESS_PAWN, "black")
    nbrs = _nbrs(board, index_of(2, 2))
    assert index_of(3, 1) not in nbrs
    assert index_of(3, 3) not in nbrs


def test_pawn_diagonal_capture():
    board = _empty_board()
    board.tiles[2][2] = _chess(2, 2, CurseType.CHESS_PAWN, "black")
    board.tiles[3][3] = _chess(3, 3, CurseType.CHESS_PAWN, "white")
    nbrs = _nbrs(board, index_of(2, 2))
    assert index_of(3, 3) in nbrs
    assert is_chess_capture_step(board, index_of(2, 2), index_of(3, 3))
    assert not is_chess_capture_step(board, index_of(2, 2), index_of(3, 2))


def test_is_chess_capture_step_pawn_forward_not_capture():
    board = _empty_board()
    board.tiles[4][0] = _chess(4, 0, CurseType.CHESS_PAWN, "white")
    board.tiles[3][0] = _tile(3, 0, letter="O")
    assert not is_chess_capture_step(board, index_of(4, 0), index_of(3, 0))


def test_en_passant_black_pawn():
    board = _empty_board()
    board.tiles[1][1] = _chess(1, 1, CurseType.CHESS_PAWN, "black")
    board.tiles[1][2] = _chess(1, 2, CurseType.CHESS_PAWN, "white")
    nbrs = _nbrs(board, index_of(1, 1))
    assert index_of(2, 2) in nbrs


def test_en_passant_white_pawn():
    board = _empty_board()
    board.tiles[3][2] = _chess(3, 2, CurseType.CHESS_PAWN, "white")
    board.tiles[3][3] = _chess(3, 3, CurseType.CHESS_PAWN, "black")
    nbrs = _nbrs(board, index_of(3, 2))
    assert index_of(2, 3) in nbrs


def test_king_cannot_move_into_check():
    board = _empty_board()
    king_idx = index_of(2, 2)
    board.tiles[2][2] = _chess(2, 2, CurseType.CHESS_KING, "black")
    board.tiles[0][2] = _chess(0, 2, CurseType.CHESS_ROOK, "white")
    nbrs = _nbrs(board, king_idx)
    assert index_of(1, 2) not in nbrs
    assert index_of(3, 3) in nbrs


ADMIXES_FIXTURE = (
    Path(__file__).parent / "fixtures" / "boards" / "20260616_admixes_king_wrap_check.json"
)
ADMIXES_PATH = [6, 10, 16, 12, 17, 22, 13]


def _admixes_board_and_loadout():
    data = json.loads(ADMIXES_FIXTURE.read_text(encoding="utf-8"))
    board = parse_board_from_run_state(data)
    loadout = parse_run_state(data)
    assert board is not None
    return board, loadout


def test_admixes_king_cannot_step_into_wrap_pawn_check():
    """Hungry Snake: white pawn (3,4) threatens (2,0) via wrap; king may not step to D."""
    board, loadout = _admixes_board_and_loadout()
    flags = stamp_search_flags(loadout)
    assert flags.horizontal_wrap is True
    visited = {index_of(1, 1)}
    assert is_square_attacked(
        board, 2, 0, "white", visited, horizontal_wrap=True
    )
    nbrs = neighbors_from_tile(board, [index_of(1, 1)], visited, flags=flags)
    assert index_of(2, 0) not in nbrs
    assert not path_movement_ok(board, ADMIXES_PATH, flags=flags)


def test_admixes_not_in_search(tmp_path):
    board, loadout = _admixes_board_and_loadout()
    wl = tmp_path / "words.txt"
    wl.write_text("admixes\n", encoding="utf-8")
    searcher = WordSearcher(
        dictionary=WordDictionary(wl),
        min_len=3,
        max_len=15,
        time_budget=5.0,
    )
    results = searcher.find_best_words(board, loadout, top_n=20)
    paths = [r.path for r in results]
    assert ADMIXES_PATH not in paths


def test_pawn_wrap_diagonal_capture_with_hungry_snake():
    """White pawn at (3,4) can capture at (2,0) when Hungry Snake wrap is active."""
    board = _empty_board()
    board.tiles[3][4] = _chess(3, 4, CurseType.CHESS_PAWN, "white")
    board.tiles[2][0] = _chess(2, 0, CurseType.CHESS_KNIGHT, "black")
    flags = stamp_search_flags(
        Loadout(stamps=[LoadoutItem(id="hungry_snake", name="Hungry Snake", kind="stamp")])
    )
    nbrs = _nbrs(board, index_of(3, 4), flags=flags)
    assert index_of(2, 0) in nbrs


def test_pawn_no_wrap_diagonal_capture_without_hungry_snake():
    """Without Hungry Snake, pawn at (3,4) cannot capture at (2,0)."""
    board = _empty_board()
    board.tiles[3][4] = _chess(3, 4, CurseType.CHESS_PAWN, "white")
    board.tiles[2][0] = _chess(2, 0, CurseType.CHESS_KNIGHT, "black")
    nbrs = _nbrs(board, index_of(3, 4))
    assert index_of(2, 0) not in nbrs


DROWSINESS_FIXTURE = (
    Path(__file__).parent / "fixtures" / "boards" / "20260529_drowsiness_wrap.json"
)
DROWSINESS_PREFIX = [2, 6, 17, 5]
DROWSINESS_PATH = [2, 6, 17, 5, 0, 1, 7, 13, 18, 9]


def _drowsiness_board_and_loadout():
    data = json.loads(DROWSINESS_FIXTURE.read_text(encoding="utf-8"))
    board = parse_board_from_run_state(data)
    loadout = parse_run_state(data)
    assert board is not None
    return board, loadout


def test_drowsiness_king_cannot_step_to_wrap_attacked_square():
    """Hungry Snake: white bishop (1,4) threatens (0,0) via wrap diagonal."""
    board, loadout = _drowsiness_board_and_loadout()
    flags = stamp_search_flags(loadout)
    assert flags.horizontal_wrap is True
    visited = set(DROWSINESS_PREFIX)
    nbrs = neighbors_from_tile(board, DROWSINESS_PREFIX, visited, flags=flags)
    assert index_of(0, 0) not in nbrs
    assert is_square_attacked(
        board, 0, 0, "white", visited, horizontal_wrap=True
    )


def test_drowsiness_king_step_allowed_without_hungry_snake():
    board, loadout = _drowsiness_board_and_loadout()
    loadout = Loadout(
        stickers=list(loadout.stickers),
        stamps=[s for s in loadout.stamps if s.id != "hungry_snake"],
        extras=dict(loadout.extras or {}),
    )
    flags = stamp_search_flags(loadout)
    assert flags.horizontal_wrap is False
    visited = set(DROWSINESS_PREFIX)
    nbrs = neighbors_from_tile(board, DROWSINESS_PREFIX, visited, flags=flags)
    assert index_of(0, 0) in nbrs


def test_drowsiness_not_in_search_with_hungry_snake(tmp_path):
    board, loadout = _drowsiness_board_and_loadout()
    wl = tmp_path / "words.txt"
    wl.write_text("drowsiness\n", encoding="utf-8")
    searcher = WordSearcher(
        dictionary=WordDictionary(wl),
        min_len=3,
        max_len=15,
        time_budget=5.0,
    )
    results = searcher.find_best_words(board, loadout, top_n=20)
    paths = [r.path for r in results]
    assert DROWSINESS_PATH not in paths


STYROFOAMS_FIXTURE = (
    Path(__file__).parent / "fixtures" / "boards" / "20260529_styrofoams_king_check.json"
)
STYROFOAMS_PATH = [18, 5, 14, 8, 13, 12, 19, 23, 22, 21]
STYROFOAMS_PREFIX = [18, 5, 14, 8, 13, 12, 19]


def _styrofoams_board_and_loadout():
    data = json.loads(STYROFOAMS_FIXTURE.read_text(encoding="utf-8"))
    board = parse_board_from_run_state(data)
    loadout = parse_run_state(data)
    assert board is not None
    return board, loadout


def test_styrofoams_king_cannot_step_into_check():
    """Visited black rook (1,3) still controls (4,3); king at (3,4) may not step there."""
    board, loadout = _styrofoams_board_and_loadout()
    flags = stamp_search_flags(loadout)
    assert flags.horizontal_wrap is True
    visited = set(STYROFOAMS_PREFIX)
    king_idx = index_of(3, 4)
    assert is_square_attacked(
        board, 4, 3, "black", visited, horizontal_wrap=True
    )
    nbrs = neighbors_from_tile(board, STYROFOAMS_PREFIX, visited, flags=flags)
    assert index_of(4, 3) not in nbrs
    assert index_of(4, 3) not in king_neighbors(
        board,
        king_idx,
        visited,
        moving_side="white",
        horizontal_wrap=True,
    )


def test_styrofoams_path_not_in_search(tmp_path):
    board, loadout = _styrofoams_board_and_loadout()
    wl = tmp_path / "words.txt"
    wl.write_text("styrofoams\n", encoding="utf-8")
    searcher = WordSearcher(
        dictionary=WordDictionary(wl),
        min_len=3,
        max_len=15,
        time_budget=5.0,
    )
    results = searcher.find_best_words(board, loadout, top_n=20)
    paths = [r.path for r in results]
    assert STYROFOAMS_PATH not in paths


def test_king_of_the_bridge_allows_ally_take():
    board = _empty_board()
    board.tiles[2][2] = _chess(2, 2, CurseType.CHESS_KNIGHT, "black")
    board.tiles[0][3] = _chess(0, 3, CurseType.CHESS_PAWN, "black")
    flags = stamp_search_flags(
        Loadout(stamps=[LoadoutItem(id="king_of_the_bridge", name="King Of The Bridge", kind="stamp")])
    )
    nbrs = _nbrs(board, index_of(2, 2), flags=flags)
    assert index_of(0, 3) in nbrs


def test_television_adds_item_neighbors_for_king():
    board = _empty_board()
    board.tiles[2][2] = _chess(2, 2, CurseType.CHESS_KING, "black")
    item_idx = index_of(4, 4)
    board.tiles[4][4] = _tile(4, 4, curse=CurseType.ITEM, letter="?")
    flags = stamp_search_flags(
        Loadout(stamps=[LoadoutItem(id="television", name="Television", kind="stamp")])
    )
    nbrs = _nbrs(board, index_of(2, 2), flags=flags)
    assert item_idx in nbrs


def test_parse_chess_color_from_run_state():
    data = {
        "board": {
            "row_order": "top_first",
            "tiles": [
                {
                    "row": 0,
                    "col": 0,
                    "char": "?",
                    "letter": "?",
                    "base_score": 3,
                    "color": "colorless",
                    "curse": "chess_knight",
                    "chess_color": "white",
                    "active": True,
                },
            ]
            + [
                {
                    "row": r,
                    "col": c,
                    "char": "A",
                    "letter": "A",
                    "base_score": 1,
                    "color": "colorless",
                    "curse": "letter",
                    "active": True,
                }
                for r in range(5)
                for c in range(5)
                if not (r == 0 and c == 0)
            ],
        }
    }
    board = parse_board_from_run_state(data)
    assert board is not None
    tile = board.get(0, 0)
    assert tile is not None
    assert chess_side(tile) == "white"


def test_chess_balanced_colors_with_metadata():
    board = _empty_board()
    board.tiles[0][0] = _chess(0, 0, CurseType.CHESS_PAWN, "black")
    board.tiles[0][1] = _chess(0, 1, CurseType.CHESS_PAWN, "white")
    path = [index_of(0, 0), index_of(0, 1)]
    assert chess_balanced_colors(board, path)


def test_is_square_attacked_by_rook():
    board = _empty_board()
    board.tiles[0][0] = _chess(0, 0, CurseType.CHESS_ROOK, "white")
    assert is_square_attacked(board, 0, 4, "white", set())
    assert not is_square_attacked(board, 4, 4, "white", set())


def test_chess_neighbors_dispatches_pawn():
    board = _empty_board()
    board.tiles[4][2] = _chess(4, 2, CurseType.CHESS_PAWN, "white")
    flags = StampSearchFlags()
    nbrs = chess_neighbors(board, [index_of(4, 2)], {index_of(4, 2)}, flags)
    assert index_of(3, 2) in nbrs


def test_white_pawn_cannot_move_down_to_letter():
    board = _empty_board()
    board.tiles[3][3] = _chess(3, 3, CurseType.CHESS_PAWN, "white")
    visited = {index_of(3, 2), index_of(3, 3)}
    nbrs = neighbors_from_tile(board, [index_of(3, 2), index_of(3, 3)], visited)
    assert index_of(4, 3) not in nbrs
    assert index_of(2, 3) in nbrs


def test_black_pawn_can_move_down_to_letter():
    board = _empty_board()
    board.tiles[3][3] = _chess(3, 3, CurseType.CHESS_PAWN, "black")
    visited = {index_of(3, 2), index_of(3, 3)}
    nbrs = neighbors_from_tile(board, [index_of(3, 2), index_of(3, 3)], visited)
    assert index_of(4, 3) in nbrs


def test_missing_chess_color_does_not_allow_pawn_forward():
    board = _empty_board()
    board.tiles[3][3] = _tile(3, 3, curse=CurseType.CHESS_PAWN, letter="?")
    visited = {index_of(3, 2), index_of(3, 3)}
    nbrs = neighbors_from_tile(board, [index_of(3, 2), index_of(3, 3)], visited)
    assert index_of(4, 3) not in nbrs
    assert index_of(2, 3) not in nbrs


def test_missing_chess_color_warning():
    board = _empty_board()
    board.tiles[3][3] = _tile(3, 3, curse=CurseType.CHESS_PAWN, letter="?")
    warnings = missing_chess_color_warnings(board)
    assert any("(3,3)" in w for w in warnings)


def test_rufiyaa_not_found_on_melmod_snapshot(tmp_path):
    fixture = Path(__file__).parent / "fixtures" / "rufiyaa_chess_blocking.json"
    data = json.loads(fixture.read_text(encoding="utf-8"))
    board = parse_board_from_run_state(data)
    assert board is not None

    invalid_path = [23, 11, 8, 3, 15, 6, 5]
    prefix_to_bishop = invalid_path[:4]
    visited = set(prefix_to_bishop)
    nbrs = neighbors_from_tile(board, prefix_to_bishop, visited)
    assert index_of(3, 0) not in nbrs

    wl = tmp_path / "words.txt"
    wl.write_text("rufiyaa\n", encoding="utf-8")
    searcher = WordSearcher(
        dictionary=WordDictionary(wl),
        min_len=3,
        max_len=15,
        time_budget=5.0,
    )
    results = searcher.find_best_words(board, top_n=20)
    words = [r.word for r in results]
    assert "rufiyaa" not in words
    assert invalid_path not in [r.path for r in results]


def test_adjigo_invalid_on_snapshot_board(tmp_path):
    fixture = Path(__file__).parent / "fixtures" / "chess_white_pawn_adjigo.json"
    data = json.loads(fixture.read_text(encoding="utf-8"))
    board = parse_board_from_run_state(data)
    assert board is not None

    pawn = board.get(3, 3)
    assert pawn is not None
    assert chess_side_known(pawn)
    assert chess_side(pawn) == "white"

    invalid_path = [22, 16, 21, 17, 18, 23]
    visited = set(invalid_path[:-1])
    nbrs = neighbors_from_tile(board, invalid_path[:-1], visited)
    assert invalid_path[-1] not in nbrs

    wl = tmp_path / "words.txt"
    wl.write_text("adjigo\n", encoding="utf-8")
    searcher = WordSearcher(
        dictionary=WordDictionary(wl),
        min_len=3,
        max_len=15,
        time_budget=5.0,
    )
    results = searcher.find_best_words(board, top_n=20)
    paths = [r.path for r in results]
    assert invalid_path not in paths


MARKKAA_PATH = [23, 11, 8, 12, 16, 5, 6, 10]
RUFIYAA_FIXTURE = Path(__file__).parent / "fixtures" / "rufiyaa_chess_blocking.json"
FALDSTOOL_FIXTURE = (
    Path(__file__).parent / "fixtures" / "mismatches" / "20260524_002926_faldstool.json"
)
FALDSTOOL_PATH = [18, 14, 5, 2, 21, 12, 11, 13, 7]
COANNEXES_FIXTURE = (
    Path(__file__).parent / "fixtures" / "mismatches" / "20260524_005127.json"
)
FASCIITIS_FIXTURE = (
    Path(__file__).parent / "fixtures" / "mismatches" / "20260524_024045.json"
)
KNAURRING_FIXTURE = (
    Path(__file__).parent / "fixtures" / "mismatches" / "20260524_034007.json"
)
SKOKIAANS_FIXTURE = (
    Path(__file__).parent / "fixtures" / "mismatches" / "20260524_035145.json"
)


def _markkaa_board_and_loadout():
    data = json.loads(RUFIYAA_FIXTURE.read_text(encoding="utf-8"))
    board = parse_board_from_run_state(data)
    loadout = parse_run_state(data)
    assert board is not None
    return board, loadout


def _faldstool_board_and_loadout():
    data = json.loads(FALDSTOOL_FIXTURE.read_text(encoding="utf-8"))
    run_state = dict(data.get("run_state_snapshot") or {})
    extras = dict(run_state.get("extras") or {})
    extras.update(data.get("extras_snapshot") or {})
    if extras:
        run_state["extras"] = extras
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    assert board is not None
    return board, loadout


def _coannexes_board_and_loadout():
    data = json.loads(COANNEXES_FIXTURE.read_text(encoding="utf-8"))
    run_state = dict(data.get("run_state_snapshot") or {})
    extras = dict(run_state.get("extras") or {})
    extras.update(data.get("extras_snapshot") or {})
    if extras:
        run_state["extras"] = extras
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    assert board is not None
    return board, loadout


def _fasciitis_board_and_loadout():
    data = json.loads(FASCIITIS_FIXTURE.read_text(encoding="utf-8"))
    run_state = dict(data.get("run_state_snapshot") or {})
    extras = dict(run_state.get("extras") or {})
    extras.update(data.get("extras_snapshot") or {})
    if extras:
        run_state["extras"] = extras
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    assert board is not None
    return board, loadout


def _knaurring_board_and_loadout():
    data = json.loads(KNAURRING_FIXTURE.read_text(encoding="utf-8"))
    run_state = dict(data.get("run_state_snapshot") or {})
    extras = dict(run_state.get("extras") or {})
    extras.update(data.get("extras_snapshot") or {})
    if extras:
        run_state["extras"] = extras
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    assert board is not None
    return board, loadout


def _skokiaans_board_and_loadout():
    data = json.loads(SKOKIAANS_FIXTURE.read_text(encoding="utf-8"))
    run_state = dict(data.get("run_state_snapshot") or {})
    extras = dict(run_state.get("extras") or {})
    extras.update(data.get("extras_snapshot") or {})
    if extras:
        run_state["extras"] = extras
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    assert board is not None
    return board, loadout


def test_markkaa_eight_tile_scores_180_with_movie_camera():
    """8-tile markkaa path: infer takes for Movie Camera when melmod take flags absent."""
    board, loadout = _markkaa_board_and_loadout()
    flags = stamp_search_flags(loadout)
    letters = "".join(
        resolve_letter(board.get_by_index(i), j, flags=flags)
        for j, i in enumerate(MARKKAA_PATH)
    )
    pipeline = ScoringPipeline()
    score, bd, _ = pipeline.score_with_trace(
        board, MARKKAA_PATH, letters.lower(), loadout
    )
    assert score == 198.0
    effects = bd["pipeline"]["effects"]
    assert any("+9 word (Movie Camera:" in e for e in effects)


def test_movie_camera_strict_when_melmod_take_metadata():
    """Melmod take flags on path switch Movie Camera to strict piece-value takes."""
    board, loadout = _markkaa_board_and_loadout()
    flags = stamp_search_flags(loadout)
    letters = "".join(
        resolve_letter(board.get_by_index(i), j, flags=flags)
        for j, i in enumerate(MARKKAA_PATH)
    )
    pipeline = ScoringPipeline()
    score_inferred, _, _ = pipeline.score_with_trace(
        board, MARKKAA_PATH, letters.lower(), loadout
    )
    assert score_inferred == 198.0
    assert not chess_take_strict_mode(board, MARKKAA_PATH, strict_requested=True)

    board.get_by_index(MARKKAA_PATH[2]).metadata["take"] = True
    assert chess_take_strict_mode(board, MARKKAA_PATH, strict_requested=True)
    score_strict, bd_strict, _ = pipeline.score_with_trace(
        board, MARKKAA_PATH, letters.lower(), loadout
    )
    assert score_strict >= score_inferred
    effects = bd_strict["pipeline"]["effects"]
    assert any("+9 word (Movie Camera:" in e for e in effects)


def test_faldstool_movie_camera_after_full_moon_capture():
    """Capture after Full Moon teleport uses boosted from-tile base for Movie Camera."""
    board, loadout = _faldstool_board_and_loadout()
    pipeline = ScoringPipeline()
    score, bd, _ = pipeline.score_with_trace(
        board, FALDSTOOL_PATH, "faldstool", loadout
    )
    assert score == 280.0
    effects = bd["pipeline"]["effects"]
    assert any("+9 word (Movie Camera:" in e for e in effects)
    assert any("+16 word (2 take(s))" in e for e in effects)


def test_coannexes_movie_camera_full_moon_chain():
    """Later FM capture counts for Movie Camera; earlier take across letters does not."""
    board, loadout = _coannexes_board_and_loadout()
    data = json.loads(COANNEXES_FIXTURE.read_text(encoding="utf-8"))
    path = data["path"]
    pipeline = ScoringPipeline()
    score, bd, _ = pipeline.score_with_trace(
        board, path, "coannexes", loadout
    )
    assert score == 316.0
    effects = bd["pipeline"]["effects"]
    assert any("+9 word (Movie Camera:" in e for e in effects)
    assert any("+24 word (3 take(s))" in e for e in effects)


def test_fasciitis_movie_camera_carousel_chess_chain():
    """Carousel + FM path: rook take and boosted knight FM capture count for Movie Camera L3."""
    board, loadout = _fasciitis_board_and_loadout()
    data = json.loads(FASCIITIS_FIXTURE.read_text(encoding="utf-8"))
    path = data["path"]
    pipeline = ScoringPipeline()
    score, bd, _ = pipeline.score_with_trace(
        board, path, "fasciitis", loadout
    )
    assert score == 1548.0
    effects = bd["pipeline"]["effects"]
    assert any("+46 word (Movie Camera:" in e for e in effects)
    assert any("+24 word (3 take(s))" in e for e in effects)


def test_knaurring_movie_camera_carousel_first_take():
    """Queen capture on doubled rook: Movie Camera credits landing base + attacker piece."""
    board, loadout = _knaurring_board_and_loadout()
    data = json.loads(KNAURRING_FIXTURE.read_text(encoding="utf-8"))
    path = data["path"]
    pipeline = ScoringPipeline()
    score, bd, _ = pipeline.score_with_trace(
        board, path, "knaurring", loadout
    )
    assert score == 3464.0
    effects = bd["pipeline"]["effects"]
    assert any("+80 word (Movie Camera:" in e for e in effects)
    assert any("+40 word (5 take(s))" in e for e in effects)


def test_skokiaans_movie_camera_carousel_chain():
    """Four captures, Movie Camera L3: sum three largest piece values (FM chain + letter gap)."""
    board, loadout = _skokiaans_board_and_loadout()
    data = json.loads(SKOKIAANS_FIXTURE.read_text(encoding="utf-8"))
    path = data["path"]
    pipeline = ScoringPipeline()
    score, bd, _ = pipeline.score_with_trace(
        board, path, "skokiaans", loadout
    )
    assert score == 4380.0
    effects = bd["pipeline"]["effects"]
    assert any("+101 word (Movie Camera:" in e for e in effects)
    assert any("+32 word (4 take(s))" in e for e in effects)


def test_hungry_snake_wrap_enables_third_rook_take():
    """White rook at (0,1) captures (0,3) through wrap when Hungry Snake is equipped."""
    board = _empty_board()
    board.tiles[1][1] = _chess(1, 1, CurseType.CHESS_BISHOP, "white")
    board.tiles[0][2] = _chess(0, 2, CurseType.CHESS_ROOK, "black")
    board.tiles[0][1] = _chess(0, 1, CurseType.CHESS_ROOK, "white")
    board.tiles[0][3] = _chess(0, 3, CurseType.CHESS_ROOK, "black")
    path = [index_of(1, 1), index_of(0, 2), index_of(0, 1), index_of(0, 3)]
    lo = Loadout(
        stamps=[LoadoutItem(id="hungry_snake", name="Hungry Snake", level=1)],
        extras={
            "pin_effect": "super_8",
            "pin_right_variable": "8",
            "movie_camera_word_score_bonus": "20",
        },
    )
    from cursed_words_solver.rules.scoring_conditions import chess_take_path_positions

    without = Loadout(extras={"pin_effect": "super_8", "pin_right_variable": "8"})
    assert chess_take_path_positions(board, path, loadout=without) == [1, 2]
    assert chess_take_path_positions(board, path, loadout=lo) == [1, 2, 3]

    pipeline = ScoringPipeline()
    score, bd = pipeline.score(board, path, "xxxx", lo)
    assert bd["pipeline"]["word_score"] == 24.0
    assert score == 24.0 + sum(bd["pipeline"]["tile_scores"])


def test_letter_take_metadata_not_counted_as_chess_take():
    """Melmod take flag on a letter tile must not count toward Super 8."""
    board = _empty_board()
    board.tiles[0][3] = _chess(0, 3, CurseType.CHESS_BISHOP, "white")
    board.tiles[2][0] = _chess(2, 0, CurseType.CHESS_KNIGHT, "black", letter="?")
    board.tiles[3][2] = _chess(3, 2, CurseType.CHESS_ROOK, "white")
    board.tiles[1][2] = _tile(1, 2, letter="A", metadata={"take": True})
    path = [
        index_of(0, 3),
        index_of(2, 0),
        index_of(3, 2),
        index_of(1, 2),
    ]
    from cursed_words_solver.rules.scoring_conditions import chess_take_path_positions

    lo = Loadout(extras={"pin_effect": "super_8", "pin_right_variable": "8"})
    takes = chess_take_path_positions(board, path, loadout=lo)
    assert 3 not in takes
    assert takes == [2]


@pytest.mark.skipif(
    not GAME_WORDLIST_PATH.exists() or GAME_WORDLIST_PATH.stat().st_size < 1024,
    reason="game wordlist required",
)
def test_markkaa_extension_found_in_search():
    """Regression: trailing WN after AA on markkaa path (180 pts, not 7-tile 170)."""
    board, loadout = _markkaa_board_and_loadout()
    d = WordDictionary(GAME_WORDLIST_PATH)
    searcher = WordSearcher(
        dictionary=d,
        min_len=3,
        max_len=15,
        time_budget=15.0,
    )
    results = searcher.find_best_words(board, loadout, top_n=30)
    match = [r for r in results if r.path == MARKKAA_PATH]
    assert match, "expected 8-tile markkaa path in search results"
    assert match[0].score >= 180.0
    effects = match[0].breakdown.get("pipeline", {}).get("effects", [])
    assert any("Movie Camera:" in e for e in effects)


def test_neighbors_mask_matches_neighbors_from_tile_on_chess_boards():
    """Bitboard neighbor API must match list API on representative fixtures."""
    from cursed_words_solver.graph_bitboard import build_board_graph_context, iter_mask
    from cursed_words_solver.search import neighbors_from_tile, neighbors_mask

    boards = []
    board, _ = _markkaa_board_and_loadout()
    boards.append(board)
    if RUFIYAA_FIXTURE.exists():
        data = json.loads(RUFIYAA_FIXTURE.read_text(encoding="utf-8"))
        rb = parse_board_from_run_state(data)
        if rb is not None:
            boards.append(rb)

    for board in boards:
        ctx = build_board_graph_context(board)
        for start in range(25):
            if not board.is_active_index(start):
                continue
            for visited_bits in (1 << start, (1 << start) | (1 << ((start + 1) % 25))):
                path = [start]
                expected = neighbors_from_tile(board, path, visited_bits)
                mask = neighbors_mask(
                    board, visited_bits, cell_id=start, graph_ctx=ctx
                )
                assert sorted(expected) == sorted(iter_mask(mask))
