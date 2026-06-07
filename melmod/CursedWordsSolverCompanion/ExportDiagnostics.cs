using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using MelonLoader;
using Newtonsoft.Json;

namespace CursedWordsSolverCompanion
{
    /// <summary>
    /// Builds export_diagnostics embedded in run_state.json and optional export_audit.jsonl.
    /// </summary>
    public static class ExportDiagnostics
    {
        private static readonly string AuditPath = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
            ".cursed_words_solver",
            "export_audit.jsonl"
        );

        private static string _lastFingerprint = "";
        private static readonly List<string> _mergeErrors = new List<string>();
        private static string _snapshotCopySource = "";

        public static void ClearMergeErrors()
        {
            _mergeErrors.Clear();
        }

        public static void RecordMergeError(string message)
        {
            if (string.IsNullOrWhiteSpace(message))
                return;
            _mergeErrors.Add(message);
            CompanionDiagnostics.LogVerboseWarning("Export merge: " + message);
        }

        public static void SetSnapshotCopySource(string source)
        {
            _snapshotCopySource = source ?? "";
        }

        public static Dictionary<string, object> Build(
            RunStateSnapshot snapshot,
            Player player,
            string exportTrigger,
            string fingerprint,
            long exportMs
        )
        {
            var missing = ExportCompleteness.CollectMissing(snapshot, player);
            var fingerprintChanged =
                !string.IsNullOrEmpty(fingerprint)
                && !string.Equals(fingerprint, _lastFingerprint, StringComparison.Ordinal);
            if (!string.IsNullOrEmpty(fingerprint))
                _lastFingerprint = fingerprint;

            var pinMemoryCount = 0;
            if (snapshot?.extras != null
                && snapshot.extras.TryGetValue("pin_memory", out var raw)
                && !string.IsNullOrWhiteSpace(raw))
            {
                try
                {
                    var rows = JsonConvert.DeserializeObject<List<RunStateItem>>(raw);
                    if (rows != null)
                        pinMemoryCount = rows.Count;
                }
                catch
                {
                    // ignore
                }
            }

            var diag = new Dictionary<string, object>
            {
                ["companion_version"] = BuildInfo.Version,
                ["game_version"] = snapshot?.extras != null
                    && snapshot.extras.TryGetValue("game_version", out var gv)
                    ? gv
                    : "",
                ["export_trigger"] = exportTrigger ?? "",
                ["fingerprint"] = fingerprint ?? "",
                ["fingerprint_changed"] = fingerprintChanged,
                ["missing_keys"] = missing,
                ["merge_errors"] = new List<string>(_mergeErrors),
                ["pin_memory_count"] = pinMemoryCount,
                ["snapshot_copy_source"] = _snapshotCopySource,
                ["last_export_ms"] = exportMs,
                ["ui_layout_status"] = UiLayoutExporter.LastStatus ?? "",
            };

            if (snapshot?.extras != null
                && snapshot.extras.TryGetValue("snapshot_copy_export_note", out var note))
                diag["snapshot_copy_export_note"] = note;

            return diag;
        }

        public static void ApplyToSnapshot(
            RunStateSnapshot snapshot,
            Player player,
            string exportTrigger,
            string fingerprint,
            long exportMs
        )
        {
            if (snapshot == null)
                return;

            snapshot.export_diagnostics = Build(snapshot, player, exportTrigger, fingerprint, exportMs);
            ExportCompleteness.LogWarningsIfNeeded(snapshot, player, true);

            if (!CompanionDiagnostics.WriteAuditJsonl)
                return;

            try
            {
                var dir = Path.GetDirectoryName(AuditPath);
                if (!string.IsNullOrEmpty(dir))
                    Directory.CreateDirectory(dir);

                var line = JsonConvert.SerializeObject(
                    new Dictionary<string, object>
                    {
                        ["exported_at"] = DateTime.UtcNow.ToString("o"),
                        ["export_trigger"] = exportTrigger ?? "",
                        ["fingerprint"] = fingerprint ?? "",
                        ["missing_keys"] = ExportCompleteness.CollectMissing(snapshot, player),
                        ["merge_errors"] = new List<string>(_mergeErrors),
                    }
                );
                File.AppendAllText(AuditPath, line + "\n", new UTF8Encoding(false));
            }
            catch (Exception ex)
            {
                MelonLogger.Warning("export_audit.jsonl write failed: " + ex.Message);
            }
        }
    }
}
