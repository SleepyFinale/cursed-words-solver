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

            var gridRows = DefaultGridSize;
            var gridCols = DefaultGridSize;
            try
            {
                var dims = grid.Dimensions;
                // Unity Vector2Int: x = width (cols), y = height (rows).
                if (dims.y > 0)
                    gridRows = dims.y;
                if (dims.x > 0)
                    gridCols = dims.x;
            }
            catch
            {
                // keep defaults
            }

            return new BoardSnapshot
            {
                source = "melmod",
                money = player.Money,
                rows = gridRows,
                cols = gridCols,
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
            var gridRows = DefaultGridSize;
            var gridCols = DefaultGridSize;

            try
            {
                var dims = grid.Dimensions;
                // Unity Vector2Int: x = width (cols), y = height (rows).
                if (dims.y > 0)
                    gridRows = dims.y;
                if (dims.x > 0)
                    gridCols = dims.x;
            }
            catch
            {
                // keep 5x5
            }

            if (gridRows < 1 || gridRows > DefaultGridSize)
                gridRows = DefaultGridSize;
            if (gridCols < 1 || gridCols > DefaultGridSize)
                gridCols = DefaultGridSize;

            for (var row = 0; row < DefaultGridSize; row++)
            {
                for (var col = 0; col < DefaultGridSize; col++)
                {
                    var displayRow = DefaultGridSize - 1 - row;
                    var inPlayable =
                        row < gridRows && col < gridCols;

                    if (!inPlayable)
                    {
                        result.Add(InactiveTileSnapshot(displayRow, col));
                        continue;
                    }

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
                    {
                        result.Add(InactiveTileSnapshot(displayRow, col));
                        continue;
                    }

                    result.Add(MapTile(tile, displayRow, col));
                }
            }

            return result;
        }

        private static BoardTileSnapshot InactiveTileSnapshot(int row, int col)
        {
            return new BoardTileSnapshot
            {
                row = row,
                col = col,
                char_display = "",
                letter = "",
                base_score = 0,
                color = "colorless",
                curse = "inactive",
                active = false,
            };
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
            var color = MapColor(tile, glyph);
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
                consumable = MapConsumable(tile),
                take = MapTake(tile),
            };

            var cardSuit = MapCardSuit(tile);
            if (!string.IsNullOrEmpty(cardSuit))
            {
                snap.curse = "card";
                snap.card_suit = cardSuit;
                snap.card_rank = MapCardRank(tile, letter);
            }

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

        private static double MapBaseScore(Tile tile)
        {
            try
            {
                var packet = tile.GetValue();
                if (packet != null)
                    // Keep full packet.Score (can exceed 10 after colour/manipulator bonuses).
                    return Math.Max(0, packet.Score);
            }
            catch
            {
                // fall through
            }

            return 0;
        }

        private static string MapColor(Tile tile, GlyphType glyph)
        {
            if (glyph == GlyphType.Number || glyph == GlyphType.Fraction)
            {
                var fromPacket = TryMapColorFromPacket(tile);
                if (!string.IsNullOrEmpty(fromPacket))
                    return fromPacket;
            }

            return MapColorFromTileType(tile);
        }

        private static string TryMapColorFromPacket(Tile tile)
        {
            try
            {
                var packet = tile.GetValue();
                if (packet == null)
                    return null;

                var fromPacket = MapColorFromReflect(packet);
                if (!string.IsNullOrEmpty(fromPacket))
                    return fromPacket;
            }
            catch
            {
                // fall through
            }

            return null;
        }

        private static string MapColorFromReflect(object obj)
        {
            if (obj == null)
                return null;

            foreach (var name in new[]
            {
                "TileType",
                "Type",
                "tileType",
                "Color",
                "Colour",
                "TileColor",
                "DisplayTileType",
            })
            {
                try
                {
                    var prop = obj.GetType().GetProperty(
                        name,
                        System.Reflection.BindingFlags.Public
                            | System.Reflection.BindingFlags.Instance
                    );
                    if (prop == null)
                        continue;
                    var val = prop.GetValue(obj, null);
                    if (val == null)
                        continue;
                    var mapped = MapColorToken(val);
                    if (!string.IsNullOrEmpty(mapped))
                        return mapped;
                }
                catch
                {
                    // try next
                }
            }

            return null;
        }

        private static string MapColorToken(object val)
        {
            if (val is TileType tt)
                return MapTileTypeEnum(tt);

            var name = val.ToString().Trim();
            if (string.IsNullOrEmpty(name))
                return null;

            if (name.Equals("Normal", StringComparison.OrdinalIgnoreCase))
                return "colorless";

            return MapTileTypeName(name);
        }

        private static string MapTileTypeName(string name)
        {
            switch (name.Trim().ToLowerInvariant())
            {
                case "normal":
                case "colorless":
                    return "colorless";
                case "red":
                    return "red";
                case "blue":
                    return "blue";
                case "shiny":
                    return "shiny";
                case "void":
                    return "void";
                case "purple":
                    return "purple";
                case "white":
                    return "white";
                case "gold":
                    return "gold";
                case "pink":
                    return "pink";
                case "green":
                    return "green";
                case "cactus":
                    return "cactus";
                case "glitch":
                    return "glitch";
                default:
                    return null;
            }
        }

        private static string MapTileTypeEnum(TileType tt)
        {
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

        private static string MapColorFromTileType(Tile tile)
        {
            try
            {
                return MapTileTypeEnum(tile.GetTileType());
            }
            catch
            {
                return "unknown";
            }
        }

        private static bool MapConsumable(Tile tile)
        {
            if (tile == null)
                return false;

            try
            {
                var prop = tile.GetType().GetProperty(
                    "IsConsumable",
                    System.Reflection.BindingFlags.Public
                        | System.Reflection.BindingFlags.Instance
                );
                if (prop != null && prop.PropertyType == typeof(bool))
                    return (bool)prop.GetValue(tile, null);
            }
            catch
            {
                // fall through
            }

            try
            {
                var prop = tile.GetType().GetProperty(
                    "Consumable",
                    System.Reflection.BindingFlags.Public
                        | System.Reflection.BindingFlags.Instance
                );
                if (prop != null && prop.PropertyType == typeof(bool))
                    return (bool)prop.GetValue(tile, null);
            }
            catch
            {
                // fall through
            }

            return false;
        }

        private static string MapCardSuit(Tile tile)
        {
            if (tile == null)
                return "";

            foreach (var name in new[]
            {
                "Suit",
                "CardSuit",
                "PlayingCardSuit",
            })
            {
                try
                {
                    var prop = tile.GetType().GetProperty(
                        name,
                        System.Reflection.BindingFlags.Public
                            | System.Reflection.BindingFlags.Instance
                    );
                    if (prop == null)
                        continue;
                    var val = prop.GetValue(tile, null);
                    if (val == null)
                        continue;
                    return val.ToString().Trim().ToLowerInvariant();
                }
                catch
                {
                    // try next
                }
            }

            return "";
        }

        private static string MapCardRank(Tile tile, string letter)
        {
            if (tile == null)
                return "";

            foreach (var name in new[] { "Rank", "CardRank", "PlayingCardRank" })
            {
                try
                {
                    var prop = tile.GetType().GetProperty(
                        name,
                        System.Reflection.BindingFlags.Public
                            | System.Reflection.BindingFlags.Instance
                    );
                    if (prop == null)
                        continue;
                    var val = prop.GetValue(tile, null);
                    if (val == null)
                        continue;
                    return val.ToString().Trim().ToUpperInvariant();
                }
                catch
                {
                    // try next
                }
            }

            if (!string.IsNullOrWhiteSpace(letter) && letter != "?")
                return letter.Trim().ToUpperInvariant();

            return "";
        }

        private static bool MapTake(Tile tile)
        {
            if (tile == null)
                return false;

            foreach (var name in new[]
            {
                "IsTake",
                "DidCapture",
                "IsCapture",
                "Take",
                "WasCaptured",
                "IsTakeLanding",
            })
            {
                try
                {
                    var prop = tile.GetType().GetProperty(
                        name,
                        System.Reflection.BindingFlags.Public
                            | System.Reflection.BindingFlags.Instance
                    );
                    if (prop != null && prop.PropertyType == typeof(bool))
                        return (bool)prop.GetValue(tile, null);
                }
                catch
                {
                    // try next
                }
            }

            return false;
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

            if (IsCardGlyph(glyph) || TryIsPlayingCard(tile))
                return "card";

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

        private static bool IsCardGlyph(GlyphType glyph)
        {
            try
            {
                if (glyph.ToString().Equals("Card", StringComparison.OrdinalIgnoreCase))
                    return true;
            }
            catch
            {
                // fall through
            }

            try
            {
                return Enum.IsDefined(typeof(GlyphType), "Card")
                    && (GlyphType)Enum.Parse(typeof(GlyphType), "Card") == glyph;
            }
            catch
            {
                return false;
            }
        }

        private static bool TryIsPlayingCard(Tile tile)
        {
            if (tile == null)
                return false;

            foreach (var name in new[] { "IsPlayingCard", "IsCard", "IsPlayingCardTile" })
            {
                try
                {
                    var method = tile.GetType().GetMethod(
                        name,
                        System.Reflection.BindingFlags.Public
                            | System.Reflection.BindingFlags.Instance
                    );
                    if (method != null && method.ReturnType == typeof(bool))
                        return (bool)method.Invoke(tile, null);
                }
                catch
                {
                    // try next
                }
            }

            try
            {
                var prop = tile.GetType().GetProperty(
                    "IsPlayingCard",
                    System.Reflection.BindingFlags.Public
                        | System.Reflection.BindingFlags.Instance
                );
                if (prop != null && prop.PropertyType == typeof(bool))
                    return (bool)prop.GetValue(tile, null);
            }
            catch
            {
                // fall through
            }

            return false;
        }
    }
}
