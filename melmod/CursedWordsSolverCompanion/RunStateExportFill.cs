using System;
using System.Collections.Generic;
using System.Reflection;
using System.Text;
using System.Text.RegularExpressions;
using MelonLoader;
using Newtonsoft.Json;
using UnityEngine;

namespace CursedWordsSolverCompanion
{
    /// <summary>
    /// Run context and future-proof fields for run_state.json export.
    /// </summary>
    internal static class RunStateExportFill
    {
        private static readonly BindingFlags MemberFlags =
            BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;
        private static bool _loggedMichaelMissingExtrasWarning = false;

        /// <summary>Last gridNumber from CalculateOverallScore (most accurate).</summary>
        public static int CachedGridNumber = -1;

        public static int TryParseGridNumber(string raw)
        {
            if (string.IsNullOrEmpty(raw))
                return -1;
            int n;
            if (!int.TryParse(raw.Trim(), out n))
                return -1;
            return n >= 1 ? n : -1;
        }

        /// <summary>
        /// True when incoming historic has fewer words than existing on the same grid (export shrink).
        /// </summary>
        public static bool HistoricWouldShrinkOnSameGrid(
            string existingHistoric,
            string incomingHistoric,
            int gridNumber,
            RunStateSnapshot snapshot = null
        )
        {
            if (snapshot != null && ShouldClearEncounterHistoricOnEmptyExport(snapshot))
                return false;

            var incomingCount = CountHistoricWordsInJson(incomingHistoric);
            var existingCount = CountHistoricWordsInJson(existingHistoric);
            if (incomingCount >= existingCount)
                return false;
            return gridNumber >= 1;
        }

        /// <summary>
        /// Grid advance: mark metadata and re-export scoring historic from cache/live only.
        /// Prior-grid disk historic is never copied onto the new grid.
        /// </summary>
        public static void TryClearStaleHistoricCacheOnGridAdvance(Player player)
        {
            if (player == null)
                return;
            var liveGrid = ResolveGridNumber(player);
            var onDiskGrid = TryParseGridNumber(
                RunStateExporter.TryReadRunStateExtra("grid_number")
            );
            if (liveGrid < 1 || onDiskGrid < 1 || liveGrid <= onDiskGrid)
                return;

            var keys = new Dictionary<string, string>
            {
                ["grid_number"] = liveGrid.ToString(),
                ["encounter_historic_source"] = "grid_advanced",
                ["previous_word_first_letter"] = "",
                ["historic_words"] = "",
                ["grid_scattered_items"] = "",
            };

            var redUsed = RunStateExporter.TryGetRedTilesUsedEncounterPublic(player);
            if (redUsed >= 0)
                keys["red_tiles_used_encounter"] = redUsed.ToString();

            var fallback = new Dictionary<string, string>();
            foreach (var kv in keys)
                fallback[kv.Key] = kv.Value ?? "";

            var built = BuildBestHistoricExtras(player, fallback);
            if (built != null)
            {
                foreach (var kv in built)
                    keys[kv.Key] = kv.Value ?? "";
            }

            TryMergeCachedEncounterHistoricIntoKeys(keys, player, liveGrid);

            string mergedHistoric;
            if (
                !keys.TryGetValue("historic_words", out mergedHistoric)
                || string.IsNullOrEmpty(mergedHistoric)
                || mergedHistoric == "[]"
            )
            {
                keys["historic_words"] = "";
                keys["encounter_historic_source"] = "grid_advanced";
            }

            RunStateExporter.ClearCachedPreviousWordsForExport();
            ApplyScoringCachedPreviousWordLetter(keys, player);
            if (RunStateExporter.PlayerHasStampSlug(player, "tile_ninja"))
            {
                var baseline = RunStateExporter.TryGetTileNinjaBonusForExport(player);
                if (baseline < 0)
                {
                    var lastKnown = RunStateExporter.TryReadRunStateExtra(
                        "tile_ninja_bonus_last_known"
                    );
                    if (
                        RunStateExporter.TryParseTileNinjaAdditiveForExport(
                            lastKnown,
                            out var parsed
                        )
                    )
                        baseline = parsed;
                }
                if (baseline >= 0)
                {
                    keys["tile_ninja_bonus_at_grid_start"] = baseline.ToString(
                        System.Globalization.CultureInfo.InvariantCulture
                    );
                }
            }
            RunStateExporter.TryMergeExtrasKeys(keys);
        }

        private static readonly string[] BossExtraKeys =
        {
            "boss_area_number",
            "boss_cursed",
            "boss_floor_modification",
            "hyena_blocked",
            "capybara_shuffle",
            "grids_remaining",
            "grids_total",
            "fox_stolen_this_grid",
            "fox_stolen_this_word",
            "wolf_max_length",
            "cobra_min_length",
            "michael_min_word_length",
            "michael_phase",
            "michael_summoned_bosses_defeated",
            "michael_puzzle_grid",
            "encounter_min_word_length",
            "boss_modifier_floor_mods",
            "boss_modifiers",
        };

        public static void ClearBossExtras(Dictionary<string, string> extras)
        {
            if (extras == null)
                return;
            foreach (var key in BossExtraKeys)
                extras.Remove(key);
        }

        public static void ApplyMetadata(RunStateSnapshot snapshot, Player player)
        {
            if (snapshot == null)
                return;

            snapshot.schema_version = 1;
            snapshot.exported_at = DateTime.UtcNow.ToString("o");

            if (player?.MyCharacter != null)
            {
                var display = RunStateExporter.GetCharacterName(player.MyCharacter);
                if (!string.IsNullOrEmpty(display))
                {
                    snapshot.extras["character_slug"] = RunStateExporter.Slugify(
                        display,
                        display
                    );
                }
            }

            if (snapshot.board != null && snapshot.board.source == "melmod")
                snapshot.extras["board_from_melmod"] = "true";

            FillGridNumber(snapshot, player);
            FillRunSeed(snapshot, player);
            FillInventoryCounters(snapshot, player);
            FillEquippedStampFlags(snapshot, player);
            FillFrozenInShop(snapshot, player);
            FillEncounterMode(snapshot, player);
            FillRunProgressExtras(snapshot, player);
            FillFutureProofTierA(snapshot, player);
            FillBossParams(snapshot, player);
            RunStateExporter.FillSnapshotCopyExtras(snapshot, player);
            if (player != null)
            {
                snapshot.extras["loadout_fingerprint"] =
                    FingerprintUtil.ComputeLoadoutFingerprint(player);
            }
        }

        public static void AppendEncounterFingerprint(StringBuilder sb, Player player)
        {
            if (player == null || sb == null)
                return;

            var gridNum = ResolveGridNumber(player);
            sb.Append('|');
            sb.Append(gridNum);

            var rackTiles = ConsumableRackExporter.Export(player);
            sb.Append('|');
            sb.Append(rackTiles != null ? rackTiles.Count : 0);
            if (rackTiles != null)
            {
                foreach (var tile in rackTiles)
                {
                    if (tile == null)
                        continue;
                    sb.Append(':');
                    sb.Append(tile.letter ?? "");
                    sb.Append('/');
                    sb.Append(tile.color ?? "colorless");
                }
            }

            var firstGrid = TryGetIntProperty(player, "IsFirstGrid", "IsFirstGridOfEncounter");
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
            sb.Append('|');
            sb.Append(firstGrid >= 0 ? firstGrid : -1);
        }

        public static string DetectEncounterMode(Player player)
        {
            if (player == null)
                return "none";

            if (IsMichaelPuzzleGridActive())
                return "puzzle";

            var shopController = UnityEngine.Object.FindAnyObjectByType<ShopController>();
            if (shopController != null && shopController.isActiveAndEnabled)
                return "shop";

            if (IsRunProgressShopNode(player))
                return "shop";

            if (BoardExporter.TryBuild(player) != null)
                return "encounter";

            var encounter = BossResolver.TryGetEncounter();
            if (encounter != null)
                return "encounter";

            if (TryGetBoolProperty(player, "InShop", "IsInShop", "ShopActive"))
                return "shop";

            return "none";
        }

        private static bool IsRunProgressShopNode(Player player)
        {
            var progress = TryGetRunProgress(player);
            if (progress == null)
                return false;
            try
            {
                var type = progress.GetType();
                var field = type.GetField("CurrentNodeType", MemberFlags);
                object value = field?.GetValue(progress);
                if (value == null)
                {
                    var prop = type.GetProperty("CurrentNodeType", MemberFlags);
                    value = prop?.GetValue(progress, null);
                }
                if (value == null)
                    return false;
                var name = value.ToString();
                return name == "ShopZero"
                    || name == "ShopOne"
                    || name == "ShopTwo"
                    || name == "MegShop";
            }
            catch
            {
                return false;
            }
        }

        private static void FillGridNumber(RunStateSnapshot snapshot, Player player)
        {
            var n = ResolveGridNumber(player);
            if (n >= 1)
                snapshot.extras["grid_number"] = n.ToString();
        }

        public static int ResolveGridNumber(Player player)
        {
            // Prefer live encounter/player index. CachedGridNumber is from the last
            // CalculateOverallScore and can stay high across grids/encounters until the
            // next submit (e.g. Bento Box firing on grid 1 when cache still says 2+).
            var gridIndex = TryGetIntProperty(
                player,
                "CurrentGridIndex",
                "GridIndex",
                "GridsCompletedThisEncounter"
            );
            if (gridIndex >= 0)
                return gridIndex + 1;

            var encounter = BossResolver.TryGetEncounter();
            if (encounter != null)
            {
                var fromEncounter = TryGetIntProperty(
                    encounter,
                    "CurrentGridNumber",
                    "GridNumber",
                    "CurrentGridsGenerated",
                    "GridsGenerated"
                );
                if (fromEncounter >= 1)
                    return fromEncounter;

                try
                {
                    var method = encounter.GetType().GetMethod(
                        "CurrentGridsGenerated",
                        BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic
                    );
                    if (method != null && method.GetParameters().Length == 0)
                    {
                        var raw = method.Invoke(encounter, null);
                        var n = TryReadIntLike(raw);
                        if (n >= 1)
                            return n;
                    }
                }
                catch
                {
                    // optional
                }
            }

            if (CachedGridNumber >= 1)
                return CachedGridNumber;

            return 1;
        }

        private static void FillRunSeed(RunStateSnapshot snapshot, Player player)
        {
            if (player == null)
                return;

            var seed = TryGetIntProperty(
                player,
                "RunSeed",
                "Seed",
                "RandomSeed",
                "GameSeed"
            );
            if (seed < 0)
            {
                var progress = TryGetRunProgress(player);
                if (progress != null)
                    seed = TryGetIntProperty(
                        progress,
                        "Seed",
                        "RunSeed",
                        "RandomSeed"
                    );
            }
            if (seed < 0)
            {
                seed = TryGetIntProperty(
                    typeof(GameStatics),
                    "RunSeed",
                    "Seed",
                    "GameSeed"
                );
            }

            if (seed >= 0)
                snapshot.extras["run_seed"] = seed.ToString();
        }

        private static void FillInventoryCounters(RunStateSnapshot snapshot, Player player)
        {
            if (player == null)
                return;

            var rare = CountItemsMatchingRarity(player, "Rare", "RARE");
            if (rare >= 0)
                snapshot.extras["rare_item_count"] = rare.ToString();
            else if (RunStateExporter.PlayerHasStampSlug(player, "steak"))
                snapshot.extras["rare_item_count"] = "0";

            var fairies = CountUnpackedOfTypeName(player, "Fairy");
            if (fairies < 0)
                fairies = CountStampsMatching(player, "fairy", "blessing_of_the_fairies");
            if (fairies >= 0)
                snapshot.extras["fairy_count"] = fairies.ToString();

            var animals = CountStampsMatching(player, "animal");
            if (animals >= 0)
                snapshot.extras["animal_stamp_count"] = animals.ToString();

            var moneyLost = TryGetIntProperty(
                player,
                "MoneyLostThisEncounter",
                "MoneyLostEncounter",
                "LostMoneyThisEncounter"
            );
            if (moneyLost < 0)
            {
                var encounter = BossResolver.TryGetEncounter();
                if (encounter != null)
                    moneyLost = TryGetIntProperty(
                        encounter,
                        "MoneyLostThisEncounter",
                        "MoneyLost"
                    );
            }
            if (moneyLost >= 0)
                snapshot.extras["money_lost_encounter"] = moneyLost.ToString();
        }

        private static void FillEquippedStampFlags(RunStateSnapshot snapshot, Player player)
        {
            if (player?.Stamps == null)
                return;

            foreach (var stamp in player.Stamps)
            {
                if (stamp == null)
                    continue;
                var slug = RunStateExporter.Slugify(stamp.ArtFileName, stamp.Name);
                if (slug == "kokeshi_dolls" || slug.IndexOf("kokeshi", StringComparison.OrdinalIgnoreCase) >= 0)
                    snapshot.extras["kokeshi_dolls"] = "true";
            }
        }

        private static void FillFrozenInShop(RunStateSnapshot snapshot, Player player)
        {
            if (snapshot.extras.ContainsKey("avocado_mushy")
                && snapshot.extras["avocado_mushy"] == "true")
            {
                snapshot.extras["frozen_in_shop"] = "true";
                return;
            }

            if (TryGetBoolProperty(player, "FrozenInShop", "IsFrozenInShop", "ShopFrozen"))
                snapshot.extras["frozen_in_shop"] = "true";
        }

        private static void FillEncounterMode(RunStateSnapshot snapshot, Player player)
        {
            snapshot.extras["encounter_mode"] = DetectEncounterMode(player);
        }

        private static void FillRunProgressExtras(RunStateSnapshot snapshot, Player player)
        {
            if (snapshot?.extras == null || player == null)
                return;

            var stage = BossResolver.TryGetRunStage(player);
            if (stage >= 1)
                snapshot.extras["run_stage"] = stage.ToString();

            var nodeType = TryGetCurrentNodeType(player);
            if (!string.IsNullOrEmpty(nodeType))
            {
                snapshot.extras["run_node_type"] = nodeType;
                if (string.Equals(nodeType, "EncounterFirst", StringComparison.Ordinal))
                    BossResolver.ClearScoringCache();
            }
        }

        private static string TryGetCurrentNodeType(Player player)
        {
            if (player?.CurrentRunProgress == null)
                return "";

            try
            {
                return player.CurrentRunProgress.GetCurrentNodeType().ToString();
            }
            catch
            {
                try
                {
                    return player.CurrentRunProgress.CurrentNodeType.ToString();
                }
                catch
                {
                    return "";
                }
            }
        }

        private static void FillFutureProofTierA(RunStateSnapshot snapshot, Player player)
        {
            snapshot.extras["game_version"] = Application.version ?? "";

            var encounter = BossResolver.TryGetEncounter();
            if (encounter != null)
            {
                var encId = TryGetIntProperty(encounter, "EncounterId", "Id", "EncounterIndex");
                if (encId >= 0)
                    snapshot.extras["encounter_id"] = encId.ToString();
            }

            var runId = TryGetIntProperty(player, "RunId", "CurrentRunId", "RunIndex");
            if (runId >= 0)
                snapshot.extras["run_id"] = runId.ToString();

            snapshot.extras["sticker_order"] = SerializeItemSlugOrder(player?.Stickers);
            snapshot.extras["stamp_order"] = SerializeItemSlugOrder(player?.Stamps);

            var gridsTotal = TryGetIntProperty(
                player,
                "GridsInEncounter",
                "GridsPerEncounter",
                "TotalGridsThisEncounter",
                "EncounterGridCount"
            );
            if (gridsTotal < 0 && encounter != null)
                gridsTotal = TryGetIntProperty(
                    encounter,
                    "GridsInEncounter",
                    "TotalGrids",
                    "MaxGrids",
                    "GridsPerEncounter"
                );
            if (gridsTotal >= 0)
                snapshot.extras["grids_total"] = gridsTotal.ToString();

            EnsureEncounterHistoricExtras(snapshot, player);
        }

        /// <summary>
        /// Export per-word historic list for Telescope / Movie Camera (F7/F8 and submit).
        /// Always refreshes from live player, cached previousWords, or longer fallback JSON.
        /// </summary>
        public static void EnsureEncounterHistoricExtras(
            RunStateSnapshot snapshot,
            Player player,
            bool liveOnly = false
        )
        {
            if (snapshot?.extras == null || player == null)
                return;

            var fallbackExtras = BuildEncounterHistoricFallbackExtras(snapshot, player);
            var built = liveOnly
                ? BuildF8HistoricExtras(player, fallbackExtras)
                : BuildBestHistoricExtras(player, fallbackExtras, liveOnly);
            if (built == null || built.Count == 0)
            {
                if (TryApplyLivePlayerEncounterHistoricToSnapshot(snapshot, player))
                {
                    ApplyProjectedWorkflowExtrasToSnapshot(snapshot, player);
                    return;
                }

                if (TryApplyCachedEncounterHistoricToSnapshot(snapshot, player))
                {
                    ApplyProjectedWorkflowExtrasToSnapshot(snapshot, player);
                    return;
                }

                if (!liveOnly && TryApplyGrid2DiskEncounterHistoricFallback(snapshot, player))
                {
                    ApplyProjectedWorkflowExtrasToSnapshot(snapshot, player);
                    return;
                }

                if (ShouldClearEncounterHistoricOnEmptyExport(snapshot))
                    ClearStaleEncounterHistoricExtras(snapshot, player, "live_empty");
                return;
            }

            string builtHistoric;
            if (built.TryGetValue("historic_words", out builtHistoric)
                && !string.IsNullOrEmpty(builtHistoric)
                && builtHistoric != "[]")
            {
                string existingHistoric = null;
                snapshot.extras.TryGetValue("historic_words", out existingHistoric);
                string fallbackHistoric = null;
                if (fallbackExtras != null)
                    fallbackExtras.TryGetValue("historic_words", out fallbackHistoric);
                var longestExisting = PreferHistoricJson(existingHistoric, fallbackHistoric);
                var grid = ResolveGridNumber(player);
                if (
                    !liveOnly
                    && HistoricWouldShrinkOnSameGrid(
                        longestExisting,
                        builtHistoric,
                        grid,
                        snapshot
                    )
                )
                {
                    built.Remove("historic_words");
                    if (longestExisting != null && longestExisting != "[]")
                        built["historic_words"] = longestExisting;
                    string fallbackRed;
                    if (
                        fallbackExtras != null
                        && fallbackExtras.TryGetValue("red_tiles_used_encounter", out fallbackRed)
                        && !string.IsNullOrEmpty(fallbackRed)
                    )
                        built["red_tiles_used_encounter"] = fallbackRed;
                }
            }

            foreach (var kv in built)
                snapshot.extras[kv.Key] = kv.Value ?? "";

            string liveHistoric;
            if (
                !snapshot.extras.TryGetValue("historic_words", out liveHistoric)
                || string.IsNullOrEmpty(liveHistoric)
                || liveHistoric == "[]"
            )
            {
                if (TryApplyLivePlayerEncounterHistoricToSnapshot(snapshot, player))
                {
                    ApplyProjectedWorkflowExtrasToSnapshot(snapshot, player);
                    return;
                }

                if (TryApplyCachedEncounterHistoricToSnapshot(snapshot, player))
                {
                    ApplyProjectedWorkflowExtrasToSnapshot(snapshot, player);
                    return;
                }
            }

            ApplyProjectedWorkflowExtrasToSnapshot(snapshot, player);
            string sourceAfter;
            if (
                !snapshot.extras.TryGetValue("encounter_historic_source", out sourceAfter)
                || !string.Equals(
                    sourceAfter,
                    "grid1_no_scoring_cache",
                    StringComparison.OrdinalIgnoreCase
                )
            )
                snapshot.extras["encounter_historic_source"] = "live";
        }

        private static bool TryApplyLivePlayerEncounterHistoricToSnapshot(
            RunStateSnapshot snapshot,
            Player player,
            string source = "live_player"
        )
        {
            if (snapshot?.extras == null || player == null)
                return false;

            var fromPlayer = RunStateExporter.TryGetHistoricPreviousWordsPublic(player);
            if (fromPlayer == null || fromPlayer.Count == 0)
                return false;

            var telescope = BuildTelescopeEncounterExtras(fromPlayer, player);
            if (telescope == null || telescope.Count == 0)
                return false;

            foreach (var kv in telescope)
                snapshot.extras[kv.Key] = kv.Value ?? "";
            snapshot.extras["encounter_historic_source"] = source;
            return true;
        }

        private static bool TryApplyCachedEncounterHistoricToSnapshot(
            RunStateSnapshot snapshot,
            Player player,
            string source = "live_cache"
        )
        {
            if (snapshot?.extras == null || player == null)
                return false;

            var grid = ResolveGridNumber(player);
            if (grid < 2)
            {
                if (grid != 1 || !RunStateExporter.ExportLiveOnlyHistoric)
                    return false;
            }

            var cached = RunStateExporter.GetCachedPreviousWords();
            if (cached == null || cached.Count == 0)
                return false;

            var telescope = BuildTelescopeEncounterExtras(cached, player);
            if (telescope == null || telescope.Count == 0)
                return false;

            foreach (var kv in telescope)
                snapshot.extras[kv.Key] = kv.Value ?? "";
            snapshot.extras["encounter_historic_source"] = source;
            return true;
        }

        /// <summary>
        /// Grid 2+: when live/cache historic is empty, pull encounter words from on-disk run_state
        /// (e.g. prior-grid words merged by TryClearStaleHistoricCacheOnGridAdvance).
        /// </summary>
        private static bool TryApplyGrid2DiskEncounterHistoricFallback(
            RunStateSnapshot snapshot,
            Player player
        )
        {
            // Live export only — never resurrect historic from on-disk run_state.json.
            return false;
        }

        private static void TryMergeCachedEncounterHistoricIntoKeys(
            Dictionary<string, string> keys,
            Player player,
            int liveGrid
        )
        {
            if (keys == null || player == null || liveGrid < 2)
                return;

            string existingHistoric;
            if (
                keys.TryGetValue("historic_words", out existingHistoric)
                && !string.IsNullOrEmpty(existingHistoric)
                && existingHistoric != "[]"
            )
                return;

            var cached = RunStateExporter.GetCachedPreviousWords();
            if (cached == null || cached.Count == 0)
                return;

            var telescope = BuildTelescopeEncounterExtras(cached, player);
            if (telescope == null || telescope.Count == 0)
                return;

            foreach (var kv in telescope)
                keys[kv.Key] = kv.Value ?? "";
            keys["encounter_historic_source"] = "live_cache";
        }

        /// <summary>
        /// Merge submit-time workflow extras so run_state.json matches score projection.
        /// </summary>
        public static void ApplyProjectedWorkflowExtrasToSnapshot(
            RunStateSnapshot snapshot,
            Player player
        )
        {
            if (snapshot?.extras == null || player == null)
                return;

            var live = new Dictionary<string, string>();
            foreach (var kv in snapshot.extras)
                live[kv.Key] = kv.Value ?? "";

            var projected = BuildSubmitWorkflowExtras(player, live);
            foreach (var key in new[]
            {
                "historic_words",
                "previous_word_first_letter",
                "red_tiles_used_encounter",
            })
            {
                string val;
                if (projected.TryGetValue(key, out val) && !string.IsNullOrEmpty(val))
                    snapshot.extras[key] = val;
            }

            ApplyScoringCachedPreviousWordLetter(snapshot.extras, player);
        }

        /// <summary>
        /// No-op: Limnophila previous comes from scoring hook cache, not encounter historic_words JSON.
        /// </summary>
        public static void ReconcilePreviousWordFirstLetterWithHistoric(
            Dictionary<string, string> extras,
            Player player = null
        )
        {
            ApplyScoringCachedPreviousWordLetter(extras, player);
        }

        /// <summary>
        /// Set previous_word_first_letter and scoring_previous_words_count from live player
        /// reflection and/or submit-hook cache (cache wins when longer).
        /// </summary>
        public static void ApplyScoringCachedPreviousWordLetter(
            Dictionary<string, string> extras,
            Player player = null
        )
        {
            if (extras == null)
                return;

            extras.Remove("previous_word_first_letter");

            string historicRaw;
            extras.TryGetValue("historic_words", out historicRaw);
            var histEmpty =
                string.IsNullOrEmpty(historicRaw) || historicRaw.Trim() == "[]";
            string sourceRaw;
            extras.TryGetValue("encounter_historic_source", out sourceRaw);
            var source = (sourceRaw ?? "").Trim().ToLowerInvariant();
            var freshGridSource =
                source == "grid_advanced"
                || source == "grid_advanced_disk"
                || source == "grid_start_cleared"
                || source == "grid1_no_scoring_cache";
            if (histEmpty && freshGridSource)
            {
                var liveWords = player != null
                    ? RunStateExporter.TryGetHistoricPreviousWordsPublic(player)
                    : null;
                if (liveWords == null || liveWords.Count == 0)
                {
                    extras["scoring_previous_words_count"] = "0";
                    return;
                }
            }

            var scoringPrevious = RunStateExporter.GetCachedPreviousWords();
            var cacheCount = scoringPrevious != null ? scoringPrevious.Count : 0;
            var fromPlayer = player != null
                ? RunStateExporter.TryGetHistoricPreviousWordsPublic(player)
                : null;
            var playerCount = fromPlayer != null ? fromPlayer.Count : 0;
            var gridNum = TryParseGridNumber(
                extras.TryGetValue("grid_number", out var gridRaw) ? gridRaw : null
            );

            List<HistoricWord> bestWords = null;
            if (cacheCount > 0 && playerCount > 0)
                bestWords = cacheCount >= playerCount ? scoringPrevious : fromPlayer;
            else if (cacheCount > 0)
                bestWords = scoringPrevious;
            else if (playerCount > 0)
                bestWords = fromPlayer;

            var bestCount = bestWords != null ? bestWords.Count : 0;

            if (bestCount == 0)
            {
                if (gridNum == 1)
                    ClearGridOneStaleEncounterHistoric(extras);

                extras["scoring_previous_words_count"] = "0";

                // Grid 2+: no scoring-cache prior means no Bento prev on this grid —
                // do not fall back to encounter-wide historic (grid-1 bleed).
                if (gridNum >= 2)
                {
                    extras.Remove("historic_words");
                    extras.Remove("red_tiles_used_encounter");
                    if (!freshGridSource)
                        extras["encounter_historic_source"] = "grid_start_cleared";
                    return;
                }

                extras.TryGetValue("historic_words", out historicRaw);
                histEmpty =
                    string.IsNullOrEmpty(historicRaw) || historicRaw.Trim() == "[]";
                if (!histEmpty)
                {
                    var prevFromHist = FirstLetterFromHistoricJson(historicRaw);
                    if (!string.IsNullOrEmpty(prevFromHist))
                        extras["previous_word_first_letter"] = prevFromHist;
                }
                return;
            }

            extras["scoring_previous_words_count"] = bestCount.ToString();

            if (histEmpty && player != null && bestWords != null && bestWords.Count > 0)
            {
                var telescope = BuildTelescopeEncounterExtras(bestWords, player);
                if (telescope != null)
                {
                    string builtHist;
                    if (
                        telescope.TryGetValue("historic_words", out builtHist)
                        && !string.IsNullOrEmpty(builtHist)
                        && builtHist != "[]"
                    )
                    {
                        extras["historic_words"] = builtHist;
                        histEmpty = false;
                        if (
                            !string.Equals(
                                source,
                                "grid1_no_scoring_cache",
                                StringComparison.OrdinalIgnoreCase
                            )
                        )
                            extras["encounter_historic_source"] = "live";
                    }

                    string builtRed;
                    if (telescope.TryGetValue("red_tiles_used_encounter", out builtRed)
                        && !string.IsNullOrEmpty(builtRed))
                        extras["red_tiles_used_encounter"] = builtRed;
                }
            }

            var prev = ScoringContextCapture.FirstLetterFromHistoricWords(bestWords);
            if (!string.IsNullOrEmpty(prev))
                extras["previous_word_first_letter"] = prev;
        }

        /// <summary>
        /// Grid 1 with no scoring-cache prior: encounter historic in export is stale for Telescope.
        /// </summary>
        internal static void ClearGridOneStaleEncounterHistoric(Dictionary<string, string> extras)
        {
            if (extras == null)
                return;

            int gridNum;
            if (!extras.TryGetValue("grid_number", out var gridRaw)
                || string.IsNullOrWhiteSpace(gridRaw)
                || !int.TryParse(gridRaw.Trim(), out gridNum)
                || gridNum != 1)
                return;

            extras.Remove("historic_words");
            extras.Remove("red_tiles_used_encounter");
            extras["encounter_historic_source"] = "grid1_no_scoring_cache";
        }

        private static readonly Regex HistoricFontTagRegex = new Regex(
            @"<font[^>]*>|</font>",
            RegexOptions.IgnoreCase | RegexOptions.Compiled
        );

        /// <summary>Strip Unity rich-text so Limnophila does not read 'f' from "&lt;font".</summary>
        internal static string StripHistoricWordRichText(string word)
        {
            if (string.IsNullOrEmpty(word))
                return word ?? "";
            if (word.IndexOf("<font", StringComparison.OrdinalIgnoreCase) < 0)
                return word;
            return HistoricFontTagRegex.Replace(word, "").Trim();
        }

        private static string FirstLetterFromHistoricJson(string json)
        {
            if (string.IsNullOrEmpty(json) || json == "[]")
                return "";
            try
            {
                var arr = JsonConvert.DeserializeObject<List<Dictionary<string, object>>>(
                    json
                );
                if (arr == null || arr.Count == 0)
                    return "";
                for (var i = arr.Count - 1; i >= 0; i--)
                {
                    object wordObj;
                    if (!arr[i].TryGetValue("word", out wordObj))
                        continue;
                    var word = StripHistoricWordRichText((wordObj ?? "").ToString());
                    if (string.IsNullOrEmpty(word))
                        continue;
                    foreach (var ch in word)
                    {
                        if (char.IsLetter(ch))
                            return char.ToLowerInvariant(ch).ToString();
                    }
                }
            }
            catch
            {
                // ignore parse errors
            }
            return "";
        }

        /// <summary>
        /// Snapshot extras plus on-disk encounter historic when live reflection is empty,
        /// unless encounter historic was intentionally cleared (grid start / grid advance).
        /// </summary>
        private static Dictionary<string, string> BuildEncounterHistoricFallbackExtras(
            RunStateSnapshot snapshot,
            Player player
        )
        {
            var fallback = new Dictionary<string, string>();
            if (snapshot?.extras != null)
            {
                foreach (var kv in snapshot.extras)
                    fallback[kv.Key] = kv.Value ?? "";
            }

            if (ShouldSkipOnDiskHistoricFallback(snapshot, player))
                return fallback;

            MergeOnDiskEncounterHistoricInto(fallback);
            return fallback;
        }

        private static bool ShouldSkipOnDiskHistoricFallback(
            RunStateSnapshot snapshot,
            Player player
        )
        {
            if (ShouldClearEncounterHistoricOnEmptyExport(snapshot))
                return true;

            var diskSource = RunStateExporter.TryReadRunStateExtra("encounter_historic_source");
            if (IsIntentionallyClearedEncounterHistoricSource(diskSource))
                return true;

            if (snapshot?.extras == null)
                return false;

            string snapSource;
            if (snapshot.extras.TryGetValue("encounter_historic_source", out snapSource)
                && IsIntentionallyClearedEncounterHistoricSource(snapSource))
                return true;

            if (player == null)
                return false;

            var liveGrid = ResolveGridNumber(player);
            var onDiskGrid = TryParseGridNumber(
                RunStateExporter.TryReadRunStateExtra("grid_number")
            );
            if (liveGrid < 1 || onDiskGrid < 1 || liveGrid <= onDiskGrid)
                return false;

            var live = PickBestHistoricWordList(player);
            var liveCount = live != null ? live.Count : 0;
            var diskHistoric = RunStateExporter.TryReadRunStateExtra("historic_words");
            var diskCount = CountHistoricWordsInJson(diskHistoric);

            if (liveCount == 0 && diskCount > 0)
                return false;

            if (diskCount > liveCount)
                return true;

            return false;
        }

        public static int CountHistoricWordsInJson(string json)
        {
            if (string.IsNullOrEmpty(json) || json == "[]")
                return 0;
            try
            {
                var arr = JsonConvert.DeserializeObject<List<object>>(json);
                return arr != null ? arr.Count : 0;
            }
            catch
            {
                return 0;
            }
        }

        public static int HistoricJsonRedTileCountSum(string json)
        {
            if (string.IsNullOrEmpty(json) || json == "[]")
                return 0;
            try
            {
                var rows = JsonConvert.DeserializeObject<List<Dictionary<string, object>>>(json);
                if (rows == null)
                    return 0;
                var total = 0;
                foreach (var row in rows)
                {
                    if (row == null || !row.TryGetValue("red_tile_count", out var raw) || raw == null)
                        continue;
                    if (int.TryParse(raw.ToString(), out var n) && n > 0)
                        total += n;
                }
                return total;
            }
            catch
            {
                return 0;
            }
        }

        private static bool IsIntentionallyClearedEncounterHistoricSource(string source)
        {
            if (string.IsNullOrEmpty(source))
                return false;

            return string.Equals(source, "grid_start_cleared", StringComparison.OrdinalIgnoreCase);
        }

        private static void MergeOnDiskEncounterHistoricInto(Dictionary<string, string> fallback)
        {
            // Live export only — never merge encounter historic from on-disk run_state.json.
        }

        /// <summary>
        /// Only telescope grid-start resets encounter historic for F8; other Snapshot copies keep it.
        /// </summary>
        private static bool ShouldClearEncounterHistoricOnEmptyExport(RunStateSnapshot snapshot)
        {
            if (snapshot?.extras == null)
                return false;

            string source;
            if (snapshot.extras.TryGetValue("encounter_historic_source", out source)
                && string.Equals(source, "grid_start_cleared", StringComparison.OrdinalIgnoreCase))
                return true;

            string copySlug;
            if (snapshot.extras.TryGetValue("snapshot_copy_slug", out copySlug)
                && string.Equals(copySlug, "telescope", StringComparison.OrdinalIgnoreCase))
                return true;

            return false;
        }

        /// <summary>
        /// Remove stale encounter historic from export; set live red count (including 0).
        /// </summary>
        public static void ClearStaleEncounterHistoricExtras(
            RunStateSnapshot snapshot,
            Player player,
            string source
        )
        {
            if (snapshot?.extras == null)
                return;

            snapshot.extras.Remove("historic_words");
            snapshot.extras.Remove("red_tiles_used_encounter");

            var grid = ResolveGridNumber(player);
            if (grid >= 2)
                snapshot.extras.Remove("previous_word_first_letter");

            var redUsed = RunStateExporter.TryGetRedTilesUsedEncounterPublic(player);
            if (redUsed >= 0)
                snapshot.extras["red_tiles_used_encounter"] = redUsed.ToString();

            snapshot.extras["encounter_historic_source"] = source ?? "cleared";

            string prev;
            if (snapshot.extras.TryGetValue("previous_word_first_letter", out prev)
                && !string.IsNullOrEmpty(prev))
            {
                CompanionDiagnostics.LogVerbose(
                    "Encounter historic empty ("
                        + (source ?? "cleared")
                        + "; previous_word_first_letter="
                        + prev
                        + ")"
                );
            }
        }

        /// <summary>
        /// Keys to merge after Snapshot grid-start: clear cached/submit historic, export live reds.
        /// </summary>
        public static Dictionary<string, string> BuildEncounterHistoricClearMergeKeys(Player player)
        {
            RunStateExporter.ClearCachedPreviousWordsForExport();
            var keys = new Dictionary<string, string>
            {
                ["historic_words"] = "",
                ["encounter_historic_source"] = "grid_start_cleared",
            };
            var redUsed = RunStateExporter.TryGetRedTilesUsedEncounterPublic(player);
            if (redUsed >= 0)
                keys["red_tiles_used_encounter"] = redUsed.ToString();
            return keys;
        }

        /// <summary>
        /// Grid 1 encounter not started: earned 0 and remaining equals total target.
        /// </summary>
        internal static bool IsFreshEncounterGridOne(Dictionary<string, string> extras)
        {
            if (extras == null)
                return false;

            var grid = TryParseGridNumber(
                extras.TryGetValue("grid_number", out var gridRaw) ? gridRaw : null
            );
            if (grid != 1)
                return false;

            string spcRaw;
            if (extras.TryGetValue("scoring_previous_words_count", out spcRaw)
                && int.TryParse((spcRaw ?? "").Trim(), out var spc)
                && spc > 0)
                return false;

            string historicRaw;
            if (extras.TryGetValue("historic_words", out historicRaw)
                && !string.IsNullOrWhiteSpace(historicRaw)
                && historicRaw != "[]")
            {
                try
                {
                    var arr = JsonConvert.DeserializeObject<List<object>>(historicRaw);
                    if (arr != null && arr.Count > 0)
                        return false;
                }
                catch
                {
                    return false;
                }
            }

            if (!extras.TryGetValue("encounter_score_earned", out var earnedRaw)
                || string.IsNullOrWhiteSpace(earnedRaw))
                return false;
            if (!int.TryParse(earnedRaw.Trim(), out var earned) || earned != 0)
                return false;

            if (!extras.TryGetValue("encounter_total_target", out var totalRaw)
                || string.IsNullOrWhiteSpace(totalRaw))
                return false;
            if (!extras.TryGetValue("encounter_remaining_target", out var remainRaw)
                || string.IsNullOrWhiteSpace(remainRaw))
                return false;
            if (!int.TryParse(totalRaw.Trim(), out var total) || total <= 0)
                return false;
            if (!int.TryParse(remainRaw.Trim(), out var remaining))
                return false;
            return remaining == total;
        }

        /// <summary>
        /// Best encounter historic extras: max(live reflection, cached score hook, fallback JSON).
        /// </summary>
        public static Dictionary<string, string> BuildBestHistoricExtras(
            Player player,
            Dictionary<string, string> fallbackExtras = null,
            bool liveOnly = false
        )
        {
            var result = new Dictionary<string, string>();
            if (player == null)
                return result;

            var historic = PickBestHistoricWordList(player, liveOnly);
            if (
                (historic == null || historic.Count == 0)
                && IsFreshEncounterGridOne(fallbackExtras)
            )
                return result;
            string serialized = null;
            if (historic != null && historic.Count > 0)
                serialized = SerializeHistoricWords(historic, player);

            string fallbackHistoric = null;
            if (fallbackExtras != null
                && fallbackExtras.TryGetValue("historic_words", out fallbackHistoric))
                fallbackHistoric = fallbackHistoric ?? "";

            var bestHistoric = PreferHistoricJson(serialized, fallbackHistoric);
            if (
                IsFreshEncounterGridOne(fallbackExtras)
                && (string.IsNullOrEmpty(serialized) || serialized == "[]")
            )
                return result;
            if (
                !string.IsNullOrEmpty(serialized)
                && serialized != "[]"
                && !string.IsNullOrEmpty(fallbackHistoric)
                && fallbackHistoric != "[]"
            )
            {
                var liveCount = historic != null ? historic.Count : CountHistoricWordsInJson(serialized);
                var fallbackCount = CountHistoricWordsInJson(fallbackHistoric);
                var liveGrid = ResolveGridNumber(player);
                var fallbackGrid = -1;
                if (fallbackExtras != null)
                {
                    string gridRaw;
                    if (fallbackExtras.TryGetValue("grid_number", out gridRaw))
                        fallbackGrid = TryParseGridNumber(gridRaw);
                }
                var sameGrid =
                    liveGrid >= 1
                    && fallbackGrid >= 1
                    && liveGrid == fallbackGrid;
                if (liveCount > 0 && liveCount < fallbackCount)
                {
                    // F8 live export: never inflate historic from stale disk/cache JSON.
                    if (liveOnly)
                        bestHistoric = serialized;
                    // Same grid: live reflection can lag after the last scored word — keep longer disk/cache JSON.
                    // Grid advance: shorter live list is the new encounter historic.
                    else
                        bestHistoric = sameGrid || liveGrid <= fallbackGrid
                            ? fallbackHistoric
                            : serialized;
                }
                else if (
                    liveCount > 0
                    && liveCount == fallbackCount
                    && !string.Equals(serialized, fallbackHistoric, StringComparison.Ordinal)
                )
                    bestHistoric = serialized;
                else if (fallbackHistoric.Length > serialized.Length && liveCount == 0)
                    bestHistoric = fallbackHistoric;
                else if (serialized.Length >= fallbackHistoric.Length)
                    bestHistoric = serialized;
            }

            if (string.IsNullOrEmpty(bestHistoric) || bestHistoric == "[]")
                return result;

            result["historic_words"] = bestHistoric;

            var usedFallbackJson =
                !string.IsNullOrEmpty(fallbackHistoric)
                && bestHistoric == fallbackHistoric
                && (
                    string.IsNullOrEmpty(serialized)
                    || fallbackHistoric.Length > serialized.Length
                );

            if (!usedFallbackJson && historic != null && historic.Count > 0)
            {
                var redSum = SumRedTilesInHistoricWords(historic);
                if (redSum > 0)
                    result["red_tiles_used_encounter"] = redSum.ToString();
            }

            if (fallbackExtras != null)
            {
                string fallbackRed;
                if (
                    (!result.ContainsKey("red_tiles_used_encounter") || usedFallbackJson)
                    && fallbackExtras.TryGetValue("red_tiles_used_encounter", out fallbackRed)
                    && !string.IsNullOrEmpty(fallbackRed)
                )
                    result["red_tiles_used_encounter"] = fallbackRed;
            }

            return result;
        }

        /// <summary>
        /// F8 live export: historic and prev-letter aligned with submit-time scoring projection.
        /// </summary>
        public static Dictionary<string, string> BuildF8HistoricExtras(
            Player player,
            Dictionary<string, string> fallbackExtras
        )
        {
            var live = fallbackExtras != null
                ? new Dictionary<string, string>(fallbackExtras)
                : new Dictionary<string, string>();
            return BuildSubmitWorkflowExtras(player, live);
        }

        /// <summary>
        /// Workflow extras as they will be at score time (live player historic, not debounced run_state).
        /// </summary>
        public static Dictionary<string, string> BuildSubmitWorkflowExtras(
            Player player,
            Dictionary<string, string> liveExtras
        )
        {
            var projected = liveExtras != null
                ? new Dictionary<string, string>(liveExtras)
                : new Dictionary<string, string>();

            projected.Remove("previous_word_first_letter");
            var scoringPrevious = RunStateExporter.GetCachedPreviousWords();
            var fromPlayer = RunStateExporter.TryGetHistoricPreviousWordsPublic(player);
            var cacheCount = scoringPrevious != null ? scoringPrevious.Count : 0;
            var playerCount = fromPlayer != null ? fromPlayer.Count : 0;
            List<HistoricWord> workflowWords = null;
            if (cacheCount > 0 && playerCount > 0)
                workflowWords = cacheCount >= playerCount ? scoringPrevious : fromPlayer;
            else if (cacheCount > 0)
                workflowWords = scoringPrevious;
            else if (playerCount > 0)
                workflowWords = fromPlayer;

            if (workflowWords != null && workflowWords.Count > 0)
            {
                var captured = ScoringContextCapture.ExtractFromPreviousWords(workflowWords);
                foreach (var kv in captured)
                    projected[kv.Key] = kv.Value ?? "";

                var telescope = BuildTelescopeEncounterExtras(workflowWords, player);
                if (telescope != null)
                {
                    foreach (var kv in telescope)
                        projected[kv.Key] = kv.Value ?? "";
                }
            }

            var overlay = BuildBestHistoricExtras(player, projected, liveOnly: true);
            if (overlay != null)
            {
                foreach (var kv in overlay)
                {
                    if (
                        string.Equals(
                            kv.Key,
                            "previous_word_first_letter",
                            StringComparison.OrdinalIgnoreCase
                        )
                    )
                        continue;
                    projected[kv.Key] = kv.Value ?? "";
                }
            }

            ApplyScoringCachedPreviousWordLetter(projected, player);
            return projected;
        }

        /// <summary>
        /// Workflow extras from CalculateOverallScore previousWords (authoritative at score time).
        /// </summary>
        public static Dictionary<string, string> BuildScoringContextWorkflowExtras(
            Player player,
            Dictionary<string, string> liveExtras,
            Dictionary<string, string> scoringExtras
        )
        {
            var projected = liveExtras != null
                ? new Dictionary<string, string>(liveExtras)
                : new Dictionary<string, string>();

            if (scoringExtras != null)
            {
                foreach (var kv in scoringExtras)
                    projected[kv.Key] = kv.Value ?? "";
            }

            ApplyScoringCachedPreviousWordLetter(projected, player);
            return projected;
        }

        public static List<HistoricWord> PickBestHistoricWordList(Player player, bool liveOnly = false)
        {
            var fromPlayer = RunStateExporter.TryGetHistoricPreviousWordsPublic(player);
            var fromCached = RunStateExporter.GetCachedPreviousWords();
            var playerCount = fromPlayer != null ? fromPlayer.Count : 0;
            var cachedCount = fromCached != null ? fromCached.Count : 0;
            var grid = ResolveGridNumber(player);

            if (liveOnly)
            {
                if (cachedCount > playerCount)
                {
                    // Grid 1 word 2+: submit-hook cache is authoritative when player
                    // reflection lags after the last scored word (OnScoringContext only).
                    if (playerCount == 0 && grid < 2)
                        return cachedCount > 0 ? fromCached : null;
                    return fromCached;
                }
                // Grid 2+: scoring cache is authoritative when player reflection over-counts.
                if (grid >= 2 && cachedCount > 0 && playerCount > cachedCount)
                    return fromCached;
                // Live player reflection is authoritative when cache is empty (F8 after reshuffle).
                if (playerCount > 0)
                    return fromPlayer;
                // Grid 2+: empty cache and no live words = fresh grid (no prior-grid bleed).
                if (grid >= 2 && cachedCount == 0)
                    return null;
                if (grid >= 2 && cachedCount > 0)
                    return fromCached;
                return cachedCount > 0 ? fromCached : null;
            }

            if (grid >= 2 && cachedCount > 0 && playerCount == 0)
                return fromCached;

            // Submit-hook cache can list prior-grid words when live reflection reset (grid advance
            // clears cache in TryClearStaleHistoricCacheOnGridAdvance). When playerCount > 0 but
            // cache is longer, reflection is lagging the last scored word — prefer cache.
            if (cachedCount > playerCount)
            {
                if (playerCount == 0 && grid < 2)
                    return cachedCount > 0 ? fromCached : null;
                return fromCached;
            }

            if (cachedCount >= playerCount && cachedCount > 0)
                return fromCached;
            // Grid 2+: scoring cache is authoritative when player reflection over-counts.
            if (grid >= 2 && cachedCount > 0 && playerCount > cachedCount)
                return fromCached;
            if (playerCount > 0)
                return fromPlayer;
            return cachedCount > 0 ? fromCached : null;
        }

        private static string PreferHistoricJson(string primary, string fallback)
        {
            if (!string.IsNullOrEmpty(primary) && primary != "[]")
                return primary;
            return fallback;
        }

        /// <summary>
        /// Telescope / Movie Camera extras from live CalculateOverallScore previousWords.
        /// </summary>
        public static Dictionary<string, string> BuildTelescopeEncounterExtras(
            List<HistoricWord> words,
            Player player
        )
        {
            var best = words;
            if (player != null)
            {
                var picked = PickBestHistoricWordList(player);
                if (picked != null && (best == null || picked.Count > best.Count))
                    best = picked;
            }

            if (best == null || best.Count == 0)
                return new Dictionary<string, string>();

            var extras = new Dictionary<string, string>();
            var serialized = SerializeHistoricWords(best, player);
            if (!string.IsNullOrEmpty(serialized) && serialized != "[]")
                extras["historic_words"] = serialized;

            var redSum = SumRedTilesInHistoricWords(best);
            if (redSum > 0)
                extras["red_tiles_used_encounter"] = redSum.ToString();

            return extras;
        }

        public static int SumRedTilesInHistoricWords(List<HistoricWord> words)
        {
            if (words == null || words.Count == 0)
                return 0;
            var total = 0;
            foreach (var hw in words)
                total += CountRedTilesInHistoric(hw);
            return total;
        }

        private static bool IsMetaBossSlug(string wikiId)
        {
            if (string.IsNullOrEmpty(wikiId))
                return false;
            return wikiId == "michael"
                || wikiId == "ogre"
                || wikiId == "sandy_saguaro"
                || wikiId == "prismatic_bean"
                || wikiId == "human_boy"
                || wikiId == "human_boy_boss"
                || wikiId == "bosshumanboy"
                || wikiId == "cretaceous_meg";
        }

        private static string WikiBossIdFromModifier(BossModifier b)
        {
            if (b == null)
                return "";
            var id = BossResolver.WikiBossIdFromRuntimeType(b);
            if (!string.IsNullOrEmpty(id))
                return id;
            if (!string.IsNullOrEmpty(b.Name)
                && b.Name.IndexOf("Michael", StringComparison.OrdinalIgnoreCase) >= 0)
                return "michael";
            return RunStateExporter.Slugify(b.PrefabFileName, b.Name);
        }

        /// <summary>
        /// Boss list for export: encounter drafts, or player ActiveBossModifiers (Michael finale).
        /// </summary>
        private static List<BossModifier> ResolveBossesForExport(Player player)
        {
            var bosses = BossResolver.Resolve(player);
            if (bosses != null && bosses.Count > 0)
                return bosses;

            var michael = TryFindMichaelBossFromPlayer(player);
            if (michael != null)
                return new List<BossModifier> { michael };

            return bosses;
        }

        private static void FillBossParams(RunStateSnapshot snapshot, Player player)
        {
            var bosses = ResolveBossesForExport(player);
            if (bosses == null || bosses.Count == 0)
                return;

            var floorMods = new Dictionary<string, int>();
            var ids = new List<string>();
            foreach (var b in bosses)
            {
                if (b == null)
                    continue;
                var id = WikiBossIdFromModifier(b);
                if (string.IsNullOrEmpty(id) || IsMetaBossSlug(id))
                    continue;
                if (!ids.Contains(id))
                    ids.Add(id);
                try
                {
                    var mod = b.FloorAdjustedModification;
                    if (mod > 0)
                        floorMods[id] = mod;
                }
                catch
                {
                    // optional
                }

                var maxLen = TryGetIntProperty(b, "MaxWordLength", "MaximumWordLength");
                if (maxLen > 0)
                    snapshot.extras["wolf_max_length"] = maxLen.ToString();

                var minLen = TryGetIntProperty(b, "MinWordLength", "MinimumWordLength");
                if (minLen > 0)
                    snapshot.extras["cobra_min_length"] = minLen.ToString();
            }
            var michaelBoss = TryFindMichaelBossExtended(player, bosses);
            var boss = bosses[0];
            var michaelMin = ResolveMichaelMinWordLength(boss, michaelBoss, player);
            var liveMin = ResolveLiveEncounterMinWordLength(player, michaelBoss, snapshot);
            if (michaelMin <= 0 && liveMin > 0)
                michaelMin = liveMin;
            var drafted = ResolveMichaelDraftedCount(michaelBoss);
            if (michaelMin <= 0 && drafted >= 3
                && IsMichaelSummonedBossesDefeated(player, michaelBoss))
                michaelMin = 25;
            if (michaelMin <= 0 && drafted >= 3 && IsMichaelPuzzleGridActive())
                michaelMin = 25;
            if (michaelMin > 0)
                snapshot.extras["michael_min_word_length"] = michaelMin.ToString();
            if (liveMin > 0)
                snapshot.extras["encounter_min_word_length"] = liveMin.ToString();

            var finale = ResolveMichaelFinaleState(snapshot, player, bosses);
            RecordMichaelFinaleProbe(snapshot, player, bosses, finale);
            if (finale.IsFinale)
            {
                ApplyMichaelFinaleExport(snapshot, finale.MinWordLength, player, michaelBoss);
                return;
            }

            if (michaelBoss != null)
            {
                if (drafted >= 1 && drafted <= 3)
                    snapshot.extras["michael_phase"] = drafted.ToString();

                if (michaelMin <= 0 && drafted >= 3 && !_loggedMichaelMissingExtrasWarning)
                {
                    MelonLogger.Warning(
                        "Michael boss detected but final-phase/min-length extras were unavailable; "
                            + "run_state may miss Michael word-length enforcement."
                    );
                    _loggedMichaelMissingExtrasWarning = true;
                }
            }

            if (ids.Count > 0)
                snapshot.extras["boss_modifiers"] = JsonConvert.SerializeObject(ids);
            if (floorMods.Count > 0)
                snapshot.extras["boss_modifier_floor_mods"] = JsonConvert.SerializeObject(floorMods);
        }

        /// <summary>Michael finale puzzle grid (PuzzleController.SubmitWord).</summary>
        public static bool IsMichaelPuzzleGridActive()
        {
            try
            {
                return UnityEngine.Object.FindAnyObjectByType<PuzzleController>() != null;
            }
            catch
            {
                return false;
            }
        }

        public struct MichaelFinaleState
        {
            public bool IsFinale;
            public int MinWordLength;
        }

        public static BossModifier TryFindMichaelBossExtended(
            Player player,
            List<BossModifier> bosses
        )
        {
            var fromList = FindMichaelBoss(bosses);
            if (fromList != null)
                return fromList;

            var fromPlayer = TryFindMichaelBossFromPlayer(player);
            if (fromPlayer != null)
                return fromPlayer;

            var encounter = BossResolver.TryGetEncounter();
            var fromEncounter = TryFindMichaelBossOnObject(encounter);
            if (fromEncounter != null)
                return fromEncounter;

            var fromPlayerScan = FindMichaelBossByTypeScan(player);
            if (fromPlayerScan != null)
                return fromPlayerScan;

            var fromEncounterScan = FindMichaelBossByTypeScan(encounter);
            if (fromEncounterScan != null)
                return fromEncounterScan;

            return TryFindMichaelBossOnObject(player);
        }

        /// <summary>
        /// Michael lives on Player.ActiveBossModifiers[0], not in EncounterController.GetBossModifiers().
        /// </summary>
        public static BossModifier TryFindMichaelBossFromPlayer(Player player)
        {
            if (player?.ActiveBossModifiers == null || player.ActiveBossModifiers.Count == 0)
                return null;
            var first = player.ActiveBossModifiers[0];
            return IsMichaelBossModifier(first) ? first : null;
        }

        public static BossModifier FindMichaelBossByTypeScan(object target)
        {
            if (target == null)
                return null;

            var type = target.GetType();
            foreach (var field in type.GetFields(MemberFlags))
            {
                try
                {
                    var val = field.GetValue(target);
                    if (val is BossModifier bm && IsMichaelBossModifier(bm))
                        return bm;
                }
                catch
                {
                    // optional
                }
            }

            foreach (var prop in type.GetProperties(MemberFlags))
            {
                if (!prop.CanRead || prop.GetIndexParameters().Length > 0)
                    continue;
                try
                {
                    var val = prop.GetValue(target, null);
                    if (val is BossModifier bm && IsMichaelBossModifier(bm))
                        return bm;
                }
                catch
                {
                    // optional
                }
            }

            return null;
        }

        private static BossModifier TryFindMichaelBossOnObject(object target)
        {
            if (target == null)
                return null;

            foreach (var name in new[]
            {
                "MichaelBoss",
                "_michaelBoss",
                "ActiveMichaelBoss",
                "Michael",
                "MichaelModifier",
                "_michaelModifier",
            })
            {
                var boss = TryGetBossModifierMember(target, name);
                if (boss != null && IsMichaelBossModifier(boss))
                    return boss;
            }

            return FindMichaelBossByTypeScan(target);
        }

        private static bool IsMichaelBossModifier(BossModifier boss)
        {
            if (boss == null)
                return false;
            if (boss.GetType().Name == "MichaelBoss")
                return true;
            return !string.IsNullOrEmpty(boss.Name)
                && boss.Name.IndexOf("Michael", StringComparison.OrdinalIgnoreCase) >= 0;
        }

        private static BossModifier TryGetBossModifierMember(object target, string name)
        {
            try
            {
                var prop = target.GetType().GetProperty(name, MemberFlags);
                if (prop != null)
                {
                    var val = prop.GetValue(target, null) as BossModifier;
                    if (val != null)
                        return val;
                }

                var field = target.GetType().GetField(name, MemberFlags);
                if (field != null)
                    return field.GetValue(target) as BossModifier;
            }
            catch
            {
                // optional
            }

            return null;
        }

        public static int ResolveMichaelDraftedCount(BossModifier michaelBoss)
        {
            if (michaelBoss == null)
                return -1;

            var draftedList = TryGetBossListMember(michaelBoss, "DraftedModifiers", isField: false);
            if (draftedList == null)
                draftedList = TryGetBossListMember(michaelBoss, "DraftedModifiers", isField: true);
            if (draftedList == null)
                draftedList = TryGetBossListMember(michaelBoss, "SummonedBosses", isField: false);
            if (draftedList == null)
                draftedList = TryGetBossListMember(michaelBoss, "SummonedBosses", isField: true);
            return draftedList != null ? draftedList.Count : -1;
        }

        public static bool IsMichaelSummonedBossesDefeated(
            Player player,
            BossModifier michaelBoss
        )
        {
            if (
                michaelBoss != null
                && TryGetBoolMember(
                    michaelBoss,
                    "SummonedBossesDefeated",
                    "AreSummonedBossesDefeated",
                    "FinalPhaseComplete",
                    "FinaleComplete",
                    "IsFinalePhase",
                    "FinalePhase",
                    "IsWordsmithPhase",
                    "InFinalePhase"
                )
            )
                return true;

            var encounter = BossResolver.TryGetEncounter();
            if (
                TryGetBoolMember(
                    encounter,
                    "SummonedBossesDefeated",
                    "AreSummonedBossesDefeated",
                    "MichaelSummonedBossesDefeated",
                    "MichaelFinaleComplete",
                    "IsFinalePhase",
                    "FinalePhase"
                )
            )
                return true;

            if (player != null)
            {
                if (
                    TryGetBoolMember(
                        player,
                        "MichaelSummonedBossesDefeated",
                        "MichaelFinaleComplete",
                        "SummonedBossesDefeated"
                    )
                )
                    return true;
            }

            return false;
        }

        public static MichaelFinaleState ResolveMichaelFinaleState(
            RunStateSnapshot snapshot,
            Player player,
            List<BossModifier> bosses
        )
        {
            var result = new MichaelFinaleState();
            if (bosses == null || bosses.Count == 0)
                return result;

            var michaelBoss = TryFindMichaelBossExtended(player, bosses);
            var boss = bosses[0];
            var michaelMin = ResolveMichaelMinWordLength(boss, michaelBoss, player);
            var drafted = ResolveMichaelDraftedCount(michaelBoss);
            var liveMin = ResolveLiveEncounterMinWordLength(player, michaelBoss, snapshot);

            if (michaelBoss != null && TryResolveMichaelFinale(michaelBoss, player, drafted, michaelMin, liveMin))
                result.IsFinale = true;
            else if (IsMichaelPuzzleGridActive())
                result.IsFinale = true;
            else if (IsMichaelSummonedBossesDefeated(player, michaelBoss))
                result.IsFinale = true;

            if (!result.IsFinale)
            {
                result.MinWordLength = liveMin > 0 ? liveMin : michaelMin;
                return result;
            }

            result.MinWordLength = ResolveFinaleMinWordLength(
                snapshot,
                player,
                michaelBoss,
                boss,
                liveMin > 0 ? liveMin : michaelMin
            );
            if (result.MinWordLength <= 0)
                result.MinWordLength = 25;
            return result;
        }

        public static int ResolveLiveEncounterMinWordLength(
            Player player,
            BossModifier michaelBoss,
            RunStateSnapshot snapshot
        )
        {
            if (IsMichaelSummonedBossesDefeated(player, michaelBoss))
                return 25;

            try
            {
                var tsm = UnityEngine.Object.FindAnyObjectByType<TileSelectionManager>();
                if (tsm != null)
                {
                    if (
                        TryGetBoolMember(
                            tsm,
                            "_isFinalPuzzleGrid",
                            "IsFinalPuzzleGrid",
                            "FinalPuzzleGrid"
                        )
                    )
                        return 25;

                    var fromTsm = TryGetIntMember(
                        tsm,
                        "MinWordLength",
                        "MinimumWordLength",
                        "RequiredWordLength",
                        "WordLengthRequirement",
                        "CurrentMinWordLength",
                        "TargetWordLength",
                        "WordLengthGoal"
                    );
                    if (fromTsm > 0)
                        return fromTsm;
                }
            }
            catch
            {
                // optional
            }

            var encounter = BossResolver.TryGetEncounter();
            if (encounter != null)
            {
                var fromEncounter = TryGetIntMember(
                    encounter,
                    "MinWordLength",
                    "MinimumWordLength",
                    "RequiredWordLength",
                    "WordLengthRequirement",
                    "CurrentMinWordLength",
                    "TargetWordLength",
                    "MichaelMinWordLength",
                    "WordsmithMinWordLength"
                );
                if (fromEncounter > 0)
                    return fromEncounter;
            }

            return -1;
        }

        private static int ResolveMichaelRunArea(Player player)
        {
            var area = BossResolver.TryGetRunStage(player);
            if (area >= 6)
                return area;

            if (player != null)
            {
                area = TryGetIntProperty(
                    player,
                    "AreaNumber",
                    "CurrentArea",
                    "StageNumber",
                    "CurrentStage",
                    "AreaIndex"
                );
                if (area >= 6)
                    return area;
            }

            return area;
        }

        private static void RecordMichaelFinaleProbe(
            RunStateSnapshot snapshot,
            Player player,
            List<BossModifier> bosses,
            MichaelFinaleState finale
        )
        {
            if (snapshot == null || ResolveMichaelRunArea(player) < 6)
                return;

            var michaelBoss = TryFindMichaelBossExtended(player, bosses);
            var liveMin = ResolveLiveEncounterMinWordLength(player, michaelBoss, snapshot);
            var parts = new List<string>
            {
                "finale=" + (finale.IsFinale ? "1" : "0"),
                "michael_boss=" + (michaelBoss != null ? "1" : "0"),
                "summoned_defeated="
                    + (IsMichaelSummonedBossesDefeated(player, michaelBoss) ? "1" : "0"),
                "live_min=" + (liveMin > 0 ? liveMin.ToString() : "-"),
                "active_tiles=" + CountActiveBoardTiles(snapshot),
            };
            snapshot.extras["michael_finale_probe"] = string.Join(",", parts);
        }

        public static int ResolveFinaleMinWordLength(
            RunStateSnapshot snapshot,
            Player player,
            BossModifier michaelBoss,
            BossModifier primaryBoss,
            int michaelMin
        )
        {
            if (michaelMin > 0)
                return michaelMin;

            try
            {
                var puzzle = UnityEngine.Object.FindAnyObjectByType<PuzzleController>();
                if (puzzle != null)
                {
                    var fromPuzzle = TryGetIntMember(
                        puzzle,
                        "MinWordLength",
                        "MinimumWordLength",
                        "RequiredWordLength",
                        "WordLengthRequirement",
                        "CurrentMinWordLength",
                        "TargetWordLength",
                        "WordLengthGoal"
                    );
                    if (fromPuzzle > 0)
                        return fromPuzzle;
                }
            }
            catch
            {
                // optional
            }

            var fromBoard = CountActiveBoardTiles(snapshot);
            if (fromBoard > 0)
                return fromBoard;

            return 25;
        }

        public static void ApplyMichaelFinaleExport(
            RunStateSnapshot snapshot,
            int finaleMin,
            Player player,
            BossModifier michaelBoss
        )
        {
            if (snapshot == null)
                return;

            var summonedDefeated = IsMichaelSummonedBossesDefeated(player, michaelBoss);
            var puzzleGrid = IsMichaelPuzzleGridActive();

            snapshot.boss_id = "michael";
            snapshot.boss_name = "Michael";
            snapshot.boss_effect = "";
            if (summonedDefeated)
                snapshot.extras["michael_summoned_bosses_defeated"] = "true";
            else
                snapshot.extras.Remove("michael_summoned_bosses_defeated");
            snapshot.extras["michael_phase"] = "4";
            if (summonedDefeated || puzzleGrid)
            {
                snapshot.extras["boss_modifiers"] = "[]";
                snapshot.extras.Remove("boss_modifier_floor_mods");
            }
            snapshot.extras["michael_min_word_length"] = finaleMin.ToString();
            snapshot.extras["encounter_min_word_length"] = finaleMin.ToString();
            if (puzzleGrid)
            {
                snapshot.extras["michael_puzzle_grid"] = "true";
            }
        }

        /// <summary>
        /// Michael finale (phase 4): summoned draft bosses inactive; 25-tile word required.
        /// </summary>
        public static bool TryResolveMichaelFinale(
            BossModifier michaelBoss,
            Player player,
            int draftedCount,
            int michaelMin,
            int liveMin = -1
        )
        {
            if (michaelBoss == null)
                return false;

            if (
                TryGetBoolMember(
                    michaelBoss,
                    "SummonedBossesDefeated",
                    "AreSummonedBossesDefeated",
                    "FinalPhaseComplete",
                    "FinaleComplete",
                    "IsFinalePhase",
                    "FinalePhase",
                    "IsWordsmithPhase",
                    "InFinalePhase"
                )
            )
                return true;

            var encounter = BossResolver.TryGetEncounter();
            if (
                TryGetBoolMember(
                    encounter,
                    "SummonedBossesDefeated",
                    "AreSummonedBossesDefeated",
                    "MichaelSummonedBossesDefeated",
                    "MichaelFinaleComplete",
                    "IsFinalePhase",
                    "FinalePhase"
                )
            )
                return true;

            if (player != null)
            {
                if (
                    TryGetBoolMember(
                        player,
                        "MichaelSummonedBossesDefeated",
                        "MichaelFinaleComplete",
                        "SummonedBossesDefeated"
                    )
                )
                    return true;
            }

            var phase = TryGetIntMember(
                michaelBoss,
                "CurrentPhase",
                "Phase",
                "MichaelPhase",
                "ActivePhase",
                "BossPhase"
            );
            if (phase < 0 && encounter != null)
                phase = TryGetIntMember(
                    encounter,
                    "CurrentPhase",
                    "Phase",
                    "MichaelPhase",
                    "ActivePhase"
                );
            if (phase >= 4)
                return true;

            return false;
        }

        public static BossModifier FindMichaelBoss(List<BossModifier> bosses)
        {
            if (bosses == null || bosses.Count == 0)
                return null;
            return bosses.Find(b =>
                b != null
                && (
                    b.GetType().Name == "MichaelBoss"
                    || (!string.IsNullOrEmpty(b.Name)
                        && b.Name.IndexOf("Michael", StringComparison.OrdinalIgnoreCase) >= 0)
                )
            );
        }

        public static int ResolveMichaelMinWordLength(
            BossModifier primaryBoss,
            BossModifier michaelBoss,
            Player player
        )
        {
            var michaelMin = ResolveMichaelMinWordLengthFromProbe(
                michaelBoss ?? primaryBoss,
                player
            );
            if (michaelMin < 0 && michaelBoss != null && michaelBoss != primaryBoss)
                michaelMin = ResolveMichaelMinWordLengthFromProbe(primaryBoss, player);
            if (michaelMin < 0)
                michaelMin = ResolveMichaelMinFromDraftedBosses(michaelBoss);
            if (michaelMin < 0)
                michaelMin = ResolveMichaelMinFromDraftedBosses(primaryBoss);
            return michaelMin;
        }

        private static int ResolveMichaelMinWordLengthFromProbe(
            BossModifier probe,
            Player player
        )
        {
            if (probe == null && player == null)
                return -1;

            var michaelMin = -1;
            if (probe != null)
            {
                michaelMin = TryGetIntMember(
                    probe,
                    "MinWordLength",
                    "MinimumWordLength",
                    "CurrentMinWordLength",
                    "RequiredWordLength",
                    "WordLengthRequirement",
                    "TargetWordLength",
                    "WordLengthGoal",
                    "WordsmithMinWordLength",
                    "CurrentWordsmithMinWordLength",
                    "MichaelMinWordLength"
                );
            }
            if (michaelMin < 0 && player != null)
            {
                michaelMin = TryGetIntMember(
                    player,
                    "MichaelMinWordLength",
                    "WordsmithMinWordLength",
                    "BossMinWordLength",
                    "MinWordLengthRequirement",
                    "CurrentMinWordLength"
                );
            }
            if (michaelMin < 0)
            {
                var encounter = BossResolver.TryGetEncounter();
                if (encounter != null)
                {
                    michaelMin = TryGetIntMember(
                        encounter,
                        "MichaelMinWordLength",
                        "WordsmithMinWordLength",
                        "BossMinWordLength",
                        "MinWordLength",
                        "RequiredWordLength",
                        "WordLengthRequirement",
                        "CurrentMinWordLength",
                        "TargetWordLength",
                        "CurrentWordsmithMinWordLength"
                    );
                    if (michaelMin < 0)
                        michaelMin = TryFindMichaelMinOnObject(encounter);
                }
            }
            if (michaelMin < 0 && probe != null)
                michaelMin = TryFindMichaelMinOnObject(probe);
            return michaelMin;
        }

        private static int TryFindMichaelMinOnObject(object target)
        {
            if (target == null)
                return -1;

            foreach (var name in new[]
            {
                "MichaelBoss",
                "_michaelBoss",
                "ActiveMichaelBoss",
                "WordsmithController",
                "WordsmithManager",
                "TileSelectionManager",
            })
            {
                var nested = TryGetBossModifierMember(target, name);
                if (nested == null)
                    continue;
                var min = TryGetIntMember(
                    nested,
                    "MinWordLength",
                    "MinimumWordLength",
                    "CurrentMinWordLength",
                    "WordsmithMinWordLength",
                    "CurrentWordsmithMinWordLength",
                    "RequiredWordLength",
                    "WordLengthRequirement",
                    "TargetWordLength",
                    "WordLengthGoal",
                    "WordsmithMinLength",
                    "CurrentWordLength",
                    "MinWordsmithLength"
                );
                if (min > 0)
                    return min;
            }

            return -1;
        }

        private static int ResolveMichaelMinFromDraftedBosses(BossModifier michaelBoss)
        {
            if (michaelBoss == null)
                return -1;

            var draftedList = TryGetBossListMember(michaelBoss, "DraftedModifiers", isField: false);
            if (draftedList == null)
                draftedList = TryGetBossListMember(michaelBoss, "DraftedModifiers", isField: true);
            if (draftedList == null)
                draftedList = TryGetBossListMember(michaelBoss, "SummonedBosses", isField: false);
            if (draftedList == null)
                draftedList = TryGetBossListMember(michaelBoss, "SummonedBosses", isField: true);
            if (draftedList == null || draftedList.Count == 0)
                return -1;

            var best = -1;
            foreach (var drafted in draftedList)
            {
                if (drafted == null)
                    continue;
                var minLen = TryGetIntProperty(
                    drafted,
                    "MinWordLength",
                    "MinimumWordLength",
                    "CurrentMinWordLength",
                    "RequiredWordLength",
                    "WordLengthRequirement",
                    "TargetWordLength",
                    "WordLengthGoal"
                );
                if (minLen > best)
                    best = minLen;
            }
            return best;
        }

        private static int CountActiveBoardTiles(RunStateSnapshot snapshot)
        {
            if (snapshot?.board?.tiles == null)
                return 0;
            var count = 0;
            foreach (var tile in snapshot.board.tiles)
            {
                if (tile != null && tile.active)
                    count++;
            }
            if (count > 0)
                return count;
            // Board may not have active flags yet; treat full 25-tile export as active.
            var total = snapshot.board.tiles.Count;
            return total >= 25 ? 25 : total;
        }

        public static List<BossModifier> TryGetBossListMember(
            object target,
            string name,
            bool isField
        )
        {
            try
            {
                object value;
                if (isField)
                {
                    var field = target.GetType().GetField(name, MemberFlags);
                    if (field == null)
                        return null;
                    value = field.GetValue(target);
                }
                else
                {
                    var prop = target.GetType().GetProperty(name, MemberFlags);
                    if (prop == null)
                        return null;
                    value = prop.GetValue(target, null);
                }
                if (value is System.Collections.IList list)
                {
                    var result = new List<BossModifier>();
                    foreach (var item in list)
                    {
                        if (item is BossModifier bm)
                            result.Add(bm);
                    }
                    return result;
                }
            }
            catch
            {
                // optional
            }
            return null;
        }

        private static string SerializeItemSlugOrder(Item[] items)
        {
            var slugs = new List<string>();
            if (items != null)
            {
                foreach (var item in items)
                {
                    if (item == null)
                        continue;
                    slugs.Add(RunStateExporter.Slugify(item.ArtFileName, item.Name));
                }
            }
            return JsonConvert.SerializeObject(slugs);
        }

        private static string SerializeHistoricWords(List<HistoricWord> words, Player player)
        {
            var takeLimit = TryGetMovieCameraTakeLimit(player);
            var rows = new List<Dictionary<string, object>>();
            foreach (var hw in words)
            {
                if (hw == null)
                    continue;
                var row = new Dictionary<string, object>();
                try
                {
                    var word = hw.GetSubmittedWordString();
                    word = StripHistoricWordRichText(word);
                    if (!string.IsNullOrEmpty(word))
                        row["word"] = word;
                }
                catch
                {
                    // optional
                }

                try
                {
                    if (hw.Score != null)
                        row["score"] = ScoringTraceCollector.ScorePacketToLong(hw.Score);
                }
                catch
                {
                    // optional
                }

                var path = new List<int>();
                try
                {
                    if (hw.TileSelections != null)
                    {
                        foreach (var sel in hw.TileSelections)
                        {
                            if (sel?.SelectedTile == null)
                                continue;
                            var coords = sel.SelectedTile.GetCoordinates();
                            path.Add(coords.y * 5 + coords.x);
                        }
                    }
                }
                catch
                {
                    // optional
                }
                if (path.Count > 0)
                    row["path"] = path;

                try
                {
                    var redCount = CountRedTilesInHistoric(hw);
                    if (redCount > 0)
                        row["red_tile_count"] = redCount;
                }
                catch
                {
                    // optional
                }

                try
                {
                    var greenCount = CountGreenTilesInHistoric(hw);
                    if (greenCount > 0)
                        row["green_tile_count"] = greenCount;
                }
                catch
                {
                    // optional
                }

                try
                {
                    var takeValue = ComputeHistoricMovieCameraTakeValue(hw, takeLimit);
                    if (takeValue > 0)
                        row["chess_take_value"] = takeValue;
                }
                catch
                {
                    // optional
                }

                if (row.Count > 0)
                    rows.Add(row);
            }
            return JsonConvert.SerializeObject(rows);
        }

        private static int CountRedTilesInHistoric(HistoricWord hw)
        {
            if (hw?.Tiles == null)
                return 0;
            var count = 0;
            foreach (var tile in hw.Tiles)
            {
                if (tile != null && tile.IsTileType(TileType.Red))
                    count++;
            }
            return count;
        }

        private static int CountGreenTilesInHistoric(HistoricWord hw)
        {
            var count = 0;
            if (hw?.TileSelections != null)
            {
                foreach (var sel in hw.TileSelections)
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
            }
            if (count > 0)
                return count;
            if (hw?.Tiles == null)
                return 0;
            foreach (var tile in hw.Tiles)
            {
                if (tile != null && tile.IsTileType(TileType.Green))
                    count++;
            }
            return count;
        }

        private static int ComputeHistoricMovieCameraTakeValue(HistoricWord hw, int takeLimit)
        {
            if (hw?.TileSelections == null || takeLimit <= 0)
                return 0;
            var takeNum = 0;
            var total = 0;
            for (var i = 0; i < hw.TileSelections.Count; i++)
            {
                var sel = hw.TileSelections[i];
                if (sel == null)
                    continue;
                if (
                    sel.SelectionMethod != TileSelectionMethod.ChessTake
                    && sel.SelectionMethod != TileSelectionMethod.EnPassant
                )
                    continue;
                if (takeNum < takeLimit)
                {
                    Tile tile = null;
                    if (hw.Tiles != null && i < hw.Tiles.Count)
                        tile = hw.Tiles[i];
                    if (tile == null)
                        tile = sel.SelectedTile;
                    if (tile != null)
                        total += Alphabet.GetChessValue(tile.PieceType);
                }
                takeNum++;
            }
            return total;
        }

        private static int TryGetMovieCameraTakeLimit(Player player)
        {
            if (player == null)
                return 1;
            try
            {
                var stickers = player.GetStickers(forItemComparison: true);
                if (stickers == null)
                    return 1;
                foreach (var item in stickers)
                {
                    if (item == null)
                        continue;
                    var mc = item as MovieCamera;
                    if (mc?.UpgradeableComponents != null && mc.UpgradeableComponents.Count > 0)
                        return Math.Max(1, mc.UpgradeableComponents[0].VariableValue);
                    var slug = RunStateExporter.Slugify(item.ArtFileName, item.Name);
                    if (slug != "movie_camera")
                        continue;
                    var comps = item.UpgradeableComponents;
                    if (comps != null && comps.Count > 0)
                        return Math.Max(1, comps[0].VariableValue);
                }
            }
            catch
            {
                // fall through
            }
            return 1;
        }

        private static bool ItemMatchesRarity(object item, string[] rarities)
        {
            if (item == null)
                return false;
            var rarity = TryGetRarityLabel(item, "Rarity", "ItemRarity", "rarity");
            if (string.IsNullOrEmpty(rarity))
                return false;
            foreach (var r in rarities)
            {
                if (rarity.Equals(r, StringComparison.OrdinalIgnoreCase))
                    return true;
            }
            return false;
        }

        /// <summary>Rarity may be a string property or an enum (ToString).</summary>
        private static string TryGetRarityLabel(object target, params string[] names)
        {
            if (target == null)
                return "";
            foreach (var name in names)
            {
                try
                {
                    var prop = target.GetType().GetProperty(name, MemberFlags);
                    if (prop != null)
                    {
                        var val = prop.GetValue(target, null);
                        if (val is string s && !string.IsNullOrEmpty(s))
                            return s;
                        if (val != null)
                            return val.ToString();
                    }
                    var field = target.GetType().GetField(name, MemberFlags);
                    if (field != null)
                    {
                        var val = field.GetValue(target);
                        if (val is string s && !string.IsNullOrEmpty(s))
                            return s;
                        if (val != null)
                            return val.ToString();
                    }
                }
                catch
                {
                    // try next
                }
            }
            return "";
        }

        /// <summary>Count owned RARE stickers/stamps/pin for Steak export (returns -1 if unknown).</summary>
        public static int CountRareItemsForPlayer(Player player)
        {
            return CountItemsMatchingRarity(player, "Rare", "RARE");
        }

        private static int CountItemsMatchingRarity(Player player, params string[] rarities)
        {
            if (player == null)
                return -1;

            var count = 0;
            var found = false;
            void Scan(Item[] items)
            {
                if (items == null)
                    return;
                foreach (var item in items)
                {
                    if (item == null)
                        continue;
                    if (!ItemMatchesRarity(item, rarities))
                        continue;
                    count++;
                    found = true;
                }
            }

            Scan(player.Stickers);
            Scan(player.Stamps);
            try
            {
                var pin = player.MyCharacter?.CharacterItem;
                if (pin != null && ItemMatchesRarity(pin, rarities))
                {
                    count++;
                    found = true;
                }
            }
            catch
            {
                // optional
            }

            return found ? count : -1;
        }

        private static int CountUnpackedOfTypeName(Player player, string typeName)
        {
            if (player == null)
                return -1;
            try
            {
                var type = Type.GetType(typeName);
                if (type == null)
                    return -1;
                var method = player.GetType().GetMethod(
                    "GetUnpackedItemsOfType",
                    BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic
                );
                if (method == null)
                    return -1;
                var list = method.Invoke(player, new object[] { type }) as System.Collections.IList;
                return list?.Count ?? 0;
            }
            catch
            {
                return -1;
            }
        }

        private static int CountStampsMatching(Player player, params string[] slugParts)
        {
            if (player?.Stamps == null)
                return 0;
            var count = 0;
            foreach (var stamp in player.Stamps)
            {
                if (stamp == null)
                    continue;
                var slug = RunStateExporter.Slugify(stamp.ArtFileName, stamp.Name);
                foreach (var part in slugParts)
                {
                    if (slug.IndexOf(part, StringComparison.OrdinalIgnoreCase) >= 0)
                    {
                        count++;
                        break;
                    }
                }
            }
            return count;
        }

        private static object TryGetRunProgress(Player player)
        {
            if (player == null)
                return null;
            try
            {
                return player.CurrentRunProgress;
            }
            catch
            {
                try
                {
                    var field = player.GetType().GetField(
                        "CurrentRunProgress",
                        BindingFlags.Public | BindingFlags.Instance
                    );
                    return field?.GetValue(player);
                }
                catch
                {
                    return null;
                }
            }
        }

        private static int TryGetConsumableRackCount(Player player)
        {
            if (player == null)
                return -1;
            try
            {
                var rack = player.GetType().GetProperty("ConsumableRack", MemberFlags);
                if (rack != null)
                {
                    var value = rack.GetValue(player, null) as System.Collections.ICollection;
                    if (value != null)
                        return value.Count;
                }
            }
            catch
            {
                // optional
            }
            return -1;
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
                    if (prop == null)
                        continue;
                    return TryReadIntLike(prop.GetValue(target, null));
                }
                catch
                {
                    // try next
                }
            }
            return -1;
        }

        private static bool TryGetBoolProperty(object target, params string[] names)
        {
            if (target == null)
                return false;
            foreach (var name in names)
            {
                try
                {
                    var prop = target.GetType().GetProperty(name, MemberFlags);
                    if (prop == null)
                        continue;
                    var val = prop.GetValue(target, null);
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

        private static bool TryGetBoolMember(object target, params string[] names)
        {
            return TryGetBoolProperty(target, names) || TryGetBoolField(target, names);
        }

        private static int TryGetIntMember(object target, params string[] names)
        {
            var fromProp = TryGetIntProperty(target, names);
            if (fromProp >= 0)
                return fromProp;
            return TryGetIntField(target, names);
        }

        private static int TryGetIntField(object target, params string[] names)
        {
            if (target == null)
                return -1;
            foreach (var name in names)
            {
                try
                {
                    var field = target.GetType().GetField(name, MemberFlags);
                    if (field == null)
                        continue;
                    return TryReadIntLike(field.GetValue(target));
                }
                catch
                {
                    // try next
                }
            }
            return -1;
        }

        private static bool TryGetBoolField(object target, params string[] names)
        {
            if (target == null)
                return false;
            foreach (var name in names)
            {
                try
                {
                    var field = target.GetType().GetField(name, MemberFlags);
                    if (field == null)
                        continue;
                    var val = field.GetValue(target);
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
                    var s = prop.GetValue(target, null) as string;
                    if (!string.IsNullOrEmpty(s))
                        return s;
                }
                catch
                {
                    // try next
                }
            }
            return "";
        }

        private static int TryReadIntLike(object raw)
        {
            if (raw == null)
                return -1;
            if (raw is int i)
                return i;
            if (raw is long l && l >= 0 && l <= int.MaxValue)
                return (int)l;
            return -1;
        }
    }
}
