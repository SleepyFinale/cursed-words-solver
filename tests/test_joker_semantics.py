"""Joker wildcard semantics vs in-game scoring (mismatch 20260526_143052)."""

import json
from pathlib import Path

from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
from cursed_words_solver.models import Board, CurseType, Loadout, LoadoutItem, Tile, TileColor
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.scoring_conditions import (
    get_x_of_a_kind_letters,
    hanafuda_hand_satisfied,
    rewind_bicycle_pre_word_extras,
    unique_suited_suits_on_path_count,
    unused_cards_on_board,
    word_starts_ends_different_suit,
    word_starts_with_face_card,
)
from cursed_words_solver.rules.rule_lookup import get_pin_scoring_rule

FIXTURE_SH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "mismatches"
    / "20260526_143052.json"
)
FIXTURE_SCOURERS = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "mismatches"
    / "20260526_143621.json"
)
FIXTURE_HYKE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "mismatches"
    / "20260526_144812.json"
)
FIXTURE_ICH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "mismatches"
    / "20260526_145218.json"
)
FIXTURE_JA = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "mismatches"
    / "20260526_145808.json"
)
FIXTURE_CLY = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "mismatches"
    / "20260526_150342.json"
)
FIXTURE_DEV = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "mismatches"
    / "20260526_150823.json"
)
FIXTURE_TINA = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "mismatches"
    / "20260526_231158.json"
)
FIXTURE_KHEDA = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "mismatches"
    / "20260526_231923.json"
)
FIXTURE_AAH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "mismatches"
    / "20260526_234220.json"
)
FIXTURE_YINCE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "mismatches"
    / "20260527_013139_yince.json"
)
FIXTURE_ALHIDADE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "mismatches"
    / "20260530_011426.json"
)


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
        letter=ch if len(ch) == 1 else ch,
        base_score=float(score),
        color=color,
        curse=curse,
        metadata=meta,
    )


def test_joker_glyph_parsed_as_wildcard():
    run_state = {
        "money": 0,
        "board": {
            "source": "melmod",
            "row_order": "top_first",
            "rows": 5,
            "cols": 5,
            "tiles": [
                {
                    "row": r,
                    "col": c,
                    "char": ("🃏︎" if (r, c) == (0, 2) else "A"),
                    "letter": ("G" if (r, c) == (0, 2) else "A"),
                    "base_score": (0.0 if (r, c) == (0, 2) else 1.0),
                    "color": "colorless",
                    "curse": "letter",
                    "active": True,
                    "is_joker": False,
                    "card_suit": "",
                    "card_rank": "",
                }
                for r in range(5)
                for c in range(5)
            ],
        },
        "extras": {"board_from_melmod": "true"},
    }
    board = parse_board_from_run_state(run_state)
    assert board is not None
    joker = board.get(0, 2)
    assert joker is not None
    assert joker.curse == CurseType.WILDCARD
    assert joker.metadata.get("is_joker") is True


def test_joker_start_poker_face_not_wrestlers_one_suited_for_bicycle():
    """Path [2,7] = joker glyph + H hearts: game scored 52, not 80."""
    grid = [[_tile(r, c, "A", 1) for c in range(5)] for r in range(5)]
    grid[0][2] = _tile(
        0,
        2,
        "🃏",
        0,
        curse=CurseType.WILDCARD,
        metadata={"is_joker": True},
    )
    grid[1][2] = _tile(
        1,
        2,
        "H",
        4,
        metadata={"card_suit": "hearts", "card_rank": "H"},
    )
    board = Board(tiles=grid, money=0)
    path = [2, 7]

    assert word_starts_with_face_card(board, path)
    assert not word_starts_ends_different_suit(board, path)
    assert unique_suited_suits_on_path_count(board, path) == 1

    loadout = Loadout(
        extras={
            "pin_effect": "bicycle",
            "pin_left_level": "2",
            "pin_right_level": "1",
            "bicycle_word_score_bonus": "21",
        },
        stickers=[
            LoadoutItem(id="poker_face", name="Poker Face", level=1, kind="sticker"),
            LoadoutItem(id="wrestlers", name="Wrestlers", level=1, kind="sticker"),
        ],
    )
    score, bd = ScoringPipeline().score(board, path, "sh", loadout)
    effects = bd["pipeline"]["effects"]
    assert any("word_starts_face_card" in e for e in effects)
    assert not any("word_starts_ends_different_suit" in e for e in effects)
  # (4 + 22) * 2
    assert score == 52.0


def test_wrestlers_joker_start_two_suited_on_path():
    """Joker start + clubs/hearts on path uses first/last suited (ich)."""
    grid = [[_tile(r, c, "A", 1) for c in range(5)] for r in range(5)]
    grid[4][4] = _tile(
        4,
        4,
        "?",
        0,
        curse=CurseType.WILDCARD,
        metadata={"is_joker": True},
    )
    grid[3][3] = _tile(
        3,
        3,
        "C",
        3,
        metadata={"card_suit": "clubs", "card_rank": "C"},
    )
    grid[2][2] = _tile(
        2,
        2,
        "?",
        4,
        curse=CurseType.CHESS_BISHOP,
        metadata={"card_suit": "hearts", "card_rank": ""},
    )
    board = Board(tiles=grid, money=0)
    path = [24, 18, 12]
    assert word_starts_ends_different_suit(board, path)


def test_wrestlers_joker_start_repeated_end_suit_uses_middle():
    """Joker + spades/hearts/spades: endpoints are spades/hearts, not both spades."""
    grid = [[_tile(r, c, "A", 1) for c in range(5)] for r in range(5)]
    grid[3][2] = _tile(
        3,
        2,
        "?",
        0,
        curse=CurseType.WILDCARD,
        metadata={"is_joker": True},
    )
    grid[3][1] = _tile(
        3,
        1,
        "D",
        2,
        metadata={"card_suit": "spades", "card_rank": "D"},
    )
    grid[2][0] = _tile(
        2,
        0,
        "E",
        1,
        metadata={"card_suit": "hearts", "card_rank": "E"},
    )
    grid[1][1] = _tile(
        1,
        1,
        "P",
        2,
        metadata={"card_suit": "spades", "card_rank": "P"},
    )
    board = Board(tiles=grid, money=0)
    path = [17, 16, 10, 6]
    assert word_starts_ends_different_suit(board, path)


def test_wrestlers_joker_start_two_same_suit_proc():
    """Regression 20260530_010829 ass: joker + E♠ + Q♠ proc despite same suit."""
    grid = [[_tile(r, c, "A", 1) for c in range(5)] for r in range(5)]
    grid[2][4] = _tile(
        2,
        4,
        "?",
        0,
        curse=CurseType.WILDCARD,
        metadata={"is_joker": True, "card_suit": "joker"},
    )
    grid[1][4] = _tile(
        1,
        4,
        "E",
        1,
        metadata={"card_suit": "spades", "card_rank": "E"},
    )
    grid[0][3] = _tile(
        0,
        3,
        "Q",
        10,
        metadata={"card_suit": "spades", "card_rank": "Q"},
    )
    board = Board(tiles=grid, money=0)
    assert word_starts_ends_different_suit(board, [14, 9, 3])


def test_wrestlers_joker_start_unsuited_end_no_proc():
    """Regression 20260530_011426 alhidade: joker start + inner suited, unsuited E end."""
    grid = [[_tile(r, c, "A", 1) for c in range(5)] for r in range(5)]
    grid[0][1] = _tile(
        0,
        1,
        "?",
        0,
        curse=CurseType.WILDCARD,
        metadata={"is_joker": True, "card_suit": "joker"},
    )
    grid[1][2] = _tile(
        1,
        2,
        "T",
        1,
        metadata={"card_suit": "diamonds", "card_rank": "T"},
    )
    grid[1][4] = _tile(
        1,
        4,
        "D",
        2,
        metadata={"card_suit": "hearts", "card_rank": "D"},
    )
    grid[0][4] = _tile(
        0,
        4,
        "B",
        3,
        metadata={"card_suit": "diamonds", "card_rank": "B"},
    )
    grid[0][0] = _tile(0, 0, "E", 1)
    board = Board(tiles=grid, money=0)
    assert not word_starts_ends_different_suit(board, [1, 7, 9, 4, 0])


def test_wrestlers_suited_start_joker_end():
    """J at spades start + joker end triggers Wrestlers; reverse does not."""
    grid = [[_tile(r, c, "A", 1) for c in range(5)] for r in range(5)]
    grid[0][1] = _tile(
        0,
        1,
        "J",
        8,
        metadata={"card_suit": "spades", "card_rank": "J"},
    )
    grid[1][4] = _tile(
        1,
        4,
        "?",
        0,
        curse=CurseType.WILDCARD,
        metadata={"is_joker": True},
    )
    board = Board(tiles=grid, money=0)
    assert word_starts_ends_different_suit(board, [1, 9])
    grid[0][1] = _tile(
        0,
        1,
        "?",
        0,
        curse=CurseType.WILDCARD,
        metadata={"is_joker": True},
    )
    grid[1][4] = _tile(
        1,
        4,
        "H",
        4,
        metadata={"card_suit": "hearts", "card_rank": "H"},
    )
    board2 = Board(tiles=grid, money=0)
    assert not word_starts_ends_different_suit(board2, [1, 9])


def test_mismatch_fixture_sh_scores_52():
    if not FIXTURE_SH.exists():
        return
    data = json.loads(FIXTURE_SH.read_text(encoding="utf-8"))
    snap = data["run_state_snapshot"]
    board = parse_board_from_run_state(snap)
    assert board is not None
    loadout = parse_run_state(snap)
    # Snapshot extras are post-submit; F8 prediction used acc 21 before this word.
    loadout.extras["bicycle_word_score_bonus"] = "21"
    loadout.extras["cards_submitted"] = "21"
    path = data["path"]
    score, _ = ScoringPipeline().score(board, path, data["word"], loadout)
    assert score == float(data["actual_score"])


def test_mismatch_fixture_scourers_scores_584():
    if not FIXTURE_SCOURERS.exists():
        return
    data = json.loads(FIXTURE_SCOURERS.read_text(encoding="utf-8"))
    snap = data["run_state_snapshot"]
    board = parse_board_from_run_state(snap)
    assert board is not None
    loadout = parse_run_state(snap)
    loadout.extras["loadout_fingerprint"] = data["loadout_fingerprint"]
    score, bd = ScoringPipeline().score(
        board, data["path"], data["word"], loadout
    )
    effects = bd["pipeline"]["effects"]
    assert any("word_starts_ends_different_suit" in e for e in effects)
    assert score == float(data["actual_score"])


def test_mismatch_fixture_hyke_scores_414():
    """Wrestlers L2 + joker end; Bicycle pre-word acc must not over-rewind."""
    if not FIXTURE_HYKE.exists():
        return
    data = json.loads(FIXTURE_HYKE.read_text(encoding="utf-8"))
    snap = data["run_state_snapshot"]
    board = parse_board_from_run_state(snap)
    assert board is not None
    loadout = parse_run_state(snap)
    loadout.extras["loadout_fingerprint"] = data["loadout_fingerprint"]
    score, _ = ScoringPipeline().score(
        board, data["path"], data["word"], loadout
    )
    assert score == float(data["actual_score"])


def test_mismatch_fixture_ich_scores_912():
    """Joker start + inner suited pair; chess bishop on path counts for Hanafuda."""
    if not FIXTURE_ICH.exists():
        return
    data = json.loads(FIXTURE_ICH.read_text(encoding="utf-8"))
    snap = data["run_state_snapshot"]
    board = parse_board_from_run_state(snap)
    assert board is not None
    loadout = parse_run_state(snap)
    loadout.extras["loadout_fingerprint"] = data["loadout_fingerprint"]
    path = data["path"]
    assert unused_cards_on_board(board, path) == 16
    score, bd = ScoringPipeline().score(board, path, data["word"], loadout)
    effects = bd["pipeline"]["effects"]
    assert any("word_starts_ends_different_suit" in e for e in effects)
    assert score == float(data["actual_score"])


def test_mismatch_fixture_ja_scores_1454():
    """Short word with joker at path end counts for Hanafuda unused."""
    if not FIXTURE_JA.exists():
        return
    data = json.loads(FIXTURE_JA.read_text(encoding="utf-8"))
    snap = data["run_state_snapshot"]
    board = parse_board_from_run_state(snap)
    assert board is not None
    loadout = parse_run_state(snap)
    loadout.extras["loadout_fingerprint"] = data["loadout_fingerprint"]
    path = data["path"]
    assert unused_cards_on_board(board, path) == 21
    score, _ = ScoringPipeline().score(board, path, data["word"], loadout)
    assert score == float(data["actual_score"])


def test_mismatch_fixture_dev_scores_730():
    """Hanafuda L2 needs three matching letters; J-joker-V is not a pair."""
    if not FIXTURE_DEV.exists():
        return
    data = json.loads(FIXTURE_DEV.read_text(encoding="utf-8"))
    snap = data["run_state_snapshot"]
    board = parse_board_from_run_state(snap)
    assert board is not None
    loadout = parse_run_state(snap)
    loadout.extras["loadout_fingerprint"] = data["loadout_fingerprint"]
    score, bd = ScoringPipeline().score(
        board, data["path"], data["word"], loadout
    )
    effects = bd["pipeline"]["effects"]
    assert not any("hanafuda" in e and "unused" in e for e in effects)
    assert score == float(data["actual_score"])


def test_hanafuda_three_of_a_kind_with_joker_glyphs_on_path():
    """Joker-glyphs with letter faces count as poker jokers for Hanafuda (tina-style)."""
    grid = [[_tile(r, c, "X", 1) for c in range(5)] for r in range(5)]
    grid[1][1] = _tile(
        1,
        1,
        "T",
        2,
        metadata={"source": "melmod", "card_suit": "clubs", "card_rank": "T"},
    )
    grid[0][1] = _tile(0, 1, "🃏", 1, color=TileColor.RED, metadata={"source": "melmod"})
    grid[0][1].letter = "A"
    grid[0][2] = _tile(0, 2, "🃏", 1, color=TileColor.RED, metadata={"source": "melmod"})
    grid[0][2].letter = "F"
    grid[0][3] = _tile(
        0,
        3,
        "A",
        2,
        metadata={"source": "melmod", "card_suit": "spades", "card_rank": "A"},
    )
    path = [6, 1, 2, 3]
    board = Board(tiles=grid, money=9)
    path_tiles = [board.get_by_index(i) for i in path]
    assert get_x_of_a_kind_letters(path_tiles, 3) is not None
    assert hanafuda_hand_satisfied(board, path, 2)


def test_mismatch_fixture_kheda_scores_2470():
    """Hanafuda unused: void letter with spurious joker export must not count (20260526_231923)."""
    if not FIXTURE_KHEDA.exists():
        return
    data = json.loads(FIXTURE_KHEDA.read_text(encoding="utf-8"))
    snap = data["run_state_snapshot"]
    board = parse_board_from_run_state(snap)
    assert board is not None
    loadout = parse_run_state(snap)
    loadout.extras.update(data.get("extras_snapshot") or {})
    loadout.extras["loadout_fingerprint"] = data["loadout_fingerprint"]
    path = data["path"]
    assert unused_cards_on_board(board, path) == 19
    score, bd = ScoringPipeline().score(board, path, data["word"], loadout)
    assert any("three_of_a_kind" in e and "19 unused" in e for e in bd["pipeline"]["effects"])
    assert score == float(data["actual_score"])


def test_mismatch_fixture_tina_scores_1250():
    """Hanafuda L2 + joker-glyphs on path + 19 unused cards (regression 20260526_231158)."""
    if not FIXTURE_TINA.exists():
        return
    data = json.loads(FIXTURE_TINA.read_text(encoding="utf-8"))
    snap = data["run_state_snapshot"]
    board = parse_board_from_run_state(snap)
    assert board is not None
    loadout = parse_run_state(snap)
    loadout.extras.update(data.get("extras_snapshot") or {})
    loadout.extras["loadout_fingerprint"] = data["loadout_fingerprint"]
    path = data["path"]
    assert unused_cards_on_board(board, path) == 19
    score, bd = ScoringPipeline().score(board, path, data["word"], loadout)
    assert any("three_of_a_kind" in e and "19 unused" in e for e in bd["pipeline"]["effects"])
    assert score == float(data["actual_score"])


def test_mismatch_fixture_cly_scores_1440():
    """3-letter word Q-L-joker: path-end joker counts toward Hanafuda (20 unused)."""
    if not FIXTURE_CLY.exists():
        return
    data = json.loads(FIXTURE_CLY.read_text(encoding="utf-8"))
    snap = data["run_state_snapshot"]
    board = parse_board_from_run_state(snap)
    assert board is not None
    loadout = parse_run_state(snap)
    loadout.extras["loadout_fingerprint"] = data["loadout_fingerprint"]
    path = data["path"]
    assert unused_cards_on_board(board, path) == 20
    score, _ = ScoringPipeline().score(board, path, data["word"], loadout)
    assert score == float(data["actual_score"])


def test_mismatch_fixture_yince_scores_8320():
    """Joker bookends + Hanafuda L3 four-of-a-kind (round log 20260527_013139)."""
    if not FIXTURE_YINCE.exists():
        return
    data = json.loads(FIXTURE_YINCE.read_text(encoding="utf-8"))
    snap = data["run_state_snapshot"]
    board = parse_board_from_run_state(snap)
    assert board is not None
    loadout = parse_run_state(snap)
    path = data["path"]
    assert word_starts_ends_different_suit(board, path)
    assert hanafuda_hand_satisfied(board, path, 3)
    pipeline = ScoringPipeline()
    rule = get_pin_scoring_rule(pipeline.rules, "bones_the_dog")
    rewind_bicycle_pre_word_extras(loadout, board, path, rule)
    score, bd = ScoringPipeline().score(board, path, data["word"], loadout)
    assert any("word_starts_ends_different_suit" in e for e in bd["pipeline"]["effects"])
    assert score == float(data["actual_score"])


def test_mismatch_fixture_alhidade_scores_792():
    """Regression 20260530_011426: joker start + unsuited E end skips Wrestlers."""
    if not FIXTURE_ALHIDADE.exists():
        return
    data = json.loads(FIXTURE_ALHIDADE.read_text(encoding="utf-8"))
    snap = data["run_state_snapshot"]
    board = parse_board_from_run_state(snap)
    assert board is not None
    loadout = parse_run_state(snap)
    loadout.extras["loadout_fingerprint"] = data["loadout_fingerprint"]
    path = data["path"]
    assert not word_starts_ends_different_suit(board, path)
    score, bd = ScoringPipeline().score(board, path, data["word"], loadout)
    effects = bd["pipeline"]["effects"]
    assert not any("word_starts_ends_different_suit" in e for e in effects)
    assert score == float(data["actual_score"])


def test_mismatch_fixture_aah_scores_1430():
    """Void A + red A + path-end wildcard: 22 unused Hanafuda, void start -1 (20260526_234220)."""
    if not FIXTURE_AAH.exists():
        return
    data = json.loads(FIXTURE_AAH.read_text(encoding="utf-8"))
    snap = data["run_state_snapshot"]
    board = parse_board_from_run_state(snap)
    assert board is not None
    loadout = parse_run_state(snap)
    loadout.extras.update(data.get("extras_snapshot") or {})
    loadout.extras["loadout_fingerprint"] = data["loadout_fingerprint"]
    path = data["path"]
    assert unused_cards_on_board(board, path) == 22
    score, bd = ScoringPipeline().score(board, path, data["word"], loadout)
    assert any("three_of_a_kind" in e and "22 unused" in e for e in bd["pipeline"]["effects"])
    assert score == float(data["actual_score"])
