using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Text;
using MelonLoader;
using Newtonsoft.Json;

namespace CursedWordsSolverCompanion
{
    public static class RunStateExporter
    {
        private static readonly string OutputPath = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
            ".cursed_words_solver",
            "run_state.json"
        );

        public static string OutputFilePath
        {
            get { return OutputPath; }
        }

        public static bool TryExport(bool logSuccess)
        {
            try
            {
                var player = GetPlayer();
                if (player == null)
                    return false;

                var snapshot = BuildSnapshot(player);
                WriteSnapshot(snapshot);
                DictionaryExporter.TryExport(logSuccess);
                if (logSuccess)
                    MelonLogger.Msg("Exported run state to " + OutputPath);
                return true;
            }
            catch (Exception ex)
            {
                MelonLogger.Error("Failed to export run state: " + ex);
                return false;
            }
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
            AppendBossFingerprint(sb, player.ActiveBossModifiers);
            sb.Append('|');
            AppendPinFingerprint(sb, player.MyCharacter);
            sb.Append('|');
            sb.Append(ComputeBoardFingerprint(player));
            return sb.ToString();
        }

        public static string ComputeBoardFingerprint(Player player)
        {
            var board = BoardExporter.TryBuild(player);
            return BoardExporter.ComputeBoardFingerprint(board);
        }

        public static Player GetPlayerForUpdate()
        {
            return GetPlayer();
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

        private static RunStateSnapshot BuildSnapshot(Player player)
        {
            var snapshot = new RunStateSnapshot
            {
                character = GetCharacterName(player.MyCharacter),
                money = player.Money,
                pin_branch = GetPinBranch(player.MyCharacter),
                stickers = MapItems(player.Stickers, false),
                stamps = MapItems(player.Stamps, true),
            };

            FillBoss(snapshot, player.ActiveBossModifiers);
            FillPinExtras(snapshot, player.MyCharacter);
            snapshot.board = BoardExporter.TryBuild(player);
            return snapshot;
        }

        private static void WriteSnapshot(RunStateSnapshot snapshot)
        {
            var dir = Path.GetDirectoryName(OutputPath);
            if (!string.IsNullOrEmpty(dir))
                Directory.CreateDirectory(dir);

            var json = JsonConvert.SerializeObject(snapshot, Formatting.Indented);
            File.WriteAllText(OutputPath, json, new UTF8Encoding(false));
        }

        private static List<RunStateItem> MapItems(Item[] items, bool stampsOnly)
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

                result.Add(
                    new RunStateItem
                    {
                        id = Slugify(item.ArtFileName, name),
                        name = name,
                        level = stampsOnly ? 1 : item.TimesUpgraded + 1,
                    }
                );
            }

            return result;
        }

        private static void FillBoss(
            RunStateSnapshot snapshot,
            List<BossModifier> bosses
        )
        {
            if (bosses == null || bosses.Count == 0)
                return;

            var boss = bosses[0];
            if (boss == null)
                return;

            var bossName = boss.Name;
            if (bossName == null)
                bossName = "";

            snapshot.boss_name = bossName;
            snapshot.boss_id = Slugify(boss.PrefabFileName, bossName);
            snapshot.boss_effect = "";
        }

        private static void FillPinExtras(RunStateSnapshot snapshot, Character character)
        {
            if (character == null || character.CharacterItem == null)
            {
                snapshot.extras["pin_effect"] = "";
                return;
            }

            var pin = character.CharacterItem;
            snapshot.extras["pin_effect"] = Slugify(pin.ArtFileName, pin.Name);
        }

        private static string GetPinBranch(Character character)
        {
            if (character == null || character.CharacterItem == null)
                return "";

            var pin = character.CharacterItem;
            if (pin.UpgradeableComponents == null)
                return "";

            var components = pin.UpgradeableComponents;
            if (components.Count < 2)
                return "";

            var leftLevel = GetUpgradeableLevel(components[0]);
            var rightLevel = GetUpgradeableLevel(components[1]);

            if (leftLevel == rightLevel)
                return "";
            return leftLevel > rightLevel ? "left" : "right";
        }

        private static int GetUpgradeableLevel(object component)
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

        private static string GetCharacterName(Character character)
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

        private static void AppendItemsFingerprint(StringBuilder sb, Item[] items)
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
                sb.Append(item.TimesUpgraded);
            }
        }

        private static void AppendBossFingerprint(StringBuilder sb, List<BossModifier> bosses)
        {
            if (bosses == null || bosses.Count == 0)
                return;

            var boss = bosses[0];
            if (boss == null)
                return;

            sb.Append(Slugify(boss.PrefabFileName, boss.Name));
        }

        private static void AppendPinFingerprint(StringBuilder sb, Character character)
        {
            if (character == null || character.CharacterItem == null)
                return;

            var pin = character.CharacterItem;
            sb.Append(Slugify(pin.ArtFileName, pin.Name));
            sb.Append(':');
            sb.Append(GetPinBranch(character));
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
