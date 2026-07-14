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
| `python scripts/mismatch_to_test.py <mismatch.json>` | Copy a scoring mismatch into `tests/fixtures/mismatches/` |
| `python scripts/compare_trace.py <mismatch.json> [--replay]` | Step-by-step predicted vs actual trace diff |
| `python scripts/triage_mismatch.py <mismatch.json>` | Classify capture (stale vs pipeline vs search miss) |
| `python scripts/promote_scoring_mismatches.py` | Batch-promote live `scoring_mismatches/` into test fixtures |
| `python scripts/mismatch_to_round_log_fixture.py` | Build round-log fixture from mismatch JSON (see script) |
| `cursed-solver diagnose` | Health report for last F8, round logs, mismatches |
| `cursed-solver explain --round-log <file>` | Why solver missed a submitted path |
| `cursed-solver validate-path --round-log <file>` | Path/quest/dictionary acceptance check |
| `python scripts/profile_solve.py [fixture.json] --budget 8` | cProfile chess-heavy solve; DFS vs scoring breakdown |
| `python scripts/profile_search.py [--run-state] [--latest N] --budget 12` | SearchTiming: scoring % vs DFS expansions; Tier-2 recommendation |
| `python scripts/search_quality.py [--ab] [--budget 12] [--long-budget 60]` | Miss-gap harness: budgeted vs long-run (or beam vs DFS A/B) |
| `python scripts/profile_search.py --round-logs --use-config-budget` | Profile every board from your `round_logs/` play sessions |
| `python scripts/profile_search.py --round-logs --mismatches-only --budget 12` | Profile only rounds where in-game score differed from solver |
| `python scripts/analyze_data_structures.py --budget 12` | Full structure analysis: phase timings, caches, tier-2, context precompute, optimization gating; see [`docs/DATA_STRUCTURE_ANALYSIS.md`](../docs/DATA_STRUCTURE_ANALYSIS.md) |
| `python scripts/analyze_data_structures.py --write-doc` | Regenerate `docs/DATA_STRUCTURE_ANALYSIS.md` from default fixtures |
| `python scripts/analyze_data_structures.py --latest 4 --category chess` | Analyze newest mismatches or filter by category (chess, sticker, hanafuda, number, boss) |
| `python scripts/analyze_data_structures.py --profile-flat` | Optional extra cProfile pass for Board.flat cumulative seconds (slow) |
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
