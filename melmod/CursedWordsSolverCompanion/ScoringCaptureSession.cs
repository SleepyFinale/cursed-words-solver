using System.Collections.Generic;
using MelonLoader;

namespace CursedWordsSolverCompanion
{
    public static class ScoringCaptureSession
    {
        private static bool _active;

        public static bool IsActive
        {
            get { return _active; }
        }
        private static LastSuggestion _suggestion;
        private static string _word;
        private static List<int> _path;
        private static string _submitMethod;
        private static List<Dictionary<string, object>> _actualTrace;
        private static string _boardFingerprint;
        private static string _loadoutFingerprint;

        public static void BeginSubmit(
            string submitMethod,
            List<TileSelection> selections,
            List<string> words
        )
        {
            _active = false;
            _actualTrace = null;
            _suggestion = SuggestionMatcher.Load();
            _word = SuggestionMatcher.WordFromSubmit(selections, words);
            _path = SuggestionMatcher.PathFromSelections(selections);
            _submitMethod = submitMethod;

            var player = RunStateExporter.GetPlayerForUpdate();
            if (player == null)
                return;

            _boardFingerprint = FingerprintUtil.ComputeBoardFingerprint(player);
            _loadoutFingerprint = FingerprintUtil.ComputeLoadoutFingerprint(player);

            if (
                SuggestionMatcher.MatchesSuggestion(
                    _suggestion,
                    _word,
                    _path,
                    _boardFingerprint,
                    _loadoutFingerprint
                )
            )
            {
                _active = true;
                MelonLogger.Msg(
                    "Scoring capture: tracking suggested word '"
                        + _word
                        + "' (predicted "
                        + (_suggestion != null ? _suggestion.predicted_score.ToString() : "?")
                        + " pts)"
                );
                return;
            }

            if (_suggestion != null)
            {
                MelonLogger.Msg(
                    "Scoring capture skipped: "
                        + SuggestionMatcher.DescribeMismatch(
                            _suggestion,
                            _word,
                            _path,
                            _boardFingerprint,
                            _loadoutFingerprint
                        )
                );
            }
        }

        public static void BeginPuzzleSubmit(List<TileSelection> selections)
        {
            BeginSubmit("PuzzleController.SubmitWord", selections, null);
        }

        public static void OnScoreStepsCalculated(List<ScoreCalcVizInfo> steps)
        {
            if (!_active || steps == null)
                return;
            _actualTrace = ScoringTraceCollector.SerializeSteps(steps);
        }

        public static void EndSubmit()
        {
            if (!_active)
                return;

            try
            {
                var actualScore = 0;
                if (CalculateOverallScorePatch.LastCalculatedSteps != null)
                {
                    var packet = ScoreCalculation.GetScoreFromScoreCalcInfo(
                        CalculateOverallScorePatch.LastCalculatedSteps
                    );
                    actualScore = (int)ScoringTraceCollector.ScorePacketToLong(packet);
                }

                var extras = RunStateExporter.BuildExtrasSnapshot();
                MismatchExporter.ExportIfMismatch(
                    _suggestion,
                    _word,
                    _path,
                    actualScore,
                    _actualTrace,
                    _boardFingerprint,
                    _loadoutFingerprint,
                    extras,
                    _submitMethod
                );
            }
            catch (System.Exception ex)
            {
                MelonLogger.Error("Scoring capture failed: " + ex);
            }
            finally
            {
                _active = false;
                CalculateOverallScorePatch.LastCalculatedSteps = null;
            }
        }
    }
}
