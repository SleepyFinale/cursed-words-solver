# Footprints non-adjacent move counting

Source: decompiled `Assembly-CSharp.dll` via `scripts/decompile_type` (`Footprints`, `GridUtilitySingleton`).

## Footprints.ApplyWordBonus

Footprints counts consecutive path tile pairs where `!GridUtility.Singleton.AreAdjacentTiles(prev, cur)`. When the count is **≥ 3**, it applies a multiplicative word bonus of `VariableValue * 100` (level 1 → ×2).

```csharp
for (int i = 1; i < tiles.Count; i++)
{
    if (!GridUtility.Singleton.AreAdjacentTiles(tiles[i - 1], tiles[i]))
    {
        num++;
    }
}
if (num >= 3)
{
    step.WordBonus = new WordBonusToken(UpgradeableComponents[0].VariableValue * 100, isMultiplicative: true);
}
```

## GridUtilitySingleton.AreAdjacentTiles

Adjacency is **8-directional** (orthogonal and diagonal). Same helper is used by **Ruler** and **Head In The Clouds**.

```csharp
public bool AreAdjacentTiles(Tile tile1, Tile tile2)
{
    Vector2Int a = tile1.GetCoordinates();
    Vector2Int b = tile2.GetCoordinates();
    if (Math.Abs(a.x - b.x) <= 1 && Math.Abs(a.y - b.y) <= 1)
        return a != b;
    return false;
}
```

Hungry Snake horizontal wrap affects `GetTilesAdjacentToCoordinates(..., isForcingWrapping)` for movement, but **not** `AreAdjacentTiles` for Footprints scoring.

## Solver mirror

[`cursed_words_solver/rules/scoring_conditions.py`](../../cursed_words_solver/rules/scoring_conditions.py) — `_path_step_adjacent` and `non_adjacent_step_count` must match `AreAdjacentTiles`.

Wiki: [Footprints](https://cursedwords.wiki.gg/wiki/Footprints)
