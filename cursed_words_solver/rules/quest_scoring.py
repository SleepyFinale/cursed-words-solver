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


def _poker_string_rep(tile: Tile) -> str:
    """Mirror Tile.GetStringRepresentation for suited Bones letter/number cards."""
    if tile.curse.value == "number" and tile.number_value is not None:
        return str(int(tile.number_value))
    raw = tile.metadata.get("card_rank") or tile.letter or tile.char or ""
    rep = str(raw).strip().upper()
    if rep and rep != "?":
        return rep
    return ""


def _poker_sort_index(tile: Tile) -> int:
    """Alphabet index for letter glyphs; numeric value for number glyphs."""
    if tile.curse.value == "number" and tile.number_value is not None:
        return int(tile.number_value)
    rep = _poker_string_rep(tile)
    if not rep:
        return -1
    if rep.isdigit():
        return int(rep)
    idx = _POKER_ALPHABET.find(rep[0])
    return idx if idx >= 0 else -1


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


def _detect_straight_from_indices(indices: list[int], min_len: int = 5) -> bool:
    uniq = sorted(set(indices), reverse=True)
    if len(uniq) < min_len:
        return False
    for i in range(len(uniq) - min_len + 1):
        seg = uniq[i : i + min_len]
        if seg[0] - seg[-1] == min_len - 1:
            return True
    return False


def detect_poker_hand(cards: list[Tile]) -> tuple[str, list[Tile]]:
    """Best poker hand from suited path cards (Bones Round / PokerHands parity)."""
    if not cards:
        return "high_card", []
    suited = [t for t in cards if not _is_joker(t) and card_suit(t)]
    jokers = [t for t in cards if _is_joker(t)]
    joker_count = len(jokers)
    pool = suited + jokers
    if len(pool) == 1:
        return "high_card", pool[:1]
    if joker_count >= 5:
        return "straight_flush", jokers[:5]

    suits: dict[str, list[Tile]] = {}
    for t in suited:
        s = (card_suit(t) or "").lower()
        suits.setdefault(s, []).append(t)

    # Flush (before of-a-kind in game when no straight flush)
    for suit_tiles in suits.values():
        if len(suit_tiles) + joker_count >= 5:
            hand = sorted(suit_tiles, key=_poker_sort_index, reverse=True)[:5]
            jokers_left = list(jokers)
            while len(hand) < 5 and jokers_left:
                hand.append(jokers_left.pop(0))
            return "flush", hand[:5]

    # Groups by GetStringRepresentation (GetXOfAKind / GetBestOfAKind parity)
    by_rep: dict[str, list[Tile]] = {}
    for t in suited:
        rep = _poker_string_rep(t)
        if not rep:
            continue
        by_rep.setdefault(rep, []).append(t)

    counts = sorted(((len(v), rep) for rep, v in by_rep.items()), reverse=True)
    if counts and counts[0][0] + joker_count >= 4:
        rep = counts[0][1]
        hand = list(by_rep[rep][:4])
        jokers_left = list(jokers)
        while len(hand) < 4 and jokers_left:
            hand.append(jokers_left.pop(0))
        for t in suited:
            if t not in hand:
                hand.append(t)
                break
        return "four_of_a_kind", hand[:5]
    if (
        len(counts) >= 2
        and counts[0][0] >= 3
        and counts[1][0] >= 2
    ):
        hand = by_rep[counts[0][1]][:3] + by_rep[counts[1][1]][:2]
        return "full_house", hand[:5]
    if counts and counts[0][0] >= 3:
        hand = list(by_rep[counts[0][1]][:3])
        for t in suited:
            if t not in hand:
                hand.append(t)
            if len(hand) >= 5:
                break
        return "three_of_a_kind", hand[:5]
    if counts and counts[0][0] == 2 and joker_count >= 1:
        hand = list(by_rep[counts[0][1]][:2])
        if jokers:
            hand.append(jokers[0])
        return "three_of_a_kind", hand[:3]
    pairs = [rep for c, rep in counts if c >= 2]
    if len(pairs) >= 2:
        hand = by_rep[pairs[0]][:2] + by_rep[pairs[1]][:2]
        for t in suited:
            if t not in hand:
                hand.append(t)
                break
        return "two_pair", hand[:5]
    if len(pairs) == 1:
        hand = list(by_rep[pairs[0]][:2])
        for t in suited:
            if t not in hand:
                hand.append(t)
            if len(hand) >= 5:
                break
        return "pair", hand[:2] if len(hand) < 2 else hand[:5]
    if joker_count >= 2 and suited:
        return "three_of_a_kind", [suited[0], *jokers[:2]]
    if joker_count == 1 and suited:
        return "pair", [suited[0], jokers[0]]

    letter_indices = [_poker_sort_index(t) for t in suited]
    letter_indices = [v for v in letter_indices if v >= 0]
    if _detect_straight_from_indices(letter_indices, min_len=5):
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
                state,
                "quest_bones_poker",
                hand=hand,
                bonus=bonus,
            )
    return state


def effective_submit_score(raw_score: float, loadout: Loadout | None) -> float:
    if two_wrongs_active(loadout):
        return -raw_score
    return raw_score


def quest_inverts_search_rank(loadout: Loadout | None) -> bool:
    """True when search should minimize raw score (Two Wrongs)."""
    return two_wrongs_active(loadout)


_quest_search_target: float | None = None


def set_quest_search_target(target: float | None) -> None:
    global _quest_search_target
    _quest_search_target = target


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


def quest_skips_rank_ub_prune(loadout: Loadout | None) -> bool:
    """True when rank upper-bound pruning is unsafe (non max-score quest ranking)."""
    return quest_inverts_search_rank(loadout) or bullseye_active(loadout)


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


def quest_candidate_rank(
    immediate: float,
    search_rank: float,
    loadout: Loadout | None,
    *,
    quest_target: float | None = None,
) -> float:
    """Ranking key for heap/finalists; Bullseye uses submit score not mult rank."""
    if bullseye_active(loadout):
        return search_rank_for_quest(immediate, loadout, quest_target=quest_target)
    return search_rank_for_quest(search_rank, loadout, quest_target=quest_target)


def display_score_for_quest(raw_score: float, loadout: Loadout | None) -> float:
    """In-game displayed word score (negated on Two Wrongs)."""
    return effective_submit_score(raw_score, loadout)


def encounter_progress_after_submit(
    remaining_before: float,
    raw_score: float,
    loadout: Loadout | None,
) -> float:
    """Internal remaining target after submit (EncounterController parity)."""
    return remaining_target_after_submit(remaining_before, raw_score, loadout)


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


def prune_cannot_beat_heap(
    raw_bound: float,
    min_heap_rank: float,
    loadout: Loadout | None,
    *,
    quest_target: float | None = None,
) -> bool:
    """True when even this raw-score bound cannot beat the heap's weakest kept entry."""
    return search_rank_for_quest(
        raw_bound, loadout, quest_target=quest_target
    ) <= min_heap_rank


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
        return baseline_score > 0
    return baseline_score < target
