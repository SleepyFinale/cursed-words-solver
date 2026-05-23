using System.Collections.Generic;
using HarmonyLib;

namespace CursedWordsSolverCompanion
{
    [HarmonyPatch(typeof(EncounterController), "SubmitWord")]
    public static class EncounterSubmitWordPatch
    {
        [HarmonyPrefix]
        public static void Prefix(List<TileSelection> tiles, List<string> words)
        {
            ScoringCaptureSession.BeginSubmit(
                "EncounterController.SubmitWord",
                tiles,
                words
            );
        }

        [HarmonyPostfix]
        public static void Postfix()
        {
            ScoringCaptureSession.EndSubmit();
        }
    }

    [HarmonyPatch(typeof(PuzzleController), "SubmitWord")]
    public static class PuzzleSubmitWordPatch
    {
        [HarmonyPrefix]
        public static void Prefix(List<TileSelection> tiles)
        {
            ScoringCaptureSession.BeginPuzzleSubmit(tiles);
        }

        [HarmonyPostfix]
        public static void Postfix()
        {
            ScoringCaptureSession.EndSubmit();
        }
    }

    [HarmonyPatch(typeof(ScoreCalculation), "CalculateOverallScore")]
    public static class CalculateOverallScorePatch
    {
        public static List<ScoreCalcVizInfo> LastCalculatedSteps;

        [HarmonyPrefix]
        public static void Prefix(List<BossModifier> bossModifiers)
        {
            BossResolver.CacheFromScoring(bossModifiers);
        }

        [HarmonyPostfix]
        public static void Postfix(List<ScoreCalcVizInfo> __result)
        {
            if (!ScoringCaptureSession.IsActive)
                return;
            LastCalculatedSteps = __result;
            ScoringCaptureSession.OnScoreStepsCalculated(__result);
        }
    }
}
