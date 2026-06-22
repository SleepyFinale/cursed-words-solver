# Boss modifiers (game + wiki)

Source: `BossModifier` subclasses in `Assembly-CSharp.dll` (`data/game/boss_subclasses.json`), `ScoreCalculation.CalculateOverallScore`, [wiki Bosses](https://cursedwords.wiki.gg/wiki/Bosses).

## Scoring order (no Hourglass)

1. Glitch settle → init tile scores (`GetInitialScoreInfo`)
2. **Early bosses** — `ApplyBossModifier` each (`ReducedLetterValue`, `StealsMoney`, `NegativeMoney`)
3. Currency / pink (if applicable)
4. Pin → stickers → stamps
5. **Late bosses** (Hourglass only) — reversed `ApplyBossModifier` list

## Game class → wiki slug

| `BossModifier` | Wiki `boss_id` | Solver |
| ---------------- | ---------------- | -------- |
| `ReducedLetterValue` | salamander | `boss_tile_penalty` (early) |
| `NegativeMoney` | robo_monkey | `boss_subtract_word_score_money` (early) |
| `StealsMoney` | fox | `boss_steal_money` (early submit) + grid-start steal |
| `MaxWordLength` | wolf | search max length |
| `MinWordLength` | cobra | search min length |
| `BigBoss` | toothed_whale | target score multiplier |
| `RandomiseItemOrder` | capybara | shuffle sticker/stamp scoring order |
| `ExtraQs` | axolotl | scatter Q |
| `ExtraVoids` | mole | scatter void |
| `AddNumbers` | bison | scatter high numbers |
| `DiscolourTiles` | yeti_crab | strip tile colours |
| `DestroyGrid` | robo_eel | eat tiles (melmod board) |
| `SmallGrid` | bat | shrink grid (melmod board) |
| `FewerGrids` | badger | `grids_remaining` extra |
| `ForcedSell` | hyena | `hyena_blocked` until sell |
| `CretaceousMegBoss` | cretaceous_meg | meta / melmod loadout |

## Cursed bosses

`BossModifier.IsCursed` → `extras.boss_cursed`. Scaling uses `cursed_*` fields in catalog `scaling` rows.

## Hidden / meta bosses

| Game class | Wiki slug | In-game name | Prefab alias |
| --- | --- | --- | --- |
| `SandySaguaroBoss` | `sandy_saguaro` | Sandy Saguaro | `bosscactus` |
| `PrismaticBeanBoss` | `prismatic_bean` | Prismatic Bean | `bosscrystal` ([Beans (boss)](https://cursedwords.wiki.gg/wiki/Beans_(boss))) |
| `HumanBoyBoss` | `human_boy_boss` | Human Boy | `bosshumanboy` |

Also:

- **Michael** (`MichaelBoss`) — unlock after 5 cursed bosses
- **Ogre** — dual-cursed draft (map meta)

### Michael draft fight (implemented)

Decompiled from `MichaelBoss.PopulateModifierDrafts()`:

- Michael offers 3 draft rounds (`FloorAdjustedModification` in Area 6).
- Each round offers 2 boss modifiers and keeps the chosen one in `DraftedModifiers`.
- Drafted modifiers stack in `extras.boss_modifiers`.
- Per-modifier scaling comes from each draft's own `FloorAdjustedModification`
  (phase 1 index 5, phase 2 index 4, phase 3 index 3), not just run-stage area.
- Draft pool includes bosses with `CanBeSummonedByMichael = true`:
  Salamander, Yeti Crab, Robo-Eel, Mole, Axolotl, Bison, Bat, Badger, Capybara,
  Toothed Whale, and either Wolf or Cobra (never both in one Michael fight).
- Not draftable by Michael: Robo-Monkey, Fox, Hyena, Michael/meta bosses, secret
  character bosses.
- Finale (`SummonedBossesDefeated`) requires a 25-tile submission.

## Area scaling

`extras.boss_area_number` from run stage (1–5, clamped). Rows with `"na": true`
skip the boss (Fox area 5, Robo-Monkey area 5).
