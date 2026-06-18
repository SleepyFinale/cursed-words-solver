using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using MelonLoader;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace CursedWordsSolverCompanion
{
    public static class MismatchExporter
    {
        public static readonly string MismatchDir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
            ".cursed_words_solver",
            "scoring_mismatches"
        );

        public static void ExportIfMismatch(
            LastSuggestion suggestion,
            string word,
            List<int> path,
            int actualScore,
            List<Dictionary<string, object>> actualTrace,
            string boardFingerprint,
            string loadoutFingerprint,
            Dictionary<string, string> extrasSnapshot,
            string submitMethod,
            Player submitPlayer = null,
            BoardSnapshot scoringBoardSnapshot = null,
            Dictionary<string, string> preWordScoringExtras = null,
            string f8PredictionHistoricStaleNote = null,
            Dictionary<string, string> originalF8Extras = null
        )
        {
            if (suggestion == null)
                return;

            if (
                suggestion.path != null
                && path != null
                && !SuggestionMatcher.PathsEqual(suggestion.path, path)
                && !SuggestionMatcher.PathsIsPrefixExtension(suggestion.path, path)
            )
            {
                MelonLogger.Msg(
                    "Path mismatch (F8 vs submit): skipping score mismatch export for '"
                        + word
                        + "' — predicted "
                        + suggestion.predicted_score
                        + ", actual "
                        + actualScore
                );
                return;
            }

            var predicted = suggestion.predicted_score;
            if (
                suggestion.score_nondeterministic
                && suggestion.predicted_score_max > suggestion.predicted_score_min
                && actualScore >= suggestion.predicted_score_min
                && actualScore <= suggestion.predicted_score_max
            )
            {
                MelonLogger.Msg(
                    "Scoring match (Capybara range) for suggested word '"
                        + word
                        + "': "
                        + actualScore
                        + " pts (predicted "
                        + predicted
                        + ", range "
                        + suggestion.predicted_score_min
                        + "–"
                        + suggestion.predicted_score_max
                        + ")"
                );
                return;
            }
            if (predicted == actualScore)
            {
                MelonLogger.Msg(
                    "Scoring match for suggested word '"
                        + word
                        + "': "
                        + actualScore
                        + " pts"
                );
                return;
            }

            Directory.CreateDirectory(MismatchDir);
            var ts = DateTime.Now.ToString("yyyyMMdd_HHmmss");
            var outPath = Path.Combine(MismatchDir, ts + ".json");

            var runStateSnapshot = CloneRunStateSnapshot(suggestion.run_state_snapshot);
            ScoringContextCapture.MergeExtrasIntoSnapshot(runStateSnapshot, extrasSnapshot);

            var submitBoard = scoringBoardSnapshot;
            if (submitBoard == null && submitPlayer != null)
                submitBoard = BoardExporter.TryBuild(submitPlayer);
            if (submitBoard != null)
            {
                BoardExporter.MergeSubmitTakeFlagsIntoRunState(runStateSnapshot, submitBoard);
                BoardExporter.MergeSubmitCardMetadataIntoRunState(runStateSnapshot, submitBoard);
            }

            var pathTiles = RoundLogExporter.BuildPathTiles(path, submitBoard);
            if (pathTiles != null && pathTiles.Count > 0)
            {
                if (extrasSnapshot == null)
                    extrasSnapshot = new Dictionary<string, string>();
                extrasSnapshot["path_resolved_word"] = word ?? "";
            }

            var f8Extras = originalF8Extras != null && originalF8Extras.Count > 0
                ? originalF8Extras
                : ExtrasDiffHelper.ExtrasFromRunStateObject(suggestion.run_state_snapshot);
            var diffExtras = preWordScoringExtras ?? extrasSnapshot;
            var extrasDiff = ExtrasDiffHelper.DiffExtras(f8Extras, diffExtras);
            var staleCtx = submitPlayer != null
                ? RunStateExporter.BuildStaleF8Context(submitPlayer)
                : StaleF8Context.Default();
            var staleNote = ExtrasDiffHelper.DescribeStaleF8Extras(extrasDiff, staleCtx);
            if (
                string.IsNullOrEmpty(staleNote)
                && !string.IsNullOrEmpty(f8PredictionHistoricStaleNote)
            )
                staleNote =
                    "F8 snapshot stale — re-run F8 after your last word before trusting predicted scores ("
                    + f8PredictionHistoricStaleNote
                    + ")";
            var pathBoardMatch = SuggestionMatcher.MatchesSuggestion(
                suggestion,
                word,
                path,
                boardFingerprint,
                loadoutFingerprint
            );
            var staleF8Extras = !string.IsNullOrEmpty(staleNote);
            if (staleF8Extras)
            {
                MelonLogger.Warning(staleNote);
                if (pathBoardMatch)
                {
                    MelonLogger.Msg(
                        "Scoring drift with stale F8 embed (path/board match): predicted "
                            + predicted
                            + ", actual "
                            + actualScore
                            + " — exporting mismatch with submit-projected extras."
                    );
                }
            }

            if (staleF8Extras && !pathBoardMatch)
            {
                MelonLogger.Msg(
                    "Scoring drift skipped (stale F8, path/board mismatch): predicted "
                        + predicted
                        + ", actual "
                        + actualScore
                        + " — re-run F8 after your last word."
                );
                return;
            }

            var payload = new Dictionary<string, object>
            {
                ["word"] = word,
                ["path"] = path,
                ["predicted_score"] = predicted,
                ["actual_score"] = actualScore,
                ["delta"] = actualScore - predicted,
                ["score_nondeterministic"] = suggestion.score_nondeterministic,
                ["predicted_score_min"] = suggestion.predicted_score_min,
                ["predicted_score_max"] = suggestion.predicted_score_max,
                ["board_fingerprint"] = boardFingerprint ?? "",
                ["loadout_fingerprint"] = loadoutFingerprint ?? "",
                ["predicted_trace"] = suggestion.predicted_trace ?? new JArray(),
                ["run_state_snapshot"] = runStateSnapshot,
                ["actual_trace"] = actualTrace ?? new List<Dictionary<string, object>>(),
                ["extras_snapshot"] = extrasSnapshot ?? new Dictionary<string, string>(),
                ["extras_diff"] = extrasDiff,
                ["submit_board_tiles"] = submitBoard?.tiles,
                ["path_tiles"] = pathTiles,
                ["f8_sequence"] = suggestion.f8_sequence,
                ["solver_version"] = suggestion.solver_version ?? "",
                ["stale_f8_extras"] = staleF8Extras,
                ["stale_f8_reason"] = staleNote ?? "",
                ["export_diagnostics_at_f8"] = ExtrasDiffHelper.ExportDiagnosticsFromRunState(
                    suggestion.run_state_snapshot
                ),
                ["game_types"] = new Dictionary<string, string>
                {
                    ["submit_method"] = submitMethod ?? "",
                    ["score_type"] = "ScoreCalculation.CalculateOverallScore",
                },
                ["exported_at"] = DateTime.UtcNow.ToString("o"),
            };

            var json = JsonConvert.SerializeObject(payload, Formatting.Indented);
            File.WriteAllText(outPath, json, new UTF8Encoding(false));
            var label = staleF8Extras ? " (stale F8 embed)" : "";
            MelonLogger.Warning(
                "Scoring MISMATCH for '"
                    + word
                    + "': predicted "
                    + predicted
                    + ", actual "
                    + actualScore
                    + label
                    + " → "
                    + outPath
            );
        }

        private static Dictionary<string, object> CloneRunStateSnapshot(object snapshot)
        {
            if (snapshot == null)
                return new Dictionary<string, object>();

            if (snapshot is Dictionary<string, object> dict)
                return new Dictionary<string, object>(dict);

            if (snapshot is JObject jobj)
                return jobj.ToObject<Dictionary<string, object>>()
                    ?? new Dictionary<string, object>();

            return new Dictionary<string, object>();
        }
    }
}
