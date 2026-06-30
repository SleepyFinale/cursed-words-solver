using System;
using System.Reflection;
using UnityEngine;

namespace CursedWordsSolverCompanion
{
    /// <summary>Live export for Cursedle (PuzzleController + FairyGrid).</summary>
    public static class CursedleExporter
    {
        private static readonly BindingFlags MemberFlags =
            BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;

        public static bool IsCursedleActive()
        {
            try
            {
                var controller = UnityEngine.Object.FindAnyObjectByType<PuzzleController>();
                if (controller == null)
                    return false;
                return TryGetFairyGrid(controller) != null;
            }
            catch
            {
                return false;
            }
        }

        public static void FillExtras(RunStateSnapshot snapshot)
        {
            if (snapshot?.extras == null)
                return;

            ClearCursedleExtras(snapshot.extras);

            if (!IsCursedleActive())
                return;

            var controller = UnityEngine.Object.FindAnyObjectByType<PuzzleController>();
            if (controller == null)
                return;

            snapshot.extras["encounter_mode"] = "cursedle";
            snapshot.extras["cursedle_active"] = "true";

            var remaining = TryGetIntField(controller, "_remainingGrids");
            if (remaining >= 0)
                snapshot.extras["cursedle_guesses_remaining"] = (remaining + 1).ToString();

            var used = CursedleGuessTracker.GuessCount;
            snapshot.extras["cursedle_guesses_used"] = used.ToString();

            var today = TryGetDateField(controller, "_today");
            if (today.HasValue)
                snapshot.extras["cursedle_puzzle_date"] = today.Value.ToString("yyyy-MM-dd");

            var guessesJson = CursedleGuessTracker.SerializeGuessesJson();
            snapshot.extras["cursedle_guesses"] = guessesJson;
        }

        public static void ClearCursedleExtras(System.Collections.Generic.Dictionary<string, string> extras)
        {
            if (extras == null)
                return;
            extras.Remove("cursedle_active");
            extras.Remove("cursedle_guesses_used");
            extras.Remove("cursedle_guesses_remaining");
            extras.Remove("cursedle_puzzle_date");
            extras.Remove("cursedle_guesses");
        }

        private static object TryGetFairyGrid(PuzzleController controller)
        {
            if (controller == null)
                return null;
            try
            {
                var field = controller.GetType().GetField("_fairyGrid", MemberFlags);
                return field?.GetValue(controller);
            }
            catch
            {
                return null;
            }
        }

        private static int TryGetIntField(object target, string name)
        {
            if (target == null)
                return -1;
            try
            {
                var field = target.GetType().GetField(name, MemberFlags);
                if (field == null)
                    return -1;
                var val = field.GetValue(target);
                if (val is int i)
                    return i;
                return Convert.ToInt32(val);
            }
            catch
            {
                return -1;
            }
        }

        private static DateTime? TryGetDateField(object target, string name)
        {
            if (target == null)
                return null;
            try
            {
                var field = target.GetType().GetField(name, MemberFlags);
                if (field == null)
                    return null;
                var val = field.GetValue(target);
                if (val is DateTime dt)
                    return dt;
                return null;
            }
            catch
            {
                return null;
            }
        }
    }
}
