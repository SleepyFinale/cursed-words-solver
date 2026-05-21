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

## Usage

```bash
python -m cursed_words_solver.app
```

For per-tile OCR debug images when using the OCR fallback:

```bash
python -m cursed_words_solver.app --debug-ocr
```

1. **Install melmod** (recommended) — build with `.\melmod\build.ps1`, start a run, press **F7** once to refresh `run_state.json` and export the game's word list to `game_words.txt`.

2. **Calibrate** (for overlay screenshot / OCR fallback) — on first run (or `--calibrate` / **F10**), drag a rectangle over the 5×5 board. The money region is **optional** when melmod is active (money comes from the game).

3. **Solve** — press **F8** (default). With melmod, the terminal prints `Board from melmod` and the parsed grid immediately. Without melmod, OCR runs (first solve on CPU can take several minutes).

4. **Quit** — **Ctrl+Shift+Q** or close the overlay window. Ctrl+C often does not work while global hotkeys are active.

5. **Recalibrate** — **F10** updates the capture region; preview at `%USERPROFILE%\.cursed_words_solver\debug\calibration_preview.png`.

### MelonLoader companion

See [`melmod/README.md`](melmod/README.md). The mod exports loadout, the live 5×5 board, and the game's vocabulary to `%USERPROFILE%\.cursed_words_solver\` (auto on loadout/board change, **F7** to force). The solver reloads `run_state.json` on every **F8** solve and prefers `game_words.txt` over ENABLE1 so suggestions match in-game validation.

Without the mod, press **F9** to edit loadout manually; board tiles are read via OCR. Word validation falls back to ENABLE1 until you export `game_words.txt` via melmod.

## Config

Stored at `%USERPROFILE%\.cursed_words_solver\config.json`:

- `board_region` — `{x, y, width, height}` (overlay + OCR fallback)

- `hotkey` — default `f8`

- `min_word_length` — default `3`

- `money_region` — optional; only used for OCR fallback when melmod money is unavailable

- `cell_inset_ratio` — OCR tile crop inset (default `0.1`)

- `debug_ocr` — save per-tile ROI images under `debug/tiles/` when using OCR

- `wordlist` — `game` (default, use `game_words.txt` from melmod) or `enable1` (offline fallback)

On startup the terminal prints which word list is loaded, e.g. `Word list: game (120000 words)`. After each solve it prints the 5×5 grid and `Board source: melmod` or `ocr`.

### Troubleshooting

- **Wrong words with melmod** — press **F7** in-game, then **F8** again; check `run_state.json` has a `board` section with 25 tiles.

- **OCR wrong** — install melmod, or compare `debug/last_board.png` to the game and recalibrate (**F10**).

- **No board in JSON** — mod only exports during an active run (not main menu).

- **Invalid word suggestions** — rebuild melmod, press **F7** during a run, and confirm `game_words.txt` exists. If the solver says `enable1 fallback`, the game dictionary was not exported yet.

## Sticker rules catalog

[`data/wiki/stickers.json`](data/wiki/stickers.json) lists wiki sticker/stamp/boss IDs (with aliases for mod `ArtFileName` mismatches). Regenerate from the wiki API:

```bash
curl -s "https://cursedwords.wiki.gg/api.php?action=query&list=categorymembers&cmtitle=Category:Stickers&cmlimit=500&format=json" -o data/wiki/_stickers_raw.json
curl -s "https://cursedwords.wiki.gg/api.php?action=query&list=categorymembers&cmtitle=Category:Stamps&cmlimit=500&format=json" -o data/wiki/_stamps_raw.json
curl -s "https://cursedwords.wiki.gg/api.php?action=query&list=categorymembers&cmtitle=Category:Characters&cmlimit=50&format=json" -o data/wiki/_chars_raw.json
python scripts/build_stickers_json.py
```

## Tests

```bash
pytest tests/
```
