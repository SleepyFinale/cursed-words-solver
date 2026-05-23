# Maintenance scripts

Run all commands from the **repository root** (the folder containing `pyproject.toml`).

| Script | Purpose |
|--------|---------|
| `python scripts/build_stickers_json.py` | Regenerate `data/wiki/stickers.json` from wiki API scratch files |
| `python scripts/mismatch_to_test.py <mismatch.json>` | Copy a scoring mismatch into `tests/fixtures/mismatches/` |
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
