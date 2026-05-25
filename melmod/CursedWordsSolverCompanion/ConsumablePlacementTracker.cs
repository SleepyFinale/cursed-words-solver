using System;
using System.Collections.Generic;

namespace CursedWordsSolverCompanion
{
    public sealed class ConsumablePlacementRecord
    {
        public int row;
        public int col;
        public int rack_index = -1;
        public BoardTileSnapshot new_tile;
        public BoardTileSnapshot replaced_tile;
        public string detected_at;
    }

    /// <summary>
    /// Detects consumable placements via board snapshot diffs between auto-exports.
    /// </summary>
    public static class ConsumablePlacementTracker
    {
        private static BoardSnapshot _previousBoard;
        private static readonly List<ConsumablePlacementRecord> Pending =
            new List<ConsumablePlacementRecord>();

        public static void OnBoardSnapshot(BoardSnapshot current)
        {
            if (current?.tiles == null)
                return;

            if (_previousBoard?.tiles != null)
                DiffBoards(_previousBoard, current);

            _previousBoard = CloneBoard(current);
        }

        public static List<ConsumablePlacementRecord> DrainPlacementsSinceLastSubmit()
        {
            var copy = new List<ConsumablePlacementRecord>(Pending);
            Pending.Clear();
            return copy;
        }

        public static void ResetAfterSubmit(BoardSnapshot boardAtSubmit)
        {
            _previousBoard = boardAtSubmit != null ? CloneBoard(boardAtSubmit) : null;
        }

        private static void DiffBoards(BoardSnapshot prev, BoardSnapshot next)
        {
            var prevByCell = IndexTiles(prev.tiles);
            var nextByCell = IndexTiles(next.tiles);

            foreach (var kv in nextByCell)
            {
                var key = kv.Key;
                var newTile = kv.Value;
                if (newTile == null)
                    continue;

                if (!IsConsumablePlacement(newTile))
                    continue;

                prevByCell.TryGetValue(key, out var oldTile);
                if (TilesEqual(oldTile, newTile))
                    continue;

                Pending.Add(
                    new ConsumablePlacementRecord
                    {
                        row = newTile.row,
                        col = newTile.col,
                        rack_index = GuessRackIndex(newTile),
                        new_tile = CloneTile(newTile),
                        replaced_tile = oldTile != null ? CloneTile(oldTile) : null,
                        detected_at = DateTime.UtcNow.ToString("o"),
                    }
                );
            }
        }

        private static bool IsConsumablePlacement(BoardTileSnapshot tile)
        {
            if (tile == null)
                return false;
            return tile.was_consumable || tile.consumable;
        }

        private static int GuessRackIndex(BoardTileSnapshot placed)
        {
            try
            {
                var player = RunStateExporter.GetPlayerForUpdate();
                if (player?.ConsumableTiles == null || placed == null)
                    return -1;

                var target = (placed.letter ?? "").Trim().ToLowerInvariant();
                for (var i = 0; i < player.ConsumableTiles.Length; i++)
                {
                    var rack = player.ConsumableTiles[i];
                    if (rack == null)
                        continue;
                    var snap = BoardExporter.ExportTileAt(rack, -1, i);
                    if (snap == null)
                        continue;
                    var rackLetter = (snap.letter ?? "").Trim().ToLowerInvariant();
                    if (!string.IsNullOrEmpty(target) && rackLetter == target)
                        return i;
                }
            }
            catch
            {
                // optional
            }

            return -1;
        }

        private static Dictionary<string, BoardTileSnapshot> IndexTiles(
            List<BoardTileSnapshot> tiles
        )
        {
            var map = new Dictionary<string, BoardTileSnapshot>();
            if (tiles == null)
                return map;

            foreach (var t in tiles)
            {
                if (t == null)
                    continue;
                map[t.row + "," + t.col] = t;
            }

            return map;
        }

        private static bool TilesEqual(BoardTileSnapshot a, BoardTileSnapshot b)
        {
            if (a == null && b == null)
                return true;
            if (a == null || b == null)
                return false;

            return a.row == b.row
                && a.col == b.col
                && a.letter == b.letter
                && a.char_display == b.char_display
                && a.curse == b.curse
                && a.color == b.color
                && Math.Abs(a.base_score - b.base_score) < 0.001
                && a.consumable == b.consumable
                && a.was_consumable == b.was_consumable;
        }

        private static BoardTileSnapshot CloneTile(BoardTileSnapshot t)
        {
            if (t == null)
                return null;

            return new BoardTileSnapshot
            {
                row = t.row,
                col = t.col,
                char_display = t.char_display,
                letter = t.letter,
                base_score = t.base_score,
                color = t.color,
                curse = t.curse,
                number_value = t.number_value,
                fraction_value = t.fraction_value,
                consumable = t.consumable,
                was_consumable = t.was_consumable,
                active = t.active,
                take = t.take,
                chess_color = t.chess_color,
                card_suit = t.card_suit,
                card_rank = t.card_rank,
                is_joker = t.is_joker,
                was_glitch = t.was_glitch,
                cactus_growth = t.cactus_growth,
                scattered_item_id = t.scattered_item_id,
            };
        }

        private static BoardSnapshot CloneBoard(BoardSnapshot board)
        {
            if (board == null)
                return null;

            var clone = new BoardSnapshot
            {
                source = board.source,
                row_order = board.row_order,
                money = board.money,
                rows = board.rows,
                cols = board.cols,
                playable_origin = board.playable_origin,
                playable_min_row = board.playable_min_row,
                playable_max_row = board.playable_max_row,
                playable_min_col = board.playable_min_col,
                playable_max_col = board.playable_max_col,
            };

            if (board.tiles != null)
            {
                foreach (var t in board.tiles)
                    clone.tiles.Add(CloneTile(t));
            }

            return clone;
        }
    }
}
