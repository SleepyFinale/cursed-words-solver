using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Text;
using System.Threading;
using MelonLoader;
using Newtonsoft.Json;

namespace CursedWordsSolverCompanion
{
    public static class RunStateExporter
    {
        private const int BicycleMergeRetryBudget = 12;
        private const int JsonMergeRetryCount = 12;
        private const int JsonMergeRetryDelayMs = 40;
        private static int _pendingBicycleMergeRetries = 0;
        private static float _lastMutatingDnaMergeTime = -999f;
        private const float MutatingDnaMergeIntervalSec = 0.5f;
        private static List<HistoricWord> _cachedPreviousWords;
        private static int _cachedMovieCameraWordScoreBonus = -1;
        private static bool _scoringCacheSubmitInFlight;
        private static bool _exportLiveOnlyHistoric;
        private static bool _exportSkipWorkflowDiskMerge;
        private static string _f8ExportRequestId = "";
        private static DateTime _lastF8ExportCompletedUtc = DateTime.MinValue;
        private const double F8SuggestionClearGraceSec = 1.5;

        internal static bool ExportLiveOnlyHistoric
        {
            get { return _exportLiveOnlyHistoric; }
        }

        internal static DateTime LastF8ExportCompletedUtc
        {
            get { return _lastF8ExportCompletedUtc; }
        }

        internal static bool ExportSkipWorkflowDiskMerge
        {
            get { return _exportSkipWorkflowDiskMerge; }
        }

        public static bool TryExportForF8(string requestId)
        {
            _exportLiveOnlyHistoric = true;
            _exportSkipWorkflowDiskMerge = true;
            _f8ExportRequestId = requestId ?? "";
            try
            {
                var ok = TryExport(false, "f8");
                if (ok)
                    _lastF8ExportCompletedUtc = DateTime.UtcNow;
                return ok;
            }
            finally
            {
                _exportLiveOnlyHistoric = false;
                _exportSkipWorkflowDiskMerge = false;
                _f8ExportRequestId = "";
            }
        }

        private static readonly string OutputPath = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
            ".cursed_words_solver",
            "run_state.json"
        );

        public static string OutputFilePath
        {
            get { return OutputPath; }
        }

        public static bool TryExport(bool logSuccess, string triggerOverride = null)
        {
            var sw = Stopwatch.StartNew();
            var trigger = triggerOverride ?? (logSuccess ? "f7" : "auto");
            ExportDiagnostics.ClearMergeErrors();
            try
            {
                var player = GetPlayer();
                if (player == null)
                    return false;

                TryFlushPendingBicycleExtrasRetry();
                TryMergeBicycleExtrasAfterScore();
                RunStateExportFill.TryClearStaleHistoricCacheOnGridAdvance(player);

                var fingerprint = ComputeFingerprint(player);
                var snapshot = BuildSnapshot(player);
                MergePreservedExtrasFromDisk(snapshot, player);
                RunStateExportFill.EnsureEncounterHistoricExtras(
                    snapshot,
                    player,
                    _exportLiveOnlyHistoric
                );
                SyncLiveBicycleExtrasIntoSnapshot(snapshot, player);
                SyncLiveMovieCameraExtrasIntoSnapshot(snapshot, player);
                SyncTileNinjaExtrasIntoSnapshot(snapshot, player);
                FillSnapshotCopyExtras(snapshot, player);
                SanitizeLoadoutSpecificExtras(snapshot, player);
                BoardExporter.ApplyGridScatteredLevelsFromExtras(snapshot);
                BoardExporter.FillGridScatteredItemsExtra(snapshot);
                sw.Stop();
                ExportDiagnostics.ApplyToSnapshot(
                    snapshot,
                    player,
                    trigger,
                    fingerprint,
                    sw.ElapsedMilliseconds,
                    _f8ExportRequestId
                );
                WriteSnapshot(snapshot);
                TryClearLastSuggestionIfWorkflowStale(snapshot, player, trigger);
                DictionaryExporter.TryExport(logSuccess);
                if (logSuccess)
                {
                    MelonLogger.Msg("Exported run state to " + OutputPath);
                    if (snapshot.ui_layout == null)
                    {
                        var status = UiLayoutExporter.LastStatus;
                        MelonLogger.Warning(
                            "ui_layout export failed ("
                                + (string.IsNullOrEmpty(status) ? "unknown" : status)
                                + ") — overlay will use manual F10 regions"
                        );
                    }
                    if (
                        HasBirthdayCakeInRun(player)
                        && !snapshot.extras.ContainsKey("birthday_cake_bonus")
                    )
                        MelonLogger.Warning(
                            "Birthday Cake is active (equipped or RAM pin memory) but accumulated "
                                + "word bonus was not read — scores may show Birthday 0; rebuild "
                                + "melmod or set run_state.extras.birthday_cake_bonus manually"
                        );
                }
                else
                {
                    var missing = ExportCompleteness.CollectMissing(snapshot, player);
                    if (missing.Count > 0)
                    {
                        CompanionDiagnostics.LogVerbose(
                            "Auto-export: fp="
                                + TruncateFingerprint(fingerprint)
                                + " missing="
                                + string.Join(",", missing.ToArray())
                        );
                    }
                    else
                    {
                        CompanionDiagnostics.LogVerbose(
                            "Auto-export: fp=" + TruncateFingerprint(fingerprint)
                        );
                    }
                }
                return true;
            }
            catch (Exception ex)
            {
                MelonLogger.Error("Failed to export run state: " + ex);
                return false;
            }
        }

        /// <summary>
        /// Full run_state export after word submit so historic/previous_letter are fresh for F8.
        /// </summary>
        public static bool TryExportAfterWordSubmit()
        {
            return TryExport(false, "submit");
        }

        private static string TruncateFingerprint(string fp)
        {
            if (string.IsNullOrEmpty(fp))
                return "";
            return fp.Length <= 48 ? fp : fp.Substring(0, 48) + "…";
        }

        /// <summary>
        /// Drop last_suggestion.json when run_state workflow extras advanced past the F8 embed.
        /// </summary>
        private static void TryClearLastSuggestionIfWorkflowStale(
            RunStateSnapshot snapshot,
            Player player,
            string exportTrigger = null
        )
        {
            if (snapshot?.extras == null)
                return;

            // Submit exports refresh historic for the next F8; F8 embed is always behind.
            if (string.Equals(exportTrigger, "submit", StringComparison.OrdinalIgnoreCase))
                return;

            if (
                _lastF8ExportCompletedUtc != DateTime.MinValue
                && (DateTime.UtcNow - _lastF8ExportCompletedUtc).TotalSeconds
                    < F8SuggestionClearGraceSec
            )
                return;

            var suggestion = SuggestionMatcher.Load();
            if (suggestion?.run_state_snapshot == null)
                return;

            var f8Extras = ExtrasDiffHelper.ExtrasFromRunStateObject(
                suggestion.run_state_snapshot
            );
            var diff = ExtrasDiffHelper.DiffExtras(f8Extras, snapshot.extras);
            var ctx = BuildStaleF8Context(player);
            if (ExtrasDiffHelper.IsBenignWorkflowShrinkDrift(diff, ctx))
                return;
            if (ScoringCaptureSession.IsWithinOverlaySubmitGrace())
                return;
            if (ExtrasDiffHelper.IsExpectedPostOverlaySubmitDrift(f8Extras, snapshot.extras))
            {
                SuggestionMatcher.TryClearLastSuggestionAfterSubmit();
                return;
            }
            if (ExtrasDiffHelper.HasPlayedWordSinceF8(diff))
            {
                var workflow = ExtrasDiffHelper.DescribePlayedWordSinceF8Drift(diff, ctx);
                SuggestionMatcher.TryClearLastSuggestionAfterSubmit();
                CompanionDiagnostics.LogVerbose(
                    "Cleared stale F8 suggestion (" + (workflow ?? "workflow advanced") + ")"
                );
                return;
            }

            int f8Grid;
            int liveGrid;
            var sameGrid =
                TryParseGridNumberFromExtras(f8Extras, out f8Grid)
                && TryParseGridNumberFromExtras(snapshot.extras, out liveGrid)
                && liveGrid == f8Grid
                && f8Grid >= 1;
            if (sameGrid)
            {
                var drift = ExtrasDiffHelper.DescribeStaleF8LoadoutDrift(
                    f8Extras,
                    snapshot.extras,
                    ctx
                );
                if (!string.IsNullOrEmpty(drift))
                {
                    SuggestionMatcher.TryClearLastSuggestionAfterSubmit();
                    CompanionDiagnostics.LogVerbose(
                        "Cleared stale F8 suggestion (" + drift + ")"
                    );
                    return;
                }
            }

            if (
                TryParseGridNumberFromExtras(f8Extras, out f8Grid)
                && TryParseGridNumberFromExtras(snapshot.extras, out liveGrid)
                && liveGrid > f8Grid
                && f8Grid >= 1
            )
            {
                SuggestionMatcher.TryClearLastSuggestionAfterSubmit();
                CompanionDiagnostics.LogVerbose(
                    "Cleared stale F8 suggestion (grid "
                        + f8Grid
                        + "→"
                        + liveGrid
                        + ")"
                );
            }
        }

        private static bool TryParseGridNumberFromExtras(
            Dictionary<string, string> extras,
            out int grid
        )
        {
            grid = -1;
            if (extras == null)
                return false;
            string raw;
            if (!extras.TryGetValue("grid_number", out raw) || string.IsNullOrEmpty(raw))
                return false;
            return int.TryParse(raw.Trim(), out grid) && grid >= 1;
        }

        public static string ComputeFingerprint(Player player)
        {
            if (player == null)
                return "";

            var sb = new StringBuilder();
            sb.Append(GetCharacterName(player.MyCharacter));
            sb.Append('|');
            sb.Append(player.Money);
            sb.Append('|');
            AppendItemsFingerprint(sb, player.Stickers);
            sb.Append('|');
            AppendItemsFingerprint(sb, player.Stamps);
            sb.Append('|');
            AppendBossFingerprint(sb, BossResolver.ResolveLiveForExport(player));
            sb.Append('|');
            AppendChallengeFingerprint(sb, player);
            sb.Append('|');
            AppendPinFingerprint(sb, player.MyCharacter);
            sb.Append('|');
            sb.Append(ComputeBoardFingerprint(player));
            RunStateExportFill.AppendEncounterFingerprint(sb, player);
            AppendMutatingDnaFingerprint(sb, player);
            return sb.ToString();
        }

        private static void AppendMutatingDnaFingerprint(StringBuilder sb, Player player)
        {
            if (!HasMutatingDnaStamp(player))
                return;

            var previousWords = TryGetHistoricPreviousWords(player);
            var letterCounts = ScoringContextCapture.ResolveMutatingDnaLetterCounts(
                player,
                previousWords
            );
            sb.Append('|');
            sb.Append(ScoringContextCapture.SerializeLetterCounts(letterCounts));
        }

        public static bool IsScoringCacheSubmitInFlight()
        {
            return _scoringCacheSubmitInFlight;
        }

        public static void SetScoringCacheSubmitInFlight(bool inFlight)
        {
            _scoringCacheSubmitInFlight = inFlight;
            if (inFlight)
                return;
            ClearCachedPreviousWordsForExport();
            RunStateExportFill.CachedGridNumber = -1;
            BossResolver.ClearScoringCache();
        }

        public static void CacheGridNumber(int gridNumber)
        {
            if (!_scoringCacheSubmitInFlight || gridNumber < 1)
                return;
            RunStateExportFill.CachedGridNumber = gridNumber;
        }

        public static List<HistoricWord> TryGetHistoricPreviousWordsPublic(Player player)
        {
            return TryGetHistoricPreviousWords(player);
        }

        public static void CachePreviousWordsForExport(List<HistoricWord> previousWords)
        {
            if (!_scoringCacheSubmitInFlight)
                return;
            if (previousWords != null && previousWords.Count > 0)
                _cachedPreviousWords = previousWords;
        }

        public static List<HistoricWord> GetCachedPreviousWords()
        {
            return _cachedPreviousWords;
        }

        /// <summary>
        /// Drop submit-hook cached previousWords (e.g. after Snapshot grid-start encounter reset).
        /// </summary>
        public static void ClearCachedPreviousWordsForExport()
        {
            _cachedPreviousWords = null;
            _cachedMovieCameraWordScoreBonus = -1;
        }

        /// <summary>
        /// Live encounter RED tile count from player properties (0 is valid).
        /// </summary>
        public static int TryGetRedTilesUsedEncounterPublic(Player player)
        {
            if (player == null)
                return -1;

            var redUsed = TryGetIntProperty(
                player,
                "RedTilesUsedThisEncounter",
                "RedTilesUsedEncounter",
                "RedTilesPlayedThisEncounter"
            );
            if (redUsed < 0)
                redUsed = TryGetIntProperty(
                    GameStatics.GetPlayer(),
                    "RedTilesUsedThisEncounter",
                    "RedTilesUsedEncounter"
                );
            return redUsed;
        }

        /// <summary>
        /// Merge historic_words and red_tiles_used_encounter after CalculateOverallScore.
        /// </summary>
        public static bool TryMergeTelescopeEncounterExtras(List<HistoricWord> previousWords)
        {
            try
            {
                CachePreviousWordsForExport(previousWords);
                if (previousWords == null || previousWords.Count == 0)
                    return false;

                var player = GetPlayer();
                var built = RunStateExportFill.BuildTelescopeEncounterExtras(previousWords, player);
                if (built == null || built.Count == 0)
                    return false;

                var keys = new Dictionary<string, string>();
                string existingHistoric = null;
                if (built.ContainsKey("historic_words"))
                {
                    existingHistoric = TryReadExtraValue("historic_words");
                    var newHistoric = built["historic_words"];
                    if (ShouldMergeHistoricWords(existingHistoric, newHistoric))
                        keys["historic_words"] = newHistoric;
                }

                if (built.ContainsKey("red_tiles_used_encounter"))
                    keys["red_tiles_used_encounter"] = built["red_tiles_used_encounter"];

                if (keys.Count == 0)
                    return true;

                TryMergeExtrasKeys(keys);
                return true;
            }
            catch
            {
                return false;
            }
        }

        public static bool TryMergeTelescopeEncounterExtrasAfterScore()
        {
            var player = GetPlayer();
            var words = RunStateExportFill.PickBestHistoricWordList(player);
            if (words == null || words.Count == 0)
                words = _cachedPreviousWords;
            return TryMergeTelescopeEncounterExtras(words);
        }

        private static bool ShouldMergeHistoricWords(string existing, string incoming)
        {
            if (string.IsNullOrEmpty(incoming) || incoming == "[]")
                return false;
            if (string.IsNullOrEmpty(existing) || existing == "[]")
                return true;
            if (string.Equals(existing, incoming, StringComparison.Ordinal))
                return false;

            var existingCount = RunStateExportFill.CountHistoricWordsInJson(existing);
            var incomingCount = RunStateExportFill.CountHistoricWordsInJson(incoming);
            var grid = RunStateExportFill.TryParseGridNumber(
                TryReadExtraValue("grid_number")
            );
            if (grid >= 1 && incomingCount < existingCount)
                return false;

            return RunStateExportFill.HistoricJsonRedTileCountSum(incoming)
                > RunStateExportFill.HistoricJsonRedTileCountSum(existing)
                || incomingCount > existingCount;
        }

        public static string TryReadRunStateExtra(string key)
        {
            return TryReadExtraValue(key);
        }

        private static string TryReadExtraValue(string key)
        {
            if (!File.Exists(OutputPath) || string.IsNullOrEmpty(key))
                return null;
            try
            {
                var json = File.ReadAllText(OutputPath, Encoding.UTF8);
                var root = JsonConvert.DeserializeObject<Dictionary<string, object>>(json);
                if (root == null)
                    return null;
                object extrasObj;
                if (!root.TryGetValue("extras", out extrasObj) || extrasObj == null)
                    return null;
                var existing = extrasObj as Dictionary<string, string>;
                if (existing != null && existing.TryGetValue(key, out var val))
                    return val;
                if (extrasObj is Newtonsoft.Json.Linq.JObject jobj)
                {
                    var token = jobj[key];
                    return token?.ToString();
                }
            }
            catch
            {
                // ignore
            }
            return null;
        }

        /// <summary>
        /// Merge submit-time take/card metadata into on-disk run_state.json (matched F8 suggestion).
        /// </summary>
        public static void TryMergeSubmitBoardMetadata(BoardSnapshot submitBoard)
        {
            if (submitBoard == null || !File.Exists(OutputPath))
                return;

            try
            {
                TryReadModifyWriteJsonRoot(root =>
                {
                    BoardExporter.MergeSubmitTakeFlagsIntoRunState(root, submitBoard);
                    BoardExporter.MergeSubmitCardMetadataIntoRunState(root, submitBoard);
                });
            }
            catch (Exception ex)
            {
                ExportDiagnostics.RecordMergeError(
                    "TryMergeSubmitBoardMetadata: " + ex.Message
                );
            }
        }

        public static string ComputeBoardFingerprint(Player player)
        {
            var board = BoardExporter.TryBuild(player);
            var fp = BoardExporter.ComputeBoardFingerprint(board) ?? "";
            if (CursedleExporter.IsCursedleActive())
            {
                var sb = new StringBuilder(fp);
                CursedleGuessTracker.AppendFingerprint(sb);
                return sb.ToString();
            }
            return fp;
        }

        public static Player GetPlayerForUpdate()
        {
            return GetPlayer();
        }

        public static Dictionary<string, string> BuildExtrasSnapshot()
        {
            var result = new Dictionary<string, string>();
            try
            {
                var player = GetPlayer();
                if (player == null)
                    return result;
                var snapshot = BuildSnapshot(player);
                if (snapshot.extras != null)
                {
                    foreach (var kv in snapshot.extras)
                    {
                        if (string.Equals(
                                kv.Key,
                                "bicycle_suited_on_path",
                                StringComparison.OrdinalIgnoreCase
                            ))
                            continue;
                        result[kv.Key] = kv.Value ?? "";
                    }
                }
            }
            catch (Exception ex)
            {
                ExportDiagnostics.RecordMergeError("BuildExtrasSnapshot: " + ex.Message);
            }
            return result;
        }

        /// <summary>
        /// Merge post-submit extras into run_state.json so F8 sees updated values (e.g. Birthday Cake).
        /// </summary>
        public static void TryMergeExtrasAfterSubmit()
        {
            try
            {
                // Pin WordScoreBonus first so scoring-context capture cannot leave a stale value.
                if (!TryMergeBicycleExtrasAfterScore())
                    QueueBicycleExtrasRetry();

                var freshExtras = BuildExtrasSnapshot();
                ScoringCaptureSession.MergeScoringContextIntoExtras(freshExtras);
                TryMergeSteakExtrasAfterSubmit(freshExtras);
                TryMergeTileNinjaExtrasAfterSubmit(freshExtras);
                if (freshExtras != null && freshExtras.Count > 0)
                {
                    TryMergeExtrasKeys(freshExtras);
                    if (!TryMergeBicycleExtrasAfterScore())
                        QueueBicycleExtrasRetry();

                    RefreshDiagnosticsAfterMerge("submit_merge");
                }
            }
            catch (Exception ex)
            {
                ExportDiagnostics.RecordMergeError("TryMergeExtrasAfterSubmit: " + ex.Message);
            }
            finally
            {
                SuggestionMatcher.TryClearLastSuggestionAfterSubmit();
                MelonLogger.Msg(
                    "Cleared last_suggestion.json after word submit — press F8 for the next grid."
                );
            }
        }

        private static void TryMergeSteakExtrasAfterSubmit(Dictionary<string, string> freshExtras)
        {
            if (freshExtras == null)
                return;

            try
            {
                var player = GetPlayer();
                if (player == null || !PlayerHasStampSlug(player, "steak"))
                    return;

                var rare = TryParseNonNegativeExtra(freshExtras, "rare_item_count");
                if (rare >= 0)
                    freshExtras["rare_item_count_last_known"] = rare.ToString();

                if (
                    !freshExtras.ContainsKey("steak_word_bonus_percent")
                    || string.IsNullOrEmpty(freshExtras["steak_word_bonus_percent"])
                )
                {
                    var steakPercent = ResolveSteakPercentForExport(player, freshExtras);
                    if (steakPercent >= 100)
                        freshExtras["steak_word_bonus_percent"] = steakPercent.ToString();
                }
            }
            catch (Exception ex)
            {
                ExportDiagnostics.RecordMergeError("TryMergeSteakExtrasAfterSubmit: " + ex.Message);
            }
        }

        private static void RefreshDiagnosticsAfterMerge(string trigger)
        {
            try
            {
                var player = GetPlayer();
                if (player == null || !File.Exists(OutputPath))
                    return;

                var json = File.ReadAllText(OutputPath, Encoding.UTF8);
                var snapshot = JsonConvert.DeserializeObject<RunStateSnapshot>(json);
                if (snapshot == null)
                    return;

                ExportDiagnostics.ClearMergeErrors();
                ExportDiagnostics.ApplyToSnapshot(
                    snapshot,
                    player,
                    trigger,
                    ComputeFingerprint(player),
                    0
                );
                WriteSnapshot(snapshot);
            }
            catch (Exception ex)
            {
                ExportDiagnostics.RecordMergeError("RefreshDiagnosticsAfterMerge: " + ex.Message);
            }
        }

        /// <summary>
        /// Merge Bicycle WordScoreBonus after CalculateOverallScore so F8 sees the value
        /// used for the next word (SubmitWord Postfix may run before scoring finishes).
        /// </summary>
        public static void TryMergeCachedGridNumber()
        {
            if (!_scoringCacheSubmitInFlight)
                return;

            var grid = -1;
            try
            {
                var player = GetPlayer();
                if (player != null)
                    grid = RunStateExportFill.ResolveGridNumber(player);
            }
            catch
            {
                return;
            }

            if (grid < 1)
                return;

            TryMergeExtrasKeys(
                new Dictionary<string, string>
                {
                    ["grid_number"] = grid.ToString(),
                }
            );
        }

        public static bool TryMergeBicycleExtrasAfterScore()
        {
            try
            {
                var player = GetPlayer();
                if (player == null || player.MyCharacter == null)
                    return false;

                var pin = player.MyCharacter.CharacterItem;
                var bicycleExtras = BuildBicycleExtras(pin);
                if (bicycleExtras == null || bicycleExtras.Count == 0)
                    return true;

                TryMergeExtrasKeys(bicycleExtras);
                return true;
            }
            catch
            {
                // ignore — F7 full export still available
                return false;
            }
        }

        /// <summary>
        /// Merge Movie Camera WordScoreBonus after CalculateOverallScore (encounter running total).
        /// </summary>
        public static bool TryMergeMovieCameraExtrasAfterScore()
        {
            try
            {
                var player = GetPlayer();
                if (player == null)
                    return false;

                var accumulated = TryGetMovieCameraWordScoreBonus(player);
                if (accumulated < 0)
                    return true;

                if (accumulated >= 0)
                    _cachedMovieCameraWordScoreBonus = accumulated;

                TryMergeExtrasKeys(
                    new Dictionary<string, string>
                    {
                        ["movie_camera_word_score_bonus"] = accumulated.ToString(),
                    }
                );
                return true;
            }
            catch
            {
                return false;
            }
        }

        private static int TryGetMovieCameraWordScoreBonus(Player player)
        {
            if (player == null)
                return -1;
            try
            {
                var stickers = player.GetStickers(forItemComparison: true);
                if (stickers == null)
                    return -1;
                foreach (var item in stickers)
                {
                    if (item == null)
                        continue;
                    var camera = item as MovieCamera;
                    if (camera != null)
                        return camera.WordScoreBonus;
                    var slug = Slugify(item.ArtFileName, item.Name);
                    if (slug != "movie_camera")
                        continue;
                    var bonus = TryGetIntMember(item, "WordScoreBonus");
                    if (bonus >= 0)
                        return bonus;
                }
            }
            catch
            {
                // ignore
            }
            return -1;
        }

        public static void QueueBicycleExtrasRetry()
        {
            _pendingBicycleMergeRetries = BicycleMergeRetryBudget;
            CompanionDiagnostics.LogVerbose(
                "Bicycle extras merge queued (budget " + BicycleMergeRetryBudget + ")"
            );
        }

        public static void TryFlushPendingBicycleExtrasRetry()
        {
            if (_pendingBicycleMergeRetries <= 0)
                return;
            if (TryMergeBicycleExtrasAfterScore())
            {
                _pendingBicycleMergeRetries = 0;
                return;
            }
            _pendingBicycleMergeRetries = Math.Max(0, _pendingBicycleMergeRetries - 1);
            if (_pendingBicycleMergeRetries == 0)
            {
                ExportDiagnostics.RecordMergeError(
                    "Bicycle extras merge exhausted retry budget (" + BicycleMergeRetryBudget + ")"
                );
            }
        }

        public static void TryMergeExtrasKeys(Dictionary<string, string> keysToMerge)
        {
            if (keysToMerge == null || keysToMerge.Count == 0)
                return;
            if (!File.Exists(OutputPath))
                return;

            TryReadModifyWriteJsonRoot(root =>
            {
                var merged = new Dictionary<string, string>();
                object extrasObj;
                if (root.TryGetValue("extras", out extrasObj) && extrasObj != null)
                {
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
                }

                foreach (var kv in keysToMerge)
                    merged[kv.Key] = kv.Value ?? "";

                root["extras"] = merged;
            });
        }

        /// <summary>
        /// Keep mutating_dna_letter_counts in run_state.json aligned with live stamp counters
        /// (fingerprint auto-export does not fire when only DNA counts change).
        /// </summary>
        public static void TryMergeMutatingDnaExtrasIfChanged()
        {
            try
            {
                if (UnityEngine.Time.unscaledTime - _lastMutatingDnaMergeTime < MutatingDnaMergeIntervalSec)
                    return;

                var player = GetPlayer();
                if (player == null || !HasMutatingDnaStamp(player))
                    return;

                if (!File.Exists(OutputPath))
                    return;

                var previousWords = TryGetHistoricPreviousWords(player);
                var letterCounts = ScoringContextCapture.ResolveMutatingDnaLetterCounts(
                    player,
                    previousWords
                );
                var serialized = ScoringContextCapture.SerializeLetterCounts(letterCounts);
                var onDisk = TryReadExtraValue("mutating_dna_letter_counts") ?? "{}";
                if (ExtrasDiffHelper.MutatingDnaLetterCountsEqual(onDisk, serialized))
                    return;

                TryMergeExtrasKeys(
                    new Dictionary<string, string>
                    {
                        ["mutating_dna_letter_counts"] = serialized,
                    }
                );
                _lastMutatingDnaMergeTime = UnityEngine.Time.unscaledTime;
            }
            catch (Exception ex)
            {
                ExportDiagnostics.RecordMergeError(
                    "TryMergeMutatingDnaExtrasIfChanged: " + ex.Message
                );
            }
        }

        /// <summary>
        /// Read-modify-write run_state.json with retries when Python solver holds the file.
        /// </summary>
        private static void TryReadModifyWriteJsonRoot(Action<Dictionary<string, object>> modify)
        {
            if (modify == null)
                return;

            Exception lastError = null;
            for (var attempt = 0; attempt < JsonMergeRetryCount; attempt++)
            {
                try
                {
                    if (!File.Exists(OutputPath))
                        return;

                    var json = File.ReadAllText(OutputPath, Encoding.UTF8);
                    var root = JsonConvert.DeserializeObject<Dictionary<string, object>>(json);
                    if (root == null)
                        return;

                    modify(root);
                    WriteJsonRoot(root);
                    return;
                }
                catch (IOException ex)
                {
                    lastError = ex;
                }
                catch (UnauthorizedAccessException ex)
                {
                    lastError = ex;
                }

                if (attempt + 1 < JsonMergeRetryCount)
                    Thread.Sleep(JsonMergeRetryDelayMs);
            }

            if (lastError != null)
                throw lastError;
        }

        private static void WriteJsonRoot(Dictionary<string, object> root)
        {
            var updated = JsonConvert.SerializeObject(root, Formatting.Indented);
            WriteTextAtomic(OutputPath, updated);
        }

        private static Player GetPlayer()
        {
            try
            {
                return GameStatics.GetPlayer();
            }
            catch
            {
                return null;
            }
        }

        public static RunStateSnapshot CaptureRunState(Player player)
        {
            if (player == null)
                return null;
            return BuildSnapshot(player);
        }

        private static RunStateSnapshot BuildSnapshot(Player player)
        {
            var snapshot = new RunStateSnapshot
            {
                character = GetCharacterName(player.MyCharacter),
                money = player.Money,
                pin_branch = GetPinBranch(player.MyCharacter),
                stickers = MapItems(player.Stickers, false, player),
                stamps = MapItems(player.Stamps, true, player),
            };

            var bosses = BossResolver.ResolveLiveForExport(player);
            if (bosses == null || bosses.Count == 0)
            {
                var michael = RunStateExportFill.TryFindMichaelBossFromPlayer(player);
                if (michael != null)
                    bosses = new List<BossModifier> { michael };
            }
            if (bosses == null || bosses.Count == 0)
                ClearBossState(snapshot);
            else
            {
                FillBoss(snapshot, player, bosses);
                FillBossExtras(snapshot, player, bosses);
            }
            FillPinExtras(snapshot, player);
            FillStickerStampOrchestration(snapshot, player);
            FillRunContextExtras(snapshot, player);
            QuestExporter.FillChallenge(snapshot, player);
            QuestExporter.FillEmbargoExtras(snapshot, player);
            snapshot.board = BoardExporter.TryBuild(player);
            if (snapshot.board != null)
            {
                QuestExporter.FillUpAndUpCenterExtras(snapshot, snapshot.board);
                snapshot.ui_layout = UiLayoutExporter.TryExport(snapshot.board);
            }
            RunStateExportFill.ApplyMetadata(snapshot, player);
            ShopExporter.FillShopState(snapshot, player);
            if (snapshot.board != null)
                ConsumablePlacementTracker.OnBoardSnapshot(snapshot.board);
            StripStaleBicycleWorkflowExtras(snapshot, player);
            return snapshot;
        }

        /// <summary>
        /// Drop bicycle-only workflow keys when the equipped pin is not Bicycle.
        /// </summary>
        private static void StripStaleBicycleWorkflowExtras(
            RunStateSnapshot snapshot,
            Player player
        )
        {
            if (snapshot?.extras == null || player == null)
                return;
            var pin = player.MyCharacter?.CharacterItem;
            if (pin != null && IsBicyclePin(pin))
                return;
            snapshot.extras.Remove("bicycle_suited_on_path");
            snapshot.extras.Remove("bicycle_word_score_bonus");
            snapshot.extras.Remove("cards_submitted");
        }

        private static readonly string[] WorkflowExtrasFromDisk =
        {
            "historic_words",
            "previous_word_first_letter",
            "scoring_previous_words_count",
            "red_tiles_used_encounter",
            "mutating_dna_letter_counts",
        };

        private static readonly string[] ExtrasPreserveFromDisk =
        {
            "ruler_distance_last_known",
            "rare_item_count_last_known",
            "steak_word_bonus_percent",
            "snapshot_copy_slug",
            "snapshot_copy_level",
        };

        /// <summary>
        /// F7 full export rebuilds extras from reflection; keep post-submit scoring keys.
        /// </summary>
        private static Dictionary<string, string> TryReadExtrasFromDisk()
        {
            var onDisk = new Dictionary<string, string>();
            if (!File.Exists(OutputPath))
                return onDisk;

            try
            {
                var json = File.ReadAllText(OutputPath, Encoding.UTF8);
                var root = JsonConvert.DeserializeObject<Dictionary<string, object>>(json);
                if (root == null || !root.TryGetValue("extras", out var extrasObj) || extrasObj == null)
                    return onDisk;

                var existing = extrasObj as Dictionary<string, string>;
                if (existing != null)
                {
                    foreach (var kv in existing)
                        onDisk[kv.Key] = kv.Value ?? "";
                }
                else if (extrasObj is Newtonsoft.Json.Linq.JObject jobj)
                {
                    foreach (var prop in jobj.Properties())
                        onDisk[prop.Name] = prop.Value?.ToString() ?? "";
                }
            }
            catch
            {
                // ignore — fresh export still usable
            }

            return onDisk;
        }

        private static bool IsWorkflowDiskExtraKey(string key)
        {
            if (string.IsNullOrEmpty(key))
                return false;
            foreach (var workflowKey in WorkflowExtrasFromDisk)
            {
                if (string.Equals(key, workflowKey, StringComparison.OrdinalIgnoreCase))
                    return true;
            }
            return false;
        }

        private static bool TryParseExtraPercent(string raw, out int percent)
        {
            percent = -1;
            if (string.IsNullOrWhiteSpace(raw))
                return false;
            if (!int.TryParse(raw.Trim(), out percent))
                return false;
            return percent >= 100 && percent <= 500;
        }

        /// <summary>
        /// Neapolitan percent from live MulticolouredWordsSubmitted (100 + n×5).
        /// </summary>
        private static int ResolveNeapolitanPercentForExport(Player player)
        {
            return TryGetNeapolitanPercent(player);
        }

        private static void MergePreservedExtrasFromDisk(
            RunStateSnapshot snapshot,
            Player player
        )
        {
            if (snapshot?.extras == null)
                return;

            try
            {
                var onDisk = TryReadExtrasFromDisk();
                if (onDisk.Count == 0)
                    return;

                var hasBicyclePin = player?.MyCharacter?.CharacterItem != null
                    && IsBicyclePin(player.MyCharacter.CharacterItem);

                var liveGrid = RunStateExportFill.ResolveGridNumber(player);
                string diskGridRaw;
                onDisk.TryGetValue("grid_number", out diskGridRaw);
                var diskGrid = RunStateExportFill.TryParseGridNumber(diskGridRaw);
                var gridAdvanced =
                    liveGrid >= 2 && diskGrid >= 1 && liveGrid > diskGrid;
                string diskHistoric;
                onDisk.TryGetValue("historic_words", out diskHistoric);
                var diskHistoricEmpty =
                    string.IsNullOrEmpty(diskHistoric) || diskHistoric == "[]";

                foreach (var key in ExtrasPreserveFromDisk)
                {
                    if (
                        _exportSkipWorkflowDiskMerge
                        && IsWorkflowDiskExtraKey(key)
                    )
                        continue;

                    if (
                        !hasBicyclePin
                        && (
                            string.Equals(key, "bicycle_word_score_bonus", StringComparison.OrdinalIgnoreCase)
                            || string.Equals(key, "cards_submitted", StringComparison.OrdinalIgnoreCase)
                        )
                    )
                        continue;

                    if (
                        gridAdvanced
                        && (
                            string.Equals(key, "historic_words", StringComparison.OrdinalIgnoreCase)
                            || string.Equals(
                                key,
                                "previous_word_first_letter",
                                StringComparison.OrdinalIgnoreCase
                            )
                            || string.Equals(
                                key,
                                "red_tiles_used_encounter",
                                StringComparison.OrdinalIgnoreCase
                            )
                        )
                    )
                        continue;

                    if (
                        liveGrid >= 2
                        && diskHistoricEmpty
                        && string.Equals(
                            key,
                            "previous_word_first_letter",
                            StringComparison.OrdinalIgnoreCase
                        )
                    )
                        continue;

                    if (snapshot.extras.ContainsKey(key)
                        && !string.IsNullOrEmpty(snapshot.extras[key]))
                        continue;
                    string value;
                    if (!onDisk.TryGetValue(key, out value) || string.IsNullOrEmpty(value))
                        continue;
                    snapshot.extras[key] = value;
                }

                string rulerLastKnownRaw;
                if (
                    onDisk.TryGetValue("ruler_distance_last_known", out rulerLastKnownRaw)
                    && int.TryParse((rulerLastKnownRaw ?? "").Trim(), out var rulerLastKnown)
                    && rulerLastKnown >= 0
                )
                {
                    var reflectedRuler = -1;
                    string liveRulerRaw;
                    if (
                        snapshot.extras.TryGetValue("ruler_distance", out liveRulerRaw)
                        && int.TryParse((liveRulerRaw ?? "").Trim(), out var liveRuler)
                        && liveRuler >= 0
                    )
                        reflectedRuler = liveRuler;
                    if (reflectedRuler >= 0)
                        snapshot.extras["ruler_distance"] = reflectedRuler.ToString();
                    else
                        snapshot.extras["ruler_distance"] = rulerLastKnown.ToString();
                }

                ApplyResolvedRareItemCount(snapshot, onDisk);
                ApplyResolvedTileNinjaBonus(snapshot, onDisk, player);
                ResolveBirthdayCakeBonusForExport(snapshot, player, onDisk);
            }
            catch (Exception ex)
            {
                ExportDiagnostics.RecordMergeError("MergePreservedExtrasFromDisk: " + ex.Message);
            }
        }

        /// <summary>
        /// Pre-word F8 export: live RAM only (no disk max-merge).
        /// </summary>
        private static void ResolveBirthdayCakeBonusForExport(
            RunStateSnapshot snapshot,
            Player player,
            Dictionary<string, string> onDisk
        )
        {
            if (snapshot?.extras == null || player == null)
                return;
            if (!HasBirthdayCakeInRun(player))
                return;

            var live = TryGetBirthdayCakeBonusForScoring(player);
            if (live >= 0)
                snapshot.extras["birthday_cake_bonus"] = live.ToString();
        }

        public static bool TryParseTileNinjaAdditiveForExport(string raw, out double additive)
        {
            return TryParseTileNinjaAdditive(raw, out additive);
        }

        public static double TryGetTileNinjaBonusForExport(Player player)
        {
            return TryGetTileNinjaBonus(player);
        }

        private static bool TryParseTileNinjaAdditive(string raw, out double additive)
        {
            additive = 0;
            if (string.IsNullOrWhiteSpace(raw))
                return false;
            if (
                !double.TryParse(
                    raw.Trim(),
                    System.Globalization.NumberStyles.Float,
                    System.Globalization.CultureInfo.InvariantCulture,
                    out additive
                )
            )
                return false;
            return additive > 0;
        }

        /// <summary>
        /// Read Tile Ninja from live stamp instance (game source of truth).
        /// </summary>
        public static bool TryReadTileNinjaLive(
            Player player,
            out int consumablesUsed,
            out int wordBonusPercent
        )
        {
            consumablesUsed = -1;
            wordBonusPercent = -1;
            if (player == null)
                return false;

            try
            {
                foreach (TileNinja tn in player.GetUnpackedItemsOfType(typeof(TileNinja)))
                {
                    if (tn == null)
                        continue;
                    consumablesUsed = tn.ConsumableTilesUsed;
                    wordBonusPercent = 120 + consumablesUsed * 2;
                    return true;
                }
            }
            catch (Exception ex)
            {
                ExportDiagnostics.RecordMergeError("TryReadTileNinjaLive: " + ex.Message);
            }

            consumablesUsed = TryGetTileNinjaConsumableTilesUsedFromStamps(player);
            if (consumablesUsed >= 0)
            {
                wordBonusPercent = 120 + consumablesUsed * 2;
                return true;
            }

            return false;
        }

        public static void AppendTileNinjaLiveExtras(
            Player player,
            Dictionary<string, string> extras
        )
        {
            if (player == null || extras == null || !HasTileNinjaStamp(player))
                return;

            if (TryReadTileNinjaLive(player, out var used, out var percent))
                ExportTileNinjaLiveExtras(extras, used, percent);
        }

        public static void ExportTileNinjaLiveExtras(
            Dictionary<string, string> extras,
            int consumablesUsed,
            int wordBonusPercent
        )
        {
            if (extras == null)
                return;

            var additive = consumablesUsed * 0.02;
            var serialized = additive <= 0
                ? "0"
                : additive.ToString(System.Globalization.CultureInfo.InvariantCulture);
            extras["tile_ninja_consumables_used"] = consumablesUsed.ToString();
            extras["tile_ninja_word_bonus_percent"] = wordBonusPercent.ToString();
            extras["tile_ninja_bonus"] = serialized;
            extras["tile_ninja_bonus_last_known"] = serialized;
        }

        private static bool IsTileNinjaItem(Item item)
        {
            if (item == null)
                return false;
            var name = item.Name ?? "";
            var art = item.ArtFileName ?? "";
            return name.IndexOf("Tile Ninja", StringComparison.OrdinalIgnoreCase) >= 0
                || art.IndexOf("tile_ninja", StringComparison.OrdinalIgnoreCase) >= 0;
        }

        private static int TryGetTileNinjaConsumableTilesUsedFromStamps(Player player)
        {
            if (player?.Stamps == null)
                return -1;

            foreach (var stamp in player.Stamps)
            {
                if (!IsTileNinjaItem(stamp))
                    continue;

                var count = TryGetIntMember(
                    stamp,
                    "ConsumableTilesUsed",
                    "ConsumablesPlaced",
                    "ConsumableTilesPlaced",
                    "TilesPlacedFromConsumables"
                );
                if (count >= 0)
                    return count;
            }

            return -1;
        }

        private static void ApplyResolvedTileNinjaBonus(
            RunStateSnapshot snapshot,
            Dictionary<string, string> onDisk,
            Player player
        )
        {
            if (snapshot?.extras == null || !HasTileNinjaStamp(player))
                return;

            if (TryReadTileNinjaLive(player, out var used, out var percent))
                ExportTileNinjaLiveExtras(snapshot.extras, used, percent);
            else
                ExportDiagnostics.RecordMergeError("ApplyResolvedTileNinjaBonus: live read failed");
        }

        private static void SyncTileNinjaExtrasIntoSnapshot(
            RunStateSnapshot snapshot,
            Player player
        )
        {
            if (snapshot?.extras == null || !HasTileNinjaStamp(player))
                return;

            var onDisk = TryReadExtrasFromDisk();
            try
            {
                if (TryReadTileNinjaLive(player, out var used, out var percent))
                    ExportTileNinjaLiveExtras(snapshot.extras, used, percent);
                else
                    ExportDiagnostics.RecordMergeError(
                        "SyncTileNinjaExtrasIntoSnapshot: live read failed"
                    );
            }
            catch (Exception ex)
            {
                ExportDiagnostics.RecordMergeError("SyncTileNinjaExtrasIntoSnapshot: " + ex.Message);
            }

            EnsureTileNinjaConsumablesUsedExtra(snapshot.extras, player, onDisk);
            SyncTileNinjaGridStartBaseline(snapshot, player, onDisk);
        }

        /// <summary>
        /// Always export consumables-used when Tile Ninja is equipped so the solver
        /// does not block F8 gather waiting for a key that reflection may omit.
        /// </summary>
        private static void EnsureTileNinjaConsumablesUsedExtra(
            Dictionary<string, string> extras,
            Player player,
            Dictionary<string, string> onDisk = null
        )
        {
            if (extras == null || !HasTileNinjaStamp(player))
                return;

            if (TryReadTileNinjaLive(player, out var used, out var percent))
                ExportTileNinjaLiveExtras(extras, used, percent);
        }

        /// <summary>
        /// Committed Tile Ninja bonus at grid start (before rack placements on this grid).
        /// Refreshed on grid advance; preserved across submits on the same grid.
        /// </summary>
        private static void SyncTileNinjaGridStartBaseline(
            RunStateSnapshot snapshot,
            Player player,
            Dictionary<string, string> onDisk = null
        )
        {
            if (snapshot?.extras == null || !HasTileNinjaStamp(player))
                return;

            onDisk = onDisk ?? TryReadExtrasFromDisk();
            var liveGrid = RunStateExportFill.ResolveGridNumber(player);
            var diskGridRaw = "";
            onDisk.TryGetValue("grid_number", out diskGridRaw);
            var diskGrid = RunStateExportFill.TryParseGridNumber(diskGridRaw);

            if (liveGrid >= 1 && diskGrid >= 1 && liveGrid > diskGrid)
            {
                if (TryReadTileNinjaLive(player, out var used, out _))
                {
                    snapshot.extras["tile_ninja_bonus_at_grid_start"] = (used * 0.02).ToString(
                        System.Globalization.CultureInfo.InvariantCulture
                    );
                }
                return;
            }

            string preserved;
            if (
                onDisk.TryGetValue("tile_ninja_bonus_at_grid_start", out preserved)
                && !string.IsNullOrEmpty(preserved)
            )
            {
                if (
                    TryReadTileNinjaLive(player, out var liveUsed, out _)
                    && liveUsed > 0
                    && (
                        preserved == "0"
                        || (
                            TryParseTileNinjaAdditive(preserved, out var preservedBonus)
                            && preservedBonus <= 0
                        )
                    )
                )
                {
                    snapshot.extras["tile_ninja_bonus_at_grid_start"] = (liveUsed * 0.02).ToString(
                        System.Globalization.CultureInfo.InvariantCulture
                    );
                    return;
                }

                snapshot.extras["tile_ninja_bonus_at_grid_start"] = preserved;
                return;
            }

            if (
                snapshot.extras.ContainsKey("tile_ninja_bonus_at_grid_start")
                && !string.IsNullOrEmpty(snapshot.extras["tile_ninja_bonus_at_grid_start"])
            )
                return;

            if (TryReadTileNinjaLive(player, out var seedUsed, out _))
            {
                snapshot.extras["tile_ninja_bonus_at_grid_start"] = (seedUsed * 0.02).ToString(
                    System.Globalization.CultureInfo.InvariantCulture
                );
            }
        }

        private static Dictionary<string, string> BuildTileNinjaExtrasMerge(
            int consumablesUsed,
            int wordBonusPercent
        )
        {
            var additive = consumablesUsed * 0.02;
            var serialized = additive <= 0
                ? "0"
                : additive.ToString(System.Globalization.CultureInfo.InvariantCulture);
            return new Dictionary<string, string>
            {
                ["tile_ninja_consumables_used"] = consumablesUsed.ToString(),
                ["tile_ninja_word_bonus_percent"] = wordBonusPercent.ToString(),
                ["tile_ninja_bonus"] = serialized,
                ["tile_ninja_bonus_last_known"] = serialized,
            };
        }

        /// <summary>
        /// Steak counts can decrease when rare items are sold. Prefer live reflection;
        /// else last submit capture (last_known), not a stale high rare_item_count.
        /// </summary>
        private static void ApplyResolvedRareItemCount(
            RunStateSnapshot snapshot,
            Dictionary<string, string> onDisk
        )
        {
            if (snapshot?.extras == null)
                return;

            var lastKnown = TryParseNonNegativeExtra(snapshot.extras, "rare_item_count_last_known");
            if (lastKnown < 0 && onDisk != null)
                lastKnown = TryParseNonNegativeExtra(onDisk, "rare_item_count_last_known");

            var live = TryParseNonNegativeExtra(snapshot.extras, "rare_item_count");

            var best = live >= 0 ? live : lastKnown;
            if (best < 0 && onDisk != null)
                best = TryParseNonNegativeExtra(onDisk, "rare_item_count");

            if (best < 0)
                return;

            snapshot.extras["rare_item_count"] = best.ToString();
        }

        /// <summary>
        /// Steak multiplicative WordBonus percent (e.g. 250 = ×2.5). Prefer live reflection,
        /// then rare-item formula (100 + 25 × count), then on-disk capture.
        /// </summary>
        public static int ResolveSteakPercentForExport(
            Player player,
            Dictionary<string, string> extras = null
        )
        {
            var reflected = TryGetSteakWordBonusPercent(player);
            if (reflected >= 100)
                return reflected;

            var rareCount = -1;
            if (extras != null)
                rareCount = TryParseNonNegativeExtra(extras, "rare_item_count");
            if (rareCount < 0)
                rareCount = RunStateExportFill.CountRareItemsForPlayer(player);
            if (rareCount < 0 && PlayerHasStampSlug(player, "steak"))
                rareCount = 0;
            if (rareCount >= 0)
                return 100 + 25 * rareCount;

            var onDisk = TryReadExtrasFromDisk();
            string cachedRaw;
            if (
                onDisk.TryGetValue("steak_word_bonus_percent", out cachedRaw)
                && TryParseExtraPercent(cachedRaw, out var cached)
                && cached >= 100
            )
                return cached;

            return reflected;
        }

        private static int TryParseNonNegativeExtra(
            Dictionary<string, string> extras,
            string key
        )
        {
            if (extras == null || string.IsNullOrEmpty(key))
                return -1;
            string raw;
            if (!extras.TryGetValue(key, out raw) || string.IsNullOrWhiteSpace(raw))
                return -1;
            int value;
            if (!int.TryParse(raw.Trim(), out value) || value < 0)
                return -1;
            return value;
        }

        /// <summary>
        /// Drop preserved extras from prior runs when the current loadout no longer uses them.
        /// </summary>
        private static void SanitizeLoadoutSpecificExtras(
            RunStateSnapshot snapshot,
            Player player
        )
        {
            if (snapshot?.extras == null)
                return;

            var pin = player?.MyCharacter?.CharacterItem;
            if (pin == null || !IsBicyclePin(pin))
            {
                snapshot.extras.Remove("bicycle_word_score_bonus");
                snapshot.extras.Remove("cards_submitted");
            }

            if (!HasMutatingDnaStamp(player))
                snapshot.extras.Remove("mutating_dna_letter_counts");
            else
            {
                var previousWords = TryGetHistoricPreviousWords(player);
                var rebuilt = ScoringContextCapture.ResolveMutatingDnaLetterCounts(
                    player,
                    previousWords
                );
                snapshot.extras["mutating_dna_letter_counts"] =
                    ScoringContextCapture.SerializeLetterCounts(
                        rebuilt ?? new Dictionary<string, int>()
                    );
            }

            if (!PlayerHasStampSlug(player, "neapolitan"))
            {
                snapshot.extras.Remove("neapolitan_percent");
            }
            else
            {
                snapshot.extras.Remove("neapolitan_percent_last_known");
            }

            if (!PlayerHasStampSlug(player, "ruler"))
            {
                snapshot.extras.Remove("ruler_distance");
                snapshot.extras.Remove("ruler_distance_last_known");
            }

            if (!PlayerHasStampSlug(player, "steak"))
            {
                snapshot.extras.Remove("steak_word_bonus_percent");
                snapshot.extras.Remove("rare_item_count");
                snapshot.extras.Remove("rare_item_count_last_known");
            }

            if (!PlayerHasStampSlug(player, "tile_ninja"))
            {
                snapshot.extras.Remove("tile_ninja_bonus");
                snapshot.extras.Remove("tile_ninja_bonus_last_known");
                snapshot.extras.Remove("tile_ninja_bonus_at_grid_start");
            }

            if (!PlayerHasStickerSlug(player, "snapshot"))
            {
                snapshot.extras.Remove("snapshot_copy_slug");
                snapshot.extras.Remove("snapshot_copy_level");
                snapshot.extras.Remove("snapshot_copy_captured_at");
                snapshot.extras.Remove("snapshot_copy_source");
            }

            if (!PlayerHasStampSlug(player, "twinkle_toes"))
                snapshot.extras.Remove("twinkle_toes_swap_available");
        }

        public static bool PlayerHasStampSlug(Player player, string slug)
        {
            if (player?.Stamps == null || string.IsNullOrEmpty(slug))
                return false;

            foreach (var stamp in player.Stamps)
            {
                if (stamp == null)
                    continue;
                var id = Slugify(stamp.ArtFileName, stamp.Name);
                if (string.Equals(id, slug, StringComparison.OrdinalIgnoreCase))
                    return true;
            }

            return false;
        }

        public static bool PlayerHasStickerSlug(Player player, string slug)
        {
            if (player?.Stickers == null || string.IsNullOrEmpty(slug))
                return false;

            foreach (var sticker in player.Stickers)
            {
                if (sticker == null)
                    continue;
                var id = Slugify(sticker.ArtFileName, sticker.Name);
                if (string.Equals(id, slug, StringComparison.OrdinalIgnoreCase))
                    return true;
            }

            return false;
        }

        public static int TryGetEquippedStickerLevel(Player player, string slug)
        {
            if (player?.Stickers == null || string.IsNullOrEmpty(slug))
                return 0;

            foreach (var sticker in player.Stickers)
            {
                if (sticker == null)
                    continue;
                var id = Slugify(sticker.ArtFileName, sticker.Name);
                if (!string.Equals(id, slug, StringComparison.OrdinalIgnoreCase))
                    continue;
                return Math.Max(1, sticker.TimesUpgraded + 1);
            }

            return 0;
        }

        public static StaleF8Context BuildStaleF8Context(Player player)
        {
            var ctx = new StaleF8Context();
            if (player?.MyCharacter?.CharacterItem != null)
                ctx.HasBicyclePin = IsBicyclePin(player.MyCharacter.CharacterItem);

            var mutatingDna = MutatingDnaLetterCounts.TryReadFromPlayer(player);
            ctx.HasMutatingDnaStamp = MutatingDnaLetterCounts.PlayerHasMutatingDnaStamp(player);
            ctx.HasBentoStamp = PlayerHasBentoStamp(player);
            return ctx;
        }

        private static bool PlayerHasBentoStamp(Player player)
        {
            if (player?.Stamps == null)
                return false;
            foreach (var stamp in player.Stamps)
            {
                if (stamp == null)
                    continue;
                var slug = Slugify(stamp.ArtFileName, stamp.Name);
                if (
                    string.Equals(slug, "bento_box", StringComparison.OrdinalIgnoreCase)
                    || string.Equals(slug, "bento", StringComparison.OrdinalIgnoreCase)
                )
                    return true;
            }
            return false;
        }

        private static void WriteSnapshot(RunStateSnapshot snapshot)
        {
            var dir = Path.GetDirectoryName(OutputPath);
            if (!string.IsNullOrEmpty(dir))
                Directory.CreateDirectory(dir);

            var json = JsonConvert.SerializeObject(snapshot, Formatting.Indented);
            WriteTextAtomic(OutputPath, json);
        }

        private static void WriteTextAtomic(string path, string content)
        {
            var dir = Path.GetDirectoryName(path);
            if (!string.IsNullOrEmpty(dir))
                Directory.CreateDirectory(dir);

            var temp = path + ".tmp";
            Exception lastError = null;
            for (var attempt = 0; attempt < JsonMergeRetryCount; attempt++)
            {
                File.WriteAllText(temp, content, new UTF8Encoding(false));
                try
                {
                    if (File.Exists(path))
                        File.Replace(temp, path, null);
                    else
                        File.Move(temp, path);
                    return;
                }
                catch (IOException ex)
                {
                    lastError = ex;
                }
                catch (UnauthorizedAccessException ex)
                {
                    lastError = ex;
                }

                try
                {
                    if (File.Exists(temp))
                        File.Delete(temp);
                }
                catch
                {
                    // ignore cleanup failure
                }

                if (attempt + 1 < JsonMergeRetryCount)
                    Thread.Sleep(JsonMergeRetryDelayMs);
            }

            if (lastError != null)
                throw lastError;
        }

        private static List<RunStateItem> MapItems(Item[] items, bool stampsOnly, Player player = null)
        {
            var result = new List<RunStateItem>();
            if (items == null)
                return result;

            foreach (var item in items)
            {
                if (item == null)
                    continue;

                var name = item.Name;
                if (name == null)
                    name = "";

                var mapped = new RunStateItem
                {
                    id = Slugify(item.ArtFileName, name),
                    name = name,
                    level = stampsOnly ? 1 : item.TimesUpgraded + 1,
                };
                if (!stampsOnly)
                {
                    try
                    {
                        if (item.IsHumanBoyFavouriteSticker)
                            mapped.is_human_boy_favourite = true;
                    }
                    catch
                    {
                        // optional
                    }
                }
                else if (player != null && IsHumanBoyFavouriteStamp(player, item))
                {
                    mapped.is_human_boy_favourite = true;
                }
                result.Add(mapped);
            }

            return result;
        }

        private static void ClearBossState(RunStateSnapshot snapshot)
        {
            snapshot.boss_id = "";
            snapshot.boss_name = "";
            snapshot.boss_effect = "";
            RunStateExportFill.ClearBossExtras(snapshot.extras);
        }

        private static void FillBoss(
            RunStateSnapshot snapshot,
            Player player,
            List<BossModifier> bosses
        )
        {
            if (bosses == null || bosses.Count == 0)
            {
                ClearBossState(snapshot);
                return;
            }

            var finale = RunStateExportFill.ResolveMichaelFinaleState(snapshot, player, bosses);
            if (finale.IsFinale)
            {
                var michaelBoss = RunStateExportFill.TryFindMichaelBossExtended(player, bosses);
                RunStateExportFill.ApplyMichaelFinaleExport(
                    snapshot,
                    finale.MinWordLength,
                    player,
                    michaelBoss
                );
                return;
            }

            var michaelBossDraft = RunStateExportFill.TryFindMichaelBossExtended(player, bosses);
            if (michaelBossDraft != null)
            {
                snapshot.boss_id = "michael";
                snapshot.boss_name = "Michael";
                snapshot.boss_effect = "";
                return;
            }

            BossModifier displayBoss = null;
            foreach (var b in bosses)
            {
                if (b == null)
                    continue;
                var wikiId = BossResolver.WikiBossIdFromRuntimeType(b);
                if (
                    string.IsNullOrEmpty(wikiId)
                    && !string.IsNullOrEmpty(b.Name)
                    && b.Name.IndexOf("Michael", StringComparison.OrdinalIgnoreCase) >= 0
                )
                    wikiId = "michael";
                if (wikiId == "michael" || string.IsNullOrEmpty(wikiId))
                    continue;
                displayBoss = b;
                break;
            }
            if (displayBoss == null)
                displayBoss = bosses[0];
            if (displayBoss == null)
                return;

            var bossName = displayBoss.Name;
            if (bossName == null)
                bossName = "";

            snapshot.boss_name = bossName;
            var wikiIdOut = BossResolver.WikiBossIdFromRuntimeType(displayBoss);
            if (string.IsNullOrEmpty(wikiIdOut))
                wikiIdOut = Slugify(displayBoss.PrefabFileName, bossName);
            snapshot.boss_id = wikiIdOut;
            snapshot.boss_effect = "";
        }

        private static void FillBossExtras(
            RunStateSnapshot snapshot,
            Player player,
            List<BossModifier> bosses
        )
        {
            if (bosses != null && bosses.Count > 0 && bosses[0] != null)
            {
                var boss = bosses[0];
                var cursed = boss.IsCursed;
                if (!cursed)
                    cursed = TryGetBoolField(boss, "IsCursed", "Cursed", "IsCursedBoss");
                if (!cursed)
                    cursed = TryGetBoolProperty(player, "BossIsCursed", "ActiveBossIsCursed");
                if (!cursed)
                {
                    var encounter = BossResolver.TryGetEncounter();
                    if (encounter != null)
                        cursed = TryGetBoolProperty(
                            encounter,
                            "BossIsCursed",
                            "IsCursedBoss",
                            "ActiveBossIsCursed",
                            "IsCursed"
                        );
                }
                if (!cursed)
                    cursed = TryGetBoolProperty(
                        typeof(GameStatics),
                        "BossIsCursed",
                        "ActiveBossIsCursed"
                    );
                if (cursed)
                    snapshot.extras["boss_cursed"] = "true";

                var area = TryGetIntProperty(
                    boss,
                    "AreaNumber",
                    "Area",
                    "StageNumber",
                    "Stage"
                );
                if (area < 0)
                    area = TryGetIntProperty(
                        player,
                        "AreaNumber",
                        "CurrentArea",
                        "StageNumber",
                        "CurrentStage",
                        "AreaIndex"
                    );
                if (area < 0)
                {
                    var encounter = BossResolver.TryGetEncounter();
                    if (encounter != null)
                        area = TryGetIntProperty(
                            encounter,
                            "AreaNumber",
                            "CurrentArea",
                            "StageNumber",
                            "CurrentStage",
                            "AreaIndex",
                            "Area"
                        );
                }
                if (area < 0)
                    area = TryGetIntProperty(
                        typeof(GameStatics),
                        "AreaNumber",
                        "CurrentArea",
                        "CurrentStage",
                        "StageNumber"
                    );
                if (area < 0)
                    area = BossResolver.TryGetRunStage(player);
                if (area >= 1)
                    snapshot.extras["boss_area_number"] = area.ToString();

                try
                {
                    var floorMod = boss.FloorAdjustedModification;
                    if (floorMod > 0)
                        snapshot.extras["boss_floor_modification"] = floorMod.ToString();
                }
                catch
                {
                    // optional
                }
            }

            var hyenaBlocked = TryGetBoolProperty(
                player,
                "HyenaBlocked",
                "BossBlocksSubmission",
                "MustSellBeforeSubmit",
                "SubmissionBlocked"
            );
            if (hyenaBlocked)
                snapshot.extras["hyena_blocked"] = "true";

            var gridsRemaining = TryGetIntProperty(
                player,
                "GridsRemaining",
                "GridsRemainingThisEncounter",
                "RemainingGrids"
            );
            if (gridsRemaining >= 0)
                snapshot.extras["grids_remaining"] = gridsRemaining.ToString();
        }

        private static void FillPinExtras(RunStateSnapshot snapshot, Player player)
        {
            var character = player?.MyCharacter;
            if (character == null || character.CharacterItem == null)
            {
                snapshot.extras["pin_effect"] = "";
                return;
            }

            var pin = character.CharacterItem;
            snapshot.extras["pin_effect"] = Slugify(pin.ArtFileName, pin.Name);

            if (pin.UpgradeableComponents != null && pin.UpgradeableComponents.Count >= 2)
            {
                snapshot.extras["pin_left_level"] = GetUpgradeableComponentLevel(
                    pin.UpgradeableComponents[0]
                ).ToString();
                snapshot.extras["pin_right_level"] = GetUpgradeableComponentLevel(
                    pin.UpgradeableComponents[1]
                ).ToString();
                snapshot.extras["pin_left_variable"] = GetUpgradeableVariableValue(
                    pin.UpgradeableComponents[0]
                ).ToString();
                snapshot.extras["pin_right_variable"] = GetUpgradeableVariableValue(
                    pin.UpgradeableComponents[1]
                ).ToString();
            }

            FillPinMemory(snapshot, pin);
            ReconcileBirthdayCakeExtrasFromPinMemory(snapshot);
            FillBicycleExtras(snapshot, pin);
            FillFavourites(snapshot, player, character);
        }

        private static void FillPinMemory(RunStateSnapshot snapshot, Item pin)
        {
            var items = TryGetPinMemoryItems(pin, out var exportNote);
            snapshot.extras["pin_memory_export_note"] = exportNote;
            if (items == null || items.Count == 0)
            {
                snapshot.extras["pin_memory"] = "[]";
                snapshot.extras["pin_memory_count"] = "0";
                if (IsRandomAccessMemoryPin(pin) && exportNote == "field_missing")
                {
                    MelonLogger.Warning(
                        "RAM pin: could not read ItemsInMemory (field/property missing). "
                            + "Rebuild melmod after updating the companion."
                    );
                }
                return;
            }

            var mapped = new List<RunStateItem>();
            foreach (var item in items)
            {
                if (item == null)
                    continue;
                var name = item.Name ?? "";
                var isStamp = item.IsStamp();
                var mappedItem = new RunStateItem
                {
                    id = Slugify(item.ArtFileName, name),
                    name = name,
                    level = isStamp ? 1 : item.TimesUpgraded + 1,
                    kind = isStamp ? "stamp" : "sticker",
                };
                if (IsBirthdayCakeItem(item))
                {
                    var bonus = TryGetBirthdayCakeBonusFromItem(item);
                    if (bonus >= 0)
                        mappedItem.birthday_cake_bonus = bonus;
                }
                mapped.Add(mappedItem);
            }

            snapshot.extras["pin_memory"] = JsonConvert.SerializeObject(mapped);
            snapshot.extras["pin_memory_count"] = mapped.Count.ToString();
        }

        /// <summary>
        /// Keep birthday_cake_bonus aligned with live RAM (pre-word scoring read).
        /// </summary>
        private static void ReconcileBirthdayCakeExtrasFromPinMemory(RunStateSnapshot snapshot)
        {
            if (snapshot?.extras == null)
                return;
            var player = GetPlayer();
            if (player == null || !HasBirthdayCakeInRun(player))
                return;
            var live = TryGetBirthdayCakeBonusForScoring(player);
            if (live >= 0)
                snapshot.extras["birthday_cake_bonus"] = live.ToString();
        }

        /// <summary>Random Access Memory pin (Nat-H4).</summary>
        public static bool IsRandomAccessMemoryPinItem(Item pin)
        {
            return IsRandomAccessMemoryPin(pin);
        }

        private static bool IsRandomAccessMemoryPin(Item pin)
        {
            if (pin == null)
                return false;
            var t = pin.GetType();
            return string.Equals(t.Name, "RandomAccessMemory", StringComparison.Ordinal)
                || t.FullName?.IndexOf("RandomAccessMemory", StringComparison.Ordinal) >= 0;
        }

        private static List<Item> TryGetPinMemoryItems(Item pin, out string exportNote)
        {
            exportNote = "empty";
            if (pin == null)
            {
                exportNote = "no_pin";
                return null;
            }

            // Game: public List<Item> ItemsInMemory (field, not property).
            try
            {
                var field = pin.GetType().GetField(
                    "ItemsInMemory",
                    BindingFlags.Public | BindingFlags.Instance
                );
                if (field != null)
                {
                    var fromField = CoerceItemList(field.GetValue(pin));
                    if (fromField != null)
                    {
                        exportNote = fromField.Count > 0 ? "ok" : "empty_valid";
                        return fromField;
                    }
                }
            }
            catch (Exception ex)
            {
                MelonLogger.Warning("RAM ItemsInMemory field read failed: " + ex.Message);
                exportNote = "reflection_failed";
            }

            var names = new[] { "MemoryItems", "PinMemory", "StoredItems", "Memory" };
            foreach (var name in names)
            {
                try
                {
                    var prop = pin.GetType().GetProperty(
                        name,
                        BindingFlags.Public | BindingFlags.Instance
                    );
                    if (prop == null)
                        continue;

                    var fromProp = CoerceItemList(prop.GetValue(pin, null));
                    if (fromProp != null)
                    {
                        exportNote = fromProp.Count > 0 ? "ok" : "empty_valid";
                        return fromProp;
                    }
                }
                catch
                {
                    // try next
                }
            }

            exportNote = IsRandomAccessMemoryPin(pin) ? "field_missing" : "empty";
            return null;
        }

        private static List<Item> CoerceItemList(object value)
        {
            if (value == null)
                return new List<Item>();
            var arr = value as Item[];
            if (arr != null)
                return new List<Item>(arr);
            var list = value as List<Item>;
            if (list != null)
                return list;
            var enumerable = value as System.Collections.IEnumerable;
            if (enumerable == null)
                return null;
            var result = new List<Item>();
            foreach (var entry in enumerable)
            {
                var it = entry as Item;
                if (it != null)
                    result.Add(it);
            }
            return result;
        }

        /// <summary>
        /// Bicycle pin (decompiled): WordScoreBonus accumulates across words; each submit adds
        /// (suited cards on path × right-track VariableValue) then applies the running total.
        /// </summary>
        private static void FillBicycleExtras(RunStateSnapshot snapshot, Item pin)
        {
            var bicycleExtras = BuildBicycleExtras(pin);
            if (bicycleExtras == null)
                return;

            foreach (var kv in bicycleExtras)
                snapshot.extras[kv.Key] = kv.Value;
        }

        /// <summary>
        /// After disk merge, ensure snapshot bicycle extras match live pin (fixes stale run_state).
        /// </summary>
        private static void SyncLiveBicycleExtrasIntoSnapshot(
            RunStateSnapshot snapshot,
            Player player
        )
        {
            if (snapshot?.extras == null || player?.MyCharacter == null)
                return;

            var pin = player.MyCharacter.CharacterItem;
            var bicycleExtras = BuildBicycleExtras(pin);
            if (bicycleExtras == null || bicycleExtras.Count == 0)
                return;

            var live = TryGetBicycleWordScoreBonus(pin);
            if (live < 0)
                return;

            var prior = -1;
            string priorRaw;
            if (
                snapshot.extras.TryGetValue("bicycle_word_score_bonus", out priorRaw)
                && !string.IsNullOrEmpty(priorRaw)
            )
                int.TryParse(priorRaw, out prior);

            foreach (var kv in bicycleExtras)
                snapshot.extras[kv.Key] = kv.Value;

            snapshot.extras["loadout_fingerprint"] =
                FingerprintUtil.ComputeLoadoutFingerprint(player);

            if (live > prior && prior >= 0)
            {
                CompanionDiagnostics.LogVerbose(
                    "Bicycle extras synced from live pin: "
                        + prior
                        + " → "
                        + live
                        + " (run_state was stale)"
                );
            }
        }

        /// <summary>
        /// F8 export: live Movie Camera WordScoreBonus from equipped sticker.
        /// </summary>
        private static void SyncLiveMovieCameraExtrasIntoSnapshot(
            RunStateSnapshot snapshot,
            Player player
        )
        {
            if (snapshot?.extras == null || player == null)
                return;

            if (!PlayerHasStickerSlug(player, "movie_camera"))
                return;

            var live = TryGetMovieCameraWordScoreBonus(player);
            if (live < 0)
                return;

            snapshot.extras["movie_camera_word_score_bonus"] = live.ToString();
        }

        private static Dictionary<string, string> BuildBicycleExtras(Item pin)
        {
            if (pin == null || !IsBicyclePin(pin))
                return null;

            var accumulated = TryGetBicycleWordScoreBonus(pin);
            if (accumulated < 0)
                return null;

            return new Dictionary<string, string>
            {
                ["bicycle_word_score_bonus"] = accumulated.ToString(),
                // Legacy key name used by older solver builds / docs.
                ["cards_submitted"] = accumulated.ToString(),
            };
        }

        private static bool IsBicyclePin(Item pin)
        {
            if (pin == null)
                return false;
            if (pin is Bicycle)
                return true;

            var slug = Slugify(pin.ArtFileName, pin.Name);
            if (string.IsNullOrEmpty(slug))
                return false;

            var s = slug.ToLowerInvariant();
            return s == "bicycle" || s == "bones_the_dog" || s == "bones";
        }

        /// <summary>Bicycle-family pin (Bicycle, Bones The Dog, etc.).</summary>
        public static bool IsBicyclePinItem(Item pin)
        {
            return IsBicyclePin(pin);
        }

        /// <summary>
        /// Live Bicycle pin WordScoreBonus (post-word value for the next F8 prediction).
        /// </summary>
        public static int TryGetLiveBicycleWordScoreBonus()
        {
            try
            {
                var player = GetPlayerForUpdate();
                if (player?.MyCharacter?.CharacterItem == null)
                    return -1;
                var pin = player.MyCharacter.CharacterItem;
                if (!IsBicyclePin(pin))
                    return -1;
                return TryGetBicycleWordScoreBonus(pin);
            }
            catch
            {
                return -1;
            }
        }

        private static int _previewGuardBicycleBonus = int.MinValue;
        private static int _previewGuardMovieCameraBonus = int.MinValue;
        private static bool _previewGuardActive;

        /// <summary>
        /// Snapshot mutable pin/sticker accumulators before preview CalculateOverallScore.
        /// </summary>
        public static void BeginPreviewScoreMutationGuard()
        {
            if (ScoringCaptureSession.IsSubmitInFlight())
                return;

            _previewGuardBicycleBonus = int.MinValue;
            _previewGuardMovieCameraBonus = int.MinValue;

            try
            {
                var player = GetPlayerForUpdate();
                if (player?.MyCharacter?.CharacterItem != null
                    && IsBicyclePin(player.MyCharacter.CharacterItem))
                {
                    var bonus = TryGetBicycleWordScoreBonus(player.MyCharacter.CharacterItem);
                    if (bonus >= 0)
                        _previewGuardBicycleBonus = bonus;
                }

                if (player != null && PlayerHasStickerSlug(player, "movie_camera"))
                {
                    var movie = TryGetMovieCameraWordScoreBonus(player);
                    if (movie >= 0)
                        _previewGuardMovieCameraBonus = movie;
                }
            }
            catch
            {
                // optional
            }

            _previewGuardActive =
                _previewGuardBicycleBonus >= 0 || _previewGuardMovieCameraBonus >= 0;
        }

        /// <summary>
        /// Restore pin/sticker accumulators after preview score (Bicycle mutates in ApplyWordBonus).
        /// </summary>
        public static void EndPreviewScoreMutationGuard()
        {
            if (!_previewGuardActive)
                return;

            try
            {
                var player = GetPlayerForUpdate();
                if (player?.MyCharacter?.CharacterItem != null
                    && _previewGuardBicycleBonus >= 0
                    && IsBicyclePin(player.MyCharacter.CharacterItem))
                {
                    TrySetBicycleWordScoreBonus(
                        player.MyCharacter.CharacterItem,
                        _previewGuardBicycleBonus
                    );
                }

                if (player != null && _previewGuardMovieCameraBonus >= 0)
                    TrySetMovieCameraWordScoreBonus(player, _previewGuardMovieCameraBonus);
            }
            catch
            {
                // optional
            }
            finally
            {
                _previewGuardBicycleBonus = int.MinValue;
                _previewGuardMovieCameraBonus = int.MinValue;
                _previewGuardActive = false;
            }
        }

        private static bool TrySetBicycleWordScoreBonus(Item pin, int value)
        {
            if (pin == null || value < 0)
                return false;
            try
            {
                var bicycle = pin as Bicycle;
                if (bicycle != null)
                {
                    bicycle.WordScoreBonus = value;
                    return true;
                }
                return TrySetIntMember(pin, value, "WordScoreBonus");
            }
            catch
            {
                return false;
            }
        }

        private static bool TrySetMovieCameraWordScoreBonus(Player player, int value)
        {
            if (player == null || value < 0)
                return false;
            try
            {
                var stickers = player.GetStickers(forItemComparison: true);
                if (stickers == null)
                    return false;
                foreach (var item in stickers)
                {
                    if (item == null)
                        continue;
                    var camera = item as MovieCamera;
                    if (camera != null)
                    {
                        camera.WordScoreBonus = value;
                        return true;
                    }
                    var slug = Slugify(item.ArtFileName, item.Name);
                    if (slug == "movie_camera" && TrySetIntMember(item, value, "WordScoreBonus"))
                        return true;
                }
            }
            catch
            {
                // optional
            }
            return false;
        }

        private static bool TrySetIntMember(object target, int value, params string[] names)
        {
            if (target == null)
                return false;

            foreach (var name in names)
            {
                try
                {
                    var prop = target.GetType().GetProperty(name, MemberFlags);
                    if (prop != null && prop.CanWrite)
                    {
                        prop.SetValue(target, value, null);
                        return true;
                    }

                    var field = target.GetType().GetField(name, MemberFlags);
                    if (field != null)
                    {
                        field.SetValue(target, value);
                        return true;
                    }
                }
                catch
                {
                    // try next
                }
            }

            return false;
        }

        private static int TryGetBicycleWordScoreBonus(Item pin)
        {
            if (pin == null)
                return -1;

            var bicycle = pin as Bicycle;
            if (bicycle != null)
                return bicycle.WordScoreBonus;

            return TryGetIntMember(pin, "WordScoreBonus");
        }

        /// <summary>
        /// Bicycle right-track rate (+WORD per suited card on path). Used when rewinding
        /// capture extras from applied step bonus to pre-word pin accumulator.
        /// </summary>
        public static int TryGetBicyclePerCardRate()
        {
            try
            {
                var player = GetPlayerForUpdate();
                if (player?.MyCharacter?.CharacterItem == null)
                    return 0;
                if (!IsBicyclePin(player.MyCharacter.CharacterItem))
                    return 0;

                var components = player.MyCharacter.CharacterItem.UpgradeableComponents;
                if (components != null && components.Count > 1)
                {
                    var right = GetUpgradeableVariableValue(components[1]);
                    if (right > 0)
                        return right;
                }
            }
            catch
            {
                // best-effort
            }

            return 1;
        }

        private static void FillRunContextExtras(RunStateSnapshot snapshot, Player player)
        {
            if (player == null)
                return;

            var firstGrid = TryGetIntProperty(player, "IsFirstGrid", "IsFirstGridOfEncounter");
            if (firstGrid < 0)
                firstGrid = TryGetIntProperty(
                    GameStatics.GetPlayer(),
                    "IsFirstGrid",
                    "IsFirstGridOfEncounter"
                );
            if (firstGrid < 0)
            {
                var gridIndex = TryGetIntProperty(
                    player,
                    "CurrentGridIndex",
                    "GridIndex",
                    "GridsCompletedThisEncounter"
                );
                if (gridIndex >= 0)
                    firstGrid = gridIndex == 0 ? 1 : 0;
            }
            if (firstGrid >= 0)
                snapshot.extras["is_first_grid_of_encounter"] = firstGrid > 0 ? "true" : "false";

            RunStateExportFill.EnsureEncounterHistoricExtras(snapshot, player);
            var historicWords = RunStateExportFill.PickBestHistoricWordList(player);

            RunStateExportFill.ApplyScoringCachedPreviousWordLetter(snapshot.extras, player);
            string exportedPrev;
            if (
                !snapshot.extras.TryGetValue("previous_word_first_letter", out exportedPrev)
                || string.IsNullOrEmpty(exportedPrev)
            )
            {
                var prevLetter = TryGetStringProperty(
                    player,
                    "PreviousWordFirstLetter",
                    "LastWordFirstLetter",
                    "PreviousSubmittedWordFirstLetter"
                );
                if (string.IsNullOrEmpty(prevLetter))
                    prevLetter = TryGetStringProperty(
                        GameStatics.GetPlayer(),
                        "PreviousWordFirstLetter",
                        "LastWordFirstLetter"
                    );
                if (string.IsNullOrEmpty(prevLetter))
                {
                    var scoringPrevious = GetCachedPreviousWords();
                    prevLetter = ScoringContextCapture.FirstLetterFromHistoricWords(
                        scoringPrevious
                    );
                }
                if (!string.IsNullOrEmpty(prevLetter))
                    snapshot.extras["previous_word_first_letter"] =
                        prevLetter.Substring(0, 1).ToLowerInvariant();
            }

            var redUsed = TryGetIntProperty(
                player,
                "RedTilesUsedThisEncounter",
                "RedTilesUsedEncounter",
                "RedTilesPlayedThisEncounter"
            );
            if (redUsed < 0)
                redUsed = TryGetIntProperty(
                    GameStatics.GetPlayer(),
                    "RedTilesUsedThisEncounter",
                    "RedTilesUsedEncounter"
                );
            if (redUsed < 0 && historicWords != null && historicWords.Count > 0)
                redUsed = RunStateExportFill.SumRedTilesInHistoricWords(historicWords);
            if (redUsed >= 0)
                snapshot.extras["red_tiles_used_encounter"] = redUsed.ToString();

            try
            {
                var hourglassType = Type.GetType("Hourglass");
                if (hourglassType != null)
                {
                    var method = player.GetType().GetMethod(
                        "GetUnpackedItemsOfType",
                        BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic
                    );
                    if (method != null)
                    {
                        var list = method.Invoke(player, new object[] { hourglassType }) as System.Collections.IList;
                        if (list != null)
                            snapshot.extras["hourglass_count"] = list.Count.ToString();
                    }
                }
                foreach (var sticker in player.GetStickers(forItemComparison: true) ?? new List<Item>())
                {
                    if (sticker != null && sticker.GetType().Name == "Capybara")
                    {
                        snapshot.extras["capybara_shuffle"] = "true";
                        break;
                    }
                }
            }
            catch
            {
                // optional scoring-order extras
            }

            var consumables = TryGetIntProperty(
                player,
                "ConsumableRackCount",
                "ConsumableCount",
                "ConsumablesOnRack",
                "RackConsumableCount"
            );
            if (consumables < 0)
                consumables = TryGetConsumableRackCount(player);
            if (consumables >= 0)
                snapshot.extras["consumable_rack_count"] = consumables.ToString();

            try
            {
                var rackTiles = ConsumableRackExporter.Export(player);
                if (rackTiles != null && rackTiles.Count > 0)
                    snapshot.extras["consumable_rack"] = JsonConvert.SerializeObject(rackTiles);
            }
            catch
            {
                // optional rack export
            }

            var targetNumber = TryGetLuckyDiceTargetNumber(player);
            if (targetNumber >= 0)
                snapshot.extras["target_number"] = targetNumber.ToString();
            else if (HasLuckyDiceSticker(player))
                snapshot.extras["lucky_dice_target_missing"] = "true";

            var stampsPrice = TryGetStampsShopPriceTotal(player);
            if (stampsPrice >= 0)
                snapshot.extras["stamps_shop_price_total"] = stampsPrice.ToString();

            var targetScore = TryGetIntProperty(
                player,
                "TargetScore",
                "DartboardTarget",
                "GridTargetScore",
                "CurrentTargetScore"
            );
            if (targetScore < 0)
                targetScore = TryGetIntProperty(
                    GameStatics.GetPlayer(),
                    "TargetScore",
                    "DartboardTarget",
                    "GridTargetScore"
                );
            if (targetScore >= 0)
                snapshot.extras["target_score"] = targetScore.ToString();

            var targetChess = TryGetStringProperty(
                player,
                "TargetChessPiece",
                "Magic8BallTarget",
                "SelectedChessPiece"
            );
            if (string.IsNullOrEmpty(targetChess))
                targetChess = TryGetStringProperty(
                    GameStatics.GetPlayer(),
                    "TargetChessPiece",
                    "Magic8BallTarget"
                );
            if (!string.IsNullOrEmpty(targetChess))
                snapshot.extras["target_chess_piece"] = Slugify(targetChess, targetChess);

            var michaelBonus = TryGetIntProperty(
                player,
                "MichaelBookBonus",
                "MichaelsBookBonus",
                "MichaelBookWordBonus"
            );
            if (michaelBonus < 0)
                michaelBonus = TryGetMichaelBookBonus(player);
            if (michaelBonus >= 0)
                snapshot.extras["michael_book_bonus"] = michaelBonus.ToString();

            var birthdayBonus = TryGetBirthdayCakeBonusForScoring(player);
            if (birthdayBonus >= 0)
                snapshot.extras["birthday_cake_bonus"] = birthdayBonus.ToString();

            var movieCameraBonus = TryGetMovieCameraWordScoreBonus(player);
            if (movieCameraBonus >= 0)
                snapshot.extras["movie_camera_word_score_bonus"] = movieCameraBonus.ToString();

            var neapolitanPercent = ResolveNeapolitanPercentForExport(player);
            if (neapolitanPercent >= 100)
                snapshot.extras["neapolitan_percent"] = neapolitanPercent.ToString();

            var rulerDistance = ResolveRulerDistanceForExport(player);
            if (rulerDistance >= 0)
            {
                snapshot.extras["ruler_distance"] = rulerDistance.ToString();
                snapshot.extras["ruler_distance_last_known"] = rulerDistance.ToString();
            }

            if (PlayerHasStampSlug(player, "steak"))
            {
                var steakPercent = ResolveSteakPercentForExport(player, snapshot.extras);
                if (steakPercent >= 100)
                    snapshot.extras["steak_word_bonus_percent"] = steakPercent.ToString();
            }

            var targetCurse = TryGetStringProperty(
                player,
                "TargetCurseType",
                "CrystalBallTargetCurse",
                "GridTargetCurseType"
            );
            if (string.IsNullOrEmpty(targetCurse))
                targetCurse = TryGetStringProperty(
                    GameStatics.GetPlayer(),
                    "TargetCurseType",
                    "CrystalBallTargetCurse"
                );
            if (!string.IsNullOrEmpty(targetCurse))
                snapshot.extras["target_curse_type"] = Slugify(targetCurse, targetCurse);

            var shopRestocks = TryGetIntProperty(
                player,
                "ShopRestockCount",
                "RestocksThisRun",
                "RestockCount"
            );
            if (shopRestocks < 0)
                shopRestocks = TryGetIntProperty(
                    GameStatics.GetPlayer(),
                    "ShopRestockCount",
                    "RestockCount"
                );
            if (shopRestocks >= 0)
                snapshot.extras["shop_restock_count"] = shopRestocks.ToString();

            var chessMoveTiles = TryGetIntProperty(
                player,
                "ChessMoveTileCount",
                "TilesMovedInChessMove"
            );
            if (chessMoveTiles >= 0)
                snapshot.extras["chess_move_tile_count"] = chessMoveTiles.ToString();

            var rackOverflow = TryGetIntProperty(
                player,
                "ConsumableRackOverflow",
                "RackOverflow",
                "RackIsOverflowing"
            );
            if (rackOverflow >= 0)
                snapshot.extras["rack_overflow"] = rackOverflow.ToString();

            EnsureTileNinjaConsumablesUsedExtra(snapshot.extras, player);

            if (TryGetAvocadoMushy(player))
                snapshot.extras["avocado_mushy"] = "true";

            if (
                snapshot.extras.ContainsKey("avocado_mushy")
                && snapshot.extras["avocado_mushy"] == "true"
            )
                snapshot.extras["frozen_in_shop"] = "true";

            if (HasMutatingDnaStamp(player))
            {
                var previousWords = TryGetHistoricPreviousWords(player);
                var letterCounts = ScoringContextCapture.ResolveMutatingDnaLetterCounts(
                    player,
                    previousWords
                );
                snapshot.extras["mutating_dna_letter_counts"] =
                    ScoringContextCapture.SerializeLetterCounts(letterCounts);
            }
        }

        private static readonly BindingFlags MemberFlags =
            BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;

        private static int TryGetMichaelBookBonus(Player player)
        {
            return TryGetStickerAccumulatedWordBonus(
                player,
                name =>
                    name.IndexOf("Michael", StringComparison.OrdinalIgnoreCase) >= 0
                    || name.IndexOf("Book", StringComparison.OrdinalIgnoreCase) >= 0,
                art =>
                    art.IndexOf("michael", StringComparison.OrdinalIgnoreCase) >= 0
                    || art.IndexOf("book", StringComparison.OrdinalIgnoreCase) >= 0
            );
        }

        /// <summary>
        /// Pre-word accumulated bonus for F8 prediction and score-prefix capture.
        /// </summary>
        public static int TryGetBirthdayCakeBonusForScoring(Player player)
        {
            if (player == null)
                return -1;

            var fromItems = TryGetBirthdayCakeBonusFromItemList(
                TryEnumerateBirthdayCakeItems(player)
            );
            var fromPlayer = TryGetIntProperty(
                player,
                "BirthdayCakeBonus",
                "BirthdayCakeWordBonus",
                "BirthdayCakeAccumulatedBonus"
            );

            // Item WordScoreBonus can lead player scalar by one word — prefer player at score time.
            if (fromItems >= 0 && fromPlayer >= 0)
            {
                if (fromItems > fromPlayer)
                    return fromPlayer;
                return Math.Min(fromItems, fromPlayer);
            }
            if (fromItems >= 0)
                return fromItems;
            if (fromPlayer >= 0)
                return fromPlayer;
            return -1;
        }

        /// <summary>
        /// Post-submit / next-word baseline (item can lead player by one word).
        /// </summary>
        public static int TryGetBirthdayCakeBonus(Player player)
        {
            if (player == null)
                return -1;

            var fromItems = TryGetBirthdayCakeBonusFromItemList(
                TryEnumerateBirthdayCakeItems(player)
            );
            var fromPlayer = TryGetIntProperty(
                player,
                "BirthdayCakeBonus",
                "BirthdayCakeWordBonus",
                "BirthdayCakeAccumulatedBonus"
            );

            if (fromItems >= 0 && fromPlayer >= 0)
                return Math.Max(fromItems, fromPlayer);
            if (fromItems >= 0)
                return fromItems;
            if (fromPlayer >= 0)
                return fromPlayer;
            return -1;
        }

        /// <summary>
        /// Birthday Cake running total after CalculateOverallScore (for next-word F8).
        /// Falls back to the RAM pin additive word_bonus step when reflection fails.
        /// </summary>
        public static bool TryMergeBirthdayCakeExtrasAfterScore(
            List<ScoreCalcVizInfo> steps = null
        )
        {
            try
            {
                var player = GetPlayer();
                if (player == null)
                    return false;
                if (!HasBirthdayCakeInRun(player))
                    return true;

                var bonus = TryGetBirthdayCakeBonus(player);
                if (bonus < 0)
                    return true;

                var keys = new Dictionary<string, string>
                {
                    ["birthday_cake_bonus"] = bonus.ToString(),
                };
                if (TryBuildPinMemoryMergeExtras(player, out var pinExtras))
                {
                    foreach (var kv in pinExtras)
                        keys[kv.Key] = kv.Value;
                }

                TryMergeExtrasKeys(keys);
                return true;
            }
            catch
            {
                return false;
            }
        }

        public static int TryGetBirthdayCakeBonusFromRamScoreStep(List<ScoreCalcVizInfo> steps)
        {
            if (steps == null)
                return -1;

            for (var i = 0; i < steps.Count; i++)
            {
                var step = steps[i];
                if (step?.WordBonus == null)
                    continue;
                if (step.WordBonus.IsMultiplicative || step.WordBonus.IsPoison)
                    continue;
                if (step.RelevantItem == null || !IsRandomAccessMemoryPinItem(step.RelevantItem))
                    continue;

                var score = step.WordBonus.Bonus != null ? step.WordBonus.Bonus.Score : 0L;
                if (score > 0L)
                    return (int)score;
            }

            return -1;
        }

        private static IEnumerable<Item> TryEnumerateBirthdayCakeItems(Player player)
        {
            var seen = new HashSet<Item>();
            if (player.Stickers != null)
            {
                foreach (var sticker in player.Stickers)
                {
                    if (sticker == null || !seen.Add(sticker))
                        continue;
                    yield return sticker;
                }
            }

            List<Item> comparisonStickers = null;
            try
            {
                comparisonStickers = player.GetStickers(forItemComparison: true);
            }
            catch
            {
                comparisonStickers = null;
            }

            if (comparisonStickers != null)
            {
                foreach (var sticker in comparisonStickers)
                {
                    if (sticker == null || !seen.Add(sticker))
                        continue;
                    yield return sticker;
                }
            }

            var pin = player.MyCharacter?.CharacterItem;
            if (pin == null || !IsRandomAccessMemoryPin(pin))
                yield break;

            var memoryItems = TryGetPinMemoryItems(pin, out _);
            if (memoryItems == null)
                yield break;

            foreach (var item in memoryItems)
            {
                if (item == null || !seen.Add(item))
                    continue;
                yield return item;
            }
        }

        private static int TryGetBirthdayCakeBonusFromItemList(IEnumerable<Item> items)
        {
            if (items == null)
                return -1;

            var best = -1;
            foreach (var item in items)
            {
                if (!IsBirthdayCakeItem(item))
                    continue;
                var bonus = TryGetBirthdayCakeBonusFromItem(item);
                if (bonus > best)
                    best = bonus;
            }

            return best;
        }

        /// <summary>
        /// Re-serialize pin_memory from live RAM so birthday_cake_bonus stays aligned with extras.
        /// </summary>
        private static bool TryBuildPinMemoryMergeExtras(
            Player player,
            out Dictionary<string, string> extras
        )
        {
            extras = null;
            if (player == null)
                return false;

            var pin = player.MyCharacter?.CharacterItem;
            if (pin == null || !IsRandomAccessMemoryPin(pin))
                return false;

            var snapshot = new RunStateSnapshot();
            FillPinMemory(snapshot, pin);
            if (snapshot.extras == null || snapshot.extras.Count == 0)
                return false;

            extras = new Dictionary<string, string>();
            if (snapshot.extras.TryGetValue("pin_memory", out var pinMemory))
                extras["pin_memory"] = pinMemory;
            if (snapshot.extras.TryGetValue("pin_memory_count", out var pinCount))
                extras["pin_memory_count"] = pinCount;
            if (snapshot.extras.TryGetValue("pin_memory_export_note", out var pinNote))
                extras["pin_memory_export_note"] = pinNote;
            return extras.Count > 0;
        }

        private static int TryGetBirthdayCakeBonusFromRamPinMemory(Player player)
        {
            return TryGetBirthdayCakeBonusFromItemList(TryEnumerateBirthdayCakeItems(player));
        }

        private static int TryGetBirthdayCakeBonusFromItem(Item item)
        {
            if (item == null)
                return -1;

            try
            {
                var cake = item as BirthdayCake;
                if (cake != null)
                    return (int)cake.WordScoreBonus;
            }
            catch
            {
                // fall through to reflection
            }

            var direct = TryGetIntMember(item, "WordScoreBonus");
            if (direct >= 0)
                return direct;

            var bonus = TryGetAccumulatedWordBonusFromObject(item);
            if (bonus >= 0)
                return bonus;

            foreach (var nested in TryGetNestedStickerTargets(item))
            {
                bonus = TryGetAccumulatedWordBonusFromObject(nested);
                if (bonus >= 0)
                    return bonus;
            }

            return -1;
        }

        private static bool IsBirthdayCakeItem(Item item)
        {
            if (item == null)
                return false;
            var name = item.Name ?? "";
            var art = item.ArtFileName ?? "";
            if (name.IndexOf("Birthday", StringComparison.OrdinalIgnoreCase) >= 0)
                return true;
            return art.IndexOf("birthday", StringComparison.OrdinalIgnoreCase) >= 0;
        }

        /// <summary>
        /// Ruler stamp cumulative non-adjacent Distance (pre-submit). Returns -1 if unknown.
        /// </summary>
        public static int TryGetRulerDistance(Player player)
        {
            if (player?.Stamps == null)
                return -1;

            foreach (var stamp in player.Stamps)
            {
                if (stamp == null)
                    continue;
                var name = stamp.Name ?? "";
                var art = stamp.ArtFileName ?? "";
                if (
                    name.IndexOf("Ruler", StringComparison.OrdinalIgnoreCase) < 0
                    && art.IndexOf("ruler", StringComparison.OrdinalIgnoreCase) < 0
                )
                    continue;

                var distance = TryGetRulerDistanceFromObject(stamp);
                if (distance >= 0)
                    return distance;

                foreach (var nested in TryGetNestedStickerTargets(stamp))
                {
                    distance = TryGetRulerDistanceFromObject(nested);
                    if (distance >= 0)
                        return distance;
                }
            }

            return -1;
        }

        private static int TryGetRulerDistanceFromObject(object target)
        {
            if (target == null)
                return -1;

            return TryGetIntMember(target, "Distance");
        }

        private static int ResolveRulerDistanceForExport(Player player)
        {
            var reflected = TryGetRulerDistance(player);
            if (reflected >= 0)
                return reflected;
            var onDisk = TryReadExtrasFromDisk();
            string cachedRaw;
            if (
                onDisk.TryGetValue("ruler_distance_last_known", out cachedRaw)
                && int.TryParse((cachedRaw ?? "").Trim(), out var cached)
                && cached >= 0
            )
                return cached;
            return reflected;
        }

        /// <summary>
        /// Neapolitan stamp multiplicative WordBonus percent (e.g. 110 = ×1.1). Returns -1 if unknown.
        /// </summary>
        public static int TryGetNeapolitanPercent(Player player)
        {
            if (player?.Stamps == null)
                return -1;

            foreach (var stamp in player.Stamps)
            {
                if (stamp == null)
                    continue;
                var name = stamp.Name ?? "";
                var art = stamp.ArtFileName ?? "";
                if (
                    name.IndexOf("Neapolitan", StringComparison.OrdinalIgnoreCase) < 0
                    && art.IndexOf("neapolitan", StringComparison.OrdinalIgnoreCase) < 0
                )
                    continue;

                var percent = TryGetNeapolitanPercentFromObject(stamp);
                if (percent >= 0)
                    return percent;

                foreach (var nested in TryGetNestedStickerTargets(stamp))
                {
                    percent = TryGetNeapolitanPercentFromObject(nested);
                    if (percent >= 0)
                        return percent;
                }
            }

            return -1;
        }

        private static int TryGetNeapolitanPercentFromObject(object target)
        {
            if (target == null)
                return -1;

            var count = TryGetIntMember(target, "MulticolouredWordsSubmitted");
            if (count >= 0)
            {
                var percent = 100 + count * 5;
                if (percent < 100)
                    return 100;
                if (percent > 500)
                    return 500;
                return percent;
            }

            var bonus = TryGetAccumulatedWordBonusFromObject(target);
            if (bonus >= 100 && bonus <= 500)
                return bonus;

            return -1;
        }

        /// <summary>
        /// Steak stamp multiplicative WordBonus percent (e.g. 250 = ×2.5). Returns -1 if unknown.
        /// </summary>
        public static int TryGetSteakWordBonusPercent(Player player)
        {
            if (player?.Stamps == null)
                return -1;

            foreach (var stamp in player.Stamps)
            {
                if (stamp == null)
                    continue;
                var name = stamp.Name ?? "";
                var art = stamp.ArtFileName ?? "";
                if (
                    name.IndexOf("Steak", StringComparison.OrdinalIgnoreCase) < 0
                    && art.IndexOf("steak", StringComparison.OrdinalIgnoreCase) < 0
                )
                    continue;

                var percent = TryGetSteakWordBonusPercentFromObject(stamp);
                if (percent >= 0)
                    return percent;

                foreach (var nested in TryGetNestedStickerTargets(stamp))
                {
                    percent = TryGetSteakWordBonusPercentFromObject(nested);
                    if (percent >= 0)
                        return percent;
                }
            }

            return -1;
        }

        private static int TryGetSteakWordBonusPercentFromObject(object target)
        {
            if (target == null)
                return -1;

            var bonus = TryGetAccumulatedWordBonusFromObject(target);
            if (bonus >= 100 && bonus <= 500)
                return bonus;

            return -1;
        }

        /// <summary>
        /// Lucky Dice grid target number (tile face value). Returns -1 if unknown.
        /// </summary>
        public static int TryGetLuckyDiceTargetNumber(Player player)
        {
            var targetNumber = TryGetIntProperty(
                player,
                "TargetNumber",
                "LuckyDiceTarget",
                "GridTargetNumber",
                "CurrentTargetNumber",
                "DiceTarget",
                "NumberTarget",
                "ChosenTargetNumber",
                "SelectedTargetNumber",
                "LuckyNumber"
            );
            if (targetNumber < 0)
                targetNumber = TryGetIntProperty(
                    GameStatics.GetPlayer(),
                    "TargetNumber",
                    "LuckyDiceTarget",
                    "GridTargetNumber",
                    "CurrentTargetNumber",
                    "DiceTarget",
                    "NumberTarget"
                );

            if (targetNumber < 0)
            {
                var grid = ResolveActiveGridData();
                if (grid != null)
                    targetNumber = TryGetIntProperty(
                        grid,
                        "TargetNumber",
                        "LuckyDiceTarget",
                        "GridTargetNumber",
                        "CurrentTargetNumber",
                        "DiceTarget",
                        "NumberTarget"
                    );
            }

            if (targetNumber < 0)
                targetNumber = TryGetStickerTargetNumber(
                    player,
                    name =>
                        name.IndexOf("Lucky", StringComparison.OrdinalIgnoreCase) >= 0
                        && name.IndexOf("Dice", StringComparison.OrdinalIgnoreCase) >= 0,
                    art => art.IndexOf("lucky_dice", StringComparison.OrdinalIgnoreCase) >= 0
                        || art.IndexOf("luckydice", StringComparison.OrdinalIgnoreCase) >= 0
                );

            if (targetNumber < 0 && player != null)
            {
                foreach (var sticker in player.GetStickers(forItemComparison: true) ?? new List<Item>())
                {
                    if (sticker == null)
                        continue;
                    if (!string.Equals(sticker.GetType().Name, "LuckyDice", StringComparison.Ordinal))
                        continue;
                    targetNumber = TryGetTargetNumberFromObject(sticker);
                    if (targetNumber >= 0)
                        break;
                    foreach (var nested in TryGetNestedStickerTargets(sticker))
                    {
                        targetNumber = TryGetTargetNumberFromObject(nested);
                        if (targetNumber >= 0)
                            break;
                    }
                    if (targetNumber >= 0)
                        break;
                }
            }

            if (targetNumber >= 0 && !IsValidLuckyDiceTarget(targetNumber))
                targetNumber = -1;

            return targetNumber;
        }

        private static int TryGetStickerTargetNumber(
            Player player,
            Func<string, bool> nameMatch,
            Func<string, bool> artMatch
        )
        {
            if (player?.Stickers == null)
                return -1;

            foreach (var sticker in player.Stickers)
            {
                if (sticker == null)
                    continue;
                var name = sticker.Name ?? "";
                var art = sticker.ArtFileName ?? "";
                if (!nameMatch(name) && !artMatch(art))
                    continue;

                var target = TryGetTargetNumberFromObject(sticker);
                if (target >= 0)
                    return target;

                foreach (var nested in TryGetNestedStickerTargets(sticker))
                {
                    target = TryGetTargetNumberFromObject(nested);
                    if (target >= 0)
                        return target;
                }
            }

            return -1;
        }

        private static int TryGetTargetNumberFromObject(object target)
        {
            if (target == null)
                return -1;

            var named = TryGetIntMember(
                target,
                "TargetNumber",
                "LuckyDiceTarget",
                "GridTargetNumber",
                "CurrentTargetNumber",
                "DiceTarget",
                "NumberTarget",
                "ChosenTargetNumber",
                "SelectedTargetNumber",
                "LuckyNumber",
                "DiceNumber",
                "_diceNumber",
                "diceNumber",
                "Target",
                "CurrentTarget",
                "_targetNumber",
                "_luckyDiceTarget",
                "targetNumber",
                "luckyDiceTarget"
            );
            if (named >= 0 && IsValidLuckyDiceTarget(named))
                return named;

            var invoked = TryInvokeTargetNumberMethod(target);
            if (invoked >= 0)
                return invoked;

            return TryScanTargetNumberMembers(target);
        }

        private static bool IsValidLuckyDiceTarget(int value) => value >= 1 && value <= 6;

        private static int TryScanTargetNumberMembers(object target)
        {
            var type = target.GetType();
            foreach (var prop in type.GetProperties(MemberFlags))
            {
                var value = TryReadIntLike(prop.GetValue(target, null));
                if (value < 0 || !IsValidLuckyDiceTarget(value))
                    continue;
                if (!MemberNameLooksLikeTargetNumber(prop.Name))
                    continue;
                return value;
            }

            foreach (var field in type.GetFields(MemberFlags))
            {
                var value = TryReadIntLike(field.GetValue(target));
                if (value < 0 || !IsValidLuckyDiceTarget(value))
                    continue;
                if (!MemberNameLooksLikeTargetNumber(field.Name))
                    continue;
                return value;
            }

            return -1;
        }

        private static int TryInvokeTargetNumberMethod(object target)
        {
            var type = target.GetType();
            foreach (var method in type.GetMethods(MemberFlags))
            {
                if (method.GetParameters().Length != 0)
                    continue;
                var lower = method.Name.ToLowerInvariant();
                if (
                    !lower.Contains("target")
                    && !lower.Contains("dice")
                    && !lower.Contains("lucky")
                    && !lower.Contains("number")
                )
                    continue;
                if (
                    lower.Contains("set")
                    || lower.Contains("add")
                    || lower.Contains("init")
                    || lower.Contains("sprite")
                    || lower.Contains("description")
                    || lower.Contains("animation")
                    || lower.Contains("effect")
                    || lower.Contains("bonus")
                )
                    continue;

                try
                {
                    var raw = method.Invoke(target, null);
                    var value = TryReadIntLike(raw);
                    if (value >= 0 && IsValidLuckyDiceTarget(value))
                        return value;
                }
                catch
                {
                    // try next
                }
            }

            return -1;
        }

        private static bool MemberNameLooksLikeTargetNumber(string name)
        {
            if (string.IsNullOrEmpty(name))
                return false;

            var lower = name.ToLowerInvariant();
            if (
                lower.Contains("level")
                || lower.Contains("upgrade")
                || lower.Contains("cost")
                || lower.Contains("price")
                || lower.Contains("rarity")
                || lower.Contains("index")
                || lower.Contains("bonus")
                || lower.Contains("score")
            )
                return false;

            return (lower.Contains("target") && lower.Contains("number"))
                || (lower.Contains("dice") && lower.Contains("number"))
                || lower == "targetnumber"
                || lower == "dicenumber"
                || lower == "_dicenumber"
                || lower == "luckydicetarget"
                || lower == "gridtargetnumber";
        }

        private static GridData ResolveActiveGridData()
        {
            GridData grid = null;

            var encounter = UnityEngine.Object.FindAnyObjectByType<EncounterController>();
            if (encounter != null)
            {
                try
                {
                    grid = encounter.GetGridData();
                }
                catch
                {
                    grid = null;
                }
            }

            if (grid != null)
                return grid;

            var puzzle = UnityEngine.Object.FindAnyObjectByType<PuzzleController>();
            if (puzzle != null)
            {
                try
                {
                    grid = puzzle.GetGridData();
                }
                catch
                {
                    grid = null;
                }
            }

            return grid;
        }

        /// <summary>
        /// Tile Ninja live multiplicative WordBonus percent (e.g. 124 = ×1.24). Returns -1 if unknown.
        /// </summary>
        public static int TryGetTileNinjaWordBonusPercent(Player player)
        {
            if (TryReadTileNinjaLive(player, out _, out var percent))
                return percent;

            if (player?.Stamps == null)
                return -1;

            foreach (var stamp in player.Stamps)
            {
                if (!IsTileNinjaItem(stamp))
                    continue;

                var nestedPercent = TryGetTileNinjaWordBonusPercentFromObject(stamp);
                if (nestedPercent >= 0)
                    return nestedPercent;

                foreach (var nested in TryGetNestedStickerTargets(stamp))
                {
                    nestedPercent = TryGetTileNinjaWordBonusPercentFromObject(nested);
                    if (nestedPercent >= 0)
                        return nestedPercent;
                }
            }

            return -1;
        }

        private static int TryGetTileNinjaWordBonusPercentFromObject(object target)
        {
            if (target == null)
                return -1;

            var bonus = TryGetAccumulatedWordBonusFromObject(target);
            if (bonus >= 120 && bonus <= 300)
                return bonus;

            return -1;
        }

        /// <summary>
        /// Additive ×WORD bonus for Tile Ninja (wiki: +0.02 per consumable placed).
        /// Returns -1 if unknown.
        /// </summary>
        private static int TryGetTileNinjaConsumableTilesUsed(Player player)
        {
            if (TryReadTileNinjaLive(player, out var used, out _))
                return used;

            return TryGetTileNinjaConsumableTilesUsedFromStamps(player);
        }

        private static double TryGetTileNinjaBonus(Player player)
        {
            var consumablesUsed = TryGetTileNinjaConsumableTilesUsed(player);
            if (consumablesUsed >= 0)
                return consumablesUsed * 0.02;

            var direct = TryGetDoubleProperty(
                player,
                "TileNinjaBonus",
                "TileNinjaMultiplierBonus",
                "TileNinjaWordBonus"
            );
            if (direct > 0)
                return direct;

            var placed = TryGetIntProperty(
                player,
                "ConsumablesPlaced",
                "ConsumableTilesPlaced",
                "TilesPlacedFromConsumables"
            );
            if (placed > 0)
                return placed * 0.02;

            var stampBonus = TryGetStampMultiplierBonus(
                player,
                name => name.IndexOf("Tile Ninja", StringComparison.OrdinalIgnoreCase) >= 0,
                art => art.IndexOf("tile_ninja", StringComparison.OrdinalIgnoreCase) >= 0,
                new[]
                {
                    "TileNinjaBonus",
                    "MultiplierBonus",
                    "WordMultiplierBonus",
                    "Bonus",
                }
            );
            if (stampBonus > 0)
                return stampBonus;

            var wordPercent = TryGetTileNinjaWordBonusPercent(player);
            if (wordPercent >= 120)
                return (wordPercent / 100.0) - 1.2;

            return -1;
        }

        /// <summary>
        /// Additive Tile Ninja bonus from score steps (total percent minus base 1.2). Returns -1 if unknown.
        /// </summary>
        public static double TryGetTileNinjaAdditiveFromSteps(List<ScoreCalcVizInfo> steps)
        {
            if (steps == null)
                return -1;

            try
            {
                for (var i = 0; i < steps.Count; i++)
                {
                    var step = steps[i];
                    if (step?.RelevantItem == null || step.WordBonus == null)
                        continue;

                    var itemId = Slugify(
                        step.RelevantItem.ArtFileName,
                        step.RelevantItem.Name
                    );
                    if (!string.Equals(itemId, "tile_ninja", StringComparison.OrdinalIgnoreCase))
                        continue;

                    if (!step.WordBonus.IsMultiplicative || step.WordBonus.IsPoison)
                        continue;

                    var bonus = step.WordBonus.Bonus != null ? step.WordBonus.Bonus.Score : 0L;
                    if (bonus < 120L)
                        continue;

                    var additive = (bonus / 100.0) - 1.2;
                    return additive >= 0 ? additive : -1;
                }
            }
            catch
            {
                // best-effort only
            }

            return -1;
        }

        /// <summary>
        /// Persist Tile Ninja additive bonus after CalculateOverallScore (for next F8).
        /// </summary>
        public static bool TryMergeTileNinjaExtrasAfterScore(List<ScoreCalcVizInfo> steps = null)
        {
            try
            {
                var player = GetPlayer();
                if (player == null || !PlayerHasStampSlug(player, "tile_ninja"))
                    return true;

                if (TryReadTileNinjaLive(player, out var used, out var percent))
                {
                    TryMergeExtrasKeys(BuildTileNinjaExtrasMerge(used, percent));
                    return true;
                }

                var additive = TryGetTileNinjaAdditiveFromSteps(steps);
                if (additive < 0)
                    return true;

                var usedFromSteps = (int)Math.Round(additive / 0.02);
                TryMergeExtrasKeys(
                    BuildTileNinjaExtrasMerge(usedFromSteps, 120 + usedFromSteps * 2)
                );
                return true;
            }
            catch
            {
                return false;
            }
        }

        private static void TryMergeTileNinjaExtrasAfterSubmit(Dictionary<string, string> freshExtras)
        {
            if (freshExtras == null)
                return;

            try
            {
                var player = GetPlayer();
                if (player == null || !PlayerHasStampSlug(player, "tile_ninja"))
                    return;

                if (TryReadTileNinjaLive(player, out var used, out var percent))
                {
                    foreach (var kv in BuildTileNinjaExtrasMerge(used, percent))
                        freshExtras[kv.Key] = kv.Value;
                    return;
                }

                var additive = TryGetTileNinjaAdditiveFromSteps(
                    CalculateOverallScorePatch.LastCalculatedSteps
                );
                if (additive < 0)
                    return;

                var usedFromSteps = (int)Math.Round(additive / 0.02);
                foreach (
                    var kv in BuildTileNinjaExtrasMerge(usedFromSteps, 120 + usedFromSteps * 2)
                )
                    freshExtras[kv.Key] = kv.Value;
            }
            catch (Exception ex)
            {
                ExportDiagnostics.RecordMergeError(
                    "TryMergeTileNinjaExtrasAfterSubmit: " + ex.Message
                );
            }
        }

        private static bool TryGetAvocadoMushy(Player player)
        {
            if (TryGetBoolProperty(player, "AvocadoMushy", "MushyAvocado", "HasMushyAvocado"))
                return true;

            if (player?.Stamps == null)
                return false;

            foreach (var stamp in player.Stamps)
            {
                if (stamp == null)
                    continue;
                var name = stamp.Name ?? "";
                var art = stamp.ArtFileName ?? "";
                var isAvocado =
                    name.IndexOf("Avocado", StringComparison.OrdinalIgnoreCase) >= 0
                    || art.IndexOf("avocado", StringComparison.OrdinalIgnoreCase) >= 0;
                if (!isAvocado)
                    continue;

                if (TryGetBoolProperty(stamp, "IsMushy", "Mushy", "IsFrozen", "Frozen"))
                    return true;

                var display = name ?? "";
                if (display.IndexOf("Mushy", StringComparison.OrdinalIgnoreCase) >= 0)
                    return true;
            }

            return false;
        }

        private static double TryGetStampMultiplierBonus(
            Player player,
            Func<string, bool> nameMatch,
            Func<string, bool> artMatch,
            string[] bonusFieldNames
        )
        {
            if (player?.Stamps == null)
                return -1;

            foreach (var stamp in player.Stamps)
            {
                if (stamp == null)
                    continue;
                var name = stamp.Name ?? "";
                var art = stamp.ArtFileName ?? "";
                if (!nameMatch(name) && !artMatch(art))
                    continue;

                foreach (var field in bonusFieldNames)
                {
                    var bonus = TryGetDoubleProperty(stamp, field);
                    if (bonus >= 0)
                        return bonus;
                }
            }

            return -1;
        }

        private static int TryGetStickerAccumulatedWordBonus(
            Player player,
            Func<string, bool> nameMatch,
            Func<string, bool> artMatch
        )
        {
            if (player?.Stickers == null)
                return -1;

            foreach (var sticker in player.Stickers)
            {
                if (sticker == null)
                    continue;
                var name = sticker.Name ?? "";
                var art = sticker.ArtFileName ?? "";
                if (!nameMatch(name) && !artMatch(art))
                    continue;

                var bonus = TryGetAccumulatedWordBonusFromObject(sticker);
                if (bonus >= 0)
                    return bonus;

                foreach (var nested in TryGetNestedStickerTargets(sticker))
                {
                    bonus = TryGetAccumulatedWordBonusFromObject(nested);
                    if (bonus >= 0)
                        return bonus;
                }
            }

            return -1;
        }

        private static IEnumerable<object> TryGetNestedStickerTargets(Item sticker)
        {
            var seen = new HashSet<object>();
            foreach (var propName in new[]
            {
                "Sticker",
                "StickerEffect",
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
                    var prop = sticker.GetType().GetProperty(propName, MemberFlags);
                    if (prop != null)
                        nested = prop.GetValue(sticker, null);
                    if (nested == null)
                    {
                        var field = sticker.GetType().GetField(propName, MemberFlags);
                        if (field != null)
                            nested = field.GetValue(sticker);
                    }
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

        private static int TryGetAccumulatedWordBonusFromObject(object target)
        {
            if (target == null)
                return -1;

            var named = TryGetIntMember(
                target,
                "WordBonus",
                "BonusWordScore",
                "AccumulatedBonus",
                "CurrentBonus",
                "GetWordScore",
                "WordScoreBonus",
                "AccumulatedWordScore",
                "WordScore",
                "TotalWordScore",
                "CurrentWordScore",
                "BonusScore",
                "CakeBonus",
                "_wordBonus",
                "_bonusWordScore",
                "_accumulatedBonus",
                "_currentBonus",
                "wordBonus",
                "bonusWordScore"
            );
            if (named >= 0)
                return named;

            var scanned = TryScanAccumulatedWordBonusMembers(target);
            if (scanned >= 0)
                return scanned;

            return TryInvokeWordBonusMethod(target);
        }

        private static int TryScanAccumulatedWordBonusMembers(object target)
        {
            var type = target.GetType();
            var best = -1;

            foreach (var prop in type.GetProperties(MemberFlags))
            {
                var value = TryReadIntLike(prop.GetValue(target, null));
                if (value < 0 || !MemberNameLooksLikeWordBonus(prop.Name))
                    continue;
                if (value > best)
                    best = value;
            }

            foreach (var field in type.GetFields(MemberFlags))
            {
                var value = TryReadIntLike(field.GetValue(target));
                if (value < 0 || !MemberNameLooksLikeWordBonus(field.Name))
                    continue;
                if (value > best)
                    best = value;
            }

            return best;
        }

        private static bool MemberNameLooksLikeWordBonus(string name)
        {
            if (string.IsNullOrEmpty(name))
                return false;

            var lower = name.ToLowerInvariant();
            if (
                lower.Contains("level")
                || lower.Contains("upgrade")
                || lower.Contains("cost")
                || lower.Contains("price")
                || lower.Contains("rarity")
                || lower.Contains("index")
                || lower == "bonus"
            )
                return false;

            return lower.Contains("word")
                || lower.Contains("bonus")
                || lower.Contains("accumul")
                || (lower.Contains("score") && !lower.Contains("high"));
        }

        private static int TryInvokeWordBonusMethod(object target)
        {
            var type = target.GetType();
            foreach (var method in type.GetMethods(MemberFlags))
            {
                if (method.GetParameters().Length != 0)
                    continue;
                var lower = method.Name.ToLowerInvariant();
                if (
                    !lower.Contains("word")
                    && !lower.Contains("bonus")
                    && !lower.Contains("score")
                )
                    continue;
                if (lower.Contains("set") || lower.Contains("add") || lower.Contains("init"))
                    continue;

                try
                {
                    var raw = method.Invoke(target, null);
                    var value = TryReadIntLike(raw);
                    if (value >= 0)
                        return value;
                }
                catch
                {
                    // try next
                }
            }

            return -1;
        }

        private static int TryGetIntMember(object target, params string[] names)
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

        private static bool HasMutatingDnaStamp(Player player)
        {
            if (player?.Stamps == null)
                return false;

            foreach (var stamp in player.Stamps)
            {
                if (stamp == null)
                    continue;
                var name = stamp.Name ?? "";
                var art = stamp.ArtFileName ?? "";
                if (name.IndexOf("Mutating", StringComparison.OrdinalIgnoreCase) >= 0)
                    return true;
                if (name.IndexOf("DNA", StringComparison.OrdinalIgnoreCase) >= 0)
                    return true;
                if (art.IndexOf("mutating", StringComparison.OrdinalIgnoreCase) >= 0)
                    return true;
                if (art.IndexOf("dna", StringComparison.OrdinalIgnoreCase) >= 0)
                    return true;
            }

            return false;
        }

        private static bool HasTileNinjaStamp(Player player)
        {
            if (player?.Stamps == null)
                return false;

            foreach (var stamp in player.Stamps)
            {
                if (stamp == null)
                    continue;
                var name = stamp.Name ?? "";
                var art = stamp.ArtFileName ?? "";
                if (name.IndexOf("Tile Ninja", StringComparison.OrdinalIgnoreCase) >= 0)
                    return true;
                if (art.IndexOf("tile_ninja", StringComparison.OrdinalIgnoreCase) >= 0)
                    return true;
            }

            return false;
        }

        private static List<HistoricWord> TryGetHistoricPreviousWords(Player player)
        {
            if (player == null)
                return null;

            try
            {
                var encounter = BossResolver.TryGetEncounter();
                if (encounter != null)
                {
                    var words = encounter.GetPreviousWords();
                    if (words != null && words.Count > 0)
                        return words;
                }
            }
            catch
            {
                // fall through to reflection
            }

            foreach (var name in new[]
            {
                "PreviousWords",
                "HistoricWords",
                "SubmittedWords",
                "WordsThisEncounter",
                "WordsThisRun",
            })
            {
                try
                {
                    var prop = player.GetType().GetProperty(name, MemberFlags);
                    if (prop == null)
                        continue;
                    var value = prop.GetValue(player, null) as List<HistoricWord>;
                    if (value != null && value.Count > 0)
                        return value;
                }
                catch
                {
                    // try next
                }
            }

            try
            {
                var encounter = BossResolver.TryGetEncounter();
                if (encounter != null)
                {
                    foreach (var name in new[]
                    {
                        "PreviousWords",
                        "HistoricWords",
                        "SubmittedWords",
                        "WordsThisEncounter",
                    })
                    {
                        var prop = encounter.GetType().GetProperty(name, MemberFlags);
                        if (prop == null)
                            continue;
                        var value = prop.GetValue(encounter, null) as List<HistoricWord>;
                        if (value != null && value.Count > 0)
                            return value;
                    }
                }
            }
            catch
            {
                // ignore
            }

            return null;
        }

        private static bool HasBirthdayCakeSticker(Player player)
        {
            if (player?.Stickers == null)
                return false;

            foreach (var sticker in player.Stickers)
            {
                if (sticker == null)
                    continue;
                if (IsBirthdayCakeItem(sticker))
                    return true;
            }

            return false;
        }

        private static bool HasBirthdayCakeInPinMemory(Player player)
        {
            var pin = player?.MyCharacter?.CharacterItem;
            if (pin == null || !IsRandomAccessMemoryPin(pin))
                return false;

            var items = TryGetPinMemoryItems(pin, out _);
            if (items == null)
                return false;

            foreach (var item in items)
            {
                if (IsBirthdayCakeItem(item))
                    return true;
            }

            return false;
        }

        public static bool HasBirthdayCakeInRun(Player player)
        {
            return HasBirthdayCakeSticker(player) || HasBirthdayCakeInPinMemory(player);
        }

        private static bool HasLuckyDiceSticker(Player player)
        {
            if (player?.Stickers == null)
                return false;

            foreach (var sticker in player.Stickers)
            {
                if (sticker == null)
                    continue;
                if (string.Equals(sticker.GetType().Name, "LuckyDice", StringComparison.Ordinal))
                    return true;
                var name = sticker.Name ?? "";
                var art = sticker.ArtFileName ?? "";
                if (
                    name.IndexOf("Lucky", StringComparison.OrdinalIgnoreCase) >= 0
                    && name.IndexOf("Dice", StringComparison.OrdinalIgnoreCase) >= 0
                )
                    return true;
                if (art.IndexOf("lucky_dice", StringComparison.OrdinalIgnoreCase) >= 0)
                    return true;
                if (art.IndexOf("luckydice", StringComparison.OrdinalIgnoreCase) >= 0)
                    return true;
            }

            return false;
        }

        private static int TryGetStampsShopPriceTotal(Player player)
        {
            if (player == null)
                return -1;

            var total = TryGetIntProperty(
                player,
                "StampsShopPriceTotal",
                "TotalStampShopPrice",
                "StampShopPriceTotal"
            );
            if (total >= 0)
                return total;

            if (player.Stamps == null || player.Stamps.Length == 0)
                return 0;

            var sum = 0;
            var found = false;
            foreach (var stamp in player.Stamps)
            {
                if (stamp == null)
                    continue;
                var price = TryGetIntProperty(
                    stamp,
                    "ShopPrice",
                    "ShopCost",
                    "Cost",
                    "Price",
                    "PurchasePrice"
                );
                if (price >= 0)
                {
                    sum += price;
                    found = true;
                }
            }

            return found ? sum : -1;
        }

        private static int TryGetConsumableRackCount(Player player)
        {
            if (player == null)
                return -1;

            try
            {
                var rack = player.GetType().GetProperty(
                    "ConsumableRack",
                    BindingFlags.Public | BindingFlags.Instance
                );
                if (rack != null)
                {
                    var value = rack.GetValue(player, null);
                    var collection = value as System.Collections.ICollection;
                    if (collection != null)
                        return collection.Count;
                }
            }
            catch
            {
                // fall through
            }

            return -1;
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
                    var value = prop.GetValue(target, null);
                    var s = value as string;
                    if (s != null && !string.IsNullOrEmpty(s))
                        return s;
                }
                catch
                {
                    // try next
                }
            }

            return "";
        }

        private static void FillFavourites(
            RunStateSnapshot snapshot,
            Player player,
            Character character
        )
        {
            var stickerIds = new List<string>();
            if (player?.Stickers != null)
            {
                foreach (var item in player.Stickers)
                {
                    if (item == null)
                        continue;
                    try
                    {
                        if (item.IsHumanBoyFavouriteSticker)
                        {
                            var slug = Slugify(item.ArtFileName, item.Name);
                            if (!string.IsNullOrEmpty(slug) && !stickerIds.Contains(slug))
                                stickerIds.Add(slug);
                        }
                    }
                    catch
                    {
                        // optional
                    }
                }
            }

            if (stickerIds.Count == 0 && character != null)
            {
                var favSticker = TryGetItemProperty(
                    character,
                    "FavouriteSticker",
                    "FavoriteSticker"
                );
                if (favSticker != null)
                {
                    var slug = Slugify(favSticker.ArtFileName, favSticker.Name);
                    if (!string.IsNullOrEmpty(slug))
                        stickerIds.Add(slug);
                }
            }

            var stampIds = new List<string>();
            var favStamp = TryGetHBFavouriteStamp(player);
            if (favStamp != null)
            {
                var slug = Slugify(favStamp.ArtFileName, favStamp.Name);
                if (!string.IsNullOrEmpty(slug))
                    stampIds.Add(slug);
            }
            else if (character != null)
            {
                var legacyStamp = TryGetItemProperty(
                    character,
                    "FavouriteStamp",
                    "FavoriteStamp"
                );
                if (legacyStamp != null)
                {
                    var slug = Slugify(legacyStamp.ArtFileName, legacyStamp.Name);
                    if (!string.IsNullOrEmpty(slug))
                        stampIds.Add(slug);
                }
            }

            if (stickerIds.Count > 0)
            {
                snapshot.extras["favourite_sticker_ids"] = string.Join(",", stickerIds);
                snapshot.extras["favourite_sticker_id"] = stickerIds[0];
            }

            if (stampIds.Count > 0)
            {
                snapshot.extras["favourite_stamp_ids"] = string.Join(",", stampIds);
                snapshot.extras["favourite_stamp_id"] = stampIds[0];
            }
        }

        private static Item TryGetHBFavouriteStamp(Player player)
        {
            if (player == null)
                return null;

            try
            {
                var method = player.GetType().GetMethod("GetHBFavouriteStamp", MemberFlags);
                if (method != null)
                    return method.Invoke(player, null) as Item;
            }
            catch
            {
                // optional
            }

            if (player.Stamps == null)
                return null;

            foreach (var item in player.Stamps)
            {
                if (item != null && IsHumanBoyFavouriteStamp(player, item))
                    return item;
            }

            return null;
        }

        private static bool IsHumanBoyFavouriteStamp(Player player, Item item)
        {
            if (player == null || item == null)
                return false;

            try
            {
                var method = player.GetType().GetMethod("IsHumanBoyFavouriteStamp", MemberFlags);
                if (method != null)
                {
                    var result = method.Invoke(player, new object[] { item });
                    if (result is bool flag)
                        return flag;
                }
            }
            catch
            {
                // optional
            }

            return false;
        }

        private static Item TryGetItemProperty(object target, params string[] names)
        {
            if (target == null)
                return null;

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
                    var value = prop.GetValue(target, null);
                    var item = value as Item;
                    if (item != null)
                        return item;
                }
                catch
                {
                    // try next
                }
            }

            return null;
        }

        private static bool TryGetBoolField(object target, params string[] names)
        {
            if (target == null)
                return false;

            ResolveReflectionTarget(target, out var type, out var instance);

            foreach (var name in names)
            {
                try
                {
                    var field = type.GetField(
                        name,
                        BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance
                    );
                    if (field == null)
                        continue;
                    var val = field.GetValue(instance);
                    if (val is bool b)
                        return b;
                }
                catch
                {
                    // try next
                }
            }

            return false;
        }

        private static bool TryGetBoolProperty(object target, params string[] names)
        {
            if (target == null)
                return false;

            ResolveReflectionTarget(target, out var type, out var instance);

            foreach (var name in names)
            {
                try
                {
                    var flags = instance == null
                        ? BindingFlags.Public | BindingFlags.Static
                        : BindingFlags.Public | BindingFlags.Instance;
                    var prop = type.GetProperty(name, flags);
                    if (prop == null)
                        continue;
                    var val = prop.GetValue(instance, null);
                    if (val is bool b)
                        return b;
                }
                catch
                {
                    // try next
                }
            }

            return false;
        }

        private static int TryGetIntProperty(object target, params string[] names)
        {
            if (target == null)
                return -1;

            ResolveReflectionTarget(target, out var type, out var instance);

            foreach (var name in names)
            {
                try
                {
                    var flags = instance == null
                        ? BindingFlags.Public | BindingFlags.Static
                        : BindingFlags.Public | BindingFlags.Instance;
                    var prop = type.GetProperty(name, flags);
                    if (prop == null)
                        continue;
                    if (prop.PropertyType == typeof(int))
                        return (int)prop.GetValue(instance, null);
                }
                catch
                {
                    // try next
                }
            }

            return -1;
        }

        private static void ResolveReflectionTarget(
            object target,
            out Type type,
            out object instance
        )
        {
            if (target is Type t)
            {
                type = t;
                instance = null;
                return;
            }

            type = target.GetType();
            instance = target;
        }

        private static double TryGetDoubleProperty(object target, params string[] names)
        {
            if (target == null)
                return -1;

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
                    var raw = prop.GetValue(target, null);
                    if (raw is float f)
                        return f;
                    if (raw is double d)
                        return d;
                    if (raw is int i)
                        return i;
                }
                catch
                {
                    // try next
                }
            }

            return -1;
        }

        public static string GetPinBranch(Character character)
        {
            if (character == null || character.CharacterItem == null)
                return "";

            var pin = character.CharacterItem;
            if (pin.UpgradeableComponents == null)
                return "";

            var components = pin.UpgradeableComponents;
            if (components.Count < 2)
                return "";

            var leftLevel = GetUpgradeableComponentLevel(components[0]);
            var rightLevel = GetUpgradeableComponentLevel(components[1]);

            if (leftLevel == rightLevel)
                return "";
            return leftLevel > rightLevel ? "left" : "right";
        }

        /// <summary>
        /// Raw upgrade pick count (UpgradeableComponent.Level only).
        /// </summary>
        internal static int GetUpgradeableComponentLevel(object component)
        {
            if (component == null)
                return 0;

            var levelProp = component.GetType().GetProperty(
                "Level",
                BindingFlags.Public | BindingFlags.Instance
            );
            if (levelProp != null && levelProp.PropertyType == typeof(int))
                return (int)levelProp.GetValue(component, null);

            return 0;
        }

        internal static int GetUpgradeableLevel(object component)
        {
            if (component == null)
                return 0;

            var level = GetUpgradeableComponentLevel(component);
            var variable = GetUpgradeableVariableValue(component);
            return Math.Max(level, variable);
        }

        internal static int GetUpgradeableVariableValue(object component)
        {
            if (component == null)
                return 0;

            var valueProp = component.GetType().GetProperty(
                "VariableValue",
                BindingFlags.Public | BindingFlags.Instance
            );
            if (valueProp != null && valueProp.PropertyType == typeof(int))
                return (int)valueProp.GetValue(component, null);

            return 0;
        }

        private static void FillStickerStampOrchestration(RunStateSnapshot snapshot, Player player)
        {
            if (player == null || snapshot.extras == null)
                return;

            var stickers = player.Stickers;
            if (stickers == null)
                return;

            for (var i = 0; i < stickers.Length; i++)
            {
                var sticker = stickers[i];
                if (sticker == null)
                    continue;

                var typeName = sticker.GetType().Name;
                if (typeName == "Frankenstein")
                {
                    var stitched = TryGetStitchedStickerIds(sticker);
                    snapshot.extras["stitched_sticker_ids"] = JsonConvert.SerializeObject(
                        stitched
                    );
                }
                else if (typeName == "Overhand")
                {
                    if (
                        sticker.UpgradeableComponents != null
                        && sticker.UpgradeableComponents.Count > 0
                    )
                    {
                        snapshot.extras["overhand_level"] = GetUpgradeableVariableValue(
                            sticker.UpgradeableComponents[0]
                        ).ToString();
                    }
                }
            }
        }

        private static List<string> TryGetStitchedStickerIds(Item frankenstein)
        {
            var result = new List<string>();
            if (frankenstein == null)
                return result;

            try
            {
                var prop = frankenstein.GetType().GetProperty(
                    "StitchedItems",
                    BindingFlags.Public | BindingFlags.Instance
                );
                if (prop == null)
                    return result;

                var items = prop.GetValue(frankenstein, null) as System.Collections.IEnumerable;
                if (items == null)
                    return result;

                foreach (var item in items)
                {
                    if (item == null)
                        continue;
                    var name = "";
                    try
                    {
                        var nameProp = item.GetType().GetProperty("Name");
                        if (nameProp != null)
                            name = nameProp.GetValue(item, null) as string ?? "";
                    }
                    catch
                    {
                        // optional
                    }
                    var art = "";
                    try
                    {
                        var artProp = item.GetType().GetProperty("ArtFileName");
                        if (artProp != null)
                            art = artProp.GetValue(item, null) as string ?? "";
                    }
                    catch
                    {
                        // optional
                    }
                    result.Add(Slugify(art, name));
                }
            }
            catch
            {
                // optional
            }

            return result;
        }

        public static string GetCharacterName(Character character)
        {
            if (character == null)
                return "";

            try
            {
                var field = typeof(Character).GetField(
                    "_name",
                    BindingFlags.NonPublic | BindingFlags.Instance
                );
                if (field != null)
                {
                    var value = field.GetValue(character) as string;
                    if (!string.IsNullOrEmpty(value))
                        return value;
                }
            }
            catch
            {
                // fall through
            }

            return character.GetType().Name;
        }

        public static void AppendItemsFingerprint(StringBuilder sb, Item[] items)
        {
            if (items == null)
                return;

            var first = true;
            for (var i = 0; i < items.Length; i++)
            {
                var item = items[i];
                if (item == null)
                    continue;
                if (!first)
                    sb.Append(',');
                first = false;
                sb.Append(Slugify(item.ArtFileName, item.Name));
                sb.Append(':');
                sb.Append(Math.Max(1, item.TimesUpgraded + 1));
            }
        }

        public static void AppendBossFingerprint(StringBuilder sb, List<BossModifier> bosses)
        {
            if (bosses == null || bosses.Count == 0)
            {
                sb.Append("-");
                return;
            }

            var ids = new List<string>();
            foreach (var boss in bosses)
            {
                if (boss == null)
                    continue;
                var wikiId = BossResolver.WikiBossIdFromRuntimeType(boss);
                if (string.IsNullOrEmpty(wikiId)
                    && !string.IsNullOrEmpty(boss.Name)
                    && boss.Name.IndexOf("Michael", StringComparison.OrdinalIgnoreCase) >= 0)
                    continue;
                if (string.IsNullOrEmpty(wikiId))
                    wikiId = Slugify(boss.PrefabFileName, boss.Name);
                if (string.IsNullOrEmpty(wikiId) || wikiId == "michael")
                    continue;
                if (!ids.Contains(wikiId))
                    ids.Add(wikiId);
            }
            if (ids.Count == 0)
            {
                sb.Append("-");
                return;
            }
            ids.Sort(StringComparer.Ordinal);
            sb.Append(string.Join("+", ids));
        }

        public static void AppendChallengeFingerprint(StringBuilder sb, Player player)
        {
            if (player == null)
            {
                sb.Append("-");
                return;
            }
            try
            {
                var progress = player.CurrentRunProgress;
                var challenge = progress?.Challenge;
                if (challenge == null)
                {
                    sb.Append("-");
                    return;
                }
                sb.Append(challenge.GetType().Name ?? "-");
            }
            catch
            {
                sb.Append("-");
            }
        }

        public static void AppendPinFingerprint(StringBuilder sb, Character character)
        {
            if (character == null || character.CharacterItem == null)
                return;

            var pin = character.CharacterItem;
            sb.Append(Slugify(pin.ArtFileName, pin.Name));
            sb.Append(':');
            sb.Append(GetPinBranch(character));

            if (IsBicyclePin(pin))
            {
                var bonus = TryGetBicycleWordScoreBonus(pin);
                if (bonus >= 0)
                {
                    sb.Append('|');
                    sb.Append(bonus);
                }
            }
        }

        /// <summary>
        /// Snapshot becomes a copy of a random grid sticker at grid start; export for F8 replay.
        /// </summary>
        public static void FillSnapshotCopyExtras(RunStateSnapshot snapshot, Player player)
        {
            if (snapshot?.extras == null)
                return;

            if (player?.Stickers == null)
            {
                snapshot.extras["snapshot_copy_export_note"] = "not_equipped";
                return;
            }

            Item snapshotSticker = null;
            foreach (var sticker in player.Stickers)
            {
                if (sticker == null)
                    continue;
                if (
                    string.Equals(
                        Slugify(sticker.ArtFileName, sticker.Name),
                        "snapshot",
                        StringComparison.OrdinalIgnoreCase
                    )
                )
                {
                    snapshotSticker = sticker;
                    break;
                }
            }

            if (snapshotSticker == null)
            {
                snapshot.extras["snapshot_copy_export_note"] = "not_equipped";
                return;
            }

            if (
                snapshot.extras.ContainsKey("snapshot_copy_slug")
                && !string.IsNullOrEmpty(snapshot.extras["snapshot_copy_slug"])
            )
            {
                snapshot.extras["snapshot_copy_export_note"] = "ok";
                if (!snapshot.extras.ContainsKey("snapshot_copy_source"))
                    ExportDiagnostics.SetSnapshotCopySource("preserved");
                return;
            }

            var copyItem = TryResolveSnapshotCopiedItem(snapshotSticker);
            if (copyItem == null)
            {
                snapshot.extras["snapshot_copy_export_note"] = "no_copy_yet";
                return;
            }

            var slug = Slugify(copyItem.ArtFileName, copyItem.Name);
            if (string.IsNullOrEmpty(slug) || slug == "unknown")
            {
                snapshot.extras["snapshot_copy_export_note"] = "reflection_failed";
                return;
            }

            var copyLevel = GetUpgradeableLevel(snapshotSticker);
            if (copyLevel < 1)
                copyLevel = 1;

            snapshot.extras["snapshot_copy_slug"] = slug;
            snapshot.extras["snapshot_copy_level"] = copyLevel.ToString();
            snapshot.extras["snapshot_copy_export_note"] = "ok";
            ExportDiagnostics.SetSnapshotCopySource("reflection");
        }

        /// <summary>
        /// Called from Snapshot.ApplyStartOfGridEffect postfix when grid copy is chosen.
        /// </summary>
        public static void CaptureSnapshotCopyFromGridStart(Snapshot snapshotSticker)
        {
            if (snapshotSticker == null)
                return;

            try
            {
                var copyItem = snapshotSticker.SnapshottedItem;
                if (copyItem == null)
                    return;

                var slug = Slugify(copyItem.ArtFileName, copyItem.Name);
                if (string.IsNullOrEmpty(slug) || slug == "unknown")
                    return;

                var copyLevel = GetUpgradeableLevel(snapshotSticker);
                if (copyLevel < 1)
                    copyLevel = 1;

                var keys = new Dictionary<string, string>
                {
                    ["snapshot_copy_slug"] = slug,
                    ["snapshot_copy_level"] = copyLevel.ToString(),
                    ["snapshot_copy_export_note"] = "ok",
                    ["snapshot_copy_captured_at"] = DateTime.UtcNow.ToString("o"),
                };
                ExportDiagnostics.SetSnapshotCopySource("grid_start_hook");
                var player = GetPlayer();
                if (string.Equals(slug, "telescope", StringComparison.OrdinalIgnoreCase))
                {
                    foreach (var kv in RunStateExportFill.BuildEncounterHistoricClearMergeKeys(player))
                        keys[kv.Key] = kv.Value;
                }
                TryMergeExtrasKeys(keys);
                CompanionDiagnostics.LogVerbose(
                    "Snapshot grid-start copy: " + slug + " level " + copyLevel
                );
            }
            catch (Exception ex)
            {
                ExportDiagnostics.RecordMergeError(
                    "CaptureSnapshotCopyFromGridStart: " + ex.Message
                );
            }
        }

        private static Item TryResolveSnapshotCopiedItem(Item snapshotSticker)
        {
            if (snapshotSticker == null)
                return null;

            if (snapshotSticker is Snapshot snap && snap.SnapshottedItem != null)
                return snap.SnapshottedItem;

            try
            {
                var field = snapshotSticker.GetType().GetField(
                    "SnapshottedItem",
                    MemberFlags
                );
                if (field != null)
                {
                    var val = field.GetValue(snapshotSticker);
                    if (val is Item fieldItem)
                        return fieldItem;
                }
            }
            catch
            {
                // fall through
            }

            try
            {
                var prop = snapshotSticker.GetType().GetProperty(
                    "SnapshottedItem",
                    MemberFlags
                );
                if (prop != null)
                {
                    var val = prop.GetValue(snapshotSticker, null);
                    if (val is Item propItem)
                        return propItem;
                }
            }
            catch
            {
                // fall through
            }

            return null;
        }

        public static string Slugify(string artFileName, string fallbackName)
        {
            var raw = artFileName;
            if (string.IsNullOrWhiteSpace(raw))
                raw = fallbackName ?? "";

            raw = raw.Trim();
            if (string.IsNullOrEmpty(raw))
                return "unknown";

            var lastDot = raw.LastIndexOf('.');
            if (lastDot > 0)
                raw = raw.Substring(0, lastDot);

            var sb = new StringBuilder(raw.Length);
            var prevUnderscore = false;
            foreach (var ch in raw.ToLowerInvariant())
            {
                if (char.IsLetterOrDigit(ch))
                {
                    sb.Append(ch);
                    prevUnderscore = false;
                }
                else if (!prevUnderscore)
                {
                    sb.Append('_');
                    prevUnderscore = true;
                }
            }

            var slug = sb.ToString().Trim('_');
            return string.IsNullOrEmpty(slug) ? "unknown" : slug;
        }
    }
}
