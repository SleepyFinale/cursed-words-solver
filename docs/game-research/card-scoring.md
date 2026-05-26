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

Implication: accumulator timing matters; replay/tests must rewind post-submit extras when needed.

## Wrestlers.ApplyWordBonus

Uses first and last submitted tiles:

- both must have `CardSuit != 0`
- proc when suits differ OR start suit is Joker
- effect is multiplicative word bonus token

Implication: endpoint logic is literal path endpoints first; fallback heuristics should only be used for capture gaps.
