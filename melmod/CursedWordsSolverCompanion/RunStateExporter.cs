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
                {
                    MelonLogger.Msg("Exported run state to " + OutputPath);
                    if (
                        HasBirthdayCakeSticker(player)
                        && !snapshot.extras.ContainsKey("birthday_cake_bonus")
                    )
                        MelonLogger.Warning(
                            "Birthday Cake is equipped but accumulated word bonus was not read — "
                                + "scores may show Birthday 0; rebuild melmod or set "
                                + "run_state.extras.birthday_cake_bonus manually"
                        );
                }
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
            AppendBossFingerprint(sb, BossResolver.Resolve(player));
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
                        result[kv.Key] = kv.Value ?? "";
                }
            }
            catch
            {
                // ignore
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
                var freshExtras = BuildExtrasSnapshot();
                if (freshExtras == null || freshExtras.Count == 0)
                    return;
                TryMergeExtrasKeys(freshExtras);
            }
            catch
            {
                // ignore — F7 full export still available
            }
        }

        /// <summary>
        /// Merge Bicycle WordScoreBonus after CalculateOverallScore so F8 sees the value
        /// used for the next word (SubmitWord Postfix may run before scoring finishes).
        /// </summary>
        public static void TryMergeBicycleExtrasAfterScore()
        {
            try
            {
                var player = GetPlayer();
                if (player == null || player.MyCharacter == null)
                    return;

                var pin = player.MyCharacter.CharacterItem;
                var bicycleExtras = BuildBicycleExtras(pin);
                if (bicycleExtras == null || bicycleExtras.Count == 0)
                    return;

                TryMergeExtrasKeys(bicycleExtras);
            }
            catch
            {
                // ignore — F7 full export still available
            }
        }

        private static void TryMergeExtrasKeys(Dictionary<string, string> keysToMerge)
        {
            if (keysToMerge == null || keysToMerge.Count == 0)
                return;
            if (!File.Exists(OutputPath))
                return;

            var json = File.ReadAllText(OutputPath, Encoding.UTF8);
            var root = JsonConvert.DeserializeObject<Dictionary<string, object>>(json);
            if (root == null)
                return;

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
            var updated = JsonConvert.SerializeObject(root, Formatting.Indented);
            File.WriteAllText(OutputPath, updated, new UTF8Encoding(false));
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

            var bosses = BossResolver.Resolve(player);
            if (bosses == null || bosses.Count == 0)
                ClearBossState(snapshot);
            else
            {
                FillBoss(snapshot, bosses);
                FillBossExtras(snapshot, player, bosses);
            }
            FillPinExtras(snapshot, player.MyCharacter);
            FillRunContextExtras(snapshot, player);
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

        private static void ClearBossState(RunStateSnapshot snapshot)
        {
            snapshot.boss_id = "";
            snapshot.boss_name = "";
            snapshot.boss_effect = "";
            if (snapshot.extras == null)
                return;
            snapshot.extras.Remove("boss_area_number");
            snapshot.extras.Remove("boss_cursed");
        }

        private static void FillBoss(
            RunStateSnapshot snapshot,
            List<BossModifier> bosses
        )
        {
            if (bosses == null || bosses.Count == 0)
            {
                ClearBossState(snapshot);
                return;
            }

            var boss = bosses[0];
            if (boss == null)
                return;

            var bossName = boss.Name;
            if (bossName == null)
                bossName = "";

            snapshot.boss_name = bossName;
            // Prefer runtime type (MaxWordLength → wolf) over prefab slug (bosssmallwords).
            var wikiId = BossResolver.WikiBossIdFromRuntimeType(boss);
            if (string.IsNullOrEmpty(wikiId))
                wikiId = Slugify(boss.PrefabFileName, bossName);
            snapshot.boss_id = wikiId;
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
                if (area >= 1 && area <= 5)
                    snapshot.extras["boss_area_number"] = area.ToString();
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

        private static void FillPinExtras(RunStateSnapshot snapshot, Character character)
        {
            if (character == null || character.CharacterItem == null)
            {
                snapshot.extras["pin_effect"] = "";
                return;
            }

            var pin = character.CharacterItem;
            snapshot.extras["pin_effect"] = Slugify(pin.ArtFileName, pin.Name);

            if (pin.UpgradeableComponents != null && pin.UpgradeableComponents.Count >= 2)
            {
                snapshot.extras["pin_left_level"] = GetUpgradeableLevel(
                    pin.UpgradeableComponents[0]
                ).ToString();
                snapshot.extras["pin_right_level"] = GetUpgradeableLevel(
                    pin.UpgradeableComponents[1]
                ).ToString();
            }

            FillPinMemory(snapshot, pin);
            FillBicycleExtras(snapshot, pin);
            FillFavourites(snapshot, character);
        }

        private static void FillPinMemory(RunStateSnapshot snapshot, Item pin)
        {
            var items = TryGetPinMemoryItems(pin);
            if (items == null || items.Count == 0)
            {
                snapshot.extras["pin_memory"] = "[]";
                return;
            }

            var mapped = new List<RunStateItem>();
            foreach (var item in items)
            {
                if (item == null)
                    continue;
                var name = item.Name ?? "";
                var isStamp = item.IsStamp();
                mapped.Add(
                    new RunStateItem
                    {
                        id = Slugify(item.ArtFileName, name),
                        name = name,
                        level = isStamp ? 1 : item.TimesUpgraded + 1,
                        kind = isStamp ? "stamp" : "sticker",
                    }
                );
            }

            snapshot.extras["pin_memory"] = JsonConvert.SerializeObject(mapped);
        }

        private static List<Item> TryGetPinMemoryItems(Item pin)
        {
            if (pin == null)
                return null;

            var names = new[]
            {
                "MemoryItems",
                "PinMemory",
                "StoredItems",
                "ItemsInMemory",
                "Memory",
            };

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

                    var value = prop.GetValue(pin, null);
                    var arr = value as Item[];
                    if (arr != null)
                        return new List<Item>(arr);
                    var list = value as System.Collections.Generic.List<Item>;
                    if (list != null)
                        return list;
                    var enumerable = value as System.Collections.IEnumerable;
                    if (enumerable != null)
                    {
                        var result = new List<Item>();
                        foreach (var entry in enumerable)
                        {
                            var it = entry as Item;
                            if (it != null)
                                result.Add(it);
                        }
                        if (result.Count > 0)
                            return result;
                    }
                }
                catch
                {
                    // try next property
                }
            }

            return null;
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

        private static int TryGetBicycleWordScoreBonus(Item pin)
        {
            if (pin == null)
                return -1;

            var bicycle = pin as Bicycle;
            if (bicycle != null)
                return bicycle.WordScoreBonus;

            return TryGetIntMember(pin, "WordScoreBonus");
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
            if (!string.IsNullOrEmpty(prevLetter))
                snapshot.extras["previous_word_first_letter"] = prevLetter.Substring(0, 1).ToLowerInvariant();

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
            if (redUsed >= 0)
                snapshot.extras["red_tiles_used_encounter"] = redUsed.ToString();

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

            var targetNumber = TryGetIntProperty(
                player,
                "TargetNumber",
                "LuckyDiceTarget",
                "GridTargetNumber",
                "CurrentTargetNumber"
            );
            if (targetNumber < 0)
                targetNumber = TryGetIntProperty(
                    GameStatics.GetPlayer(),
                    "TargetNumber",
                    "LuckyDiceTarget",
                    "GridTargetNumber"
                );
            if (targetNumber >= 0)
                snapshot.extras["target_number"] = targetNumber.ToString();

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

            var birthdayBonus = TryGetBirthdayCakeBonus(player);
            if (birthdayBonus >= 0)
                snapshot.extras["birthday_cake_bonus"] = birthdayBonus.ToString();

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

            var tileNinjaBonus = TryGetTileNinjaBonus(player);
            if (tileNinjaBonus >= 0)
                snapshot.extras["tile_ninja_bonus"] = tileNinjaBonus.ToString(
                    System.Globalization.CultureInfo.InvariantCulture
                );

            if (TryGetAvocadoMushy(player))
                snapshot.extras["avocado_mushy"] = "true";

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

        public static int TryGetBirthdayCakeBonus(Player player)
        {
            var fromPlayer = TryGetIntProperty(
                player,
                "BirthdayCakeBonus",
                "BirthdayCakeWordBonus",
                "BirthdayCakeAccumulatedBonus"
            );
            if (fromPlayer >= 0)
                return fromPlayer;

            return TryGetStickerAccumulatedWordBonus(
                player,
                name => name.IndexOf("Birthday", StringComparison.OrdinalIgnoreCase) >= 0,
                art => art.IndexOf("birthday", StringComparison.OrdinalIgnoreCase) >= 0
            );
        }

        /// <summary>
        /// Additive ×WORD bonus for Tile Ninja (wiki: +0.02 per consumable placed).
        /// Returns -1 if unknown.
        /// </summary>
        private static double TryGetTileNinjaBonus(Player player)
        {
            var direct = TryGetDoubleProperty(
                player,
                "TileNinjaBonus",
                "TileNinjaMultiplierBonus",
                "TileNinjaWordBonus"
            );
            if (direct >= 0)
                return direct;

            var placed = TryGetIntProperty(
                player,
                "ConsumablesPlaced",
                "ConsumableTilesPlaced",
                "TilesPlacedFromConsumables"
            );
            if (placed >= 0)
                return placed * 0.02;

            return TryGetStampMultiplierBonus(
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

        private static List<HistoricWord> TryGetHistoricPreviousWords(Player player)
        {
            if (player == null)
                return null;

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
                var name = sticker.Name ?? "";
                var art = sticker.ArtFileName ?? "";
                if (name.IndexOf("Birthday", StringComparison.OrdinalIgnoreCase) >= 0)
                    return true;
                if (art.IndexOf("birthday", StringComparison.OrdinalIgnoreCase) >= 0)
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

        private static void FillFavourites(RunStateSnapshot snapshot, Character character)
        {
            var favSticker = TryGetItemProperty(character, "FavouriteSticker", "FavoriteSticker");
            if (favSticker != null)
            {
                snapshot.extras["favourite_sticker_id"] = Slugify(
                    favSticker.ArtFileName,
                    favSticker.Name
                );
            }

            var favStamp = TryGetItemProperty(character, "FavouriteStamp", "FavoriteStamp");
            if (favStamp != null)
            {
                snapshot.extras["favourite_stamp_id"] = Slugify(
                    favStamp.ArtFileName,
                    favStamp.Name
                );
            }
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
                sb.Append(item.TimesUpgraded);
            }
        }

        public static void AppendBossFingerprint(StringBuilder sb, List<BossModifier> bosses)
        {
            if (bosses == null || bosses.Count == 0)
            {
                sb.Append("-");
                return;
            }

            var boss = bosses[0];
            if (boss == null)
            {
                sb.Append("-");
                return;
            }

            var wikiId = BossResolver.WikiBossIdFromRuntimeType(boss);
            if (string.IsNullOrEmpty(wikiId))
                wikiId = Slugify(boss.PrefabFileName, boss.Name);
            sb.Append(string.IsNullOrEmpty(wikiId) ? "-" : wikiId);
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
