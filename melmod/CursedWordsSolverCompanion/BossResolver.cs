using System;
using System.Collections;
using System.Collections.Generic;
using System.Reflection;
using UnityEngine;

namespace CursedWordsSolverCompanion
{
    /// <summary>
    /// Resolves active boss modifiers when Player.ActiveBossModifiers is empty
    /// (common during encounter grids). Uses scoring cache, encounter API, and fields.
    /// </summary>
    public static class BossResolver
    {
        private static List<BossModifier> _cachedFromScoring;
        private static int _cachedFromScoringGridNumber = -1;

        public static void CacheFromScoring(List<BossModifier> bossModifiers)
        {
            if (bossModifiers == null || bossModifiers.Count == 0)
            {
                ClearScoringCache();
                return;
            }

            if (_cachedFromScoring == null)
                _cachedFromScoring = new List<BossModifier>();

            _cachedFromScoring.Clear();
            foreach (var b in bossModifiers)
            {
                if (b != null)
                    _cachedFromScoring.Add(b);
            }

            var grid = RunStateExportFill.CachedGridNumber;
            _cachedFromScoringGridNumber = grid >= 1 ? grid : _cachedFromScoringGridNumber;
        }

        public static void ClearScoringCache()
        {
            if (_cachedFromScoring != null)
                _cachedFromScoring.Clear();
            _cachedFromScoringGridNumber = -1;
        }

        /// <summary>
        /// Live encounter/player state only — never returns a stale scoring cache
        /// after the boss fight ends.
        /// </summary>
        public static List<BossModifier> Resolve(Player player)
        {
            var encounter = TryGetEncounter();
            if (encounter != null)
            {
                var fromEncounter = ResolveFromEncounter(encounter);
                if (fromEncounter != null && fromEncounter.Count > 0)
                    return fromEncounter;

                if (fromEncounter != null && fromEncounter.Count == 0)
                {
                    ClearScoringCache();
                    return null;
                }

                // Encounter API unreadable; scoring cache only mid-fight on same grid.
                if (CanUseScoringCacheFallback(encounter, player))
                    return _cachedFromScoring;

                ClearScoringCache();
                return null;
            }

            ClearScoringCache();

            if (player != null && player.ActiveBossModifiers != null
                && player.ActiveBossModifiers.Count > 0)
                return player.ActiveBossModifiers;

            return null;
        }

        public static List<BossModifier> ResolveFromEncounter(EncounterController encounter)
        {
            if (encounter == null)
                return null;

            try
            {
                var list = encounter.GetBossModifiers();
                if (list != null)
                {
                    if (list.Count == 0)
                        return new List<BossModifier>();
                    return list;
                }
            }
            catch
            {
                // fall through to reflection
            }

            var drafted = TryGetBossField(encounter, "_draftedBossModifier");
            if (drafted != null)
                return new List<BossModifier> { drafted };

            return TryGetBossListFromObject(encounter);
        }

        public static EncounterController TryGetEncounter()
        {
            try
            {
                return UnityEngine.Object.FindAnyObjectByType<EncounterController>();
            }
            catch
            {
                return null;
            }
        }

        private static bool CanUseScoringCacheFallback(
            EncounterController encounter,
            Player player
        )
        {
            if (_cachedFromScoring == null || _cachedFromScoring.Count == 0)
                return false;
            if (!IsWaitingForWordSubmission(encounter))
                return false;
            if (_cachedFromScoringGridNumber < 1)
                return false;
            var currentGrid = RunStateExportFill.ResolveGridNumber(player);
            return currentGrid >= 1 && currentGrid == _cachedFromScoringGridNumber;
        }

        private static bool IsWaitingForWordSubmission(EncounterController encounter)
        {
            if (encounter == null)
                return false;
            try
            {
                return encounter.GetEncounterThreadStage()
                    == EncounterThreadStage.WaitingForWordSubmission;
            }
            catch
            {
                return false;
            }
        }

        /// <summary>Wiki boss_id slug from game BossModifier subclass name.</summary>
        public static string WikiBossIdFromRuntimeType(BossModifier boss)
        {
            if (boss == null)
                return "";

            switch (boss.GetType().Name)
            {
                case "MaxWordLength":
                    return "wolf";
                case "MinWordLength":
                    return "cobra";
                case "ReducedLetterValue":
                    return "salamander";
                case "NegativeMoney":
                    return "robo_monkey";
                case "StealsMoney":
                    return "fox";
                case "ExtraVoids":
                    return "mole";
                case "ExtraQs":
                    return "axolotl";
                case "AddNumbers":
                    return "bison";
                case "DiscolourTiles":
                    return "yeti_crab";
                case "DestroyGrid":
                    return "robo_eel";
                case "SmallGrid":
                    return "bat";
                case "FewerGrids":
                    return "badger";
                case "ForcedSell":
                    return "hyena";
                case "RandomiseItemOrder":
                    return "capybara";
                case "BigBoss":
                    return "toothed_whale";
                case "CretaceousMegBoss":
                    return "cretaceous_meg";
                case "SandySaguaroBoss":
                    return "sandy_saguaro";
                case "HumanBoyBoss":
                    return "human_boy_boss";
                default:
                    return "";
            }
        }

        public static int TryGetRunStage(Player player)
        {
            if (player == null || player.CurrentRunProgress == null)
                return -1;

            try
            {
                return player.CurrentRunProgress.GetStage();
            }
            catch
            {
                return -1;
            }
        }

        private static List<BossModifier> TryGetBossListFromObject(object target)
        {
            if (target == null)
                return null;

            foreach (var name in new[]
            {
                "ActiveBossModifiers",
                "BossModifiers",
                "CurrentBossModifiers",
                "Bosses",
                "ActiveBosses",
            })
            {
                var list = TryGetBossListMember(target, name, isField: false);
                if (list != null && list.Count > 0)
                    return list;
            }

            foreach (var name in new[] { "_bossModifiers", "_currentDraftBossModifiers" })
            {
                var list = TryGetBossListMember(target, name, isField: true);
                if (list != null && list.Count > 0)
                    return list;
            }

            foreach (var name in new[] { "CurrentBoss", "Boss", "ActiveBoss", "_draftedBossModifier" })
            {
                var single = TryGetBossMember(target, name, isField: name.StartsWith("_"));
                if (single != null)
                    return new List<BossModifier> { single };
            }

            return null;
        }

        private static BossModifier TryGetBossField(object target, string name)
        {
            return TryGetBossMember(target, name, isField: true);
        }

        private static BossModifier TryGetBossMember(object target, string name, bool isField)
        {
            try
            {
                var flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;
                if (isField)
                {
                    var field = target.GetType().GetField(name, flags);
                    if (field == null)
                        return null;
                    return field.GetValue(target) as BossModifier;
                }

                var prop = target.GetType().GetProperty(name, flags);
                if (prop == null)
                    return null;
                return prop.GetValue(target, null) as BossModifier;
            }
            catch
            {
                return null;
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
                var flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;
                object value;
                if (isField)
                {
                    var field = target.GetType().GetField(name, flags);
                    if (field == null)
                        return null;
                    value = field.GetValue(target);
                }
                else
                {
                    var prop = target.GetType().GetProperty(name, flags);
                    if (prop == null)
                        return null;
                    value = prop.GetValue(target, null);
                }

                if (value == null)
                    return null;

                var asList = value as IList<BossModifier>;
                if (asList != null)
                {
                    var result = new List<BossModifier>();
                    foreach (var b in asList)
                    {
                        if (b != null)
                            result.Add(b);
                    }
                    return result.Count > 0 ? result : null;
                }

                var enumerable = value as IEnumerable;
                if (enumerable == null)
                    return null;

                var fromEnum = new List<BossModifier>();
                foreach (var item in enumerable)
                {
                    var boss = item as BossModifier;
                    if (boss != null)
                        fromEnum.Add(boss);
                }
                return fromEnum.Count > 0 ? fromEnum : null;
            }
            catch
            {
                return null;
            }
        }
    }
}
