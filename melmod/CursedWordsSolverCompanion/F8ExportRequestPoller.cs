using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Threading;
using MelonLoader;
using Newtonsoft.Json;

namespace CursedWordsSolverCompanion
{
    /// <summary>
    /// Polls f8_export_request.json from the Python solver and forces a live game export.
    /// </summary>
    public static class F8ExportRequestPoller
    {
        private const int ReadRetryCount = 12;
        private const int ReadRetryDelayMs = 40;

        private static readonly string RequestPath = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
            ".cursed_words_solver",
            "f8_export_request.json"
        );

        private static string _lastHandledRequestId = "";

        public static void TryPollAndExport()
        {
            try
            {
                if (!File.Exists(RequestPath))
                    return;

                var json = ReadRequestJsonWithRetry();
                if (string.IsNullOrWhiteSpace(json))
                    return;

                var root = JsonConvert.DeserializeObject<Dictionary<string, object>>(json);
                if (root == null)
                    return;

                object rawId;
                if (!root.TryGetValue("request_id", out rawId) || rawId == null)
                    return;

                var requestId = (rawId.ToString() ?? "").Trim();
                if (string.IsNullOrEmpty(requestId))
                    return;
                if (string.Equals(requestId, _lastHandledRequestId, StringComparison.Ordinal))
                    return;

                _lastHandledRequestId = requestId;
                if (RunStateExporter.TryExportForF8(requestId))
                {
                    CompanionDiagnostics.LogVerbose(
                        "F8 live export for request " + requestId
                    );
                }
            }
            catch (Exception ex)
            {
                CompanionDiagnostics.LogVerboseWarning(
                    "F8 export request poll failed: " + ex.Message
                );
            }
        }

        private static string ReadRequestJsonWithRetry()
        {
            Exception lastError = null;
            for (var attempt = 0; attempt < ReadRetryCount; attempt++)
            {
                try
                {
                    using (var stream = new FileStream(
                        RequestPath,
                        FileMode.Open,
                        FileAccess.Read,
                        FileShare.ReadWrite))
                    using (var reader = new StreamReader(stream, Encoding.UTF8))
                    {
                        return reader.ReadToEnd();
                    }
                }
                catch (IOException ex)
                {
                    lastError = ex;
                }
                catch (UnauthorizedAccessException ex)
                {
                    lastError = ex;
                }

                if (attempt + 1 < ReadRetryCount)
                    Thread.Sleep(ReadRetryDelayMs);
            }

            if (lastError != null)
                throw lastError;
            return "";
        }
    }
}
