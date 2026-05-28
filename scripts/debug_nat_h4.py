"""Debug Nat-H4 sev/earrings scoring."""
import json
from pathlib import Path

from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
from cursed_words_solver.rules.pipeline import ScoringPipeline
from tests.regression.test_scoring_mismatches import (
    _adjust_bento_previous_word_extras,
    _adjust_nat_h4_session_extras,
    _adjust_neapolitan_percent_extras,
    _adjust_previous_word_letter_extras,
    _adjust_rare_item_count_extras,
    _adjust_snapshot_copy_from_trace,
    _adjust_steak_percent_extras,
    _adjust_void_penalty_from_trace,
    _run_state_for_replay,
)


def score_case(stem: str, *, no_flush: bool = False) -> None:
    p = Path("tests/fixtures/mismatches") / f"{stem}.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    rs = _run_state_for_replay(data)
    for fn in (
        _adjust_previous_word_letter_extras,
        _adjust_bento_previous_word_extras,
        _adjust_neapolitan_percent_extras,
        _adjust_rare_item_count_extras,
        _adjust_steak_percent_extras,
    ):
        fn(rs, data)
    board = parse_board_from_run_state(rs)
    _adjust_void_penalty_from_trace(rs, data, board, data["path"])
    _adjust_nat_h4_session_extras(rs, data, stem)
    _adjust_snapshot_copy_from_trace(rs, data, board, data["path"], data["word"])
    if no_flush:
        ex = rs.setdefault("extras", {})
        ex.pop("flush_word_mults_after_pin", None)
        ex.pop("flush_word_mults_before_cocktail", None)
    board = parse_board_from_run_state(rs)
    loadout = parse_run_state(rs)
    score, _, tr = ScoringPipeline().score_with_trace(board, data["path"], data["word"], loadout)
    print(stem, "expected", data["actual_score"], "got", int(score))
    ex = loadout.extras or {}
    print(
        "  snapshot=",
        ex.get("snapshot_copy_slug"),
        "flush_pin=",
        ex.get("flush_word_mults_after_pin"),
    )
    for step in tr:
        ph = step.get("phase")
        rid = step.get("rule_id", "")
        if ph in ("rule", "multiply", "finalize", "grid_item", "pin") or rid in (
            "snapshot",
            "burrito",
            "cocktail",
            "steak",
            "neapolitan",
            "ferris_wheel",
        ):
            tiles = step.get("tile_scores") or []
            ts = sum(tiles) if tiles else 0
            print(
                f"  {ph:12} {str(rid):20} sub={step.get('subtotal')} "
                f"tiles={ts} word={step.get('word_score')}"
            )


if __name__ == "__main__":
    for stem in ("20260528_124638", "20260528_124729"):
        print("=== WITH flush ===")
        score_case(stem)
        print("=== NO flush ===")
        score_case(stem, no_flush=True)
