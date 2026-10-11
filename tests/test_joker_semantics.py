"""Joker wildcard semantics vs in-game scoring (mismatch 20260526_143052)."""

import json
from pathlib import Path

from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
from cursed_words_solver.models import CurseType, Tile, TileColor
from cursed_words_solver.engine.scorer import EngineScorer

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


def test_mismatch_fixture_scourers_scores_584():
    if not FIXTURE_SCOURERS.exists():
        return
    data = json.loads(FIXTURE_SCOURERS.read_text(encoding="utf-8"))
    snap = data["run_state_snapshot"]
    board = parse_board_from_run_state(snap)
    assert board is not None
    loadout = parse_run_state(snap)
    loadout.extras["loadout_fingerprint"] = data["loadout_fingerprint"]
    score, bd = EngineScorer().score(
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
    score, _ = EngineScorer().score(
        board, data["path"], data["word"], loadout
    )
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
    score, bd = EngineScorer().score(
        board, data["path"], data["word"], loadout
    )
    effects = bd["pipeline"]["effects"]
    assert not any("hanafuda" in e and "unused" in e for e in effects)
    assert score == float(data["actual_score"])
