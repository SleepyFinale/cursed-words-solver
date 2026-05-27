# MelonLoader companion (recommended)

**Python solver setup:** see the [repository README](../README.md#setup) (`pip install -r requirements.txt`, `pip install -e .`, then `python -m cursed_words_solver.app`).

This MelonLoader mod writes files under `%USERPROFILE%\.cursed_words_solver\` while you play:

- **Loadout** — character, stickers, stamps, boss, pin, money (`run_state.json`). Top-level `schema_version` (currently `1`) and `exported_at` (UTC ISO) on each export.

- **Board** — live 5×5 tiles (letters, scores, colors, curse types) from game `GridData` (`run_state.json`). Per-tile: `was_glitch`, `cactus_growth`, `scattered_item_id`, `arrow` curse mapping. `extras.board_from_melmod` is `true` when a live board is exported (solver skips scatter simulation).
- **Tile scoring extras** — `extras.green_poison_bonus` (10% × green tiles per prior word), pink piggy bank handled in solver `tile_scoring.py`
- **Boss extras** — `boss_floor_modification` (from active `BossModifier`), `fox_stolen_this_grid` / `fox_stolen_this_word` when applicable

- **Dictionary** — full active-language vocabulary from game `WordTrie` (`game_words.txt` + `game_words_meta.json`)

- **Auto-export** when loadout or board changes (~0.5s debounce)

- **F7** in-game forces an immediate refresh (MelonLoader console log)

- **Boss context** — `boss_id`, `boss_name`, plus `extras.boss_area_number` (from `Player.CurrentRunProgress.GetStage()`), `extras.boss_cursed` (from `BossModifier.IsCursed`), `extras.hyena_blocked`, `extras.boss_floor_modification`, `extras.grids_remaining`, live `wolf_max_length` / `cobra_min_length` when applicable. Boss discovery uses live `EncounterController.GetBossModifiers()` (then player `ActiveBossModifiers`); boss fields and boss-specific extras are **cleared** when no boss is active. Scoring hooks clear their cache when `bossModifiers` is empty. Wolf maps from game type `MaxWordLength` → wiki id `wolf`. **Bat** boards export all 25 slots with `active: false` on unused cells plus `rows`/`cols` (height × width from `GridData.Dimensions`), `playable_origin`, and `playable_min_row`…`playable_max_col` for overlay alignment. After rebuilding the companion, press **F7** in-game before **F8** solve so shrunk grids (e.g. game **4×3**) export with the correct active columns.

- **Submit merge** — when you submit the F8 suggestion, `take` / `card_suit` / `card_rank` on the path are merged into `run_state.json` (plus `bicycle_suited_on_path` in `extras`) so the next solve does not require F7 after tracing the path.

The Python solver reads `run_state.json` on every **F8** solve (board export is required). It prefers `game_words.txt` for word validation so suggestions match what the game accepts (ENABLE1 includes many words the game rejects).

Do not bind F8 in the mod — that is the solver hotkey.

## Scoring mismatch capture (v1.1.6+)

When the solver’s predicted score does not match the game after you play the **F8 suggestion**, the mod writes a debug bundle you can turn into a regression test.

### Scoring mismatch workflow

1. In-game: **F7** (refresh board/loadout), then run the Python solver and press **F8**.
2. Solver writes `%USERPROFILE%\.cursed_words_solver\last_suggestion.json` (`scoring_word` / `word`, `path`, fingerprints, `predicted_trace`; optional `dictionary_word` when the game will spell it differently).
3. Trace the **exact highlighted path** on the **same board** (before the grid changes) and submit. The game shows the **dictionary** spelling (e.g. `settee`); the solver stores the **scoring** form (e.g. `12ttee` with number/shiny tiles). Capture matches on **path + board fingerprint**, not the word string.
4. On submit, Harmony hooks read the game’s `ScoreCalculation.CalculateOverallScore` steps.
5. If totals differ → `scoring_mismatches\<timestamp>.json` with `predicted_trace`, `actual_trace`, and `run_state_snapshot`. Submit-time `extras_snapshot` (including `previous_word_first_letter` from `HistoricWord` during scoring) is merged into `run_state_snapshot.extras` so regression replay matches in-game context.

If you play the same dictionary word on a **different valid path** (e.g. another ending tile), capture is skipped — predicted score is only valid for the F8 path.

MelonLoader console logs `Scoring MISMATCH` with the file path, or `Scoring match` when totals agree.

### Where files live

| File | Path |
| ---- | ---- |
| F8 prediction (written by Python) | `%USERPROFILE%\.cursed_words_solver\last_suggestion.json` |
| Mismatch bundles (written by mod) | `%USERPROFILE%\.cursed_words_solver\scoring_mismatches\*.json` |
| Solver debug per F8 | `%USERPROFILE%\.cursed_words_solver\debug\parse_*.json` |

On startup the mod prints the mismatch folder path. After each word submit you should see either `Scoring capture: tracking suggested word …` or `Scoring capture skipped: …` (explains why it did not match, e.g. different path or board changed).

If you only see a score difference in-game but **no** `scoring_mismatches` file, the mod did not recognize the submit as the F8 suggestion — check the skip message (alternate path vs board changed), press **F8** again, then submit on the **highlighted path** before the board changes.

If the board changed since F8, melmod logs a **Warning** at submit (`Solver suggestion is stale…`) and round logs set `comparison.stale_suggestion: true` when `board_fingerprint` on `last_suggestion.json` does not match the current board. The Python solver prints a startup note when an old `last_suggestion.json` does not match the current board (and clears the file when the loadout changed); press **F8** to refresh before submitting.

### Turn a mismatch into a regression fixture

```powershell
python scripts/mismatch_to_test.py $env:USERPROFILE\.cursed_words_solver\scoring_mismatches\20260523_143022.json
pytest tests/regression/ -k 20260523_143022
```

Writes `tests/fixtures/mismatches/<timestamp>.json`; parametrized tests live in `tests/regression/test_scoring_mismatches.py`.

See [`SCORING_HOOKS.md`](SCORING_HOOKS.md) for hooked game types (`EncounterController.SubmitWord`, `ScoreCalculation.CalculateOverallScore`, etc.).

## Round logs (v1.2+)

After **every** word submit (encounter or puzzle), the mod writes a structured round record — not only on score mismatches.

### Round log workflow

1. **F7** refresh, then **F8** solve (Python writes `last_suggestion.json` with `f8_sequence`, path, predicted score/trace).
2. Submit any word (F8 path, alternate path, or manual).
3. Mod writes `%USERPROFILE%\.cursed_words_solver\round_logs\<timestamp>.json` with `match_status`: `score_match`, `score_mismatch`, `path_mismatch`, or `no_suggestion`.
4. Append-only index: `round_logs/index.jsonl` (round id, file path, scores, words).

Each log includes: full `run_state` at submit, solver block (when `last_suggestion.json` exists), actual word/path/score/trace, consumable rack before/after, and `consumables.placements_this_round` (board-diff detections between submits).

**Mismatch bundles unchanged** — `scoring_mismatches/` still only when F8 path + board fingerprint match and scores differ.

| File | Path |
| ---- | ---- |
| F8 prediction | `%USERPROFILE%\.cursed_words_solver\last_suggestion.json` |
| Per-round logs | `%USERPROFILE%\.cursed_words_solver\round_logs\*.json` |
| Round log index | `%USERPROFILE%\.cursed_words_solver\round_logs\index.jsonl` |
| Mismatch bundles | `%USERPROFILE%\.cursed_words_solver\scoring_mismatches\*.json` |

MelonPreference **Round log enabled** (default on). Startup logs the round log directory.

### Turn a round log into a fixture

```powershell
python scripts/round_log_to_test.py $env:USERPROFILE\.cursed_words_solver\round_logs\20260525_120000_000.json
pytest tests/integration/test_round_log_schema.py -q
```

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

Top-level `money` and `board.money` are the same value (`player.Money`). The solver uses this for GOLD tile scoring.

`base_score` is the tile's full in-game `packet.Score` (including fractional values and bonuses above 10). Rebuild the mod and press **F7** after updating so exports stay accurate.

NUMBER tiles (scattered red/void/blue) read colour from the tile **packet** when `GetTileType()` is still `Normal`; without this, Abacus only sees one coloured number on the path. The Python solver also treats melmod colourless numbers with `base_score == face + 2` as red until you rebuild the mod.

Sticker/stamp `id` values are derived from the game's `ArtFileName` (slugified) so they align with `data/wiki/stickers.json` when filenames match wiki keys.

`extras.pin_effect` is the pin **art** slug (e.g. `abacus`, `sam_gambit` for Super 8, `bones_the_dog` for Bicycle). Pins are not stickers/stamps.

`pin_left_level` and `pin_right_level` are cumulative counts of left- and right-side pin upgrades (after each stage you pick one side, or both with ID Card). **`pin_left_variable`** and **`pin_right_variable`** mirror in-game `UpgradeableComponents[i].VariableValue` (used for bonuses; preferred over level when present). For **Abacus**, only the right track affects word scoring (+N TILE SCORE per coloured number on the path, N = `pin_right_variable`); the left track is the grid scatter only. **VOID** number tiles count as coloured (void is a tile colour, not colourless). The solver does not use `pin_branch` for math (that field is display-only: which side is ahead).

Optional extras for specific pins:

| Field | Pin |
| ---- | ---- |
| `bicycle_word_score_bonus` | Bicycle (`bones_the_dog`) — running `WordScoreBonus` on the pin before this word (game adds suited cards on path × right-track rate, then applies the total). Merged into `run_state.json` after each `CalculateOverallScore` (and on submit) so F8 stays in sync. |
| `cards_submitted` | Legacy alias of `bicycle_word_score_bonus` for older solver builds |
| `bicycle_suited_on_path` | Set during submit scoring capture — Bicycle suited credit on the path (unique suits when at most one suit on the path, else unique suited card ranks). Merged into `run_state.json` on matched submit; path tiles also get `card_suit` / `card_rank` on the board snapshot. After each scored word, press **F7** if the solver Bicycle total looks one step behind the in-game pin. |
| `favourite_sticker_id`, `favourite_stamp_id` | Human Hands (`human_boy`) |
| `pin_memory` | Random Access Memory (JSON array of `{id,name,level,kind}`) |

Run context extras (default-unlocked stickers):

| Field | Sticker |
| ---- | ---- |
| `is_first_grid_of_encounter` | Chequered Flag (`true` / `false`) |
| `previous_word_first_letter` | Chips, Bento Box, Limnophila (single letter, e.g. `a`) |
| `stitched_sticker_ids` | Frankenstein (JSON array of stitched sticker art slugs) |
| `overhand_level` | Overhand (`UpgradeableComponents[0].VariableValue` — extra stamp applications per slot) |
| `hourglass_count` | Hourglass (odd count reverses pin/sticker/stamp scoring order) |
| `mutating_dna_letter_counts` | Mutating DNA (JSON map letter → use count) |
| `tile_ninja_bonus` | Tile Ninja (additive ×WORD bonus; wiki +0.02 per consumable placed) |
| `avocado_mushy` | Avocado frozen in shop (`true` → ×-2 WORD SCORE instead of ×2) |
| `red_tiles_used_encounter` | Telescope (integer count this encounter) |
| `consumable_rack_count` | Hi Vis Jacket (tiles on consumable rack) |
| `grid_number` | Current grid index in the encounter (1-based; also updated from `CalculateOverallScore`) |
| `run_seed` | Run RNG seed when readable from player/progress |
| `rare_item_count` | Owned RARE stickers/stamps/pin |
| `fairy_count` | Fairy-related stamp count |
| `animal_stamp_count` | Animal-themed stamps equipped |
| `money_lost_encounter` | Money lost this encounter |
| `kokeshi_dolls` | `true` when Kokeshi Dolls stamp equipped (currency path uses letter values) |
| `frozen_in_shop` | `true` when Avocado is mushy / shop freeze active (`avocado_mushy` still exported) |
| `character_slug` | Wiki-style slug for the active character |
| `encounter_mode` | `encounter`, `shop`, or `none` |
| `grids_total` | Total grids in encounter (Badger) when readable |
| `sticker_order` / `stamp_order` | JSON slug arrays (live slot order) |
| `historic_words` | Compact JSON of prior submitted words (word, path, score) |
| `game_version` | `Application.version` for mismatch triage |
| `target_number` | Lucky Dice (grid target number tile value, e.g. `2`) |
| `birthday_cake_bonus` | Birthday Cake (accumulated “Get +X WORD SCORE” before this submit). If the solver shows `Birthday Cake: 0 + …`, press **F7** in-game after rebuilding the companion; until then you can set `"birthday_cake_bonus": "15"` (match the sticker UI) in `run_state.json` → `extras`. |
| `michael_book_bonus` | Michael's Book (accumulated word bonus) |

Board tiles may include:

| Field | Used by |
| ---- | ---- |
| `consumable` | Mahjong Red Dragon pin |
| `take` | Movie Camera, Clapper Board, Zebra (chess capture on the word path) |
| `chess_color` | Chess movement blocking and Dove balanced-colors scoring (`black` = filled piece, `white` = outlined). Exported from game field `Tile.IsWhitePiece` (`false` = black/filled, `true` = white/outlined). |
| `card_suit`, `card_rank` | Bones The Dog poker stickers (`hearts`, `spades`, `clubs`, `diamonds` + rank letter). Suited tiles keep their primary curse (`letter`, `number`, `chess_*`, etc.) and add suit metadata. |
| `is_joker` | Joker tiles (`true`): wildcard letter `?` for search; count as any card for poker hands and **Poker Face** (starts with face card). They do **not** add Bicycle suited credit. **Wrestlers**: suited start + joker at path end qualifies; joker at start uses first/last **suited tiles on the path** (e.g. clubs then hearts); joker start + only one suited tile on a short word does not. |

When `take` is absent, sticker rules with `strict_takes` stay inactive for captures; the Super 8 pin infers takes from valid chess capture moves along the word path (opponent landing squares and en passant).

Pure card glyphs export `curse: "card"`. Suited overlays only set `card_suit` / `card_rank` without replacing the primary curse.

## Usage

1. Start a run in Cursed Words (mod auto-exports loadout and board).

2. Run the Python solver: `python -m cursed_words_solver.app` (see [root README](../README.md#setup)).

3. Press **F7** in-game if you want to force an export before solving (also writes `game_words.txt`).

4. Press **F8** in the solver — terminal should show `Word list: game (...)` and `Board from melmod` with the correct grid.

5. **F10** in the solver recalibrates the on-screen board region (for numbered green path highlights).

6. **ESC** hides the solver overlay and board highlights.

## Troubleshooting

- **Build error: MelonLoader not found** — install MelonLoader into the game folder first.

- **No export in menus** — export only runs when `GameStatics.GetPlayer()` is available (mid-run).

- **No `board` in JSON** — board export requires an active encounter/puzzle grid; press **F7** during a round with tiles visible.

- **Wrong sticker ids** — ids follow `ArtFileName`; add overrides in `data/wiki/stickers.json` if a name differs.

- **No `game_words.txt`** — vocabulary export requires an active run with initialized dictionary; press **F7** mid-run. Close the game before rebuilding the mod if deploy fails with "file in use".

See [Thunderstore Cursed Words mods](https://thunderstore.io/c/cursed-words/) for other MelonLoader examples.
