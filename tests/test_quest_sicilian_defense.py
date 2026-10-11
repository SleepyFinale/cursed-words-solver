"""Knight Time (SicilianDefense) movement override."""

import json
from pathlib import Path

from cursed_words_solver.dictionary import WordDictionary
from cursed_words_solver.models import Board, CurseType, Loadout, Tile, TileColor
from cursed_words_solver.rules.stamp_behaviors import stamp_search_flags
from cursed_words_solver.search import WordSearcher, path_movement_ok
from cursed_words_solver.suggestion import f8_should_block_save, filter_submittable_results, path_is_submittable, save_last_suggestion
from tests.helpers.boards import _make_wordlist


def _letter_tile(r: int, c: int, ch: str) -> Tile:
    return Tile(
        row=r,
        col=c,
        char=ch,
        letter=ch,
        base_score=1,
        color=TileColor.COLORLESS,
        curse=CurseType.LETTER,
    )


def _board_knight_cat() -> Board:
    """CAT on indices 0→7→10 (knight moves only)."""
    grid = [[_letter_tile(r, c, "q") for c in range(5)] for r in range(5)]
    grid[0][0] = _letter_tile(0, 0, "c")
    grid[1][2] = _letter_tile(1, 2, "a")
    grid[2][0] = _letter_tile(2, 0, "t")
    return Board(tiles=grid, money=0)


def _chess(idx: int, piece: CurseType, color: str = "white") -> Tile:
    row, col = divmod(idx, 5)
    return Tile(
        row=row,
        col=col,
        char="k",
        letter="k",
        base_score=0,
        color=TileColor.COLORLESS,
        curse=piece,
        metadata={"chess_color": color},
    )


def test_knight_time_filter_needs_movement_context_after_search(tmp_path: Path) -> None:
    """Post-search filter must pass loadout for quest movement (no global)."""
    wl = _make_wordlist(tmp_path)
    dictionary = WordDictionary(wl)
    board = _board_knight_cat()
    loadout = Loadout(extras={"challenge_game_class": "SicilianDefense"})
    searcher = WordSearcher(
        dictionary=dictionary,
        min_len=3,
        max_len=6,
        time_budget=3.0,
        search_workers=1,
    )
    results = searcher.find_best_words(board, loadout, top_n=3)
    assert results

    kept = filter_submittable_results(board, results, loadout, dictionary)
    assert kept


def test_knight_time_f8_should_not_block_save_after_search(tmp_path: Path) -> None:
    """f8_should_block_save must validate knight movement without a global loadout."""
    wl = _make_wordlist(tmp_path)
    dictionary = WordDictionary(wl)
    board = _board_knight_cat()
    loadout = Loadout(extras={"challenge_game_class": "SicilianDefense"})
    searcher = WordSearcher(
        dictionary=dictionary,
        min_len=3,
        max_len=6,
        time_budget=3.0,
        search_workers=1,
    )
    results = searcher.find_best_words(board, loadout, top_n=1)
    assert results
    top = results[0]

    blocked, reason = f8_should_block_save(
        gather_succeeded=True,
        loadout=loadout,
        board=board,
        path=top.path,
        dictionary=dictionary,
        scoring_word=top.word,
        min_len=3,
    )
    assert not blocked
    assert reason is None


def test_sicilian_blocks_friendly_knight_capture() -> None:
    """Black pawn cannot knight-capture friendly black king (Knight Time)."""
    board = _board_last_suggestion_knight_time()
    loadout = Loadout(extras={"challenge_game_class": "SicilianDefense"})
    flags = stamp_search_flags(loadout)
    assert not path_movement_ok(board, [4, 7], flags=flags, loadout=loadout)


def test_sicilian_king_cannot_step_into_threat() -> None:
    """Black king may not step onto a square attacked by an enemy knight piece."""
    board = _board_last_suggestion_knight_time()
    loadout = Loadout(extras={"challenge_game_class": "SicilianDefense"})
    flags = stamp_search_flags(loadout)
    assert not path_movement_ok(board, [7, 10], flags=flags, loadout=loadout)


def test_last_suggestion_knight_time_path_rejected(tmp_path: Path) -> None:
    """Regression: invalid melmod path ??f?y? must not pass submittability."""
    wl = _make_wordlist(tmp_path)
    dictionary = WordDictionary(wl)
    board = _board_last_suggestion_knight_time()
    loadout = Loadout(extras={"challenge_game_class": "SicilianDefense"})
    path = [4, 7, 10, 21, 12, 23]
    assert not path_is_submittable(
        board,
        path,
        "??f?y?",
        loadout,
        dictionary,
        min_len=3,
    )
    blocked, reason = f8_should_block_save(
        gather_succeeded=True,
        loadout=loadout,
        board=board,
        path=path,
        dictionary=dictionary,
        scoring_word="??f?y?",
        min_len=3,
    )
    assert blocked
    assert reason in ("invalid_path_movement", "no_playable_dictionary_word")


def _board_last_suggestion_knight_time() -> Board:
    """Board layout from 2026-06-26 Knight Time last_suggestion.json failure."""
    letters = [
        "TROU?",
        "II?UI",
        "FNYRI",
        "HEUOO",
        "L?I??",
    ]
    chess_at: dict[tuple[int, int], tuple[CurseType, str, float]] = {
        (0, 4): (CurseType.CHESS_PAWN, "black", 1.0),
        (1, 2): (CurseType.CHESS_KING, "black", 15.0),
        (4, 1): (CurseType.CHESS_PAWN, "white", 1.0),
        (4, 3): (CurseType.CHESS_PAWN, "black", 1.0),
        (4, 4): (CurseType.CHESS_KNIGHT, "white", 3.0),
    }
    grid: list[list[Tile]] = []
    for r, row in enumerate(letters):
        grid_row: list[Tile] = []
        for c, ch in enumerate(row):
            if (r, c) in chess_at:
                piece, color, score = chess_at[(r, c)]
                grid_row.append(
                    Tile(
                        row=r,
                        col=c,
                        char=ch.lower() if ch != "?" else "?",
                        letter="?" if ch == "?" else ch,
                        base_score=score,
                        color=TileColor.COLORLESS,
                        curse=piece,
                        metadata={"chess_color": color},
                    )
                )
            else:
                grid_row.append(_letter_tile(r, c, ch))
        grid.append(grid_row)
    return Board(tiles=grid, money=9)


def test_save_last_suggestion_blocks_offshores_path(
    tmp_path: Path, monkeypatch
) -> None:
    """save_last_suggestion must not write invalid offshores movement."""
    from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
    from cursed_words_solver.models import WordResult
    from cursed_words_solver import suggestion as sug_mod

    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "knight_time_offshores_step3_4.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    board = parse_board_from_run_state(data["run_state_snapshot"])
    loadout = parse_run_state(data["run_state_snapshot"])
    path = data["path"]
    out = tmp_path / "last_suggestion.json"
    monkeypatch.setattr(sug_mod, "LAST_SUGGESTION_PATH", out)

    save_last_suggestion(
        board=board,
        loadout=loadout,
        result=WordResult(word=data["word"], path=path, score=100.0),
        predicted_trace=[],
        dictionary=None,
        min_len=5,
    )
    assert not out.exists()


def test_save_last_suggestion_blocks_invalid_knight_time_path(
    tmp_path: Path, monkeypatch
) -> None:
    """save_last_suggestion must not write when movement validation fails."""
    from cursed_words_solver.models import WordResult
    from cursed_words_solver import suggestion as sug_mod

    wl = _make_wordlist(tmp_path)
    dictionary = WordDictionary(wl)
    board = _board_last_suggestion_knight_time()
    loadout = Loadout(extras={"challenge_game_class": "SicilianDefense"})
    path = [4, 7, 10, 21, 12, 23]
    out = tmp_path / "last_suggestion.json"
    monkeypatch.setattr(sug_mod, "LAST_SUGGESTION_PATH", out)

    save_last_suggestion(
        board=board,
        loadout=loadout,
        result=WordResult(word="??f?y?", path=path, score=100.0),
        predicted_trace=[],
        dictionary=dictionary,
        min_len=3,
    )
    assert not out.exists()
