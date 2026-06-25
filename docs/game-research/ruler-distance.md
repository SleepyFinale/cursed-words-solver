# Ruler cumulative Distance

Source: decompiled `Assembly-CSharp.dll` (`Ruler`, `GridUtilitySingleton`), [Ruler wiki](https://cursedwords.wiki.gg/wiki/Ruler).

## Ruler.ApplyWordBonus

Ruler stores a run-long counter `Distance` on the stamp instance. Each submitted word adds its non-adjacent step count, then emits a multiplicative word bonus from the **new** total:

```csharp
public int Distance;

Distance += num;  // num = non-adjacent steps this word
if (Distance > 0)
    step.WordBonus = new WordBonusToken(100 + Distance * 2, isMultiplicative: true);
```

| Topic | Behavior |
|-------|----------|
| Adjacency | `GridUtility.Singleton.AreAdjacentTiles` — 8-directional (see [footprints-adjacency.md](footprints-adjacency.md)) |
| Formula | `×(100 + Distance × 2) / 100` — each accumulated unit is +2% word score |
| Zero case | No `WordBonus` when `Distance` is 0 after increment |
| UI text | `GetDescription()` shows the **current accumulated** multiplier |

Wiki copy (“Improved by 0.02 for each non-adjacent move”) describes the per-unit increment; the game persists the total on the stamp.

## Solver export

melmod exports pre-submit stamp state as `ruler_distance` (and caches `ruler_distance_last_known` on disk). When scoring a candidate path:

```
effective_distance = ruler_distance + non_adjacent_step_count(path)
multiplier = (100 + effective_distance × 2) / 100   # if effective_distance > 0
```

Post-submit simulation increments `ruler_distance` by the path's non-adjacent step count (`advance_ruler_distance_after_submit`).
