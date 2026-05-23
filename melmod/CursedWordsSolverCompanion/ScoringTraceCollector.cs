using System;
using System.Collections.Generic;

namespace CursedWordsSolverCompanion
{
    public static class ScoringTraceCollector
    {
        public static List<Dictionary<string, object>> SerializeSteps(
            List<ScoreCalcVizInfo> steps
        )
        {
            var trace = new List<Dictionary<string, object>>();
            if (steps == null)
                return trace;

            for (var i = 0; i < steps.Count; i++)
            {
                var step = steps[i];
                if (step == null)
                    continue;
                trace.Add(SerializeStep(step, i));
            }
            return trace;
        }

        private static Dictionary<string, object> SerializeStep(ScoreCalcVizInfo step, int index)
        {
            var entry = new Dictionary<string, object>
            {
                ["step_index"] = index,
                ["money"] = step.Money,
                ["is_pulsing_whole_word"] = step.IsPulsingWholeWord,
                ["is_settling_glitch"] = step.IsSettlingGlitchTiles,
            };

            if (step.TileScores != null && step.TileScores.Count > 0)
            {
                var scores = new List<long>();
                for (var i = 0; i < step.TileScores.Count; i++)
                {
                    var pkt = step.TileScores[i];
                    scores.Add(pkt != null ? pkt.Score : 0L);
                }
                entry["tile_scores"] = scores;
            }

            if (step.WordBonus != null)
            {
                entry["word_bonus"] = step.WordBonus.Bonus != null
                    ? step.WordBonus.Bonus.Score
                    : 0L;
                entry["word_bonus_multiplicative"] = step.WordBonus.IsMultiplicative;
                entry["word_bonus_poison"] = step.WordBonus.IsPoison;
            }

            if (step.RelevantItem != null)
            {
                entry["item_id"] = RunStateExporter.Slugify(
                    step.RelevantItem.ArtFileName,
                    step.RelevantItem.Name
                );
                entry["item_name"] = step.RelevantItem.Name ?? "";
            }

            entry["poker_hand"] = step.PokerHand.ToString();

            return entry;
        }

        public static long ScorePacketToLong(ScorePacket packet)
        {
            if (packet == null)
                return 0L;
            try
            {
                if (packet.IsInfinite)
                    return long.MaxValue;
                return packet.Score;
            }
            catch
            {
                return 0L;
            }
        }
    }
}
