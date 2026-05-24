"""Scoring trace and fingerprint helpers."""

from cursed_words_solver.fingerprints import board_fingerprint, loadout_fingerprint
from cursed_words_solver.models import Board, CurseType, Loadout, LoadoutItem, Tile, TileColor
from cursed_words_solver.rules.pipeline import ScoringPipeline


def _simple_board() -> Board:
    tiles = [
        [
            Tile(
                row=r,
                col=c,
                char="A",
                letter="A",
                base_score=2,
                color=TileColor.COLORLESS,
                curse=CurseType.LETTER,
            )
            for c in range(5)
        ]
        for r in range(5)
    ]
    return Board(tiles=tiles, money=10)


def test_score_with_trace_returns_steps():
    board = _simple_board()
    path = [0, 1, 2]
    word = "aaa"
    pipeline = ScoringPipeline()
    score, _bd, trace = pipeline.score_with_trace(board, path, word, Loadout())
    assert score == pipeline.score_total_only(board, path, word, Loadout())
    assert trace
    assert trace[0]["phase"] == "init"
    assert any(s.get("phase") == "pre_multiply" for s in trace)


def test_trace_conditional_rule_applied_flag():
    """Skipped conditional rules must not reuse a prior rule's effect text."""
    board = _simple_board()
    board.tiles[0][0] = Tile(
        row=0,
        col=0,
        char="$",
        letter="S",
        base_score=0,
        color=TileColor.COLORLESS,
        curse=CurseType.CURRENCY,
    )
    path = [0, 1, 2]
    loadout = Loadout(
        stickers=[
            LoadoutItem(id="sunflower", name="Sunflower", level=1),
            LoadoutItem(id="wheezy_vixen", name="Wheezy Vixen", level=2),
        ],
        money=10,
    )
    pipeline = ScoringPipeline()
    _score, _bd, trace = pipeline.score_with_trace(board, path, "aaa", loadout)

    rule_steps = [s for s in trace if s.get("phase") == "rule"]
    assert rule_steps
    assert all("applied" in s for s in rule_steps)

    sunflower = next(s for s in rule_steps if s.get("rule_id") == "sunflower")
    wheezy = next(s for s in rule_steps if s.get("rule_id") == "wheezy_vixen")

    assert sunflower["applied"] is True
    assert wheezy["applied"] is False
    assert wheezy["detail"] != sunflower["detail"]
    assert "vwxyz" in wheezy["detail"].lower()


def test_fingerprints_stable():
    board = _simple_board()
    lo = Loadout(
        character="Test",
        money=10,
        stickers=[LoadoutItem(id="birthday_cake", name="Birthday Cake", level=2)],
    )
    fp1 = board_fingerprint(board)
    fp2 = board_fingerprint(board)
    assert fp1 == fp2
    assert loadout_fingerprint(lo) == loadout_fingerprint(lo)
