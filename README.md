# Cursed Words Screenshot Solver

Desktop assistant for **Cursed Words: The Word Game That Isn't**. Press a hotkey to read the 5×5 board and find the highest-scoring valid word.

## Setup

From the **repository root** (the folder that contains `pyproject.toml` and `requirements.txt`):

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install -e .
```

Do not `cd` into the inner `cursed_words_solver/` package folder for setup — that directory is only the Python source, not the installable project.

**Recommended:** install the [MelonLoader companion mod](melmod/README.md) so the board and money come from the game (fast and exact). Without the mod, the solver falls back to screenshot OCR (slower; EasyOCR downloads ~100MB to `%USERPROFILE%\.EasyOCR\` on first use).

### MelonLoader + companion mod (recommended)

Close Cursed Words, then from the repo root in PowerShell:

```powershell
.\melmod\install-melonloader.ps1
.\melmod\build.ps1
```

Steam default path: `C:\Program Files (x86)\Steam\steamapps\common\Cursed Words\`. Use `-GameDir` on either script if your install is elsewhere. Launch the game **once** from Steam after MelonLoader installs, then start a run and press **F7** before solving. Full steps: [`melmod/README.md`](melmod/README.md).

## Usage

```bash
python -m cursed_words_solver.app
```

For per-tile OCR debug images when using the OCR fallback:

```bash
python -m cursed_words_solver.app --debug-ocr
```

1. **Install melmod** (recommended) — `.\melmod\install-melonloader.ps1` then `.\melmod\build.ps1` (see above), launch the game once, start a run, press **F7** once to refresh `run_state.json` and export the game's word list to `game_words.txt`.

2. **Calibrate** (for overlay screenshot / OCR fallback) — on first run (or `--calibrate` / **F10**), drag a rectangle over the 5×5 board. The money region is **optional** when melmod is active (money comes from the game).

3. **Solve** — press **F8** (default). With melmod, the terminal prints `Board from melmod` and the parsed grid immediately. Without melmod, OCR runs (first solve on CPU can take several minutes). A compact overlay (about the 2nd column from the left) shows the best word and score; numbered green circles on the live board mark which tiles to click (recalibrate with **F10** if misaligned). Highlights are click-through and clear automatically when the round ends or you enter the shop (melmod export). Press **ESC** to hide the overlay and highlights manually.

4. **Quit** — **Ctrl+Shift+Q** or close the overlay window. Ctrl+C often does not work while global hotkeys are active.

5. **Recalibrate** — **F10** updates the capture region; preview at `%USERPROFILE%\.cursed_words_solver\debug\calibration_preview.png`.

### MelonLoader companion

See [`melmod/README.md`](melmod/README.md). The mod exports loadout, the live 5×5 board, and the game's vocabulary to `%USERPROFILE%\.cursed_words_solver\` (auto on loadout/board change, **F7** to force). The solver reloads `run_state.json` on every **F8** solve and prefers `game_words.txt` over ENABLE1 so suggestions match in-game validation.

Without the mod, press **F9** to edit loadout manually; board tiles are read via OCR. Word validation falls back to ENABLE1 until you export `game_words.txt` via melmod.

## Config

Stored at `%USERPROFILE%\.cursed_words_solver\config.json`:

- `board_region` — `{x, y, width, height}` (overlay + OCR fallback + on-board path highlights)

- `show_board_highlight` — default `true`; set `false` to disable numbered circles on the game board

- `hotkey` — default `f8`

- `min_word_length` — default `3`

- `max_word_length` — default `15` (longest path explored on the 5×5 board; max possible is 25). Keep at 15 for long number words (e.g. `fu34s6s`); search cost grows quickly with depth and the solver reserves time for digit/void passes on number boards.

- `search_time_budget_sec` — default `30` (seconds spent finding words per **F8** solve; lower for snappier feedback on easy boards). Older installs with `2` / `15` are auto-upgraded on startup.

- `money_region` — optional; only used for OCR fallback when melmod money is unavailable

- `cell_inset_ratio` — OCR tile crop inset (default `0.1`)

- `debug_ocr` — save per-tile ROI images under `debug/tiles/` when using OCR

- `wordlist` — `game` (default, use `game_words.txt` from melmod) or `enable1` (offline fallback)

On startup the terminal prints which word list is loaded, e.g. `Word list: game (120000 words)`. After each solve it prints the 5×5 grid and `Board source: melmod` or `ocr`.

### Search performance

- **Melmod board (F7)** — accurate tiles avoid wasted DFS branches; use before **F8**.
- **Game wordlist** — press **F7** in-game so `game_words.txt` is exported; tighter dictionary pruning than enable1 fallback.
- **`search_time_budget_sec`** — main knob when you need more candidates explored within a time limit.
- **Curse-heavy boards** (white teleports, queen/rook lines, wildcards) branch heavily; more time helps. Wildcard tiles are searched first; raise `search_time_budget_sec` on dense boards if needed.

### Troubleshooting

- **Wrong words with melmod** — press **F7** in-game, then **F8** again; check `run_state.json` has a `board` section with 25 tiles.

- **OCR wrong** — install melmod, or compare `debug/last_board.png` to the game and recalibrate (**F10**).

- **Overlay stuck on “Press F8 to solve”** — restart the solver after updating; results must update on the Qt GUI thread. Check the terminal for `Done in … Best: WORD` after **F8**.

- **No on-board highlights** — confirm `show_board_highlight` is `true` in config and **F10** board region matches the live 5×5 grid; melmod alone does not position highlights without calibration.

- **No board in JSON** — mod only exports during an active run (not main menu).

- **Invalid word suggestions** — rebuild melmod, press **F7** during a run, and confirm `game_words.txt` exists. If the solver says `enable1 fallback`, the game dictionary was not exported yet.

- **Birthday Cake shows 0 in score effects** — the sticker’s accumulated “Get +X WORD SCORE” must be in `run_state.json` → `extras.birthday_cake_bonus`. Press **F7** in-game (rebuild melmod if needed), or set that value manually to match the in-game sticker UI.

### Scoring calibration (predicted vs in-game)

With melmod companion **v1.1.6+** and a current solver build:

1. **F7** in-game, then **F8** in the solver — writes `last_suggestion.json` with a step-by-step `predicted_trace`.
2. Play the suggested word on the highlighted path before the board changes.
3. If the game score differs, the mod saves `scoring_mismatches\<timestamp>.json` (predicted vs actual traces + board snapshot).
4. Add a regression fixture: `python scripts/mismatch_to_test.py <path-to-mismatch.json>` (writes `tests/fixtures/mismatches/<id>.json`).

Rebuild the companion after pulling solver changes: `.\melmod\build.ps1`. Details: [`melmod/README.md`](melmod/README.md#scoring-mismatch-capture-v116) and [`melmod/SCORING_HOOKS.md`](melmod/SCORING_HOOKS.md).

## Sticker rules catalog

Rules follow the official [Scoring](https://cursedwords.wiki.gg/wiki/Scoring) order (tile scores, word score, then word multipliers). Canonical item lists:

- [List of pins](https://cursedwords.wiki.gg/wiki/List_of_pins)
- [List of stickers](https://cursedwords.wiki.gg/wiki/List_of_stickers)
- [List of stamps](https://cursedwords.wiki.gg/wiki/List_of_stamps)

[`data/wiki/stickers.json`](data/wiki/stickers.json) lists wiki sticker/stamp/boss/pin IDs (with aliases for mod `ArtFileName` mismatches). Pin rules are keyed by **art slug** (`abacus`, `milky_way`, …) via `extras.pin_effect` in `run_state.json`.

**Main Bosses** ([wiki list](https://cursedwords.wiki.gg/wiki/Bosses)): scoring bosses (Salamander, Robo-Monkey, Toothed Whale, Cobra, Wolf) use `boss_id` plus melmod extras `boss_area_number` (1–5) and `boss_cursed` (`true`/`false`). Hyena sets `hyena_blocked` until you sell a sticker/stamp. Bat shrinks the grid: board export includes `rows`/`cols` (height × width) and per-tile `active: false` for off-board cells. After updating the melmod companion, rebuild (`.\melmod\build.ps1`) and press **F7** in-game so `run_state.json` picks up the fix before **F8** solve.

Regenerate from the wiki API:

```bash
curl -s "https://cursedwords.wiki.gg/api.php?action=query&list=categorymembers&cmtitle=Category:Stickers&cmlimit=500&format=json" -o data/wiki/_stickers_raw.json
curl -s "https://cursedwords.wiki.gg/api.php?action=query&list=categorymembers&cmtitle=Category:Stamps&cmlimit=500&format=json" -o data/wiki/_stamps_raw.json
curl -s "https://cursedwords.wiki.gg/api.php?action=query&list=categorymembers&cmtitle=Category:Bosses&cmlimit=50&format=json" -o data/wiki/_bosses_raw.json
curl -s "https://cursedwords.wiki.gg/api.php?action=query&list=categorymembers&cmtitle=Category:Characters&cmlimit=50&format=json" -o data/wiki/_chars_raw.json
python scripts/build_stickers_json.py
```

## Tests

```bash
pip install -e ".[dev]"
pytest tests/ -m "not slow"
pytest tests/ -m slow    # search benchmarks only
```
