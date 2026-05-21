# MelonLoader companion (recommended)

This MelonLoader mod writes files under `%USERPROFILE%\.cursed_words_solver\` while you play:

- **Loadout** — character, stickers, stamps, boss, pin, money (`run_state.json`)

- **Board** — live 5×5 tiles (letters, scores, colors, curse types) from game `GridData` (`run_state.json`)

- **Dictionary** — full active-language vocabulary from game `WordTrie` (`game_words.txt` + `game_words_meta.json`)

- **Auto-export** when loadout or board changes (~0.5s debounce)

- **F7** in-game forces an immediate refresh (MelonLoader console log)

The Python solver reads `run_state.json` on every **F8** solve. When `board` is present, it skips screenshot OCR entirely. It prefers `game_words.txt` for word validation so suggestions match what the game accepts (ENABLE1 includes many words the game rejects).

Do not bind F8 in the mod — that is the solver hotkey.

## Prerequisites

1. [MelonLoader](https://melonwiki.xyz) installed into your Cursed Words folder (Steam default:

   `C:\Program Files (x86)\Steam\steamapps\common\Cursed Words\`)

2. Launch the game once after installing MelonLoader (creates `Mods/`)

3. [.NET SDK](https://dotnet.microsoft.com/download) for building the mod

## Build and install

From the repository root:

```powershell
.\melmod\build.ps1
```

Custom game path:

```powershell
.\melmod\build.ps1 -GameDir "D:\Games\Cursed Words"
```

This builds `CursedWordsSolverCompanion.dll` and copies it to `Cursed Words\Mods\`.

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
  "extras": {"pin_effect": ""},
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
        "curse": "letter"
      }
    ]
  }
}
```

Top-level `money` and `board.money` are the same value (`player.Money`). The solver uses this for GOLD tile scoring instead of money OCR.

Sticker/stamp `id` values are derived from the game's `ArtFileName` (slugified) so they align with `data/wiki/stickers.json` when filenames match wiki keys.

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
