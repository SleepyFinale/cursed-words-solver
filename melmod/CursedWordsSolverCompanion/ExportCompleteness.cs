using System;
using System.Collections.Generic;
using System.Text;
using MelonLoader;
using Newtonsoft.Json;

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

            var encounterMode = extras.TryGetValue("encounter_mode", out var modeRaw)
                ? modeRaw
                : RunStateExportFill.DetectEncounterMode(player);
            if (encounterMode == "cursedle")
            {
                CollectCursedleWarnings(extras, missing);
            }
            else if (encounterMode == "encounter")
            {
                if (!extras.ContainsKey("run_stage"))
                    missing.Add("run_stage");
                if (!extras.ContainsKey("run_node_type"))
                    missing.Add("run_node_type");
                if (
                    extras.ContainsKey("encounter_total_target")
                    && !extras.ContainsKey("encounter_score_earned")
                )
                    missing.Add("encounter_score_earned");
            }

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

            if (HasLuckyDice(player))
            {
                if (!extras.ContainsKey("target_number"))
                    missing.Add("target_number");
            }

            CollectSnapshotWarnings(snapshot, player, extras, missing);
            CollectGridScatteredWarnings(snapshot, missing);
            CollectCounterStickerWarnings(player, extras, missing);

            CollectRamMemoryWarnings(snapshot, player, missing);

            return missing;
        }

        private static void CollectCursedleWarnings(
            Dictionary<string, string> extras,
            List<string> missing
        )
        {
            if (!extras.ContainsKey("cursedle_guesses_remaining"))
                missing.Add("cursedle_guesses_remaining");
            if (!extras.ContainsKey("cursedle_guesses_used"))
                missing.Add("cursedle_guesses_used");
            if (!extras.ContainsKey("cursedle_guesses"))
                missing.Add("cursedle_guesses");

            var used = 0;
            if (extras.TryGetValue("cursedle_guesses_used", out var usedRaw))
                int.TryParse(usedRaw, out used);
            if (used <= 0)
                return;

            var historyCount = CountCursedleGuessesInExport(extras);
            if (historyCount < used && !missing.Contains("cursedle_guesses"))
                missing.Add("cursedle_guesses");
        }

        private static int CountCursedleGuessesInExport(Dictionary<string, string> extras)
        {
            if (
                !extras.TryGetValue("cursedle_guesses", out var guessesRaw)
                || string.IsNullOrWhiteSpace(guessesRaw)
                || guessesRaw == "[]"
            )
                return 0;
            try
            {
                var rows = JsonConvert.DeserializeObject<System.Collections.Generic.List<object>>(
                    guessesRaw
                );
                return rows != null ? rows.Count : 0;
            }
            catch
            {
                return 0;
            }
        }

        private static void CollectSnapshotWarnings(
            RunStateSnapshot snapshot,
            Player player,
            Dictionary<string, string> extras,
            List<string> missing
        )
        {
            if (!HasSticker(player, "snapshot"))
                return;

            string note;
            extras.TryGetValue("snapshot_copy_export_note", out note);
            if (string.Equals(note, "no_copy_yet", StringComparison.OrdinalIgnoreCase))
                return;

            if (
                !extras.ContainsKey("snapshot_copy_slug")
                || string.IsNullOrWhiteSpace(extras["snapshot_copy_slug"])
            )
                missing.Add("snapshot_copy_slug");
        }

        private static void CollectGridScatteredWarnings(
            RunStateSnapshot snapshot,
            List<string> missing
        )
        {
            if (snapshot?.board?.tiles == null)
                return;

            var hasScattered = false;
            foreach (var tile in snapshot.board.tiles)
            {
                if (tile == null || !tile.active)
                    continue;
                if (
                    string.Equals(tile.curse, "item", StringComparison.OrdinalIgnoreCase)
                    && !string.IsNullOrEmpty(tile.scattered_item_id)
                )
                {
                    hasScattered = true;
                    if (!tile.scattered_item_level.HasValue)
                        missing.Add("scattered_item_level@" + tile.row + "," + tile.col);
                }
            }

            if (hasScattered && !snapshot.extras.ContainsKey("grid_scattered_items"))
                missing.Add("grid_scattered_items");
        }

        private static void CollectCounterStickerWarnings(
            Player player,
            Dictionary<string, string> extras,
            List<string> missing
        )
        {
            if (HasStamp(player, "hourglass") && !extras.ContainsKey("hourglass_count"))
                missing.Add("hourglass_count");

            if (HasStamp(player, "neapolitan") && !extras.ContainsKey("neapolitan_percent"))
                missing.Add("neapolitan_percent");

            if (HasStamp(player, "ruler"))
            {
                var hasLive = extras.ContainsKey("ruler_distance")
                    && !string.IsNullOrEmpty(extras["ruler_distance"]);
                var hasCached = extras.ContainsKey("ruler_distance_last_known")
                    && !string.IsNullOrEmpty(extras["ruler_distance_last_known"]);
                if (!hasLive && !hasCached)
                    missing.Add("ruler_distance");
            }

            if (HasStamp(player, "steak") && !extras.ContainsKey("steak_word_bonus_percent"))
                missing.Add("steak_word_bonus_percent");

            if (HasStamp(player, "tile_ninja"))
            {
                var hasLive = extras.ContainsKey("tile_ninja_bonus")
                    && !string.IsNullOrEmpty(extras["tile_ninja_bonus"]);
                var hasCached = extras.ContainsKey("tile_ninja_bonus_last_known")
                    && !string.IsNullOrEmpty(extras["tile_ninja_bonus_last_known"]);
                var hasGridStart = extras.ContainsKey("tile_ninja_bonus_at_grid_start")
                    && !string.IsNullOrEmpty(extras["tile_ninja_bonus_at_grid_start"]);
                if (!hasLive && !hasCached && !hasGridStart)
                    missing.Add("tile_ninja_bonus");
            }
        }

        private static bool HasSticker(Player player, string slugPart)
        {
            if (player?.Stickers == null)
                return false;
            foreach (var sticker in player.Stickers)
            {
                if (sticker == null)
                    continue;
                var slug = RunStateExporter.Slugify(sticker.ArtFileName, sticker.Name);
                if (slug.IndexOf(slugPart, StringComparison.OrdinalIgnoreCase) >= 0)
                    return true;
            }
            return false;
        }

        private static readonly HashSet<string> RamNonGeneratableSlugs = new HashSet<string>(
            StringComparer.OrdinalIgnoreCase
        )
        {
            "beam_me_up",
            "crystal_ball",
            "dartboard",
            "magic_8_ball",
            "hungry_hippo",
            "lucky_dice",
            "mystery_gift",
            "nest_egg",
            "overhand",
            "sewing_needle",
            "signal_receiver",
            "snapshot",
            "underhand",
            "unicorn",
        };

        private static void CollectRamMemoryWarnings(
            RunStateSnapshot snapshot,
            Player player,
            List<string> missing
        )
        {
            var pin = player?.MyCharacter?.CharacterItem;
            if (pin == null || !IsRandomAccessMemoryPin(pin))
                return;

            var extras = snapshot.extras ?? new Dictionary<string, string>();
            if (
                extras.TryGetValue("pin_memory_export_note", out var note)
                && note == "field_missing"
            )
                missing.Add("pin_memory (ItemsInMemory unreadable)");

            if (!extras.TryGetValue("pin_memory", out var raw) || string.IsNullOrWhiteSpace(raw))
                return;

            try
            {
                var rows = JsonConvert.DeserializeObject<List<RunStateItem>>(raw);
                if (rows == null)
                    return;
                foreach (var row in rows)
                {
                    if (row == null || string.IsNullOrEmpty(row.id))
                        continue;
                    if (RamNonGeneratableSlugs.Contains(row.id))
                        missing.Add("pin_memory unexpected item:" + row.id);
                }
            }
            catch
            {
                missing.Add("pin_memory (invalid JSON)");
            }
        }

        private static bool IsRandomAccessMemoryPin(Item pin)
        {
            var t = pin.GetType();
            return string.Equals(t.Name, "RandomAccessMemory", StringComparison.Ordinal);
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

        private static bool HasLuckyDice(Player player)
        {
            if (player?.Stickers == null)
                return false;
            foreach (var sticker in player.Stickers)
            {
                if (sticker == null)
                    continue;
                if (string.Equals(sticker.GetType().Name, "LuckyDice", System.StringComparison.Ordinal))
                    return true;
                var name = sticker.Name ?? "";
                if (
                    name.IndexOf("Lucky", System.StringComparison.OrdinalIgnoreCase) >= 0
                    && name.IndexOf("Dice", System.StringComparison.OrdinalIgnoreCase) >= 0
                )
                    return true;
            }
            return false;
        }
    }
}
