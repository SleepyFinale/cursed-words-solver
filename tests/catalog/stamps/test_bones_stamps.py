"""Bones The Dog unlock stamp catalog and behavior (wiki: Unlocked when unlocking Bones The Dog)."""

from cursed_words_solver.models import (
    Board,
    CurseType,
    Loadout,
    LoadoutItem,
    Tile,
)
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.rule_lookup import count_scoring_items, get_rule, slugify_name
from cursed_words_solver.rules.scoring_conditions import detect_card_hand
from cursed_words_solver.rules.stamp_behaviors import stamp_search_flags
from cursed_words_solver.search import resolve_letter

BONES_STAMP_NAMES = [
    "Card Shark",
    "Martini",
    "Four Leaf Clover",
    "Go Fish!",
    "Magician's Hat",
    "Smart Shirt",
    "Valentine's Day Card",
]

GRID_ONLY_SLUGS = {
    "card_shark",
    "four_leaf_clover",
    "go_fish",
    "magician_s_hat",
    "smart_shirt",
    "valentine_s_day_card",
}


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


def test_all_bones_stamps_catalogued():
    pipeline = ScoringPipeline()
    for name in BONES_STAMP_NAMES:
        slug = slugify_name(name)
        _key, rule = get_rule(pipeline.rules, "stamps", slug, name)
        assert rule is not None, slug
        assert rule.get("type") != "unmodeled", slug


def test_count_scoring_vs_grid_only_bones_stamps():
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stamps=[
            LoadoutItem(id=slugify_name(n), name=n, level=1, kind="stamp")
            for n in BONES_STAMP_NAMES
        ]
    )
    scoring, total, grid_only = count_scoring_items(pipeline.rules, loadout)
    assert total == 7
    assert grid_only == len(GRID_ONLY_SLUGS)
    assert scoring == 1


def test_martini_three_card_flush():
    board = _empty_board()
    path = []
    for c in range(3):
        board.tiles[0][c] = _card(0, c, str(2 + c), "hearts")
        path.append(c)
    loadout = Loadout(
        stamps=[LoadoutItem(id="martini", name="Martini", kind="stamp")]
    )
    assert detect_card_hand("flush", board, path, loadout)
    assert not detect_card_hand("flush", board, path, Loadout())


def test_martini_five_card_flush_without_stamp():
    board = _empty_board()
    path = []
    for c in range(5):
        board.tiles[0][c] = _card(0, c, str(2 + c), "hearts")
        path.append(c)
    assert detect_card_hand("flush", board, path, Loadout())


def test_martini_three_card_straight():
    board = _empty_board()
    path = []
    for c, rank in enumerate("234"):
        board.tiles[0][c] = _card(0, c, rank, "hearts")
        path.append(c)
    loadout = Loadout(
        stamps=[LoadoutItem(id="martini", name="Martini", kind="stamp")]
    )
    assert detect_card_hand("straight", board, path, loadout)
    assert not detect_card_hand("straight", board, path, Loadout())


def test_card_shark_suit_first_letter():
    tile = _card(0, 0, "K", "hearts")
    loadout = Loadout(
        stamps=[LoadoutItem(id="card_shark", name="Card Shark", kind="stamp")]
    )
    flags = stamp_search_flags(loadout)
    assert resolve_letter(tile, 0, flags=flags) == "h"
    assert resolve_letter(tile, 0, flags=stamp_search_flags(Loadout())) == "K"
