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
        private static readonly Dictionary<string, string> CurrencyMap =
            new Dictionary<string, string>(StringComparer.Ordinal)
            {
                { "฿", "B" },
                { "¥", "Y" },
                { "$", "S" },
                { "₡", "C" },
                { "€", "E" },
                { "₭", "K" },
                { "₮", "T" },
                { "₦", "N" },
                { "₩", "W" },
                { "₱", "P" },
                { "₣", "F" },
                { "₲", "G" },
            };

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
                ApplyMutatingDnaHistoricWord(counts, historic);
            }

            return counts;
        }

        /// <summary>
        /// Mirror MutatingDNA.ApplyTileBonus key updates for one historic submit.
        /// </summary>
        private static void ApplyMutatingDnaHistoricWord(
            Dictionary<string, int> counts,
            HistoricWord historic
        )
        {
            var selections = TryGetTileSelections(historic);
            if (selections == null || selections.Count == 0)
                return;

            foreach (var sel in selections)
            {
                if (sel?.SelectedTile == null)
                    continue;
                try
                {
                    var key = TileMutatingDnaKey(sel.SelectedTile);
                    if (string.IsNullOrEmpty(key))
                        continue;
                    ApplyMutatingDnaKeyUpdate(counts, key);
                }
                catch
                {
                    // skip bad tile
                }
            }
        }

        /// <summary>
        /// Same state transition as MutatingDNA.ApplyTileBonus (count only, no score).
        /// </summary>
        internal static void ApplyMutatingDnaKeyUpdate(
            Dictionary<string, int> counts,
            string key
        )
        {
            if (string.IsNullOrEmpty(key))
                return;
            if (counts.ContainsKey(key))
                counts[key]++;
            else
                counts[key] = 1;
        }

        /// <summary>
        /// Tile.GetStringRepresentation() parity for Mutating DNA keys.
        /// </summary>
        internal static string TileMutatingDnaKey(Tile tile)
        {
            if (tile == null)
                return "";

            try
            {
                var method = tile.GetType().GetMethod(
                    "GetStringRepresentation",
                    MemberFlags,
                    null,
                    new[] { typeof(bool) },
                    null
                );
                if (method != null)
                {
                    var raw = method.Invoke(tile, new object[] { false }) as string;
                    if (!string.IsNullOrWhiteSpace(raw))
                        return raw.Trim();
                }

                method = tile.GetType().GetMethod(
                    "GetStringRepresentation",
                    MemberFlags,
                    null,
                    Type.EmptyTypes,
                    null
                );
                if (method != null)
                {
                    var raw = method.Invoke(tile, null) as string;
                    if (!string.IsNullOrWhiteSpace(raw))
                        return raw.Trim();
                }
            }
            catch
            {
                // fall through
            }

            try
            {
                if (tile.IsNumber())
                {
                    var num = tile.GetNumber();
                    return num.ToString();
                }
            }
            catch
            {
                // fall through
            }

            try
            {
                var letter = tile.Letter;
                if (!string.IsNullOrWhiteSpace(letter))
                {
                    var key = letter.Trim().ToLowerInvariant();
                    if (key.Length == 1 && char.IsLetter(key[0]))
                        return key;
                }
            }
            catch
            {
                // ignore
            }

            return "";
        }

        /// <summary>
        /// Prefer live Mutating DNA stamp counters; fall back to historic word/path aggregation.
        /// </summary>
        public static Dictionary<string, int> ResolveMutatingDnaLetterCounts(
            Player player,
            List<HistoricWord> previousWords
        )
        {
            var fromHistoric = LetterUseCountsFromPreviousWords(previousWords);
            var fromStamp = MutatingDnaLetterCounts.TryReadFromPlayer(player);

            Dictionary<string, int> result;
            if (fromStamp != null && fromStamp.Count > 0)
                result = fromStamp;
            else if (fromHistoric != null && fromHistoric.Count > 0)
                result = fromHistoric;
            else
                result = fromStamp ?? fromHistoric ?? new Dictionary<string, int>();

            if (
                MutatingDnaLetterCounts.PlayerHasMutatingDnaStamp(player)
                && result.Count == 0
            )
            {
                var liveN = fromStamp?.Count ?? 0;
                var histN = fromHistoric?.Count ?? 0;
                CompanionDiagnostics.LogVerbose(
                    "Mutating DNA stamp equipped but LetterUseCounts export empty (live="
                        + liveN
                        + " historic="
                        + histN
                        + " keys)"
                );
            }

            return result;
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
                var letter = FirstLetterFromHistoricWord(previousWords[i]);
                if (!string.IsNullOrEmpty(letter))
                    return letter;
            }

            return "";
        }

        /// <summary>
        /// Path-first parity with FirstLetterFromSubmittedWord / solver _effective_word_start_letter.
        /// </summary>
        internal static string FirstLetterFromHistoricWord(HistoricWord historic)
        {
            if (historic == null)
                return "";

            var path = TryGetPathFromHistoric(historic);
            var word = GetSubmittedWordString(historic);
            var wordFirst = FirstAlphabeticLetter(word);
            var currencyWordFirst = TryCurrencyWordFirstLetter(path, historic, wordFirst);
            if (!string.IsNullOrEmpty(currencyWordFirst))
                return currencyWordFirst;

            var pathFirst = FirstLetterOnHistoricPath(historic);
            if (
                !string.IsNullOrEmpty(pathFirst)
                && !string.IsNullOrEmpty(wordFirst)
                && pathFirst != wordFirst
            )
                return pathFirst;
            return !string.IsNullOrEmpty(wordFirst) ? wordFirst : pathFirst;
        }

        private static List<int> TryGetPathFromHistoric(HistoricWord historic)
        {
            var path = new List<int>();
            var selections = TryGetTileSelections(historic);
            if (selections == null)
                return path;

            foreach (var sel in selections)
            {
                if (sel?.SelectedTile == null)
                    continue;
                try
                {
                    var coords = sel.SelectedTile.GetCoordinates();
                    path.Add(coords.y * 5 + coords.x);
                }
                catch
                {
                    // skip bad tile
                }
            }

            return path;
        }

        private static string FirstLetterOnHistoricPath(HistoricWord historic)
        {
            var path = TryGetPathFromHistoric(historic);
            if (path.Count == 0)
                return "";

            var selections = TryGetTileSelections(historic);
            if (selections == null)
                return "";

            const int cols = 5;
            foreach (var idx in path)
            {
                if (idx < 0)
                    continue;
                var row = idx / cols;
                var col = idx % cols;
                foreach (var sel in selections)
                {
                    if (sel?.SelectedTile == null)
                        continue;
                    try
                    {
                        var coords = sel.SelectedTile.GetCoordinates();
                        if (coords.y != row || coords.x != col)
                            continue;
                        var letter = sel.SelectedTile.Letter;
                        if (string.IsNullOrEmpty(letter))
                            continue;
                        var key = letter.Trim().ToLowerInvariant();
                        if (key.Length == 1 && char.IsLetter(key[0]))
                            return key;
                    }
                    catch
                    {
                        // try next selection
                    }
                }
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
                        return RunStateExportFill.StripHistoricWordRichText(value);
                }
            }
            catch
            {
                // fall through
            }

            return RunStateExportFill.StripHistoricWordRichText(
                TryGetStringProperty(
                    historic,
                    "Word",
                    "SubmittedWord",
                    "Text",
                    "SubmittedText"
                )
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
            word = RunStateExportFill.StripHistoricWordRichText(word);
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
        /// First letter of the word just submitted — becomes previous_word_first_letter for the next F8.
        /// Path-first when currency/symbol leads the path (Bento/Chips parity with solver).
        /// </summary>
        public static string FirstLetterFromSubmittedWord(
            string word,
            List<int> path,
            BoardSnapshot board
        )
        {
            var pathFirst = FirstLetterOnBoardPath(path, board);
            var wordFirst = FirstAlphabeticLetter(word);
            var currencyWordFirst = TryCurrencyWordFirstLetter(path, board, wordFirst);
            if (!string.IsNullOrEmpty(currencyWordFirst))
                return currencyWordFirst;
            if (
                !string.IsNullOrEmpty(pathFirst)
                && !string.IsNullOrEmpty(wordFirst)
                && pathFirst != wordFirst
            )
                return pathFirst;
            return !string.IsNullOrEmpty(wordFirst) ? wordFirst : pathFirst;
        }

        /// <summary>
        /// When a currency tile leads the path and maps to the dictionary word's first letter,
        /// the game uses word-first (boluses-style), not the next path letter.
        /// </summary>
        private static string TryCurrencyWordFirstLetter(
            List<int> path,
            BoardSnapshot board,
            string wordFirst
        )
        {
            if (path == null || path.Count == 0 || board?.tiles == null)
                return "";
            if (string.IsNullOrEmpty(wordFirst))
                return "";

            const int cols = 5;
            var idx = path[0];
            if (idx < 0)
                return "";
            var row = idx / cols;
            var col = idx % cols;
            foreach (var tile in board.tiles)
            {
                if (tile == null || tile.row != row || tile.col != col)
                    continue;
                if (!string.Equals(tile.curse, "currency", StringComparison.OrdinalIgnoreCase))
                    return "";
                var raw = (tile.letter ?? tile.char_display ?? "").Trim();
                string mapped;
                if (!CurrencyMap.TryGetValue(raw, out mapped))
                    return "";
                if (string.Equals(mapped, wordFirst, StringComparison.OrdinalIgnoreCase))
                    return wordFirst;
                return "";
            }

            return "";
        }

        private static string TryCurrencyWordFirstLetter(
            List<int> path,
            HistoricWord historic,
            string wordFirst
        )
        {
            if (path == null || path.Count == 0 || historic == null)
                return "";
            if (string.IsNullOrEmpty(wordFirst))
                return "";

            var selections = TryGetTileSelections(historic);
            if (selections == null)
                return "";

            const int cols = 5;
            var idx = path[0];
            if (idx < 0)
                return "";
            var row = idx / cols;
            var col = idx % cols;
            foreach (var sel in selections)
            {
                if (sel?.SelectedTile == null)
                    continue;
                try
                {
                    var coords = sel.SelectedTile.GetCoordinates();
                    if (coords.y != row || coords.x != col)
                        continue;
                    var raw = (sel.SelectedTile.Letter ?? "").Trim();
                    string mapped;
                    if (!CurrencyMap.TryGetValue(raw, out mapped))
                        return "";
                    if (string.Equals(mapped, wordFirst, StringComparison.OrdinalIgnoreCase))
                        return wordFirst;
                    return "";
                }
                catch
                {
                    // try next selection
                }
            }

            return "";
        }

        private static string FirstLetterOnBoardPath(List<int> path, BoardSnapshot board)
        {
            if (path == null || board?.tiles == null)
                return "";

            const int cols = 5;
            foreach (var idx in path)
            {
                if (idx < 0)
                    continue;
                var row = idx / cols;
                var col = idx % cols;
                foreach (var tile in board.tiles)
                {
                    if (tile == null || tile.row != row || tile.col != col)
                        continue;
                    var ch = (tile.letter ?? tile.char_display ?? "").Trim().ToLowerInvariant();
                    if (ch.Length == 1 && char.IsLetter(ch[0]))
                        return ch;
                }
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

            foreach (var stamp in player.Stamps)
            {
                if (stamp == null || !LooksLikeMutatingDna(stamp))
                    continue;

                var counts = TryReadFromItem(stamp, allowEmpty: true);
                if (counts != null)
                    return counts;
            }

            return null;
        }

        public static bool PlayerHasMutatingDnaStamp(Player player)
        {
            if (player?.Stamps == null)
                return false;

            foreach (var stamp in player.Stamps)
            {
                if (stamp != null && LooksLikeMutatingDna(stamp))
                    return true;
            }

            return false;
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

        private static Dictionary<string, int> TryReadFromItem(Item stamp, bool allowEmpty = false)
        {
            Dictionary<string, int> counts;
            var foundEmpty = false;
            bool parseFailed;

            counts = TryReadDictionaryFromObject(stamp, allowEmpty, out foundEmpty, out parseFailed);
            if (counts != null && (allowEmpty || counts.Count > 0))
                return counts;
            if (parseFailed)
            {
                CompanionDiagnostics.LogVerboseWarning(
                    "Mutating DNA LetterUseCounts on stamp had entries but none parsed as valid keys"
                );
            }

            foreach (var nested in TryGetNestedTargets(stamp))
            {
                bool nestedEmpty;
                counts = TryReadDictionaryFromObject(
                    nested,
                    allowEmpty,
                    out nestedEmpty,
                    out parseFailed
                );
                if (nestedEmpty)
                    foundEmpty = true;
                if (counts != null && (allowEmpty || counts.Count > 0))
                    return counts;
                if (parseFailed)
                {
                    CompanionDiagnostics.LogVerboseWarning(
                        "Mutating DNA LetterUseCounts on nested stamp object had entries but none parsed"
                    );
                }
            }

            if (allowEmpty && foundEmpty)
                return new Dictionary<string, int>();

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

        private static Dictionary<string, int> TryReadDictionaryFromObject(
            object target,
            bool allowEmpty,
            out bool foundEmptyMember,
            out bool parseFailedWithEntries
        )
        {
            foundEmptyMember = false;
            parseFailedWithEntries = false;
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
                var counts = TryReadNamedDictionaryMember(
                    target,
                    name,
                    allowEmpty,
                    out foundEmptyMember,
                    out parseFailedWithEntries
                );
                if (counts != null && (allowEmpty || counts.Count > 0))
                    return counts;
                if (foundEmptyMember || parseFailedWithEntries)
                    return counts;
            }

            return TryScanDictionaryMembers(
                target,
                allowEmpty,
                out foundEmptyMember,
                out parseFailedWithEntries
            );
        }

        private static Dictionary<string, int> TryReadDictionaryFromObject(
            object target,
            bool allowEmpty = false
        )
        {
            bool foundEmpty;
            bool parseFailed;
            return TryReadDictionaryFromObject(target, allowEmpty, out foundEmpty, out parseFailed);
        }

        private static Dictionary<string, int> TryReadNamedDictionaryMember(
            object target,
            string memberName,
            bool allowEmpty,
            out bool foundEmptyMember,
            out bool parseFailedWithEntries
        )
        {
            foundEmptyMember = false;
            parseFailedWithEntries = false;
            try
            {
                var prop = target.GetType().GetProperty(memberName, MemberFlags);
                if (prop != null)
                {
                    return ParseDictionaryMemberValue(
                        prop.GetValue(target, null),
                        allowEmpty,
                        out foundEmptyMember,
                        out parseFailedWithEntries
                    );
                }

                var field = target.GetType().GetField(memberName, MemberFlags);
                if (field != null)
                {
                    return ParseDictionaryMemberValue(
                        field.GetValue(target),
                        allowEmpty,
                        out foundEmptyMember,
                        out parseFailedWithEntries
                    );
                }
            }
            catch
            {
                // ignore
            }

            return null;
        }

        private static Dictionary<string, int> TryReadNamedDictionaryMember(
            object target,
            string memberName,
            bool allowEmpty = false
        )
        {
            bool foundEmpty;
            bool parseFailed;
            return TryReadNamedDictionaryMember(
                target,
                memberName,
                allowEmpty,
                out foundEmpty,
                out parseFailed
            );
        }

        private static Dictionary<string, int> ParseDictionaryMemberValue(
            object raw,
            bool allowEmpty,
            out bool foundEmptyMember,
            out bool parseFailedWithEntries
        )
        {
            foundEmptyMember = false;
            parseFailedWithEntries = false;
            if (raw == null)
                return null;

            var dict = raw as IDictionary;
            if (dict != null && dict.Count == 0)
            {
                foundEmptyMember = true;
                return allowEmpty ? new Dictionary<string, int>() : null;
            }

            var counts = ParseDictionary(raw);
            if (counts != null && counts.Count > 0)
                return counts;
            if (counts != null && counts.Count == 0 && allowEmpty)
            {
                foundEmptyMember = true;
                return counts;
            }
            if (dict != null && dict.Count > 0)
                parseFailedWithEntries = true;

            return null;
        }

        private static Dictionary<string, int> TryScanDictionaryMembers(
            object target,
            bool allowEmpty,
            out bool foundEmptyMember,
            out bool parseFailedWithEntries
        )
        {
            foundEmptyMember = false;
            parseFailedWithEntries = false;
            var type = target.GetType();
            Dictionary<string, int> best = null;

            foreach (var prop in type.GetProperties(MemberFlags))
            {
                if (!MemberNameLooksLikeLetterCounts(prop.Name))
                    continue;
                bool empty;
                bool failed;
                var counts = ParseDictionaryMemberValue(
                    prop.GetValue(target, null),
                    allowEmpty,
                    out empty,
                    out failed
                );
                if (empty)
                    foundEmptyMember = true;
                if (failed)
                    parseFailedWithEntries = true;
                if (counts == null || (!allowEmpty && counts.Count == 0))
                    continue;
                if (best == null || SumCounts(counts) > SumCounts(best))
                    best = counts;
            }

            foreach (var field in type.GetFields(MemberFlags))
            {
                if (!MemberNameLooksLikeLetterCounts(field.Name))
                    continue;
                bool empty;
                bool failed;
                var counts = ParseDictionaryMemberValue(
                    field.GetValue(target),
                    allowEmpty,
                    out empty,
                    out failed
                );
                if (empty)
                    foundEmptyMember = true;
                if (failed)
                    parseFailedWithEntries = true;
                if (counts == null || (!allowEmpty && counts.Count == 0))
                    continue;
                if (best == null || SumCounts(counts) > SumCounts(best))
                    best = counts;
            }

            return best;
        }

        private static Dictionary<string, int> TryScanDictionaryMembers(
            object target,
            bool allowEmpty = false
        )
        {
            bool foundEmpty;
            bool parseFailed;
            return TryScanDictionaryMembers(target, allowEmpty, out foundEmpty, out parseFailed);
        }

        /// <summary>
        /// Mutating DNA dictionary keys: lowercase letters or number strings (Tile.GetStringRepresentation).
        /// </summary>
        internal static string NormalizeMutatingDnaDictionaryKey(string raw)
        {
            if (string.IsNullOrWhiteSpace(raw))
                return null;

            var key = raw.Trim();
            if (key.Length == 1 && char.IsLetter(key[0]))
                return key.ToLowerInvariant();

            if (IsDigitString(key))
                return key;

            return null;
        }

        private static bool IsDigitString(string value)
        {
            if (string.IsNullOrEmpty(value))
                return false;

            for (var i = 0; i < value.Length; i++)
            {
                if (!char.IsDigit(value[i]))
                    return false;
            }

            return true;
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
                    var key = NormalizeMutatingDnaDictionaryKey(
                        TryGetStringProperty(entry, "Key", "Letter", "Character")
                    );
                    var value = TryGetIntProperty(entry, "Value", "Count", "Uses", "TimesUsed");
                    if (string.IsNullOrEmpty(key) || value < 0)
                        continue;
                    counts[key] = value;
                }

                return counts.Count > 0 ? counts : null;
            }

            return null;
        }

        private static Dictionary<string, int> ParseGenericDictionary(IDictionary dict)
        {
            if (dict == null)
                return null;

            var counts = new Dictionary<string, int>();
            var hadAnyKey = false;
            foreach (DictionaryEntry entry in dict)
            {
                hadAnyKey = true;
                var key = NormalizeMutatingDnaDictionaryKey(entry.Key?.ToString());
                if (string.IsNullOrEmpty(key))
                    continue;

                var value = TryReadIntLike(entry.Value);
                if (value < 0)
                    continue;
                counts[key] = value;
            }

            if (counts.Count > 0)
                return counts;
            if (!hadAnyKey)
                return new Dictionary<string, int>();

            return null;
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

