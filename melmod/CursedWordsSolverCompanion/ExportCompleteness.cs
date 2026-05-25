using System.Collections.Generic;
using System.Text;
using MelonLoader;

namespace CursedWordsSolverCompanion
{
    /// <summary>
    /// Validates that run_state export includes keys the Python solver expects for the current loadout.
    /// </summary>
    internal static class ExportCompleteness
    {
        public static void LogWarningsIfNeeded(
            RunStateSnapshot snapshot,
            Player player,
            bool logSuccess
        )
        {
            if (!logSuccess || snapshot == null)
                return;

            var missing = CollectMissing(snapshot, player);
            if (missing.Count == 0)
                return;

            var sb = new StringBuilder();
            sb.Append("Export completeness: missing or empty — ");
            for (var i = 0; i < missing.Count; i++)
            {
                if (i > 0)
                    sb.Append(", ");
                sb.Append(missing[i]);
            }
            MelonLogger.Warning(sb.ToString());
        }

        public static List<string> CollectMissing(RunStateSnapshot snapshot, Player player)
        {
            var missing = new List<string>();
            if (snapshot == null)
                return missing;

            var extras = snapshot.extras ?? new Dictionary<string, string>();

            if (player?.MyCharacter?.CharacterItem != null)
            {
                if (!extras.ContainsKey("pin_effect") || string.IsNullOrEmpty(extras["pin_effect"]))
                    missing.Add("pin_effect");
            }

            if (snapshot.board == null)
            {
                if (RunStateExportFill.DetectEncounterMode(player) == "encounter")
                    missing.Add("board");
            }
            else
            {
                if (!extras.ContainsKey("board_from_melmod"))
                    missing.Add("board_from_melmod");
            }

            if (!extras.ContainsKey("grid_number"))
                missing.Add("grid_number");

            if (HasFrankenstein(player))
            {
                if (
                    !extras.TryGetValue("stitched_sticker_ids", out var stitched)
                    || string.IsNullOrWhiteSpace(stitched)
                    || stitched == "[]"
                )
                    missing.Add("stitched_sticker_ids");
            }

            if (HasStamp(player, "kokeshi") && !extras.ContainsKey("kokeshi_dolls"))
                missing.Add("kokeshi_dolls");

            if (!string.IsNullOrEmpty(snapshot.boss_id))
            {
                if (!extras.ContainsKey("boss_area_number"))
                    missing.Add("boss_area_number");
            }

            return missing;
        }

        private static bool HasFrankenstein(Player player)
        {
            if (player?.Stickers == null)
                return false;
            foreach (var s in player.Stickers)
            {
                if (s != null && s.GetType().Name == "Frankenstein")
                    return true;
            }
            return false;
        }

        private static bool HasStamp(Player player, string slugPart)
        {
            if (player?.Stamps == null)
                return false;
            foreach (var stamp in player.Stamps)
            {
                if (stamp == null)
                    continue;
                var slug = RunStateExporter.Slugify(stamp.ArtFileName, stamp.Name);
                if (slug.IndexOf(slugPart, System.StringComparison.OrdinalIgnoreCase) >= 0)
                    return true;
            }
            return false;
        }
    }
}
