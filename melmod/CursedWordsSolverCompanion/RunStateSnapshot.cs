using System.Collections.Generic;
using Newtonsoft.Json;

namespace CursedWordsSolverCompanion
{
    public sealed class RunStateSnapshot
    {
        public int schema_version = 1;
        public string exported_at = "";
        public string character = "";
        public string pin_branch = "";
        public int money;
        public List<RunStateItem> stickers = new List<RunStateItem>();
        public List<RunStateItem> stamps = new List<RunStateItem>();
        public string boss_id = "";
        public string boss_name = "";
        public string boss_effect = "";
        public Dictionary<string, string> extras = new Dictionary<string, string>();
        public Dictionary<string, object> export_diagnostics;
        public BoardSnapshot board;
        public UiLayoutSnapshot ui_layout;
        [JsonProperty(NullValueHandling = NullValueHandling.Ignore)]
        public ShopStateSnapshot shop;
        [JsonProperty(NullValueHandling = NullValueHandling.Ignore)]
        public List<InventorySellSnapshot> inventory_sell;
        [JsonProperty(NullValueHandling = NullValueHandling.Ignore)]
        public EncounterGridRerollSnapshot encounter_grid_reroll;
    }

    public sealed class RunStateItem
    {
        public string id = "";
        public string name = "";
        public int level = 1;
        public string kind = "sticker";

        /// <summary>
        /// Birthday Cake accumulated word bonus when this item is stored in RAM pin memory.
        /// </summary>
        [JsonProperty(NullValueHandling = NullValueHandling.Ignore)]
        public int? birthday_cake_bonus;
    }
}
