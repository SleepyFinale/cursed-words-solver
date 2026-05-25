using System.Collections.Generic;
using MelonLoader;

namespace CursedWordsSolverCompanion
{
    public static class ScoringCaptureSession
    {
        private static bool _active;
        private static LastSuggestion _suggestion;
        private static string _word;
        private static List<int> _path;
        private static string _submitMethod;
        private static List<Dictionary<string, object>> _actualTrace;
        private static List<Dictionary<string, object>> _roundTrace;
        private static string _boardFingerprint;
        private static string _loadoutFingerprint;
        private static Dictionary<string, string> _scoringContextExtras =
            new Dictionary<string, string>();
        private static BoardSnapshot _submitBoardSnapshot;
        private static BoardSnapshot _boardAtSubmit;
        private static List<ConsumableRackTileSnapshot> _rackBefore;
        private static List<ConsumablePlacementRecord> _consumablePlacements;

        public static bool IsActive
        {
            get { return _active; }
        }

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
            _roundTrace = null;
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
            _boardAtSubmit = BoardExporter.TryBuild(player);
            _rackBefore = ConsumableRackExporter.Export(player);
            _consumablePlacements = ConsumablePlacementTracker.DrainPlacementsSinceLastSubmit();

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
            }
            else if (_suggestion != null)
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

            if (!_active)
                return;
        }

        /// <summary>
        /// After each submit, store the submitted word's first letter for the next word's Bento Box check.
        /// </summary>
        private static void PersistLastSubmittedWordFirstLetter()
        {
            var letter = ScoringContextCapture.FirstLetterFromSubmittedWord(
                _word,
                _path,
                _submitBoardSnapshot ?? _boardAtSubmit
            );
            if (string.IsNullOrEmpty(letter))
                return;

            _scoringContextExtras["previous_word_first_letter"] = letter;
            TryPersistScoringContextExtras();
        }

        /// <summary>
        /// Write scoring-time extras into run_state.json so F8 sees them before the next submit.
        /// </summary>
        public static void TryPersistScoringContextExtras()
        {
            if (_scoringContextExtras == null || _scoringContextExtras.Count == 0)
                return;

            try
            {
                RunStateExporter.TryMergeExtrasKeys(_scoringContextExtras);
            }
            catch
            {
                // ignore — F7 full export still available
            }
        }

        /// <summary>Overlay scoring-time extras onto a snapshot before post-submit merge.</summary>
        public static void MergeScoringContextIntoExtras(Dictionary<string, string> target)
        {
            if (target == null || _scoringContextExtras == null)
                return;

            foreach (var kv in _scoringContextExtras)
                target[kv.Key] = kv.Value ?? "";
        }

        public static void OnScoreStepsCalculated(List<ScoreCalcVizInfo> steps)
        {
            if (steps == null)
                return;

            _roundTrace = ScoringTraceCollector.SerializeSteps(steps);
            if (_active)
                _actualTrace = _roundTrace;
        }

        public static void OnSubmitWordTiles(List<TileSelection> wordTiles)
        {
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
            try
            {
                PersistLastSubmittedWordFirstLetter();

                var actualScore = ComputeActualScore();
                var submitPlayer = RunStateExporter.GetPlayerForUpdate();
                var runState = RunStateExporter.CaptureRunState(submitPlayer);
                var rackAfter = ConsumableRackExporter.Export(submitPlayer);

                var extras = RunStateExporter.BuildExtrasSnapshot();
                foreach (var kv in _scoringContextExtras)
                    extras[kv.Key] = kv.Value;

                var ctx = new RoundCaptureContext
                {
                    SubmitMethod = _submitMethod,
                    SubmittedWord = _word,
                    SubmittedPath = _path,
                    Suggestion = _suggestion,
                    ActualScore = actualScore,
                    ActualTrace = _roundTrace,
                    BoardFingerprint = _boardFingerprint,
                    LoadoutFingerprint = _loadoutFingerprint,
                    BoardAtSubmit = _boardAtSubmit,
                    SubmitBoardSnapshot = _submitBoardSnapshot,
                    RackBefore = _rackBefore,
                    RackAfter = rackAfter,
                    ConsumablePlacements = _consumablePlacements,
                    RunState = runState,
                    ScoringExtras = extras,
                    CaptureActive = _active,
                };

                RoundLogExporter.EnsurePrefs();
                RoundLogExporter.ExportRound(ctx);

                if (_active)
                {
                    if (_submitBoardSnapshot != null)
                        RunStateExporter.TryMergeSubmitBoardMetadata(_submitBoardSnapshot);

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

                ConsumablePlacementTracker.ResetAfterSubmit(_boardAtSubmit);
            }
            catch (System.Exception ex)
            {
                MelonLogger.Error("Submit capture failed: " + ex);
            }
            finally
            {
                _active = false;
                _submitBoardSnapshot = null;
                CalculateOverallScorePatch.LastCalculatedSteps = null;
            }
        }

        private static int ComputeActualScore()
        {
            if (CalculateOverallScorePatch.LastCalculatedSteps == null)
                return 0;

            try
            {
                var packet = ScoreCalculation.GetScoreFromScoreCalcInfo(
                    CalculateOverallScorePatch.LastCalculatedSteps
                );
                return (int)ScoringTraceCollector.ScorePacketToLong(packet);
            }
            catch
            {
                return 0;
            }
        }
    }
}
