"""Sam Gambit unlock sticker scoring."""

from cursed_words_solver.models import (
    Board,
    CurseType,
    Loadout,
    LoadoutItem,
    Tile,
    TileColor,
)
from cursed_words_solver.engine.scorer import EngineScorer
from cursed_words_solver.rules.rule_lookup import count_scoring_items, get_rule, slugify_name

SAM_STICKER_NAMES = [
    "Backpack",
    "Carousel Horse",
    "Clapper Board",
    "Gorilla",
    "Movie Camera",
    "Raccoon",
    "Suitcase",
    "Zebra",
]

GRID_ONLY_SLUGS = {
    "backpack",
    "carousel_horse",
    "gorilla",
    "raccoon",
    "suitcase",
}


def _tile(
    row: int,
    col: int,
    ch: str,
    score: int,
    *,
    color=TileColor.COLORLESS,
    curse=CurseType.LETTER,
    metadata=None,
) -> Tile:
    meta = {"source": "melmod"}
    if metadata:
        meta.update(metadata)
    return Tile(
        row=row,
        col=col,
        char=ch,
        letter=ch,
        base_score=score,
        color=color,
        curse=curse,
        metadata=meta,
    )


def _empty_board() -> Board:
    grid = [[_tile(r, c, "X", 1) for c in range(5)] for r in range(5)]
    return Board(tiles=grid, money=0)


def test_all_sam_stickers_catalogued():
    pipeline = EngineScorer()
    for name in SAM_STICKER_NAMES:
        slug = slugify_name(name)
        _key, rule = get_rule(pipeline.rules, "stickers", slug, name)
        assert rule is not None, slug
        assert rule.get("type") != "unmodeled", slug


def test_count_scoring_vs_grid_only_sam():
    pipeline = EngineScorer()
    loadout = Loadout(
        stickers=[
            LoadoutItem(id=slugify_name(n), name=n, level=1, kind="sticker")
            for n in SAM_STICKER_NAMES
        ]
    )
    scoring, total, grid_only = count_scoring_items(pipeline.rules, loadout)
    assert total == 8
    assert grid_only == len(GRID_ONLY_SLUGS)
    assert scoring == 8 - len(GRID_ONLY_SLUGS)


def test_grid_sticker_scatter_class():
    pipeline = EngineScorer()
    _key, rule = get_rule(pipeline.rules, "stickers", "raccoon", "Raccoon")
    assert rule.get("effect_class") == "scatter"


def test_clapper_board_two_takes_multiply():
    board = _empty_board()
    board.tiles[2][0] = _tile(
        2,
        0,
        "R",
        5,
        curse=CurseType.CHESS_ROOK,
        metadata={"chess_color": "black"},
    )
    board.tiles[2][2] = _tile(
        2,
        2,
        "P",
        1,
        curse=CurseType.CHESS_PAWN,
        metadata={"chess_color": "white"},
    )
    board.tiles[1][3] = _tile(
        1,
        3,
        "P",
        1,
        curse=CurseType.CHESS_PAWN,
        metadata={"chess_color": "black"},
    )
    board.tiles[1][4] = _tile(1, 4, "A", 2)
    pipeline = EngineScorer()
    loadout = Loadout(
        stickers=[LoadoutItem(id="clapper_board", name="Clapper Board", level=1)]
    )
    path = [10, 12, 8, 9]
    score, bd = pipeline.score(board, path, "rppa", loadout)
    base, _ = pipeline.score(board, path, "rppa", Loadout())
    assert bd["multiplier"] == 2.0
    assert score == base * 2


def test_clapper_board_one_take_no_mult():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "N", 3, curse=CurseType.CHESS_KNIGHT)
    board.tiles[0][1] = _tile(0, 1, "A", 2)
    pipeline = EngineScorer()
    loadout = Loadout(
        stickers=[LoadoutItem(id="clapper_board", name="Clapper Board", level=1)]
    )
    score, bd = pipeline.score(board, [0, 1], "na", loadout)
    base, _ = pipeline.score(board, [0, 1], "na", Loadout())
    assert bd["multiplier"] == 1.0
    assert score == base


def test_movie_camera_rewind_pre_word_extras():
    from cursed_words_solver.rules.scoring_conditions import (
        movie_camera_accumulated,
        rewind_movie_camera_pre_word_extras,
    )

    board = _empty_board()
    board.tiles[0][0] = _tile(
        0,
        0,
        "Q",
        4,
        curse=CurseType.CHESS_QUEEN,
        metadata={"take": True},
    )
    board.tiles[0][1] = _tile(0, 1, "A", 2)
    loadout = Loadout(
        stickers=[LoadoutItem(id="movie_camera", name="Movie Camera", level=1)],
        extras={"movie_camera_word_score_bonus": 29},
    )
    rewind_movie_camera_pre_word_extras(loadout, board, [0, 1], 1, strict=True)
    assert movie_camera_accumulated(loadout) == 20


def test_zebra_inferred_capture_multiplies_attacker_tile():
    """Capture landing at path[2]; Zebra multiplies capturing bishop at path[1]."""
    board = _empty_board()
    board.tiles[4][0] = _tile(
        4,
        0,
        "?",
        3,
        curse=CurseType.CHESS_BISHOP,
        metadata={"chess_color": "black"},
    )
    board.tiles[3][1] = _tile(
        3,
        1,
        "?",
        12,
        curse=CurseType.CHESS_KNIGHT,
        metadata={"chess_color": "white"},
    )
    board.tiles[0][2] = _tile(0, 2, "A", 2)
    path = [21, 20, 16, 2]  # bishop -> knight capture -> letter
    pipeline = EngineScorer()
    loadout = Loadout(stickers=[LoadoutItem(id="zebra", name="Zebra", level=1)])
    score, bd = pipeline.score(board, path, "abca", loadout)
    base, base_bd = pipeline.score(board, path, "abca", Loadout())
    assert bd["pipeline"]["tile_scores"][1] == base_bd["pipeline"]["tile_scores"][1] * 3
    assert bd["pipeline"]["tile_scores"][2] == base_bd["pipeline"]["tile_scores"][2]
    assert score > base


def test_zebra_chess_without_take_no_mult():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "N", 4, curse=CurseType.CHESS_KNIGHT)
    board.tiles[0][1] = _tile(0, 1, "A", 2)
    pipeline = EngineScorer()
    loadout = Loadout(stickers=[LoadoutItem(id="zebra", name="Zebra", level=1)])
    score, bd = pipeline.score(board, [0, 1], "na", loadout)
    base, base_bd = pipeline.score(board, [0, 1], "na", Loadout())
    assert bd["pipeline"]["tile_scores"] == base_bd["pipeline"]["tile_scores"]
    assert score == base
