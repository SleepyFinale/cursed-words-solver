# Card scoring notes (decompiled)

## PokerHands.GetXOfAKind

`PokerHands.GetXOfAKind(int xOfAKind, List<Tile> tiles)`:

- non-joker cards: `tile.GetSuit() != 0 && tile.GetSuit() != Suit.Joker`
- jokers: `tile.GetSuit() == Suit.Joker`
- grouping key is `tile.GetStringRepresentation()`
- if jokers >= x, returns x jokers directly
- otherwise fills the first matching group where `group.Count + jokers.Count == x`

Implication: solver grouping should follow game string-representation grouping, with joker fill.

## Hanafuda.ApplyWordBonus

- hand type by level:
  - level1 => pair (2)
  - level2 => three-of-a-kind (3)
  - level3+ => four-of-a-kind (4)
- when hand exists:
  - sets `step.PokerHand` and `step.PokerHandTiles`
  - unused cards computed from `gridData.GetAvailableTiles()` with `CardSuit != 0` and not in submitted `tiles`
  - additive word bonus: `unused_cards * upgradeable_value`

Implication: Hanafuda bonus is strictly tied to available grid cards at scoring-time, not wiki shorthand.

## Bicycle.ApplyWordBonus

- iterates submitted path tiles
- for each tile with `CardSuit != 0`, adds per-card upgrade value to accumulator
- persists accumulator (`WordScoreBonus`) and emits additive word bonus
- **suited credit on path:** when at most one suit appears on the path (among non-joker suited tiles), credit is **1** (mono-suit collapse), **except** when a joker not at path end appears with **≥2 non-joker suited tiles** — then credit is the per-tile count of `CardSuit != 0` tiles (excluding path-end joker only); with multiple suits and any non-end joker but fewer than two non-joker suited tiles, credit is still per-tile; otherwise multi-suit credit is **unique suited card ranks** on the path
- melmod exports `card_suit` only from in-game `CardSuit` (packet / `GetCardSuit` methods), not display or field heuristics — plain letter tiles must not inherit spurious suits

Implication: accumulator timing matters; replay/tests must rewind post-submit extras when needed.

## Wrestlers.ApplyWordBonus

Uses first and last submitted tiles:

- both literal path endpoints must have `CardSuit != 0` (joker counts)
- proc when suits differ OR start suit is Joker OR (joker at path start, **≥2 non-joker suited tiles** on path, and path end is **suited** — suits may match) OR (joker at path start and path end, using inner first/last different-suited pair for bookends)
- unsuited letter at path end does **not** proc even when inner tiles are suited
- effect is multiplicative word bonus token

Implication: endpoint logic is literal path endpoints first; fallback heuristics only when path end is joker (bookends), not for unsuited letters.
