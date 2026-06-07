using System;

using System.Collections.Generic;

using System.Text;

using Newtonsoft.Json;

using Newtonsoft.Json.Linq;



namespace CursedWordsSolverCompanion

{

    public class StaleF8Context

    {

        public bool HasBicyclePin { get; set; }

        public bool HasMutatingDnaStamp { get; set; }



        public static StaleF8Context Default()

        {

            return new StaleF8Context();

        }

    }



    public static class ExtrasDiffHelper

    {

        private static readonly string[] StaleF8IntKeys =

        {

            "cards_submitted",

            "bicycle_word_score_bonus",

        };



        private static readonly string[] StaleF8StringKeys =

        {

            "historic_words",

            "mutating_dna_letter_counts",

        };



        /// <summary>

        /// True when submit-time extras drifted from the F8 snapshot (workflow stale, not a solver bug).

        /// </summary>

        public static bool HasStaleF8ExtrasDrift(Dictionary<string, object> extrasDiff)

        {

            return HasStaleF8ExtrasDrift(extrasDiff, StaleF8Context.Default());

        }



        public static bool HasStaleF8ExtrasDrift(

            Dictionary<string, object> extrasDiff,

            StaleF8Context ctx

        )

        {

            return !string.IsNullOrEmpty(DescribeStaleF8Extras(extrasDiff, ctx));

        }



        /// <summary>

        /// Human-readable note when submit-time extras advanced past the F8 snapshot (e.g. Bicycle acc).

        /// </summary>

        public static string DescribeStaleF8Extras(Dictionary<string, object> extrasDiff)

        {

            return DescribeStaleF8Extras(extrasDiff, StaleF8Context.Default());

        }



        public static string DescribeStaleF8Extras(

            Dictionary<string, object> extrasDiff,

            StaleF8Context ctx

        )

        {

            var workflow = CollectWorkflowDriftNotes(extrasDiff, ctx);

            var bicycle = CollectBicycleDriftNotes(extrasDiff, ctx);

            if (workflow.Count == 0 && bicycle.Count == 0)

                return null;



            var notes = new List<string>();

            notes.AddRange(workflow);

            notes.AddRange(bicycle);



            return FormatStaleF8ExtrasMessage(notes);

        }



        public static string DescribeF8PredictionHistoricStaleNote(

            Dictionary<string, string> originalF8Extras,

            Dictionary<string, string> authoritativeExtras

        )

        {

            if (originalF8Extras == null || authoritativeExtras == null)

                return null;

            string f8Raw;

            string authRaw;

            originalF8Extras.TryGetValue("historic_words", out f8Raw);

            authoritativeExtras.TryGetValue("historic_words", out authRaw);

            f8Raw = (f8Raw ?? "").Trim();

            authRaw = (authRaw ?? "").Trim();

            var f8Count = CountHistoricWordsInJson(f8Raw);

            var authCount = CountHistoricWordsInJson(authRaw);

            if (authCount <= f8Count)

                return null;

            if (string.IsNullOrEmpty(f8Raw) && authCount > 0)

                return "F8 prediction used empty historic, score used " + authCount + "-word historic";

            return "F8 prediction used " + f8Count + "-word historic, score used " + authCount + "-word historic";

        }



        private static int CountHistoricWordsInJson(string json)

        {

            return RunStateExportFill.CountHistoricWordsInJson(json);

        }



        private static string FormatStaleF8ExtrasMessage(List<string> notes)

        {

            var sb = new StringBuilder();

            sb.Append(

                "F8 snapshot stale — re-run F8 after your last word before trusting predicted scores ("

            );

            sb.Append(string.Join("; ", notes.ToArray()));

            sb.Append(")");

            return sb.ToString();

        }



        /// <summary>

        /// Workflow drift: user played word(s) since F8 without refreshing the suggestion.

        /// </summary>

        public static string DescribeStaleF8WorkflowDrift(

            Dictionary<string, object> extrasDiff,

            StaleF8Context ctx

        )

        {

            var notes = CollectWorkflowDriftNotes(extrasDiff, ctx);

            if (notes.Count == 0)

                return null;



            var sb = new StringBuilder();

            sb.Append(

                "F8 snapshot stale — played word(s) since F8 — press F8 again before submitting the overlay suggestion ("

            );

            sb.Append(string.Join("; ", notes.ToArray()));

            sb.Append(")");

            return sb.ToString();

        }



        /// <summary>

        /// Bicycle accumulator drift when the Bicycle pin is equipped.

        /// </summary>

        public static string DescribeStaleF8BicycleDrift(

            Dictionary<string, object> extrasDiff,

            StaleF8Context ctx

        )

        {

            var notes = CollectBicycleDriftNotes(extrasDiff, ctx);

            if (notes.Count == 0)

                return null;



            var sb = new StringBuilder();

            sb.Append(

                "F8 snapshot stale — re-run F8 after your last word before trusting predicted scores ("

            );

            sb.Append(string.Join("; ", notes.ToArray()));

            sb.Append(")");

            return sb.ToString();

        }



        /// <summary>

        /// Compare F8 snapshot extras to live export (Bicycle acc, previous word letter).

        /// </summary>

        public static string DescribeStaleF8LoadoutDrift(

            Dictionary<string, string> f8Extras,

            Dictionary<string, string> liveExtras

        )

        {

            return DescribeStaleF8LoadoutDrift(f8Extras, liveExtras, StaleF8Context.Default());

        }



        public static string DescribeStaleF8LoadoutDrift(

            Dictionary<string, string> f8Extras,

            Dictionary<string, string> liveExtras,

            StaleF8Context ctx

        )

        {

            if (f8Extras == null || liveExtras == null)

                return null;



            var diff = DiffExtras(f8Extras, liveExtras);

            var workflow = DescribeStaleF8WorkflowDrift(diff, ctx);

            var bicycle = DescribeStaleF8BicycleDrift(diff, ctx);

            if (string.IsNullOrEmpty(workflow) && string.IsNullOrEmpty(bicycle))

                return null;

            if (string.IsNullOrEmpty(workflow))

                return bicycle;

            if (string.IsNullOrEmpty(bicycle))

                return workflow;

            return workflow + " | " + bicycle;

        }



        public static void LogStaleF8DriftWarnings(

            Dictionary<string, string> f8Extras,

            Dictionary<string, string> liveExtras,

            StaleF8Context ctx

        )

        {

            if (f8Extras == null || liveExtras == null)

                return;



            var diff = DiffExtras(f8Extras, liveExtras);

            var workflow = DescribeStaleF8WorkflowDrift(diff, ctx);

            var bicycle = DescribeStaleF8BicycleDrift(diff, ctx);

            if (!string.IsNullOrEmpty(workflow))

                MelonLoader.MelonLogger.Warning(workflow);

            if (!string.IsNullOrEmpty(bicycle))

                MelonLoader.MelonLogger.Warning(bicycle);

        }



        private static List<string> CollectWorkflowDriftNotes(

            Dictionary<string, object> extrasDiff,

            StaleF8Context ctx

        )

        {

            var notes = new List<string>();

            if (extrasDiff == null || extrasDiff.Count == 0)

                return notes;



            foreach (var key in StaleF8StringKeys)

            {

                if (key == "mutating_dna_letter_counts" && (ctx == null || !ctx.HasMutatingDnaStamp))

                    continue;

                TryAddStaleStringDriftNote(extrasDiff, key, notes);

            }



            if (extrasDiff.TryGetValue("previous_word_first_letter", out var letterRaw))

            {

                var letterEntry = letterRaw as Dictionary<string, string>;

                if (letterEntry != null)

                {

                    string f8Letter;

                    string submitLetter;

                    letterEntry.TryGetValue("f8", out f8Letter);

                    letterEntry.TryGetValue("submit", out submitLetter);

                    f8Letter = (f8Letter ?? "").Trim();

                    submitLetter = (submitLetter ?? "").Trim();

                    if (

                        !string.IsNullOrEmpty(f8Letter)

                        && !string.IsNullOrEmpty(submitLetter)

                        && !string.Equals(f8Letter, submitLetter, StringComparison.OrdinalIgnoreCase)

                    )

                        notes.Add(

                            "previous_word_first_letter f8='"

                                + f8Letter

                                + "' submit='"

                                + submitLetter

                                + "'"

                        );

                }

            }



            return notes;

        }



        private static List<string> CollectBicycleDriftNotes(

            Dictionary<string, object> extrasDiff,

            StaleF8Context ctx

        )

        {

            var notes = new List<string>();

            if (extrasDiff == null || extrasDiff.Count == 0)

                return notes;

            if (ctx == null || !ctx.HasBicyclePin)

                return notes;



            foreach (var key in StaleF8IntKeys)

                TryAddStaleIntDriftNote(extrasDiff, key, notes, requireSubmitHigher: true);



            return notes;

        }



        private static void TryAddStaleIntDriftNote(

            Dictionary<string, object> extrasDiff,

            string key,

            List<string> notes,

            bool requireSubmitHigher

        )

        {

            if (!extrasDiff.TryGetValue(key, out var raw))

                return;

            var entry = raw as Dictionary<string, string>;

            if (entry == null)

                return;

            string f8Raw;

            string submitRaw;

            entry.TryGetValue("f8", out f8Raw);

            entry.TryGetValue("submit", out submitRaw);

            f8Raw = f8Raw ?? "";

            submitRaw = submitRaw ?? "";

            int f8Val;

            int submitVal;

            if (!int.TryParse(f8Raw, out f8Val) || !int.TryParse(submitRaw, out submitVal))

            {

                if (string.IsNullOrEmpty(f8Raw) && !string.IsNullOrEmpty(submitRaw))

                    notes.Add(key + " f8=(empty) submit=" + submitRaw);

                else if (!string.IsNullOrEmpty(f8Raw) && string.IsNullOrEmpty(submitRaw))

                    notes.Add(key + " f8=" + f8Raw + " submit=(empty)");

                return;

            }

            if (requireSubmitHigher)

            {

                if (submitVal > f8Val)

                {

                    if (!IsSameSubmitBicycleIncrement(extrasDiff, submitVal - f8Val))

                        notes.Add(key + " f8=" + f8Val + " submit=" + submitVal);

                }

            }

            else if (submitVal != f8Val)

            {

                notes.Add(key + " f8=" + f8Val + " submit=" + submitVal);

            }

        }



        /// <summary>

        /// Post-word pin increment on this submit equals suited cards — not workflow drift.

        /// </summary>

        private static bool IsSameSubmitBicycleIncrement(

            Dictionary<string, object> extrasDiff,

            int delta

        )

        {

            if (delta <= 0 || extrasDiff == null)

                return false;



            var perCard = RunStateExporter.TryGetBicyclePerCardRate();

            if (perCard <= 0)

                perCard = 1;



            var suited = 0;

            object raw;

            if (extrasDiff.TryGetValue("bicycle_suited_on_path", out raw))

            {

                var entry = raw as Dictionary<string, string>;

                if (entry != null)

                {

                    string submitRaw;

                    entry.TryGetValue("submit", out submitRaw);

                    int.TryParse(submitRaw ?? "", out suited);

                }

            }



            if (suited <= 0)

                return false;



            return delta == suited * perCard;

        }



        private static void TryAddStaleStringDriftNote(

            Dictionary<string, object> extrasDiff,

            string key,

            List<string> notes

        )

        {

            if (!extrasDiff.TryGetValue(key, out var raw))

                return;

            var entry = raw as Dictionary<string, string>;

            if (entry == null)

                return;

            string f8Raw;

            string submitRaw;

            entry.TryGetValue("f8", out f8Raw);

            entry.TryGetValue("submit", out submitRaw);

            f8Raw = (f8Raw ?? "").Trim();

            submitRaw = (submitRaw ?? "").Trim();

            if (string.Equals(f8Raw, submitRaw, StringComparison.Ordinal))

                return;

            if (string.IsNullOrEmpty(f8Raw) && string.IsNullOrEmpty(submitRaw))

                return;

            if (key == "historic_words")

            {

                notes.Add("historic_words changed");

                return;

            }

            if (key == "mutating_dna_letter_counts")

            {

                if (!MutatingDnaLetterCountsEqual(f8Raw, submitRaw))

                    notes.Add("mutating_dna_letter_counts changed");

                return;

            }

            notes.Add(key + " changed");

        }



        public static bool MutatingDnaLetterCountsEqual(string f8Raw, string submitRaw)

        {

            var f8Counts = ParseLetterCountMap(f8Raw);

            var submitCounts = ParseLetterCountMap(submitRaw);

            if (f8Counts == null || submitCounts == null)

                return string.Equals(f8Raw ?? "", submitRaw ?? "", StringComparison.Ordinal);



            if (f8Counts.Count != submitCounts.Count)

                return false;



            foreach (var kv in f8Counts)

            {

                int submitVal;

                if (!submitCounts.TryGetValue(kv.Key, out submitVal) || submitVal != kv.Value)

                    return false;

            }



            return true;

        }



        private static Dictionary<string, int> ParseLetterCountMap(string raw)

        {

            raw = (raw ?? "").Trim();

            if (string.IsNullOrEmpty(raw) || raw == "{}")

                return new Dictionary<string, int>();



            try

            {

                var jobj = JObject.Parse(raw);

                var result = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);

                foreach (var prop in jobj.Properties())

                {

                    int val;

                    if (int.TryParse(prop.Value?.ToString(), out val))

                        result[prop.Name.Trim().ToLowerInvariant()] = val;

                }

                return result;

            }

            catch

            {

                return null;

            }

        }



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


