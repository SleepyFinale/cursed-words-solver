using System;
using System.Collections.Generic;

namespace CursedWordsSolverCompanion
{
    /// <summary>
    /// Rack placement hint from last_suggestion.json (Python F8 solve).
    /// </summary>
    public sealed class SuggestedConsumablePlacement
    {
        public int row;
        public int col;
        public int index;
        public string letter;
        public int rack_index;
    }

    /// <summary>
    /// Board fingerprint drift tolerance when the player places suggested rack consumables.
    /// Parity contract: tests/test_suggestion_placement.py (Python solver).
    /// </summary>
    public static class ConsumablePlacementHelper
    {
        public static bool BoardFingerprintMatchesSuggestion(
            LastSuggestion suggestion,
            string currentBoardFingerprint
        )
        {
            if (suggestion == null)
                return false;
            var saved = suggestion.board_fingerprint ?? "";
            var current = currentBoardFingerprint ?? "";
            if (string.Equals(saved, current, StringComparison.Ordinal))
                return true;
            return IsConsumablePlacementProgress(
                saved,
                current,
                suggestion.consumable_placements
            );
        }

        public static bool IsConsumablePlacementProgress(
            string savedBoardFingerprint,
            string currentBoardFingerprint,
            List<SuggestedConsumablePlacement> placements
        )
        {
            if (placements == null || placements.Count == 0)
                return false;

            var saved = ParseBoardFpTiles(savedBoardFingerprint);
            var current = ParseBoardFpTiles(currentBoardFingerprint);
            if (saved.Count == 0 || current.Count == 0)
                return false;

            var placementCells = PlacementCellsFromRecords(placements);
            if (placementCells.Count == 0)
                return false;

            var allKeys = new HashSet<string>();
            foreach (var key in saved.Keys)
                allKeys.Add(key);
            foreach (var key in current.Keys)
                allKeys.Add(key);

            var changedKeys = new List<string>();
            foreach (var key in allKeys)
            {
                string savedTile;
                string currentTile;
                saved.TryGetValue(key, out savedTile);
                current.TryGetValue(key, out currentTile);
                savedTile = savedTile ?? "";
                currentTile = currentTile ?? "";
                if (!string.Equals(savedTile, currentTile, StringComparison.Ordinal))
                    changedKeys.Add(key);
            }

            if (changedKeys.Count == 0)
                return false;

            foreach (var key in changedKeys)
            {
                string placementLetter;
                if (!placementCells.TryGetValue(key, out placementLetter))
                    return false;

                string curTile;
                if (!current.TryGetValue(key, out curTile) || string.IsNullOrEmpty(curTile))
                    return false;

                if (!curTile.ToUpperInvariant().StartsWith(placementLetter, StringComparison.Ordinal))
                    return false;
            }

            return true;
        }

        private static Dictionary<string, string> ParseBoardFpTiles(string fingerprint)
        {
            var tiles = new Dictionary<string, string>();
            var fp = (fingerprint ?? "").Trim();
            if (string.IsNullOrEmpty(fp))
                return tiles;

            var pipe = fp.IndexOf('|');
            var suffix = pipe >= 0 ? fp.Substring(pipe + 1) : fp;
            foreach (var segment in suffix.Split(';'))
            {
                var trimmed = (segment ?? "").Trim();
                if (string.IsNullOrEmpty(trimmed))
                    continue;
                var colon = trimmed.IndexOf(':');
                if (colon < 0)
                    continue;
                var coord = trimmed.Substring(0, colon);
                var rest = trimmed.Substring(colon + 1);
                var comma = coord.IndexOf(',');
                if (comma < 0)
                    continue;
                var row = coord.Substring(0, comma);
                var col = coord.Substring(comma + 1);
                tiles[row + "," + col] = rest;
            }

            return tiles;
        }

        private static Dictionary<string, string> PlacementCellsFromRecords(
            List<SuggestedConsumablePlacement> placements
        )
        {
            var cells = new Dictionary<string, string>();
            if (placements == null)
                return cells;

            foreach (var rec in placements)
            {
                if (rec == null)
                    continue;
                var letter = (rec.letter ?? "").Trim().ToUpperInvariant();
                if (string.IsNullOrEmpty(letter))
                    continue;
                cells[rec.row + "," + rec.col] = letter;
            }

            return cells;
        }
    }
}
