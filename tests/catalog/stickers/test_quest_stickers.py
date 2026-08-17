"""Quest unlock sticker scoring."""

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

QUEST_STICKER_NAMES = [
    "Mystery Gift",
    "Hungry Hippo",
    "Sushi",
    "Ambulance",
    "Dartboard",
    "Magic 8 Ball",
    "Wind Chime",
    "Michael's Book",
    "Luffing Jib Crane",
    "Base Camp",
]

GRID_ONLY_SLUGS = {
    "mystery_gift",
    "luffing_jib_crane",
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


def _card(row: int, col: int, rank: str, suit: str, score: int = 2) -> Tile:
    return Tile(
        row=row,
        col=col,
        char=rank,
        letter=rank,
        base_score=score,
        curse=CurseType.CARD,
        metadata={"source": "melmod", "card_suit": suit, "card_rank": rank},
    )


def _empty_board() -> Board:
    grid = [[_tile(r, c, "X", 1) for c in range(5)] for r in range(5)]
    return Board(tiles=grid, money=0)


def test_all_quest_stickers_catalogued():
    pipeline = ScoringPipeline()
    for name in QUEST_STICKER_NAMES:
        slug = slugify_name(name)
        _key, rule = get_rule(pipeline.rules, "stickers", slug, name)
        assert rule is not None, slug
        assert rule.get("type") != "unmodeled", slug


def test_count_scoring_vs_grid_only_quest():
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[
            LoadoutItem(id=slugify_name(n), name=n, level=1, kind="sticker")
            for n in QUEST_STICKER_NAMES
        ]
    )
    scoring, total, grid_only = count_scoring_items(pipeline.rules, loadout)
    assert total == 10
    assert grid_only == len(GRID_ONLY_SLUGS)
    assert scoring == 10 - len(GRID_ONLY_SLUGS)


def test_mystery_gift_and_crane_catalog():
    pipeline = ScoringPipeline()
    _key, gift = get_rule(pipeline.rules, "stickers", "mystery_gift", "Mystery Gift")
    assert gift.get("effect_class") == "sell"
    _key, crane = get_rule(
        pipeline.rules, "stickers", "luffing_jib_crane", "Luffing Jib Crane"
    )
    assert crane.get("effect_class") == "rack"


def test_hungry_hippo_word_bonus():
    board = _empty_board()
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="hungry_hippo", name="Hungry Hippo", level=1)])
    score, bd = pipeline.score(board, [0], "x", loadout)
    base, base_bd = pipeline.score(board, [0], "x", Loadout())
    assert bd["word_score"] == base_bd["word_score"] + 20
    assert score == base + 20


def test_sushi_colourless_adjacent_multiply():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "R", 1, color=TileColor.RED)
    board.tiles[0][1] = _tile(0, 1, "C", 1, color=TileColor.COLORLESS)
    board.tiles[0][2] = _tile(0, 2, "B", 1, color=TileColor.BLUE)
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="sushi", name="Sushi", level=1)])
    score, bd = pipeline.score(board, [1], "c", loadout)
    base, base_bd = pipeline.score(board, [1], "c", Loadout())
    assert bd["pipeline"]["tile_scores"][0] == base_bd["pipeline"]["tile_scores"][0] * 3
    assert score == base * 3


def test_sushi_counts_diagonal_neighbours():
    """Sushi uses 8-dir adjacency (GridUtility), not orthogonal-only."""
    board = _empty_board()
    # Centre colourless; red NW and blue SE are diagonal-only.
    board.tiles[1][1] = _tile(1, 1, "C", 1, color=TileColor.COLORLESS)
    board.tiles[0][0] = _tile(0, 0, "R", 1, color=TileColor.RED)
    board.tiles[2][2] = _tile(2, 2, "B", 1, color=TileColor.BLUE)
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="sushi", name="Sushi", level=1)])
    score, bd = pipeline.score(board, [6], "c", loadout)  # (1,1) → index 6 on 5×5
    base, base_bd = pipeline.score(board, [6], "c", Loadout())
    assert bd["pipeline"]["tile_scores"][0] == base_bd["pipeline"]["tile_scores"][0] * 3
    assert score == base * 3


def test_ambulance_negative_base_multiplier():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "Z", 0, color=TileColor.VOID, curse=CurseType.LETTER)
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="ambulance", name="Ambulance", level=1)])
    score, bd = pipeline.score(board, [0], "z", loadout)
    base, _ = pipeline.score(board, [0], "z", Loadout())
    assert bd["base_total"] < 0
    assert bd["multiplier"] == 1.5
    assert score == base * 1.5


def test_dartboard_target_base_bonus():
    board = _empty_board()
    board.tiles[0][0] = _tile(0, 0, "A", 1)
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[LoadoutItem(id="dartboard", name="Dartboard", level=1)],
        extras={"target_score": "1"},
    )
    score, bd = pipeline.score(board, [0], "a", loadout)
    base, _ = pipeline.score(board, [0], "a", Loadout())
    assert bd["base_total"] == 1
    assert score == base + 101


def test_magic_8_ball_target_knight():
    board = _empty_board()
    board.tiles[0][0] = _tile(
        0, 0, "N", 3, color=TileColor.RED, curse=CurseType.CHESS_KNIGHT
    )
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[LoadoutItem(id="magic_8_ball", name="Magic 8 Ball", level=1)],
        extras={"target_chess_piece": "knight"},
    )
    score, bd = pipeline.score(board, [0], "n", loadout)
    base, base_bd = pipeline.score(board, [0], "n", Loadout())
    assert bd["pipeline"]["tile_scores"][0] == base_bd["pipeline"]["tile_scores"][0] + 25
    assert score == base + 25


def test_wind_chime_five_cards():
    board = _empty_board()
    path = []
    for c in range(5):
        board.tiles[0][c] = _card(0, c, str(c + 2), "hearts")
        path.append(c)
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="wind_chime", name="Wind Chime", level=1)])
    score, bd = pipeline.score(board, path, "23456", loadout)
    base, _ = pipeline.score(board, path, "23456", Loadout())
    assert bd["multiplier"] == 2.0
    assert score == base * 2


def test_michael_s_book_bonus_from_extras():
    board = _empty_board()
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[LoadoutItem(id="michael_s_book", name="Michael's Book", level=1)],
        extras={"michael_book_bonus": "90"},
    )
    score, _ = pipeline.score(board, [0], "x", loadout)
    base, _ = pipeline.score(board, [0], "x", Loadout())
    assert score == base + 90


def test_base_camp_grid_total_base():
    board = _empty_board()
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="base_camp", name="Base Camp", level=1)])
    score, bd = pipeline.score(board, [0], "x", loadout)
    base, base_bd = pipeline.score(board, [0], "x", Loadout())
    grid_base = 25
    assert bd["word_score"] == base_bd["word_score"] + grid_base
    assert score == base + grid_base
