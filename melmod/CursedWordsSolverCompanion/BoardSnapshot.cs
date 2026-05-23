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
        /// <summary>False when Bat (or similar) leaves this slot off the playable grid.</summary>
        public bool active = true;
        /// <summary>True when this tile is a chess capture landing square (Movie Camera, Zebra).</summary>
        public bool take;
        public string card_suit = "";
        public string card_rank = "";
    }
}
