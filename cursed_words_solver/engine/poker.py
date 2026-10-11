"""Port of the game's ``PokerHands`` helpers (hand detection over suited tiles).

Jokers are shuffled in game but interchangeable for scoring, so they are kept in
path order. ``None`` entries in intermediate hands stand for joker slots exactly
like the C# lists.
"""

from __future__ import annotations

from cursed_words_solver.engine.model import G_LETTER, G_NUMBER, LETTERS, SUIT_JOKER, SUIT_NONE, ETile

HAND_POINTS = {
    "god_flush": 3000,
    "monster_flush": 2750,
    "wicked_flush": 2500,
    "unreal_flush": 2250,
    "ludicrous_flush": 2000,
    "ultra_flush": 1800,
    "mega_flush": 1600,
    "impressive_flush": 1400,
    "flush_spree": 1200,
    "royal_flush": 1000,
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


def _split(tiles: list[ETile]) -> tuple[list[ETile], list[ETile]]:
    cards = [t for t in tiles if t.suit not in (SUIT_NONE, SUIT_JOKER)]
    jokers = [t for t in tiles if t.suit == SUIT_JOKER]
    return cards, jokers


def _rank_value(t: ETile, is_number: bool) -> int:
    if is_number:
        return int(t.number or 0)
    srep = t.srep
    return LETTERS.index(srep) if srep in LETTERS else -1


def _sorted_letters(cards: list[ETile]) -> list[ETile]:
    return sorted((t for t in cards if t.glyph == G_LETTER), key=lambda t: t.srep, reverse=True)


def _sorted_numbers(cards: list[ETile]) -> list[ETile]:
    return sorted((t for t in cards if t.glyph == G_NUMBER), key=lambda t: int(t.number or 0), reverse=True)


def _straight_or_flush(
    cards: list[ETile], joker_count: int, required: int
) -> tuple[list[ETile | None] | None, str]:
    """``TryGetStraightOrStraightFlush`` → (hand, 'straight_flush'|'straight'|'none')."""
    if len(cards) + joker_count < required:
        return None, "none"
    if joker_count >= required and cards:
        return [cards[0], None, None, None, None], "straight_flush"
    is_number = cards[0].is_number()
    fallback: list[ETile | None] | None = None
    for start in cards:
        loose: list[ETile | None] = [start]
        suited: list[ETile | None] = [start]
        top = _rank_value(start, is_number)
        for k in range(1, required):
            need = top - k
            match = next(
                (c for c in cards if c.suit == start.suit and _rank_value(c, is_number) == need),
                None,
            )
            if match is not None:
                if fallback is None:
                    loose.append(match)
                suited.append(match)
                continue
            suited.append(None)
            if fallback is None:
                loose.append(next((c for c in cards if _rank_value(c, is_number) == need), None))
        if sum(1 for c in suited if c is None) <= joker_count:
            return suited, "straight_flush"
        if fallback is None and sum(1 for c in loose if c is None) <= joker_count:
            fallback = loose
    if fallback is None:
        return None, "none"
    return fallback, "straight"


def _complement(cards: list[ETile | None], jokers: list[ETile]) -> list[ETile]:
    out: list[ETile] = []
    j = 0
    for c in cards:
        if c is None:
            out.append(jokers[j])
            j += 1
        else:
            out.append(c)
    return out


def _try_flush(cards: list[ETile], joker_count: int, required: int) -> list[ETile | None] | None:
    if len(cards) + joker_count < required:
        return None
    if joker_count >= required:
        return [None] * required
    by_suit: dict[str, list[ETile | None]] = {}
    for card in cards:
        group = by_suit.setdefault(card.suit, [])
        group.append(card)
        if len(group) + joker_count >= required:
            while len(group) < required:
                group.append(None)
            return group
    return None


def _best_of_a_kind(cards: list[ETile], joker_count: int) -> tuple[list[ETile | None], str]:
    if joker_count >= 4:
        return [None, None, None, None], "four_of_a_kind"
    if joker_count == 3:
        if cards:
            return [cards[0], None, None, None], "four_of_a_kind"
        return [None, None, None], "three_of_a_kind"
    if joker_count == 2 and not cards:
        return [None, None], "pair"
    groups: dict[str, list[ETile | None]] = {}
    for card in cards:
        key = card.srep
        if key in groups:
            groups[key].append(card)
            if len(groups[key]) + joker_count == 4:
                while len(groups[key]) < 4:
                    groups[key].append(None)
                return groups[key], "four_of_a_kind"
        else:
            groups[key] = [card]
    trips = pair = pair2 = None
    for value in groups.values():
        if len(value) == 3:
            if trips is None:
                trips = value
        elif len(value) == 2:
            if pair is None:
                pair = value
                if trips is not None:
                    return list(trips) + list(pair), "full_house"
            elif pair2 is None:
                pair2 = value
    if trips is not None:
        if joker_count > 0:
            return [trips[0], trips[1], trips[2], None], "four_of_a_kind"
        if pair is not None:
            return [trips[0], trips[1], trips[2], pair[0], pair[1]], "full_house"
        return trips, "three_of_a_kind"
    if pair is not None:
        if joker_count == 1:
            if pair2 is None:
                return [pair[0], pair[1], None], "three_of_a_kind"
            return [pair[0], pair[1], None, pair2[0], pair2[1]], "full_house"
        if pair2 is None:
            return [pair[0], pair[1]], "pair"
        return [pair[0], pair[1], pair2[0], pair2[1]], "two_pair"
    if joker_count == 2:
        return [cards[0], None, None], "three_of_a_kind"
    if joker_count == 1:
        return [cards[0], None], "pair"
    return [cards[0]], "high_card"


def poker_hand(tiles: list[ETile], required: int) -> tuple[list[ETile] | None, str]:
    """``GetPokerHandFromTiles`` → (hand tiles, hand name or 'none')."""
    cards, jokers = _split(tiles)
    if not cards and not jokers:
        return None, "none"
    if len(cards) + len(jokers) == 1:
        return [cards[0] if cards else jokers[0]], "high_card"
    if len(jokers) >= required:
        return jokers[:required], "straight_flush"
    letters = _sorted_letters(cards)
    numbers = _sorted_numbers(cards)
    letter_hand, letter_kind = _straight_or_flush(letters, len(jokers), required)
    if letter_kind == "straight_flush":
        return _complement(letter_hand, jokers), "straight_flush"
    number_hand, number_kind = _straight_or_flush(numbers, len(jokers), required)
    if number_kind == "straight_flush":
        return _complement(number_hand, jokers), "straight_flush"
    kind_hand, kind = _best_of_a_kind(cards, len(jokers))
    if kind in ("four_of_a_kind", "full_house"):
        return _complement(kind_hand, jokers), kind
    flush = _try_flush(cards, len(jokers), required)
    if flush is not None:
        return _complement(flush, jokers), "flush"
    if letter_kind == "straight":
        return _complement(letter_hand, jokers), "straight"
    if number_kind == "straight":
        return _complement(number_hand, jokers), "straight"
    return _complement(kind_hand, jokers), kind


def get_flush(tiles: list[ETile], required: int) -> list[ETile] | None:
    cards, jokers = _split(tiles)
    hand = _try_flush(cards, len(jokers), required)
    if hand is None:
        return None
    return _complement(hand, jokers)


def get_straight(tiles: list[ETile], required: int) -> list[ETile] | None:
    cards, jokers = _split(tiles)
    if len(cards) + len(jokers) <= 1:
        return None
    if len(jokers) >= required:
        return jokers[:required]
    hand, kind = _straight_or_flush(_sorted_letters(cards), len(jokers), required)
    if kind in ("straight_flush", "straight"):
        return _complement(hand, jokers)
    hand, kind = _straight_or_flush(_sorted_numbers(cards), len(jokers), required)
    if kind in ("straight_flush", "straight"):
        return _complement(hand, jokers)
    return None


def get_x_of_a_kind(x: int, tiles: list[ETile]) -> list[ETile] | None:
    cards, jokers = _split(tiles)
    jokers = list(jokers)
    if len(jokers) >= x:
        return jokers[:x]
    groups: dict[str, list[ETile]] = {}
    for card in cards:
        group = groups.setdefault(card.srep, [])
        group.append(card)
        if len(group) + len(jokers) == x:
            while len(group) < x:
                group.append(jokers.pop(0))
            return group
    return None


def max_distinct_pairs(tiles: list[ETile]) -> list[list[ETile]]:
    """``Scissors.GetMaxDistinctPairs`` (rank = glyph + string representation)."""
    if len(tiles) < 2:
        return []
    jokers = [t for t in tiles if t.suit == SUIT_JOKER]
    groups: dict[str, list[ETile]] = {}
    for t in tiles:
        if t.suit in (SUIT_JOKER, SUIT_NONE):
            continue
        groups.setdefault(f"{t.glyph}_{t.srep}", []).append(t)
    pairs: list[list[ETile]] = []
    used: set[str] = set()
    for key, group in groups.items():
        if len(group) >= 2:
            pairs.append([group[0], group[1]])
            used.add(key)
    for key, group in groups.items():
        if not jokers:
            break
        if len(group) == 1 and key not in used:
            pairs.append([group[0], jokers.pop(0)])
            used.add(key)
    while len(jokers) >= 2:
        pairs.append([jokers.pop(0), jokers.pop(0)])
    return pairs
