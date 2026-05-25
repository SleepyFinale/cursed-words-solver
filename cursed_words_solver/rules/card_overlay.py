"""Playing-card suit/rank parsing (used by melmod metadata tests)."""

from __future__ import annotations

import re

SUIT_SYMBOL_TO_NAME: dict[str, str] = {
    "♣": "clubs",
    "♠": "spades",
    "♥": "hearts",
    "♦": "diamonds",
}

SUIT_WORD_TO_NAME: dict[str, str] = {
    "club": "clubs",
    "clubs": "clubs",
    "spade": "spades",
    "spades": "spades",
    "heart": "hearts",
    "hearts": "hearts",
    "diamond": "diamonds",
    "diamonds": "diamonds",
}


def detect_card_overlay(text: str) -> tuple[str | None, str | None, bool]:
    """Return (suit, rank_hint, is_joker) from overlay text."""
    combined = text or ""
    lower = combined.lower()
    is_joker = bool(re.search(r"\bjoker\b", lower)) or "🃏" in combined
    if is_joker:
        return None, None, True

    suit: str | None = None
    for sym, name in SUIT_SYMBOL_TO_NAME.items():
        if sym in combined:
            suit = name
            break
    if suit is None:
        for word, name in SUIT_WORD_TO_NAME.items():
            if re.search(rf"\b{re.escape(word)}\b", lower):
                suit = name
                break

    rank: str | None = None
    cleaned = re.sub(r"[^A-Za-z0-9?]", "", combined.upper())
    for sym in SUIT_SYMBOL_TO_NAME:
        cleaned = cleaned.replace(sym, "")
    if cleaned:
        ch = cleaned[0]
        if ch.isalnum() and ch != "?":
            rank = ch

    return suit, rank, is_joker
