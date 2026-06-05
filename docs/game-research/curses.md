# Tile curses / glyphs (game + wiki)

Source: `GlyphType`, `Tile.GetGlyphType()`, melmod `BoardExporter.MapCurse`, [wiki Tiles](https://cursedwords.wiki.gg/wiki/Tiles).

## GlyphType → solver `CurseType` / melmod string

| Game `GlyphType` | Melmod curse | Solver `CurseType` | Base score |
| ---------------- | ------------ | ------------------- | ---------- |
| Letter | letter | letter | Scrabble letter value |
| Blank | wildcard | wildcard | 0 |
| Number | number | number | Tile number value |
| Fraction | fraction | fraction | Sum of numerator + denominator |
| Currency | currency | currency | 0; +$1 on submit (Kokeshi: scrabble value) |
| Chess | chess_* | chess_pawn…king | Chess piece table |
| BespokeCard | card / wildcard | card | 0 + suit |
| ScatteredItem | item | item | 0; scored via item pipeline |
| Arrow | arrow | arrow | Wobbly / redirect (item-granted) |
| None | letter | letter | Inactive / destroyed |

Playing cards use `BespokeCard` or legacy `Card` enum name; joker uses `Suit.Joker`.

## Currency symbols (13)

฿→B, ¥→Y, $→S, ₡→C, €→E, ₭→K, ₮→T, ₦→N, ₩→W, ₱→P, ₣→F, ₲→G — see `CURRENCY_MAP` in `models.py`.

## Search rules

- **Number**: position must match value (1 = first letter), unless Test Tube / Number Go Up / wildcards. **Microscope**: a tile may also use its `base_score` as an alternate number value (e.g. blue 5 with base 6 → position 5 or 6; letter V with base 4 → letter anywhere, or number at position 4).
- **Fraction**: valid in numerator or denominator slot positions.
- **Chess**: piece-specific movement; take metadata for scoring stickers.
- **WHITE colour**: teleport neighbors (not a glyph).

## Purple dual-type

`Tile.IsTileType(Red)` and `IsTileType(Blue)` return true when `MyTileType == Purple`. Solver: `tile_counts_as_color(tile, RED|BLUE)`.
