# Maintenance scripts

## Game research

Full decompile refresh from your Steam install (core types, quests, shop, stamps, UI + metadata extraction):

```powershell
.\scripts\decompile_all.ps1
.\scripts\decompile_all.ps1 -GameDll "D:\Steam\...\Assembly-CSharp.dll"   # non-default path
.\scripts\decompile_all.ps1 -SkipExtract                                   # decompile only
```

Partial refresh (encounter/sim types only): `.\scripts\decompile_sim_types.ps1`

```bash
python scripts/extract_game_types.py   # also writes shop advice tags per Item subclass
python scripts/extract_run_catalog.py  # rarity/cost/slot per item, characters, bosses (full-run sim)
python scripts/generate_sticker_audit.py
```

See [`docs/game-research/README.md`](../docs/game-research/README.md).

## Trace comparison

```bash
python scripts/compare_trace.py tests/fixtures/mismatches/<id>.json
```

Run all commands from the **repository root** (the folder containing `pyproject.toml`).

| Script | Purpose |
| ------ | ------- |
| `python scripts/build_stickers_json.py` | Regenerate `data/wiki/stickers.json` from wiki API scratch files |
| `python scripts/engine_replay.py [--since DATE] [--write-lists]` | Replay every capture through the engine: exact-score and path-validity rates by month; `--write-lists` regenerates `tests/engine/engine_*_captures.txt` |
| `python scripts/capture_to_fixture.py <round_log.json>` / `--failing` | Copy captures (companion >= 1.4) into `tests/fixtures/captures/` — each file is a test; `--failing` adds every local capture the engine mis-scores |
| `python scripts/search_benchmark.py --latest 30 [--budget 20]` | Re-solve recent rounds with the current search; compare with what was played and the F8 suggestion |
| `python scripts/mismatch_to_test.py <mismatch.json>` | Copy a scoring mismatch into `tests/fixtures/mismatches/` |
| `python scripts/compare_trace.py <mismatch.json> [--replay]` | Step-by-step predicted vs actual trace diff |
| `python scripts/mismatch_to_round_log_fixture.py` | Build round-log fixture from mismatch JSON (see script) |
| `cursed-solver diagnose` | Health report for last F8, round logs, mismatches |
| `cursed-solver explain --round-log <file>` | Why solver missed a submitted path |
| `cursed-solver validate-path --round-log <file>` | Path/quest/dictionary acceptance check |
| `scripts/catalog/achievement_stamps_catalog.py` | Data module (not run directly); imported by `build_stickers_json.py` |

## Regenerate `stickers.json`

Fetch wiki category lists (gitignored scratch files), then build:

```bash
curl -s "https://cursedwords.wiki.gg/api.php?action=query&list=categorymembers&cmtitle=Category:Stickers&cmlimit=500&format=json" -o data/wiki/_stickers_raw.json
curl -s "https://cursedwords.wiki.gg/api.php?action=query&list=categorymembers&cmtitle=Category:Stamps&cmlimit=500&format=json" -o data/wiki/_stamps_raw.json
curl -s "https://cursedwords.wiki.gg/api.php?action=query&list=categorymembers&cmtitle=Category:Bosses&cmlimit=50&format=json" -o data/wiki/_bosses_raw.json
curl -s "https://cursedwords.wiki.gg/api.php?action=query&list=categorymembers&cmtitle=Category:Characters&cmlimit=50&format=json" -o data/wiki/_chars_raw.json
python scripts/build_stickers_json.py
```

## Scoring mismatch fixtures

After the melmod companion records a mismatch under `%USERPROFILE%\.cursed_words_solver\scoring_mismatches\`:

```bash
python scripts/mismatch_to_test.py %USERPROFILE%\.cursed_words_solver\scoring_mismatches\20260523_143022.json
pytest tests/regression/ -k 20260523_143022
```
