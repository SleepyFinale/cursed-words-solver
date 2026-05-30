using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace CursedWordsSolverCompanion
{
    public sealed class LastSuggestion
    {
        public string word;
        public List<int> path;
        public int predicted_score;
        public string board_fingerprint;
        public string loadout_fingerprint;
        public JArray predicted_trace;
        public JObject run_state_snapshot;
        public int f8_sequence;
        public string solver_version;
        public string created_at;
    }

    public static class SuggestionMatcher
    {
        public static readonly string SuggestionFilePath = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
            ".cursed_words_solver",
            "last_suggestion.json"
        );

        public static LastSuggestion Load()
        {
            try
            {
                if (!File.Exists(SuggestionFilePath))
                    return null;
                var json = File.ReadAllText(SuggestionFilePath);
                return JsonConvert.DeserializeObject<LastSuggestion>(json);
            }
            catch
            {
                return null;
            }
        }

        /// <summary>
        /// Remove last_suggestion.json after a word submit so the next scored word requires F8.
        /// </summary>
        public static void TryClearLastSuggestionAfterSubmit()
        {
            try
            {
                if (File.Exists(SuggestionFilePath))
                    File.Delete(SuggestionFilePath);
            }
            catch
            {
                // best-effort
            }
        }

        public static bool PathsEqual(List<int> a, List<int> b)
        {
            if (a == null || b == null || a.Count != b.Count)
                return false;
            for (var i = 0; i < a.Count; i++)
            {
                if (a[i] != b[i])
                    return false;
            }
            return true;
        }

        /// <summary>
        /// True when the player extended the F8 highlight (same board, longer path, same prefix).
        /// </summary>
        public static bool PathsIsPrefixExtension(List<int> suggestionPath, List<int> submittedPath)
        {
            if (suggestionPath == null || submittedPath == null)
                return false;
            if (suggestionPath.Count == 0 || submittedPath.Count <= suggestionPath.Count)
                return false;
            for (var i = 0; i < suggestionPath.Count; i++)
            {
                if (suggestionPath[i] != submittedPath[i])
                    return false;
            }
            return true;
        }

        /// <summary>
        /// Solver scoring strings use digits / stamp substitutions; game submit uses dictionary spelling.
        /// </summary>
        public static bool LooksLikeScoringWord(string word)
        {
            if (string.IsNullOrEmpty(word))
                return false;
            return word.Any(ch => char.IsDigit(ch));
        }

        /// <summary>
        /// Convert tile coordinates to solver path index (same as overlay / last_suggestion.json).
        /// Game coords use display row (0 = top); solver index uses row 0 = top of overlay.
        /// </summary>
        public static int CoordsToSolverIndex(UnityEngine.Vector2Int coords)
        {
            const int gridSize = 5;
            var displayRow = coords.y;
            var col = coords.x;
            return (gridSize - 1 - displayRow) * gridSize + col;
        }

        public static List<int> PathFromSelections(List<TileSelection> selections)
        {
            var path = new List<int>();
            if (selections == null)
                return path;

            foreach (var sel in selections)
            {
                if (sel == null || sel.SelectedTile == null)
                    continue;
                try
                {
                    var coords = sel.SelectedTile.GetCoordinates();
                    path.Add(CoordsToSolverIndex(coords));
                }
                catch
                {
                    // skip bad tile
                }
            }
            return path;
        }

        public static string WordFromSubmit(List<TileSelection> selections, List<string> words)
        {
            if (words != null && words.Count > 0)
            {
                var w = words[words.Count - 1];
                if (!string.IsNullOrWhiteSpace(w))
                    return w.Trim().ToLowerInvariant();
            }

            if (selections == null)
                return "";

            var sb = new System.Text.StringBuilder();
            foreach (var sel in selections)
            {
                if (sel?.SelectedTile == null)
                    continue;
                try
                {
                    var letter = sel.SelectedTile.Letter;
                    if (!string.IsNullOrEmpty(letter))
                        sb.Append(letter);
                }
                catch
                {
                    // ignore
                }
            }
            return sb.ToString().Trim().ToLowerInvariant();
        }

        public static bool MatchesSuggestion(
            LastSuggestion suggestion,
            string word,
            List<int> path,
            string boardFingerprint,
            string loadoutFingerprint
        )
        {
            if (suggestion == null || suggestion.path == null || suggestion.path.Count == 0)
                return false;
            if (!PathsEqual(suggestion.path, path))
                return false;
            if (!string.Equals(
                    suggestion.board_fingerprint ?? "",
                    boardFingerprint ?? "",
                    StringComparison.Ordinal))
                return false;
            return true;
        }

        public static string DescribeMismatch(
            LastSuggestion suggestion,
            string word,
            List<int> path,
            string boardFingerprint,
            string loadoutFingerprint
        )
        {
            if (suggestion == null)
                return "no last_suggestion.json (press F8 in solver first)";

            var parts = new List<string>();
            var pathMatches = PathsEqual(suggestion.path, path);
            var boardMatches = string.Equals(
                suggestion.board_fingerprint ?? "",
                boardFingerprint ?? "",
                StringComparison.Ordinal);
            var wordMatches = string.Equals(
                suggestion.word?.Trim() ?? "",
                word ?? "",
                StringComparison.OrdinalIgnoreCase);

            if (!pathMatches)
            {
                if (
                    boardMatches
                    && PathsIsPrefixExtension(suggestion.path, path)
                )
                {
                    parts.Add(
                        "submitted path extends F8 highlight (press F8 again after extending, "
                            + "or play the exact highlighted path for score compare)"
                    );
                }
                else
                {
                    parts.Add(
                        "path differs from F8 suggestion (score compare needs the exact highlighted path; "
                            + "alternate routes for the same dictionary word are not captured)"
                    );
                }
                parts.Add(
                    "submitted ["
                        + string.Join(",", path ?? new List<int>())
                        + "] vs suggestion ["
                        + string.Join(",", suggestion.path ?? new List<int>())
                        + "]"
                );
            }

            if (!boardMatches)
                parts.Add("board_fingerprint differs (board changed since F8?)");

            if (pathMatches && boardMatches && suggestion.run_state_snapshot != null)
            {
                var f8Extras = ExtrasDiffHelper.ExtrasFromRunStateObject(
                    suggestion.run_state_snapshot
                );
                var liveExtras = RunStateExporter.BuildExtrasSnapshot();
                var stale = ExtrasDiffHelper.DescribeStaleF8LoadoutDrift(f8Extras, liveExtras);
                if (!string.IsNullOrEmpty(stale))
                    parts.Add(stale);
            }

            if (!wordMatches && pathMatches && boardMatches)
            {
                if (LooksLikeScoringWord(suggestion.word))
                    parts.Add(
                        "scoring word '"
                            + suggestion.word
                            + "' vs dictionary submit '"
                            + word
                            + "' (expected; capture should still run)"
                    );
                else
                    parts.Add(
                        "word: submitted '"
                            + word
                            + "' vs suggestion '"
                            + suggestion.word
                            + "'"
                    );
            }
            else if (!wordMatches && (!pathMatches || !boardMatches))
            {
                parts.Add(
                    "word: submitted '"
                        + word
                        + "' vs suggestion '"
                        + suggestion.word
                        + "'"
                );
            }

            if (parts.Count == 0)
                return "unknown (path and board match but capture inactive)";

            return string.Join("; ", parts);
        }
    }
}

