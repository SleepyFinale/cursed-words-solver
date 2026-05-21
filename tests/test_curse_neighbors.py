from cursed_words_solver.models import Board, CurseType, Tile, TileColor
from cursed_words_solver.search import neighbors_from_tile


def _tile(r, c, curse=CurseType.LETTER):
    return Tile(r, c, "?", "?", 0, TileColor.COLORLESS, curse)


def _empty_board() -> Board:
    return Board(tiles=[[_tile(r, c) for c in range(5)] for r in range(5)])


def test_knight_moves():
    board = _empty_board()
    board.tiles[2][2] = _tile(2, 2, CurseType.CHESS_KNIGHT)
    nbrs = neighbors_from_tile(board, [board.tiles[2][2].index], {12})
    # Knight at (2,2) -> some L positions
    assert len(nbrs) > 0
    assert all(n != 12 for n in nbrs)


def test_white_teleport():
    board = _empty_board()
    board.tiles[0][0].color = TileColor.WHITE
    nbrs = neighbors_from_tile(board, [0], {0})
    assert len(nbrs) == 24
