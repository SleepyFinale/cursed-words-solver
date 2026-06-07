# Michael boss (decompile notes)

Source: `Assembly-CSharp.dll` (`MichaelBoss`, `EncounterController`, `TileSelectionManager`).

## Encounter flow

1. Michael intro
2. Draft 1 (choose 1 of 2 bosses)
3. Wordsmith grids with selected modifiers
4. Draft 2
5. Draft 3
6. Finale grid — 25-tile word on `EncounterController` (not only `PuzzleController`)

## Draft pool

Michael can only draft boss modifiers where `CanBeSummonedByMichael = true`.

Draftable:

- salamander
- yeti_crab
- robo_eel
- mole
- axolotl
- bison
- bat
- badger
- capybara
- toothed_whale
- wolf **or** cobra (one family removed each run)

Not draftable:

- robo_monkey
- fox
- hyena
- meta/secret bosses

## Scaling

When draft options are created, each option calls:

`boss.SetFloorAdjustedModification(5 - draftIndex, false)`

So each drafted modifier keeps its own live floor-adjusted value. This is exported
as `extras.boss_modifier_floor_mods` and must be used for stacked Michael scoring.

## Finale

After drafted bosses are defeated, `MichaelBoss.SummonedBossesDefeated` (on
`Player.ActiveBossModifiers[0]`, not `EncounterController.GetBossModifiers()`) enables the
finale rule: submission must include all 25 tiles. `TileSelectionManager` blocks words
with fewer than 25 selected tiles while that flag is set.
