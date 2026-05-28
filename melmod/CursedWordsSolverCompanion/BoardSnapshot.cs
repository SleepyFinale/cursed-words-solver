using System.Collections.Generic;
using Newtonsoft.Json;

namespace CursedWordsSolverCompanion
{
    public sealed class BoardSnapshot
    {
        public string source = "melmod";
        /// <summary>Row 0 is the top visible row (matches solver/OCR).</summary>
        public string row_order = "top_first";
        public int money;
        public int rows = 5;
        public int cols = 5;
        /// <summary>Where the shrunk grid sits in the 5×5 frame: bottom_left, top_left, center, or full.</summary>
        public string playable_origin = "full";
        public int playable_min_row;
        public int playable_max_row = 4;
        public int playable_min_col;
        public int playable_max_col = 4;
        public List<BoardTileSnapshot> tiles = new List<BoardTileSnapshot>();
    }

    public sealed class BoardTileSnapshot
    {
        public int row;
        public int col;
        [JsonProperty("char")]
        public string char_display = "";
        public string letter = "";
        public double base_score;
        public string color = "colorless";
        public string curse = "letter";
        public int? number_value;
        public double? fraction_value;
        public bool consumable;
        /// <summary>True when tile was placed from consumable rack (Tile.WasConsumable).</summary>
        public bool was_consumable;
        /// <summary>False when Bat (or similar) leaves this slot off the playable grid.</summary>
        public bool active = true;
        /// <summary>True when this tile is a chess capture landing square (Movie Camera, Zebra).</summary>
        public bool take;
        /// <summary>Chess piece side: black (filled) or white (outlined).</summary>
        public string chess_color = "";
        public string card_suit = "";
        public string card_rank = "";
        /// <summary>True for joker tiles (wildcard that counts as any card for poker hands).</summary>
        public bool is_joker;
        /// <summary>True when tile was GLITCH before SettleGlitchTiles.</summary>
        public bool was_glitch;
        /// <summary>CactusGrowth packet value (+1 per grid start).</summary>
        public int? cactus_growth;
        public string scattered_item_id = "";
        /// <summary>Upgrade level of the scattered sticker on this tile (when curse is item).</summary>
        public int? scattered_item_level;
        /// <summary>VOID letter: grid index when scattered (face + 10 × steps penalty).</summary>
        public int? void_penalty_steps;
    }
}
