using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;

namespace CursedWordsSolverCompanion
{
    /// <summary>
    /// Raw dump of the game objects the solver's engine reads (``game_state``).
    ///
    /// Everything is exported as the game holds it -- tile glyph / type / letter /
    /// number / suit / piece / value, every item's components and fields, boss
    /// modifiers and challenge with their fields, previous words with their tiles,
    /// the encounter counters, consumable rack and the Vocabulary accumulator words
    /// -- so the solver never has to reconstruct or rewind anything. Round logs take
    /// this snapshot in the SubmitWord prefix, i.e. exactly the state the word is
    /// scored against.
    ///
    /// Every read is guarded: a failing field is skipped, never thrown into the game.
    /// </summary>
    internal static class GameStateSerializer
    {
        public const string Schema = "game_state/1";

        private const BindingFlags InstanceFields =
            BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;

        private const int MaxCollection = 256;

        public static Dictionary<string, object> Capture(string trigger)
        {
            var state = new Dictionary<string, object>
            {
                ["schema"] = Schema,
                ["captured_at"] = DateTime.UtcNow.ToString("o"),
                ["trigger"] = trigger ?? "",
                ["companion_version"] = BuildInfo.Version,
            };
            Player player = null;
            try
            {
                player = GameStatics.GetPlayer();
            }
            catch
            {
                // no player (menus)
            }
            var encounter = BossResolver.TryGetEncounter();
            Guard(state, "grid", () => DescribeGrid(encounter));
            Guard(state, "encounter", () => DescribeEncounter(encounter));
            Guard(state, "player", () => DescribePlayer(player));
            Guard(state, "run", () => DescribeRun(player));
            return state;
        }

        private static void Guard(Dictionary<string, object> target, string key, Func<object> build)
        {
            try
            {
                var value = build();
                if (value != null)
                    target[key] = value;
            }
            catch (Exception ex)
            {
                target[key + "_error"] = ex.GetType().Name + ": " + ex.Message;
            }
        }

        // ------------------------------------------------------------------ grid

        private static object DescribeGrid(EncounterController encounter)
        {
            if (encounter == null)
                return null;
            var grid = GetField(encounter, "_gridData") as GridData;
            if (grid == null)
                return null;
            var dims = grid.GetDimensions();
            var available = new HashSet<Tile>(grid.GetAvailableTiles() ?? new List<Tile>());
            var tiles = new List<object>();
            foreach (var tile in grid.GetTiles() ?? new Tile[0])
            {
                if (tile == null)
                    continue;
                var d = DescribeTile(tile);
                d["available"] = available.Contains(tile);
                tiles.Add(d);
            }
            return new Dictionary<string, object>
            {
                ["width"] = dims.x,
                ["height"] = dims.y,
                ["grid_number"] = grid.GridNumber,
                ["tiles"] = tiles,
            };
        }

        /// <summary>One tile as the game holds it (game coordinates: y = 0 is the bottom row).</summary>
        public static Dictionary<string, object> DescribeTile(Tile tile)
        {
            var d = new Dictionary<string, object>();
            Try(() =>
            {
                var c = tile.GetCoordinates();
                d["x"] = c.x;
                d["y"] = c.y;
            });
            Try(() => d["glyph"] = tile.GetGlyphType().ToString());
            Try(() => d["type"] = tile.GetTileType().ToString());
            Try(() => d["letter"] = tile.Letter);
            Try(() => d["number"] = tile.Number);
            Try(() => d["fraction"] = tile.FractionNumbers != null ? tile.FractionNumbers.ToList() : null);
            Try(() => d["suit"] = tile.GetSuit().ToString());
            Try(() => d["piece"] = tile.PieceType.ToString());
            Try(() => d["white"] = tile.IsWhitePiece);
            Try(() => d["value"] = Packet(tile.GetValue()));
            Try(() => d["value_modifier"] = Packet(tile.ValueModifier));
            Try(() => d["cactus_growth"] = Packet(tile.CactusGrowth));
            Try(() => d["srep"] = tile.GetStringRepresentation());
            Try(() => d["srep_word"] = tile.GetStringRepresentation(true));
            Try(() => d["cursed"] = tile.IsCursed());
            Try(() =>
            {
                var flags = new List<string>();
                if (tile.IsEmptyTile) flags.Add("empty");
                if (tile.WasConsumable) flags.Add("was_consumable");
                if (tile.HasBeenDestroyed) flags.Add("destroyed");
                if (tile.IsCrossedOut) flags.Add("crossed_out");
                if (tile.IsInTheVoid) flags.Add("in_void");
                if (tile.Gone) flags.Add("gone");
                if (tile.IsInverted) flags.Add("inverted");
                if (tile.WasGlitchTile) flags.Add("was_glitch");
                if (tile.IsSandyBossTile) flags.Add("sandy");
                if (tile.IsNumberGoUpMiddleTile) flags.Add("number_go_up_middle");
                if (tile.SafeFromDestruction) flags.Add("safe_from_destruction");
                if (tile.AlreadyOnTileRack) flags.Add("on_rack");
                d["flags"] = flags;
            });
            Try(() =>
            {
                if (tile.ScatteredItem != null)
                    d["item"] = ItemStateExporter.Describe(tile.ScatteredItem, 0);
            });
            return d;
        }

        // ------------------------------------------------------------------ encounter

        private static object DescribeEncounter(EncounterController encounter)
        {
            if (encounter == null)
                return null;
            var d = new Dictionary<string, object>();
            Try(() => d["grids_generated"] = encounter.CurrentGridsGenerated());
            Try(() => d["total_target"] = Packet(GetField(encounter, "_totalTarget") as ScorePacket));
            Try(() => d["remaining_target"] = Packet(GetField(encounter, "_remainingTarget") as ScorePacket));
            Try(() => d["remaining_grids"] = GetField(encounter, "_remainingGrids"));
            Try(() => d["total_grids"] = GetField(encounter, "_totalGridsPerRound"));
            Try(() => d["rerolls"] = GetField(encounter, "_rerollsForEncounter"));
            Try(() => d["piggy_bank_savings"] = GetField(encounter, "_piggyBankSavings"));
            Try(() => d["twinkle_toes_swap_available"] = encounter.TwinkleToesSwapAvailable);
            Try(() => d["thread_stage"] = GetField(encounter, "_encounterThreadStage")?.ToString());
            Try(() =>
            {
                var bosses = new List<object>();
                if (GetField(encounter, "_bossModifiers") is IList list)
                    foreach (var boss in list)
                        if (boss is BossModifier mod)
                            bosses.Add(DescribeObject(mod, typeof(BossModifier)));
                d["bosses"] = bosses;
            });
            Try(() =>
            {
                var words = new List<object>();
                if (GetField(encounter, "_previousWords") is IList list)
                    foreach (var entry in list)
                        if (entry is HistoricWord word)
                            words.Add(DescribeHistoricWord(word));
                d["previous_words"] = words;
            });
            return d;
        }

        private static Dictionary<string, object> DescribeHistoricWord(HistoricWord word)
        {
            var d = new Dictionary<string, object>();
            Try(() => d["words"] = word.Words != null ? word.Words.ToList() : new List<string>());
            Try(() => d["skipped"] = word.IsWordSkipped);
            Try(() => d["score"] = Packet(word.Score));
            Try(() => d["remainder"] = Packet(word.Remainder));
            Try(() => d["round"] = word.SubmittedRound);
            Try(() => d["dims"] = new List<int> { word.GridDimensions.x, word.GridDimensions.y });
            Try(() =>
            {
                var tiles = new List<object>();
                foreach (var tile in word.Tiles ?? new List<Tile>())
                    tiles.Add(tile != null ? DescribeTile(tile) : null);
                d["tiles"] = tiles;
            });
            Try(() =>
            {
                var methods = new List<string>();
                foreach (var sel in word.TileSelections ?? new List<TileSelection>())
                    methods.Add(sel?.SelectionMethod.ToString() ?? "");
                d["methods"] = methods;
            });
            Try(() => d["wobbly"] = word.Wobbly != null ? word.Wobbly.ToList() : null);
            return d;
        }

        // ------------------------------------------------------------------ player / run

        private static object DescribePlayer(Player player)
        {
            if (player == null)
                return null;
            var d = new Dictionary<string, object>();
            Try(() => d["money"] = player.Money);
            Try(() => d["character"] = player.MyCharacter?.GetType().Name);
            Try(() =>
            {
                foreach (var kv in ItemStateExporter.BuildItemStates(player))
                    d[kv.Key] = kv.Value; // stickers / stamps (5 slots each) / pin
            });
            Try(() =>
            {
                var rack = new List<object>();
                foreach (var tile in player.ConsumableTiles ?? new Tile[0])
                    rack.Add(tile != null ? DescribeTile(tile) : null);
                d["consumables"] = rack;
            });
            Try(() =>
            {
                // InventoryCache: words Vocabulary accepts before the dictionary.
                var cache = new InventoryCache(new List<Tile>());
                d["accumulator_words"] = cache.PertinentAccumulatorWords?.ToList() ?? new List<string>();
                d["accumulator_pairs"] = cache.PertinentAccumulatorPairs?.Select(p => (object)p.ToList()).ToList()
                    ?? new List<object>();
            });
            return d;
        }

        private static object DescribeRun(Player player)
        {
            var progress = player?.CurrentRunProgress;
            if (progress == null)
                return null;
            var d = new Dictionary<string, object>();
            Try(() => d["stage"] = progress.CurrentStage);
            Try(() => d["node_type"] = progress.CurrentNodeType.ToString());
            Try(() => d["ascension"] = progress.Ascension.ToString());
            Try(() => d["cactus_growth_level"] = progress.CactusGrowthLevel);
            Try(() => d["cursed_bosses_defeated"] = progress.CursedBossesDefeated?.ToList() ?? new List<int>());
            Try(() => d["available_colours"] = progress.AvailableColours?.Select(c => c.ToString()).ToList());
            Try(() => d["embargoed_items"] = progress.EmbargoedItemTypes?.Select(t => t.Name).ToList());
            Try(() =>
            {
                if (progress.Challenge != null)
                    d["challenge"] = DescribeObject(progress.Challenge, typeof(ChallengeRun));
            });
            return d;
        }

        // ------------------------------------------------------------------ helpers

        /// <summary>Class name plus every plain-data field of ``obj`` up to (not including) ``stopAt``'s base.</summary>
        private static Dictionary<string, object> DescribeObject(object obj, Type stopAt)
        {
            var d = new Dictionary<string, object> { ["class"] = obj.GetType().Name };
            var fields = new Dictionary<string, object>();
            var type = obj.GetType();
            while (type != null && type != typeof(object) && type != stopAt.BaseType)
            {
                foreach (var field in type.GetFields(InstanceFields))
                {
                    if (fields.ContainsKey(field.Name))
                        continue;
                    object value;
                    try
                    {
                        value = field.GetValue(obj);
                    }
                    catch
                    {
                        continue;
                    }
                    var exported = Plain(value, 0);
                    if (exported != null)
                        fields[field.Name] = exported;
                }
                type = type.BaseType;
            }
            d["fields"] = fields;
            return d;
        }

        /// <summary>Primitive / enum / packet / vector / item / tile / plain collections; null for anything else.</summary>
        private static object Plain(object value, int depth)
        {
            switch (value)
            {
                case null:
                    return null;
                case int _:
                case long _:
                case bool _:
                case string _:
                case double _:
                    return value;
                case float f:
                    return (double)f;
                case Enum e:
                    return e.ToString();
                case ScorePacket packet:
                    return Packet(packet);
                case UnityEngine.Vector2Int v:
                    return new List<int> { v.x, v.y };
                case Type t:
                    return t.Name;
                case UnityEngine.Object _:
                    return null;
                case Item item:
                    return depth < 2 ? ItemStateExporter.Describe(item, 1) : null;
                case Tile tile:
                    return depth < 2 ? DescribeTile(tile) : null;
            }
            if (depth >= 2)
                return null;
            if (value is IDictionary dict)
            {
                var outDict = new Dictionary<string, object>();
                foreach (DictionaryEntry entry in dict)
                {
                    if (outDict.Count >= MaxCollection)
                        break;
                    var v = Plain(entry.Value, depth + 1);
                    if (entry.Key != null && v != null)
                        outDict[Plain(entry.Key, depth + 1)?.ToString() ?? entry.Key.ToString()] = v;
                }
                return outDict;
            }
            if (value is IEnumerable seq && !(value is Array arr && arr.Rank != 1))
            {
                var outList = new List<object>();
                foreach (var entry in seq)
                {
                    if (outList.Count >= MaxCollection)
                        break;
                    outList.Add(Plain(entry, depth + 1));
                }
                return outList;
            }
            return null;
        }

        /// <summary>ScorePacket as a JSON number, or "inf" / "-inf".</summary>
        public static object Packet(ScorePacket packet)
        {
            if (packet == null)
                return null;
            if (packet.IsInfinite)
                return packet.IsNegative ? "-inf" : "inf";
            return packet.Score;
        }

        private static object GetField(object obj, string name)
        {
            var type = obj.GetType();
            while (type != null)
            {
                var field = type.GetField(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
                if (field != null)
                    return field.GetValue(obj);
                type = type.BaseType;
            }
            return null;
        }

        private static void Try(Action action)
        {
            try
            {
                action();
            }
            catch
            {
                // field unavailable in this game version / scene
            }
        }
    }
}
