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
        public List<SuggestedConsumablePlacement> consumable_placements;
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
                var suggestion = JsonConvert.DeserializeObject<LastSuggestion>(json);
                if (suggestion != null)
                    TryRefreshWorkflowExtrasOnLoad(suggestion);
                return suggestion;
            }
            catch
            {
                return null;
            }
        }

        /// <summary>
        /// Patch embedded F8 workflow extras when live export caught up after last_suggestion was written.
        /// </summary>
        public static bool TryRefreshWorkflowExtrasOnLoad(LastSuggestion suggestion)
        {
            if (suggestion == null)
                return false;
            var player = RunStateExporter.GetPlayerForUpdate();
            if (player == null)
                return false;
            var liveExtras = RunStateExporter.BuildExtrasSnapshot();
            var projected = RunStateExportFill.BuildSubmitWorkflowExtras(player, liveExtras);
            return TrySyncWorkflowExtrasToProjected(suggestion, projected);
        }

        /// <summary>
        /// Remove last_suggestion.json after a word submit so the next scored word requires F8.
        /// </summary>
        public static void TryClearLastSuggestionAfterSubmit()
        {
            try
            {
                if (!File.Exists(SuggestionFilePath))
                    return;
                File.Delete(SuggestionFilePath);
            }
            catch (Exception ex)
            {
                CompanionDiagnostics.LogVerboseWarning(
                    "Could not delete last_suggestion.json: " + ex.Message
                );
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
            if (!ConsumablePlacementHelper.BoardFingerprintMatchesSuggestion(
                    suggestion,
                    boardFingerprint))
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
            var boardMatches = ConsumablePlacementHelper.BoardFingerprintMatchesSuggestion(
                suggestion,
                boardFingerprint);
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
                var staleCtx = RunStateExporter.BuildStaleF8Context(
                    RunStateExporter.GetPlayerForUpdate()
                );
                var stale = ExtrasDiffHelper.DescribeStaleF8LoadoutDrift(
                    f8Extras,
                    liveExtras,
                    staleCtx
                );
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

        /// <summary>
        /// Align embedded F8 workflow extras with submit-time projection (same board/path).
        /// </summary>
        public static bool TrySyncWorkflowExtrasToProjected(
            LastSuggestion suggestion,
            Dictionary<string, string> projectedExtras
        )
        {
            if (suggestion == null || projectedExtras == null)
                return false;
            if (suggestion.run_state_snapshot == null)
                return false;

            try
            {
                var extras = suggestion.run_state_snapshot["extras"] as JObject;
                if (extras == null)
                {
                    extras = new JObject();
                    suggestion.run_state_snapshot["extras"] = extras;
                }

                var changed = false;
                foreach (var key in new[]
                {
                    "historic_words",
                    "previous_word_first_letter",
                    "red_tiles_used_encounter",
                    "scoring_previous_words_count",
                    "mutating_dna_letter_counts",
                    "encounter_historic_source",
                })
                {
                    string val;
                    if (!projectedExtras.TryGetValue(key, out val) || string.IsNullOrEmpty(val))
                        continue;
                    var cur = extras[key]?.ToString() ?? "";
                    if (!string.Equals(cur, val, StringComparison.Ordinal))
                    {
                        extras[key] = val;
                        changed = true;
                    }
                }

                if (!changed)
                    return false;

                File.WriteAllText(
                    SuggestionFilePath,
                    JsonConvert.SerializeObject(suggestion, Formatting.Indented)
                );
                CompanionDiagnostics.LogVerbose(
                    "Synced F8 run_state_snapshot workflow extras to submit projection"
                );
                return true;
            }
            catch (Exception ex)
            {
                CompanionDiagnostics.LogVerboseWarning(
                    "Could not sync last_suggestion workflow extras: " + ex.Message
                );
                return false;
            }
        }
    }
}

