using System;
using System.Collections.Generic;
using System.Reflection;
using System.Text;
using System.Text.RegularExpressions;
using Newtonsoft.Json.Linq;
using UnityEngine;

namespace CursedWordsSolverCompanion
{
    public static class BoardExporter
    {
        private const int DefaultGridSize = 5;

        private static readonly BindingFlags MemberFlags =
            BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;

        public static BoardSnapshot TryBuild(Player player)
        {
            if (player == null)
                return null;

            var grid = ResolveActiveGridData();
            if (grid == null)
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

            if (gridRows < 1 || gridRows > DefaultGridSize)
                gridRows = DefaultGridSize;
            if (gridCols < 1 || gridCols > DefaultGridSize)
                gridCols = DefaultGridSize;

            var origin = DetectPlayableOrigin(grid, gridRows, gridCols);
            var tiles = ExportTiles(grid, gridRows, gridCols, origin);
            if (tiles == null || tiles.Count != DefaultGridSize * DefaultGridSize)
                return null;

            var snapshot = new BoardSnapshot
            {
                source = "melmod",
                money = player.Money,
                rows = gridRows,
                cols = gridCols,
                playable_origin = origin,
                tiles = tiles,
            };
            FillPlayableBounds(snapshot);
            return snapshot;
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

        /// <summary>
        /// Patch F8 snapshot board tiles with submit-time capture flags from the live grid.
        /// </summary>
        public static void MergeSubmitTakeFlagsIntoRunState(
            Dictionary<string, object> runStateSnapshot,
            BoardSnapshot submitBoard
        )
        {
            if (runStateSnapshot == null || submitBoard?.tiles == null)
                return;

            var takeAt = CollectTakeFlags(submitBoard);
            if (takeAt.Count == 0)
                return;

            ApplyTakeFlagsToRunState(runStateSnapshot, takeAt);
        }

        /// <summary>
        /// Apply take flags keyed by "row,col" onto a board snapshot (during scoring).
        /// </summary>
        public static void ApplyTakeFlags(BoardSnapshot board, Dictionary<string, bool> takeAt)
        {
            if (board?.tiles == null || takeAt == null || takeAt.Count == 0)
                return;

            foreach (var tile in board.tiles)
            {
                if (tile == null)
                    continue;
                var key = tile.row + "," + tile.col;
                if (takeAt.TryGetValue(key, out var isTake) && isTake)
                    tile.take = true;
            }
        }

        /// <summary>
        /// True when the tile has a playing-card suit (Bicycle / poker scoring).
        /// </summary>
        public static bool TileHasSuitedCard(Tile tile)
        {
            return !string.IsNullOrEmpty(MapCardSuit(tile));
        }

        /// <summary>
        /// Bicycle suited credit on path: unique suits when at most one suit, else unique ranks.
        /// </summary>
        public static int CountSuitedCardsOnSelections(List<TileSelection> selections)
        {
            if (selections == null)
                return 0;

            var suitedCount = 0;
            foreach (var sel in selections)
            {
                if (sel?.SelectedTile == null)
                    continue;
                var tile = sel.SelectedTile;
                var suit = MapCardSuit(tile);
                if (string.IsNullOrEmpty(suit))
                {
                    // Bicycle counts any `CardSuit != 0` tile; jokers may not expose a suit,
                    // but still count as suited credit.
                    try
                    {
                        var glyph = tile.GetGlyphType();
                        if (!IsJokerGlyph(glyph) && !MapIsJoker(tile, glyph))
                            continue;
                    }
                    catch
                    {
                        continue;
                    }
                }
                suitedCount += 1;
            }
            return suitedCount;
        }

        /// <summary>
        /// Patch card_suit / card_rank on a board snapshot from word-path selections.
        /// </summary>
        public static void ApplyCardMetadataFromSelections(
            BoardSnapshot board,
            List<TileSelection> selections
        )
        {
            if (board?.tiles == null || selections == null)
                return;

            foreach (var sel in selections)
            {
                if (sel?.SelectedTile == null)
                    continue;

                var tile = sel.SelectedTile;
                var suit = MapCardSuit(tile);
                if (string.IsNullOrEmpty(suit))
                    continue;

                try
                {
                    var coords = tile.GetCoordinates();
                    var row = coords.y;
                    var col = coords.x;
                    var rank = MapCardRank(tile, null);
                    foreach (var snap in board.tiles)
                    {
                        if (snap == null || snap.row != row || snap.col != col)
                            continue;
                        snap.card_suit = suit;
                        if (!string.IsNullOrEmpty(rank))
                            snap.card_rank = rank;
                        else if (
                            !string.IsNullOrWhiteSpace(snap.letter)
                            && snap.letter != "?"
                        )
                            snap.card_rank = snap.letter.Trim().ToUpperInvariant();
                        break;
                    }
                }
                catch
                {
                    // skip bad tile
                }
            }
        }

        /// <summary>
        /// Merge submit-time card metadata into an F8 run_state board snapshot.
        /// </summary>
        public static void MergeSubmitCardMetadataIntoRunState(
            Dictionary<string, object> runStateSnapshot,
            BoardSnapshot submitBoard
        )
        {
            if (runStateSnapshot == null || submitBoard?.tiles == null)
                return;

            var cardAt = new Dictionary<string, BoardTileSnapshot>();
            foreach (var tile in submitBoard.tiles)
            {
                if (tile == null || string.IsNullOrEmpty(tile.card_suit))
                    continue;
                cardAt[tile.row + "," + tile.col] = tile;
            }
            if (cardAt.Count == 0)
                return;

            object boardObj;
            if (!runStateSnapshot.TryGetValue("board", out boardObj) || boardObj == null)
                return;

            var boardJson = boardObj as JObject ?? JObject.FromObject(boardObj);
            var tiles = boardJson["tiles"] as JArray;
            if (tiles == null)
                return;

            foreach (var token in tiles)
            {
                var tile = token as JObject;
                if (tile == null)
                    continue;
                var row = tile["row"]?.ToObject<int>() ?? -1;
                var col = tile["col"]?.ToObject<int>() ?? -1;
                if (row < 0 || col < 0)
                    continue;
                BoardTileSnapshot src;
                if (!cardAt.TryGetValue(row + "," + col, out src) || src == null)
                    continue;
                tile["card_suit"] = src.card_suit;
                if (!string.IsNullOrEmpty(src.card_rank))
                    tile["card_rank"] = src.card_rank;
            }

            runStateSnapshot["board"] = boardJson.ToObject<Dictionary<string, object>>();
        }

        /// <summary>
        /// Read take flags from word-path tile selections during ScoreCalculation.
        /// </summary>
        public static Dictionary<string, bool> ExtractTakeFlagsFromSelections(
            List<TileSelection> selections
        )
        {
            var takeAt = new Dictionary<string, bool>();
            if (selections == null)
                return takeAt;

            foreach (var sel in selections)
            {
                if (sel?.SelectedTile == null)
                    continue;
                var tile = sel.SelectedTile;
                if (!TileHasTake(tile))
                    continue;
                try
                {
                    var coords = tile.GetCoordinates();
                    var key = coords.y + "," + coords.x;
                    takeAt[key] = true;
                }
                catch
                {
                    // skip bad tile
                }
            }
            return takeAt;
        }

        public static bool TileHasTake(Tile tile)
        {
            return MapTake(tile);
        }

        private static Dictionary<string, bool> CollectTakeFlags(BoardSnapshot submitBoard)
        {
            var takeAt = new Dictionary<string, bool>();
            foreach (var tile in submitBoard.tiles)
            {
                if (tile == null || !tile.take)
                    continue;
                takeAt[tile.row + "," + tile.col] = true;
            }
            return takeAt;
        }

        private static void ApplyTakeFlagsToRunState(
            Dictionary<string, object> runStateSnapshot,
            Dictionary<string, bool> takeAt
        )
        {
            object boardObj;
            if (!runStateSnapshot.TryGetValue("board", out boardObj) || boardObj == null)
                return;

            var boardJson = boardObj as JObject ?? JObject.FromObject(boardObj);
            var tiles = boardJson["tiles"] as JArray;
            if (tiles == null)
                return;

            foreach (var token in tiles)
            {
                var tile = token as JObject;
                if (tile == null)
                    continue;
                var row = tile["row"]?.ToObject<int>() ?? -1;
                var col = tile["col"]?.ToObject<int>() ?? -1;
                if (row < 0 || col < 0)
                    continue;
                var key = row + "," + col;
                if (takeAt.TryGetValue(key, out var isTake) && isTake)
                    tile["take"] = true;
            }

            runStateSnapshot["board"] = boardJson.ToObject<Dictionary<string, object>>();
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

        private static string DetectPlayableOrigin(GridData grid, int gridRows, int gridCols)
        {
            if (gridRows >= DefaultGridSize && gridCols >= DefaultGridSize)
                return "full";

            var bottomCount = 0;
            var topCount = 0;
            for (var row = 0; row < DefaultGridSize; row++)
            {
                for (var col = 0; col < DefaultGridSize; col++)
                {
                    var tile = TryGetTileAt(grid, col, row);
                    if (tile == null || IsSkippedTile(tile))
                        continue;
                    if (IsPlayableBottomLeft(row, col, gridRows, gridCols))
                        bottomCount++;
                    if (IsPlayableTopLeft(row, col, gridRows, gridCols))
                        topCount++;
                }
            }

            if (topCount > bottomCount)
                return "top_left";
            if (bottomCount > 0)
                return "bottom_left";
            return "top_left";
        }

        private static bool IsPlayableBottomLeft(int row, int col, int gridRows, int gridCols)
        {
            return row < gridRows && col < gridCols;
        }

        private static bool IsPlayableTopLeft(int row, int col, int gridRows, int gridCols)
        {
            return row >= DefaultGridSize - gridRows && col < gridCols;
        }

        private static bool IsPlayableSlot(
            int row,
            int col,
            int gridRows,
            int gridCols,
            string origin
        )
        {
            if (gridRows >= DefaultGridSize && gridCols >= DefaultGridSize)
                return true;
            switch (origin)
            {
                case "top_left":
                    return IsPlayableTopLeft(row, col, gridRows, gridCols);
                case "center":
                {
                    var rowStart = (DefaultGridSize - gridRows) / 2;
                    var colStart = (DefaultGridSize - gridCols) / 2;
                    return row >= rowStart
                        && row < rowStart + gridRows
                        && col >= colStart
                        && col < colStart + gridCols;
                }
                case "full":
                    return true;
                default:
                    return IsPlayableBottomLeft(row, col, gridRows, gridCols);
            }
        }

        private static Tile TryGetTileAt(GridData grid, int col, int row)
        {
            if (grid == null)
                return null;
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

            return tile;
        }

        private static void FillPlayableBounds(BoardSnapshot snapshot)
        {
            var minR = DefaultGridSize;
            var maxR = -1;
            var minC = DefaultGridSize;
            var maxC = -1;
            if (snapshot.tiles == null)
                return;

            foreach (var t in snapshot.tiles)
            {
                if (t == null || !t.active)
                    continue;
                if (t.row < minR)
                    minR = t.row;
                if (t.row > maxR)
                    maxR = t.row;
                if (t.col < minC)
                    minC = t.col;
                if (t.col > maxC)
                    maxC = t.col;
            }

            if (maxR < 0)
                return;

            snapshot.playable_min_row = minR;
            snapshot.playable_max_row = maxR;
            snapshot.playable_min_col = minC;
            snapshot.playable_max_col = maxC;
        }

        private static List<BoardTileSnapshot> ExportTiles(
            GridData grid,
            int gridRows,
            int gridCols,
            string origin
        )
        {
            var result = new List<BoardTileSnapshot>(DefaultGridSize * DefaultGridSize);

            for (var row = 0; row < DefaultGridSize; row++)
            {
                for (var col = 0; col < DefaultGridSize; col++)
                {
                    var displayRow = DefaultGridSize - 1 - row;
                    var inPlayable = IsPlayableSlot(row, col, gridRows, gridCols, origin);

                    if (!inPlayable)
                    {
                        result.Add(InactiveTileSnapshot(displayRow, col));
                        continue;
                    }

                    var tile = TryGetTileAt(grid, col, row);

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
            var baseScore = MapBaseScore(tile, color, curse);

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
                was_consumable = MapWasConsumable(tile),
                take = MapTake(tile),
            };

            var isJoker = MapIsJoker(tile, glyph);
            if (isJoker)
            {
                snap.is_joker = true;
                snap.curse = "wildcard";
                snap.letter = "?";
            }

            var cardSuit = MapCardSuit(tile);
            if (cardSuit == "joker")
            {
                // Void letter tiles can mis-read as Joker suit; game uses CardSuit == 0 for Hanafuda unused.
                var spuriousVoidLetterJoker =
                    curse == "letter" && color == "void" && !isJoker;
                if (!spuriousVoidLetterJoker)
                {
                    snap.is_joker = true;
                    snap.card_suit = "joker";
                    if (string.IsNullOrEmpty(snap.card_rank))
                        snap.card_rank = MapCardRank(tile, letter);
                }
            }
            else if (!string.IsNullOrEmpty(cardSuit))
            {
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

            if (curse.StartsWith("chess_"))
            {
                var chessColor = MapChessColor(tile);
                if (!string.IsNullOrEmpty(chessColor))
                    snap.chess_color = chessColor;
            }

            if (curse == "item")
            {
                try
                {
                    var scattered = tile.ScatteredItem;
                    if (scattered != null)
                    {
                        var art = scattered.ArtFileName ?? scattered.Name ?? "";
                        if (!string.IsNullOrWhiteSpace(art))
                            snap.scattered_item_id = RunStateExporter.Slugify(
                                scattered.ArtFileName,
                                scattered.Name
                            );
                        var scatteredLevel = RunStateExporter.GetUpgradeableLevel(scattered);
                        if (scatteredLevel >= 1)
                            snap.scattered_item_level = scatteredLevel;
                    }
                }
                catch
                {
                    // optional field
                }
            }

            try
            {
                if (tile.WasGlitchTile)
                    snap.was_glitch = true;
            }
            catch
            {
                // optional
            }

            if (color == "cactus")
            {
                try
                {
                    var growth = tile.CactusGrowth;
                    if (growth != null)
                        snap.cactus_growth = (int)Math.Max(0, growth.Score);
                }
                catch
                {
                    snap.cactus_growth = 1;
                }
            }

            var voidSteps = MapVoidPenaltySteps(tile, curse, color, letter);
            if (voidSteps.HasValue)
                snap.void_penalty_steps = voidSteps.Value;

            return snap;
        }

        private static int? MapVoidPenaltySteps(
            Tile tile,
            string curse,
            string color,
            string letter
        )
        {
            if (color != "void" || curse != "letter")
                return null;

            var face = ScrabbleFaceValue(letter);

            foreach (var name in new[]
            {
                "VoidPenaltySteps",
                "VoidGridNumber",
                "GridNumberWhenScattered",
                "GridWhenScattered",
                "CreatedGridNumber",
                "SpawnGridNumber",
                "GridIndexAtSpawn",
                "GridsGeneratedWhenScattered",
                "VoidGeneration",
            })
            {
                var n = TryReadIntMember(tile, name);
                if (n >= 1)
                    return Math.Max(1, n);
            }

            try
            {
                var packet = tile.GetValue();
                if (packet != null)
                {
                    var score = TryReadIntMember(packet, "Score");
                    if (score > face)
                    {
                        var steps = (score - face + 9) / 10;
                        if (steps >= 1)
                            return steps;
                    }
                }
            }
            catch
            {
                // optional
            }

            return null;
        }

        private static int ScrabbleFaceValue(string letter)
        {
            if (string.IsNullOrWhiteSpace(letter))
                return 1;
            var ch = char.ToUpperInvariant(letter.Trim()[0]);
            switch (ch)
            {
                case 'A':
                case 'E':
                case 'I':
                case 'O':
                case 'U':
                case 'L':
                case 'N':
                case 'S':
                case 'T':
                case 'R':
                    return 1;
                case 'D':
                case 'G':
                    return 2;
                case 'B':
                case 'C':
                case 'M':
                case 'P':
                    return 3;
                case 'F':
                case 'H':
                case 'V':
                case 'W':
                case 'Y':
                    return 4;
                case 'K':
                    return 5;
                case 'J':
                case 'X':
                    return 8;
                case 'Q':
                case 'Z':
                    return 10;
                default:
                    return 1;
            }
        }

        private static int TryReadIntMember(object obj, string name)
        {
            if (obj == null || string.IsNullOrEmpty(name))
                return -1;
            try
            {
                var prop = obj.GetType().GetProperty(name, MemberFlags);
                if (prop == null)
                    return -1;
                return TryCoerceInt(prop.GetValue(obj, null));
            }
            catch
            {
                return -1;
            }
        }

        private static int TryCoerceInt(object raw)
        {
            if (raw == null)
                return -1;
            if (raw is int i)
                return i;
            if (raw is long l)
                return (int)l;
            if (raw is float f)
                return (int)f;
            if (raw is double d)
                return (int)d;
            int parsed;
            if (int.TryParse(raw.ToString(), out parsed))
                return parsed;
            return -1;
        }

        private static string MapDisplay(Tile tile, string letter)
        {
            try
            {
                var s = tile.GetStringRepresentation();
                if (!string.IsNullOrWhiteSpace(s))
                    return StripRichText(s);
            }
            catch
            {
                // fall through
            }

            try
            {
                var s = tile.GetValueForDisplay();
                if (!string.IsNullOrWhiteSpace(s))
                    return StripRichText(s);
            }
            catch
            {
                // fall through
            }

            return letter ?? "?";
        }

        private static string StripRichText(string s)
        {
            if (string.IsNullOrEmpty(s))
                return s;
            var trimmed = s.Trim();
            var match = Regex.Match(
                trimmed,
                @"<font[^>]*>(.*?)</font>",
                RegexOptions.IgnoreCase | RegexOptions.Singleline
            );
            if (match.Success)
                return match.Groups[1].Value.Trim();
            return trimmed;
        }

        private static string MapLetter(Tile tile, GlyphType glyph, string curse)
        {
            if (IsJokerGlyph(glyph) || MapIsJoker(tile, glyph))
                return "?";

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
                        return StripRichText(sym);
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

        private static double MapBaseScore(Tile tile, string color, string curse)
        {
            try
            {
                var packet = tile.GetValue();
                if (packet != null)
                {
                    // VOID letters keep signed packet.Score for void_penalty_steps inference.
                    if (color == "void" && curse == "letter")
                        return packet.Score;
                    // Keep full packet.Score (can exceed 10 after colour/manipulator bonuses).
                    return Math.Max(0, packet.Score);
                }
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

        private static bool MapWasConsumable(Tile tile)
        {
            if (tile == null)
                return false;

            try
            {
                var field = tile.GetType().GetField("WasConsumable", MemberFlags);
                if (field != null && field.FieldType == typeof(bool))
                    return (bool)field.GetValue(tile);
            }
            catch
            {
                // fall through
            }

            return false;
        }

        /// <summary>Export a single tile (e.g. consumable rack slot).</summary>
        public static BoardTileSnapshot ExportTileAt(Tile tile, int row, int col)
        {
            if (tile == null)
                return null;
            return MapTile(tile, row, col);
        }

        private static string MapCardSuit(Tile tile)
        {
            if (tile == null)
                return "";

            var fromPacket = TryMapCardSuitFromPacket(tile);
            if (!string.IsNullOrEmpty(fromPacket))
                return fromPacket;

            foreach (var methodName in new[]
            {
                "GetCardSuit",
                "GetPlayingCardSuit",
                "GetSuit",
            })
            {
                try
                {
                    var method = tile.GetType().GetMethod(methodName, MemberFlags);
                    if (method == null || method.GetParameters().Length != 0)
                        continue;
                    var val = method.Invoke(tile, null);
                    if (val == null)
                        continue;
                    var normalized = NormalizeCardSuit(val.ToString());
                    if (!string.IsNullOrEmpty(normalized))
                        return normalized;
                }
                catch
                {
                    // try next
                }
            }

            foreach (var name in new[]
            {
                "Suit",
                "CardSuit",
                "PlayingCardSuit",
                "PlayingCard",
                "Card",
                "PlayingCardData",
                "card",
                "playingCard",
            })
            {
                try
                {
                    var prop = tile.GetType().GetProperty(name, MemberFlags);
                    if (prop == null)
                        continue;
                    var val = prop.GetValue(tile, null);
                    var nested = ReadSuitFromObject(val);
                    if (!string.IsNullOrEmpty(nested))
                        return nested;
                }
                catch
                {
                    // try next
                }
            }

            foreach (var name in new[] { "HasSuit", "HasPlayingCardSuit", "IsSuited" })
            {
                try
                {
                    var prop = tile.GetType().GetProperty(name, MemberFlags);
                    if (prop == null || prop.PropertyType != typeof(bool))
                        continue;
                    if (!(bool)prop.GetValue(tile, null))
                        continue;
                    var suit = MapCardSuitFromFields(tile);
                    if (!string.IsNullOrEmpty(suit))
                        return suit;
                }
                catch
                {
                    // try next
                }
            }

            var fromFields = MapCardSuitFromFields(tile);
            if (!string.IsNullOrEmpty(fromFields))
                return fromFields;

            return TryMapCardSuitFromDisplay(tile);
        }

        private static string TryMapCardSuitFromPacket(Tile tile)
        {
            try
            {
                var packet = tile.GetValue();
                return ReadSuitFromObject(packet);
            }
            catch
            {
                return "";
            }
        }

        private static string ReadSuitFromObject(object obj)
        {
            if (obj == null)
                return "";

            if (obj is string s)
            {
                var direct = NormalizeCardSuit(s);
                if (!string.IsNullOrEmpty(direct))
                    return direct;
            }

            var asText = obj.ToString();
            var fromText = NormalizeCardSuit(asText);
            if (!string.IsNullOrEmpty(fromText))
                return fromText;

            if (obj.GetType().IsEnum)
            {
                fromText = NormalizeCardSuit(asText);
                if (!string.IsNullOrEmpty(fromText))
                    return fromText;
            }

            foreach (var name in new[]
            {
                "Suit",
                "CardSuit",
                "PlayingCardSuit",
                "PlayingCard",
                "suit",
                "cardSuit",
            })
            {
                try
                {
                    var prop = obj.GetType().GetProperty(name, MemberFlags);
                    if (prop == null)
                        continue;
                    var val = prop.GetValue(obj, null);
                    var nested = ReadSuitFromObject(val);
                    if (!string.IsNullOrEmpty(nested))
                        return nested;
                }
                catch
                {
                    // try next
                }

                try
                {
                    var field = obj.GetType().GetField(name, MemberFlags);
                    if (field == null)
                        continue;
                    var val = field.GetValue(obj);
                    var nested = ReadSuitFromObject(val);
                    if (!string.IsNullOrEmpty(nested))
                        return nested;
                }
                catch
                {
                    // try next
                }
            }

            return "";
        }

        private static string TryMapCardSuitFromDisplay(Tile tile)
        {
            foreach (var raw in new[] { MapDisplay(tile, ""), TryGetTileDisplayString(tile) })
            {
                if (string.IsNullOrWhiteSpace(raw))
                    continue;
                var suit = NormalizeCardSuitFromDisplay(raw);
                if (!string.IsNullOrEmpty(suit))
                    return suit;
            }
            return "";
        }

        private static string TryGetTileDisplayString(Tile tile)
        {
            if (tile == null)
                return "";
            try
            {
                var s = tile.GetStringRepresentation();
                if (!string.IsNullOrWhiteSpace(s))
                    return StripRichText(s);
            }
            catch
            {
                // fall through
            }
            return "";
        }

        private static string NormalizeCardSuitFromDisplay(string raw)
        {
            if (string.IsNullOrWhiteSpace(raw))
                return "";
            if (raw.IndexOf('♥') >= 0 || raw.IndexOf('♡') >= 0)
                return "hearts";
            if (raw.IndexOf('♠') >= 0)
                return "spades";
            if (raw.IndexOf('♣') >= 0)
                return "clubs";
            if (raw.IndexOf('♦') >= 0 || raw.IndexOf('♢') >= 0)
                return "diamonds";
            return NormalizeCardSuit(raw);
        }

        private static string MapCardSuitFromFields(Tile tile)
        {
            foreach (var name in new[]
            {
                "suit",
                "cardSuit",
                "playingCardSuit",
            })
            {
                try
                {
                    var field = tile.GetType().GetField(
                        name,
                        System.Reflection.BindingFlags.Public
                            | System.Reflection.BindingFlags.NonPublic
                            | System.Reflection.BindingFlags.Instance
                    );
                    if (field == null)
                        continue;
                    var val = field.GetValue(tile);
                    if (val == null)
                        continue;
                    var normalized = NormalizeCardSuit(val.ToString());
                    if (!string.IsNullOrEmpty(normalized))
                        return normalized;
                }
                catch
                {
                    // try next
                }
            }

            return "";
        }

        private static string NormalizeCardSuit(string raw)
        {
            if (string.IsNullOrWhiteSpace(raw))
                return "";
            var s = raw.Trim().ToLowerInvariant();
            if (s.Contains("club"))
                return "clubs";
            if (s.Contains("spade"))
                return "spades";
            if (s.Contains("heart"))
                return "hearts";
            if (s.Contains("diamond"))
                return "diamonds";
            if (s == "c" || s == "♣")
                return "clubs";
            if (s == "s" || s == "♠")
                return "spades";
            if (s == "h" || s == "♥")
                return "hearts";
            if (s == "d" || s == "♦")
                return "diamonds";
            if (s.Contains("joker"))
                return "joker";
            return "";
        }

        private static bool MapIsJoker(Tile tile, GlyphType glyph)
        {
            if (IsJokerGlyph(glyph))
                return true;
            if (tile != null && DisplayContainsJokerGlyph(MapDisplay(tile, "")))
                return true;
            if (tile == null)
                return false;

            foreach (var name in new[]
            {
                "IsJoker",
                "IsJokerTile",
                "IsPlayingCardJoker",
            })
            {
                try
                {
                    var prop = tile.GetType().GetProperty(
                        name,
                        System.Reflection.BindingFlags.Public
                            | System.Reflection.BindingFlags.Instance
                    );
                    if (prop == null || prop.PropertyType != typeof(bool))
                        continue;
                    if ((bool)prop.GetValue(tile, null))
                        return true;
                }
                catch
                {
                    // try next
                }
            }

            return false;
        }

        private static bool IsJokerGlyph(GlyphType glyph)
        {
            try
            {
                if (glyph.ToString().Equals("Joker", StringComparison.OrdinalIgnoreCase))
                    return true;
            }
            catch
            {
                // fall through
            }

            try
            {
                return Enum.IsDefined(typeof(GlyphType), "Joker")
                    && (GlyphType)Enum.Parse(typeof(GlyphType), "Joker") == glyph;
            }
            catch
            {
                return false;
            }
        }

        private static bool DisplayContainsJokerGlyph(string display)
        {
            if (string.IsNullOrEmpty(display))
                return false;
            return display.IndexOf('\uD83C') >= 0 && display.IndexOf('\uDCCF') >= 0
                || display.IndexOf("🃏", StringComparison.Ordinal) >= 0;
        }

        private static string MapCardRank(Tile tile, string letter)
        {
            if (tile == null)
                return "";

            foreach (var methodName in new[] { "GetCardRank", "GetPlayingCardRank", "GetRank" })
            {
                try
                {
                    var method = tile.GetType().GetMethod(methodName, MemberFlags);
                    if (method == null || method.GetParameters().Length != 0)
                        continue;
                    var val = method.Invoke(tile, null);
                    if (val == null)
                        continue;
                    var rank = val.ToString().Trim().ToUpperInvariant();
                    if (!string.IsNullOrEmpty(rank))
                        return rank;
                }
                catch
                {
                    // try next
                }
            }

            foreach (var name in new[]
            {
                "Rank",
                "CardRank",
                "PlayingCardRank",
                "PlayingCard",
                "Card",
            })
            {
                try
                {
                    var prop = tile.GetType().GetProperty(name, MemberFlags);
                    if (prop == null)
                        continue;
                    var val = prop.GetValue(tile, null);
                    if (val == null)
                        continue;
                    if (val is string rankStr && !string.IsNullOrWhiteSpace(rankStr))
                        return rankStr.Trim().ToUpperInvariant();
                    var rankProp = val.GetType().GetProperty("Rank", MemberFlags);
                    if (rankProp != null)
                    {
                        var nested = rankProp.GetValue(val, null);
                        if (nested != null)
                        {
                            var nestedRank = nested.ToString().Trim().ToUpperInvariant();
                            if (!string.IsNullOrEmpty(nestedRank))
                                return nestedRank;
                        }
                    }
                    var asRank = val.ToString().Trim().ToUpperInvariant();
                    if (!string.IsNullOrEmpty(asRank) && asRank.Length <= 2)
                        return asRank;
                }
                catch
                {
                    // try next
                }
            }

            try
            {
                var packet = tile.GetValue();
                if (packet != null)
                {
                    foreach (var name in new[] { "Rank", "CardRank", "PlayingCardRank" })
                    {
                        var prop = packet.GetType().GetProperty(name, MemberFlags);
                        if (prop == null)
                            continue;
                        var val = prop.GetValue(packet, null);
                        if (val == null)
                            continue;
                        var rank = val.ToString().Trim().ToUpperInvariant();
                        if (!string.IsNullOrEmpty(rank))
                            return rank;
                    }
                }
            }
            catch
            {
                // fall through
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

        private static string MapChessColor(Tile tile)
        {
            if (tile == null)
                return "";

            // Game API: SetChessPiece(piece, isWhite); Tile.IsWhitePiece is the source of truth.
            try
            {
                if (tile.IsChessPiece())
                    return tile.IsWhitePiece ? "white" : "black";
            }
            catch
            {
                // fall through to reflection
            }

            var fromTile = MapChessColorFromReflect(tile);
            if (!string.IsNullOrEmpty(fromTile))
                return fromTile;

            try
            {
                var packet = tile.GetValue();
                if (packet != null)
                {
                    var fromPacket = MapChessColorFromReflect(packet);
                    if (!string.IsNullOrEmpty(fromPacket))
                        return fromPacket;
                }
            }
            catch
            {
                // fall through
            }

            try
            {
                if (tile.IsChessPiece())
                {
                    var fromMethods = MapChessColorFromTileMethods(tile);
                    if (!string.IsNullOrEmpty(fromMethods))
                        return fromMethods;
                }
            }
            catch
            {
                // fall through
            }

            return "";
        }

        /// <summary>
        /// Game Tile API helpers (IsBlackChessPiece / IsWhiteChessPiece). Never infer white from false.
        /// </summary>
        private static string MapChessColorFromTileMethods(Tile tile)
        {
            if (tile == null)
                return "";

            var tileType = tile.GetType();

            foreach (var name in new[] { "IsBlackChessPiece", "IsFilledChessPiece" })
            {
                var method = tileType.GetMethod(name, MemberFlags);
                if (method != null && method.ReturnType == typeof(bool))
                {
                    try
                    {
                        if ((bool)method.Invoke(tile, null))
                            return "black";
                    }
                    catch
                    {
                        // try next
                    }
                }
            }

            foreach (var name in new[] { "IsWhiteChessPiece", "IsOutlinedChessPiece" })
            {
                var method = tileType.GetMethod(name, MemberFlags);
                if (method != null && method.ReturnType == typeof(bool))
                {
                    try
                    {
                        if ((bool)method.Invoke(tile, null))
                            return "white";
                    }
                    catch
                    {
                        // try next
                    }
                }
            }

            var isWhiteField = tileType.GetField("IsWhitePiece", MemberFlags);
            if (isWhiteField != null && isWhiteField.FieldType == typeof(bool))
            {
                try
                {
                    return (bool)isWhiteField.GetValue(tile) ? "white" : "black";
                }
                catch
                {
                    // fall through
                }
            }

            return "";
        }

        private static string MapChessColorFromReflect(object obj)
        {
            if (obj == null)
                return "";

            foreach (var name in new[]
            {
                "ChessColor",
                "PieceColor",
                "ChessPieceColor",
                "chessColor",
                "pieceColor",
            })
            {
                var mapped = TryReadChessColorMember(obj, name, isField: false);
                if (!string.IsNullOrEmpty(mapped))
                    return mapped;
                mapped = TryReadChessColorMember(obj, name, isField: true);
                if (!string.IsNullOrEmpty(mapped))
                    return mapped;
            }

            foreach (var name in new[]
            {
                "IsBlackPiece",
                "IsBlack",
                "IsFilled",
                "IsFilledIn",
                "isBlack",
                "isFilled",
                "_isBlack",
                "_isBlackChessPiece",
            })
            {
                var black = TryReadChessBoolMember(obj, name);
                if (black == true)
                    return "black";
            }

            foreach (var name in new[]
            {
                "IsWhite",
                "IsOutlined",
                "IsOutline",
                "isWhite",
                "isOutlined",
                "_isWhite",
            })
            {
                var white = TryReadChessBoolMember(obj, name);
                if (white == true)
                    return "white";
            }

            return MapChessColorFromMemberScan(obj);
        }

        private static string TryReadChessColorMember(object obj, string name, bool isField)
        {
            try
            {
                var type = obj.GetType();
                object val = null;
                if (isField)
                {
                    var field = type.GetField(name, MemberFlags);
                    if (field != null)
                        val = field.GetValue(obj);
                }
                else
                {
                    var prop = type.GetProperty(name, MemberFlags);
                    if (prop != null)
                        val = prop.GetValue(obj, null);
                }

                if (val == null)
                    return "";
                if (val is bool b)
                    return MapChessColorBoolFromMemberName(name, b);
                return MapChessColorToken(val);
            }
            catch
            {
                return "";
            }
        }

        private static bool? TryReadChessBoolMember(object obj, string name)
        {
            try
            {
                var type = obj.GetType();
                var prop = type.GetProperty(name, MemberFlags);
                if (prop != null && prop.PropertyType == typeof(bool))
                    return (bool)prop.GetValue(obj, null);

                var field = type.GetField(name, MemberFlags);
                if (field != null && field.FieldType == typeof(bool))
                    return (bool)field.GetValue(obj);
            }
            catch
            {
                // fall through
            }

            return null;
        }

        private static string MapChessColorToken(object val)
        {
            if (val == null)
                return "";

            if (val is bool)
                return "";

            var name = val.ToString().Trim();
            if (string.IsNullOrEmpty(name))
                return "";

            var lower = name.ToLowerInvariant();
            if (lower.Contains("white") || lower.Contains("outline"))
                return "white";
            if (lower.Contains("black") || lower.Contains("filled"))
                return "black";
            return "";
        }

        private static string MapChessColorBoolFromMemberName(string memberName, bool value)
        {
            if (!value || string.IsNullOrEmpty(memberName))
                return "";

            var lower = memberName.ToLowerInvariant();
            if (lower.Contains("white") || lower.Contains("outline"))
                return "white";
            if (lower.Contains("black") || lower.Contains("filled"))
                return "black";
            return "";
        }

        private static string MapChessColorFromMemberScan(object obj)
        {
            if (obj == null)
                return "";

            var type = obj.GetType();
            foreach (var prop in type.GetProperties(MemberFlags))
            {
                if (!MemberNameLooksLikeChessColor(prop.Name))
                    continue;
                try
                {
                    var val = prop.GetValue(obj, null);
                    if (val == null)
                        continue;
                    var mapped = val is bool b
                        ? MapChessColorBoolFromMemberName(prop.Name, b)
                        : MapChessColorToken(val);
                    if (!string.IsNullOrEmpty(mapped))
                        return mapped;
                }
                catch
                {
                    // try next
                }
            }

            foreach (var field in type.GetFields(MemberFlags))
            {
                if (!MemberNameLooksLikeChessColor(field.Name))
                    continue;
                try
                {
                    var val = field.GetValue(obj);
                    if (val == null)
                        continue;
                    var mapped = val is bool b
                        ? MapChessColorBoolFromMemberName(field.Name, b)
                        : MapChessColorToken(val);
                    if (!string.IsNullOrEmpty(mapped))
                        return mapped;
                }
                catch
                {
                    // try next
                }
            }

            return "";
        }

        private static bool MemberNameLooksLikeChessColor(string name)
        {
            if (string.IsNullOrEmpty(name))
                return false;

            var lower = name.ToLowerInvariant();
            return lower.Contains("chess")
                || lower.Contains("piececolor")
                || lower.Contains("isblack")
                || lower.Contains("iswhite")
                || lower.Contains("isfilled")
                || lower.Contains("isoutline");
        }

        private static string MapCurse(Tile tile, GlyphType glyph)
        {
            if (IsJokerGlyph(glyph) || MapIsJoker(tile, glyph))
                return "wildcard";

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

            if (glyph == GlyphType.Arrow)
                return "arrow";

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
