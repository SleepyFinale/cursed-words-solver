using System;
using System.Collections.Generic;
using System.Reflection;

namespace CursedWordsSolverCompanion
{
    /// <summary>
    /// Extract scoring context from CalculateOverallScore inputs (e.g. prior words).
    /// </summary>
    public static class ScoringContextCapture
    {
        public static Dictionary<string, string> ExtractFromPreviousWords(
            List<HistoricWord> previousWords
        )
        {
            var extras = new Dictionary<string, string>();
            var letter = FirstLetterFromHistoricWords(previousWords);
            if (!string.IsNullOrEmpty(letter))
                extras["previous_word_first_letter"] = letter;
            return extras;
        }

        public static string FirstLetterFromHistoricWords(List<HistoricWord> previousWords)
        {
            if (previousWords == null || previousWords.Count == 0)
                return "";

            for (var i = previousWords.Count - 1; i >= 0; i--)
            {
                var word = GetSubmittedWordString(previousWords[i]);
                var letter = FirstAlphabeticLetter(word);
                if (!string.IsNullOrEmpty(letter))
                    return letter;
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
                    var prop = target.GetType().GetProperty(
                        name,
                        BindingFlags.Public | BindingFlags.Instance
                    );
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
}
