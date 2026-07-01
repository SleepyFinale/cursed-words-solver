# MelonLoader companion (recommended)

**Python solver setup:** see the [repository README](../README.md#python-solver) (`pip install -r requirements.txt`, `pip install -e .`, then `python -m cursed_words_solver.app`).

This MelonLoader mod writes files under `%USERPROFILE%\.cursed_words_solver\` while you play:

- **Loadout** — character, stickers, stamps, boss, pin, money (`run_state.json`). Top-level `schema_version` (currently `1`) and `exported_at` (UTC ISO) on each export.

- **Board** — live board tiles (letters, scores, colors, curse types) from game `GridData` (`run_state.json`). Standard grids export **25** slots (5×5); **Call Of The Void** exports **36** slots (6×6) with center void cells `active: false`. Bat and other shrunk grids still use 25 slots with `rows`/`cols` and `playable_*` bounds. Per-tile: `was_glitch`, `cactus_growth`, `scattered_item_id`, `arrow` curse mapping. `extras.board_from_melmod` is `true` when a live board is exported (solver skips scatter simulation).
- **Tile scoring extras** — `historic_words[].green_tile_count` per prior word (solver derives green poison at finalize); pink piggy bank handled in solver `tile_scoring.py`
- **Boss extras** — `boss_floor_modification` (from active `BossModifier`), `fox_stolen_this_grid` / `fox_stolen_this_word` when applicable

- **Dictionary** — full active-language vocabulary from game `WordTrie` (`game_words.txt` + `game_words_meta.json`)

- **Auto-export** when loadout or board changes (~0.5s debounce)

- **F7** in-game forces an immediate refresh (MelonLoader console log). Auto-export runs when the fingerprint changes (~0.5s debounce), including consumable rack tiles (`extras.consumable_rack`). A single **F8** in the solver polls `run_state.json` until the board and required extras are ready; F7 is only needed to force export when auto-export has not caught up yet.

- **Quest context** — `challenge_game_class` (C# `ChallengeRun` subclass, e.g. `SicilianDefense`), `challenge_name` (wiki display, e.g. `Knight Time`), `challenge_elite`. Per-tile `is_crossed_out` (On Cooldown), `is_up_and_up_center` (Up and Up). `extras.favourite_sticker_ids` / `favourite_stamp_ids` for Playing Favourites. `extras.embargoed_item_types` / `embargoed_item_slugs` from `CurrentRunProgress.EmbargoedItemTypes` (Embargo quest). Quest class is included in the loadout fingerprint.

- **Boss context** — `boss_id`, `boss_name`, plus `extras.boss_area_number` (from `Player.CurrentRunProgress.GetStage()`), `extras.boss_cursed` (from `BossModifier.IsCursed`), `extras.hyena_blocked`, `extras.boss_floor_modification`, `extras.grids_remaining`, live `wolf_max_length` / `cobra_min_length` when applicable. Boss discovery uses live `EncounterController.GetBossModifiers()` (then player `ActiveBossModifiers`); boss fields and boss-specific extras are **cleared** when no boss is active. Scoring hooks clear their cache when `bossModifiers` is empty. Wolf maps from game type `MaxWordLength` → wiki id `wolf`. **Bat** boards export all 25 slots with `active: false` on unused cells plus `rows`/`cols` (height × width from `GridData.Dimensions`), `playable_origin`, and `playable_min_row`…`playable_max_col` for overlay alignment. After rebuilding the companion, press **F7** in-game before **F8** solve so shrunk grids (e.g. game **4×3**) export with the correct active columns.

- **Submit merge** — when you submit the F8 suggestion, `take` / `card_suit` / `card_rank` on the path are merged into `run_state.json` (plus `bicycle_suited_on_path` in `extras`) so the next solve does not require F7 after tracing the path.

The Python solver reads `run_state.json` on every **F8** solve (board export is required). It prefers `game_words.txt` for word validation so suggestions match what the game accepts (ENABLE1 includes many words the game rejects).

Do not bind F8 in the mod — that is the solver hotkey.

## Scoring mismatch capture (v1.1.6+)

When the solver’s predicted score does not match the game after you play the **F8 suggestion**, the mod writes a debug bundle you can turn into a regression test.

### Scoring mismatch workflow

1. In-game: open the grid or shop, then run the Python solver and press **F8** once (F7 optional if export is stale).
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

If you only see a score difference in-game but **no** `scoring_mismatches` file, the mod did not recognize the submit as the F8 suggestion — check the skip message (alternate path vs board changed), then submit on the **highlighted path** before the board changes.

If the board changed since F8 (you played a different word or the grid advanced), melmod logs a **Warning** at submit (`Solver suggestion is stale…`) and round logs set `comparison.stale_suggestion: true` when `board_fingerprint` on `last_suggestion.json` does not match the current board. **Exception:** when F8 wrote `consumable_placements` (Sandy Saguaro rack tiles), placing those consumables on the suggested cells — including one at a time before submit — is treated as valid board drift; scoring capture and round logs should not mark the suggestion stale for that change alone. The Python overlay uses the same rule (`tests/test_suggestion_placement.py`). After submit, the solver clears the overlay; press **F8** on the next grid when ready.

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
3. Mod writes `%USERPROFILE%\.cursed_words_solver\round_logs\<timestamp>.json` with `match_status`: `score_match`, `score_mismatch`, `path_mismatch`, or `no_suggestion`. **`no_suggestion`** means you submitted without a valid F8 `last_suggestion.json` (manual play or cleared suggestion) — it is informational, not a mod error. Press **F8** in the solver before submit for score capture. **`path_mismatch`** with the same board fingerprint and a higher score than F8 often means the solver missed a better route — use the round log (`comparison.submitted_beat_suggestion`) and replay tests under `tests/regression/test_path_mismatch_round_log.py`.
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

## Export diagnostics (v1.2.0+)

**v1.2.3** — skip workflow-stale suggestion clearing on submit exports; clear `last_suggestion.json` before post-submit `run_state` export; recognize grid-1 word-1 historic drift (`0→1`) as expected after submit; omit misleading `stale_f8_reason` on path-mismatch round logs.

**v1.2.2** — submit path capture uses Unity bottom-origin `GetCoordinates().y` for melmod index (`y * cols + col`), matching `last_suggestion.json` and fixing false `path_mismatch` on 5×5 boards when tracing the F8 overlay.

**v1.2.1** — submit path capture uses `board.cols` for coordinate→index conversion (fixes false `path_mismatch` on 6×6 Call of the Void grids).

Every `run_state.json` write includes top-level **`export_diagnostics`**:

| Field | Meaning |
| ----- | ------- |
| `companion_version` | Melmod build |
| `export_trigger` | `auto`, `f7`, or `submit_merge` |
| `fingerprint` / `fingerprint_changed` | Loadout+board fingerprint |
| `missing_keys` | Completeness warnings (Snapshot copy, RAM, counters, …) |
| `merge_errors` | Post-submit merge failures (no longer silent) |
| `snapshot_copy_source` | `reflection`, `grid_start_hook`, `trace_fallback`, or `preserved` |
| `pin_memory_count` | Items exported from RAM pin |

**Verbose logging** (MelonPreference, default **on**) prints auto-export lines and capture decisions. When enabled, also appends to `%USERPROFILE%\.cursed_words_solver\export_audit.jsonl`.

**Snapshot copy:** Game field `Snapshot.SnapshottedItem` (set in `ApplyStartOfGridEffect`). Exported as `extras.snapshot_copy_slug` / `snapshot_copy_level`. If unreadable: `snapshot_copy_export_note` = `no_copy_yet` | `reflection_failed` | `not_equipped`.

**Grid scattered items:** `extras.grid_scattered_items` JSON array `[{row,col,id,level},…]` plus per-tile `scattered_item_level` (defaults to 1).

Python F8 mirrors diagnostics in `last_suggestion.json` (`export_diagnostics`, `export_warnings`, `solver_session_extras`) and `debug/parse_*.json`.

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
  },
  "ui_layout": {
    "coordinate_space": "screen_top_left",
    "screen_w": 2560,
    "screen_h": 1440,
    "board": { "x": 1026, "y": 132, "width": 703, "height": 700, "rows": 5, "cols": 5 },
    "consumable_rack": { "x": 2392, "y": 571, "width": 293, "height": 45, "slot_count": 5 }
  }
}
```

`ui_layout` is exported on every board export (F7 / auto-export) from live Unity UI bounds (`GridLayoutController` tile renderers and consumable rack slot transforms). The Python solver uses it for green path and orange rack overlays — no manual F10 calibration when present. Coordinates are Qt virtual-desktop pixels (top-left origin).

Top-level `money` and `board.money` are the same value (`player.Money`). The solver uses this for GOLD tile scoring.

`base_score` is the tile's full in-game `packet.Score` (including fractional values and bonuses above 10). Rebuild the mod and press **F7** after updating so exports stay accurate.

NUMBER tiles (scattered red/void/blue) read colour from the tile **packet** when `GetTileType()` is still `Normal`; without this, Abacus only sees one coloured number on the path. The Python solver also treats melmod colourless numbers with `base_score == face + 2` as red until you rebuild the mod.

Sticker/stamp `id` values are derived from the game's `ArtFileName` (slugified) so they align with `data/wiki/stickers.json` when filenames match wiki keys.

`extras.pin_effect` is the pin **art** slug (e.g. `abacus`, `sam_gambit` for Super 8, `bones_the_dog` for Bicycle). Pins are not stickers/stamps.

`pin_left_level` and `pin_right_level` are the raw `UpgradeableComponents[i].Level` values: cumulative counts of left- and right-side pin **upgrade picks** (after each stage you pick one side, or both with ID Card). They must **not** be `max(Level, VariableValue)` — that conflates picks with runtime magnitudes. **`pin_left_variable`** and **`pin_right_variable`** mirror in-game `UpgradeableComponents[i].VariableValue` (runtime scatter counts, +TILE bonuses, etc.; the solver prefers these for scoring math where applicable). Example **Wad of Cash** with 2 left / 0 right picks: `pin_left_level` = `2`, `pin_right_level` = `0`, `pin_left_variable` = `3` (scatters 3 currencies), `pin_right_variable` = `10` (+10 TILE SCORE) — display shows `L2/R0`, not `L3/R10`. For **Abacus**, only the right track affects word scoring (+N TILE SCORE per coloured number on the path, N = `pin_right_variable`); the left track is the grid scatter only. **VOID** number tiles count as coloured (void is a tile colour, not colourless). The solver does not use `pin_branch` for math (that field is display-only: which side has more upgrade picks).

Optional extras for specific pins:

| Field | Pin |
| ---- | ---- |
| `bicycle_word_score_bonus` | Bicycle (`bones_the_dog`) — running `WordScoreBonus` on the pin before this word (game adds suited cards on path × right-track rate, then applies the total). Merged into `run_state.json` after each `CalculateOverallScore` (and on submit) so F8 stays in sync. |
| `cards_submitted` | Legacy alias of `bicycle_word_score_bonus` for older solver builds |
| `bicycle_suited_on_path` | Set during submit scoring capture — Bicycle suited credit on the path (unique suits when at most one suit on the path, else unique suited card ranks). Merged into `run_state.json` on matched submit; path tiles also get `card_suit` / `card_rank` on the board snapshot. After each scored word, press **F7** if the solver Bicycle total looks one step behind the in-game pin. |
| `favourite_sticker_id`, `favourite_stamp_id` | Human Hands (`human_boy`) |
| `pin_memory` | Random Access Memory (JSON array of `{id,name,level,kind}`, acquisition order) |
| `pin_memory_count` | Number of items exported from `ItemsInMemory` |
| `pin_memory_export_note` | `ok`, `empty_valid`, `field_missing`, `reflection_failed`, or `no_pin` |

### Random Access Memory troubleshooting

- Pin memory starts **empty** at run start; `pin_memory: []` with `pin_memory_export_note: empty_valid` is normal before the first boss pick.
- After boss picks, press **F7** so `ItemsInMemory` is read from the game (`public List<Item> ItemsInMemory` field).
- If the MelonLoader console shows **`RAM pin: could not read ItemsInMemory`**, rebuild/install the latest companion mod — older builds only checked properties, not the field.
- **`Export completeness: pin_memory (ItemsInMemory unreadable)`** means the RAM pin is active but export failed; fix melmod and F7 again.
- **`pin_memory unexpected item:<slug>`** should never happen in-game (wiki-blacklisted draft pool). Report if you see it.
- The solver applies RAM items **after scattered grid items on the path**, **before** equipped stickers/stamps. Movement stamps (e.g. Hungry Snake) affect **search** via `pin_memory`; they do not add word-score replay.

Run context extras (default-unlocked stickers):

| Field | Sticker |
| ---- | ---- |
| `is_first_grid_of_encounter` | Chequered Flag (`true` / `false`) |
| `previous_word_first_letter` | Chips, Bento Box, Limnophila (single letter, e.g. `a`) |
| `stitched_sticker_ids` | Frankenstein (JSON array of stitched sticker art slugs) |
| `overhand_level` | Overhand (`UpgradeableComponents[0].VariableValue` — extra stamp applications per slot) |
| `hourglass_count` | Hourglass (odd count reverses pin/sticker/stamp scoring order) |
| `mutating_dna_letter_counts` | Mutating DNA pre-submit use counts (JSON map: lowercase letters **or number strings** like `"1"`, `"22"` from `Tile.GetStringRepresentation`) |
| `tile_ninja_bonus` | Tile Ninja (additive ×WORD bonus; wiki +0.02 per consumable placed) |
| `avocado_mushy` | Avocado frozen in shop (`true` → ×-2 WORD SCORE instead of ×2) |
| `red_tiles_used_encounter` | Telescope fallback when `historic_words` lacks per-word red counts; also merged from the sum of prior-word RED tiles after each `CalculateOverallScore`, and derived on **F7** when the game property is missing |
| `movie_camera_word_score_bonus` | Movie Camera encounter running `WordScoreBonus` (exported on **F7** and merged after each score). If the solver shows `Movie Camera: 0 + …`, press **F7** in-game; until then set `"movie_camera_word_score_bonus": "20"` in `run_state.json` → `extras` to match the sticker UI. |
| `historic_words` | Prior words: `word`, `path`, `score`, `red_tile_count`, `chess_take_value` |
| `consumable_rack_count` | Hi Vis Jacket (tiles on consumable rack) |
| `consumable_rack` | JSON array of rack tile snapshots (letters, colors, `cactus_growth`) for solver placement simulation |
| `grid_number` | Current grid index in the encounter (1-based; also updated from `CalculateOverallScore`) |
| `twinkle_toes_swap_available` | `true` when Twinkle Toes stamp is equipped and the player has not yet swapped tiles this grid (`EncounterController.TwinkleToesSwapAvailable`). Press **F7** before **F8** on a fresh grid so the solver can recommend which pair to swap. |
| `run_seed` | Run RNG seed when readable from player/progress |
| `rare_item_count` | Owned RARE stickers/stamps/pin |
| `steak_word_bonus_percent` | Steak multiplicative ×WORD percent (e.g. `250` = ×2.5). Auto-exported from live stamp reflection or `100 + 25 × rare_item_count`; submit/F8 trace overwrites when the game formula differs. Press **F7** after equipping Steak if the solver warns it is missing. |
| `rare_item_count_last_known` | Last submit-captured rare count (Steak); used when live reflection is unavailable |
| `fairy_count` | Fairy-related stamp count |
| `animal_stamp_count` | Animal-themed stamps equipped |
| `money_lost_encounter` | Money lost this encounter |
| `kokeshi_dolls` | `true` when Kokeshi Dolls stamp equipped (currency path uses letter values) |
| `frozen_in_shop` | `true` when Avocado is mushy / shop freeze active (`avocado_mushy` still exported) |
| `character_slug` | Wiki-style slug for the active character |
| `encounter_mode` | `encounter`, `shop`, or `none` |
| `run_stage` | Current run stage (1–6) from `CurrentRunProgress.GetStage()`; always exported during a run |
| `run_node_type` | Current node in the stage: `EncounterFirst`, `Boss`, `ShopZero`, `ShopOne`, `ShopTwo`, `MegShop`, or `None` |
| `encounter_score_earned` | Points scored this encounter so far (`encounter_total_target − encounter_remaining_target`) |
| `shop_node` | When in shop: `ShopZero`, `ShopOne`, `ShopTwo`, or `MegShop` (from `CurrentRunProgress.CurrentNodeType`) |

### Shop advisor export (v1.2+)

When you are in the Ej?A56 shop, the companion exports live shop state for the Python shop advisor (press **F7** in the shop, then **F8** in the solver).

Top-level `run_state.json` fields:

| Field | Purpose |
| ----- | ------- |
| `shop.restock_cost` | Next restock price ($) |
| `shop.free_item_available` | Pre-Yellow crown free purchase still available |
| `shop.angel_investment_available` | Angel Investment first-free eligible |
| `shop.hungry_hippo_equipped` | Hungry Hippo can eat shop stickers |
| `shop.offers[]` | Live offers: `slot` (`sticker`/`stamp`/`tile`), `index`, `id`, `name`, `level`, `foil`, `price`, `frozen`, `free`, `sold`, tile `color`/`curse`/`letter` |
| `inventory_sell[]` | Owned stickers/stamps with `sell_value`, `sell_cost`, `costs_money_to_sell` |
| `encounter_grid_reroll` | Encounter **grid** reroll (not shop restock): `remaining`, `cost_per_use` (0 default, $1 with Wheel), `can_reroll`, `wheel_equipped`, `fan_equipped` |
| `extras.encounter_remaining_target` | Score still needed this encounter (from `_remainingTarget`) |
| `extras.encounter_total_target` | Encounter total target score (from `_totalTarget`) |
| `extras.encounter_score_earned` | Points scored this encounter (`total_target − remaining_target`) |

Capture a shop fixture for regression tests: press **F7** in the shop and copy `%USERPROFILE%\.cursed_words_solver\run_state.json` to `tests/fixtures/shops/`.
| `grids_total` | Total grids in encounter (Badger) when readable |
| `sticker_order` / `stamp_order` | JSON slug arrays (live slot order) |
| `historic_words` | Compact JSON of prior submitted words (word, path, score) |
| `game_version` | `Application.version` for mismatch triage |
| `target_number` | Lucky Dice (grid target number tile value, e.g. `2`). Read from player/grid state and the Lucky Dice sticker when property names differ by build. |
| `lucky_dice_target_missing` | `true` when Lucky Dice is equipped but `target_number` could not be read (rebuild melmod and press **F7**) |
| `birthday_cake_bonus` | Birthday Cake (accumulated “Get +X WORD SCORE” before this submit). Read from the equipped sticker or, when Birthday Cake lives in **RAM pin memory only**, from the memory item on **F7**. If the solver shows `Birthday Cake: 0 + …`, press **F7** in-game after rebuilding the companion; until then you can set `"birthday_cake_bonus": "15"` (match the sticker UI) in `run_state.json` → `extras`. |
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

2. Run the Python solver: `python -m cursed_words_solver.app` (see [root README](../README.md#python-solver)).

3. Press **F7** in-game if you want to force an export before solving (also writes `game_words.txt`).

4. Press **F8** in the solver — terminal should show `Word list: game (...)` and `Board from melmod` with the correct grid.

5. Press **F8** in the solver. Overlays align automatically from `ui_layout` when melmod is current.

6. **F10** in the solver is manual overlay calibration — only needed if `ui_layout` is missing from `run_state.json`.

7. **ESC** hides the solver overlay and board highlights.

## Troubleshooting

- **Build error: MelonLoader not found** — install MelonLoader into the game folder first.

- **No export in menus** — export only runs when `GameStatics.GetPlayer()` is available (mid-run).

- **No `board` in JSON** — board export requires an active encounter/puzzle grid; press **F7** during a round with tiles visible.

- **Wrong sticker ids** — ids follow `ArtFileName`; add overrides in `data/wiki/stickers.json` if a name differs.

- **No `game_words.txt`** — vocabulary export requires an active run with initialized dictionary; press **F7** mid-run. Close the game before rebuilding the mod if deploy fails with "file in use".

See [Thunderstore Cursed Words mods](https://thunderstore.io/c/cursed-words/) for other MelonLoader examples.
