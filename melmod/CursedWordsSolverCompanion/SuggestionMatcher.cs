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
        public bool capture_blocked;
        public string block_reason;
        public int predicted_score;
        public int predicted_score_min;
        public int predicted_score_max;
        public bool score_nondeterministic;
        public int capybara_perm_count;
        public bool capybara_exhaustive;
        public string board_fingerprint;
        public string loadout_fingerprint;
        public JArray predicted_trace;
        public JObject run_state_snapshot;
        public int f8_sequence;
        public string solver_version;
        public string created_at;
        public List<SuggestedConsumablePlacement> consumable_placements;
        public JObject twinkle_toes_swap;
    }

    public static class SuggestionMatcher
    {
        public static readonly string SuggestionFilePath = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
            ".cursed_words_solver",
            "last_suggestion.json"
        );

        public static readonly string BlockedSuggestionFilePath = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
            ".cursed_words_solver",
            "last_suggestion_blocked.json"
        );

        public static LastSuggestion Load()
        {
            var suggestion = TryReadSuggestionFile(SuggestionFilePath);
            if (suggestion != null)
                TryRefreshWorkflowExtrasOnLoad(suggestion);
            if (suggestion != null)
                return suggestion;
            return LoadBlocked();
        }

        public static LastSuggestion LoadBlocked()
        {
            return TryReadSuggestionFile(BlockedSuggestionFilePath);
        }

        private static LastSuggestion TryReadSuggestionFile(string path)
        {
            try
            {
                if (!File.Exists(path))
                    return null;
                var json = File.ReadAllText(path);
                return JsonConvert.DeserializeObject<LastSuggestion>(json);
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
            TryDeleteSuggestionFile(SuggestionFilePath);
            TryDeleteSuggestionFile(BlockedSuggestionFilePath);
        }

        private static void TryDeleteSuggestionFile(string path)
        {
            try
            {
                if (!File.Exists(path))
                    return;
                File.Delete(path);
            }
            catch (Exception ex)
            {
                CompanionDiagnostics.LogVerboseWarning(
                    "Could not delete " + Path.GetFileName(path) + ": " + ex.Message
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
        public static int CoordsToSolverIndex(UnityEngine.Vector2Int coords, int cols = 5)
        {
            if (cols <= 0)
                cols = 5;
            var displayRow = coords.y;
            var col = coords.x;
            return (cols - 1 - displayRow) * cols + col;
        }

        public static List<int> PathFromSelections(List<TileSelection> selections, int cols = 5)
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
                    path.Add(CoordsToSolverIndex(coords, cols));
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
            if (suggestion.capture_blocked)
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
                        "submitted path extends F8 highlight — a longer path may beat the "
                            + "F8 prefix (solver extension miss); press F8 again after extending "
                            + "for an updated suggestion"
                    );
                }
                else if (boardMatches)
                {
                    parts.Add(
                        "alternate path on same board (score compare needs the exact highlighted path; "
                            + "round log saved for solver replay)"
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
                    "birthday_cake_bonus",
                    "tile_ninja_bonus",
                    "tile_ninja_consumables_used",
                    "tile_ninja_word_bonus_percent",
                    "pin_memory",
                    "pin_memory_count",
                    "consumable_rack_count",
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

                foreach (var key in new[]
                {
                    "boss_modifiers",
                    "boss_modifier_floor_mods",
                    "boss_cursed",
                    "boss_area_number",
                    "boss_floor_modification",
                })
                {
                    string val;
                    projectedExtras.TryGetValue(key, out val);
                    val = val ?? "";
                    var cur = extras[key]?.ToString() ?? "";
                    if (string.Equals(cur, val, StringComparison.Ordinal))
                        continue;
                    if (string.IsNullOrEmpty(val))
                    {
                        if (extras.Remove(key))
                            changed = true;
                        else if (!string.IsNullOrEmpty(cur))
                        {
                            extras.Remove(key);
                            changed = true;
                        }
                    }
                    else
                    {
                        extras[key] = val;
                        changed = true;
                    }
                }

                string projectedBossMods;
                projectedExtras.TryGetValue("boss_modifiers", out projectedBossMods);
                projectedBossMods = (projectedBossMods ?? "").Trim();
                if (string.IsNullOrEmpty(projectedBossMods) || projectedBossMods == "[]")
                {
                    var snap = suggestion.run_state_snapshot as JObject;
                    if (snap != null)
                    {
                        var bossId = snap["boss_id"]?.ToString() ?? "";
                        if (!string.IsNullOrEmpty(bossId))
                        {
                            snap["boss_id"] = "";
                            snap["boss_name"] = "";
                            snap["boss_effect"] = "";
                            changed = true;
                        }
                    }
                }

                if (!changed)
                    return false;

                var syncedExtras = ExtrasDiffHelper.ExtrasFromRunStateObject(
                    suggestion.run_state_snapshot
                );
                if (syncedExtras != null)
                {
                    RunStateExportFill.ApplyScoringCachedPreviousWordLetter(syncedExtras);
                    var extrasObj = suggestion.run_state_snapshot["extras"] as JObject;
                    if (extrasObj != null)
                    {
                        foreach (var kv in syncedExtras)
                        {
                            if (string.Equals(kv.Key, "scoring_previous_words_count", StringComparison.Ordinal)
                                || string.Equals(kv.Key, "previous_word_first_letter", StringComparison.Ordinal))
                            {
                                if (string.IsNullOrEmpty(kv.Value))
                                    extrasObj.Remove(kv.Key);
                                else
                                    extrasObj[kv.Key] = kv.Value;
                            }
                        }
                    }
                }

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

