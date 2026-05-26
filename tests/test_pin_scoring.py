"""Pin scoring for all 11 character pins."""

from cursed_words_solver.models import (
    Board,
    CurseType,
    Loadout,
    LoadoutItem,
    Tile,
    TileColor,
)
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.rule_lookup import (
    count_scoring_items,
    get_pin_scoring_rule,
    resolve_rule_id,
)


def _tile(
    row: int,
    col: int,
    ch: str,
    score: int,
    *,
    color=TileColor.COLORLESS,
    curse=CurseType.LETTER,
    number_value=None,
    metadata=None,
) -> Tile:
    meta = {"source": "melmod"}
    if metadata:
        meta.update(metadata)
    letter = ch if len(ch) == 1 else ch
    return Tile(
        row=row,
        col=col,
        char=ch,
        letter=letter,
        base_score=score,
        color=color,
        curse=curse,
        number_value=number_value,
        metadata=meta,
    )


def _letter_board(word: str = "aaaaa") -> Board:
    grid = [[_tile(r, c, "A", 1) for c in range(5)] for r in range(5)]
    for i, ch in enumerate(word[:5]):
        grid[0][i] = _tile(0, i, ch.upper(), 1)
    return Board(tiles=grid, money=0)


def test_all_pin_aliases_resolve():
    pipeline = ScoringPipeline()
    aliases = [
        ("abacus", "abacus"),
        ("super_8", "sam_gambit"),
        ("bicycle", "bones_the_dog"),
        ("carp_streamers", "rodman"),
        ("human_hands", "human_boy"),
        ("wad_of_cash", "cretaceous_meg"),
    ]
    for alias, canonical in aliases:
        assert resolve_rule_id(pipeline.rules, "pins", alias, "") == canonical


def test_abacus_pin_left_scatter_numbers_on_manual_board():
    from cursed_words_solver.encounter_board import effective_board_for_loadout

    pipeline = ScoringPipeline()
    grid = [[_tile(r, c, "A", 1) for c in range(5)] for r in range(5)]
    for row in grid:
        for t in row:
            t.metadata.pop("source", None)
    board = Board(tiles=grid, money=0)
    lo = Loadout(
        extras={
            "pin_effect": "abacus",
            "pin_left_level": "2",
            "grid_number": "1",
        }
    )
    effective = effective_board_for_loadout(board, lo, pipeline.rules)
    numbers = [
        t
        for t in effective.flat
        if t.number_value is not None and 1 <= t.number_value <= 5
    ]
    assert len(numbers) >= 1


def test_grid_only_pins_no_word_score_change():
    pipeline = ScoringPipeline()
    board = _letter_board()
    path = [0, 1, 2]
    base, _ = pipeline.score(board, path, "aaa", Loadout())
    for pin in ("rodman", "milky_way", "bucket"):
        lo = Loadout(extras={"pin_effect": pin})
        score, _ = pipeline.score(board, path, "aaa", lo)
        assert score == base


def test_mahjong_consumable_multiply():
    pipeline = ScoringPipeline()
    board = Board(
        tiles=[
            [
                _tile(
                    0,
                    0,
                    "X",
                    10,
                    metadata={"consumable": True},
                ),
                _tile(0, 1, "A", 1),
                _tile(0, 2, "B", 1),
            ]
            + [_tile(0, c, "C", 1) for c in range(3, 5)]
        ]
        + [[_tile(r, c, "D", 1) for c in range(5)] for r in range(1, 5)],
        money=0,
    )
    lo = Loadout(
        extras={
            "pin_effect": "mahjong_red_dragon",
            "pin_right_level": "1",
        }
    )
    score, bd = pipeline.score(board, [0], "X", lo)
    assert score == 30.0  # 10 base × 3 factor
    assert any("consumable" in e for e in bd["pipeline"]["effects"])


def test_super_8_chess_take_bonus():
    pipeline = ScoringPipeline()
    grid = [[_tile(r, c, "D", 1) for c in range(5)] for r in range(5)]
    grid[4][2] = _tile(
        4,
        2,
        "?",
        1,
        curse=CurseType.CHESS_PAWN,
        metadata={"chess_color": "white"},
    )
    grid[3][3] = _tile(
        3,
        3,
        "?",
        1,
        curse=CurseType.CHESS_PAWN,
        metadata={"chess_color": "black"},
    )
    grid[3][4] = _tile(3, 4, "A", 1)
    board = Board(tiles=grid, money=0)
    path = [22, 18, 19]

    lo = Loadout(extras={"pin_effect": "sam_gambit", "pin_right_level": "1"})
    score, bd = pipeline.score(board, path, "PAA", lo)
    assert bd["pipeline"]["word_score"] == 8
    assert score == 11.0  # 3 tile base + 8 take bonus

    lo2 = Loadout(extras={"pin_effect": "sam_gambit", "pin_right_level": "2"})
    score2, bd2 = pipeline.score(board, path, "PAA", lo2)
    assert bd2["pipeline"]["word_score"] == 16
    assert score2 == 19.0  # 3 tile base + 16 take bonus (1 right upgrade)

    lo3 = Loadout(extras={"pin_effect": "sam_gambit", "pin_right_level": "3"})
    score3, bd3 = pipeline.score(board, path, "PAA", lo3)
    assert bd3["pipeline"]["word_score"] == 8
    assert score3 == 11.0  # 2 right upgrades: alternates back to +8


def test_super_8_no_bonus_for_pawn_forward_move():
    """Regression: volvox path starts on pawn and moves forward — not a take."""
    pipeline = ScoringPipeline()
    grid = [[_tile(r, c, "D", 1) for c in range(5)] for r in range(5)]
    grid[4][0] = _tile(
        4,
        0,
        "?",
        1,
        curse=CurseType.CHESS_PAWN,
        metadata={"chess_color": "white"},
    )
    grid[3][0] = _tile(3, 0, "O", 1)
    grid[3][1] = _tile(3, 1, "L", 1)
    grid[2][1] = _tile(2, 1, "V", 4)
    grid[1][1] = _tile(1, 1, "O", 1)
    grid[1][2] = _tile(1, 2, "X", 8)
    board = Board(tiles=grid, money=0)
    path = [20, 15, 16, 11, 6, 7]

    lo = Loadout(extras={"pin_effect": "super_8", "pin_right_level": "1"})
    score, bd = pipeline.score(board, path, "volvox", lo)
    assert bd["pipeline"]["word_score"] == 0
    assert score == 16.0


def test_bicycle_cards_submitted_base_right_track():
    """Mirrors zooier/weakness: accumulated WordScoreBonus, no suited cards on path."""
    pipeline = ScoringPipeline()
    board = _letter_board("abc")
    lo = Loadout(
        extras={
            "pin_effect": "bicycle",
            "pin_left_level": "1",
            "pin_right_level": "1",
            "bicycle_word_score_bonus": "1",
        }
    )
    score, bd = pipeline.score(board, [0, 1, 2], "abc", lo)
    assert bd["pipeline"]["word_score"] == 1
    assert score == 4.0  # 3 tile base + 1 word


def test_bicycle_zoonymy_two_suited_cards_on_path():
    """Mirrors zoonymy: Bicycle acc 1 + 2 suited, yellow glasses ×1.5 on 24+3."""
    pipeline = ScoringPipeline()
    scores = [10, 1, 1, 1, 4, 3, 4]
    letters = "ZOONYMY"
    grid = [[_tile(r, c, "X", 1) for c in range(5)] for r in range(5)]
    path: list[int] = []
    coords = [(0, 0), (0, 1), (0, 2), (0, 3), (0, 4), (1, 0), (1, 1)]
    for (row, col), ch, sc in zip(coords, letters, scores, strict=True):
        meta: dict = {"source": "melmod"}
        if ch == "Z":
            meta["card_suit"] = "hearts"
            meta["card_rank"] = "Z"
        elif ch == "O" and col == 1 and row == 0:
            meta["card_suit"] = "spades"
            meta["card_rank"] = "O"
        grid[row][col] = _tile(row, col, ch, sc, metadata=meta)
        path.append(row * 5 + col)
    board = Board(tiles=grid, money=9)
    lo = Loadout(
        character="Bones The Dog",
        stickers=[LoadoutItem(id="yellow_glasses", name="Yellow Glasses", level=1)],
        extras={
            "pin_effect": "bicycle",
            "pin_left_level": "2",
            "pin_right_level": "1",
            "bicycle_word_score_bonus": 1,
        },
    )
    score, bd = pipeline.score(board, path, "zoonymy", lo)
    assert int(score) == 40


def test_bicycle_suited_count_from_melmod_extra():
    pipeline = ScoringPipeline()
    board = _letter_board("abc")
    lo = Loadout(
        extras={
            "pin_effect": "bicycle",
            "pin_right_level": "1",
            "bicycle_word_score_bonus": 1,
            "bicycle_suited_on_path": 2,
        }
    )
    score, bd = pipeline.score(board, [0, 1, 2], "abc", lo)
    assert bd["pipeline"]["word_score"] == 3
    assert score == 6.0


def test_bicycle_suited_cards_on_path():
    pipeline = ScoringPipeline()
    grid = [[_tile(0, c, "A", 1) for c in range(5)] for _ in range(5)]
    grid[0][0] = _tile(
        0,
        0,
        "A",
        1,
        metadata={"source": "melmod", "card_suit": "hearts"},
    )
    grid[0][1] = _tile(
        0,
        1,
        "K",
        1,
        metadata={"source": "melmod", "card_suit": "spades"},
    )
    grid[0][2] = _tile(0, 2, "Q", 1, metadata={"source": "melmod", "card_suit": "clubs"})
    board = Board(tiles=grid, money=0)
    lo = Loadout(
        extras={
            "pin_effect": "bones_the_dog",
            "pin_right_level": "2",
            "bicycle_word_score_bonus": "0",
        }
    )
    score, bd = pipeline.score(board, [0, 1, 2], "abc", lo)
    # pin_right 2 → +2 per suited card; 3 suited on path = 6 word; + 3 tile base
    assert bd["pipeline"]["word_score"] == 6
    assert score == 9.0


def test_bicycle_hadjees_multi_suit_same_rank_counts_tiles():
    """Regression: hadjees path awards +1 per suited tile on path (3 suited tiles)."""
    pipeline = ScoringPipeline()
    grid = [[_tile(r, c, "X", 1) for c in range(5)] for r in range(5)]
    path: list[int] = []
    tiles = [
        (2, 3, "H", 4, {"card_suit": "hearts", "card_rank": "H"}),
        (3, 2, "A", 1, {}),
        (2, 2, "E", 1, {"card_suit": "diamonds", "card_rank": "E"}),
        (1, 1, "J", 8, {}),
        (2, 1, "E", 1, {}),
        (2, 0, "E", 1, {}),
        (3, 0, "E", 1, {"card_suit": "spades", "card_rank": "E"}),
    ]
    for row, col, ch, sc, meta in tiles:
        grid[row][col] = _tile(row, col, ch, sc, metadata=meta)
        path.append(row * 5 + col)
    board = Board(tiles=grid, money=1)
    lo = Loadout(
        extras={
            "pin_effect": "bicycle",
            "pin_right_level": "1",
            "pin_right_variable": "1",
            "bicycle_word_score_bonus": "5",
        }
    )
    score, bd = pipeline.score(board, path, "hadjees", lo)
    assert bd["pipeline"]["word_score"] == 8
    assert int(score) == 25


def test_bicycle_ricinolic_single_suit_multi_rank_counts_one():
    """Regression: ricinolic — A/L/G all clubs on path → 1 suited credit."""
    pipeline = ScoringPipeline()
    grid = [[_tile(r, c, "X", 1) for c in range(5)] for r in range(5)]
    path: list[int] = []
    tiles = [
        (4, 1, "R", 1, {}),
        (3, 2, "I", 1, {}),
        (3, 3, "A", 1, {"card_suit": "clubs", "card_rank": "A"}),
        (2, 2, "I", 1, {}),
        (2, 3, "N", 1, {}),
        (1, 2, "O", 1, {}),
        (1, 3, "L", 1, {"card_suit": "clubs", "card_rank": "L"}),
        (2, 4, "I", 1, {}),
        (3, 4, "G", 2, {"card_suit": "clubs", "card_rank": "G"}),
    ]
    for row, col, ch, sc, meta in tiles:
        grid[row][col] = _tile(row, col, ch, sc, metadata=meta)
        path.append(row * 5 + col)
    board = Board(tiles=grid, money=1)
    lo = Loadout(
        extras={
            "pin_effect": "bicycle",
            "pin_right_level": "1",
            "pin_right_variable": "1",
            "bicycle_word_score_bonus": "4",
        }
    )
    score, bd = pipeline.score(board, path, "ricinolic", lo)
    assert bd["pipeline"]["word_score"] == 5
    assert int(score) == 15


def test_ram_replays_memory_items():
    pipeline = ScoringPipeline()
    board = _letter_board("cat")
    lo = Loadout(
        extras={
            "pin_effect": "random_access_memory",
            "pin_memory": [
                {"id": "tombstone", "name": "Tombstone", "kind": "sticker", "level": 1},
            ],
        }
    )
    score, bd = pipeline.score(board, [0, 1, 2], "cat", lo)
    assert any("RAM" in e for e in bd["pipeline"]["effects"])


def test_human_hands_favourite_boost():
    pipeline = ScoringPipeline()
    board = Board(
        tiles=[
            [
                _tile(0, 0, "4", 4, curse=CurseType.NUMBER, number_value=4),
                _tile(0, 1, "5", 5, curse=CurseType.NUMBER, number_value=5),
                _tile(0, 2, "6", 6, curse=CurseType.NUMBER, number_value=6),
            ]
            + [_tile(0, c, "A", 1) for c in range(3, 5)]
        ]
        + [[_tile(r, c, "B", 1) for c in range(5)] for r in range(1, 5)],
        money=0,
    )
    lo = Loadout(
        stickers=[LoadoutItem(id="brain", name="Brain", level=1, kind="sticker")],
        stamps=[LoadoutItem(id="newspaper", name="Newspaper", kind="stamp")],
        extras={
            "pin_effect": "human_boy",
            "pin_left_level": "0",
            "pin_right_level": "1",
            "favourite_sticker_id": "brain",
            "favourite_stamp_id": "newspaper",
        },
    )
    score, bd = pipeline.score(board, [0, 1, 2], "456", lo)
    assert bd["pipeline"]["word_score"] >= 8
    assert any("Human Hands" in e for e in bd["pipeline"]["effects"])


def test_pin_scoring_counts_include_scoring_pins():
    pipeline = ScoringPipeline()
    lo = Loadout(extras={"pin_effect": "sam_gambit"})
    scoring, total, grid_only = count_scoring_items(pipeline.rules, lo)
    assert scoring == 1
    assert total == 1
    assert grid_only == 0

    lo_grid = Loadout(extras={"pin_effect": "rodman"})
    scoring_g, total_g, grid_only_g = count_scoring_items(pipeline.rules, lo_grid)
    assert scoring_g == 0
    assert grid_only_g == 1


def test_super_8_pin_right_variable_overrides_level_heuristic():
    pipeline = ScoringPipeline()
    grid = [[_tile(r, c, "D", 1) for c in range(5)] for r in range(5)]
    grid[4][2] = _tile(
        4,
        2,
        "?",
        1,
        curse=CurseType.CHESS_PAWN,
        metadata={"chess_color": "white"},
    )
    grid[3][3] = _tile(
        3,
        3,
        "?",
        1,
        curse=CurseType.CHESS_PAWN,
        metadata={"chess_color": "black"},
    )
    grid[3][4] = _tile(3, 4, "A", 1)
    board = Board(tiles=grid, money=0)
    path = [22, 18, 19]
    lo = Loadout(
        extras={
            "pin_effect": "sam_gambit",
            "pin_right_level": "3",
            "pin_right_variable": "24",
        }
    )
    score, bd = pipeline.score(board, path, "PAA", lo)
    assert bd["pipeline"]["word_score"] == 24
    assert score == 27.0


def test_both_pin_tracks_independent_of_branch():
    """Left/right levels apply together; pin_branch does not gate scoring."""
    pipeline = ScoringPipeline()
    rule = get_pin_scoring_rule(pipeline.rules, "bones_the_dog")
    assert rule is not None
    assert rule["type"] == "cards_submitted_word_bonus"

    grid = [[_tile(0, c, "A", 1) for c in range(5)] for _ in range(5)]
    grid[0][0] = _tile(
        0, 0, "A", 1, metadata={"source": "melmod", "card_suit": "hearts"}
    )
    grid[0][1] = _tile(
        0, 1, "K", 1, metadata={"source": "melmod", "card_suit": "spades"}
    )
    board = Board(tiles=grid, money=0)
    lo = Loadout(
        pin_branch="left",
        extras={
            "pin_effect": "bones_the_dog",
            "pin_left_level": "2",
            "pin_right_level": "1",
            "bicycle_word_score_bonus": "0",
        },
    )
    _, bd = pipeline.score(board, [0, 1], "aa", lo)
    assert bd["pipeline"]["word_score"] == 2  # +1 per suited card × 2 on path
