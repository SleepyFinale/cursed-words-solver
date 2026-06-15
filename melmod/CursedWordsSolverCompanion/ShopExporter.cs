using System;
using System.Collections.Generic;
using System.Reflection;
using Newtonsoft.Json;

namespace CursedWordsSolverCompanion
{
    public sealed class ShopOfferSnapshot
    {
        public string slot = "";
        public int index;
        public string id = "";
        public string name = "";
        public int level = 1;
        public bool foil;
        public int price;
        public int base_price;
        public bool frozen;
        public bool free;
        public bool sold;
        public bool hippo_eligible;
        [JsonProperty(NullValueHandling = NullValueHandling.Ignore)]
        public string color;
        [JsonProperty(NullValueHandling = NullValueHandling.Ignore)]
        public string curse;
        [JsonProperty(NullValueHandling = NullValueHandling.Ignore)]
        public string letter;
        [JsonProperty(NullValueHandling = NullValueHandling.Ignore)]
        public double? base_score;
    }

    public sealed class InventorySellSnapshot
    {
        public string kind = "";
        public int slot;
        public string id = "";
        public string name = "";
        public int level = 1;
        public bool foil;
        public int sell_value;
        public int sell_cost;
        public bool costs_money_to_sell;
    }

    public sealed class ShopStateSnapshot
    {
        public int restock_cost;
        public bool free_item_available;
        public bool angel_investment_available;
        public bool hungry_hippo_equipped;
        public List<ShopOfferSnapshot> offers = new List<ShopOfferSnapshot>();
    }

    public sealed class EncounterGridRerollSnapshot
    {
        public int remaining;
        public int cost_per_use;
        public bool can_reroll;
        public bool wheel_equipped;
        public bool fan_equipped;
        // Legacy fields (deprecated; kept for one release)
        public int cost;
        public bool available;
    }

    public static class ShopExporter
    {
        private const BindingFlags MemberFlags =
            BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;

        /// <summary>Last good remaining target when reflection reads fail mid-transition.</summary>
        private static int _lastKnownRemainingTarget = -1;

        /// <summary>Encounter total used to invalidate stale remaining cache.</summary>
        private static int _lastKnownEncounterTotal = -1;

        public static void FillShopState(RunStateSnapshot snapshot, Player player)
        {
            if (snapshot == null || player == null)
                return;

            snapshot.inventory_sell = ExportInventorySell(player);

            var shop = UnityEngine.Object.FindAnyObjectByType<ShopController>();
            if (shop != null)
            {
                snapshot.shop = ExportShop(shop, player);
                FillShopNodeExtra(snapshot, player);
            }

            var encounter = BossResolver.TryGetEncounter();
            if (encounter != null)
            {
                snapshot.encounter_grid_reroll = ExportEncounterGridReroll(encounter, player);
                FillEncounterTargetExtras(snapshot, encounter);
                ExportTwinkleToesExtras(encounter, player, snapshot.extras);
            }
        }

        private static ShopStateSnapshot ExportShop(ShopController shop, Player player)
        {
            var result = new ShopStateSnapshot
            {
                restock_cost = SafeGetRerollPrice(shop),
                free_item_available = ReadBoolField(shop, "_freeItemActive"),
                angel_investment_available = SafeAngelInvestment(shop),
                hungry_hippo_equipped = HasHungryHippo(player),
            };

            ExportStickerOffers(shop, player, result.offers);
            ExportStampOffers(shop, result.offers);
            ExportTileOffers(shop, result.offers);
            return result;
        }

        private static int SafeGetRerollPrice(ShopController shop)
        {
            var fromField = ReadIntField(shop, "_rerollPrice", defaultValue: -1);
            if (fromField >= 0)
                return fromField;

            return InvokeIntMethod(shop, "GetRerollPrice", defaultValue: 1);
        }

        private static bool SafeAngelInvestment(ShopController shop)
        {
            if (ReadBoolField(shop, "_hasUsedAngelInvestment"))
                return false;

            return InvokeBoolMethod(shop, "IsAngelInvestmentAvailable", defaultValue: false);
        }

        private static void ExportStickerOffers(
            ShopController shop,
            Player player,
            List<ShopOfferSnapshot> offers
        )
        {
            var stickers = ReadArrayField<ItemInStock>(shop, "_stickersInStock");
            if (stickers == null)
                return;

            var hippo = HasHungryHippo(player);
            for (var i = 0; i < stickers.Length; i++)
                AppendItemOffer(offers, stickers[i], "sticker", i, isStamp: false, hippoEligible: hippo);
        }

        private static void ExportStampOffers(ShopController shop, List<ShopOfferSnapshot> offers)
        {
            var stamps = ReadArrayField<ItemInStock>(shop, "_stampsInStock");
            if (stamps == null)
                return;

            for (var i = 0; i < stamps.Length; i++)
                AppendItemOffer(offers, stamps[i], "stamp", i, isStamp: true);
        }

        private static void AppendItemOffer(
            List<ShopOfferSnapshot> offers,
            ItemInStock stock,
            string slot,
            int index,
            bool isStamp,
            bool hippoEligible = false
        )
        {
            if (stock == null || stock.MyItem == null)
                return;

            var item = stock.MyItem;
            var name = item.Name ?? "";
            offers.Add(
                new ShopOfferSnapshot
                {
                    slot = slot,
                    index = index,
                    id = RunStateExporter.Slugify(item.ArtFileName, name),
                    name = name,
                    level = isStamp ? 1 : Math.Max(1, item.TimesUpgraded + 1),
                    foil = item.IsFoil,
                    price = stock.DisplayedCost >= 0 ? stock.DisplayedCost : stock.Cost,
                    base_price = stock.Cost,
                    frozen = stock.IsFrozen,
                    free = stock.IsFree,
                    sold = false,
                    hippo_eligible = hippoEligible && slot == "sticker" && !isStamp,
                }
            );
        }

        private static void ExportTileOffers(ShopController shop, List<ShopOfferSnapshot> offers)
        {
            var tiles = ReadArrayField<TileInStock>(shop, "_tilesInStock");
            if (tiles == null)
                return;

            for (var i = 0; i < tiles.Length; i++)
            {
                var stock = tiles[i];
                if (stock == null || stock.MyTile == null)
                    continue;

                var mapped = BoardExporter.ExportTileAt(stock.MyTile, -1, i);
                if (mapped == null)
                    continue;

                offers.Add(
                    new ShopOfferSnapshot
                    {
                        slot = "tile",
                        index = i,
                        id = "consumable_tile",
                        name = "Consumable tile",
                        level = 1,
                        price = stock.Price,
                        base_price = stock.Price,
                        sold = stock.HasBeenBought,
                        color = mapped.color,
                        curse = mapped.curse,
                        letter = mapped.letter,
                        base_score = mapped.base_score,
                    }
                );
            }
        }

        private static List<InventorySellSnapshot> ExportInventorySell(Player player)
        {
            var result = new List<InventorySellSnapshot>();
            if (player == null)
                return result;

            if (player.Stickers != null)
            {
                for (var i = 0; i < player.Stickers.Length; i++)
                    AppendSellCandidate(result, player.Stickers[i], "sticker", i, isStamp: false);
            }

            if (player.Stamps != null)
            {
                for (var i = 0; i < player.Stamps.Length; i++)
                    AppendSellCandidate(result, player.Stamps[i], "stamp", i, isStamp: true);
            }

            return result;
        }

        private static void AppendSellCandidate(
            List<InventorySellSnapshot> result,
            Item item,
            string kind,
            int slot,
            bool isStamp
        )
        {
            if (item == null)
                return;

            var name = item.Name ?? "";
            var sellValue = 0;
            try
            {
                sellValue = item.GetSellValue();
            }
            catch
            {
                sellValue = Math.Max(0, item.Cost);
            }

            result.Add(
                new InventorySellSnapshot
                {
                    kind = kind,
                    slot = slot,
                    id = RunStateExporter.Slugify(item.ArtFileName, name),
                    name = name,
                    level = isStamp ? 1 : Math.Max(1, item.TimesUpgraded + 1),
                    foil = item.IsFoil,
                    sell_value = sellValue,
                    sell_cost = item.SellCost,
                    costs_money_to_sell = item.CostsMoneyToSell,
                }
            );
        }

        private static EncounterGridRerollSnapshot ExportEncounterGridReroll(
            EncounterController encounter,
            Player player
        )
        {
            var remaining = ReadIntField(encounter, "_rerollsForEncounter", defaultValue: 0);
            var wheelEquipped = HasWheelStamp(player);
            var costPerUse = wheelEquipped ? 1 : 0;
            var canReroll = remaining > 0 && IsWaitingForWordSubmission(encounter);
            return new EncounterGridRerollSnapshot
            {
                remaining = remaining,
                cost_per_use = costPerUse,
                can_reroll = canReroll,
                wheel_equipped = wheelEquipped,
                fan_equipped = HasFanStamp(player),
                cost = costPerUse,
                available = canReroll,
            };
        }

        private static void ExportTwinkleToesExtras(
            EncounterController encounter,
            Player player,
            Dictionary<string, string> extras
        )
        {
            if (extras == null)
                return;

            if (!HasTwinkleToesStamp(player))
            {
                extras.Remove("twinkle_toes_swap_available");
                return;
            }

            var swapAvailable = ReadBoolField(encounter, "TwinkleToesSwapAvailable");
            try
            {
                if (
                    encounter.GetEncounterThreadStage() == EncounterThreadStage.SwappingTiles
                )
                    swapAvailable = false;
            }
            catch
            {
                // ignore
            }

            extras["twinkle_toes_swap_available"] = swapAvailable ? "true" : "false";
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

        private static void FillEncounterTargetExtras(
            RunStateSnapshot snapshot,
            EncounterController encounter
        )
        {
            if (snapshot == null || encounter == null)
                return;

            var remaining = ReadScorePacketField(encounter, "_remainingTarget");
            var total = ReadScorePacketField(encounter, "_totalTarget");

            if (total >= 0)
            {
                if (_lastKnownEncounterTotal >= 0 && total != _lastKnownEncounterTotal)
                    _lastKnownRemainingTarget = -1;
                _lastKnownEncounterTotal = (int)total;
                snapshot.extras["encounter_total_target"] = total.ToString();
            }

            if (remaining >= 0)
            {
                _lastKnownRemainingTarget = (int)remaining;
                snapshot.extras["encounter_remaining_target"] = remaining.ToString();
            }
            else if (_lastKnownRemainingTarget >= 0)
            {
                remaining = _lastKnownRemainingTarget;
                snapshot.extras["encounter_remaining_target"] = remaining.ToString();
            }

            if (total >= 0 && remaining >= 0)
            {
                var earned = total - remaining;
                if (earned >= 0)
                    snapshot.extras["encounter_score_earned"] = earned.ToString();
            }
        }

        private static long ReadScorePacketField(object target, string fieldName)
        {
            if (target == null)
                return -1;

            try
            {
                var field = target.GetType().GetField(fieldName, MemberFlags);
                if (field == null)
                    return -1;
                var packet = field.GetValue(target);
                if (packet == null)
                    return -1;
                var scoreField = packet.GetType().GetField("Score", MemberFlags);
                if (scoreField == null)
                    return -1;
                var raw = scoreField.GetValue(packet);
                if (raw is long l)
                    return l;
                if (raw is int i)
                    return i;
            }
            catch
            {
                // ignore
            }

            return -1;
        }

        private static bool HasFanStamp(Player player)
        {
            if (player?.Stamps == null)
                return false;

            foreach (var stamp in player.Stamps)
            {
                if (stamp == null)
                    continue;
                if (string.Equals(stamp.GetType().Name, "Fan", StringComparison.Ordinal))
                    return true;
                var slug = RunStateExporter.Slugify(stamp.ArtFileName, stamp.Name);
                if (string.Equals(slug, "fan", StringComparison.OrdinalIgnoreCase))
                    return true;
            }

            return false;
        }

        private static bool HasWheelStamp(Player player)
        {
            if (player?.Stamps == null)
                return false;

            foreach (var stamp in player.Stamps)
            {
                if (stamp == null)
                    continue;
                var slug = RunStateExporter.Slugify(stamp.ArtFileName, stamp.Name);
                if (string.Equals(slug, "wheel", StringComparison.OrdinalIgnoreCase))
                    return true;
            }

            return false;
        }

        private static bool HasTwinkleToesStamp(Player player)
        {
            if (player?.Stamps == null)
                return false;

            foreach (var stamp in player.Stamps)
            {
                if (stamp == null)
                    continue;
                var slug = RunStateExporter.Slugify(stamp.ArtFileName, stamp.Name);
                if (string.Equals(slug, "twinkle_toes", StringComparison.OrdinalIgnoreCase))
                    return true;
            }

            return false;
        }

        private static bool HasHungryHippo(Player player)
        {
            if (player?.Stickers == null)
                return false;

            foreach (var sticker in player.Stickers)
            {
                if (sticker == null)
                    continue;
                if (string.Equals(sticker.GetType().Name, "HungryHippo", StringComparison.Ordinal))
                    return true;
                var slug = RunStateExporter.Slugify(sticker.ArtFileName, sticker.Name);
                if (string.Equals(slug, "hungry_hippo", StringComparison.OrdinalIgnoreCase))
                    return true;
            }

            return false;
        }

        private static T[] ReadArrayField<T>(object target, string fieldName)
        {
            if (target == null)
                return null;

            try
            {
                var field = target.GetType().GetField(fieldName, MemberFlags);
                if (field == null)
                    return null;
                return field.GetValue(target) as T[];
            }
            catch
            {
                return null;
            }
        }

        private static int ReadIntField(object target, string fieldName, int defaultValue = -1)
        {
            if (target == null)
                return defaultValue;

            try
            {
                var field = target.GetType().GetField(fieldName, MemberFlags);
                if (field == null)
                    return defaultValue;
                var raw = field.GetValue(target);
                if (raw is int i)
                    return i;
            }
            catch
            {
                // ignore
            }

            return defaultValue;
        }

        private static bool ReadBoolField(object target, string fieldName)
        {
            if (target == null)
                return false;

            try
            {
                var field = target.GetType().GetField(fieldName, MemberFlags);
                if (field == null)
                    return false;
                var raw = field.GetValue(target);
                if (raw is bool b)
                    return b;
            }
            catch
            {
                // ignore
            }

            return false;
        }

        private static int InvokeIntMethod(object target, string methodName, int defaultValue)
        {
            if (target == null)
                return defaultValue;

            try
            {
                var method = target.GetType().GetMethod(methodName, MemberFlags);
                if (method == null || method.GetParameters().Length != 0)
                    return defaultValue;
                var raw = method.Invoke(target, null);
                if (raw is int i)
                    return i;
            }
            catch
            {
                // ignore
            }

            return defaultValue;
        }

        private static bool InvokeBoolMethod(object target, string methodName, bool defaultValue)
        {
            if (target == null)
                return defaultValue;

            try
            {
                var method = target.GetType().GetMethod(methodName, MemberFlags);
                if (method == null || method.GetParameters().Length != 0)
                    return defaultValue;
                var raw = method.Invoke(target, null);
                if (raw is bool b)
                    return b;
            }
            catch
            {
                // ignore
            }

            return defaultValue;
        }

        private static void FillShopNodeExtra(RunStateSnapshot snapshot, Player player)
        {
            if (snapshot == null || player == null)
                return;

            var node = TryGetShopNodeName(player);
            if (string.IsNullOrEmpty(node))
                return;

            if (snapshot.extras == null)
                snapshot.extras = new Dictionary<string, string>();
            snapshot.extras["shop_node"] = node;
        }

        private static string TryGetShopNodeName(Player player)
        {
            var progress = player?.CurrentRunProgress;
            if (progress == null)
                return "";

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
                    return "";

                var name = value.ToString();
                if (name == "ShopZero"
                    || name == "ShopOne"
                    || name == "ShopTwo"
                    || name == "MegShop")
                    return name;
            }
            catch
            {
                // optional
            }

            return "";
        }
    }
}
