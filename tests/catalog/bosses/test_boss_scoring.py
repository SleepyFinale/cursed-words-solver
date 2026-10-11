"""Boss submit-time scoring."""

from __future__ import annotations

from cursed_words_solver.models import Board, CurseType, Loadout, Tile, TileColor
from cursed_words_solver.engine.scorer import EngineScorer


def _tile(letter: str = "A") -> Tile:
    return Tile(0, 0, letter, letter, 2, TileColor.COLORLESS, CurseType.LETTER)


def _board() -> Board:
    tiles = [[_tile() if r == 0 and c < 3 else Tile(r, c, "", "", 0, curse=CurseType.ITEM) for c in range(5)] for r in range(5)]
    active = [r * 5 + c < 3 for r in range(5) for c in range(5)]
    return Board(tiles=tiles, money=10, active=active)


def test_boss_modifiers_source_of_truth_can_disable_stale_primary_boss() -> None:
    board = _board()
    # Primary boss id can be stale in capture; explicit empty boss_modifiers means
    # this phase has no copied boss effects.
    loadout = Loadout(
        boss_id="salamander",
        extras={"boss_area_number": 1, "boss_modifiers": []},
    )
    pipe = EngineScorer()
    _, bd = pipe.score(board, [0, 1, 2], "aaa", loadout)
    assert not any("per tile (boss)" in e for e in bd["pipeline"]["effects"])
