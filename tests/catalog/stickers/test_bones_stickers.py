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


def _joker_tile(row: int, col: int, suit: str = "joker") -> Tile:
    return Tile(
        row=row,
        col=col,
        char="?",
        letter="?",
        base_score=0,
        color=TileColor.COLORLESS,
        curse=CurseType.WILDCARD,
        metadata={"source": "melmod", "card_suit": suit, "is_joker": True},
    )


def _letter_card(
    row: int, col: int, ch: str, suit: str, score: int = 1
) -> Tile:
    """Bones-style playing card on a letter tile (melmod export)."""
    return Tile(
        row=row,
        col=col,
        char=ch.lower(),
        letter=ch.upper(),
        base_score=score,
        curse=CurseType.LETTER,
        metadata={
            "source": "melmod",
            "card_suit": suit,
            "card_rank": ch.upper()[:1],
        },
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


def test_celestial_body_l2_solitary_endpoint_d_no_bonus():
    """L2: duplicate suited E get +20; solitary suited D at path end does not (coalesced)."""
    board = _empty_board()
    board.tiles[4][3] = _letter_card(4, 3, "E", "clubs", 1)
    board.tiles[3][3] = _letter(3, 3, "O", 1)
    board.tiles[2][2] = _letter(2, 2, "A", 1)
    board.tiles[1][2] = _letter(1, 2, "L", 1)
    board.tiles[0][1] = _letter(0, 1, "E", 1)
    board.tiles[1][1] = _letter_card(1, 1, "E", "spades", 1)
    board.tiles[2][0] = _letter_card(2, 0, "E", "clubs", 1)
    board.tiles[2][4] = _letter(2, 4, "E", 1)
    board.tiles[1][4] = _letter_card(1, 4, "D", "diamonds", 2)
    path = [23, 18, 12, 7, 1, 6, 10, 14, 9]
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[LoadoutItem(id="celestial_body", name="Celestial Body", level=2)]
    )
    score, bd = pipeline.score(board, path, "coalesced", loadout)
    base, base_bd = pipeline.score(board, path, "coalesced", Loadout())
    tiles = bd["pipeline"]["tile_scores"]
    base_tiles = base_bd["pipeline"]["tile_scores"]
    assert tiles[-1] == base_tiles[-1]
    assert sum(tiles) == sum(base_tiles) + 60
    assert score == base + 60


def test_celestial_body_duplicate_rank_only_last_gets_bonus():
    """Duplicate D letters: last suited D (+10); poker T and value-3 M also qualify."""
    board = _empty_board()
    board.tiles[0][0] = Tile(
        row=0, col=0, char="D", letter="D", base_score=2, curse=CurseType.LETTER,
        metadata={"source": "melmod", "card_suit": "diamonds", "card_rank": "D"},
    )
    board.tiles[0][1] = _letter(0, 1, "O", 1)
    board.tiles[0][2] = Tile(
        row=0, col=2, char="T", letter="T", base_score=1, curse=CurseType.LETTER,
        metadata={"source": "melmod", "card_suit": "diamonds", "card_rank": "T"},
    )
    board.tiles[0][3] = Tile(
        row=0, col=3, char="D", letter="D", base_score=2, curse=CurseType.LETTER,
        metadata={"source": "melmod", "card_suit": "hearts", "card_rank": "D"},
    )
    board.tiles[0][4] = Tile(
        row=0, col=4, char="M", letter="M", base_score=3, curse=CurseType.LETTER,
        metadata={"source": "melmod", "card_suit": "spades", "card_rank": "M"},
    )
    path = [0, 1, 2, 3, 4]
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[LoadoutItem(id="celestial_body", name="Celestial Body", level=1)]
    )
    score, bd = pipeline.score(board, path, "dotdm", loadout)
    base, base_bd = pipeline.score(board, path, "dotdm", Loadout())
    assert sum(bd["pipeline"]["tile_scores"]) == sum(base_bd["pipeline"]["tile_scores"]) + 30
    assert bd["pipeline"]["tile_scores"][0] == base_bd["pipeline"]["tile_scores"][0]
    assert bd["pipeline"]["tile_scores"][3] == base_bd["pipeline"]["tile_scores"][3] + 10
    assert bd["pipeline"]["tile_scores"][2] == base_bd["pipeline"]["tile_scores"][2] + 10
    assert bd["pipeline"]["tile_scores"][4] == base_bd["pipeline"]["tile_scores"][4] + 10
    assert score == base + 30


def test_celestial_body_l1_joker_wildcard_gets_bonus():
    board = _empty_board()
    board.tiles[0][0] = _joker_tile(0, 0, "diamonds")
    board.tiles[0][1] = _letter(0, 1, "E", 1)
    board.tiles[0][2] = _letter(0, 2, "X", 1)
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[LoadoutItem(id="celestial_body", name="Celestial Body", level=1)]
    )
    score, bd = pipeline.score(board, [0, 1, 2], "eex", loadout)
    base, base_bd = pipeline.score(board, [0, 1, 2], "eex", Loadout())
    assert bd["pipeline"]["tile_scores"][0] == base_bd["pipeline"]["tile_scores"][0] + 10
    assert score == base + 10


def test_celestial_body_l1_joker_suit_rank_i_gets_bonus():
    board = _empty_board()
    board.tiles[0][0] = Tile(
        row=0,
        col=0,
        char="i",
        letter="I",
        base_score=1,
        curse=CurseType.LETTER,
        metadata={"source": "melmod", "card_suit": "joker", "card_rank": "I"},
    )
    board.tiles[0][1] = _letter(0, 1, "T", 1)
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[LoadoutItem(id="celestial_body", name="Celestial Body", level=1)]
    )
    score, bd = pipeline.score(board, [0, 1], "it", loadout)
    base, base_bd = pipeline.score(board, [0, 1], "it", Loadout())
    assert bd["pipeline"]["tile_scores"][0] == base_bd["pipeline"]["tile_scores"][0] + 10
    assert score == base + 10


def test_celestial_body_l1_high_value_non_poker_rank_gets_bonus():
    board = _empty_board()
    board.tiles[0][0] = Tile(
        row=0,
        col=0,
        char="x",
        letter="X",
        base_score=8,
        curse=CurseType.LETTER,
        metadata={"source": "melmod", "card_suit": "spades", "card_rank": "X"},
    )
    board.tiles[0][1] = _letter(0, 1, "E", 1)
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[LoadoutItem(id="celestial_body", name="Celestial Body", level=1)]
    )
    score, bd = pipeline.score(board, [0, 1], "xe", loadout)
    base, base_bd = pipeline.score(board, [0, 1], "xe", Loadout())
    assert bd["pipeline"]["tile_scores"][0] == base_bd["pipeline"]["tile_scores"][0] + 10
    assert score == base + 10


def test_celestial_body_l3_duplicate_letter_coalesce():
    """First unsuited duplicate + last per suit; middle duplicate skipped (snash-style)."""
    board = _empty_board()
    board.tiles[0][4] = _letter_card(0, 4, "A", "spades", 1)
    board.tiles[1][4] = _letter(1, 4, "N", 1)
    board.tiles[1][3] = _letter(1, 3, "A", 1)
    board.tiles[3][1] = _letter_card(3, 1, "A", "spades", 1)
    board.tiles[0][3] = _letter_card(0, 3, "A", "hearts", 1)
    path = [4, 9, 8, 16, 3]
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[LoadoutItem(id="celestial_body", name="Celestial Body", level=3)]
    )
    score, bd = pipeline.score(board, path, "anaas", loadout)
    base, base_bd = pipeline.score(board, path, "anaas", Loadout())
    tiles = bd["pipeline"]["tile_scores"]
    assert tiles == [31.0, 1.0, 1.0, 31.0, 31.0]
    assert sum(tiles) == sum(base_bd["pipeline"]["tile_scores"]) + 90
    assert score == base + 90


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


def test_wrestlers_letter_card_endpoints_different_suits():
    """Same letter 3+ times with suited ends on different suits (chaleh-style)."""
    board = _empty_board()
    board.tiles[0][0] = _letter_card(0, 0, "E", "hearts", 1)
    board.tiles[0][1] = _letter(0, 1, "E", 1)
    board.tiles[0][2] = _letter(0, 2, "E", 1)
    board.tiles[0][3] = _letter(0, 3, "E", 1)
    board.tiles[0][4] = _letter_card(0, 4, "E", "clubs", 1)
    path = [0, 1, 2, 3, 4]
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="wrestlers", name="Wrestlers", level=1)])
    score, bd = pipeline.score(board, path, "eeeee", loadout)
    base, _ = pipeline.score(board, path, "eeeee", Loadout())
    assert bd["multiplier"] == 1.5
    assert score == int(base * 1.5)


def test_wrestlers_poker_rank_letter_endpoints():
    """Poker-rank letter cards at path ends (T/A) trigger Wrestlers."""
    board = _empty_board()
    board.tiles[2][1] = _letter_card(2, 1, "T", "clubs", 1)
    board.tiles[0][1] = _letter(0, 1, "A", 1)
    board.tiles[0][0] = _letter_card(0, 0, "A", "spades", 1)
    path = [11, 6, 0]
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="wrestlers", name="Wrestlers", level=1)])
    score, bd = pipeline.score(board, path, "tat", loadout)
    base, _ = pipeline.score(board, path, "tat", Loadout())
    assert bd["multiplier"] == 1.5
    assert score == int(base * 1.5)


def test_wrestlers_flush_all_suited_letter_endpoints():
    """All-suited path with letter endpoints on different suits triggers Wrestlers (rood)."""
    board = _empty_board()
    board.tiles[3][4] = _letter_card(3, 4, "R", "diamonds", 1)
    board.tiles[2][3] = _letter_card(2, 3, "O", "diamonds", 1)
    board.tiles[4][1] = _letter_card(4, 1, "O", "diamonds", 1)
    board.tiles[4][0] = _letter_card(4, 0, "D", "hearts", 2)
    path = [19, 13, 21, 20]
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="wrestlers", name="Wrestlers", level=1)])
    score, bd = pipeline.score(board, path, "rood", loadout)
    base, _ = pipeline.score(board, path, "rood", Loadout())
    assert bd["multiplier"] == 1.5
    assert score == int(base * 1.5)


def test_wrestlers_bones_rank_letter_endpoints_mismatch_value():
    """D/I suited ends with different tile values do not trigger Wrestlers (dooses)."""
    board = _empty_board()
    board.tiles[2][3] = _letter_card(2, 3, "D", "diamonds", 2)
    board.tiles[0][1] = _letter(0, 1, "A", 1)
    board.tiles[0][2] = _letter_card(0, 2, "I", "spades", 1)
    path = [13, 6, 2]
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="wrestlers", name="Wrestlers", level=1)])
    score, bd = pipeline.score(board, path, "dai", loadout)
    base, _ = pipeline.score(board, path, "dai", Loadout())
    assert bd["multiplier"] == 1.0
    assert score == base


def test_wrestlers_first_last_suited_not_path_endpoints():
    """Unsuited path ends; first/last suited share letter on different suits (diatheses-style)."""
    board = _empty_board()
    board.tiles[0][0] = _letter(0, 0, "T", 1)
    board.tiles[0][1] = _letter(0, 1, "I", 1)
    board.tiles[0][3] = _letter_card(0, 3, "L", "hearts", 1)
    board.tiles[0][2] = _letter_card(0, 2, "L", "spades", 1)
    board.tiles[0][4] = _letter(0, 4, "E", 1)
    path = [0, 1, 3, 2, 4]
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="wrestlers", name="Wrestlers", level=1)])
    score, bd = pipeline.score(board, path, "tille", loadout)
    base, _ = pipeline.score(board, path, "tille", Loadout())
    assert bd["multiplier"] == 1.5
    assert score == int(base * 1.5)


def test_wrestlers_unsuited_path_end_different_letter_suited_no_mult():
    """yecchs-style: path starts unsuited; first/last suited are different letters."""
    board = _empty_board()
    board.tiles[0][4] = _letter(0, 4, "Y", 4)
    board.tiles[1][1] = _letter(1, 1, "E", 1)
    board.tiles[0][3] = _letter_card(0, 3, "A", "clubs", 1)
    board.tiles[2][1] = _letter_card(2, 1, "A", "clubs", 1)
    board.tiles[1][2] = _letter_card(1, 2, "E", "hearts", 1)
    board.tiles[2][2] = _letter_card(2, 2, "R", "spades", 1)
    path = [4, 8, 3, 11, 7, 12]
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="wrestlers", name="Wrestlers", level=3)])
    score, bd = pipeline.score(board, path, "yecchs", loadout)
    base, _ = pipeline.score(board, path, "yecchs", Loadout())
    assert bd["multiplier"] == 1.0
    assert score == base


def test_wrestlers_long_word_unsuited_ends_no_mult():
    """adultresses-style: 11-tile path; endpoints unsuited, suited middle letters differ."""
    board = _empty_board()
    board.tiles[2][0] = _letter(2, 0, "A", 1)
    board.tiles[2][1] = _letter_card(2, 1, "A", "diamonds", 1)
    board.tiles[2][2] = _letter(2, 2, "U", 1)
    board.tiles[2][3] = _letter(2, 3, "T", 1)
    board.tiles[2][4] = _letter(2, 4, "E", 1)
    board.tiles[1][0] = _letter(1, 0, "L", 1)
    board.tiles[1][1] = _letter_card(1, 1, "Y", "hearts", 1)
    board.tiles[1][2] = _letter(1, 2, "L", 1)
    board.tiles[1][3] = _letter_card(1, 3, "U", "hearts", 1)
    board.tiles[1][4] = _letter_card(1, 4, "R", "spades", 1)
    board.tiles[0][0] = _letter_card(0, 0, "R", "hearts", 1)
    board.tiles[0][1] = _letter(0, 1, "O", 1)
    board.tiles[0][2] = _letter(0, 2, "I", 1)
    board.tiles[0][3] = _letter_card(0, 3, "M", "spades", 3)
    board.tiles[0][4] = _letter_card(0, 4, "E", "spades", 1)
    path = [10, 11, 12, 7, 13, 9, 14, 19, 23, 18, 4]
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="wrestlers", name="Wrestlers", level=3)])
    score, bd = pipeline.score(board, path, "adultresses", loadout)
    base, _ = pipeline.score(board, path, "adultresses", Loadout())
    assert bd["multiplier"] == 1.0
    assert score == base


def test_wrestlers_one_suited_path_endpoint_no_mult():
    """aahs-style: unsuited start, suited end; interior same-letter suited pair."""
    board = _empty_board()
    board.tiles[2][3] = _letter(2, 3, "A", 1)
    board.tiles[0][3] = _letter(0, 3, "A", 1)
    board.tiles[0][4] = _letter_card(0, 4, "O", "hearts", 1)
    board.tiles[3][2] = _letter_card(3, 2, "O", "spades", 1)
    path = [13, 3, 4, 17]
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="wrestlers", name="Wrestlers", level=3)])
    score, bd = pipeline.score(board, path, "aahs", loadout)
    base, _ = pipeline.score(board, path, "aahs", Loadout())
    assert bd["multiplier"] == 1.0
    assert score == base


def test_wrestlers_long_path_one_suited_endpoint_no_mult():
    """raphides-style: long path; unsuited R start, suited A end; interior A-A."""
    board = _empty_board()
    board.tiles[3][2] = _letter(3, 2, "R", 1)
    board.tiles[2][2] = _letter(2, 2, "A", 1)
    board.tiles[2][3] = _letter(2, 3, "P", 3)
    board.tiles[2][4] = _letter_card(2, 4, "A", "hearts", 1)
    board.tiles[1][3] = _letter(1, 3, "I", 1)
    board.tiles[0][3] = _letter(0, 3, "E", 1)
    board.tiles[2][0] = _letter(2, 0, "E", 1)
    board.tiles[2][1] = _letter_card(2, 1, "A", "spades", 1)
    path = [17, 12, 13, 14, 8, 3, 10, 11]
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="wrestlers", name="Wrestlers", level=3)])
    score, bd = pipeline.score(board, path, "raphides", loadout)
    base, _ = pipeline.score(board, path, "raphides", Loadout())
    assert bd["multiplier"] == 1.0
    assert score == base


def test_celestial_body_l3_last_suited_single_letter():
    """L3: path-end suited tile and rank-I singleton get +30."""
    board = _empty_board()
    board.tiles[0][4] = _letter(0, 4, "Y", 4)
    board.tiles[1][3] = _letter(1, 3, "E", 1)
    board.tiles[0][3] = _letter_card(0, 3, "A", "clubs", 1)
    board.tiles[2][1] = _letter_card(2, 1, "A", "clubs", 1)
    board.tiles[1][2] = _letter_card(1, 2, "E", "hearts", 1)
    board.tiles[2][2] = _letter_card(2, 2, "R", "spades", 1)
    path = [4, 8, 3, 11, 7, 12]
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[LoadoutItem(id="celestial_body", name="Celestial Body", level=3)]
    )
    score, bd = pipeline.score(board, path, "yecchs", loadout)
    base, base_bd = pipeline.score(board, path, "yecchs", Loadout())
    tiles = bd["pipeline"]["tile_scores"]
    assert tiles == [4.0, 1.0, 31.0, 31.0, 31.0, 31.0]
    assert sum(tiles) == sum(base_bd["pipeline"]["tile_scores"]) + 120
    assert score == base + 120


def test_celestial_body_l3_mid_path_last_suited_low_card():
    """klongs-style: suited L/N mid-path (last suited, not path end) get +30 at L3."""
    board = _empty_board()
    board.tiles[3][1] = _letter_card(3, 1, "K", "clubs", 5)
    board.tiles[2][2] = _letter_card(2, 2, "L", "spades", 1)
    board.tiles[1][2] = _letter(1, 2, "O", 1)
    board.tiles[2][3] = _letter_card(2, 3, "N", "diamonds", 1)
    board.tiles[3][3] = _letter_card(3, 3, "G", "hearts", 2)
    board.tiles[4][4] = _letter(4, 4, "S", 1)
    path = [16, 12, 7, 13, 18, 24]
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[LoadoutItem(id="celestial_body", name="Celestial Body", level=3)]
    )
    score, bd = pipeline.score(board, path, "klongs", loadout)
    base, base_bd = pipeline.score(board, path, "klongs", Loadout())
    tiles = bd["pipeline"]["tile_scores"]
    assert tiles == [35.0, 31.0, 1.0, 31.0, 32.0, 1.0]
    assert sum(tiles) == sum(base_bd["pipeline"]["tile_scores"]) + 120
    assert score == base + 120


def test_celestial_body_l3_base2_suited_path_end():
    """jabbed-style: suited D at path end (base 2) gets +30 at L3."""
    board = _empty_board()
    board.tiles[1][3] = _letter_card(1, 3, "J", "hearts", 8)
    board.tiles[1][4] = _letter(1, 4, "A", 1)
    board.tiles[0][4] = _letter(0, 4, "B", 3)
    board.tiles[0][2] = _letter_card(0, 2, "B", "clubs", 3)
    board.tiles[1][2] = _letter(1, 2, "E", 1)
    board.tiles[2][3] = _letter_card(2, 3, "D", "hearts", 2)
    path = [8, 9, 4, 2, 7, 13]
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[LoadoutItem(id="celestial_body", name="Celestial Body", level=3)]
    )
    score, bd = pipeline.score(board, path, "jabbed", loadout)
    base, base_bd = pipeline.score(board, path, "jabbed", Loadout())
    tiles = bd["pipeline"]["tile_scores"]
    assert tiles == [38.0, 1.0, 3.0, 33.0, 1.0, 32.0]
    assert tiles[-1] == base_bd["pipeline"]["tile_scores"][-1] + 30
    assert sum(tiles) == sum(base_bd["pipeline"]["tile_scores"]) + 90


def test_celestial_body_l3_path_start_last_suited_low_cards():
    """togging-style: suited T/O at path start (last suited, not path end) get +30 at L3."""
    board = _empty_board()
    board.tiles[1][3] = _letter_card(1, 3, "T", "clubs", 1)
    board.tiles[2][3] = _letter_card(2, 3, "O", "clubs", 1)
    board.tiles[1][4] = _letter_card(1, 4, "G", "diamonds", 2)
    board.tiles[3][0] = _letter(3, 0, "G", 2)
    board.tiles[2][1] = _letter_card(2, 1, "I", "clubs", 1)
    board.tiles[2][2] = _letter(2, 2, "N", 1)
    board.tiles[1][1] = _letter(1, 1, "G", 2)
    path = [8, 13, 9, 15, 11, 12, 6]
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[LoadoutItem(id="celestial_body", name="Celestial Body", level=3)]
    )
    score, bd = pipeline.score(board, path, "togging", loadout)
    base, base_bd = pipeline.score(board, path, "togging", Loadout())
    tiles = bd["pipeline"]["tile_scores"]
    assert tiles == [31.0, 31.0, 32.0, 2.0, 31.0, 1.0, 2.0]
    assert sum(tiles) == sum(base_bd["pipeline"]["tile_scores"]) + 120
    assert score == base + 120


def test_wrestlers_letter_card_e_endpoints_different_suits():
    """Mirrors chaleh: E clubs at start, E hearts at end, 3+ E on path."""
    board = _empty_board()
    board.tiles[1][4] = _letter_card(1, 4, "E", "clubs", 1)
    board.tiles[1][3] = _letter(1, 3, "E", 1)
    board.tiles[1][2] = _letter(1, 2, "E", 1)
    board.tiles[1][1] = _letter(1, 1, "E", 1)
    board.tiles[1][0] = _letter(1, 0, "E", 1)
    board.tiles[0][0] = _letter_card(0, 0, "E", "hearts", 1)
    path = [9, 8, 7, 6, 5, 0]
    pipeline = ScoringPipeline()
    loadout = Loadout(stickers=[LoadoutItem(id="wrestlers", name="Wrestlers", level=1)])
    score, bd = pipeline.score(board, path, "eeeee", loadout)
    base, _ = pipeline.score(board, path, "eeeee", Loadout())
    assert bd["multiplier"] == 1.5
    assert score == int(base * 1.5)


def test_yellow_glasses_path_double_not_word_string():
    """Word 'cross' has ss; path c-r-o-j-c has no consecutive duplicate."""
    board = _empty_board()
    board.tiles[0][4] = _letter_card(0, 4, "C", "clubs", 3)
    board.tiles[1][3] = _letter(1, 3, "R", 1)
    board.tiles[1][2] = _letter(1, 2, "O", 1)
    board.tiles[2][3] = _letter_card(2, 3, "J", "spades", 8)
    board.tiles[1][4] = _letter_card(1, 4, "C", "spades", 3)
    path = [4, 8, 7, 13, 9]
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[LoadoutItem(id="yellow_glasses", name="Yellow Glasses", level=1)]
    )
    score, bd = pipeline.score(board, path, "cross", loadout)
    base, _ = pipeline.score(board, path, "cross", Loadout())
    assert bd["multiplier"] == 1.0
    assert score == base


def test_yellow_glasses_skips_mixed_currency_letter_double():
    """preppy: word pp with currency then letter p — mixed source does not count."""
    board = _empty_board()
    board.tiles[0][0] = Tile(
        row=0,
        col=0,
        char="₱",
        letter="₱",
        base_score=16,
        color=TileColor.RED,
        curse=CurseType.CURRENCY,
        metadata={"source": "melmod"},
    )
    board.tiles[0][1] = _letter(0, 1, "P", 18)
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[LoadoutItem(id="yellow_glasses", name="Yellow Glasses", level=3)]
    )
    base, _ = pipeline.score(board, [0, 1], "pp", Loadout())
    score, bd = pipeline.score(board, [0, 1], "pp", loadout)
    assert bd["multiplier"] == 1.0
    assert score == base


def test_yellow_glasses_currency_pair_double():
    """bott: consecutive currency tiles with tt in the submitted word."""
    board = _empty_board()
    for col, glyph in enumerate(("₮", "₮")):
        board.tiles[0][col] = Tile(
            row=0,
            col=col,
            char=glyph,
            letter=glyph,
            base_score=16,
            color=TileColor.BLUE,
            curse=CurseType.CURRENCY,
            metadata={"source": "melmod"},
        )
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[LoadoutItem(id="yellow_glasses", name="Yellow Glasses", level=3)]
    )
    base, _ = pipeline.score(board, [0, 1], "tt", Loadout())
    score, bd = pipeline.score(board, [0, 1], "tt", loadout)
    assert bd["multiplier"] == 2.5
    assert score == int(base * 2.5)


def test_celestial_before_yellow_glasses_with_bicycle_pin():
    """Celestial +tile, then ×WORD on subtotal (sticker list order; dooses board)."""
    board = _empty_board()
    board.tiles[2][3] = _letter_card(2, 3, "D", "diamonds", 2)
    board.tiles[3][3] = _letter(3, 3, "O", 1)
    board.tiles[1][1] = _letter(1, 1, "O", 1)
    board.tiles[2][1] = _letter_card(2, 1, "U", "spades", 1)
    board.tiles[1][2] = _letter(1, 2, "E", 1)
    board.tiles[0][2] = _letter_card(0, 2, "I", "spades", 1)
    path = [13, 18, 6, 11, 7, 2]
    pipeline = ScoringPipeline()
    loadout = Loadout(
        stickers=[
            LoadoutItem(id="celestial_body", name="Celestial Body", level=1),
            LoadoutItem(id="yellow_glasses", name="Yellow Glasses", level=1),
            LoadoutItem(id="wrestlers", name="Wrestlers", level=1),
        ],
        extras={
            "pin_effect": "bicycle",
            "bicycle_word_score_bonus": "7",
            "cards_submitted": "7",
        },
        pin_branch="left",
    )
    score, bd = pipeline.score(board, path, "dooses", loadout)
    assert bd["multiplier"] == 1.5
    assert score == 55.0


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
