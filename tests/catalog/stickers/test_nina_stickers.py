"""Nina Nix unlock sticker scoring."""

from cursed_words_solver.models import (
    Board,
    CurseType,
    Loadout,
    LoadoutItem,
    Tile,
    TileColor,
)
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.rule_lookup import count_scoring_items, get_rule, slugify_name

NINA_STICKER_NAMES = [
    "Deep Sea Horror",
    "Doughnut",
    "Ferris Wheel",
    "Fish Cake",
    "Game Pad",
    "Jigsaw Piece",
    "Maracas",
    "Rainbow Sprinkles",
    "Tombstone",
]

GRID_ONLY_SLUGS = {
    "doughnut",
    "game_pad",
    "maracas",
    "rainbow_sprinkles",
}


def _tile(
    row: int,
    col: int,
    ch: str,
    score: int,
    *,
    color=TileColor.COLORLESS,
    curse=CurseType.LETTER,
) -> Tile:
    return Tile(
        row=row,
        col=col,
        char=ch,
        letter=ch,
        base_score=score,
        color=color,
        curse=curse,
        metadata={"source": "melmod"},
    )


def _empty_board() -> Board:
    grid = [[_tile(r, c, "X", 1) for c in range(5)] for r in range(5)]
    return Board(tiles=grid, money=0)


def test_all_nina_stickers_catalogued():
    pipeline = ScoringPipeline()
    for name in NINA_STICKER_NAMES:
        slug = slugify_name(name)
        _key, rule = get_rule(pipeline.rules, "stickers", slug, name)
        assert rule is not None, slug
        assert rule.get("type") != "unmodeled", slug


def test_count_scoring_vs_grid_only_nina():
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[
            LoadoutItem(id=slugify_name(n), name=n, level=1, kind="sticker")
            for n in NINA_STICKER_NAMES
        ]
    )
    scoring, total, grid_only = count_scoring_items(pipeline.rules, loadout)
    assert total == 9
    assert grid_only == len(GRID_ONLY_SLUGS)
    assert scoring == 9 - len(GRID_ONLY_SLUGS)


def test_deep_sea_horror_void_penalty():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", -3, color=TileColor.VOID)
    board.tiles[0][1] = _tile(0, 1, "B", 2)
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[LoadoutItem(id="deep_sea_horror", name="Deep Sea Horror", level=1)]
    )
    score, _ = pipeline.score(board, [0, 1], "ab", loadout)
    base, _ = pipeline.score(board, [0, 1], "ab", Loadout())
    assert score == base - 10


def test_ferris_wheel_different_coloured_ends():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 4, color=TileColor.RED)
    board.tiles[0][1] = _tile(0, 1, "B", 4)
    board.tiles[0][2] = _tile(0, 2, "C", 4, color=TileColor.BLUE)
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="ferris_wheel", name="Ferris Wheel", level=1)])
    score, bd = pipeline.score(board, [0, 1, 2], "abc", loadout)
    assert bd["multiplier"] == 1.5
    assert score == 12 * 1.5


def test_ferris_wheel_same_colour_ends_no_mult():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 5, color=TileColor.RED)
    board.tiles[0][1] = _tile(0, 1, "B", 5, color=TileColor.RED)
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="ferris_wheel", name="Ferris Wheel", level=1)])
    score, bd = pipeline.score(board, [0, 1], "ab", loadout)
    base, _ = pipeline.score(board, [0, 1], "ab", Loadout())
    assert bd["multiplier"] == 1.0
    assert score == base


def test_fish_cake_shiny_multiply():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "S", 10, color=TileColor.SHINY)
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="fish_cake", name="Fish Cake", level=1)])
    score, _ = pipeline.score(board, [0], "s", loadout)
    assert score == 20


def test_jigsaw_piece_zero_subtotal_bonus():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 0)
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="jigsaw_piece", name="Jigsaw Piece", level=1)])
    score, bd = pipeline.score(board, [0], "a", loadout)
    assert bd["word_score"] == 100
    assert score == 100


def test_jigsaw_piece_nonzero_subtotal_no_bonus():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 5)
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="jigsaw_piece", name="Jigsaw Piece", level=1)])
    score, bd = pipeline.score(board, [0], "a", loadout)
    assert bd["word_score"] == 0
    assert score == 5


def test_tombstone_void_adjacent_bonus():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "V", 0, color=TileColor.VOID)
    board.tiles[0][1] = _tile(0, 1, "A", 3)
    board.tiles[1][1] = _tile(1, 1, "V2", 0, color=TileColor.VOID)
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="tombstone", name="Tombstone", level=1)])
    score, _ = pipeline.score(board, [1], "a", loadout)
    # A at (0,1) has void at (0,0) and (1,1) → +10
    assert score == 13


def test_tombstone_diagonal_void_adjacent_bonus():
    board = _empty_board()
    board.tiles[4][3] = _tile(4, 3, "G", 2)
    board.tiles[3][4] = _tile(3, 4, "E", 0, color=TileColor.VOID)
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="tombstone", name="Tombstone", level=1)])
    score, _ = pipeline.score(board, [23], "g", loadout)
    base, _ = pipeline.score(board, [23], "g", Loadout())
    assert score == base + 5


def test_tombstone_void_path_corner_cluster_two_hop():
    """VOID path tile with three direct VOID neighbours also picks up 2-hop VOIDs."""
    board = _empty_board()
    board.tiles[2][0] = _tile(2, 0, "Y", 0, color=TileColor.VOID)
    board.tiles[2][1] = _tile(2, 1, "S", 0, color=TileColor.VOID)
    board.tiles[2][2] = _tile(2, 2, "M", 0, color=TileColor.VOID)
    board.tiles[3][0] = _tile(3, 0, "I", 0, color=TileColor.VOID)
    board.tiles[3][1] = _tile(3, 1, "F", 0, color=TileColor.VOID)
    board.tiles[3][4] = _tile(3, 4, "X", 0, color=TileColor.VOID)
    board.tiles[1][1] = _tile(1, 1, "R", 1)
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="tombstone", name="Tombstone", level=2)])
    score, _ = pipeline.score(board, [10, 6, 11], "yrs", loadout)
    base, _ = pipeline.score(board, [10, 6, 11], "yrs", Loadout())
    assert score - base == 110


def test_tombstone_number_void_counts_adjacent():
    board = _empty_board()
    board.tiles[3][2] = _tile(3, 2, "E", 1)
    board.tiles[3][0] = _tile(3, 0, "O", 0, color=TileColor.VOID)
    board.tiles[2][2] = _tile(2, 2, "A", 0, color=TileColor.VOID)
    board.tiles[2][3] = _tile(2, 3, "F", 0, color=TileColor.VOID)
    board.tiles[3][1] = Tile(
        row=3,
        col=1,
        char="8",
        letter="8",
        base_score=0.0,
        color=TileColor.VOID,
        curse=CurseType.NUMBER,
        number_value=8,
        metadata={"source": "melmod"},
    )
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="tombstone", name="Tombstone", level=1)])
    score, _ = pipeline.score(board, [17], "e", loadout)
    base, _ = pipeline.score(board, [17], "e", Loadout())
    assert score == base + 15
