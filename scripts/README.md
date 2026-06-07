# Maintenance scripts

## Game research

```bash
python scripts/extract_game_types.py
python scripts/generate_sticker_audit.py
```

See [`docs/game-research/README.md`](../docs/game-research/README.md).

## Trace comparison

```bash
python scripts/compare_trace.py tests/fixtures/mismatches/<id>.json
```

Run all commands from the **repository root** (the folder containing `pyproject.toml`).

| Script | Purpose |
|--------|---------|
| `python scripts/build_stickers_json.py` | Regenerate `data/wiki/stickers.json` from wiki API scratch files |
| `python scripts/mismatch_to_test.py <mismatch.json>` | Copy a scoring mismatch into `tests/fixtures/mismatches/` |
| `python scripts/profile_solve.py [fixture.json] --budget 8` | cProfile chess-heavy solve; DFS vs scoring breakdown |
| `python scripts/profile_search.py [--run-state] [--latest N] --budget 12` | SearchTiming: scoring % vs DFS expansions; Tier-2 recommendation |
| `python scripts/profile_search.py --round-logs --use-config-budget` | Profile every board from your `round_logs/` play sessions |
| `python scripts/profile_search.py --round-logs --mismatches-only --budget 12` | Profile only rounds where in-game score differed from solver |
| `python scripts/analyze_data_structures.py --budget 12` | Full structure analysis: hot-path, cache hit rates, precompute audit; see [`docs/DATA_STRUCTURE_ANALYSIS.md`](../docs/DATA_STRUCTURE_ANALYSIS.md) |
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
