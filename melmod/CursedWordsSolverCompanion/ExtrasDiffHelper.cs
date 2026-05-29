using System;
using System.Collections.Generic;
using Newtonsoft.Json.Linq;

namespace CursedWordsSolverCompanion
{
    public static class ExtrasDiffHelper
    {
        public static Dictionary<string, object> DiffExtras(
            Dictionary<string, string> before,
            Dictionary<string, string> after
        )
        {
            var diff = new Dictionary<string, object>();
            if (before == null)
                before = new Dictionary<string, string>();
            if (after == null)
                after = new Dictionary<string, string>();

            var keys = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (var k in before.Keys)
                keys.Add(k);
            foreach (var k in after.Keys)
                keys.Add(k);

            foreach (var key in keys)
            {
                string a;
                string b;
                before.TryGetValue(key, out a);
                after.TryGetValue(key, out b);
                a = a ?? "";
                b = b ?? "";
                if (string.Equals(a, b, StringComparison.Ordinal))
                    continue;

                diff[key] = new Dictionary<string, string>
                {
                    ["f8"] = a,
                    ["submit"] = b,
                };
            }

            return diff;
        }

        public static Dictionary<string, string> ExtrasFromRunStateObject(object runState)
        {
            var result = new Dictionary<string, string>();
            if (runState == null)
                return result;

            try
            {
                JObject jobj = null;
                if (runState is JObject jo)
                    jobj = jo;
                else if (runState is Dictionary<string, object> dict)
                    jobj = JObject.FromObject(dict);

                if (jobj == null || jobj["extras"] == null)
                    return result;

                var extras = jobj["extras"] as JObject;
                if (extras == null)
                    return result;

                foreach (var prop in extras.Properties())
                    result[prop.Name] = prop.Value?.ToString() ?? "";
            }
            catch
            {
                // ignore
            }

            return result;
        }

        public static object ExportDiagnosticsFromRunState(object runState)
        {
            if (runState == null)
                return null;

            try
            {
                JObject jobj = null;
                if (runState is JObject jo)
                    jobj = jo;
                else if (runState is Dictionary<string, object> dict)
                    jobj = JObject.FromObject(dict);

                return jobj?["export_diagnostics"];
            }
            catch
            {
                return null;
            }
        }
    }
}
