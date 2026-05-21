using MelonLoader;
using UnityEngine;

[assembly: MelonInfo(
    typeof(CursedWordsSolverCompanion.CompanionMod),
    CursedWordsSolverCompanion.BuildInfo.Name,
    CursedWordsSolverCompanion.BuildInfo.Version,
    CursedWordsSolverCompanion.BuildInfo.Author
)]
[assembly: MelonGame(null, null)]

namespace CursedWordsSolverCompanion
{
    public sealed class CompanionMod : MelonMod
    {
        private const float AutoExportIntervalSec = 0.5f;

        private string _lastFingerprint = "";
        private float _lastExportTime = -999f;

        public override void OnInitializeMelon()
        {
            MelonLogger.Msg(
                BuildInfo.Name + " v" + BuildInfo.Version
                    + " — auto-export loadout, board, and game dictionary on change, F7 manual refresh"
            );
            MelonLogger.Msg("Output: " + RunStateExporter.OutputFilePath);
            MelonLogger.Msg("Dictionary: " + DictionaryExporter.WordsFilePath);
        }

        public override void OnUpdate()
        {
            if (Input.GetKeyDown(KeyCode.F7))
            {
                RunStateExporter.TryExport(true);
                RefreshFingerprint();
                return;
            }

            var player = GetPlayerSafe();
            if (player == null)
                return;

            var fingerprint = RunStateExporter.ComputeFingerprint(player);
            if (fingerprint == _lastFingerprint)
                return;

            if (Time.unscaledTime - _lastExportTime < AutoExportIntervalSec)
                return;

            if (RunStateExporter.TryExport(false))
            {
                _lastFingerprint = fingerprint;
                _lastExportTime = Time.unscaledTime;
            }
        }

        private void RefreshFingerprint()
        {
            var player = GetPlayerSafe();
            _lastFingerprint = player != null
                ? RunStateExporter.ComputeFingerprint(player)
                : "";
            _lastExportTime = Time.unscaledTime;
        }

        private static Player GetPlayerSafe()
        {
            return RunStateExporter.GetPlayerForUpdate();
        }
    }
}
