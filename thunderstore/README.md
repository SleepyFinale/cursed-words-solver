# Cursed Words Solver (beta)

Beta assistant for **Cursed Words: The Word Game That Isn't**. Launch the game and press **F8** during a run. The solver starts with the game, shows the highest-scoring word, and draws the click path on the board. You do not open a terminal.

This is a beta. Scoring and pathfinding still miss cases. When something looks wrong, send a bug report so it can be fixed before any AI training work.

Windows only. The game is 64-bit.

## Install with a mod manager

This is the easiest install. [Thunderstore Mod Manager](https://www.overwolf.com/app/thunderstore-thunderstore_mod_manager), [r2modman](https://thunderstore.io/package/ebkr/r2modman/), or [Gale](https://thunderstore.io/package/Kesomannen/GaleModManager/) all work.

1. Install one of those managers.
2. Select the **Cursed Words** community.
3. Install **Cursed Words Solver**. **MelonLoader 0.7.3** is a dependency and should install with it. If it does not, install [LavaGang-MelonLoader](https://thunderstore.io/c/cursed-words/p/LavaGang/MelonLoader/) yourself, version **0.7.3**.
4. Launch **Cursed Words from the mod manager**. Starting the game only from Steam skips the manager's mod profile, so this package will not load.
5. Start a run. Press **F8**. The result panel and the numbered path should show up. Press **F7** only when the board looks stale (for example right after a consumable that has not exported yet).

The first launch can sit for a few seconds while the solver starts. A MelonLoader console window is normal. That console is the game log, not a step you have to run.

## Install manually

Use this when you are not using a mod manager. Close the game before copying files.

Steam's usual folder is `C:\Program Files (x86)\Steam\steamapps\common\Cursed Words\`. If yours is elsewhere, use that folder everywhere below.

### 1. Visual C++ runtime

Install the [Visual C++ 2015–2022 x64 redistributable](https://aka.ms/vs/17/release/vc_redist.x64.exe). You do not need the .NET 6 runtime. Cursed Words is a 64-bit Mono game.

### 2. MelonLoader 0.7.x

Install **64-bit MelonLoader 0.7.0 or newer**. **0.7.3** matches the mod-manager package.

- Installer: [MelonLoader releases](https://github.com/LavaGang/MelonLoader/releases). Pick Cursed Words from Steam.
- Or download `MelonLoader.x64.zip` from that page and copy these into the game folder:
  - the `MelonLoader` folder
  - `version.dll`
  - `dobby.dll`

Launch the game **once** from Steam so MelonLoader can create `Mods\` and `UserData\`. Quit before the next step.

### 3. This package

Unzip the Thunderstore package. The zip root contains `manifest.json`, `README.md`, `icon.png`, `CursedWordsSolverCompanion.dll`, and a `UserData\solver\` folder. Copy files, not the zip itself, and do not leave them nested in an extra folder.

1. Copy `CursedWordsSolverCompanion.dll` to `<game>\Mods\`.
2. Copy the **contents** of the zip's `UserData\solver\` folder into `<game>\UserData\CursedWordsSolver\`.

The solver executable must be directly here:

`<game>\UserData\CursedWordsSolver\CursedWordsSolver.exe`

`_internal\` and `data\` from that same `solver` folder sit next to the exe. If the exe is inside an extra `solver` folder (`UserData\CursedWordsSolver\solver\CursedWordsSolver.exe`), the mod will not find it.

### 4. Play

Launch Cursed Words from Steam. Start a run and press **F8**.

MelonLoader's log should include a line like `Cursed Words Solver Companion v1.3.0 (package 0.1.0)` and `Started bundled solver:`. If it says `No bundled solver found`, the exe is not in `UserData\CursedWordsSolver\`.

## How to play

| Key | Action |
| --- | --- |
| F8 | Solve the current board |
| F7 | Force a fresh export of the board, loadout, and dictionary |
| F9 | Edit the loadout by hand |
| F10 | Manual overlay alignment, only if automatic layout is missing |
| ESC | Hide the overlay and highlights |
| Ctrl+Shift+Q | Quit the solver. Quitting the game also stops it |

Green numbers on the board are the click order. Orange numbers on the consumable rack are the slot to drag for that step. Play the **highlighted path** if you want the predicted score. A different route on the same letters can score something else.

The overlay clears after you submit. Press **F8** again on the next grid.

## Report a bug

Open a [GitHub issue](https://github.com/SleepyFinale/cursed-words-solver/issues). One issue per problem. Include:

1. What you expected and what happened (wrong word, wrong score, no overlay, crash, and so on).
2. The character, and the stickers, stamps, pin, or boss if you know them.
3. The MelonLoader lines for `[Cursed Words Solver Companion]` from just before the problem through the round-log line. The MelonLoader console shows them. The same text is in `MelonLoader\Logs\Latest.log` in the game folder (or in the mod-manager profile, if that is where the log is written).
4. The round log file that line names. It lives under `%USERPROFILE%\.cursed_words_solver\round_logs\`. Attach that `.json`.
5. If the score was wrong **on the highlighted path**, also attach the newest file in `%USERPROFILE%\.cursed_words_solver\scoring_mismatches\`.
6. `%USERPROFILE%\.cursed_words_solver\solver.log`.

A useful report looks like this. Yours will have different words, scores, and paths:

```text
[23:25:59.943] [Cursed Words Solver Companion] Scoring capture skipped f8#2421: alternate path on same board (score compare needs the exact highlighted path; round log saved for solver replay); submitted [14,13,8,9] vs suggestion [14,13,17,12]; submitted tiles: j@(2,4) → a@(2,3) → d@(3,3) → e@(3,4); suggestion tiles: j@(2,4) → a@(2,3) → t@(1,2) → o@(2,2); word: submitted 'jade' vs suggestion 'jato'
[23:26:00.029] [Cursed Words Solver Companion] Alternate path beat F8 by +1 pts (54 vs 53); round log saved for solver replay.
[23:26:00.029] [Cursed Words Solver Companion] Round log: C:\Users\TheMi\.cursed_words_solver\round_logs\20260816_232600_025.json (path_mismatch)
```

Attach `20260816_232600_025.json` (your filename will differ) with that paste. `path_mismatch` means a submit did not follow the F8 path. That file is what we replay. You do not need to explain the log format.

`no_suggestion` on a round log means F8 had not produced a suggestion yet. Press F8 before you submit if you want a score comparison.

## Files the mod writes

Everything is under `%USERPROFILE%\.cursed_words_solver\`:

| Path | What it is |
| --- | --- |
| `solver.log` | Solver output (there is no solver terminal window) |
| `run_state.json` | Live board and loadout |
| `game_words.txt` | Dictionary exported from the game |
| `last_suggestion.json` | Last F8 result |
| `round_logs\` | One JSON file per word you submit |
| `scoring_mismatches\` | Saved when the highlighted path scores differently than predicted |

## Source

Development setup, tests, and the unbundled companion live in the [GitHub repo](https://github.com/SleepyFinale/cursed-words-solver). The player install is this package. You do not need Python, a venv, or `cursed-solver` to play.
