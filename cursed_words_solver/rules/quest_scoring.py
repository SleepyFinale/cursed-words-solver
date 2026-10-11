"""Quest scoring overrides (TheBonesRound, Lexographer, target quests)."""

from __future__ import annotations


from cursed_words_solver.models import Loadout, Tile
from cursed_words_solver.rules.quest_effects import (
    active_quest_game_class,
)

_POKER_SCORES: dict[str, int] = {
    "straight_flush": 800,
    "four_of_a_kind": 420,
    "full_house": 160,
    "flush": 140,
    "straight": 120,
    "three_of_a_kind": 90,
    "two_pair": 40,
    "pair": 20,
    "high_card": 5,
}


def bones_round_active(loadout: Loadout | None) -> bool:
    return active_quest_game_class(loadout) == "TheBonesRound"


def two_wrongs_active(loadout: Loadout | None) -> bool:
    return active_quest_game_class(loadout) == "TwoWrongs"


def bullseye_active(loadout: Loadout | None) -> bool:
    return active_quest_game_class(loadout) == "Bullseye"


_POKER_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _rank_value(tile: Tile) -> int:
    rank = (tile.metadata.get("card_rank") or tile.letter or tile.char or "").upper()
    if rank.isdigit():
        return int(rank)
    order = "A23456789TJQK"
    if rank in order:
        return order.index(rank) + 1
    if tile.curse.value == "number" and tile.number_value is not None:
        return int(tile.number_value)
    return 0


def effective_submit_score(raw_score: float, loadout: Loadout | None) -> float:
    if two_wrongs_active(loadout):
        return -raw_score
    return raw_score


def quest_inverts_search_rank(loadout: Loadout | None) -> bool:
    """True when search should minimize raw score (Two Wrongs)."""
    return two_wrongs_active(loadout)


_quest_search_target: float | None = None


def encounter_remaining_from_loadout(loadout: Loadout | None) -> int:
    if loadout is None:
        return 0
    try:
        return int((loadout.extras or {}).get("encounter_remaining_target") or 0)
    except (TypeError, ValueError):
        return 0


def _resolve_quest_target(
    loadout: Loadout | None,
    quest_target: float | None,
) -> float | None:
    if quest_target is not None:
        return quest_target
    if bullseye_active(loadout) and _quest_search_target is not None and _quest_search_target > 0:
        return _quest_search_target
    if bullseye_active(loadout):
        remaining = encounter_remaining_from_loadout(loadout)
        if remaining > 0:
            return float(remaining)
    return None


def bullseye_heap_rank(score: float, target: float) -> float:
    """Heap ordering for Bullseye: exact integer hit wins; else prefer closer scores."""
    if target > 0 and int(round(score)) == int(target):
        return 1e15 + float(score)
    if target > 0:
        return -abs(float(score) - float(target))
    return float(score)


def search_rank_for_quest(
    raw_rank: float,
    loadout: Loadout | None,
    *,
    quest_target: float | None = None,
) -> float:
    """Heap ordering key: higher is better. Quest-specific adjustments."""
    target = _resolve_quest_target(loadout, quest_target)
    if bullseye_active(loadout) and target is not None and target > 0:
        return bullseye_heap_rank(float(raw_rank), float(target))
    if quest_inverts_search_rank(loadout):
        return -float(raw_rank)
    return float(raw_rank)


def display_score_for_quest(raw_score: float, loadout: Loadout | None) -> float:
    """In-game displayed word score (negated on Two Wrongs)."""
    return effective_submit_score(raw_score, loadout)


def quest_rank_beats_baseline(
    candidate_rank: float,
    baseline_rank: float,
    loadout: Loadout | None,
    *,
    quest_target: float | None = None,
) -> bool:
    """True when candidate beats baseline under quest-adjusted heap ordering."""
    return search_rank_for_quest(
        candidate_rank, loadout, quest_target=quest_target
    ) > search_rank_for_quest(baseline_rank, loadout, quest_target=quest_target)


def remaining_target_after_submit(
    remaining_before: float,
    raw_score: float,
    loadout: Loadout | None,
) -> float:
    """Mirror EncounterController.SubmitWord target update."""
    score = effective_submit_score(raw_score, loadout)
    delta = remaining_before - score
    if bullseye_active(loadout):
        return abs(delta)
    return delta


def target_met(score: float, target: float, loadout: Loadout | None) -> bool:
    if target <= 0:
        return score >= target
    if bullseye_active(loadout):
        return int(score) == int(target)
    if two_wrongs_active(loadout):
        eff = effective_submit_score(score, loadout)
        return remaining_target_after_submit(float(target), score, loadout) <= 0
    return score >= target


def target_rescue_worth_trying_quest(
    baseline_score: float,
    target: int,
    loadout: Loadout | None,
) -> bool:
    if target <= 0:
        return False
    if bullseye_active(loadout):
        return baseline_score != target
    if two_wrongs_active(loadout):
        return baseline_score > 0
    return baseline_score < target
