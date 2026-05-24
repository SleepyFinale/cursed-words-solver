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
    missing_chess_color_warnings,
)
from cursed_words_solver.rules.scoring_conditions import chess_balanced_colors, chess_take_strict_mode
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.stamp_behaviors import StampSearchFlags, stamp_search_flags
from cursed_words_solver.search import WordSearcher, neighbors_from_tile, resolve_letter


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
    board.tiles[0][2] = _chess(0, 2, CurseType.CHESS_PAWN, "black")
    nbrs = _nbrs(board, index_of(0, 2))
    assert index_of(1, 2) in nbrs
    assert index_of(2, 2) in nbrs


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


def test_markkaa_eight_tile_scores_180_with_movie_camera():
    """8-tile markkaa path: infer takes for Movie Camera when melmod take flags absent."""
    board, loadout = _markkaa_board_and_loadout()
    flags = stamp_search_flags(loadout)
    letters = "".join(
        resolve_letter(board.get_by_index(i), j, flags=flags)
        for j, i in enumerate(MARKKAA_PATH)
    )
    pipeline = ScoringPipeline()
    score, _, trace = pipeline.score_with_trace(
        board, MARKKAA_PATH, letters.lower(), loadout
    )
    assert score == 180.0
    details = [t.get("detail", "") for t in trace]
    assert any("+3 word (first 1 take piece value)" in d for d in details)


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
    assert score_inferred == 180.0
    assert not chess_take_strict_mode(board, MARKKAA_PATH, strict_requested=True)

    board.get_by_index(MARKKAA_PATH[2]).metadata["take"] = True
    assert chess_take_strict_mode(board, MARKKAA_PATH, strict_requested=True)
    score_strict, _, trace = pipeline.score_with_trace(
        board, MARKKAA_PATH, letters.lower(), loadout
    )
    assert score_strict > score_inferred
    details = [t.get("detail", "") for t in trace]
    assert any("+9 word (first 1 take piece value)" in d for d in details)


def test_faldstool_movie_camera_after_full_moon_capture():
    """Capture after Full Moon teleport uses boosted from-tile base for Movie Camera."""
    board, loadout = _faldstool_board_and_loadout()
    pipeline = ScoringPipeline()
    score, _, trace = pipeline.score_with_trace(
        board, FALDSTOOL_PATH, "faldstool", loadout
    )
    assert score == 280.0
    details = [t.get("detail", "") for t in trace]
    assert any("+9 word (first 2 take piece value)" in d for d in details)
    assert any("+16 word (2 take(s))" in d for d in details)


def test_coannexes_movie_camera_full_moon_chain():
    """Later FM capture counts for Movie Camera; earlier take across letters does not."""
    board, loadout = _coannexes_board_and_loadout()
    data = json.loads(COANNEXES_FIXTURE.read_text(encoding="utf-8"))
    path = data["path"]
    pipeline = ScoringPipeline()
    score, _, trace = pipeline.score_with_trace(
        board, path, "coannexes", loadout
    )
    assert score == 316.0
    details = [t.get("detail", "") for t in trace]
    assert any("+9 word (first 2 take piece value)" in d for d in details)
    assert any("+24 word (3 take(s))" in d for d in details)


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
    assert any("first 1 take piece value" in e for e in effects)
