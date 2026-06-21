# Character pins (game research)

Source: decompiled `Item` subclasses in `Assembly-CSharp.dll`. Pins are `CharacterItem` with two `UpgradeableComponents`: **index 0 = left** (grid), **index 1 = right** (scoring).

Wiki: [List of pins](https://cursedwords.wiki.gg/wiki/List_of_pins)

## Scoring order

`Player.GetAllItems()` → pin (`MyCharacter.GetCharacterItem()`), then stickers, then stamps. `ScoreCalculation.CalculateOverallScore` calls `Item.ApplyItemToScore` on each (Hourglass reverses the list).

Pin scoring hooks:

- **Left:** `ApplyStartOfGridEffect` / `StartOfEncounterSetUp` (not in word-score loop)
- **Right:** `ApplyTileBonus` / `ApplyWordBonus` inside `ApplyItemToScore`

## Per-pin summary

| Slug | Game class | Left (component 0) | Right (component 1) |
| ---- | ---------- | -------------------- | --------------------- |
| `abacus` | `Abacus` | Scatter unique numbers 1–5 on grid | +`VariableValue` TILE SCORE per coloured number on path |
| `milky_way` | `MilkyWay` | Scatter VOID tiles | VOID tiles % chance → SHINY (`VariableValue` on right) |
| `rainbow` | `Rainbow` | Scatter unusual colour tile | +`VariableValue` WORD SCORE per unique colour on path |
| `sam_gambit` | `SuperEight` | Scatter chess pieces by left level | +`VariableValue` × chess take count (`ChessTake` / `EnPassant`) |
| `bones_the_dog` | `Bicycle` | Scatter suited cards | Add suited-on-path × right rate to `WordScoreBonus`, then +WORD |
| `bucket` | `Bucket` | Scatter bucket tiles | (none) |
| `random_access_memory` | `RandomAccessMemory` | Memory draft (meta) | Replay `ItemsInMemory` in score loop (blacklist some types) |
| `mahjong_red_dragon` | `MahjongRedDragon` | Encounter red consumable | ×TILE SCORE on consumables (`2 + right` factor) |
| `cretaceous_meg` | `WadOfCash` | Scatter currency | +10 TILE SCORE on currency tiles |
| `human_boy` | `HumanHands` | Favourite sticker level boost (left hand) | Favourite stamp extra applications (right hand) |
| `rodman` | `CarpStreamers` | Scatter 1 RED + 1 BLUE | (none) |

## Special cases

### Random Access Memory

- **Field:** `public List<Item> ItemsInMemory` (acquisition order preserved).
- **Draft blacklist** (`BlacklistedItemTypes`, cannot be offered after boss): `BeamMeUp`, `CrystalBall`, `Dartboard`, `EightBall`, `HungryHippo`, `LuckyDice`, `MysteryGift`, `NestEgg`, `Overhand`, `SewingNeedle`, `SignalReceiver`, `Snapshot`, `Underhand`, `Unicorn`.
- **Solver slugs:** `beam_me_up`, `crystal_ball`, `dartboard`, `magic_8_ball`, `hungry_hippo`, `lucky_dice`, `mystery_gift`, `nest_egg`, `overhand`, `sewing_needle`, `signal_receiver`, `snapshot`, `underhand`, `unicorn` (see `cursed_words_solver/rules/ram_memory.py`).
- **Scoring order (wiki):** scattered grid-item tiles on path → RAM memory items (in order) → equipped stickers/stamps.
- **Movement stamps** (e.g. `hungry_snake`) can be stored in RAM; they affect search via `pin_memory`, not word-score replay.

### Human Hands

Favourite stamp is the stamp **after** `right_hand` in inventory (`Stamps[i-1] is RightHumanHand`). Extra stamp applications: `right.VariableValue - 1` times in game loop.

### Bicycle

`WordScoreBonus` field persists on pin; each word adds `suited_on_path × UpgradeableComponents[1].VariableValue` then applies total as additive WORD bonus.

### Super 8

`ApplyWordBonus`: `UpgradeableComponents[1].VariableValue * take_count` where take_count includes en passant.

## Solver mapping

| Game | Solver |
| ---- | ------ |
| `UpgradeableComponents[i].VariableValue` | `extras.pin_left_variable` / `pin_right_variable` (melmod) |
| `UpgradeableComponents[i].Level` | `extras.pin_left_level` / `pin_right_level` |
| Left scatter | `pins[].left` → `grid_effects.apply_pin_grid_mutations` |
| Right score | `pins[].right` → `pin_effects.apply_pin_scoring` |

Regenerate audit: `python scripts/generate_pin_audit.py`
