using HarmonyLib;

namespace CursedWordsSolverCompanion
{
    /// <summary>
    /// Snapshot picks its copy target in ApplyStartOfGridEffect (grid start).
    /// </summary>
    [HarmonyPatch(typeof(Snapshot), "ApplyStartOfGridEffect")]
    public static class SnapshotGridStartPatch
    {
        [HarmonyPostfix]
        public static void Postfix(Snapshot __instance)
        {
            RunStateExporter.CaptureSnapshotCopyFromGridStart(__instance);
        }
    }
}
