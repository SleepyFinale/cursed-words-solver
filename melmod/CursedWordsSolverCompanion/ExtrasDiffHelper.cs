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

        public bool HasBentoStamp { get; set; }



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



        private static readonly string[] StaleF8TileNinjaIntKeys =

        {

            "tile_ninja_consumables_used",

            "tile_ninja_word_bonus_percent",

        };



        private static readonly string[] StaleF8StringKeys =

        {

            "historic_words",

            "mutating_dna_letter_counts",

            "birthday_cake_bonus",

        };



        private static readonly string[] StaleF8BossKeys =

        {

            "boss_modifiers",

            "boss_modifier_floor_mods",

            "boss_cursed",

            "boss_area_number",

            "boss_floor_modification",

        };



        /// <summary>

        /// True when F8 embed had boss extras that submit-time scoring did not use.

        /// </summary>

        public static bool HasBossExtrasDrift(Dictionary<string, object> extrasDiff)

        {

            return CollectBossDriftNotes(extrasDiff).Count > 0;

        }



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

            var benignShrink = IsBenignWorkflowShrinkDrift(extrasDiff, ctx);

            var workflow = benignShrink

                ? new List<string>()

                : CollectWorkflowDriftNotes(extrasDiff, ctx);

            var bicycle = CollectBicycleDriftNotes(extrasDiff, ctx);

            var tileNinja = CollectTileNinjaDriftNotes(extrasDiff);

            var boss = CollectBossDriftNotes(extrasDiff);

            if (workflow.Count == 0 && bicycle.Count == 0 && tileNinja.Count == 0 && boss.Count == 0)

                return null;



            var notes = new List<string>();

            notes.AddRange(workflow);

            notes.AddRange(bicycle);

            notes.AddRange(tileNinja);

            notes.AddRange(boss);



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

            {

                if (

                    f8Count > authCount

                    && originalF8Extras != null

                    && authoritativeExtras != null

                    && HasPreviousWordLetterDrift(originalF8Extras, authoritativeExtras)

                )

                    return (

                        "F8 prediction used "

                            + f8Count

                            + "-word historic, score used "

                            + authCount

                            + "-word historic (previous word letter drift)"

                    );

                return null;

            }

            if (string.IsNullOrEmpty(f8Raw) && authCount > 0)

                return "F8 prediction used empty historic, score used " + authCount + "-word historic";

            return "F8 prediction used " + f8Count + "-word historic, score used " + authCount + "-word historic";

        }



        private static bool HasPreviousWordLetterDrift(

            Dictionary<string, string> f8Extras,

            Dictionary<string, string> submitExtras

        )

        {

            if (f8Extras == null || submitExtras == null)

                return false;

            string f8Letter;

            string submitLetter;

            f8Extras.TryGetValue("previous_word_first_letter", out f8Letter);

            submitExtras.TryGetValue("previous_word_first_letter", out submitLetter);

            f8Letter = (f8Letter ?? "").Trim();

            submitLetter = (submitLetter ?? "").Trim();

            if (string.IsNullOrEmpty(f8Letter) || string.IsNullOrEmpty(submitLetter))

                return false;

            return !string.Equals(

                f8Letter,

                submitLetter,

                StringComparison.OrdinalIgnoreCase

            );

        }



        /// <summary>

        /// True when submit-time workflow shows a word was played after F8 (historic or count advanced).

        /// </summary>

        public static bool HasPlayedWordSinceF8(Dictionary<string, object> extrasDiff)

        {

            if (extrasDiff == null || extrasDiff.Count == 0)

                return false;



            if (extrasDiff.TryGetValue("scoring_previous_words_count", out var spcRaw))

            {

                var spcEntry = spcRaw as Dictionary<string, string>;

                if (spcEntry != null)

                {

                    int f8Count;

                    int submitCount;

                    int.TryParse(

                        (spcEntry.TryGetValue("f8", out var f8Spc) ? f8Spc : null) ?? "0",

                        out f8Count

                    );

                    int.TryParse(

                        (spcEntry.TryGetValue("submit", out var submitSpc) ? submitSpc : null)

                            ?? "0",

                        out submitCount

                    );

                    if (submitCount > f8Count)

                        return true;

                }

            }



            if (extrasDiff.TryGetValue("historic_words", out var histRaw))

            {

                var histEntry = histRaw as Dictionary<string, string>;

                if (histEntry != null)

                {

                    string f8Hist;

                    string submitHist;

                    histEntry.TryGetValue("f8", out f8Hist);

                    histEntry.TryGetValue("submit", out submitHist);

                    var f8Count = CountHistoricWordsInJson((f8Hist ?? "").Trim());

                    var submitCount = CountHistoricWordsInJson((submitHist ?? "").Trim());

                    if (submitCount > f8Count)

                        return true;

                }

            }



            return false;

        }



        /// <summary>

        /// Human-readable note when a word was played after F8 without refreshing the suggestion.

        /// </summary>

        public static string DescribePlayedWordSinceF8Drift(

            Dictionary<string, object> extrasDiff,

            StaleF8Context ctx

        )

        {

            if (!HasPlayedWordSinceF8(extrasDiff))

                return null;



            var notes = new List<string>();



            if (extrasDiff.TryGetValue("scoring_previous_words_count", out var spcRaw))

            {

                var spcEntry = spcRaw as Dictionary<string, string>;

                if (spcEntry != null)

                {

                    int f8Count;

                    int submitCount;

                    int.TryParse(

                        (spcEntry.TryGetValue("f8", out var f8Spc) ? f8Spc : null) ?? "0",

                        out f8Count

                    );

                    int.TryParse(

                        (spcEntry.TryGetValue("submit", out var submitSpc) ? submitSpc : null)

                            ?? "0",

                        out submitCount

                    );

                    if (submitCount > f8Count)

                        notes.Add(

                            "scoring_previous_words_count f8="

                                + f8Count

                                + " submit="

                                + submitCount

                        );

                }

            }



            if (extrasDiff.TryGetValue("historic_words", out var histRaw))

            {

                var histEntry = histRaw as Dictionary<string, string>;

                if (histEntry != null)

                {

                    string f8Hist;

                    string submitHist;

                    histEntry.TryGetValue("f8", out f8Hist);

                    histEntry.TryGetValue("submit", out submitHist);

                    var f8Count = CountHistoricWordsInJson((f8Hist ?? "").Trim());

                    var submitCount = CountHistoricWordsInJson((submitHist ?? "").Trim());

                    if (submitCount > f8Count)

                        notes.Add(

                            "historic_words f8=" + f8Count + " submit=" + submitCount

                        );

                }

            }



            if (notes.Count == 0)

                notes.Add("workflow advanced since F8");



            var sb = new StringBuilder();

            sb.Append(

                "F8 snapshot stale — played word(s) since F8 — press F8 again before submitting the overlay suggestion ("

            );

            sb.Append(string.Join("; ", notes.ToArray()));

            sb.Append(")");

            return sb.ToString();

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

        /// True when F8 embed workflow is ahead of live/submit (stale export lag), not user played since F8.

        /// </summary>

        public static bool IsStaleExportAheadDrift(Dictionary<string, object> extrasDiff)

        {

            if (extrasDiff == null || extrasDiff.Count == 0)

                return false;



            if (extrasDiff.TryGetValue("historic_words", out var histRaw))

            {

                var histEntry = histRaw as Dictionary<string, string>;

                if (histEntry != null)

                {

                    string f8Hist;

                    string submitHist;

                    histEntry.TryGetValue("f8", out f8Hist);

                    histEntry.TryGetValue("submit", out submitHist);

                    var f8Count = CountHistoricWordsInJson((f8Hist ?? "").Trim());

                    var submitCount = CountHistoricWordsInJson((submitHist ?? "").Trim());

                    if (f8Count > submitCount)

                        return true;

                }

            }



            if (extrasDiff.TryGetValue("scoring_previous_words_count", out var spcRaw))

            {

                var spcEntry = spcRaw as Dictionary<string, string>;

                if (spcEntry != null)

                {

                    int f8Count;

                    int submitCount;

                    int.TryParse(

                        (spcEntry.TryGetValue("f8", out var f8Spc) ? f8Spc : null) ?? "0",

                        out f8Count

                    );

                    int.TryParse(

                        (spcEntry.TryGetValue("submit", out var submitSpc) ? submitSpc : null)

                            ?? "0",

                        out submitCount

                    );

                    if (f8Count > submitCount)

                        return true;

                }

            }



            return false;

        }



        /// <summary>

        /// True when F8 embed is longer than submit projection (benign shrink), not played-since-F8 drift.

        /// </summary>

        public static bool IsBenignWorkflowShrinkDrift(

            Dictionary<string, object> extrasDiff,

            StaleF8Context ctx

        )

        {

            if (extrasDiff == null || extrasDiff.Count == 0)

                return false;



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

                    {

                        if (ctx != null && ctx.HasBentoStamp)

                            return false;

                        if (!IsStaleExportAheadDrift(extrasDiff))

                            return false;

                    }

                }

            }



            if (

                ctx != null

                && ctx.HasMutatingDnaStamp

                && extrasDiff.TryGetValue("mutating_dna_letter_counts", out var dnaRaw)

            )

            {

                var dnaEntry = dnaRaw as Dictionary<string, string>;

                if (dnaEntry != null)

                {

                    string f8Dna;

                    string submitDna;

                    dnaEntry.TryGetValue("f8", out f8Dna);

                    dnaEntry.TryGetValue("submit", out submitDna);

                    if (!MutatingDnaLetterCountsEqual(f8Dna, submitDna))

                        return false;

                }

            }



            var hasShrink = false;



            if (extrasDiff.TryGetValue("historic_words", out var histRaw))

            {

                var histEntry = histRaw as Dictionary<string, string>;

                if (histEntry != null)

                {

                    string f8Hist;

                    string submitHist;

                    histEntry.TryGetValue("f8", out f8Hist);

                    histEntry.TryGetValue("submit", out submitHist);

                    var f8Count = CountHistoricWordsInJson((f8Hist ?? "").Trim());

                    var submitCount = CountHistoricWordsInJson((submitHist ?? "").Trim());

                    if (submitCount > f8Count)

                        return false;

                    if (

                        f8Count > submitCount

                        || (

                            f8Count == submitCount

                            && !string.Equals(

                                (f8Hist ?? "").Trim(),

                                (submitHist ?? "").Trim(),

                                StringComparison.Ordinal

                            )

                            && (f8Count > 0 || submitCount > 0)

                        )

                    )

                        hasShrink = true;

                }

            }



            if (extrasDiff.TryGetValue("scoring_previous_words_count", out var spcRaw))

            {

                var spcEntry = spcRaw as Dictionary<string, string>;

                if (spcEntry != null)

                {

                    int f8Count;

                    int submitCount;

                    int.TryParse(

                        (spcEntry.TryGetValue("f8", out var f8Spc) ? f8Spc : null) ?? "0",

                        out f8Count

                    );

                    int.TryParse(

                        (spcEntry.TryGetValue("submit", out var submitSpc) ? submitSpc : null)

                            ?? "0",

                        out submitCount

                    );

                    if (submitCount > f8Count)

                        return false;

                    if (f8Count > submitCount)

                        hasShrink = true;

                }

            }



            return hasShrink;

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



            if (extrasDiff.TryGetValue("scoring_previous_words_count", out var spcRaw))

            {

                var spcEntry = spcRaw as Dictionary<string, string>;

                if (spcEntry != null)

                {

                    int f8Count;

                    int submitCount;

                    int.TryParse((spcEntry.TryGetValue("f8", out var f8Spc) ? f8Spc : null) ?? "0", out f8Count);

                    int.TryParse((spcEntry.TryGetValue("submit", out var submitSpc) ? submitSpc : null) ?? "0", out submitCount);

                    if (f8Count > submitCount)

                        notes.Add(

                            "scoring_previous_words_count f8="

                                + f8Count

                                + " submit="

                                + submitCount

                        );

                }

            }



            return notes;

        }



        private static List<string> CollectBossDriftNotes(Dictionary<string, object> extrasDiff)

        {

            var notes = new List<string>();

            if (extrasDiff == null || extrasDiff.Count == 0)

                return notes;



            foreach (var key in StaleF8BossKeys)

            {

                if (!extrasDiff.TryGetValue(key, out var raw))

                    continue;

                var entry = raw as Dictionary<string, string>;

                if (entry == null)

                    continue;



                string f8Val;

                string submitVal;

                entry.TryGetValue("f8", out f8Val);

                entry.TryGetValue("submit", out submitVal);

                f8Val = (f8Val ?? "").Trim();

                submitVal = (submitVal ?? "").Trim();

                if (string.IsNullOrEmpty(f8Val))

                    continue;

                if (string.Equals(f8Val, submitVal, StringComparison.Ordinal))

                    continue;



                notes.Add(

                    key

                        + " f8='"

                        + TruncateBossDriftValue(f8Val)

                        + "' submit='"

                        + TruncateBossDriftValue(submitVal)

                        + "'"

                );

            }



            return notes;

        }



        private static string TruncateBossDriftValue(string value)

        {

            if (string.IsNullOrEmpty(value))

                return "(empty)";

            if (value.Length <= 48)

                return value;

            return value.Substring(0, 45) + "...";

        }



        private static List<string> CollectTileNinjaDriftNotes(

            Dictionary<string, object> extrasDiff

        )

        {

            var notes = new List<string>();

            if (extrasDiff == null || extrasDiff.Count == 0)

                return notes;



            foreach (var key in StaleF8TileNinjaIntKeys)

                TryAddStaleIntDriftNote(extrasDiff, key, notes, requireSubmitHigher: true);



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

            if (key == "birthday_cake_bonus")

            {

                int f8Val;

                int submitVal;

                if (

                    int.TryParse(f8Raw, out f8Val)

                    && int.TryParse(submitRaw, out submitVal)

                    && submitVal > f8Val

                )

                    notes.Add("birthday_cake_bonus f8=" + f8Val + " submit=" + submitVal);

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


