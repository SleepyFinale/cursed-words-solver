"""Quest search path filters."""

from cursed_words_solver.models import (
    Board,
    CurseType,
    Loadout,
    LoadoutItem,
    Tile,
    TileColor,
)
from cursed_words_solver.rules.quest_effects import quest_path_allowed


def _tile(
    idx: int,
    *,
    color=TileColor.COLORLESS,
    curse=CurseType.LETTER,
    letter="a",
    meta=None,
) -> Tile:
    row, col = divmod(idx, 5)
    return Tile(
        row=row,
        col=col,
        char=letter,
        letter=letter,
        base_score=1,
        color=color,
        curse=curse,
        metadata=meta or {},
    )


def _board(tiles: dict[int, Tile]) -> Board:
    grid: list[list[Tile]] = []
    for r in range(5):
        row: list[Tile] = []
        for c in range(5):
            idx = r * 5 + c
            row.append(tiles.get(idx, _tile(idx)))
        grid.append(row)
    return Board(tiles=grid, money=0)


def test_crossed_out_tile_blocks_path() -> None:
    board = _board({2: _tile(2, letter="x", meta={"is_crossed_out": True})})
    loadout = Loadout(extras={"challenge_game_class": "SupplyAndDemand"})
    assert not quest_path_allowed(board, [2, 7, 12], loadout=loadout)
    assert quest_path_allowed(board, [7, 12, 13], loadout=loadout)


def test_up_and_up_requires_center() -> None:
    center = 12
    board = _board({center: _tile(center, meta={"is_up_and_up_center": True})})
    loadout = Loadout(
        extras={
            "challenge_game_class": "UpAndUp",
            "up_and_up_center_index": str(center),
        }
    )
    assert not quest_path_allowed(board, [0, 1, 2], loadout=loadout)
    assert quest_path_allowed(board, [0, center, 2], loadout=loadout)


def test_chromaphobia_rejects_colored_tiles() -> None:
    board = _board({3: _tile(3, color=TileColor.RED)})
    loadout = Loadout(extras={"challenge_game_class": "Chromaphobia"})
    assert not quest_path_allowed(board, [3, 8, 13], loadout=loadout)


def test_cursophobia_rejects_cursed_tiles() -> None:
    board = _board({4: _tile(4, curse=CurseType.WILDCARD)})
    loadout = Loadout(extras={"challenge_game_class": "Cursophobia"})
    assert not quest_path_allowed(board, [4, 9, 14], loadout=loadout)


def test_cursophobia_rejects_jellyfish_wobbly_j() -> None:
    """Jellyfish makes J display as H/Y → IsCursed; Cursophobia must reject it."""
    board = _board({4: _tile(4, letter="j"), 9: _tile(9, letter="a"), 14: _tile(14, letter="y")})
    loadout = Loadout(
        stamps=[LoadoutItem(id="jellyfish", name="Jellyfish", level=1)],
        extras={"challenge_game_class": "Cursophobia"},
    )
    assert not quest_path_allowed(board, [4, 9, 14], loadout=loadout)
    # Plain letter path without J is still allowed.
    board_ok = _board({4: _tile(4, letter="c"), 9: _tile(9, letter="a"), 14: _tile(14, letter="t")})
    assert quest_path_allowed(board_ok, [4, 9, 14], loadout=loadout)


def test_cursophobia_neighbor_mask_drops_chess() -> None:
    """DFS must not expand onto cursed tiles under Cursophobia (wildcard thrash)."""
    from cursed_words_solver.rules.quest_movement import neighbors_mask_for_quest

    board = _board(
        {
            12: _tile(12, letter="a"),
            7: _tile(7, curse=CurseType.CHESS_ROOK, letter="?"),
            13: _tile(13, letter="d"),
        }
    )
    loadout = Loadout(extras={"challenge_game_class": "Cursophobia"})
    # From A@12: neighbors include rook@7 and D@13 (among others).
    standard = (1 << 7) | (1 << 13)
    filtered = neighbors_mask_for_quest(
        board,
        visited_mask=1 << 12,
        cell_id=12,
        flags=0,
        graph_ctx=None,
        loadout=loadout,
        standard_mask=standard,
    )
    assert filtered & (1 << 7) == 0
    assert filtered & (1 << 13) != 0
