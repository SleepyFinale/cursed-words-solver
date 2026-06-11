"""Quest scoring overrides (TheBonesRound, Lexographer, target quests)."""

from __future__ import annotations

from typing import Any

from cursed_words_solver.models import Board, Loadout, Tile
from cursed_words_solver.rules.quest_effects import (
    active_quest_game_class,
    load_quests_catalog,
)
from cursed_words_solver.rules.scoring_conditions import (
    card_suit,
    is_cursed_tile,
    is_poker_card_tile,
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


def poker_scores_for_quest(loadout: Loadout | None) -> dict[str, int]:
    from cursed_words_solver.rules.quest_effects import active_quest_slug

    slug = active_quest_slug(loadout)
    if not slug:
        return _POKER_SCORES
    row = load_quests_catalog().get("quests", {}).get(slug) or {}
    scores = row.get("poker_scores")
    if isinstance(scores, dict):
        return {str(k): int(v) for k, v in scores.items()}
    return _POKER_SCORES


def bones_round_active(loadout: Loadout | None) -> bool:
    return active_quest_game_class(loadout) == "TheBonesRound"


def lexographer_active(loadout: Loadout | None) -> bool:
    return active_quest_game_class(loadout) == "Lexographer"


def two_wrongs_active(loadout: Loadout | None) -> bool:
    return active_quest_game_class(loadout) == "TwoWrongs"


def bullseye_active(loadout: Loadout | None) -> bool:
    return active_quest_game_class(loadout) == "Bullseye"


def zero_tile_scores_for_bones(state: dict[str, Any]) -> None:
    n = len(state.get("tile_scores", []))
    state["tile_scores"] = [0.0] * n
    if "tile_base_scores" in state:
        state["tile_base_scores"] = [0.0] * n


def apply_lexographer_tile_zero(
    state: dict[str, Any],
    board: Board,
    path: list[int],
) -> dict[str, Any]:
    scores = list(state.get("tile_scores", []))
    for i, idx in enumerate(path):
        if i >= len(scores):
            break
        if is_cursed_tile(board.get_by_index(idx)):
            scores[i] = 0.0
    state["tile_scores"] = scores
    return state


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


def _suited_cards_on_path(board: Board, path: list[int]) -> list[Tile]:
    out: list[Tile] = []
    for idx in path:
        tile = board.get_by_index(idx)
        suit = card_suit(tile)
        if suit and suit.lower() not in ("", "none"):
            out.append(tile)
    return out


def _is_joker(tile: Tile) -> bool:
    suit = (card_suit(tile) or "").lower()
    return suit == "joker" or tile.metadata.get("is_joker") in (True, "true", "1", 1)


def detect_poker_hand(cards: list[Tile]) -> tuple[str, list[Tile]]:
    """Best poker hand from suited path cards (Bones Round / PokerHands parity)."""
    if not cards:
        return "high_card", []
    suited = [t for t in cards if not _is_joker(t) and card_suit(t)]
    jokers = [t for t in cards if _is_joker(t)]
    pool = suited + jokers
    if len(pool) == 1:
        return "high_card", pool[:1]
    if len(jokers) >= 5:
        return "straight_flush", jokers[:5]
    ranks = sorted((_rank_value(t) for t in suited), reverse=True)
    suits: dict[str, list[Tile]] = {}
    for t in suited:
        s = (card_suit(t) or "").lower()
        suits.setdefault(s, []).append(t)
    # Flush
    for suit_tiles in suits.values():
        if len(suit_tiles) + len(jokers) >= 5:
            hand = sorted(suit_tiles, key=_rank_value, reverse=True)[:5]
            while len(hand) < 5 and jokers:
                hand.append(jokers.pop(0))
            return "flush", hand[:5]
    # Groups by rank
    by_rank: dict[int, list[Tile]] = {}
    for t in suited:
        by_rank.setdefault(_rank_value(t), []).append(t)
    counts = sorted(((len(v), r) for r, v in by_rank.items()), reverse=True)
    if counts and counts[0][0] >= 4:
        r = counts[0][1]
        hand = by_rank[r][:4]
        for t in suited:
            if t not in hand:
                hand.append(t)
                break
        return "four_of_a_kind", hand[:5]
    if len(counts) >= 2 and counts[0][0] >= 3 and counts[1][0] >= 2:
        hand = by_rank[counts[0][1]][:3] + by_rank[counts[1][1]][:2]
        return "full_house", hand[:5]
    if counts and counts[0][0] >= 3:
        r = counts[0][1]
        hand = by_rank[r][:3]
        for t in suited:
            if t not in hand:
                hand.append(t)
            if len(hand) >= 5:
                break
        return "three_of_a_kind", hand[:5]
    pairs = [r for c, r in counts if c >= 2]
    if len(pairs) >= 2:
        hand = by_rank[pairs[0]][:2] + by_rank[pairs[1]][:2]
        for t in suited:
            if t not in hand:
                hand.append(t)
                break
        return "two_pair", hand[:5]
    if len(pairs) == 1:
        hand = by_rank[pairs[0]][:2]
        for t in suited:
            if t not in hand:
                hand.append(t)
            if len(hand) >= 5:
                break
        return "pair", hand[:2] if len(hand) < 2 else hand[:5]
    uniq = sorted(set(ranks), reverse=True)
    if len(uniq) >= 5:
        for i in range(len(uniq) - 4):
            seg = uniq[i : i + 5]
            if seg[0] - seg[4] == 4:
                return "straight", suited[:5]
    return "high_card", suited[:1] if suited else pool[:1]


def bones_round_poker_bonus(
    board: Board,
    path: list[int],
    loadout: Loadout | None,
) -> tuple[int, str]:
    cards = _suited_cards_on_path(board, path)
    if not cards and not any(_is_joker(board.get_by_index(i)) for i in path):
        return 0, "none"
    if not any(is_poker_card_tile(board.get_by_index(i)) for i in path):
        suited_only = [t for t in cards if card_suit(t)]
        if not suited_only:
            return 0, "none"
    hand_name, _hand_tiles = detect_poker_hand(
        [board.get_by_index(i) for i in path if card_suit(board.get_by_index(i)) or _is_joker(board.get_by_index(i))]
    )
    scores = poker_scores_for_quest(loadout)
    key = hand_name
    return scores.get(key, scores.get("high_card", 5)), hand_name


def apply_bones_round_early_bonus(
    state: dict[str, Any],
    board: Board,
    path: list[int],
    loadout: Loadout | None,
    *,
    trace_step: Any = None,
) -> dict[str, Any]:
    zero_tile_scores_for_bones(state)
    bonus, hand = bones_round_poker_bonus(board, path, loadout)
    if bonus:
        state["word_score"] = float(state.get("word_score", 0)) + float(bonus)
        state.setdefault("bones_poker_hand", hand)
        state.setdefault("bones_poker_bonus", bonus)
        if trace_step is not None:
            trace_step(
                "quest_bones_poker",
                {"hand": hand, "bonus": bonus},
            )
    return state


def effective_submit_score(raw_score: float, loadout: Loadout | None) -> float:
    if two_wrongs_active(loadout):
        return -raw_score
    return raw_score


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


def do_not_pass_go_active(loadout: Loadout | None) -> bool:
    return active_quest_game_class(loadout) == "DoNotPassGo"


def encounter_reward_for_quest(loadout: Loadout | None, base_reward: int) -> int:
    """Encounter/boss clear money after quest modifiers (Do Not Pass Go → $0)."""
    if do_not_pass_go_active(loadout):
        return 0
    return max(0, int(base_reward))


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
        return baseline_score < target
    return baseline_score < target
