# Cursedle (daily fairy trial)

Source: `Assembly-CSharp.dll` (`PuzzleController`, `FairyGridGeneration`, `FairyGrid`, `TileSolutionState`).

Wiki: [Cursedle](https://cursedwords.wiki.gg/wiki/Cursedle)

## Scene

Cursedle uses a dedicated `PuzzleController` scene (Michael's nose on the main menu). It is **not** the Michael boss finale grid (`EncounterController` + 25-tile word).

## Rules

- **6×6** grid (`_gridDimension = 6`).
- **5 guesses** (`_totalGridsPerRound = 5`, `_remainingGrids` decrements on wrong guess).
- **Scoring disabled** for the trial.
- Hidden solution path length **4–6** (`Vocabulary.GetRandomFairyGridWord`).
- Players may submit **any valid dictionary word length** on the board to gather tile feedback (longer words check more tiles).
- Puzzle seed: `new Random(year*10000 + month*100 + day)` from `DateTime.Today`.
- Feedback is **per tile coordinate**, not per letter (`PuzzleController.CheckAnswer`).

| `TileSolutionState` | UI color | Meaning |
|---------------------|----------|---------|
| `CorrectPosition` | Green | Tile is in the solution at this path index |
| `IncorrectPosition` | Yellow | Tile is in the solution but wrong index |
| `AdjacentToPosition` | Red | Not in solution; 8-neighbor adjacent to a solution tile |
| `Incorrect` | Grey | Not in solution and not adjacent |

Adjacency matches `GridUtility.Singleton.AreAdjacentTiles` (chess-king distance ≤ 1).

## Generation

`FairyGridGeneration.GenerateRandomFairyGrid` picks a curated word length 4–6, applies one of seven “theme” mutators (Test Tube, Number Go Up, Queenie, Card Shark, Zombie, Jellyfish, Hungry Snake), places the solution path on the grid, then fills remaining cells.

Decompiled references: [`scripts/decompile_type/out_cursedle/`](../scripts/decompile_type/out_cursedle/).

## Solver companion

Melmod exports `encounter_mode: cursedle`, live guess history, and remaining tries. The Python solver filters hidden **solution** paths to length 4–6, but may suggest **longer dictionary words** as probes to maximize tile feedback. Scoring capture is disabled in that scene.
