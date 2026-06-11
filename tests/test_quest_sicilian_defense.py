"""Knight Time (SicilianDefense) movement override."""

from cursed_words_solver.models import Board, CurseType, Loadout, Tile, TileColor
from cursed_words_solver.rules.chess_tiles import clear_chess_attack_cache
from cursed_words_solver.rules.quest_movement import sicilian_neighbors_mask
from cursed_words_solver.rules.stamp_behaviors import stamp_search_flags
from cursed_words_solver.graph_bitboard import build_board_graph_context


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


def test_sicilian_uses_knight_moves_from_knight_tile() -> None:
    start = 12
    grid: list[list[Tile]] = []
    for r in range(5):
        row: list[Tile] = []
        for c in range(5):
            idx = r * 5 + c
            if idx == start:
                row.append(_chess(idx, CurseType.CHESS_KNIGHT))
            else:
                row.append(
                    Tile(
                        row=r,
                        col=c,
                        char="a",
                        letter="a",
                        base_score=1,
                        color=TileColor.COLORLESS,
                        curse=CurseType.LETTER,
                    )
                )
        grid.append(row)
    board = Board(tiles=grid, money=0)
    loadout = Loadout(extras={"challenge_game_class": "SicilianDefense"})
    graph = build_board_graph_context(board)
    clear_chess_attack_cache(has_chess_pieces=True)
    flags = stamp_search_flags(loadout)
    mask = sicilian_neighbors_mask(
        board,
        start,
        1 << start,
        flags=flags,
        graph_ctx=graph,
    )
    # Knight from center reaches corner-like L shapes, not orthogonal neighbors.
    assert mask & (1 << 5)
    assert not (mask & (1 << 13))
    assert loadout.extras["challenge_game_class"] == "SicilianDefense"
