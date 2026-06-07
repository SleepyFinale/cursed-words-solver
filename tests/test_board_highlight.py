from cursed_words_solver.config import Region
from cursed_words_solver.consumable_placement import ConsumablePlacement
from cursed_words_solver.models import Board
from cursed_words_solver.ui.board_geometry import placement_geometry, path_geometry
from tests.test_search import _tile


def test_placement_geometry_maps_indices():
    region = Region(x=0, y=0, width=500, height=500)
    board = Board(tiles=[[_tile("x", r, c) for c in range(5)] for r in range(5)])
    records = [
        ConsumablePlacement(row=1, col=1, index=6, letter="U"),
        ConsumablePlacement(row=2, col=2, index=12, letter="D"),
    ]
    markers = placement_geometry(region, records, board)
    assert len(markers) == 2
    assert {m.letter for m in markers} == {"U", "D"}
    path = path_geometry(region, [6, 12], board)
    assert len(path) == 2
    assert path[0].x == markers[0].x
    assert path[0].y == markers[0].y
