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
    is_poker_card_tile,
    tile_is_cursed_for_lexographer,
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
    loadout: Loadout | None = None,
) -> dict[str, Any]:
    scores = list(state.get("tile_scores", []))
    for i, idx in enumerate(path):
        if i >= len(scores):
            break
        if tile_is_cursed_for_lexographer(board.get_by_index(idx), loadout):
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


def _has_martini_stamp(loadout: Loadout | None) -> bool:
    if loadout is None:
        return False
    return any(
        (s.id or "").lower() == "martini" or (s.name or "").lower() == "martini"
        for s in loadout.stamps
    )


def _required_cards_for_hand(loadout: Loadout | None) -> int:
    return 3 if _has_martini_stamp(loadout) else 5


def _is_number_glyph(tile: Tile) -> bool:
    from cursed_words_solver.models import CurseType

    if tile.curse in (CurseType.NUMBER, CurseType.FRACTION):
        return True
    if tile.number_value is not None:
        return True
    rep = _poker_string_rep(tile)
    return bool(rep and rep.isdigit())


def _glyph_sort_key(tile: Tile) -> tuple[int, str]:
    if _is_number_glyph(tile):
        return (1, f"{_poker_sort_index(tile):010d}")
    return (0, _poker_string_rep(tile))


def _split_letter_number_pools(suited: list[Tile]) -> tuple[list[Tile], list[Tile]]:
    letters = sorted(
        [t for t in suited if not _is_number_glyph(t)],
        key=_glyph_sort_key,
        reverse=True,
    )
    numbers = sorted(
        [t for t in suited if _is_number_glyph(t)],
        key=lambda t: _poker_sort_index(t),
        reverse=True,
    )
    return letters, numbers


def _rank_index_for_straight(tile: Tile, *, is_number_type: bool) -> int:
    if is_number_type:
        return _poker_sort_index(tile)
    rep = _poker_string_rep(tile)
    if not rep:
        return -1
    idx = _POKER_ALPHABET.find(rep[0])
    return idx if idx >= 0 else -1


def _try_get_straight_or_straight_flush(
    cards: list[Tile],
    joker_count: int,
    required_len: int,
) -> tuple[str, list[Tile | None]]:
    """Mirror PokerHands.TryGetStraightOrStraightFlush (flush-suited vs straight)."""
    if len(cards) + joker_count < required_len:
        return "none", []
    if joker_count >= required_len and cards:
        return "straight_flush", [cards[0], *[None] * (required_len - 1)]

    if not cards:
        return "none", []

    is_number_type = _is_number_glyph(cards[0])
    straight_fallback: list[Tile | None] | None = None

    for start in cards:
        flush_run: list[Tile | None] = [start]
        straight_run: list[Tile | None] = [start]
        current_suit = (card_suit(start) or "").lower()
        base = _rank_index_for_straight(start, is_number_type=is_number_type)
        if base < 0:
            continue

        for step in range(1, required_len):
            required_value = base - step
            same_suit = next(
                (
                    t
                    for t in cards
                    if (card_suit(t) or "").lower() == current_suit
                    and _rank_index_for_straight(t, is_number_type=is_number_type)
                    == required_value
                ),
                None,
            )
            if same_suit is not None:
                flush_run.append(same_suit)
                if straight_fallback is None:
                    straight_run.append(same_suit)
            else:
                flush_run.append(None)
                if straight_fallback is None:
                    cross_suit = next(
                        (
                            t
                            for t in cards
                            if _rank_index_for_straight(t, is_number_type=is_number_type)
                            == required_value
                        ),
                        None,
                    )
                    straight_run.append(cross_suit)

        null_flush = sum(1 for t in flush_run if t is None)
        if null_flush <= joker_count:
            return "straight_flush", flush_run

        if straight_fallback is None:
            null_straight = sum(1 for t in straight_run if t is None)
            if null_straight <= joker_count:
                straight_fallback = straight_run

    if straight_fallback is None:
        return "none", []
    return "straight", straight_fallback


def _fill_jokers(hand: list[Tile | None], jokers: list[Tile]) -> list[Tile]:
    out: list[Tile] = []
    j_idx = 0
    for slot in hand:
        if slot is None:
            if j_idx < len(jokers):
                out.append(jokers[j_idx])
                j_idx += 1
        else:
            out.append(slot)
    return out


def _get_best_of_a_kind(
    cards: list[Tile],
    joker_count: int,
) -> tuple[str, list[Tile | None]]:
    """Mirror PokerHands.GetBestOfAKind."""
    if joker_count >= 4:
        return "four_of_a_kind", [None, None, None, None]
    if joker_count == 3:
        if cards:
            return "four_of_a_kind", [cards[0], None, None, None]
        return "three_of_a_kind", [None, None, None]
    if joker_count == 2 and not cards:
        return "pair", [None, None]

    by_rep: dict[str, list[Tile]] = {}
    for card in cards:
        rep = _poker_string_rep(card)
        if not rep:
            continue
        bucket = by_rep.setdefault(rep, [])
        bucket.append(card)
        if len(bucket) + joker_count == 4:
            hand: list[Tile | None] = list(bucket)
            while len(hand) < 4:
                hand.append(None)
            return "four_of_a_kind", hand

    triple: list[Tile] | None = None
    pair_a: list[Tile] | None = None
    pair_b: list[Tile] | None = None
    for group in by_rep.values():
        if len(group) == 3:
            if triple is None:
                triple = group
        elif len(group) == 2:
            if pair_a is None:
                pair_a = group
                if triple is not None:
                    return "full_house", [*triple, *pair_a]
            elif pair_b is None:
                pair_b = group

    if triple is not None:
        if joker_count > 0:
            return "four_of_a_kind", [triple[0], triple[1], triple[2], None]
        if pair_a is not None:
            return "full_house", [triple[0], triple[1], triple[2], pair_a[0], pair_a[1]]
        return "three_of_a_kind", list(triple)

    if pair_a is not None:
        if joker_count == 1:
            if pair_b is None:
                return "three_of_a_kind", [pair_a[0], pair_a[1], None]
            return "full_house", [pair_a[0], pair_a[1], None, pair_b[0], pair_b[1]]
        if pair_b is None:
            return "pair", [pair_a[0], pair_a[1]]
        return "two_pair", [pair_a[0], pair_a[1], pair_b[0], pair_b[1]]

    if joker_count == 2 and cards:
        return "three_of_a_kind", [cards[0], None, None]
    if joker_count == 1 and cards:
        return "pair", [cards[0], None]
    if cards:
        return "high_card", [cards[0]]
    return "high_card", []


def _try_get_flush(
    cards: list[Tile],
    joker_count: int,
    required_len: int,
) -> list[Tile | None] | None:
    """Mirror PokerHands.TryGetFlush."""
    if len(cards) + joker_count < required_len:
        return None
    if joker_count >= required_len:
        return [None] * required_len

    by_suit: dict[str, list[Tile]] = {}
    for card in cards:
        suit = (card_suit(card) or "").lower()
        bucket = by_suit.setdefault(suit, [])
        bucket.append(card)
        if len(bucket) + joker_count >= required_len:
            hand: list[Tile | None] = list(bucket)
            while len(hand) < required_len:
                hand.append(None)
            return hand
    return None


def detect_poker_hand(
    cards: list[Tile],
    loadout: Loadout | None = None,
) -> tuple[str, list[Tile]]:
    """Best poker hand from suited path cards (Bones Round / PokerHands parity)."""
    suited = [t for t in cards if not _is_joker(t) and card_suit(t)]
    jokers = [t for t in cards if _is_joker(t)]
    joker_count = len(jokers)
    required_len = _required_cards_for_hand(loadout)
    pool = suited + jokers

    if not pool:
        return "high_card", []
    if len(pool) == 1:
        return "high_card", pool[:1]
    if joker_count >= required_len:
        return "straight_flush", jokers[:required_len]

    letters, numbers = _split_letter_number_pools(suited)

    sf_kind, sf_hand = _try_get_straight_or_straight_flush(
        letters, joker_count, required_len
    )
    if sf_kind == "straight_flush":
        return "straight_flush", _fill_jokers(sf_hand, jokers)

    sf_kind_num, sf_hand_num = _try_get_straight_or_straight_flush(
        numbers, joker_count, required_len
    )
    if sf_kind_num == "straight_flush":
        return "straight_flush", _fill_jokers(sf_hand_num, jokers)

    kind, kind_hand = _get_best_of_a_kind(suited, joker_count)
    if kind in ("four_of_a_kind", "full_house"):
        return kind, _fill_jokers(kind_hand, jokers)

    flush_slots = _try_get_flush(suited, joker_count, required_len)
    if flush_slots is not None:
        return "flush", _fill_jokers(flush_slots, jokers)

    if sf_kind == "straight":
        return "straight", _fill_jokers(sf_hand, jokers)
    if sf_kind_num == "straight":
        return "straight", _fill_jokers(sf_hand_num, jokers)

    if kind != "high_card":
        return kind, _fill_jokers(kind_hand, jokers)

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
        [
            board.get_by_index(i)
            for i in path
            if card_suit(board.get_by_index(i)) or _is_joker(board.get_by_index(i))
        ],
        loadout,
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
