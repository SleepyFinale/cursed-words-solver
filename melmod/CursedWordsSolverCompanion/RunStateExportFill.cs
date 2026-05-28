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
        private static bool _loggedMichaelMissingExtrasWarning = false;

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
            "michael_phase",
            "michael_summoned_bosses_defeated",
            "boss_modifier_floor_mods",
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
            RunStateExporter.FillSnapshotCopyExtras(snapshot, player);
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

        private static bool IsMetaBossSlug(string wikiId)
        {
            if (string.IsNullOrEmpty(wikiId))
                return false;
            return wikiId == "michael"
                || wikiId == "ogre"
                || wikiId == "sandy_saguaro"
                || wikiId == "prismatic_bean"
                || wikiId == "human_boy"
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

        private static void FillBossParams(RunStateSnapshot snapshot, Player player)
        {
            var bosses = BossResolver.Resolve(player);
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
            if (ids.Count > 0)
                snapshot.extras["boss_modifiers"] = JsonConvert.SerializeObject(ids);
            if (floorMods.Count > 0)
                snapshot.extras["boss_modifier_floor_mods"] = JsonConvert.SerializeObject(floorMods);

            var boss = bosses[0];
            var michaelMin = TryGetIntMember(
                boss,
                "MinWordLength",
                "MinimumWordLength",
                "CurrentMinWordLength",
                "RequiredWordLength",
                "WordLengthRequirement",
                "TargetWordLength",
                "WordLengthGoal"
            );
            if (michaelMin < 0)
                michaelMin = TryGetIntMember(
                    player,
                    "MichaelMinWordLength",
                    "WordsmithMinWordLength",
                    "BossMinWordLength",
                    "MinWordLengthRequirement"
                );
            if (michaelMin < 0)
            {
                var encounter = BossResolver.TryGetEncounter();
                if (encounter != null)
                    michaelMin = TryGetIntMember(
                        encounter,
                        "MichaelMinWordLength",
                        "WordsmithMinWordLength",
                        "BossMinWordLength",
                        "MinWordLength",
                        "RequiredWordLength",
                        "WordLengthRequirement",
                        "CurrentMinWordLength",
                        "TargetWordLength"
                    );
            }
            if (michaelMin > 0)
                snapshot.extras["michael_min_word_length"] = michaelMin.ToString();

            var michaelBoss = bosses.Find(b =>
                b != null
                && (
                    b.GetType().Name == "MichaelBoss"
                    || (!string.IsNullOrEmpty(b.Name)
                        && b.Name.IndexOf("Michael", StringComparison.OrdinalIgnoreCase) >= 0)
                )
            );
            if (michaelBoss != null)
            {
                var draftedList = TryGetBossListMember(michaelBoss, "DraftedModifiers", isField: false);
                if (draftedList == null)
                    draftedList = TryGetBossListMember(michaelBoss, "DraftedModifiers", isField: true);
                if (draftedList == null)
                    draftedList = TryGetBossListMember(michaelBoss, "SummonedBosses", isField: false);
                if (draftedList == null)
                    draftedList = TryGetBossListMember(michaelBoss, "SummonedBosses", isField: true);
                var drafted = draftedList != null ? draftedList.Count : -1;
                if (drafted >= 1 && drafted <= 3)
                    snapshot.extras["michael_phase"] = drafted.ToString();

                var summonedDefeated = TryGetBoolMember(
                    michaelBoss,
                    "SummonedBossesDefeated",
                    "AreSummonedBossesDefeated",
                    "FinalPhaseComplete",
                    "FinaleComplete"
                );
                if (summonedDefeated)
                    snapshot.extras["michael_summoned_bosses_defeated"] = "true";
                else
                {
                    var encounter = BossResolver.TryGetEncounter();
                    if (
                        TryGetBoolMember(
                            encounter,
                            "SummonedBossesDefeated",
                            "AreSummonedBossesDefeated",
                            "MichaelSummonedBossesDefeated",
                            "MichaelFinaleComplete"
                        )
                    )
                    {
                        summonedDefeated = true;
                        snapshot.extras["michael_summoned_bosses_defeated"] = "true";
                    }
                }
                if (michaelMin <= 0 && !summonedDefeated && !_loggedMichaelMissingExtrasWarning)
                {
                    MelonLogger.Warning(
                        "Michael boss detected but final-phase/min-length extras were unavailable; "
                            + "run_state may miss Michael word-length enforcement."
                    );
                    _loggedMichaelMissingExtrasWarning = true;
                }
            }
        }

        private static List<BossModifier> TryGetBossListMember(
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
