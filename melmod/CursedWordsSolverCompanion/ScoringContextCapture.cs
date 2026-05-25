using System;
using System.Collections;
using System.Collections.Generic;
using System.Reflection;
using Newtonsoft.Json;

namespace CursedWordsSolverCompanion
{
    /// <summary>
    /// Extract scoring context from CalculateOverallScore inputs (e.g. prior words).
    /// </summary>
    public static class ScoringContextCapture
    {
        private static readonly BindingFlags MemberFlags =
            BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;

        public static Dictionary<string, string> ExtractFromPreviousWords(
            List<HistoricWord> previousWords
        )
        {
            var extras = new Dictionary<string, string>();
            var letter = FirstLetterFromHistoricWords(previousWords);
            if (!string.IsNullOrEmpty(letter))
                extras["previous_word_first_letter"] = letter;

            var letterCounts = LetterUseCountsFromPreviousWords(previousWords);
            extras["mutating_dna_letter_counts"] = JsonConvert.SerializeObject(
                letterCounts
            );

            return extras;
        }

        public static Dictionary<string, int> LetterUseCountsFromPreviousWords(
            List<HistoricWord> previousWords
        )
        {
            var counts = new Dictionary<string, int>();
            if (previousWords == null)
                return counts;

            foreach (var historic in previousWords)
            {
                if (historic == null)
                    continue;

                var fromPath = CountLettersFromHistoricPath(historic);
                if (fromPath.Count > 0)
                {
                    MergeLetterCounts(counts, fromPath);
                    continue;
                }

                var word = GetSubmittedWordString(historic);
                if (string.IsNullOrEmpty(word))
                    continue;

                foreach (var ch in word)
                {
                    if (!char.IsLetter(ch))
                        continue;
                    var key = char.ToLowerInvariant(ch).ToString();
                    IncrementCount(counts, key);
                }
            }

            return counts;
        }

        /// <summary>
        /// Prefer live Mutating DNA stamp counters; fall back to historic word/path aggregation.
        /// </summary>
        public static Dictionary<string, int> ResolveMutatingDnaLetterCounts(
            Player player,
            List<HistoricWord> previousWords
        )
        {
            var fromStamp = MutatingDnaLetterCounts.TryReadFromPlayer(player);
            if (fromStamp != null && fromStamp.Count > 0)
                return fromStamp;

            return LetterUseCountsFromPreviousWords(previousWords);
        }

        public static string SerializeLetterCounts(Dictionary<string, int> counts)
        {
            if (counts == null || counts.Count == 0)
                return "{}";
            return JsonConvert.SerializeObject(counts);
        }

        private static Dictionary<string, int> CountLettersFromHistoricPath(HistoricWord historic)
        {
            var counts = new Dictionary<string, int>();
            var selections = TryGetTileSelections(historic);
            if (selections == null || selections.Count == 0)
                return counts;

            foreach (var sel in selections)
            {
                if (sel?.SelectedTile == null)
                    continue;
                try
                {
                    var letter = sel.SelectedTile.Letter;
                    if (string.IsNullOrEmpty(letter))
                        continue;
                    var key = letter.Trim().ToLowerInvariant();
                    if (key.Length != 1 || !char.IsLetter(key[0]))
                        continue;
                    IncrementCount(counts, key);
                }
                catch
                {
                    // skip bad tile
                }
            }

            return counts;
        }

        private static List<TileSelection> TryGetTileSelections(HistoricWord historic)
        {
            if (historic == null)
                return null;

            try
            {
                var prop = historic.GetType().GetProperty(
                    "TileSelections",
                    MemberFlags
                );
                if (prop != null)
                {
                    var value = prop.GetValue(historic, null) as List<TileSelection>;
                    if (value != null && value.Count > 0)
                        return value;
                }
            }
            catch
            {
                // fall through
            }

            foreach (var name in new[] { "Selections", "Tiles", "SubmittedTiles" })
            {
                try
                {
                    var prop = historic.GetType().GetProperty(name, MemberFlags);
                    if (prop == null)
                        continue;
                    var value = prop.GetValue(historic, null) as List<TileSelection>;
                    if (value != null && value.Count > 0)
                        return value;
                }
                catch
                {
                    // try next
                }
            }

            return null;
        }

        private static void MergeLetterCounts(
            Dictionary<string, int> target,
            Dictionary<string, int> source
        )
        {
            foreach (var kv in source)
                IncrementCount(target, kv.Key, kv.Value);
        }

        private static void IncrementCount(Dictionary<string, int> counts, string key, int delta = 1)
        {
            if (string.IsNullOrEmpty(key))
                return;
            if (!counts.ContainsKey(key))
                counts[key] = 0;
            counts[key] += delta;
        }

        public static string FirstLetterFromHistoricWords(List<HistoricWord> previousWords)
        {
            if (previousWords == null || previousWords.Count == 0)
                return "";

            for (var i = previousWords.Count - 1; i >= 0; i--)
            {
                var pathCounts = CountLettersFromHistoricPath(previousWords[i]);
                if (pathCounts.Count > 0)
                {
                    foreach (var sel in TryGetTileSelections(previousWords[i]) ?? new List<TileSelection>())
                    {
                        if (sel?.SelectedTile == null)
                            continue;
                        try
                        {
                            var letter = sel.SelectedTile.Letter;
                            if (!string.IsNullOrEmpty(letter))
                            {
                                var key = letter.Trim().ToLowerInvariant();
                                if (key.Length == 1 && char.IsLetter(key[0]))
                                    return key;
                            }
                        }
                        catch
                        {
                            // try next
                        }
                    }
                }

                var word = GetSubmittedWordString(previousWords[i]);
                var letterFromWord = FirstAlphabeticLetter(word);
                if (!string.IsNullOrEmpty(letterFromWord))
                    return letterFromWord;
            }

            return "";
        }

        private static string GetSubmittedWordString(HistoricWord historic)
        {
            if (historic == null)
                return "";

            try
            {
                var method = historic.GetType().GetMethod(
                    "GetSubmittedWordString",
                    BindingFlags.Public | BindingFlags.Instance
                );
                if (method != null)
                {
                    var value = method.Invoke(historic, null) as string;
                    if (!string.IsNullOrEmpty(value))
                        return value;
                }
            }
            catch
            {
                // fall through
            }

            return TryGetStringProperty(
                historic,
                "Word",
                "SubmittedWord",
                "Text",
                "SubmittedText"
            );
        }

        private static string TryGetStringProperty(object target, params string[] names)
        {
            if (target == null)
                return "";

            foreach (var name in names)
            {
                try
                {
                    var prop = target.GetType().GetProperty(name, MemberFlags);
                    if (prop == null)
                        continue;
                    var value = prop.GetValue(target, null) as string;
                    if (!string.IsNullOrEmpty(value))
                        return value;
                }
                catch
                {
                    // try next
                }
            }

            return "";
        }

        private static string FirstAlphabeticLetter(string word)
        {
            if (string.IsNullOrEmpty(word))
                return "";

            foreach (var ch in word)
            {
                if (char.IsLetter(ch))
                    return char.ToLowerInvariant(ch).ToString();
            }

            return "";
        }

        /// <summary>
        /// ApplyPoisonEffect parity: per prior word, green_tile_count × 10% of that word's score.
        /// </summary>
        public static double ComputeGreenPoisonBonus(List<HistoricWord> previousWords)
        {
            if (previousWords == null || previousWords.Count == 0)
                return 0.0;

            double total = 0.0;
            foreach (var historic in previousWords)
            {
                if (historic == null)
                    continue;

                var greenCount = CountGreenTilesInHistoric(historic);
                if (greenCount <= 0)
                    continue;

                var wordScore = TryGetHistoricWordScore(historic);
                if (wordScore <= 0)
                    continue;

                total += greenCount * wordScore * 0.1;
            }

            return total;
        }

        private static int CountGreenTilesInHistoric(HistoricWord historic)
        {
            var count = 0;
            var selections = TryGetTileSelections(historic);
            if (selections == null)
                return 0;

            foreach (var sel in selections)
            {
                if (sel == null)
                    continue;
                try
                {
                    var tile = sel.SelectedTile;
                    if (tile != null && tile.IsTileType(TileType.Green))
                        count++;
                }
                catch
                {
                    // skip
                }
            }

            return count;
        }

        private static double TryGetHistoricWordScore(HistoricWord historic)
        {
            if (historic == null)
                return 0.0;

            foreach (var name in new[] { "Score", "WordScore", "FinalScore", "TotalScore" })
            {
                try
                {
                    var prop = historic.GetType().GetProperty(name, MemberFlags);
                    if (prop == null)
                        continue;
                    var raw = prop.GetValue(historic, null);
                    if (raw == null)
                        continue;

                    var scoreProp = raw.GetType().GetProperty("Score", MemberFlags);
                    if (scoreProp != null)
                    {
                        var val = scoreProp.GetValue(raw, null);
                        if (val is long lv)
                            return lv;
                        if (val is int iv)
                            return iv;
                        if (val is double dv)
                            return dv;
                    }

                    if (raw is long l)
                        return l;
                    if (raw is int i)
                        return i;
                    if (raw is double d)
                        return d;
                }
                catch
                {
                    // try next
                }
            }

            return 0.0;
        }

        public static void MergeExtrasIntoSnapshot(
            Dictionary<string, object> runStateSnapshot,
            Dictionary<string, string> extrasSnapshot
        )
        {
            if (runStateSnapshot == null || extrasSnapshot == null || extrasSnapshot.Count == 0)
                return;

            object extrasObj;
            if (!runStateSnapshot.TryGetValue("extras", out extrasObj) || extrasObj == null)
            {
                runStateSnapshot["extras"] = new Dictionary<string, string>(extrasSnapshot);
                return;
            }

            var merged = new Dictionary<string, string>();
            var existing = extrasObj as Dictionary<string, string>;
            if (existing != null)
            {
                foreach (var kv in existing)
                    merged[kv.Key] = kv.Value ?? "";
            }
            else if (extrasObj is Newtonsoft.Json.Linq.JObject jobj)
            {
                foreach (var prop in jobj.Properties())
                    merged[prop.Name] = prop.Value?.ToString() ?? "";
            }

            foreach (var kv in extrasSnapshot)
                merged[kv.Key] = kv.Value ?? "";

            runStateSnapshot["extras"] = merged;
        }
    }

    /// <summary>
    /// Read per-letter use counters from the equipped Mutating DNA stamp via reflection.
    /// </summary>
    internal static class MutatingDnaLetterCounts
    {
        private static readonly BindingFlags MemberFlags =
            BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;

        public static Dictionary<string, int> TryReadFromPlayer(Player player)
        {
            if (player?.Stamps == null)
                return null;

            Dictionary<string, int> best = null;
            foreach (var stamp in player.Stamps)
            {
                if (stamp == null || !LooksLikeMutatingDna(stamp))
                    continue;

                var counts = TryReadFromItem(stamp);
                if (counts == null || counts.Count == 0)
                    continue;

                if (best == null || SumCounts(counts) > SumCounts(best))
                    best = counts;
            }

            return best;
        }

        private static bool LooksLikeMutatingDna(Item item)
        {
            var name = item.Name ?? "";
            var art = item.ArtFileName ?? "";
            return name.IndexOf("Mutating", StringComparison.OrdinalIgnoreCase) >= 0
                || name.IndexOf("DNA", StringComparison.OrdinalIgnoreCase) >= 0
                || art.IndexOf("mutating", StringComparison.OrdinalIgnoreCase) >= 0
                || art.IndexOf("dna", StringComparison.OrdinalIgnoreCase) >= 0;
        }

        private static int SumCounts(Dictionary<string, int> counts)
        {
            var sum = 0;
            foreach (var kv in counts)
                sum += kv.Value;
            return sum;
        }

        private static Dictionary<string, int> TryReadFromItem(Item stamp)
        {
            var counts = TryReadDictionaryFromObject(stamp);
            if (counts != null && counts.Count > 0)
                return counts;

            foreach (var nested in TryGetNestedTargets(stamp))
            {
                counts = TryReadDictionaryFromObject(nested);
                if (counts != null && counts.Count > 0)
                    return counts;
            }

            return null;
        }

        private static IEnumerable<object> TryGetNestedTargets(Item stamp)
        {
            var seen = new HashSet<object>();
            foreach (var propName in new[]
            {
                "Stamp",
                "StampEffect",
                "Effect",
                "RuntimeData",
                "Data",
                "Component",
                "ItemEffect",
            })
            {
                object nested = null;
                try
                {
                    var prop = stamp.GetType().GetProperty(propName, MemberFlags);
                    if (prop != null)
                        nested = prop.GetValue(stamp, null);
                }
                catch
                {
                    // try next
                }

                if (nested == null || nested is string || seen.Contains(nested))
                    continue;
                seen.Add(nested);
                yield return nested;
            }
        }

        private static Dictionary<string, int> TryReadDictionaryFromObject(object target)
        {
            if (target == null)
                return null;

            foreach (var name in new[]
            {
                "LetterUseCounts",
                "LettersUsed",
                "UsedLetters",
                "LetterCounts",
                "CharacterUseCounts",
                "LetterUsageCounts",
                "UsedLetterCounts",
                "MutatingDnaLetterCounts",
            })
            {
                var counts = TryReadNamedDictionaryMember(target, name);
                if (counts != null && counts.Count > 0)
                    return counts;
            }

            return TryScanDictionaryMembers(target);
        }

        private static Dictionary<string, int> TryReadNamedDictionaryMember(
            object target,
            string memberName
        )
        {
            try
            {
                var prop = target.GetType().GetProperty(memberName, MemberFlags);
                if (prop != null)
                {
                    var counts = ParseDictionary(prop.GetValue(target, null));
                    if (counts != null && counts.Count > 0)
                        return counts;
                }

                var field = target.GetType().GetField(memberName, MemberFlags);
                if (field != null)
                {
                    var counts = ParseDictionary(field.GetValue(target));
                    if (counts != null && counts.Count > 0)
                        return counts;
                }
            }
            catch
            {
                // ignore
            }

            return null;
        }

        private static Dictionary<string, int> TryScanDictionaryMembers(object target)
        {
            var type = target.GetType();
            Dictionary<string, int> best = null;

            foreach (var prop in type.GetProperties(MemberFlags))
            {
                if (!MemberNameLooksLikeLetterCounts(prop.Name))
                    continue;
                var counts = ParseDictionary(prop.GetValue(target, null));
                if (counts == null || counts.Count == 0)
                    continue;
                if (best == null || SumCounts(counts) > SumCounts(best))
                    best = counts;
            }

            foreach (var field in type.GetFields(MemberFlags))
            {
                if (!MemberNameLooksLikeLetterCounts(field.Name))
                    continue;
                var counts = ParseDictionary(field.GetValue(target));
                if (counts == null || counts.Count == 0)
                    continue;
                if (best == null || SumCounts(counts) > SumCounts(best))
                    best = counts;
            }

            return best;
        }

        private static bool MemberNameLooksLikeLetterCounts(string name)
        {
            if (string.IsNullOrEmpty(name))
                return false;

            var lower = name.ToLowerInvariant();
            return lower.Contains("letter")
                && (lower.Contains("count") || lower.Contains("used") || lower.Contains("usage"));
        }

        private static Dictionary<string, int> ParseDictionary(object raw)
        {
            if (raw == null)
                return null;

            var dict = raw as IDictionary;
            if (dict != null)
                return ParseGenericDictionary(dict);

            if (raw is IEnumerable enumerable && !(raw is string))
            {
                var counts = new Dictionary<string, int>();
                foreach (var entry in enumerable)
                {
                    if (entry == null)
                        continue;
                    var key = TryGetStringProperty(entry, "Key", "Letter", "Character");
                    var value = TryGetIntProperty(entry, "Value", "Count", "Uses", "TimesUsed");
                    if (string.IsNullOrEmpty(key) || value < 0)
                        continue;
                    key = key.Trim().ToLowerInvariant();
                    if (key.Length != 1 || !char.IsLetter(key[0]))
                        continue;
                    counts[key] = value;
                }

                return counts.Count > 0 ? counts : null;
            }

            return null;
        }

        private static Dictionary<string, int> ParseGenericDictionary(IDictionary dict)
        {
            var counts = new Dictionary<string, int>();
            foreach (DictionaryEntry entry in dict)
            {
                var key = entry.Key as string;
                if (string.IsNullOrEmpty(key))
                    continue;
                key = key.Trim().ToLowerInvariant();
                if (key.Length != 1 || !char.IsLetter(key[0]))
                    continue;

                var value = TryReadIntLike(entry.Value);
                if (value < 0)
                    continue;
                counts[key] = value;
            }

            return counts.Count > 0 ? counts : null;
        }

        private static string TryGetStringProperty(object target, params string[] names)
        {
            if (target == null)
                return "";

            foreach (var name in names)
            {
                try
                {
                    var prop = target.GetType().GetProperty(name, MemberFlags);
                    if (prop == null)
                        continue;
                    var value = prop.GetValue(target, null) as string;
                    if (!string.IsNullOrEmpty(value))
                        return value;
                }
                catch
                {
                    // try next
                }
            }

            return "";
        }

        private static int TryGetIntProperty(object target, params string[] names)
        {
            if (target == null)
                return -1;

            foreach (var name in names)
            {
                try
                {
                    var prop = target.GetType().GetProperty(name, MemberFlags);
                    if (prop != null)
                    {
                        var value = TryReadIntLike(prop.GetValue(target, null));
                        if (value >= 0)
                            return value;
                    }

                    var field = target.GetType().GetField(name, MemberFlags);
                    if (field != null)
                    {
                        var value = TryReadIntLike(field.GetValue(target));
                        if (value >= 0)
                            return value;
                    }
                }
                catch
                {
                    // try next
                }
            }

            return -1;
        }

        private static int TryReadIntLike(object raw)
        {
            if (raw == null)
                return -1;
            if (raw is int i)
                return i;
            if (raw is long l && l >= 0 && l <= int.MaxValue)
                return (int)l;
            if (raw is float f && f >= 0 && Math.Abs(f - Math.Round(f)) < 0.001f)
                return (int)Math.Round(f);
            if (raw is double d && d >= 0 && Math.Abs(d - Math.Round(d)) < 0.001)
                return (int)Math.Round(d);
            return -1;
        }
    }
}

