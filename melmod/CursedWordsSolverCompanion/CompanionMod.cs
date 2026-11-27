using HarmonyLib;
using MelonLoader;
using UnityEngine;

[assembly: MelonInfo(
    typeof(CursedWordsSolverCompanion.CompanionMod),
    CursedWordsSolverCompanion.BuildInfo.Name,
    CursedWordsSolverCompanion.BuildInfo.Version,
    CursedWordsSolverCompanion.BuildInfo.Author
)]
[assembly: MelonGame(null, null)]
[assembly: HarmonyDontPatchAll]

namespace CursedWordsSolverCompanion
{
    public sealed class CompanionMod : MelonMod
    {
        private const float AutoExportIntervalSec = 0.5f;

        // Export once the fingerprint has held still this long: a shop reroll (or any
        // animation that changes state item by item) then writes one run_state instead of
        // one per item. A state that keeps changing still exports every MaxSettleWaitSec.
        private const float AutoExportSettleSec = 0.3f;
        private const float MaxSettleWaitSec = 2.0f;

        private string _lastFingerprint = "";
        private float _lastExportTime = -999f;
        private string _pendingFingerprint = "";
        private float _pendingSince = -999f;
        private float _firstUnexportedChange = -999f;

        public override void OnInitializeMelon()
        {
            MelonLogger.Msg(
                BuildInfo.Name + " v" + BuildInfo.Version
                    + " (package " + BuildInfo.PackageVersion + ")"
                    + " — auto-export loadout, board, and game dictionary on change, F7 manual refresh"
            );
            MelonLogger.Msg("Output: " + RunStateExporter.OutputFilePath);
            MelonLogger.Msg("Dictionary: " + DictionaryExporter.WordsFilePath);
            RoundLogExporter.EnsurePrefs();
            CompanionDiagnostics.EnsurePrefs();
            MelonLogger.Msg("Round logs: " + RoundLogExporter.RoundLogDir);
            MelonLogger.Msg(
                "Diagnostics: verbose="
                    + CompanionDiagnostics.VerboseLogging
                    + ", audit jsonl="
                    + CompanionDiagnostics.WriteAuditJsonl
            );

            try
            {
                var harmony = new HarmonyLib.Harmony("cursed_words_solver.companion.scoring");
                harmony.PatchAll(System.Reflection.Assembly.GetExecutingAssembly());
                MelonLogger.Msg(
                    "Scoring mismatch capture enabled (play F8 suggestion to record diffs)"
                );
                MelonLogger.Msg("Mismatch files: " + MismatchExporter.MismatchDir);
                MelonLogger.Msg(
                    "Suggestion file: "
                        + System.IO.Path.Combine(
                            System.Environment.GetFolderPath(
                                System.Environment.SpecialFolder.UserProfile
                            ),
                            ".cursed_words_solver",
                            "last_suggestion.json"
                        )
                );
            }
            catch (System.Exception ex)
            {
                MelonLogger.Error("Failed to apply scoring Harmony patches: " + ex);
            }

            SolverHost.Start();
        }

        public override void OnApplicationQuit()
        {
            SolverHost.Stop();
        }

        public override void OnDeinitializeMelon()
        {
            SolverHost.Stop();
        }

        public override void OnUpdate()
        {
            SolverHost.Poll();
            if (Input.GetKeyDown(KeyCode.F7))
            {
                RunStateExporter.TryExport(true);
                RunStateExporter.TryFlushPendingBicycleExtrasRetry();
                RefreshFingerprint();
                return;
            }

            F8ExportRequestPoller.TryPollAndExport();

            var player = GetPlayerSafe();
            if (player == null)
                return;

            RunStateExporter.TryFlushPendingBicycleExtrasRetry();
            RunStateExporter.TryMergeBicycleExtrasAfterScore();

            var fingerprint = RunStateExporter.ComputeFingerprint(player);
            if (fingerprint == _lastFingerprint)
            {
                _pendingFingerprint = "";
                _firstUnexportedChange = -999f;
                return;
            }

            var now = Time.unscaledTime;
            if (_firstUnexportedChange < 0f)
                _firstUnexportedChange = now;
            if (fingerprint != _pendingFingerprint)
            {
                _pendingFingerprint = fingerprint;
                _pendingSince = now;
            }
            var settled = now - _pendingSince >= AutoExportSettleSec;
            var waitedTooLong = now - _firstUnexportedChange >= MaxSettleWaitSec;
            if (!settled && !waitedTooLong)
                return;

            if (now - _lastExportTime < AutoExportIntervalSec)
                return;

            if (RunStateExporter.TryExport(false))
            {
                _lastFingerprint = fingerprint;
                _lastExportTime = now;
                _pendingFingerprint = "";
                _firstUnexportedChange = -999f;
            }
        }

        private void RefreshFingerprint()
        {
            var player = GetPlayerSafe();
            _lastFingerprint = player != null
                ? RunStateExporter.ComputeFingerprint(player)
                : "";
            _lastExportTime = Time.unscaledTime;
            _pendingFingerprint = "";
            _firstUnexportedChange = -999f;
        }

        private static Player GetPlayerSafe()
        {
            return RunStateExporter.GetPlayerForUpdate();
        }
    }
}
