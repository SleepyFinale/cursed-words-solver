# Boss regression triage

Filter mismatch traces for boss phases:

```python
[t for t in predicted_trace if t.get("phase") in ("boss_early", "boss_late")]
```

| Phase | Typical cause |
|-------|----------------|
| `boss_early` | Salamander penalty, Robo-Monkey money subtract, Fox submit steal |
| `boss_late` | Hourglass-reordered boss pass |

Melmod F7 extras: `boss_id`, `boss_cursed`, `boss_area_number`, `boss_floor_modification`, `hyena_blocked`, `capybara_shuffle`.

Rebuild melmod after BossResolver changes: `.\melmod\build.ps1`
