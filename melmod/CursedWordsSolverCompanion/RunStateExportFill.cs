using System;
using System.Collections.Generic;
using System.Reflection;
using System.Text;
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

        /// <summary>Last gridNumber from CalculateOverallScore (most accurate).</summary>
        public static int CachedGridNumber = -1;

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
            FillFutureProofTierA(snapshot, player);
            FillBossParams(snapshot, player);
        }

        public static void AppendEncounterFingerprint(StringBuilder sb, Player player)
        {
            if (player == null || sb == null)
                return;

            var gridNum = ResolveGridNumber(player);
            sb.Append('|');
            sb.Append(gridNum);

            var consumables = TryGetIntProperty(
                player,
                "ConsumableRackCount",
                "ConsumableCount",
                "ConsumablesOnRack"
            );
            if (consumables < 0)
                consumables = TryGetConsumableRackCount(player);
            sb.Append('|');
            sb.Append(consumables >= 0 ? consumables : -1);

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

            if (BoardExporter.TryBuild(player) != null)
                return "encounter";

            var encounter = BossResolver.TryGetEncounter();
            if (encounter != null)
                return "encounter";

            if (TryGetBoolProperty(player, "InShop", "IsInShop", "ShopActive"))
                return "shop";

            return "none";
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

            var historic = RunStateExporter.TryGetHistoricPreviousWordsPublic(player);
            if (historic != null && historic.Count > 0)
            {
                snapshot.extras["historic_words"] = SerializeHistoricWords(historic);
                if (!snapshot.extras.ContainsKey("previous_word_first_letter"))
                {
                    var prev = ScoringContextCapture.FirstLetterFromHistoricWords(historic);
                    if (!string.IsNullOrEmpty(prev))
                        snapshot.extras["previous_word_first_letter"] = prev;
                }
            }
        }

        private static void FillBossParams(RunStateSnapshot snapshot, Player player)
        {
            if (string.IsNullOrEmpty(snapshot.boss_id))
                return;

            var bosses = BossResolver.Resolve(player);
            if (bosses == null || bosses.Count == 0 || bosses[0] == null)
                return;

            var boss = bosses[0];
            var maxLen = TryGetIntProperty(boss, "MaxWordLength", "MaximumWordLength");
            if (maxLen > 0 && snapshot.boss_id == "wolf")
                snapshot.extras["wolf_max_length"] = maxLen.ToString();

            var minLen = TryGetIntProperty(boss, "MinWordLength", "MinimumWordLength");
            if (minLen > 0 && snapshot.boss_id == "cobra")
                snapshot.extras["cobra_min_length"] = minLen.ToString();

            var ids = new List<string>();
            foreach (var b in bosses)
            {
                if (b == null)
                    continue;
                var id = BossResolver.WikiBossIdFromRuntimeType(b);
                if (string.IsNullOrEmpty(id) && !string.IsNullOrEmpty(b.Name)
                    && b.Name.IndexOf("Michael", StringComparison.OrdinalIgnoreCase) >= 0)
                    id = "michael";
                if (string.IsNullOrEmpty(id))
                    id = RunStateExporter.Slugify(b.PrefabFileName, b.Name);
                if (!string.IsNullOrEmpty(id))
                    ids.Add(id);
            }
            if (ids.Count > 0)
                snapshot.extras["boss_modifiers"] = JsonConvert.SerializeObject(ids);

            var michaelMin = TryGetIntProperty(
                boss,
                "MinWordLength",
                "MinimumWordLength",
                "CurrentMinWordLength",
                "RequiredWordLength",
                "WordLengthRequirement"
            );
            if (michaelMin < 0)
                michaelMin = TryGetIntProperty(
                    player,
                    "MichaelMinWordLength",
                    "WordsmithMinWordLength",
                    "BossMinWordLength"
                );
            if (michaelMin < 0)
            {
                var encounter = BossResolver.TryGetEncounter();
                if (encounter != null)
                    michaelMin = TryGetIntProperty(
                        encounter,
                        "MichaelMinWordLength",
                        "WordsmithMinWordLength",
                        "BossMinWordLength",
                        "MinWordLength",
                        "RequiredWordLength"
                    );
            }
            if (michaelMin > 0)
                snapshot.extras["michael_min_word_length"] = michaelMin.ToString();
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

        private static string SerializeHistoricWords(List<HistoricWord> words)
        {
            var rows = new List<Dictionary<string, object>>();
            foreach (var hw in words)
            {
                if (hw == null)
                    continue;
                var row = new Dictionary<string, object>();
                try
                {
                    var word = hw.GetSubmittedWordString();
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

                if (row.Count > 0)
                    rows.Add(row);
            }
            return JsonConvert.SerializeObject(rows);
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
                    var rarity = TryGetStringProperty(item, "Rarity", "ItemRarity", "rarity");
                    if (string.IsNullOrEmpty(rarity))
                        continue;
                    foreach (var r in rarities)
                    {
                        if (rarity.Equals(r, StringComparison.OrdinalIgnoreCase))
                        {
                            count++;
                            found = true;
                            break;
                        }
                    }
                }
            }

            Scan(player.Stickers);
            Scan(player.Stamps);
            try
            {
                var pin = player.MyCharacter?.CharacterItem;
                if (pin != null)
                {
                    var rarity = TryGetStringProperty(pin, "Rarity", "ItemRarity");
                    foreach (var r in rarities)
                    {
                        if (rarity.Equals(r, StringComparison.OrdinalIgnoreCase))
                        {
                            count++;
                            found = true;
                        }
                    }
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
                var prop = player.GetType().GetProperty(
                    "CurrentRunProgress",
                    BindingFlags.Public | BindingFlags.Instance
                );
                return prop?.GetValue(player, null);
            }
            catch
            {
                return null;
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
