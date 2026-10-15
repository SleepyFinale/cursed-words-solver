# Run structure (full-run simulator rules)

Decompiled from `Assembly-CSharp.dll` (`RunProgress`, `EncounterController`, `ShopController`,
`ItemPools`, `GridUtilitySingleton`, `EnglishDefaultAlphabet`, `BossRewardController`,
`PinDraftVisualController`, `GameStatics`). Regenerate sources locally into
`docs/game-research/_decompiled/run/` (gitignored) with `ilspycmd -t <Type>`.

Python port: [`sim/run_rules.py`](../../cursed_words_solver/sim/run_rules.py),
[`sim/shop.py`](../../cursed_words_solver/sim/shop.py),
[`sim/inventory.py`](../../cursed_words_solver/sim/inventory.py),
[`sim/grid_gen.py`](../../cursed_words_solver/sim/grid_gen.py),
[`sim/catalog.py`](../../cursed_words_solver/sim/catalog.py) (data:
`data/game/run_catalog.json` from `scripts/extract_run_catalog.py`).

## Crowns

`AscensionLevel` 0–8; each crown includes all lower ones. Playable crowns are 0–7
(`GameStatics.HighestCrownAvailable = 7`); level 8 `HarderBosses` exists in code only.
1 cursed bosses · 2 unkind shops (no first free pick, reroll starts at $2) · 3 lower letter
values · 4 two stamp padlocks · 5 harder letter weights · 6 two sticker padlocks · 7 one
fewer grid. The wiki ([Crowns](https://cursedwords.wiki.gg/wiki/Crowns)) agrees except
crown 3's letter list (code also lowers C and G) and implies a free item in every shop
(code: only the first shop of the run).

## Stages and nodes

5 stages (with the Numbers bulk unlock; 4 with Rainbow only, 3 otherwise), plus a sixth
Michael stage. `RunProgress.AdvanceToNextNodeType`:

```
stage 1:  EncounterFirst → ShopOne → EncounterSecond → ShopTwo → BossDraft → Boss → BossReward
stage 2+: ShopZero → EncounterFirst → ShopOne → EncounterSecond → ShopTwo → BossDraft → Boss → BossReward
stage 6:  ShopZero → EncounterFirst → ShopOne → EncounterSecond → ShopTwo → Boss (Michael)
```

Beating the stage-5 boss wins the run when crown < 1 **or** the player faced any uncursed
boss (`HasFacedUncursedBoss`). At crown ≥ 1, picking the cursed boss on all five floors
continues to stage 6 and Michael. Crown 0 has no cursed bosses, so no Michael.

## Encounter targets

`RunProgress.GetEncounterTarget` (float32 math, `Mathf.RoundToInt` = half-to-even):

```
base     = 12 * round(3.8 ^ (stage - 1))            # 12, 48, 168, 660, 2508, 9504
progress = ((stage - 1) * 3 + idx) / 14              # idx: First 0, Second 1, Boss 2
crownMul = 1 + crown * 0.4 * progress ^ 1.2
nodeMul  = 1.0 / 1.4 / 2.0                           # First / Second / Boss
target   = round(base * nodeMul * crownMul * (1 - divingMask% / 100))
```

Checked against 697 recorded encounters (non-quest): 653 exact; the rest are Michael
(separate scaling, open) and Diving Mask (percent not exported).

## Grids, rerolls, payouts

- Grids per encounter: 5, −Badger (`FewerGrids`) floor value, +1 per Diya, −1 at crown 7.
- One grid reroll per encounter (Wheel makes it cost $1).
- Clear payout: $10 + $2 per unused grid, +$5 on a boss. Dragon: +floor(10% × (money +
  payout)) per Dragon.
- Ogre (Common stamp, $12): the wiki says bosses give double reward money, and the
  rewards panel shows "Ogre bonus" +$5 per Ogre — but the decompiled `TryGoToNextGrid`
  never passes it to `ChangeMoney`. Unverified in game (`OGRE_BONUS_CREDITED`).

## Grid generation

`GenerateBasicGridData`: every tile is an independent weighted letter, colourless.
Weights (Scrabble-like) `e12 a9 i9 o8 n6 r6 t6 d4 l4 s4 u4 g3 …`; crown 5 switches to the
flatter ascension weights; crown 3 lowers letter values (e.g. E and S worth 0). Item,
challenge, then boss start-of-grid adjustments follow (reversed with an odd number of
Hourglasses).

## Shop

Stock: 4 stickers, 2 stamps, 2 consumable tiles.

- **Pools:** item slot is by `UpgradeableComponents.Count` (0 stamp, 1 sticker, 2 pin).
  Unique/Weird rarities never appear. 137 stickers, 146 stamps (fully unlocked).
- **Rarity:** stickers 10% rare; stamps 1% legendary, 13% rare (same roll). Genie ×3 each.
- **Foil:** 1% per sticker (Fortune Cookie 5%). Buying a foil of an owned sticker foils it
  (+2 max upgrades).
- **Build bias** (`GetRandomBuildBiasedSticker/Stamp`), in order, each a 1-in-10 roll:
  unfulfilled dependency tag → (stickers, only when 5 owned) upgrade of an owned non-maxed
  sticker (1 in `(6 − owned) × 5 + 5`) → top-3 build-synergy tags by count (pin tags
  count) → generator tag (only stage 1 or no generator owned) → uniform by rarity.
- **Blacklist:** maxed owned stickers, owned stamps, items already in stock or frozen,
  embargoed types.
- **First shop** (stage 1 ShopOne, crown < 2): all Common, one random sticker slot is
  build-biased, and the first purchase is free (`IsFirstDiscount`).
- **Prices:** `Cost − Discount`, ×2 per Avocado, −$4 on red items with Northern Cardinal,
  $10 flat with Blessing of the Shopkeeper. Tiles $2–4 by colour (Falling Leaf $1).
- **Reroll:** $1 (crown ≥ 2: $2), +$1 per reroll, −$1 with Fried Shrimp. Frozen items
  survive rerolls and carry to the next shop.
- **Buying an owned sticker** upgrades it (max 2 upgrades, 4 if foil) instead of using a
  slot. Stickers 5 slots, stamps 5 (crown 4/6 add padlocks), consumables 5 (10 with Stadium).
- **Sell value:** half the purchase price + a quarter of each upgrade payment (Receipt:
  full refund).
- **Consumable tiles:** glyph weights letter 19 / blank 1 / number 1 / joker 1 / chess 1
  (fully unlocked); 10% get a card suit. Letters always roll a colour; other glyphs roll
  from the available colours, which never include Normal.

## Bosses

`RunProgress.GetRandomBossDrafts`: five floors of two bosses, no boss twice per run,
respecting `BannedFloorIndexes`; secret-character bosses and Michael excluded. Crown ≥ 1
curses one random option per floor (`DifficultyModifier += DifficultyIncrease`). Strength is
`DifficultyModifier[floor]` (crown 8: `[floor + 1]`).

Ogre: buying it curses both options on the current floor (`OnAcquire`; they stay cursed
if Ogre is sold). Leaving BossReward while holding Ogre curses both options on the next
floor. Cursed wins only count toward Michael at crown ≥ 1. At crown ≥ 1 an all-cursed
run cannot win at stage 5 and must go on to Michael.

## Pin draft (boss reward)

Upgrade the pin's left or right side (`UpgradeableComponent`: level +1, value +increment).
ID Card offers both.

## Not yet ported

Michael fight targets/drafts, Meg shop, secret bosses (Hayley Bayles unlock), quests
(`ChallengeRun` rules), per-item shop hooks (Hungry Hippo, Frankenstein, Eraser, Delivery
Truck, Future Funds, Downward Trending Chart, Roller Skate, Rollercoaster, Lollipop,
Snail, Stack of Pancakes), item-order effects of challenge runs, unlock profiles other
than "everything unlocked".
