using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using MelonLoader;
using MelonLoader.Preferences;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace CursedWordsSolverCompanion
{
    public sealed class RoundCaptureContext
    {
        public string SubmitMethod;
        public string SubmittedWord;
        public List<int> SubmittedPath;
        public LastSuggestion Suggestion;
        public int ActualScore;
        public List<Dictionary<string, object>> ActualTrace;
        public List<ScoreCalcVizInfo> ScoreSteps;
        public string BoardFingerprint;
        public string LoadoutFingerprint;
        public BoardSnapshot BoardAtSubmit;
        public BoardSnapshot SubmitBoardSnapshot;
        public List<ConsumableRackTileSnapshot> RackBefore;
        public List<ConsumableRackTileSnapshot> RackAfter;
        public List<ConsumablePlacementRecord> ConsumablePlacements;
        public RunStateSnapshot RunState;
        public Dictionary<string, string> ScoringExtras;
        public bool CaptureActive;
    }

    public static class RoundLogExporter
    {
        public const int SchemaVersion = 1;

        public static readonly string RoundLogDir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
            ".cursed_words_solver",
            "round_logs"
        );

        private static MelonPreferences_Category _prefs;
        private static MelonPreferences_Entry<bool> _enabled;

        public static bool IsEnabled
        {
            get
            {
                EnsurePrefs();
                return _enabled.Value;
            }
        }

        public static void EnsurePrefs()
        {
            if (_prefs != null)
                return;

            _prefs = MelonPreferences.CreateCategory(
                "CursedWordsSolverCompanion_RoundLog",
                "Cursed Words Solver Round Logs"
            );
            _enabled = _prefs.CreateEntry(
                "RoundLogEnabled",
                true,
                "Round log enabled",
                "Write a JSON log after every word submit"
            );
        }

        public static string ExportRound(RoundCaptureContext ctx)
        {
            if (!IsEnabled || ctx == null)
                return "";

            try
            {
                Directory.CreateDirectory(RoundLogDir);
                var ts = DateTime.Now.ToString("yyyyMMdd_HHmmss_fff");
                var outPath = Path.Combine(RoundLogDir, ts + ".json");

                var matchStatus = ResolveMatchStatus(ctx);
                var pathTiles = BuildPathTiles(ctx);
                var runStateDict = SerializeRunState(ctx.RunState);

                var f8Extras = ctx.Suggestion != null
                    ? ExtrasDiffHelper.ExtrasFromRunStateObject(ctx.Suggestion.run_state_snapshot)
                    : new Dictionary<string, string>();
                var extrasDiff = ExtrasDiffHelper.DiffExtras(f8Extras, ctx.ScoringExtras);

                var payload = new Dictionary<string, object>
                {
                    ["schema_version"] = SchemaVersion,
                    ["exported_at"] = DateTime.UtcNow.ToString("o"),
                    ["round_id"] = ts,
                    ["submit_method"] = ctx.SubmitMethod ?? "",
                    ["grid_number"] = GetGridNumber(ctx),
                    ["match_status"] = matchStatus,
                    ["solver"] = BuildSolverBlock(ctx),
                    ["actual"] = BuildActualBlock(ctx, pathTiles),
                    ["run_state"] = runStateDict,
                    ["consumables"] = BuildConsumablesBlock(ctx),
                    ["comparison"] = BuildComparisonBlock(ctx, matchStatus),
                    ["extras_diff"] = extrasDiff,
                    ["export_diagnostics_at_submit"] = ctx.RunState?.export_diagnostics,
                    ["export_diagnostics_at_f8"] = ctx.Suggestion != null
                        ? ExtrasDiffHelper.ExportDiagnosticsFromRunState(
                            ctx.Suggestion.run_state_snapshot
                        )
                        : null,
                };

                var json = JsonConvert.SerializeObject(payload, Formatting.Indented);
                WriteAtomic(outPath, json);
                AppendIndex(ts, outPath, matchStatus, ctx);

                var staleSuggestion =
                    ctx.Suggestion != null
                    && !ConsumablePlacementHelper.BoardFingerprintMatchesSuggestion(
                        ctx.Suggestion,
                        ctx.BoardFingerprint
                    );
                var statusLabel = matchStatus;
                if (staleSuggestion && (matchStatus == "path_mismatch" || matchStatus == "path_extension"))
                    statusLabel = matchStatus + " (stale F8 board)";
                MelonLogger.Msg("Round log: " + outPath + " (" + statusLabel + ")");
                return outPath;
            }
            catch (Exception ex)
            {
                MelonLogger.Error("Round log export failed: " + ex);
                return "";
            }
        }

        private static string ResolveMatchStatus(RoundCaptureContext ctx)
        {
            if (ctx.Suggestion == null || ctx.Suggestion.path == null || ctx.Suggestion.path.Count == 0)
                return "no_suggestion";

            var pathMatch = SuggestionMatcher.PathsEqual(
                ctx.Suggestion.path,
                ctx.SubmittedPath
            );
            var boardMatch = ConsumablePlacementHelper.BoardFingerprintMatchesSuggestion(
                ctx.Suggestion,
                ctx.BoardFingerprint
            );

            if (!boardMatch)
                return "path_mismatch";

            if (!pathMatch)
            {
                if (
                    SuggestionMatcher.PathsIsPrefixExtension(
                        ctx.Suggestion.path,
                        ctx.SubmittedPath
                    )
                )
                    return "path_extension";
                return "path_mismatch";
            }

            var predicted = ctx.Suggestion.predicted_score;
            if (predicted != ctx.ActualScore)
            {
                var f8Extras = ExtrasDiffHelper.ExtrasFromRunStateObject(
                    ctx.Suggestion.run_state_snapshot
                );
                var extrasDiff = ExtrasDiffHelper.DiffExtras(f8Extras, ctx.ScoringExtras);
                var staleCtx = RunStateExporter.BuildStaleF8Context(
                    RunStateExporter.GetPlayerForUpdate()
                );
                if (ExtrasDiffHelper.HasStaleF8ExtrasDrift(extrasDiff, staleCtx))
                    return "stale_f8_extras";
                return "score_mismatch";
            }

            return "score_match";
        }

        private static Dictionary<string, object> BuildSolverBlock(RoundCaptureContext ctx)
        {
            var block = new Dictionary<string, object> { ["available"] = false };
            if (ctx.Suggestion == null)
                return block;

            block["available"] = true;
            block["word"] = ctx.Suggestion.word ?? "";
            block["scoring_word"] = ctx.Suggestion.word ?? "";
            block["path"] = ctx.Suggestion.path ?? new List<int>();
            block["predicted_score"] = ctx.Suggestion.predicted_score;
            block["board_fingerprint"] = ctx.Suggestion.board_fingerprint ?? "";
            block["loadout_fingerprint"] = ctx.Suggestion.loadout_fingerprint ?? "";
            var submittedPath = ctx.SubmittedPath ?? new List<int>();
            var suggestedPath = ctx.Suggestion.path ?? new List<int>();
            block["f8_path_prefix_match"] = SuggestionMatcher.PathsIsPrefixExtension(
                suggestedPath,
                submittedPath
            );
            block["suggested_path_length"] = suggestedPath.Count;
            block["submitted_path_length"] = submittedPath.Count;

            if (ctx.Suggestion.predicted_trace != null)
                block["predicted_trace"] = ctx.Suggestion.predicted_trace;

            try
            {
                if (File.Exists(SuggestionMatcher.SuggestionFilePath))
                {
                    var raw = JObject.Parse(File.ReadAllText(SuggestionMatcher.SuggestionFilePath));
                    if (raw["dictionary_word"] != null)
                        block["dictionary_word"] = raw["dictionary_word"].ToString();
                    if (raw["f8_sequence"] != null)
                        block["f8_sequence"] = raw["f8_sequence"].ToString();
                    if (raw["created_at"] != null)
                        block["solver_created_at"] = raw["created_at"].ToString();
                }
            }
            catch
            {
                // optional
            }

            return block;
        }

        private static Dictionary<string, object> BuildActualBlock(
            RoundCaptureContext ctx,
            List<Dictionary<string, object>> pathTiles
        )
        {
            return new Dictionary<string, object>
            {
                ["word"] = ctx.SubmittedWord ?? "",
                ["path"] = ctx.SubmittedPath ?? new List<int>(),
                ["path_tiles"] = pathTiles,
                ["score"] = ctx.ActualScore,
                ["trace"] = ctx.ActualTrace ?? new List<Dictionary<string, object>>(),
            };
        }

        private static Dictionary<string, object> BuildConsumablesBlock(RoundCaptureContext ctx)
        {
            var placements = new List<Dictionary<string, object>>();
            if (ctx.ConsumablePlacements != null)
            {
                foreach (var p in ctx.ConsumablePlacements)
                {
                    if (p == null)
                        continue;
                    placements.Add(
                        new Dictionary<string, object>
                        {
                            ["row"] = p.row,
                            ["col"] = p.col,
                            ["rack_index"] = p.rack_index,
                            ["detected_at"] = p.detected_at ?? "",
                            ["new_tile"] = p.new_tile,
                            ["replaced_tile"] = p.replaced_tile,
                        }
                    );
                }
            }

            return new Dictionary<string, object>
            {
                ["rack_before"] = ctx.RackBefore ?? new List<ConsumableRackTileSnapshot>(),
                ["rack_after"] = ctx.RackAfter ?? new List<ConsumableRackTileSnapshot>(),
                ["placements_this_round"] = placements,
            };
        }

        private static Dictionary<string, object> BuildComparisonBlock(
            RoundCaptureContext ctx,
            string matchStatus
        )
        {
            var predicted = ctx.Suggestion != null ? ctx.Suggestion.predicted_score : 0;
            var boardFingerprintMatches = false;
            var pathMatches = false;
            if (ctx.Suggestion != null && ctx.Suggestion.path != null)
            {
                boardFingerprintMatches =
                    ConsumablePlacementHelper.BoardFingerprintMatchesSuggestion(
                        ctx.Suggestion,
                        ctx.BoardFingerprint
                    );
                pathMatches =
                    SuggestionMatcher.PathsEqual(ctx.Suggestion.path, ctx.SubmittedPath)
                    && boardFingerprintMatches;
            }

            var staleSuggestion =
                ctx.Suggestion != null && !boardFingerprintMatches;
            var staleF8Extras = matchStatus == "stale_f8_extras";

            string staleF8Reason = null;
            if (ctx.Suggestion != null && ctx.ScoringExtras != null)
            {
                var f8Extras = ExtrasDiffHelper.ExtrasFromRunStateObject(
                    ctx.Suggestion.run_state_snapshot
                );
                var extrasDiff = ExtrasDiffHelper.DiffExtras(f8Extras, ctx.ScoringExtras);
                var staleCtx = RunStateExporter.BuildStaleF8Context(
                    RunStateExporter.GetPlayerForUpdate()
                );
                staleF8Reason = ExtrasDiffHelper.DescribeStaleF8Extras(extrasDiff, staleCtx);
            }

            return new Dictionary<string, object>
            {
                ["score_delta"] = ctx.ActualScore - predicted,
                ["path_matches_suggestion"] = pathMatches,
                ["board_fingerprint_matches_suggestion"] = boardFingerprintMatches,
                ["stale_suggestion"] = staleSuggestion || staleF8Extras,
                ["stale_f8_extras"] = staleF8Extras,
                ["stale_f8_reason"] = staleF8Reason ?? "",
                ["capture_active"] = ctx.CaptureActive,
                ["match_status"] = matchStatus,
            };
        }

        private static List<Dictionary<string, object>> BuildPathTiles(RoundCaptureContext ctx)
        {
            var result = new List<Dictionary<string, object>>();
            var board = ctx.SubmitBoardSnapshot ?? ctx.BoardAtSubmit;
            if (board?.tiles == null || ctx.SubmittedPath == null)
                return result;

            var cols = board.cols > 0 ? board.cols : 5;
            var byIndex = new Dictionary<int, BoardTileSnapshot>();
            foreach (var t in board.tiles)
            {
                if (t == null || !t.active)
                    continue;
                // Path indices match melmod export row (0 = top) per loadout.py.
                var idx = t.row * cols + t.col;
                byIndex[idx] = t;
            }

            foreach (var idx in ctx.SubmittedPath)
            {
                if (!byIndex.TryGetValue(idx, out var tile) || tile == null)
                {
                    result.Add(
                        new Dictionary<string, object>
                        {
                            ["path_index"] = idx,
                            ["row"] = idx / cols,
                            ["col"] = idx % cols,
                        }
                    );
                    continue;
                }

                result.Add(
                    new Dictionary<string, object>
                    {
                        ["path_index"] = idx,
                        ["row"] = tile.row,
                        ["col"] = tile.col,
                        ["letter"] = tile.letter,
                        ["char"] = tile.char_display,
                        ["curse"] = tile.curse,
                        ["color"] = tile.color,
                        ["base_score"] = tile.base_score,
                        ["consumable"] = tile.consumable,
                        ["was_consumable"] = tile.was_consumable,
                        ["take"] = tile.take,
                        ["card_suit"] = tile.card_suit ?? "",
                        ["card_rank"] = tile.card_rank ?? "",
                    }
                );
            }

            return result;
        }

        private static Dictionary<string, object> SerializeRunState(RunStateSnapshot snapshot)
        {
            if (snapshot == null)
                return new Dictionary<string, object>();

            var json = JsonConvert.SerializeObject(snapshot);
            return JsonConvert.DeserializeObject<Dictionary<string, object>>(json)
                ?? new Dictionary<string, object>();
        }

        private static string GetGridNumber(RoundCaptureContext ctx)
        {
            if (ctx.RunState?.extras != null
                && ctx.RunState.extras.TryGetValue("grid_number", out var gn))
                return gn ?? "";

            if (ctx.ScoringExtras != null
                && ctx.ScoringExtras.TryGetValue("grid_number", out var g2))
                return g2 ?? "";

            return "";
        }

        private static void AppendIndex(
            string roundId,
            string filePath,
            string matchStatus,
            RoundCaptureContext ctx
        )
        {
            try
            {
                var indexPath = Path.Combine(RoundLogDir, "index.jsonl");
                var predicted = ctx.Suggestion != null ? ctx.Suggestion.predicted_score : 0;
                var line =
                    JsonConvert.SerializeObject(
                        new Dictionary<string, object>
                        {
                            ["round_id"] = roundId,
                            ["file"] = filePath,
                            ["match_status"] = matchStatus,
                            ["predicted_score"] = predicted,
                            ["actual_score"] = ctx.ActualScore,
                            ["submitted_word"] = ctx.SubmittedWord ?? "",
                            ["solver_word"] = ctx.Suggestion?.word ?? "",
                        }
                    ) + "\n";
                File.AppendAllText(indexPath, line, new UTF8Encoding(false));
            }
            catch
            {
                // optional
            }
        }

        private static void WriteAtomic(string path, string content)
        {
            var temp = path + ".tmp";
            File.WriteAllText(temp, content, new UTF8Encoding(false));
            if (File.Exists(path))
                File.Delete(path);
            File.Move(temp, path);
        }
    }
}
