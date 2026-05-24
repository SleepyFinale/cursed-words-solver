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
            string submitMethod
        )
        {
            if (suggestion == null)
                return;

            var predicted = suggestion.predicted_score;
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

            var payload = new Dictionary<string, object>
            {
                ["word"] = word,
                ["path"] = path,
                ["predicted_score"] = predicted,
                ["actual_score"] = actualScore,
                ["delta"] = actualScore - predicted,
                ["board_fingerprint"] = boardFingerprint ?? "",
                ["loadout_fingerprint"] = loadoutFingerprint ?? "",
                ["predicted_trace"] = suggestion.predicted_trace ?? new JArray(),
                ["run_state_snapshot"] = runStateSnapshot,
                ["actual_trace"] = actualTrace ?? new List<Dictionary<string, object>>(),
                ["extras_snapshot"] = extrasSnapshot ?? new Dictionary<string, string>(),
                ["game_types"] = new Dictionary<string, string>
                {
                    ["submit_method"] = submitMethod ?? "",
                    ["score_type"] = "ScoreCalculation.CalculateOverallScore",
                },
                ["exported_at"] = DateTime.UtcNow.ToString("o"),
            };

            var json = JsonConvert.SerializeObject(payload, Formatting.Indented);
            File.WriteAllText(outPath, json, new UTF8Encoding(false));
            MelonLogger.Warning(
                "Scoring MISMATCH for '"
                    + word
                    + "': predicted "
                    + predicted
                    + ", actual "
                    + actualScore
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
