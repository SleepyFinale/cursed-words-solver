using System.Collections.Generic;
using HarmonyLib;

namespace CursedWordsSolverCompanion
{
    [HarmonyPatch(typeof(PuzzleController), "Start")]
    public static class PuzzleControllerStartPatch
    {
        [HarmonyPostfix]
        public static void Postfix(PuzzleController __instance)
        {
            if (__instance == null)
                return;
            if (CursedleExporter.IsCursedleActive())
                CursedleGuessTracker.OnPuzzleStarted(__instance);
        }
    }

    [HarmonyPatch(typeof(PuzzleController), "MainMenuButtonCallback")]
    public static class PuzzleControllerExitPatch
    {
        [HarmonyPrefix]
        public static void Prefix()
        {
            CursedleGuessTracker.Reset();
        }
    }

    [HarmonyPatch(typeof(WordHistoryController), "AddPuzzleEntry")]
    public static class WordHistoryAddPuzzleEntryPatch
    {
        [HarmonyPostfix]
        public static void Postfix(
            WordHistoryController __instance,
            List<Tile> tiles,
            List<TileSolutionState> solutionStates
        )
        {
            if (!CursedleExporter.IsCursedleActive())
                return;
            var controller = UnityEngine.Object.FindAnyObjectByType<PuzzleController>();
            CursedleGuessTracker.OnGuessAdded(controller, tiles, solutionStates);
        }
    }
}
