using System;
using System.Collections.Generic;
using System.Text;
using Newtonsoft.Json;
using UnityEngine;

namespace CursedWordsSolverCompanion
{
    public sealed class CursedleGuessTileRecord
    {
        public int row;
        public int col;
        public int index;
        public string feedback;
    }

    public sealed class CursedleGuessRecord
    {
        public List<int> path = new List<int>();
        public List<CursedleGuessTileRecord> tiles = new List<CursedleGuessTileRecord>();
    }

    /// <summary>
    /// RAM-only guess history for the active Cursedle scene. Cleared on puzzle start/exit.
    /// </summary>
    public static class CursedleGuessTracker
    {
        private static readonly List<CursedleGuessRecord> Guesses = new List<CursedleGuessRecord>();
        private static int _activePuzzleId;

        public static void OnPuzzleStarted(PuzzleController controller)
        {
            Reset();
            if (controller != null)
                _activePuzzleId = controller.GetInstanceID();
        }

        public static void Reset()
        {
            Guesses.Clear();
            _activePuzzleId = 0;
        }

        public static int GuessCount
        {
            get { return Guesses.Count; }
        }

        public static void OnGuessAdded(
            PuzzleController controller,
            List<Tile> tiles,
            List<TileSolutionState> states
        )
        {
            if (controller == null || tiles == null || states == null)
                return;
            if (_activePuzzleId != 0 && controller.GetInstanceID() != _activePuzzleId)
                return;

            GridData grid = null;
            try
            {
                grid = controller.GetGridData();
            }
            catch
            {
                grid = null;
            }

            var cols = 6;
            var gridRows = 6;
            if (grid != null)
            {
                try
                {
                    var dims = grid.Dimensions;
                    if (dims.x > 0)
                        cols = dims.x;
                    if (dims.y > 0)
                        gridRows = dims.y;
                }
                catch
                {
                    // optional
                }
            }

            var record = new CursedleGuessRecord();
            var count = Math.Min(tiles.Count, states.Count);
            for (var i = 0; i < count; i++)
            {
                var tile = tiles[i];
                if (tile == null)
                    continue;
                Vector2Int coord;
                try
                {
                    coord = tile.Coordinates;
                }
                catch
                {
                    continue;
                }

                var col = coord.x;
                // Unity y=0 is bottom; solver board export uses top_first (row 0 = top).
                var storageRow = gridRows - 1 - coord.y;
                // Cursedle submit indices use Unity bottom-origin (not CoordsToSolverIndex).
                var cursedleIndex = coord.y * cols + col;
                record.path.Add(cursedleIndex);
                record.tiles.Add(
                    new CursedleGuessTileRecord
                    {
                        row = storageRow,
                        col = col,
                        index = cursedleIndex,
                        feedback = FeedbackToString(states[i]),
                    }
                );
            }

            if (record.path.Count > 0)
                Guesses.Add(record);
        }

        public static string SerializeGuessesJson()
        {
            if (Guesses.Count == 0)
                return "[]";
            return JsonConvert.SerializeObject(Guesses);
        }

        public static void AppendFingerprint(StringBuilder sb)
        {
            if (sb == null)
                return;
            sb.Append("|cursedle:");
            sb.Append(Guesses.Count);
            foreach (var guess in Guesses)
            {
                if (guess?.path == null)
                    continue;
                sb.Append('|');
                for (var i = 0; i < guess.path.Count; i++)
                {
                    if (i > 0)
                        sb.Append(',');
                    sb.Append(guess.path[i]);
                    var fb = "";
                    if (guess.tiles != null && i < guess.tiles.Count && guess.tiles[i] != null)
                        fb = guess.tiles[i].feedback ?? "";
                    sb.Append(':');
                    sb.Append(fb);
                }
            }
        }

        private static string FeedbackToString(TileSolutionState state)
        {
            switch (state)
            {
                case TileSolutionState.CorrectPosition:
                    return "green";
                case TileSolutionState.IncorrectPosition:
                    return "yellow";
                case TileSolutionState.AdjacentToPosition:
                    return "red";
                case TileSolutionState.Incorrect:
                    return "grey";
                default:
                    return "none";
            }
        }
    }
}
