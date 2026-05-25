# Tile init regression triage

After enabling `tile_scoring.apply_tile_init` in the pipeline:

| Phase | Trace `phase` | Typical mismatch cause |
|-------|---------------|------------------------|
| glitch_settle | `tile_init` / `glitch_settle` | Deterministic RNG ≠ live Unity random |
| currency | `tile_init` / `currency` | Fixtures captured before currency $ bump |
| pink | `tile_init` / `pink` | Piggy bank meta only (no tile score delta) |
| poison | `tile_init` / `poison` | Missing `extras.green_poison_bonus` in old snapshots |
| init_scores | `tile_init` / `init_scores` | Cactus growth / purple dual-colour sticker fixes |

Filter mismatch JSON traces:

```python
[t for t in predicted_trace if t.get("phase") == "tile_init"]
```

Rebuild melmod and press **F7** so new exports include `green_poison_bonus`, `was_glitch`, `cactus_growth`.
