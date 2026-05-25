using System.Collections.Generic;

namespace CursedWordsSolverCompanion
{
    public sealed class ConsumableRackTileSnapshot
    {
        public int rack_index;
        public string letter = "";
        public string char_display = "";
        public string color = "colorless";
        public string curse = "letter";
        public double base_score;
    }

    public static class ConsumableRackExporter
    {
        public static List<ConsumableRackTileSnapshot> Export(Player player)
        {
            var result = new List<ConsumableRackTileSnapshot>();
            if (player?.ConsumableTiles == null)
                return result;

            for (var i = 0; i < player.ConsumableTiles.Length; i++)
            {
                var tile = player.ConsumableTiles[i];
                if (tile == null)
                    continue;

                var mapped = BoardExporter.ExportTileAt(tile, -1, i);
                if (mapped == null)
                    continue;

                result.Add(
                    new ConsumableRackTileSnapshot
                    {
                        rack_index = i,
                        letter = mapped.letter,
                        char_display = mapped.char_display,
                        color = mapped.color,
                        curse = mapped.curse,
                        base_score = mapped.base_score,
                    }
                );
            }

            return result;
        }
    }
}
