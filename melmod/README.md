# MelonLoader companion (recommended)

This MelonLoader mod writes files under `%USERPROFILE%\.cursed_words_solver\` while you play:

- **Loadout** — character, stickers, stamps, boss, pin, money (`run_state.json`)

- **Board** — live 5×5 tiles (letters, scores, colors, curse types) from game `GridData` (`run_state.json`)

- **Dictionary** — full active-language vocabulary from game `WordTrie` (`game_words.txt` + `game_words_meta.json`)

- **Auto-export** when loadout or board changes (~0.5s debounce)

- **F7** in-game forces an immediate refresh (MelonLoader console log)

- **Boss context** — `boss_id`, `boss_name`, plus `extras.boss_area_number` (from `Player.CurrentRunProgress.GetStage()`), `extras.boss_cursed` (from `BossModifier.IsCursed`), `extras.hyena_blocked`. Boss discovery uses live `EncounterController.GetBossModifiers()` (then player `ActiveBossModifiers`); fields are **cleared** when no boss is active (leaving a Wolf fight clears `boss_id` on the next export). Scoring hooks clear their cache when `bossModifiers` is empty. Wolf maps from game type `MaxWordLength` → wiki id `wolf`. **Bat** boards export all 25 slots with `active: false` on unused cells plus `rows`/`cols` (height × width from `GridData.Dimensions`). After rebuilding the companion, press **F7** in-game before **F8** solve so shrunk grids (e.g. 3×4) export with the correct active columns.

The Python solver reads `run_state.json` on every **F8** solve. When `board` is present, it skips screenshot OCR entirely. It prefers `game_words.txt` for word validation so suggestions match what the game accepts (ENABLE1 includes many words the game rejects).

Do not bind F8 in the mod — that is the solver hotkey.

## Scoring mismatch capture (v1.1+)

When the solver’s predicted score does not match the game after you play the **F8 suggestion**, the mod writes a debug bundle you can turn into a regression test.

**Workflow**

1. In-game: **F7** (refresh board/loadout), then run the Python solver and press **F8**.
2. Solver writes `%USERPROFILE%\.cursed_words_solver\last_suggestion.json` (`scoring_word` / `word`, `path`, fingerprints, `predicted_trace`; optional `dictionary_word` when the game will spell it differently).
3. Trace the **exact highlighted path** on the **same board** (before the grid changes) and submit. The game shows the **dictionary** spelling (e.g. `settee`); the solver stores the **scoring** form (e.g. `12ttee` with number/shiny tiles). Capture matches on **path + board fingerprint**, not the word string.
4. On submit, Harmony hooks read the game’s `ScoreCalculation.CalculateOverallScore` steps.
5. If totals differ → `scoring_mismatches\<timestamp>.json` with `predicted_trace`, `actual_trace`, and `run_state_snapshot`.

If you play the same dictionary word on a **different valid path** (e.g. another ending tile), capture is skipped — predicted score is only valid for the F8 path.

MelonLoader console logs `Scoring MISMATCH` with the file path, or `Scoring match` when totals agree.

**Where files live**

| File | Path |
|------|------|
| F8 prediction (written by Python) | `%USERPROFILE%\.cursed_words_solver\last_suggestion.json` |
| Mismatch bundles (written by mod) | `%USERPROFILE%\.cursed_words_solver\scoring_mismatches\*.json` |
| Solver debug per F8 | `%USERPROFILE%\.cursed_words_solver\debug\parse_*.json` |

On startup the mod prints the mismatch folder path. After each word submit you should see either `Scoring capture: tracking suggested word …` or `Scoring capture skipped: …` (explains why it did not match, e.g. different path or board changed).

If you only see a score difference in-game but **no** `scoring_mismatches` file, the mod did not recognize the submit as the F8 suggestion — check the skip message (alternate path vs board changed), press **F8** again, then submit on the **highlighted path** before the board changes.

**Turn a mismatch into pytest**

```powershell
python scripts/mismatch_to_test.py $env:USERPROFILE\.cursed_words_solver\scoring_mismatches\20260523_143022.json
```

See [`SCORING_HOOKS.md`](SCORING_HOOKS.md) for hooked game types (`EncounterController.SubmitWord`, `ScoreCalculation.CalculateOverallScore`, etc.).

## Install MelonLoader and the companion mod

From the **repository root** in PowerShell. Steam default game path:

`C:\Program Files (x86)\Steam\steamapps\common\Cursed Words\`

### 1. Prerequisites (one-time)

- **Close the game** before installing or updating mods.
- Install [VC++ 2015–2022 x64](https://aka.ms/vs/17/release/vc_redist.x64.exe) (Cursed Words is 64-bit Mono; you do **not** need .NET 6 for this game).
- Install the [.NET SDK](https://dotnet.microsoft.com/download) to build the companion DLL.

### 2. Install MelonLoader

**Automated (this repo):**

```powershell
.\melmod\install-melonloader.ps1
```

Custom Steam/library path:

```powershell
.\melmod\install-melonloader.ps1 -GameDir "D:\SteamLibrary\steamapps\common\Cursed Words"
```

This downloads [MelonLoader x64](https://github.com/LavaGang/MelonLoader/releases/latest/download/MelonLoader.x64.zip), copies `MelonLoader\`, `version.dll`, and `dobby.dll` into the game folder, and creates `Mods\`.

**Alternatives:** [MelonLoader installer](https://github.com/LavaGang/MelonLoader/releases) (pick Cursed Words from Steam), or [Thunderstore MelonLoader](https://thunderstore.io/c/cursed-words/p/LavaGang/MelonLoader/) via r2modman/Gale. See [melonwiki.xyz](https://melonwiki.xyz).

### 3. Launch the game once

Start **Cursed Words** from Steam so MelonLoader finishes setup (`UserData\`, `MelonLoader\Logs\`). You should see a MelonLoader console on first run. Quit before rebuilding the mod.

### 4. Build and deploy the companion mod

```powershell
.\melmod\build.ps1
```

Custom game path:

```powershell
.\melmod\build.ps1 -GameDir "D:\Games\Cursed Words"
```

This builds `CursedWordsSolverCompanion.dll` and copies it to `Cursed Words\Mods\`.

**One-liner** (MelonLoader + mod, after prerequisites):

```powershell
.\melmod\install-melonloader.ps1; .\melmod\build.ps1
```

## Expected JSON shape

```json
{
  "character": "CharacterName",
  "pin_branch": "left",
  "money": 42,
  "stickers": [
    {"id": "sticky_plaster", "name": "Sticky Plaster", "level": 2}
  ],
  "stamps": [{"id": "newspaper", "name": "Newspaper"}],
  "boss_id": "mole",
  "boss_name": "Mole",
  "boss_effect": "",
  "extras": {
    "boss_area_number": "2",
    "boss_cursed": "false",
    "hyena_blocked": "false",
    "pin_effect": "abacus",
    "pin_left_level": "0",
    "pin_right_level": "1",
    "cards_submitted": "0",
    "favourite_sticker_id": "brain",
    "favourite_stamp_id": "newspaper",
    "pin_memory": "[{\"id\":\"tombstone\",\"name\":\"Tombstone\",\"level\":1,\"kind\":\"sticker\"}]"
  },
  "board": {
    "source": "melmod",
    "row_order": "top_first",
    "money": 42,
    "rows": 5,
    "cols": 5,
    "tiles": [
      {
        "row": 0,
        "col": 0,
        "char": "N",
        "letter": "N",
        "base_score": 1,
        "color": "shiny",
        "curse": "letter",
        "active": true
      }
    ]
  }
}
```

Top-level `money` and `board.money` are the same value (`player.Money`). The solver uses this for GOLD tile scoring instead of money OCR.

`base_score` is the tile's full in-game `packet.Score` (including fractional values and bonuses above 10). Rebuild the mod and press **F7** after updating so exports stay accurate.

NUMBER tiles (scattered red/void/blue) read colour from the tile **packet** when `GetTileType()` is still `Normal`; without this, Abacus only sees one coloured number on the path. The Python solver also treats melmod colourless numbers with `base_score == face + 2` as red until you rebuild the mod.

Sticker/stamp `id` values are derived from the game's `ArtFileName` (slugified) so they align with `data/wiki/stickers.json` when filenames match wiki keys.

`extras.pin_effect` is the pin **art** slug (e.g. `abacus`, `sam_gambit` for Super 8, `bones_the_dog` for Bicycle). Pins are not stickers/stamps.

`pin_left_level` and `pin_right_level` are cumulative counts of left- and right-side pin upgrades (after each stage you pick one side, or both with ID Card). For **Abacus**, only the right track affects word scoring (+10 TILE SCORE per coloured number on the path, scaling with `pin_right_level`); the left track is the grid scatter only. **VOID** number tiles count as coloured (void is a tile colour, not colourless). The solver does not use `pin_branch` for math (that field is display-only: which side is ahead).

Optional extras for specific pins:

| Field | Pin |
|-------|-----|
| `cards_submitted` | Bicycle (`bones_the_dog`) |
| `favourite_sticker_id`, `favourite_stamp_id` | Human Hands (`human_boy`) |
| `pin_memory` | Random Access Memory (JSON array of `{id,name,level,kind}`) |

Run context extras (default-unlocked stickers):

| Field | Sticker |
|-------|---------|
| `is_first_grid_of_encounter` | Chequered Flag (`true` / `false`) |
| `previous_word_first_letter` | Chips, Bento Box, Limnophila (single letter, e.g. `a`) |
| `tile_ninja_bonus` | Tile Ninja (additive ×WORD bonus; wiki +0.02 per consumable placed) |
| `avocado_mushy` | Avocado frozen in shop (`true` → ×-2 WORD SCORE instead of ×2) |
| `red_tiles_used_encounter` | Telescope (integer count this encounter) |
| `consumable_rack_count` | Hi Vis Jacket (tiles on consumable rack) |
| `rare_item_count` | Steak stamp (owned RARE items; set manually if not exported) |
| `target_number` | Lucky Dice (grid target number tile value, e.g. `2`) |
| `birthday_cake_bonus` | Birthday Cake (accumulated “Get +X WORD SCORE” before this submit). If the solver shows `Birthday Cake: 0 + …`, press **F7** in-game after rebuilding the companion; until then you can set `"birthday_cake_bonus": "15"` (match the sticker UI) in `run_state.json` → `extras`. |
| `michael_book_bonus` | Michael's Book (accumulated word bonus) |

Board tiles may include:

| Field | Used by |
|-------|---------|
| `consumable` | Mahjong Red Dragon pin |
| `take` | Movie Camera, Clapper Board, Zebra (chess capture on the word path) |
| `card_suit`, `card_rank` | Bones The Dog poker stickers (`hearts`, `spades`, `clubs`, `diamonds` + rank letter) |

When `take` is absent, Sam sticker rules with `strict_takes` stay inactive for captures; the Super 8 pin still treats chess tiles on the path as takes (non-strict fallback).

Playing cards export `curse: "card"` when suit metadata is found.

## Usage

1. Start a run in Cursed Words (mod auto-exports loadout and board).

2. Run the Python solver: `python -m cursed_words_solver.app`

3. Press **F7** in-game if you want to force an export before solving (also writes `game_words.txt`).

4. Press **F8** in the solver — terminal should show `Word list: game (...)` and `Board from melmod` with the correct grid.

5. Without the mod, the solver uses screenshot OCR (slower); press **F9** to edit loadout manually.

## Troubleshooting

- **Build error: MelonLoader not found** — install MelonLoader into the game folder first.

- **No export in menus** — export only runs when `GameStatics.GetPlayer()` is available (mid-run).

- **No `board` in JSON** — board export requires an active encounter/puzzle grid; press **F7** during a round with tiles visible.

- **Wrong sticker ids** — ids follow `ArtFileName`; add overrides in `data/wiki/stickers.json` if a name differs.

- **No `game_words.txt`** — vocabulary export requires an active run with initialized dictionary; press **F7** mid-run. Close the game before rebuilding the mod if deploy fails with "file in use".

See [Thunderstore Cursed Words mods](https://thunderstore.io/c/cursed-words/) for other MelonLoader examples.
