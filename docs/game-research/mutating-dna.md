# Mutating DNA (stamp)

Source: decompiled `MutatingDNA` and `Tile.GetStringRepresentation` from `Assembly-CSharp.dll` (game v0.2.0). Wiki: [Mutating DNA](https://cursedwords.wiki.gg/wiki/Mutating_DNA).

## Effect (wiki)

Each time you use a letter, tiles with that letter get +1 TILE SCORE whilst you have this item.

On **number boards** (Sudoku / Advent Calendar), the game keys off `Tile.GetStringRepresentation()` — number faces like `"1"`, `"22"` — not dictionary word letters.

## Game implementation

```csharp
public class MutatingDNA : Item
{
    public Dictionary<string, int> LetterUseCounts = new Dictionary<string, int>();

    public override void ApplyTileBonus(
        ScoreCalcVizInfo step, int index, List<Tile> tiles,
        List<TileSelection> selections, List<HistoricWord> previousWords, GridData gridData)
    {
        if (tiles.Count != 0)
        {
            string key = tiles[index].GetStringRepresentation();
            if (LetterUseCounts.ContainsKey(key))
            {
                step.TileScores[index] += LetterUseCounts[key];
                LetterUseCounts[key]++;
            }
            else
            {
                LetterUseCounts[key] = 1;  // first use: no tile bonus
            }
        }
    }
}
```

- **Tile-only** — overrides `ApplyTileBonus` only; no `ApplyWordBonus`.
- Called **once per path tile** inside `Item.ApplyItemToScore`.
- State persists on the stamp instance in RAM for the run.

## `GetStringRepresentation` keys (forWordValidity=false)

| Tile type | Key |
|-----------|-----|
| Letter | lowercase letter (`"a"`) |
| Number | `Number.ToString()` (`"1"`, `"22"`) |
| Currency | display string (font-tagged) or lowercase when `forWordValidity=true` |

Mutating DNA uses the default (`forWordValidity=false`).

## Scoring rules

1. **First use** of a key: set count to 1, **+0** tile score on that tile.
2. **Subsequent uses**: add **current count** to that path tile's score, then increment count.
3. Multi-tile words: each path index gets its own `ApplyTileBonus` call with that tile's key.

Example: `LetterUseCounts = {"1": 5, "2": 1, "3": 1}` on path using number faces 1/2/3 → tile bonuses +5, +1, +1 (+7 total).

## Solver / melmod export

- Export extra: `mutating_dna_letter_counts` (JSON map string → int). Values include **number strings** and letters.
- Prefer live `MutatingDNA.LetterUseCounts` from equipped stamp; rebuild from historic words using string repr when live read is empty.
- Python: `tile_string_representation()` + `apply_mutating_dna_bonus()` mirror `ApplyTileBonus`.

## Regression fixtures

- `tests/fixtures/mismatches/20260615_174109.json` — single tile `"1"`, +3 DNA
- `tests/fixtures/mismatches/20260615_174218.json` — single tile `"1"`, +4 DNA
- `tests/fixtures/mismatches/20260615_174554.json` — `'pho'` on `"1"`/`"2"`/`"3"`, +7 DNA
