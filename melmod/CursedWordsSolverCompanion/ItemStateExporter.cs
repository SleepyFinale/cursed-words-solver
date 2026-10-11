using System;
using System.Collections;
using System.Collections.Generic;
using System.Reflection;

namespace CursedWordsSolverCompanion
{
    /// <summary>
    /// Exact live item state for the solver's game-port scoring engine.
    ///
    /// Exports every inventory slot (empty slots as null, so positional items such as
    /// Overhand / Arrivals / Departures keep their slot), the pin, and each item's
    /// UpgradeableComponents (Level + VariableValue — not TimesUpgraded, which
    /// Item.Upgrade never bumps), RelevantColours, and the item's own counter fields
    /// (Ruler.Distance, Neapolitan.MulticolouredWordsSubmitted, EightBall._selectedPiece,
    /// Dartboard._targetNumber, CrystalBall.ChosenCurseType, BirthdayCake float bonus...).
    /// RAM memory, Frankenstein stitches and the Snapshot copy are exported as nested items.
    /// </summary>
    internal static class ItemStateExporter
    {
        private const BindingFlags InstanceFields =
            BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly;

        public static Dictionary<string, object> BuildItemStates(Player player)
        {
            var result = new Dictionary<string, object>();
            if (player == null)
                return result;
            result["stickers"] = DescribeSlots(player.Stickers);
            result["stamps"] = DescribeSlots(player.Stamps);
            try
            {
                var pin = player.MyCharacter?.GetCharacterItem();
                if (pin != null)
                    result["pin"] = Describe(pin, 0);
            }
            catch
            {
                // optional
            }
            return result;
        }

        private static List<object> DescribeSlots(Item[] slots)
        {
            var list = new List<object>();
            if (slots == null)
                return list;
            for (var i = 0; i < slots.Length; i++)
            {
                var item = slots[i];
                if (item == null)
                {
                    list.Add(null);
                    continue;
                }
                var described = Describe(item, 0);
                described["slot"] = i;
                list.Add(described);
            }
            return list;
        }

        public static Dictionary<string, object> Describe(Item item, int depth)
        {
            var d = new Dictionary<string, object>
            {
                ["id"] = RunStateExporter.Slugify(item.ArtFileName, item.Name),
                ["class"] = item.GetType().Name,
            };
            var levels = new List<int>();
            var values = new List<int>();
            if (item.UpgradeableComponents != null)
            {
                foreach (var component in item.UpgradeableComponents)
                {
                    levels.Add(component?.Level ?? 1);
                    values.Add(component?.VariableValue ?? 0);
                }
            }
            d["levels"] = levels;
            d["values"] = values;
            if (item.RelevantColours != null)
            {
                var colours = new List<string>();
                foreach (var colour in item.RelevantColours)
                    colours.Add(colour.ToString());
                d["colours"] = colours;
            }
            d["fields"] = DescribeFields(item);
            if (depth < 2)
            {
                var nested = new List<object>();
                if (item is RandomAccessMemory ram && ram.ItemsInMemory != null)
                {
                    foreach (var inner in ram.ItemsInMemory)
                        if (inner != null)
                            nested.Add(Describe(inner, depth + 1));
                }
                else if (item is Frankenstein frank && frank.StitchedItems != null)
                {
                    foreach (var inner in frank.StitchedItems)
                        if (inner != null)
                            nested.Add(Describe(inner, depth + 1));
                }
                else if (item is Snapshot snap && snap.SnapshottedItem != null)
                {
                    nested.Add(Describe(snap.SnapshottedItem, depth + 1));
                }
                if (nested.Count > 0)
                    d["nested"] = nested;
            }
            return d;
        }

        /// <summary>Primitive / enum / small collection fields declared on the item's own class chain.</summary>
        private static Dictionary<string, object> DescribeFields(Item item)
        {
            var fields = new Dictionary<string, object>();
            var type = item.GetType();
            while (type != null && type != typeof(Item) && type != typeof(object))
            {
                foreach (var field in type.GetFields(InstanceFields))
                {
                    if (fields.ContainsKey(field.Name))
                        continue;
                    object value;
                    try
                    {
                        value = field.GetValue(item);
                    }
                    catch
                    {
                        continue;
                    }
                    var exported = ExportValue(value);
                    if (exported != null)
                        fields[field.Name] = exported;
                }
                type = type.BaseType;
            }
            return fields;
        }

        private static object ExportValue(object value)
        {
            if (value == null)
                return null;
            switch (value)
            {
                case int _:
                case long _:
                case bool _:
                case string _:
                    return value;
                case float f:
                    return (double)f;
                case double _:
                    return value;
                case Enum e:
                    return e.ToString();
                case ScorePacket packet:
                    return packet.IsInfinite ? (object)(packet.IsNegative ? "-inf" : "inf") : packet.Score;
            }
            if (value is IDictionary dict)
            {
                var outDict = new Dictionary<string, object>();
                foreach (DictionaryEntry entry in dict)
                {
                    var v = ExportValue(entry.Value);
                    if (entry.Key != null && v != null && !(v is Dictionary<string, object>) && !(v is List<object>))
                        outDict[entry.Key.ToString()] = v;
                    if (outDict.Count > 64)
                        break;
                }
                return outDict;
            }
            if (value is IList list && !(value is Array arr && arr.Rank != 1))
            {
                var outList = new List<object>();
                foreach (var entry in list)
                {
                    var v = ExportValue(entry);
                    if (v == null || v is Dictionary<string, object> || v is List<object>)
                        continue;
                    outList.Add(v);
                    if (outList.Count > 64)
                        break;
                }
                return outList;
            }
            return null;
        }

        /// <summary>Signed Tile.GetValue() plus raw glyph / type / suit for exact replay.</summary>
        public static void FillExactTileFields(Tile tile, BoardTileSnapshot snap)
        {
            if (tile == null || snap == null)
                return;
            try
            {
                var packet = tile.GetValue();
                if (packet != null && !packet.IsInfinite)
                {
                    snap.value_exact = packet.Score;
                    snap.base_score = packet.Score;
                }
            }
            catch
            {
                // optional
            }
            try
            {
                snap.value_modifier = tile.ValueModifier != null && !tile.ValueModifier.IsInfinite
                    ? tile.ValueModifier.Score
                    : (long?)null;
                snap.glyph = tile.GetGlyphType().ToString();
                snap.tile_type = tile.GetTileType().ToString();
                snap.suit = tile.GetSuit().ToString();
                if (tile.GetGlyphType() == GlyphType.ScatteredItem && tile.ScatteredItem != null)
                {
                    snap.scattered_item_state = Describe(tile.ScatteredItem, 0);
                    var components = tile.ScatteredItem.UpgradeableComponents;
                    if (components != null && components.Count > 0)
                        snap.scattered_item_level = components[0].Level;
                }
            }
            catch
            {
                // optional
            }
        }
    }
}
