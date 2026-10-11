"""Pre-item tile scoring: glitch, currency, pink, poison."""

from __future__ import annotations

from cursed_words_solver.models import Board, CurseType, Loadout, LoadoutItem, Tile, TileColor
from cursed_words_solver.engine.scorer import EngineScorer


def _board_with(*specs: tuple[int, TileColor, CurseType]) -> Board:
    tiles = [
        [
            Tile(r, c, "A", "A", 1, TileColor.COLORLESS, CurseType.LETTER)
            for c in range(5)
        ]
        for r in range(5)
    ]
    for idx, color, curse in specs:
        r, c = divmod(idx, 5)
        tiles[r][c] = Tile(r, c, "A", "A", 1, color, curse)
    return Board(tiles=tiles, money=5)


def test_poison_applied_post_multiply() -> None:
    board = _board_with((0, TileColor.COLORLESS, CurseType.WILDCARD))
    loadout = Loadout(
        stamps=[LoadoutItem(id="oden", name="Oden", kind="stamp")],
        extras={
            "historic_words": '[{"word":"gree","score":10,"green_tile_count":1}]',
            "encounter_score_earned": "10",
        },
    )
    pipe = EngineScorer()
    final, _, tr = pipe.score_with_trace(board, [0], "A", loadout)
    assert final == 2.0  # 1 tile + 1 poison after ×1 oden
    assert any(s.get("phase") == "poison" for s in tr)
    assert not any(s.get("phase_detail") == "poison" for s in tr)


