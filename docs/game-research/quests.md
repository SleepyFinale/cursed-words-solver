# Quest / Challenge research

Wiki quest names differ from C# `ChallengeRun` subclasses. Canonical mapping lives in:

- `data/game/quest_taxonomy.json` — 26 `ChallengeRun` subclasses from `Assembly-CSharp.dll`
- `data/wiki/quests.json` — wiki slugs, unlock items, steam achievements, effect classes

Decompiled references: `scripts/decompile_type/out_quests/`. Shop hooks: `scripts/decompile_type/out_shop/ShopController.decompiled.cs`, `scripts/decompile_type/out/EncounterController.decompiled.cs`.

## Melmod export

`run_state.json` includes:

| Field | Source |
|-------|--------|
| `challenge_game_class` | `CurrentRunProgress.Challenge` type name (e.g. `SicilianDefense`) |
| `challenge_name` | `ChallengeName` (wiki display, e.g. `Knight Time`) |
| `challenge_elite` | `EliteQuest` |
| Per-tile `is_crossed_out` | `Tile.IsCrossedOut` (On Cooldown) |
| Per-tile `is_up_and_up_center` | `Tile.IsNumberGoUpMiddleTile` |
| `extras.up_and_up_center_*` | Center cell index/number for Up and Up |
| `extras.favourite_*_ids` | Playing Favourites HumanBoy favourites |
| `extras.embargoed_item_types` | `CurrentRunProgress.EmbargoedItemTypes` (C# class names) |
| `extras.embargoed_item_slugs` | Slugified embargo types for Python |

## Grid solver integration

| Module | Role |
|--------|------|
| `rules/quest_effects.py` | Path filters, Playing Favourites loadout filter |
| `rules/quest_movement.py` | Knight Time knight-only `GetValidNextTiles` branch |
| `rules/quest_scoring.py` | Bones Round poker, Lexographer, Two Wrongs / Bullseye targets, Do Not Pass Go encounter rewards |

## Shop quests (`effect_class: shop_only`)

Quest classes are thin `ChallengeRun` stubs; rules live in `ShopController` / `EncounterController`.

| Wiki name | Game class | Game hook | Solver (`shop_quest_effects.py`) |
|-----------|------------|-----------|----------------------------------|
| Shelf Life | `DecisionParalysis` | Block manual reroll; auto-restock on buy | `block_restock` |
| Secret Santa | `SecretSanta` | Foil/legendary quips hide identity | Warning only |
| Antiphilatelist | `Antiphilatelist` | No stamp slots / generation | Filter stamp offers |
| Masochist | `Masochist` | No sticker slots / generation | Filter sticker offers |
| In The Beginning | `InTheBeginning` | No sticker or stamp slots | Filter both |
| Do Not Pass Go | `DoNotPassGo` | $0 encounter/boss/grid rewards | `encounter_reward_for_quest`; angel investment note |
| Embargo | `Embargo` | Boss wipe + `EmbargoedItemTypes` pool ban; no selling | Filter embargoed types; `block_sell` |

F8 shop advice: [`shop_advisor.py`](../../cursed_words_solver/shop_advisor.py) → [`game_shop/recommendation.py`](../../cursed_words_solver/game_shop/recommendation.py) with quest filtering before `ShopRecommendation` logic.
