using System;
using System.Collections.Generic;
using System.Text;
using UnityEngine;

namespace CursedWordsSolverCompanion
{
    public static class BoardExporter
    {
        private const int DefaultGridSize = 5;

        public static BoardSnapshot TryBuild(Player player)
        {
            if (player == null)
                return null;

            var grid = ResolveActiveGridData();
            if (grid == null)
                return null;

            var tiles = ExportTiles(grid);
            if (tiles == null || tiles.Count != DefaultGridSize * DefaultGridSize)
                return null;

            return new BoardSnapshot
            {
                source = "melmod",
                money = player.Money,
                rows = DefaultGridSize,
                cols = DefaultGridSize,
                tiles = tiles,
            };
        }

        public static string ComputeBoardFingerprint(BoardSnapshot board)
        {
            if (board == null || board.tiles == null || board.tiles.Count == 0)
                return "";

            var sb = new StringBuilder();
            sb.Append(board.money);
            sb.Append('|');
            foreach (var t in board.tiles)
            {
                sb.Append(t.row);
                sb.Append(',');
                sb.Append(t.col);
                sb.Append(':');
                sb.Append(t.letter ?? "");
                sb.Append('/');
                sb.Append(t.curse ?? "");
                sb.Append('/');
                sb.Append(t.color ?? "");
                sb.Append(';');
            }
            return sb.ToString();
        }

        private static GridData ResolveActiveGridData()
        {
            GridData grid = null;

            var encounter = UnityEngine.Object.FindAnyObjectByType<EncounterController>();
            if (encounter != null)
            {
                try
                {
                    grid = encounter.GetGridData();
                }
                catch
                {
                    grid = null;
                }
            }

            if (grid != null && HasUsableTiles(grid))
                return grid;

            var puzzle = UnityEngine.Object.FindAnyObjectByType<PuzzleController>();
            if (puzzle != null)
            {
                try
                {
                    grid = puzzle.GetGridData();
                }
                catch
                {
                    grid = null;
                }
            }

            if (grid != null && HasUsableTiles(grid))
                return grid;

            return null;
        }

        private static bool HasUsableTiles(GridData grid)
        {
            if (grid == null)
                return false;

            try
            {
                var dims = grid.Dimensions;
                if (dims.x >= 1 && dims.y >= 1)
                    return true;
            }
            catch
            {
                // fall through
            }

            return grid.GridTiles != null && grid.GridTiles.Length > 0;
        }

        private static List<BoardTileSnapshot> ExportTiles(GridData grid)
        {
            var result = new List<BoardTileSnapshot>(DefaultGridSize * DefaultGridSize);
            var size = DefaultGridSize;

            try
            {
                var dims = grid.Dimensions;
                if (dims.x > 0)
                    size = dims.x;
            }
            catch
            {
                size = DefaultGridSize;
            }

            if (size != DefaultGridSize)
                size = DefaultGridSize;

            for (var row = 0; row < DefaultGridSize; row++)
            {
                for (var col = 0; col < DefaultGridSize; col++)
                {
                    Tile tile = null;
                    try
                    {
                        tile = grid.GetTileAtCoordinates(col, row);
                    }
                    catch
                    {
                        try
                        {
                            tile = grid.GetTileAtCoordinates(new Vector2Int(col, row));
                        }
                        catch
                        {
                            tile = null;
                        }
                    }

                    if (tile == null && grid.GridTiles != null)
                    {
                        var idx = row * DefaultGridSize + col;
                        if (idx >= 0 && idx < grid.GridTiles.Length)
                            tile = grid.GridTiles[idx];
                    }

                    if (tile == null || IsSkippedTile(tile))
                        return null;

                    var displayRow = DefaultGridSize - 1 - row;
                    result.Add(MapTile(tile, displayRow, col));
                }
            }

            return result;
        }

        private static bool IsSkippedTile(Tile tile)
        {
            if (tile == null)
                return true;

            try
            {
                if (tile.Gone)
                    return true;
            }
            catch
            {
                // ignore
            }

            try
            {
                if (tile.IsEmpty())
                    return true;
            }
            catch
            {
                // ignore
            }

            try
            {
                if (tile.IsEmptyTile)
                    return true;
            }
            catch
            {
                // ignore
            }

            return false;
        }

        private static BoardTileSnapshot MapTile(Tile tile, int row, int col)
        {
            var glyph = tile.GetGlyphType();
            var curse = MapCurse(tile, glyph);
            var letter = MapLetter(tile, glyph, curse);
            var display = MapDisplay(tile, letter);
            var color = MapColor(tile);
            var baseScore = MapBaseScore(tile);

            var snap = new BoardTileSnapshot
            {
                row = row,
                col = col,
                char_display = display,
                letter = letter,
                base_score = baseScore,
                color = color,
                curse = curse,
            };

            if (curse == "number")
            {
                try
                {
                    snap.number_value = tile.GetNumber();
                }
                catch
                {
                    int parsed;
                    if (int.TryParse(letter, out parsed))
                        snap.number_value = parsed;
                }
            }

            if (curse == "fraction")
            {
                try
                {
                    snap.fraction_value = tile.GetFractionFloat();
                }
                catch
                {
                    snap.fraction_value = null;
                }
            }

            return snap;
        }

        private static string MapDisplay(Tile tile, string letter)
        {
            try
            {
                var s = tile.GetStringRepresentation();
                if (!string.IsNullOrWhiteSpace(s))
                    return s.Trim();
            }
            catch
            {
                // fall through
            }

            try
            {
                var s = tile.GetValueForDisplay();
                if (!string.IsNullOrWhiteSpace(s))
                    return s.Trim();
            }
            catch
            {
                // fall through
            }

            return letter ?? "?";
        }

        private static string MapLetter(Tile tile, GlyphType glyph, string curse)
        {
            if (curse.StartsWith("chess_"))
                return "?";

            if (glyph == GlyphType.Blank)
                return "?";

            if (glyph == GlyphType.Number)
            {
                try
                {
                    return tile.GetNumber().ToString();
                }
                catch
                {
                    if (tile.Number != 0)
                        return tile.Number.ToString();
                }
            }

            if (glyph == GlyphType.Fraction)
            {
                try
                {
                    return tile.GetFractionFloat().ToString();
                }
                catch
                {
                    return "?";
                }
            }

            if (glyph == GlyphType.Currency)
            {
                try
                {
                    var sym = tile.GetStringRepresentation();
                    if (!string.IsNullOrEmpty(sym))
                        return sym.Trim();
                }
                catch
                {
                    // fall through
                }
            }

            var letter = tile.Letter;
            if (!string.IsNullOrWhiteSpace(letter))
                return letter.Trim().ToUpperInvariant();

            if (glyph == GlyphType.Letter)
                return "?";

            return "?";
        }

        private static int MapBaseScore(Tile tile)
        {
            try
            {
                var packet = tile.GetValue();
                if (packet != null)
                    return (int)Math.Max(0, Math.Min(10, packet.Score));
            }
            catch
            {
                // fall through
            }

            return 0;
        }

        private static string MapColor(Tile tile)
        {
            try
            {
                var tt = tile.GetTileType();
                switch (tt)
                {
                    case TileType.Normal:
                        return "colorless";
                    case TileType.Red:
                        return "red";
                    case TileType.Blue:
                        return "blue";
                    case TileType.Shiny:
                        return "shiny";
                    case TileType.Void:
                        return "void";
                    case TileType.Purple:
                        return "purple";
                    case TileType.White:
                        return "white";
                    case TileType.Gold:
                        return "gold";
                    case TileType.Pink:
                        return "pink";
                    case TileType.Green:
                        return "green";
                    case TileType.Cactus:
                        return "cactus";
                    case TileType.Glitch:
                        return "glitch";
                    default:
                        return "unknown";
                }
            }
            catch
            {
                return "unknown";
            }
        }

        private static string MapCurse(Tile tile, GlyphType glyph)
        {
            if (glyph == GlyphType.Blank)
                return "wildcard";

            if (glyph == GlyphType.Number)
                return "number";

            if (glyph == GlyphType.Fraction)
                return "fraction";

            if (glyph == GlyphType.Currency)
                return "currency";

            if (glyph == GlyphType.ScatteredItem)
                return "item";

            if (glyph == GlyphType.Chess || tile.IsChessPiece())
            {
                try
                {
                    switch (tile.PieceType)
                    {
                        case ChessPiece.Pawn:
                            return "chess_pawn";
                        case ChessPiece.Knight:
                            return "chess_knight";
                        case ChessPiece.Bishop:
                            return "chess_bishop";
                        case ChessPiece.Rook:
                            return "chess_rook";
                        case ChessPiece.Queen:
                            return "chess_queen";
                        case ChessPiece.King:
                            return "chess_king";
                        default:
                            return "chess_pawn";
                    }
                }
                catch
                {
                    return "chess_pawn";
                }
            }

            return "letter";
        }
    }
}
