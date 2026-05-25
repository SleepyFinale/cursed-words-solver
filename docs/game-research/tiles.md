# Tile colours (game + wiki)

Source: `Tile.TileType`, `Tile.GetValue()`, `Tile.IsTileType()`, [wiki Tiles](https://cursedwords.wiki.gg/wiki/Tiles).

## Generatable pool

Default shop/scatter pool: **RED**, **BLUE**, **VOID**, **SHINY**. Other colours enter the pool when first encountered (except **GLITCH** — last-resort only, never added to generatable pool).

## TileType → solver `TileColor`

| Game `TileType` | Solver | Base score (GetValue) | Notes |
|-----------------|--------|----------------------|-------|
| Normal | colorless | Letter scrabble value | Not a “colour” for Dango |
| Red | red | +1 on packet | |
| Blue | blue | +1 on packet | Shield pin can override blue base |
| Shiny | shiny | Flat 50 | Ignores letter manipulators |
| Void | void | Packet × −1 | Sticky Plaster subtracts; Tombstone adds tile score normally |
| Cactus | cactus | +`CactusGrowth` packet | +1 per grid start; immutable colour |
| Pink | pink | Letter base | `StoreMoneyInPinkTiles`: −$1 per pink in word while money > 0 |
| Gold | gold | Current player money | |
| Green | green | Letter base | 10% of tile score → word score at finalize; poison on later words |
| Purple | purple | +2; `IsTileType(Red\|Blue)` true | Dual-colour for stickers/stamps |
| White | white | Letter base | Teleport to any unused grid cell (search) |
| Glitch | glitch | Letter until settle | `SettleGlitchTiles` before init scores |

## Pre-item pipeline order

See [scoring-pipeline.md](scoring-pipeline.md): glitch settle → init (`GetValue`) → currency money → pink piggy bank → items → green finalize transfer.

## Glitch settle pool (`SettleGlitchTiles`)

Colour roll (11 types, excludes Glitch): Normal, Blue, Cactus, Gold, Green, Purple, Pink, White, Red, Void, Shiny.

25% chance: random card suit. Glyph roll (0–7): random letter, currency, fraction, number, blank, scattered item, chess, bespoke joker card.

Solver uses deterministic RNG from path + run seed when board still shows `glitch` colour.
