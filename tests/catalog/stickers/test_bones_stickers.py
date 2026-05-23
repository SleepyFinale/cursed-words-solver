"""Bones The Dog unlock sticker scoring."""

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

BONES_STICKER_NAMES = [
    "Celestial Body",
    "Hanafuda",
    "Joker",
    "Kadomatsu",
    "Musical Notes",
    "Peacock",
    "Pear",
    "Peas Of A Pod",
    "Poker Face",
    "Postal Horn",
    "Slide",
    "Wrestlers",
]

GRID_ONLY_SLUGS = {
    "joker",
    "musical_notes",
    "postal_horn",
}


def _card(
    row: int,
    col: int,
    rank: str,
    suit: str,
    score: int = 2,
) -> Tile:
    return Tile(
        row=row,
        col=col,
        char=rank,
        letter=rank,
        base_score=score,
        curse=CurseType.CARD,
        metadata={"source": "melmod", "card_suit": suit, "card_rank": rank},
    )


def _letter(row: int, col: int, ch: str, score: int = 1) -> Tile:
    return Tile(
        row=row,
        col=col,
        char=ch,
        letter=ch,
        base_score=score,
        metadata={"source": "melmod"},
    )


def _empty_board() -> Board:
    grid = [[_letter(r, c, "X", 1) for c in range(5)] for r in range(5)]
    return Board(tiles=grid, money=0)


def test_all_bones_stickers_catalogued():
    pipeline = ScoringPipeline()
    for name in BONES_STICKER_NAMES:
        slug = slugify_name(name)
        _key, rule = get_rule(pipeline.rules, "stickers", slug, name)
        assert rule is not None, slug
        assert rule.get("type") != "unmodeled", slug


def test_count_scoring_vs_grid_only_bones():
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[
            LoadoutItem(id=slugify_name(n), name=n, level=1, kind="sticker")
            for n in BONES_STICKER_NAMES
        ]
    )
    scoring, total, grid_only = count_scoring_items(pipeline.rules, loadout)
    assert total == 12
    assert grid_only == len(GRID_ONLY_SLUGS)
    assert scoring == 12 - len(GRID_ONLY_SLUGS)


def test_postal_horn_grid_scatter():
    pipeline = ScoringPipeline()
    _key, rule = get_rule(pipeline.rules, "stickers", "postal_horn", "Postal Horn")
    assert rule.get("effect_class") == "scatter"


def test_celestial_body_card_tile_bonus_level2():
    board = _empty_board()
    board.tiles[0][0] = _card(0, 0, "A", "hearts")
    board.tiles[0][1] = _card(0, 1, "K", "spades")
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[LoadoutItem(id="celestial_body", name="Celestial Body", level=2)]
    )
    score, bd = pipeline.score(board, [0, 1], "ak", loadout)
    base, base_bd = pipeline.score(board, [0, 1], "ak", Loadout())
    assert sum(bd["pipeline"]["tile_scores"]) == sum(base_bd["pipeline"]["tile_scores"]) + 40
    assert score == base + 40


def test_kadomatsu_three_of_a_kind():
    board = _empty_board()
    board.tiles[0][0] = _card(0, 0, "K", "hearts")
    board.tiles[0][1] = _card(0, 1, "K", "spades")
    board.tiles[0][2] = _card(0, 2, "K", "clubs")
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="kadomatsu", name="Kadomatsu", level=1)])
    score, bd = pipeline.score(board, [0, 1, 2], "kkk", loadout)
    base, base_bd = pipeline.score(board, [0, 1, 2], "kkk", Loadout())
    assert bd["word_score"] == base_bd["word_score"] + 80
    assert score == base + 80


def test_peacock_flush_multiply():
    board = _empty_board()
    path = []
    for c in range(5):
        board.tiles[0][c] = _card(0, c, str(2 + c), "hearts")
        path.append(c)
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="peacock", name="Peacock", level=1)])
    score, bd = pipeline.score(board, path, "23456", loadout)
    base, _ = pipeline.score(board, path, "23456", Loadout())
    assert bd["multiplier"] == 2.0
    assert score == base * 2


def test_pear_pair_money_bonus():
    board = _empty_board()
    board.tiles[0][0] = _card(0, 0, "7", "hearts")
    board.tiles[0][1] = _card(0, 1, "7", "diamonds")
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="pear", name="Pear", level=1)])
    score, bd = pipeline.score(board, [0, 1], "77", loadout)
    base, _ = pipeline.score(board, [0, 1], "77", Loadout())
    assert bd["money_bonus"] == 2
    assert score == base


def test_hanafuda_pair_per_unused_card():
    board = _empty_board()
    board.tiles[0][0] = _card(0, 0, "A", "hearts")
    board.tiles[0][1] = _card(0, 1, "A", "spades")
    board.tiles[1][0] = _card(1, 0, "2", "clubs")
    board.tiles[1][1] = _card(1, 1, "3", "diamonds")
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="hanafuda", name="Hanafuda", level=1)])
    score, bd = pipeline.score(board, [0, 1], "aa", loadout)
    base, base_bd = pipeline.score(board, [0, 1], "aa", Loadout())
    assert bd["word_score"] == base_bd["word_score"] + 24
    assert score == base + 24


def test_slide_straight_word_bonus():
    board = _empty_board()
    path = []
    for c, rank in enumerate("23456"):
        board.tiles[0][c] = _card(0, c, rank, "hearts")
        path.append(c)
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="slide", name="Slide", level=1)])
    score, bd = pipeline.score(board, path, "23456", loadout)
    base, base_bd = pipeline.score(board, path, "23456", Loadout())
    assert bd["word_score"] == base_bd["word_score"] + 150
    assert score == base + 150


def test_poker_face_starts_with_face_card():
    board = _empty_board()
    board.tiles[0][0] = _card(0, 0, "Q", "hearts")
    board.tiles[0][1] = _letter(0, 1, "A")
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="poker_face", name="Poker Face", level=1)])
    score, bd = pipeline.score(board, [0, 1], "qa", loadout)
    base, _ = pipeline.score(board, [0, 1], "qa", Loadout())
    assert bd["multiplier"] == 2.0
    assert score == base * 2


def test_poker_face_non_face_start_no_mult():
    board = _empty_board()
    board.tiles[0][0] = _card(0, 0, "2", "hearts")
    board.tiles[0][1] = _letter(0, 1, "A")
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="poker_face", name="Poker Face", level=1)])
    score, bd = pipeline.score(board, [0, 1], "2a", loadout)
    base, _ = pipeline.score(board, [0, 1], "2a", Loadout())
    assert bd["multiplier"] == 1.0
    assert score == base


def test_wrestlers_different_suits_at_ends():
    board = _empty_board()
    board.tiles[0][0] = _card(0, 0, "K", "hearts")
    board.tiles[0][1] = _letter(0, 1, "A")
    board.tiles[0][2] = _card(0, 2, "5", "clubs")
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="wrestlers", name="Wrestlers", level=1)])
    score, bd = pipeline.score(board, [0, 1, 2], "ka5", loadout)
    base, _ = pipeline.score(board, [0, 1, 2], "ka5", Loadout())
    assert bd["multiplier"] == 1.5
    assert score == int(base * 1.5)  # floor after ×WORD


def test_wrestlers_same_suit_ends_no_mult():
    board = _empty_board()
    board.tiles[0][0] = _card(0, 0, "K", "hearts")
    board.tiles[0][1] = _letter(0, 1, "A")
    board.tiles[0][2] = _card(0, 2, "5", "hearts")
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="wrestlers", name="Wrestlers", level=1)])
    score, bd = pipeline.score(board, [0, 1, 2], "ka5", loadout)
    base, _ = pipeline.score(board, [0, 1, 2], "ka5", Loadout())
    assert bd["multiplier"] == 1.0
    assert score == base


def test_peas_of_a_pod_four_of_a_kind():
    board = _empty_board()
    path = []
    for c in range(4):
        board.tiles[0][c] = _card(0, c, "9", "hearts")
        path.append(c)
    board.tiles[0][4] = _letter(0, 4, "A")
    path.append(4)
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[LoadoutItem(id="peas_of_a_pod", name="Peas Of A Pod", level=1)]
    )
    score, bd = pipeline.score(board, path, "9999a", loadout)
    base, _ = pipeline.score(board, path, "9999a", Loadout())
    assert bd["multiplier"] == 2.0
    assert score == base * 2
