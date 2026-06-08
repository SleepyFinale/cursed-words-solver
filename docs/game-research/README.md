# Game research (Assembly-CSharp)

Notes derived from the installed game DLL (`Cursed Words_Data/Managed/Assembly-CSharp.dll`) via ILSpy/ilspycmd. **Do not commit** full decompiled sources — regenerate locally into `_decompiled/` (gitignored).

## Regenerate

```powershell
$dll = "C:\Program Files (x86)\Steam\steamapps\common\Cursed Words\Cursed Words_Data\Managed\Assembly-CSharp.dll"
$out = "docs\game-research\_decompiled"
ilspycmd $dll -t ScoreCalculation -o $out
ilspycmd $dll -t EncounterController -o $out
ilspycmd $dll -t Item -o $out
ilspycmd $dll -t Player -o $out
ilspycmd $dll -t Tile -o $out
ilspycmd $dll -t Hanafuda -o $out
ilspycmd $dll -t PokerHands -o $out
ilspycmd $dll -t Wrestlers -o $out
ilspycmd $dll -t Bicycle -o $out
ilspycmd $dll -t Joker -o $out
ilspycmd $dll -t ScoreCalcVizInfo -o $out
ilspycmd $dll -t WordBonusToken -o $out
# Or: dotnet run --project scripts/decompile_type -- $dll ScoreCalculation Hanafuda ...
python scripts/extract_game_types.py  # Item subclasses + shop advice tags
python scripts/extract_stamp_types.py
python scripts/extract_tile_enums.py
python scripts/generate_sticker_audit.py
python scripts/generate_stamp_audit.py
python scripts/generate_tile_audit.py
python scripts/extract_boss_types.py
python scripts/enrich_boss_catalog.py
python scripts/generate_boss_audit.py
```

## Documents

| File | Purpose |
| ---- | ---- |
| [../SEARCH_ARCHITECTURE.md](../SEARCH_ARCHITECTURE.md) | Solver search/scoring performance architecture |
| [../DATA_STRUCTURE_ANALYSIS.md](../DATA_STRUCTURE_ANALYSIS.md) | Profiling results and hot-path analysis |
| [scoring-pipeline.md](scoring-pipeline.md) | In-game `CalculateOverallScore` order vs wiki |
| [effect-taxonomy.md](effect-taxonomy.md) | JSON schema + `Item` subclass mapping |
| [sticker-audit.md](sticker-audit.md) | Catalog vs game-type coverage (generated) |
| [stamps.md](stamps.md) | Stamp taxonomy, movement flags, orchestration |
| [stamp-audit.md](stamp-audit.md) | Per-stamp catalog status (generated) |
| [tiles.md](tiles.md) | Tile colours, base scores, glitch/pink/green |
| [curses.md](curses.md) | GlyphType / curse mapping |
| [tile-audit.md](tile-audit.md) | Enum vs taxonomy coverage (generated) |
| [bosses.md](bosses.md) | BossModifier taxonomy and scoring order |
| [boss-audit.md](boss-audit.md) | Per-boss implementation status (generated) |

## Solver mapping

| Game | Solver module |
| ---- | ------------- |
| `EncounterController.GetItemsForWordSubmission` | `cursed_words_solver/rules/scoring_order.py` |
| `Item.ApplyStartOfGridEffect` | `cursed_words_solver/rules/grid_effects.py` |
| `ScoreCalculation.CalculateOverallScore` | `cursed_words_solver/rules/pipeline.py` |
| Per-solve loadout snapshot | `cursed_words_solver/solve_context.py` |
| Board topology / chess masks | `cursed_words_solver/graph_bitboard.py`, `rules/chess_tiles.py` |
| Board-static scoring precompute | `cursed_words_solver/board_scoring_context.py` |
| Static vs dynamic rule classification | `cursed_words_solver/rules/rule_phase.py` |
| Tier-2 bounds / fast rank | `cursed_words_solver/fast_rank.py` |
| Stamp movement / letter substitution | `stickers.json` → `search_flags`, `stamp_behaviors.py` |
