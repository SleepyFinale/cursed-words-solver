"""Pin scoring for all 11 character pins."""

import pytest

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


def test_wad_of_cash_pin_right_variable_per_currency_tile():
    """Regression: melmod pin_right_variable=20 → +20 per currency tile, not catalog +10."""
    pipeline = ScoringPipeline()
    grid = [[_tile(r, c, "A", 1) for c in range(5)] for r in range(5)]
    grid[2][1] = _tile(2, 1, "₲", 0, curse=CurseType.CURRENCY)
    grid[2][2] = _tile(2, 2, "M", 3, curse=CurseType.LETTER)
    grid[2][3] = _tile(2, 3, "₱", 0, curse=CurseType.CURRENCY)
    grid[1][2] = _tile(1, 2, "E", 1, curse=CurseType.LETTER)
    board = Board(tiles=grid, money=8)
    path = [11, 12, 13, 7]
    lo = Loadout(
        extras={
            "pin_effect": "wad_of_cash",
            "pin_left_level": "3",
            "pin_right_level": "2",
            "pin_right_variable": "20",
        }
    )
    score, bd = pipeline.score(board, path, "game", lo)
    assert any("+40 currency tile score (2)" in e for e in bd["pipeline"]["effects"])
    assert int(score) == 44


def test_wad_of_cash_game_mismatch_replay_scores_344():
    """Regression 20260620_224601: upgraded Wad of Cash + sticker mult stack."""
    import json
    from pathlib import Path

    from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
    from tests.regression.test_scoring_mismatches import (
        _bank_money_for_replay,
        _run_state_for_replay,
    )

    fixture = (
        Path(__file__).resolve().parents[0]
        / "fixtures"
        / "mismatches"
        / "20260620_224601.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    run_state = _run_state_for_replay(data)
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    path = data["path"]
    word = data["word"]
    replay_money = _bank_money_for_replay(data, board, path, loadout)
    if replay_money is not None:
        board.money = max(board.money, replay_money)
        loadout.money = max(loadout.money, replay_money)

    score, _bd = ScoringPipeline().score(board, path, word, loadout)
    assert int(score) == data["actual_score"]


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


def test_bicycle_suited_count_from_board_metadata():
    pipeline = ScoringPipeline()
    grid = [[_tile(0, c, "A", 1) for c in range(5)] for _ in range(5)]
    grid[0][0] = _tile(
        0, 0, "A", 1, metadata={"source": "melmod", "card_suit": "hearts"},
    )
    grid[0][1] = _tile(
        0, 1, "B", 1, metadata={"source": "melmod", "card_suit": "spades"},
    )
    board = Board(tiles=grid, money=0)
    lo = Loadout(
        extras={
            "pin_effect": "bicycle",
            "pin_right_level": "1",
            "bicycle_word_score_bonus": 1,
        }
    )
    score, bd = pipeline.score(board, [0, 1], "ab", lo)
    assert bd["pipeline"]["word_score"] == 3
    assert score == 5.0


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
    """Regression: hadjees — acc 5 + 2 unique suited ranks (H, E), not per-tile."""
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
    assert bd["pipeline"]["word_score"] == 7
    assert int(score) == 24


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


def test_bicycle_stale_warning_when_extras_differ_from_fingerprint():
    from cursed_words_solver.loadout import bicycle_extras_stale_warning

    fp = "Bones The Dog|9||-|bicycle:left|34"
    lo = Loadout(
        extras={
            "pin_effect": "bicycle",
            "bicycle_word_score_bonus": "35",
            "loadout_fingerprint": fp,
        }
    )
    warn = bicycle_extras_stale_warning(lo)
    assert warn is not None
    assert "35" in warn
    assert "34" in warn


def test_bicycle_extras_ahead_of_stale_fingerprint_suffix():
    """Regression snash: extras=35, fingerprint|34 → 35+4 suited, ×2.5 wrestlers = 260."""
    pipeline = ScoringPipeline()
    grid = [[_tile(r, c, "X", 1) for c in range(5)] for r in range(5)]
    configs = [
        (0, 0, "S", 2, {"card_suit": "spades", "card_rank": "S"}),
        (0, 1, "N", 2, {"card_suit": "spades", "card_rank": "N"}),
        (0, 2, "A", 0, {}),
        (0, 3, "H", 50, {"card_suit": "hearts", "card_rank": "H"}),
        (0, 4, "Q", 11, {"card_suit": "hearts", "card_rank": "Q"}),
    ]
    path: list[int] = []
    for row, col, ch, sc, meta in configs:
        grid[row][col] = _tile(row, col, ch, sc, metadata=meta)
        path.append(row * 5 + col)
    board = Board(tiles=grid, money=9)
    fp = (
        "Bones The Dog|9|joker:2,postal_horn:2,hanafuda:1,wrestlers:2,poker_face:0|"
        "card_shark:0,full_moon:0,martini:0,haunted_mirror:0|fox|bicycle:left|34"
    )
    lo = Loadout(
        character="Bones The Dog",
        stickers=[LoadoutItem(id="wrestlers", name="Wrestlers", level=3)],
        boss_id="fox",
        extras={
            "pin_effect": "bicycle",
            "pin_left_level": "4",
            "pin_right_level": "1",
            "pin_right_variable": "1",
            "bicycle_word_score_bonus": "35",
            "cards_submitted": "35",
            "loadout_fingerprint": fp,
        },
    )
    score, bd = pipeline.score(board, path, "snahq", lo)
    assert bd["pipeline"]["word_score"] == 39
    assert int(score) == 260


def test_bicycle_stale_fingerprint_pre_word_acc_didder():
    """Regression didder: extras=11, fingerprint|9, +1 suited, Peacock x2 → 42."""
    pipeline = ScoringPipeline()
    grid = [[_tile(r, c, "X", 1) for c in range(5)] for r in range(5)]
    configs = [
        (2, 4, "Y", 4, {"card_suit": "diamonds", "card_rank": "Y"}),
        (3, 3, "I", 1, {}),
        (2, 2, "T", 1, {"card_suit": "diamonds", "card_rank": "T"}),
        (2, 1, "E", 1, {"card_suit": "diamonds", "card_rank": "E"}),
        (0, 2, "E", 1, {}),
        (1, 2, "R", 1, {}),
    ]
    path: list[int] = []
    for row, col, ch, sc, meta in configs:
        grid[row][col] = _tile(row, col, ch, sc, metadata=meta)
        path.append(row * 5 + col)
    board = Board(tiles=grid, money=9)
    fp = (
        "Bones The Dog|9|postal_horn:0,peacock:0|"
        "martini:0,full_moon:0,card_shark:0|-|bicycle:left|9"
    )
    lo = Loadout(
        character="Bones The Dog",
        stickers=[
            LoadoutItem(id="postal_horn", name="Postal Horn", level=1),
            LoadoutItem(id="peacock", name="Peacock", level=1),
        ],
        stamps=[
            LoadoutItem(id="martini", name="Martini", level=1),
            LoadoutItem(id="full_moon", name="Full Moon", level=1),
            LoadoutItem(id="card_shark", name="Card Shark", level=1),
        ],
        extras={
            "pin_effect": "bicycle",
            "pin_left_level": "4",
            "pin_right_level": "1",
            "pin_right_variable": "1",
            "bicycle_word_score_bonus": "11",
            "cards_submitted": "11",
            "bicycle_suited_on_path": "1",
            "loadout_fingerprint": fp,
        },
    )
    score, bd = pipeline.score(board, path, "didder", lo)
    assert bd["pipeline"]["word_score"] == 12
    assert int(score) == 42


def test_rewind_setup_does_not_cache_neapolitan_without_stamp():
    from cursed_words_solver.rules.scoring_conditions import rewind_setup_extras

    board = _letter_board("abc")
    lo = Loadout(extras={"neapolitan_percent": "155"})
    notes = rewind_setup_extras(lo, board)
    assert not any("neapolitan baseline cached" in n for n in notes)
    assert "neapolitan_percent_last_known" not in (lo.extras or {})


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


def test_human_hands_favourite_sticker_left_variable_boost():
    """Favourite sticker uses pin_left_variable as level boost during sticker pass."""
    pipeline = ScoringPipeline()
    grid = [[_tile(r, c, "A", 1) for c in range(5)] for r in range(5)]
    grid[0][0] = _tile(0, 0, "B", 3)
    grid[0][1] = _tile(0, 1, "R", 1)
    grid[0][2] = _tile(0, 2, "R", 1)
    grid[0][3] = _tile(0, 3, "E", 1)
    grid[0][4] = _tile(0, 4, "E", 1)
    board = Board(tiles=grid, money=0)
    path = [0, 1, 2, 3, 4]
    boosted = Loadout(
        stickers=[LoadoutItem(id="yellow_glasses", name="Yellow Glasses", level=2)],
        extras={
            "pin_effect": "human_hands",
            "pin_left_variable": "1",
            "favourite_sticker_id": "yellow_glasses",
        },
    )
    plain = Loadout(
        stickers=[LoadoutItem(id="yellow_glasses", name="Yellow Glasses", level=2)],
        extras={"pin_effect": ""},
    )
    score_boost, _ = pipeline.score(board, path, "bree", boosted)
    score_plain, _ = pipeline.score(board, path, "bree", plain)
    assert score_boost > score_plain
    assert int(score_boost) == 17
    assert int(score_plain) == 14


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


def test_human_hands_favourite_stamp_inferred_from_stamp_order():
    from cursed_words_solver.loadout import parse_run_state
    from cursed_words_solver.rules.scoring_conditions import human_hands_favourite_stamp_slug

    loadout = parse_run_state(
        {
            "character": "Human Boy",
            "stickers": [],
            "stamps": [
                {"id": "right_hand", "name": "Right Hand", "level": 1},
                {"id": "dango", "name": "Dango", "level": 1},
            ],
            "extras": {
                "pin_effect": "human_hands",
                "stamp_order": '["right_hand","dango"]',
            },
        }
    )
    assert human_hands_favourite_stamp_slug(loadout) == "dango"
    assert loadout.extras.get("favourite_stamp_id") == "dango"


@pytest.mark.parametrize(
    ("fixture_name", "expected_score"),
    [
        ("20260621_114547.json", 22590),
        ("20260621_114839.json", 25803),
    ],
)
def test_human_hands_dango_mismatch_replay(fixture_name, expected_score):
    """Human Hands replays favourite stamp (dango) once when pin_right_variable=2."""
    import json
    from pathlib import Path

    from cursed_words_solver.loadout import (
        parse_board_from_run_state,
        parse_run_state,
    )
    from tests.regression.test_scoring_mismatches import _run_state_for_replay

    fixture = (
        Path(__file__).resolve().parent / "fixtures" / "mismatches" / fixture_name
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    run_state = _run_state_for_replay(data)
    loadout = parse_run_state(run_state)
    assert loadout.extras.get("favourite_stamp_id") == "dango"
    board = parse_board_from_run_state(run_state)
    pipeline = ScoringPipeline()
    score, bd = pipeline.score(board, data["path"], data["word"], loadout)
    assert score == data["actual_score"] == expected_score
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


def test_bicycle_ashy_joker_multi_suit_scores_1100():
    """Regression 20260530_005432: joker start + multi-suit path, ×20 mult stack."""
    import json
    from pathlib import Path

    from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state

    fixture = (
        Path(__file__).resolve().parents[0]
        / "fixtures"
        / "mismatches"
        / "20260530_005432.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    run_state = data["run_state_snapshot"]
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    path = data["path"]
    word = data["word"]

    score, bd = ScoringPipeline().score(board, path, word, loadout)
    assert bd["pipeline"]["word_score"] == 46.0
    assert int(score) == 1100


def test_bicycle_godsons_two_jokers_multi_suit_scores_1080():
    """Regression 20260530_010221: two jokers + multi-suit path, ×20 mult stack."""
    import json
    from pathlib import Path

    from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state

    fixture = (
        Path(__file__).resolve().parents[0]
        / "fixtures"
        / "mismatches"
        / "20260530_010221.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    run_state = data["run_state_snapshot"]
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    path = data["path"]
    word = data["word"]

    score, bd = ScoringPipeline().score(board, path, word, loadout)
    assert bd["pipeline"]["word_score"] == 47.0
    assert int(score) == 1080


def test_bicycle_ass_joker_two_spades_scores_1980():
    """Regression 20260530_010829: Wrestlers + mono-suit joker path, ×30 mult stack."""
    import json
    from pathlib import Path

    from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state

    fixture = (
        Path(__file__).resolve().parents[0]
        / "fixtures"
        / "mismatches"
        / "20260530_010829.json"
    )
    data = json.loads(fixture.read_text(encoding="utf-8"))
    run_state = data["run_state_snapshot"]
    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    path = data["path"]
    word = data["word"]

    score, bd = ScoringPipeline().score(board, path, word, loadout)
    assert bd["pipeline"]["word_score"] == 55.0
    assert int(score) == 1980
    assert any("word_starts_ends_different_suit" in e for e in bd["pipeline"]["effects"])


def test_rack_tile_from_entry_preserves_card_suit():
    from cursed_words_solver.consumable_placement import rack_tile_from_entry
    from cursed_words_solver.rules.scoring_conditions import card_rank, card_suit

    tile = rack_tile_from_entry(
        {
            "rack_index": 1,
            "letter": "R",
            "char_display": "r",
            "color": "colorless",
            "curse": "letter",
            "base_score": 1.0,
            "card_suit": "hearts",
            "card_rank": "R",
        }
    )
    assert tile is not None
    assert card_suit(tile) == "hearts"
    assert card_rank(tile) == "R"


def test_bicycle_consumable_placement_rack_card_suit_bizarre():
    """Regression bizarre f8#1628: placed rack R must carry hearts for Bicycle credit."""
    from cursed_words_solver.consumable_placement import (
        apply_consumable_placements,
        rack_tile_from_entry,
    )
    from cursed_words_solver.rules.scoring_conditions import (
        bicycle_suited_credit_on_path,
        card_suit,
    )

    grid = [[_tile(r, c, "X", 1) for c in range(5)] for r in range(5)]
    configs = [
        (3, 2, "B", 3, {"card_suit": "hearts", "card_rank": "B"}),
        (2, 1, "I", 1, {}),
        (3, 0, "Z", 10, {}),
        (2, 0, "A", 1, {}),
        (1, 1, "R", 1, {}),
        (1, 2, "L", 1, {}),
        (0, 3, "E", 1, {"card_suit": "diamonds", "card_rank": "E"}),
    ]
    path: list[int] = []
    for row, col, ch, sc, meta in configs:
        grid[row][col] = _tile(row, col, ch, sc, metadata=meta)
        path.append(row * 5 + col)
    board = Board(tiles=grid, money=0)
    placement_index = 7

    rack_plain = rack_tile_from_entry(
        {
            "rack_index": 1,
            "letter": "R",
            "char_display": "r",
            "color": "colorless",
            "curse": "letter",
            "base_score": 1.0,
            "card_suit": "",
            "card_rank": "",
        }
    )
    rack_suited = rack_tile_from_entry(
        {
            "rack_index": 1,
            "letter": "R",
            "char_display": "r",
            "color": "colorless",
            "curse": "letter",
            "base_score": 1.0,
            "card_suit": "hearts",
            "card_rank": "R",
        }
    )
    assert rack_plain is not None and rack_suited is not None

    plain_board = apply_consumable_placements(board, [(placement_index, rack_plain)])
    suited_board = apply_consumable_placements(board, [(placement_index, rack_suited)])

    placed_plain = plain_board.get_by_index(placement_index)
    placed_suited = suited_board.get_by_index(placement_index)
    assert card_suit(placed_plain) is None
    assert card_suit(placed_suited) == "hearts"

    suited_plain = bicycle_suited_credit_on_path(plain_board, path)
    suited_hearts = bicycle_suited_credit_on_path(suited_board, path)
    assert suited_hearts == suited_plain + 1

    lo = Loadout(
        character="Bones The Dog",
        stamps=[
            LoadoutItem(id="golden_record", name="Golden Record", level=1),
            LoadoutItem(id="tile_ninja", name="Tile Ninja", level=1),
        ],
        boss_id="robo_monkey",
        extras={
            "pin_effect": "bicycle",
            "pin_right_level": "1",
            "pin_right_variable": "1",
            "bicycle_word_score_bonus": "3",
            "tile_ninja_word_bonus_percent": "122",
            "tile_ninja_consumables_used": "1",
        },
    )
    pipeline = ScoringPipeline()
    score_plain, bd_plain = pipeline.score(plain_board, path, "bizarre", lo)
    score_suited, bd_suited = pipeline.score(suited_board, path, "bizarre", lo)
    assert bd_suited["pipeline"]["word_score"] == bd_plain["pipeline"]["word_score"] + 1.0
    assert int(score_suited) > int(score_plain)


def test_bicycle_fingerprint_no_downgrade_beefed():
    """July 8 beefed: fresher extras acc must not be downgraded by stale fingerprint."""
    from cursed_words_solver.loadout import align_bicycle_extras_from_fingerprint

    fp = "Bones The Dog|0||golden_record:1,tile_ninja:1|robo_monkey|bicycle:left|5"
    extras = {
        "pin_effect": "bicycle",
        "bicycle_word_score_bonus": "6",
        "cards_submitted": "6",
        "loadout_fingerprint": fp,
    }
    lo = Loadout(character="Bones The Dog", extras=dict(extras))
    align_bicycle_extras_from_fingerprint(extras, lo)
    assert extras["bicycle_word_score_bonus"] == "6"
    assert extras["cards_submitted"] == "6"
