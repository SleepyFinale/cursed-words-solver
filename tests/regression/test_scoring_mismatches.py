"""Regression tests from melmod scoring mismatch captures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cursed_words_solver.loadout import parse_board_from_run_state, parse_run_state
from cursed_words_solver.rules.pipeline import ScoringPipeline
from cursed_words_solver.rules.rule_lookup import get_pin_scoring_rule, resolve_rule_id
from cursed_words_solver.rules.scoring_conditions import (
    bicycle_word_per_card,
    effective_suited_cards_on_path,
    path_letter_for_count,
    rewind_bicycle_pre_word_extras,
    suited_cards_on_path_count,
)

_BICYCLE_POST_EXTRAS = frozenset({"bicycle_word_score_bonus", "cards_submitted"})

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "mismatches"


def _merge_submit_take_flags(run_state: dict, data: dict) -> None:
    """Apply submit-time take flags when snapshot predates melmod merge."""
    submit_tiles = data.get("submit_board_tiles")
    if not isinstance(submit_tiles, list):
        return
    board = run_state.get("board")
    if not isinstance(board, dict):
        return
    tiles = board.get("tiles")
    if not isinstance(tiles, list):
        return
    take_at = {
        (int(t["row"]), int(t["col"]))
        for t in submit_tiles
        if isinstance(t, dict) and t.get("take")
    }
    if not take_at:
        return
    for tile in tiles:
        if not isinstance(tile, dict):
            continue
        key = (int(tile.get("row", -1)), int(tile.get("col", -1)))
        if key in take_at:
            tile["take"] = True


def _bicycle_trace_word_bonus(data: dict) -> int | None:
    trace = data.get("actual_trace")
    if not isinstance(trace, list):
        return None
    for step in trace:
        if not isinstance(step, dict):
            continue
        item_id = str(step.get("item_id", "") or "").lower()
        item_name = str(step.get("item_name", "") or "").lower()
        if item_id != "bicycle" and item_name != "bicycle":
            continue
        try:
            total = int(step.get("word_bonus", 0))
        except (TypeError, ValueError):
            continue
        if total <= 0 or step.get("word_bonus_multiplicative"):
            continue
        return total
    return None


def _infer_bicycle_accumulator_from_trace(
    data: dict, extras: dict, board, path: list[int], loadout
) -> int | None:
    """Infer pre-word accumulator from actual_trace when extras are missing or post-submit."""
    pin_effect = str(extras.get("pin_effect", "") or "").strip().lower()
    if pin_effect not in ("bicycle", "bones_the_dog", "bones"):
        return None

    total = _bicycle_trace_word_bonus(data)
    if total is None:
        return None

    pipeline = ScoringPipeline()
    canonical = resolve_rule_id(pipeline.rules, "pins", pin_effect, "") or "bones_the_dog"
    rule = get_pin_scoring_rule(pipeline.rules, canonical)
    if not rule:
        return None
    per_card = bicycle_word_per_card(loadout, rule)
    suited = effective_suited_cards_on_path(board, path, loadout)
    return max(0, total - per_card * suited)


def _merge_submit_card_metadata(run_state: dict, data: dict) -> None:
    """Apply submit-time card_suit from capture when F8 board lacked suits."""
    submit_tiles = data.get("submit_board_tiles")
    if not isinstance(submit_tiles, list):
        return
    board = run_state.get("board")
    if not isinstance(board, dict):
        return
    tiles = board.get("tiles")
    if not isinstance(tiles, list):
        return
    card_at: dict[tuple[int, int], tuple[str, str]] = {}
    for t in submit_tiles:
        if not isinstance(t, dict):
            continue
        suit = str(t.get("card_suit") or "").strip()
        if not suit:
            continue
        key = (int(t["row"]), int(t["col"]))
        rank = str(t.get("card_rank") or "").strip()
        card_at[key] = (suit, rank)

    if not card_at:
        return

    for tile in tiles:
        if not isinstance(tile, dict):
            continue
        key = (int(tile.get("row", -1)), int(tile.get("col", -1)))
        if key not in card_at:
            continue
        suit, rank = card_at[key]
        tile["card_suit"] = suit
        if rank:
            tile["card_rank"] = rank


def _adjust_bicycle_pre_word_extras(
    run_state: dict,
    data: dict,
    board,
    path: list[int],
    loadout,
) -> None:
    """Use pre-word Bicycle accumulator; post-submit extras include this word's cards."""
    extras = dict(run_state.get("extras") or {})
    pin_effect = str(extras.get("pin_effect", "") or "").strip().lower()
    if pin_effect not in ("bicycle", "bones_the_dog", "bones"):
        return

    snapshot_extras = data.get("extras_snapshot") or {}
    pipeline = ScoringPipeline()
    canonical = resolve_rule_id(pipeline.rules, "pins", pin_effect, "") or "bones_the_dog"
    rule = get_pin_scoring_rule(pipeline.rules, canonical)
    if not rule:
        return

    post: int | None = None
    try:
        post = int(snapshot_extras.get("bicycle_word_score_bonus", -1))
    except (TypeError, ValueError):
        post = -1
    if post < 0:
        inferred = _infer_bicycle_accumulator_from_trace(
            data, extras, board, path, loadout
        )
        if inferred is not None:
            extras = dict(run_state.get("extras") or {})
            extras["bicycle_word_score_bonus"] = str(inferred)
            extras["cards_submitted"] = str(inferred)
            run_state["extras"] = extras
        return

    rewind_bicycle_pre_word_extras(
        loadout, board, path, rule, post_bonus=post
    )
    run_state["extras"] = dict(loadout.extras or {})


def _has_mutating_dna_stamp(run_state: dict) -> bool:
    stamps = run_state.get("stamps")
    if not isinstance(stamps, list):
        return False
    for stamp in stamps:
        if not isinstance(stamp, dict):
            continue
        stamp_id = str(stamp.get("id", "") or "").lower()
        name = str(stamp.get("name", "") or "").lower()
        if "mutating" in stamp_id or "dna" in stamp_id:
            return True
        if "mutating" in name or "dna" in name:
            return True
    return False


def _parse_mutating_dna_counts(raw) -> dict[str, int]:
    if raw is None or raw == "":
        return {}
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
        if isinstance(data, dict):
            return {
                str(k).lower(): int(v)
                for k, v in data.items()
                if str(k).strip()
            }
    except (TypeError, ValueError, json.JSONDecodeError):
        pass
    return {}


def _infer_mutating_dna_counts_from_trace(
    data: dict, board, path: list[int]
) -> dict[str, int]:
    """Infer pre-submit per-letter counts from the mutating DNA actual_trace step."""
    trace = data.get("actual_trace")
    if not isinstance(trace, list):
        return {}

    mutating_idx: int | None = None
    for i, step in enumerate(trace):
        if not isinstance(step, dict):
            continue
        item_id = str(step.get("item_id", "") or "").lower()
        item_name = str(step.get("item_name", "") or "").lower()
        if item_id == "mutating_dna" or item_name == "mutating dna":
            mutating_idx = i
            break
    if mutating_idx is None or mutating_idx <= 0:
        return {}

    before = trace[mutating_idx - 1].get("tile_scores")
    after = trace[mutating_idx].get("tile_scores")
    if not isinstance(before, list) or not isinstance(after, list):
        return {}
    if len(before) != len(after) or len(before) != len(path):
        return {}

    counts: dict[str, int] = {}
    for i, idx in enumerate(path):
        ch = path_letter_for_count(board.get_by_index(idx))
        if not ch:
            continue
        try:
            delta = int(after[i]) - int(before[i])
        except (TypeError, ValueError):
            continue
        if ch not in counts and delta > 0:
            counts[ch] = delta
    return counts


def _predicted_mutating_first_word_only(data: dict) -> bool:
    """True when solver applied the empty-history first-word Mutating DNA bonus."""
    trace = data.get("predicted_trace")
    if not isinstance(trace, list):
        return False
    for step in trace:
        if not isinstance(step, dict):
            continue
        rule_id = str(step.get("rule_id", "") or "").lower()
        effect = str(step.get("effect_type", "") or "").lower()
        if "mutating" not in rule_id and "mutating" not in effect:
            continue
        detail = str(step.get("detail", "") or "").lower()
        return "word" in detail
    return False


def _adjust_mutating_dna_extras(
    run_state: dict,
    data: dict,
    board,
    path: list[int],
) -> None:
    """Fill Mutating DNA letter counts when capture omitted them."""
    if not _has_mutating_dna_stamp(run_state):
        return

    extras = dict(run_state.get("extras") or {})
    snapshot_extras = data.get("extras_snapshot") or {}
    has_captured = bool(
        extras.get("mutating_dna_letter_counts")
        or (isinstance(snapshot_extras, dict)
            and snapshot_extras.get("mutating_dna_letter_counts"))
    )
    counts = _parse_mutating_dna_counts(extras.get("mutating_dna_letter_counts"))
    if not counts and not has_captured:
        inferred = _infer_mutating_dna_counts_from_trace(data, board, path)
        # Large deltas (e.g. a:9) are historic use counts; small ones are not reliable.
        if inferred and max(inferred.values(), default=0) >= 8:
            counts = inferred
    if not counts:
        return
    extras["mutating_dna_letter_counts"] = json.dumps(counts, sort_keys=True)
    run_state["extras"] = extras


def _run_state_for_replay(data: dict) -> dict:
    """Merge submit-time extras into the F8 snapshot so replay matches in-game scoring."""
    run_state = dict(data.get("run_state_snapshot") or {})
    extras = dict(run_state.get("extras") or {})
    snapshot_extras = data.get("extras_snapshot") or {}
    if isinstance(snapshot_extras, dict):
        for key, value in snapshot_extras.items():
            if key in _BICYCLE_POST_EXTRAS:
                continue
            extras[key] = value
    if extras:
        run_state["extras"] = extras
    _merge_submit_take_flags(run_state, data)
    _merge_submit_card_metadata(run_state, data)
    return run_state


def _money_from_actual_trace(data: dict) -> int | None:
    """Peak bank $ during scoring; F8 snapshot can be behind in-run earnings."""
    trace = data.get("actual_trace")
    if not isinstance(trace, list):
        return None
    peak = 0
    for step in trace:
        if isinstance(step, dict) and step.get("money") is not None:
            peak = max(peak, int(step["money"]))
    return peak if peak > 0 else None


@pytest.mark.parametrize(
    "case_path",
    sorted(FIXTURES.glob("*.json")),
    ids=lambda p: p.stem,
)
def test_scoring_mismatch(case_path: Path) -> None:
    data = json.loads(case_path.read_text(encoding="utf-8"))
    if "word" not in data or "path" not in data:
        pytest.skip(f"{case_path.name}: incomplete mismatch capture")
    run_state = _run_state_for_replay(data)
    if not run_state:
        pytest.fail(f"{case_path.name}: missing run_state_snapshot")

    word = data["word"]
    path = data["path"]
    expected = int(data["actual_score"])

    board = parse_board_from_run_state(run_state)
    loadout = parse_run_state(run_state)
    _adjust_bicycle_pre_word_extras(run_state, data, board, path, loadout)
    loadout = parse_run_state(run_state)
    _adjust_mutating_dna_extras(run_state, data, board, path)
    loadout = parse_run_state(run_state)
    replay_money = _money_from_actual_trace(data)
    if replay_money is not None:
        board.money = max(board.money, replay_money)
        loadout.money = max(loadout.money, replay_money)
    pipeline = ScoringPipeline()
    score, _bd = pipeline.score(board, path, word, loadout)
    assert int(score) == expected
