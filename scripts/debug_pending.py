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


def setup(stem: str):
    data = json.loads(
        Path(f"tests/fixtures/mismatches/{stem}.json").read_text(encoding="utf-8")
    )
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
    return data, parse_board_from_run_state(rs), parse_run_state(rs)


for stem in ("20260528_124729", "20260528_124638"):
    # no flush variant for sev
    if stem == "20260528_124638":
        data, board, loadout = setup(stem)
        ex = data
        rs = _run_state_for_replay(
            json.loads(
                Path(f"tests/fixtures/mismatches/{stem}.json").read_text(encoding="utf-8")
            )
        )
        # skip - just test no flush via pop
        data2, board2, loadout2 = setup(stem)
        loadout2.extras.pop("flush_word_mults_after_pin", None)
        loadout2.extras.pop("flush_word_mults_before_cocktail", None)
        p2 = ScoringPipeline()
        state2 = p2._compute_state(
            board2, data2["path"], data2["word"], loadout2, trace=[]
        )
        print(stem, "NO FLUSH pending", state2.get("pending_word_finalize_steps"))
        print("  subtotal", sum(state2["tile_scores"]) + state2["word_score"])

for stem in ("20260528_124729", "20260528_124638"):
    data, board, loadout = setup(stem)
    p = ScoringPipeline()
    trace = []
    state = p._compute_state(board, data["path"], data["word"], loadout, trace=trace)
    pending = state.get("pending_word_finalize_steps", [])
    print(stem, "pending", pending)
    from cursed_words_solver.rules.pipeline import _apply_pending_word_finalize_steps
    import math

    subtotal = sum(state["tile_scores"]) + state["word_score"]
    print("  pre-finalize subtotal", subtotal)
    total = subtotal
    for kind, value, rule_id in pending:
        if kind == "percent":
            total = math.floor(total * int(value) / 100.0)
        else:
            total = math.floor(total * float(value))
        print(f"    {rule_id} {kind} {value} -> {total}")
    score, _, tr = p.score_with_trace(board, data["path"], data["word"], loadout)
    mults = [
        (s.get("rule_id"), s.get("percent"), s.get("factor"), s.get("subtotal"))
        for s in tr
        if s.get("phase") == "multiply"
    ]
    print(stem, "score", int(score), "mult steps:", mults)
