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
            return SerializeSteps(steps, null);
        }

        public static List<Dictionary<string, object>> SerializeSteps(
            List<ScoreCalcVizInfo> steps,
            List<int> pathIndices
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
                trace.Add(SerializeStep(step, i, pathIndices));
            }
            return trace;
        }

        private static Dictionary<string, object> SerializeStep(
            ScoreCalcVizInfo step,
            int index,
            List<int> pathIndices
        )
        {
            var entry = new Dictionary<string, object>
            {
                ["step_index"] = index,
                ["money"] = step.Money,
                ["is_pulsing_whole_word"] = step.IsPulsingWholeWord,
                ["is_settling_glitch"] = step.IsSettlingGlitchTiles,
                ["poker_hand"] = step.PokerHand.ToString(),
            };

            if (pathIndices != null && pathIndices.Count > 0)
                entry["path_tile_indices"] = new List<int>(pathIndices);

            long tileSum = 0L;
            if (step.TileScores != null && step.TileScores.Count > 0)
            {
                var scores = new List<long>();
                var multipliers = new List<long>();
                for (var i = 0; i < step.TileScores.Count; i++)
                {
                    var pkt = step.TileScores[i];
                    var score = pkt != null ? pkt.Score : 0L;
                    scores.Add(score);
                    tileSum += score;

                    long mult = 0L;
                    if (step.TileScoreMultipliers != null && i < step.TileScoreMultipliers.Count)
                    {
                        var mp = step.TileScoreMultipliers[i];
                        mult = mp.HasValue ? mp.Value : 0L;
                    }
                    multipliers.Add(mult);
                }
                entry["tile_scores"] = scores;
                if (multipliers.Count > 0)
                    entry["tile_score_multipliers"] = multipliers;
            }

            long wordAdditive = 0L;
            if (step.WordBonus != null)
            {
                wordAdditive = step.WordBonus.Bonus != null ? step.WordBonus.Bonus.Score : 0L;
                entry["word_bonus"] = wordAdditive;
                entry["word_bonus_multiplicative"] = step.WordBonus.IsMultiplicative;
                entry["word_bonus_poison"] = step.WordBonus.IsPoison;
            }

            entry["running_subtotal"] = tileSum + (step.WordBonus != null && !step.WordBonus.IsMultiplicative
                ? wordAdditive
                : 0L);

            if (step.RelevantItem != null)
            {
                entry["item_id"] = RunStateExporter.Slugify(
                    step.RelevantItem.ArtFileName,
                    step.RelevantItem.Name
                );
                entry["item_name"] = step.RelevantItem.Name ?? "";
                var level = RunStateExporter.GetUpgradeableLevel(step.RelevantItem);
                if (level >= 1)
                    entry["item_level"] = level;
            }

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
