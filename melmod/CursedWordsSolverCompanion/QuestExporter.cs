using System;
using System.Collections.Generic;
using System.Reflection;
using System.Text;

namespace CursedWordsSolverCompanion
{
    /// <summary>Export Player.CurrentRunProgress.Challenge (wiki Quests / game ChallengeRun).</summary>
    internal static class QuestExporter
    {
        private static readonly BindingFlags MemberFlags =
            BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;

        public static void FillChallenge(RunStateSnapshot snapshot, Player player)
        {
            if (snapshot == null || player == null)
                return;

            var challenge = TryGetChallengeFromPlayer(player);
            if (challenge == null)
                return;

            var gameClass = challenge.GetType().Name ?? "";
            if (string.IsNullOrEmpty(gameClass))
                return;

            snapshot.challenge_game_class = gameClass;
            snapshot.challenge_name = TryGetStringField(challenge, "ChallengeName") ?? "";
            snapshot.challenge_elite = TryGetBoolField(challenge, "EliteQuest");

            snapshot.extras["challenge_game_class"] = gameClass;
            if (!string.IsNullOrEmpty(snapshot.challenge_name))
                snapshot.extras["challenge_name"] = snapshot.challenge_name;
            if (snapshot.challenge_elite)
                snapshot.extras["challenge_elite"] = "true";

            if (gameClass == "PlayingFavourites")
                FillPlayingFavourites(snapshot, player);

            var wordsCount = TryGetWordsSubmittedThisRunCount(player);
            if (wordsCount >= 0)
                snapshot.extras["words_submitted_this_run_count"] = wordsCount.ToString();

        }

        public static bool IsTwoWrongs(Player player)
        {
            var challenge = TryGetChallengeFromPlayer(player);
            return challenge != null
                && string.Equals(
                    challenge.GetType().Name,
                    "TwoWrongs",
                    StringComparison.Ordinal
                );
        }

        public static bool IsTwoWrongsSnapshot(RunStateSnapshot snapshot)
        {
            if (snapshot == null)
                return false;
            if (
                string.Equals(
                    snapshot.challenge_game_class,
                    "TwoWrongs",
                    StringComparison.Ordinal
                )
            )
                return true;
            if (snapshot.extras == null)
                return false;
            string gc;
            return snapshot.extras.TryGetValue("challenge_game_class", out gc)
                && string.Equals(gc, "TwoWrongs", StringComparison.Ordinal);
        }

        public static void FillEmbargoExtras(RunStateSnapshot snapshot, Player player)
        {
            if (snapshot == null || player == null)
                return;
            FillEmbargoExtras(snapshot, TryGetRunProgress(player));
        }

        public static void FillEmbargoExtras(RunStateSnapshot snapshot, object progress)
        {
            if (snapshot?.extras == null)
                return;

            var types = TryGetEmbargoedItemTypes(progress);
            if (types == null || types.Count == 0)
            {
                snapshot.extras["embargoed_item_types"] = "";
                snapshot.extras["embargoed_item_slugs"] = "";
                return;
            }

            var typeNames = new List<string>();
            var slugs = new List<string>();
            foreach (var t in types)
            {
                if (t == null)
                    continue;
                var name = t.Name ?? "";
                if (string.IsNullOrEmpty(name))
                    continue;
                if (!typeNames.Contains(name))
                    typeNames.Add(name);
                var slug = RunStateExporter.Slugify(name, name);
                if (!string.IsNullOrEmpty(slug) && !slugs.Contains(slug))
                    slugs.Add(slug);
            }
            typeNames.Sort(StringComparer.Ordinal);
            slugs.Sort(StringComparer.Ordinal);
            snapshot.extras["embargoed_item_types"] = string.Join(",", typeNames);
            snapshot.extras["embargoed_item_slugs"] = string.Join(",", slugs);
        }

        private static List<Type> TryGetEmbargoedItemTypes(object progress)
        {
            if (progress == null)
                return null;
            try
            {
                var prop = progress.GetType().GetProperty("EmbargoedItemTypes", MemberFlags);
                if (prop != null)
                {
                    var list = prop.GetValue(progress, null) as System.Collections.IEnumerable;
                    return EnumerateTypes(list);
                }
                var field = progress.GetType().GetField("EmbargoedItemTypes", MemberFlags);
                if (field != null)
                {
                    var list = field.GetValue(progress) as System.Collections.IEnumerable;
                    return EnumerateTypes(list);
                }
            }
            catch
            {
                // optional
            }
            return null;
        }

        private static List<Type> EnumerateTypes(System.Collections.IEnumerable list)
        {
            var result = new List<Type>();
            if (list == null)
                return result;
            foreach (var entry in list)
            {
                if (entry is Type t && !result.Contains(t))
                    result.Add(t);
            }
            return result;
        }

        public static void FillUpAndUpCenterExtras(
            RunStateSnapshot snapshot,
            BoardSnapshot board
        )
        {
            if (snapshot == null || board == null || board.tiles == null)
                return;
            if (snapshot.challenge_game_class != "UpAndUp"
                && !string.Equals(
                    snapshot.extras.TryGetValue("challenge_game_class", out var gc) ? gc : "",
                    "UpAndUp",
                    StringComparison.Ordinal))
                return;

            foreach (var tile in board.tiles)
            {
                if (tile == null || !tile.is_up_and_up_center)
                    continue;
                snapshot.extras["up_and_up_center_row"] = tile.row.ToString();
                snapshot.extras["up_and_up_center_col"] = tile.col.ToString();
                snapshot.extras["up_and_up_center_index"] = (tile.row * 5 + tile.col).ToString();
                if (tile.number_value.HasValue)
                    snapshot.extras["up_and_up_center_number"] = tile.number_value.Value.ToString();
                break;
            }
        }

        private static void FillPlayingFavourites(RunStateSnapshot snapshot, Player player)
        {
            var stickerIds = new List<string>();
            var stampIds = new List<string>();
            if (player.Stickers != null)
            {
                foreach (var item in player.Stickers)
                {
                    if (item == null)
                        continue;
                    if (TryGetBoolField(item, "IsHumanBoyFavouriteSticker"))
                    {
                        stickerIds.Add(RunStateExporter.Slugify(item.ArtFileName, item.Name));
                    }
                }
            }
            try
            {
                var method = player.GetType().GetMethod(
                    "GetHBFavouriteStamp",
                    MemberFlags
                );
                if (method != null)
                {
                    var fav = method.Invoke(player, null) as Item;
                    if (fav != null)
                    {
                        var slug = RunStateExporter.Slugify(fav.ArtFileName, fav.Name);
                        if (!stampIds.Contains(slug))
                            stampIds.Add(slug);
                    }
                }
            }
            catch
            {
                // optional
            }
            if (stickerIds.Count > 0)
                snapshot.extras["favourite_sticker_ids"] = string.Join(",", stickerIds);
            if (stampIds.Count > 0)
                snapshot.extras["favourite_stamp_ids"] = string.Join(",", stampIds);
        }

        private static int TryGetWordsSubmittedThisRunCount(Player player)
        {
            try
            {
                var progress = TryGetRunProgress(player);
                if (progress == null)
                    return -1;
                var stats = progress.GetType().GetProperty("CurrentRunStatistics", MemberFlags);
                if (stats == null)
                    return -1;
                var statsObj = stats.GetValue(progress, null);
                if (statsObj == null)
                    return -1;
                var listProp = statsObj.GetType().GetProperty("WordsSubmittedThisRun", MemberFlags);
                if (listProp == null)
                    return -1;
                var list = listProp.GetValue(statsObj, null) as System.Collections.ICollection;
                return list?.Count ?? -1;
            }
            catch
            {
                return -1;
            }
        }

        private static object TryGetRunProgress(Player player)
        {
            try
            {
                return player.CurrentRunProgress;
            }
            catch
            {
                try
                {
                    var field = player.GetType().GetField("CurrentRunProgress", MemberFlags);
                    return field?.GetValue(player);
                }
                catch
                {
                    return null;
                }
            }
        }

        /// <summary>
        /// Same access path as RunStateExporter.AppendChallengeFingerprint (direct then reflection).
        /// </summary>
        private static object TryGetChallengeFromPlayer(Player player)
        {
            if (player == null)
                return null;
            try
            {
                var progress = player.CurrentRunProgress;
                if (progress == null)
                    return null;
                return progress.Challenge;
            }
            catch
            {
                var progress = TryGetRunProgress(player);
                return TryGetChallenge(progress);
            }
        }

        private static object TryGetChallenge(object progress)
        {
            if (progress == null)
                return null;
            try
            {
                var prop = progress.GetType().GetProperty("Challenge", MemberFlags);
                if (prop != null)
                {
                    var val = prop.GetValue(progress, null);
                    if (val != null)
                        return val;
                }
                var field = progress.GetType().GetField("Challenge", MemberFlags);
                if (field != null)
                    return field.GetValue(progress);
            }
            catch
            {
                // ignore
            }
            return null;
        }

        private static string TryGetStringField(object target, string name)
        {
            if (target == null)
                return "";
            try
            {
                var field = target.GetType().GetField(name, MemberFlags);
                if (field != null)
                    return field.GetValue(target)?.ToString() ?? "";
                var prop = target.GetType().GetProperty(name, MemberFlags);
                if (prop != null)
                    return prop.GetValue(target, null)?.ToString() ?? "";
            }
            catch
            {
                // ignore
            }
            return "";
        }

        private static bool TryGetBoolField(object target, string name)
        {
            if (target == null)
                return false;
            try
            {
                var field = target.GetType().GetField(name, MemberFlags);
                if (field != null)
                    return field.GetValue(target) is bool b && b;
                var prop = target.GetType().GetProperty(name, MemberFlags);
                if (prop != null)
                    return prop.GetValue(target, null) is bool b2 && b2;
            }
            catch
            {
                // ignore
            }
            return false;
        }
    }
}
