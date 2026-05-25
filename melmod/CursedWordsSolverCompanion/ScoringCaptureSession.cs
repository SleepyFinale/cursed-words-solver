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
        private static Dictionary<string, string> _scoringContextExtras =
            new Dictionary<string, string>();
        private static BoardSnapshot _submitBoardSnapshot;

        public static BoardSnapshot SubmitBoardSnapshot
        {
            get { return _submitBoardSnapshot; }
        }

        public static void BeginSubmit(
            string submitMethod,
            List<TileSelection> selections,
            List<string> words
        )
        {
            _active = false;
            _actualTrace = null;
            _submitBoardSnapshot = null;
            _scoringContextExtras = new Dictionary<string, string>();
            _suggestion = SuggestionMatcher.Load();
            _word = SuggestionMatcher.WordFromSubmit(selections, words);
            _path = SuggestionMatcher.PathFromSelections(selections);
            _submitMethod = submitMethod;

            var player = RunStateExporter.GetPlayerForUpdate();
            if (player == null)
                return;

            _boardFingerprint = FingerprintUtil.ComputeBoardFingerprint(player);
            _loadoutFingerprint = FingerprintUtil.ComputeLoadoutFingerprint(player);

            var birthdayBonus = RunStateExporter.TryGetBirthdayCakeBonus(player);
            if (birthdayBonus >= 0)
                _scoringContextExtras["birthday_cake_bonus"] = birthdayBonus.ToString();

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

        public static void OnScoringContext(List<HistoricWord> previousWords)
        {
            if (!_active)
                return;

            var player = RunStateExporter.GetPlayerForUpdate();
            var captured = ScoringContextCapture.ExtractFromPreviousWords(previousWords);
            var letterCounts = ScoringContextCapture.ResolveMutatingDnaLetterCounts(
                player,
                previousWords
            );
            captured["mutating_dna_letter_counts"] =
                ScoringContextCapture.SerializeLetterCounts(letterCounts);

            foreach (var kv in captured)
                _scoringContextExtras[kv.Key] = kv.Value;
        }

        public static void OnScoreStepsCalculated(List<ScoreCalcVizInfo> steps)
        {
            if (!_active || steps == null)
                return;
            _actualTrace = ScoringTraceCollector.SerializeSteps(steps);
        }

        /// <summary>
        /// Snapshot board + take flags from word tiles while ScoreCalculation runs.
        /// </summary>
        public static void OnSubmitWordTiles(List<TileSelection> wordTiles)
        {
            if (!_active)
                return;

            var player = RunStateExporter.GetPlayerForUpdate();
            if (player == null)
                return;

            var snapshot = BoardExporter.TryBuild(player);
            if (snapshot == null)
                return;

            var takeAt = BoardExporter.ExtractTakeFlagsFromSelections(wordTiles);
            if (takeAt.Count > 0)
                BoardExporter.ApplyTakeFlags(snapshot, takeAt);

            BoardExporter.ApplyCardMetadataFromSelections(snapshot, wordTiles);

            var suitedOnPath = BoardExporter.CountSuitedCardsOnSelections(wordTiles);
            _scoringContextExtras["bicycle_suited_on_path"] = suitedOnPath.ToString();

            _submitBoardSnapshot = snapshot;
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
                foreach (var kv in _scoringContextExtras)
                    extras[kv.Key] = kv.Value;
                var submitPlayer = RunStateExporter.GetPlayerForUpdate();
                MismatchExporter.ExportIfMismatch(
                    _suggestion,
                    _word,
                    _path,
                    actualScore,
                    _actualTrace,
                    _boardFingerprint,
                    _loadoutFingerprint,
                    extras,
                    _submitMethod,
                    submitPlayer,
                    _submitBoardSnapshot
                );
            }
            catch (System.Exception ex)
            {
                MelonLogger.Error("Scoring capture failed: " + ex);
            }
            finally
            {
                _active = false;
                _submitBoardSnapshot = null;
                CalculateOverallScorePatch.LastCalculatedSteps = null;
            }
        }
    }
}
