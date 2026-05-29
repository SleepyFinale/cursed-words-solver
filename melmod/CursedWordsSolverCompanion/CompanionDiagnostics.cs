using MelonLoader;
using MelonLoader.Preferences;

namespace CursedWordsSolverCompanion
{
    /// <summary>
    /// MelonPreferences for verbose logging and export audit jsonl.
    /// </summary>
    public static class CompanionDiagnostics
    {
        private static MelonPreferences_Category _prefs;
        private static MelonPreferences_Entry<bool> _verboseLogging;
        private static MelonPreferences_Entry<bool> _writeAuditJsonl;

        public static void EnsurePrefs()
        {
            if (_prefs != null)
                return;

            _prefs = MelonPreferences.CreateCategory(
                "CursedWordsSolverCompanion_Diagnostics",
                "Cursed Words Solver Diagnostics"
            );
            _verboseLogging = _prefs.CreateEntry(
                "VerboseLogging",
                true,
                "Verbose logging",
                "Log auto-export, capture decisions, and merge details to MelonLoader console"
            );
            _writeAuditJsonl = _prefs.CreateEntry(
                "WriteAuditJsonl",
                true,
                "Write export audit jsonl",
                "Append one JSON line per export to export_audit.jsonl when verbose logging is on"
            );
        }

        public static bool VerboseLogging
        {
            get
            {
                EnsurePrefs();
                return _verboseLogging.Value;
            }
        }

        public static bool WriteAuditJsonl
        {
            get
            {
                EnsurePrefs();
                return VerboseLogging && _writeAuditJsonl.Value;
            }
        }

        public static void LogVerbose(string message)
        {
            if (!VerboseLogging || string.IsNullOrEmpty(message))
                return;
            MelonLogger.Msg(message);
        }

        public static void LogVerboseWarning(string message)
        {
            if (!VerboseLogging || string.IsNullOrEmpty(message))
                return;
            MelonLogger.Warning(message);
        }
    }
}
