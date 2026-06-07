using System;
using System.Collections.Generic;
using MelonLoader;

namespace CursedWordsSolverCompanion
{
    public static class ScoringCaptureSession
    {
        private static bool _active;
        private static bool _captureCandidate;
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
            _captureCandidate = false;
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
            if (!string.IsNullOrEmpty(_loadoutFingerprint))
                _scoringContextExtras["loadout_fingerprint"] = _loadoutFingerprint;
            _boardAtSubmit = BoardExporter.TryBuild(player);
            _rackBefore = ConsumableRackExporter.Export(player);
            _consumablePlacements = ConsumablePlacementTracker.DrainPlacementsSinceLastSubmit();

            var birthdayBonus = RunStateExporter.TryGetBirthdayCakeBonus(player);
            if (birthdayBonus >= 0)
                _scoringContextExtras["birthday_cake_bonus"] = birthdayBonus.ToString();

            var targetNumber = RunStateExporter.TryGetLuckyDiceTargetNumber(player);
            if (targetNumber >= 0)
                _scoringContextExtras["target_number"] = targetNumber.ToString();

            var boardMatchesSuggestion = _suggestion != null
                && ConsumablePlacementHelper.BoardFingerprintMatchesSuggestion(
                    _suggestion,
                    _boardFingerprint
                );

            if (boardMatchesSuggestion == false && _suggestion != null)
            {
                MelonLogger.Warning(
                    "Solver suggestion is stale (board changed since F8). "
                        + "Press F7 then F8 on this board before using the overlay or score capture."
                );
            }

            var f8Seq = "";
            try
            {
                if (_suggestion != null && _suggestion.f8_sequence > 0)
                    f8Seq = " f8#" + _suggestion.f8_sequence;
            }
            catch
            {
                // optional
            }

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
                _captureCandidate = true;
            }
            else if (_suggestion != null)
            {
                CompanionDiagnostics.LogVerbose(
                    "Scoring capture skipped"
                        + f8Seq
                        + ": "
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
            RunStateExporter.CachePreviousWordsForExport(previousWords);
            var captured = ScoringContextCapture.ExtractFromPreviousWords(previousWords);
            var letterCounts = ScoringContextCapture.ResolveMutatingDnaLetterCounts(
                player,
                previousWords
            );
            captured["mutating_dna_letter_counts"] =
                ScoringContextCapture.SerializeLetterCounts(letterCounts);

            var telescopeExtras = RunStateExportFill.BuildTelescopeEncounterExtras(
                previousWords,
                player
            );
            foreach (var kv in telescopeExtras)
                captured[kv.Key] = kv.Value;

            foreach (var kv in captured)
                _scoringContextExtras[kv.Key] = kv.Value;

            if (telescopeExtras != null && telescopeExtras.Count > 0)
                TryPersistScoringContextExtras();

            if (_captureCandidate)
            {
                _captureCandidate = false;
                TryActivateCaptureFromScoringContext(player, captured);
            }
        }

        private static void TryActivateCaptureFromScoringContext(
            Player player,
            Dictionary<string, string> scoringExtras
        )
        {
            if (_suggestion == null || player == null)
                return;

            var liveExtras = RunStateExporter.BuildExtrasSnapshot();
            var authoritativeExtras = RunStateExportFill.BuildScoringContextWorkflowExtras(
                player,
                liveExtras,
                scoringExtras
            );

            SuggestionMatcher.TrySyncWorkflowExtrasToProjected(
                _suggestion,
                authoritativeExtras
            );
            var f8Extras = ExtrasDiffHelper.ExtrasFromRunStateObject(
                _suggestion?.run_state_snapshot
            );
            var staleCtx = RunStateExporter.BuildStaleF8Context(player);
            var diff = ExtrasDiffHelper.DiffExtras(f8Extras, authoritativeExtras);
            var workflowStale = ExtrasDiffHelper.DescribeStaleF8WorkflowDrift(
                diff,
                staleCtx
            );
            if (!string.IsNullOrEmpty(workflowStale))
            {
                MelonLogger.Warning(workflowStale);
                SuggestionMatcher.TryClearLastSuggestionAfterSubmit();
                _active = false;
                return;
            }

            ExtrasDiffHelper.LogStaleF8DriftWarnings(
                f8Extras,
                authoritativeExtras,
                staleCtx
            );

            _active = true;
            var f8Seq = "";
            try
            {
                if (_suggestion.f8_sequence > 0)
                    f8Seq = " f8#" + _suggestion.f8_sequence;
            }
            catch
            {
                // optional
            }

            MelonLogger.Msg(
                "Scoring capture: tracking suggested word '"
                    + _word
                    + "' (predicted "
                    + _suggestion.predicted_score.ToString()
                    + " pts)"
                    + f8Seq
            );
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

        /// <summary>
        /// Keys written from live pin via TryMergeBicycleExtrasAfterScore — do not let
        /// derived capture values overwrite pin WordScoreBonus in run_state.json.
        /// </summary>
        private static readonly string[] BicyclePinExtrasKeys =
        {
            "bicycle_word_score_bonus",
            "cards_submitted",
        };

        /// <summary>
        /// After submit, BuildExtrasSnapshot reflects live encounter state; do not let
        /// pre-word scoring-context extras overwrite these keys.
        /// </summary>
        private static readonly string[] PostSubmitLiveExtrasKeys =
        {
            "historic_words",
            "red_tiles_used_encounter",
        };

        private static readonly string[] WorkflowExtrasPreserveKeys =
        {
            "previous_word_first_letter",
            "historic_words",
            "mutating_dna_letter_counts",
        };

        private static bool IsWorkflowExtrasPreserveKey(string key)
        {
            if (string.IsNullOrEmpty(key))
                return false;
            foreach (var preserveKey in WorkflowExtrasPreserveKeys)
            {
                if (string.Equals(key, preserveKey, StringComparison.OrdinalIgnoreCase))
                    return true;
            }
            return false;
        }

        /// <summary>Overlay scoring-time extras onto a snapshot before post-submit merge.</summary>
        public static void MergeScoringContextIntoExtras(Dictionary<string, string> target)
        {
            if (target == null || _scoringContextExtras == null)
                return;

            foreach (var kv in _scoringContextExtras)
            {
                if (IsBicyclePinExtraKey(kv.Key))
                    continue;
                if (IsPostSubmitLiveExtraKey(kv.Key) && ShouldKeepPostSubmitLiveExtra(target, kv.Key))
                    continue;
                target[kv.Key] = kv.Value ?? "";
            }
        }

        private static bool IsPostSubmitLiveExtraKey(string key)
        {
            if (string.IsNullOrEmpty(key))
                return false;
            foreach (var liveKey in PostSubmitLiveExtrasKeys)
            {
                if (string.Equals(key, liveKey, StringComparison.OrdinalIgnoreCase))
                    return true;
            }
            return false;
        }

        private static bool ShouldKeepPostSubmitLiveExtra(
            Dictionary<string, string> target,
            string key
        )
        {
            if (target == null || string.IsNullOrEmpty(key))
                return false;
            string liveVal;
            if (!target.TryGetValue(key, out liveVal) || string.IsNullOrEmpty(liveVal))
                return false;
            if (string.Equals(key, "historic_words", StringComparison.OrdinalIgnoreCase))
                return RunStateExportFill.HistoricJsonRedTileCountSum(liveVal)
                    >= RunStateExportFill.HistoricJsonRedTileCountSum(
                        _scoringContextExtras != null
                            && _scoringContextExtras.TryGetValue(key, out var ctxVal)
                            ? ctxVal
                            : null
                    );
            return true;
        }

        private static bool IsBicyclePinExtraKey(string key)
        {
            if (string.IsNullOrEmpty(key))
                return false;
            foreach (var blocked in BicyclePinExtrasKeys)
            {
                if (string.Equals(key, blocked, StringComparison.OrdinalIgnoreCase))
                    return true;
            }
            return false;
        }

        /// <summary>
        /// Scoring-time extras for round logs / mismatch export (pre-word Bicycle, no next-word letter).
        /// </summary>
        private static Dictionary<string, string> BuildExportExtras()
        {
            var extras = new Dictionary<string, string>();
            if (_scoringContextExtras != null)
            {
                foreach (var kv in _scoringContextExtras)
                    extras[kv.Key] = kv.Value ?? "";
            }

            var live = RunStateExporter.BuildExtrasSnapshot();
            if (live == null)
                return extras;

            foreach (var kv in live)
            {
                if (IsBicyclePinExtraKey(kv.Key))
                {
                    if (!extras.ContainsKey(kv.Key))
                        extras[kv.Key] = kv.Value ?? "";
                    continue;
                }
                if (
                    IsWorkflowExtrasPreserveKey(kv.Key)
                    && extras.ContainsKey(kv.Key)
                    && !string.IsNullOrEmpty(extras[kv.Key])
                )
                    continue;
                extras[kv.Key] = kv.Value ?? "";
            }

            ApplyBicyclePreWordRewindFallback(extras);
            ApplyF8SnapshotBicycleOverlay(extras);

            return extras;
        }

        private static bool IsBicycleFamilySlug(string slug)
        {
            if (string.IsNullOrEmpty(slug))
                return false;
            var s = slug.ToLowerInvariant();
            return s == "bicycle" || s == "bones_the_dog" || s == "bones";
        }

        private static int TryGetF8SnapshotBicycleAcc()
        {
            if (_suggestion?.run_state_snapshot == null)
                return -1;

            var f8Extras = ExtrasDiffHelper.ExtrasFromRunStateObject(
                _suggestion.run_state_snapshot
            );
            string raw;
            if (
                f8Extras.TryGetValue("bicycle_word_score_bonus", out raw)
                && int.TryParse(raw, out var bonus)
                && bonus >= 0
            )
                return bonus;
            if (
                f8Extras.TryGetValue("cards_submitted", out raw)
                && int.TryParse(raw, out bonus)
                && bonus >= 0
            )
                return bonus;
            return -1;
        }

        private static int GetSuitedCountFromContext()
        {
            var suited = 0;
            if (
                _scoringContextExtras != null
                && _scoringContextExtras.TryGetValue("bicycle_suited_on_path", out var suitedRaw)
            )
                int.TryParse(suitedRaw, out suited);
            return suited;
        }

        /// <summary>
        /// Use F8 embed pre-word acc for export when capture matches (prediction baseline).
        /// </summary>
        private static void ApplyF8SnapshotBicycleOverlay(Dictionary<string, string> extras)
        {
            if (!_active || _suggestion == null || extras == null)
                return;

            if (
                !SuggestionMatcher.MatchesSuggestion(
                    _suggestion,
                    _word,
                    _path,
                    _boardFingerprint,
                    _loadoutFingerprint
                )
            )
                return;

            var f8Acc = TryGetF8SnapshotBicycleAcc();
            if (f8Acc < 0)
                return;

            extras["bicycle_word_score_bonus"] = f8Acc.ToString();
            extras["cards_submitted"] = f8Acc.ToString();
        }

        /// <summary>
        /// When step capture missed, rewind live post-word pin to pre-word using suited count.
        /// </summary>
        private static void ApplyBicyclePreWordRewindFallback(Dictionary<string, string> extras)
        {
            if (extras == null)
                return;

            string capturedRaw;
            if (
                extras.TryGetValue("bicycle_word_score_bonus", out capturedRaw)
                && !string.IsNullOrEmpty(capturedRaw)
            )
            {
                var livePin = RunStateExporter.TryGetLiveBicycleWordScoreBonus();
                int captured;
                if (livePin >= 0 && int.TryParse(capturedRaw, out captured) && captured < livePin)
                    return;
            }

            var liveBonus = RunStateExporter.TryGetLiveBicycleWordScoreBonus();
            if (liveBonus < 0)
                return;

            var perCard = RunStateExporter.TryGetBicyclePerCardRate();
            if (perCard <= 0)
                perCard = 1;

            var suited = 0;
            if (extras.TryGetValue("bicycle_suited_on_path", out var suitedRaw))
                int.TryParse(suitedRaw, out suited);

            if (suited <= 0)
            {
                var f8Acc = TryGetF8SnapshotBicycleAcc();
                if (f8Acc >= 0 && liveBonus > f8Acc)
                {
                    var delta = liveBonus - f8Acc;
                    if (delta > 0 && delta % perCard == 0)
                        suited = delta / perCard;
                }
            }

            if (suited <= 0)
                return;

            var pre = liveBonus - perCard * suited;
            if (pre < 0 || pre >= liveBonus)
                return;

            extras["bicycle_word_score_bonus"] = pre.ToString();
            extras["cards_submitted"] = pre.ToString();
        }

        public static void OnScoreStepsCalculated(List<ScoreCalcVizInfo> steps)
        {
            if (steps == null)
                return;

            CaptureBicycleAccumulatorFromSteps(steps);
            CaptureNeapolitanPercentFromSteps(steps);
            CaptureRareItemCountFromSteps(steps);
            CaptureSnapshotCopyFromSteps(steps);
            TryPersistScoringContextExtras();
            _roundTrace = ScoringTraceCollector.SerializeSteps(steps, _path);
            if (_active)
                _actualTrace = _roundTrace;
        }

        /// <summary>
        /// Prefer the scoring engine's computed Bicycle bonus (WordScoreBonus after increment)
        /// over reflection reads, which can be stale for the next F8 prediction.
        /// </summary>
        private static void CaptureBicycleAccumulatorFromSteps(List<ScoreCalcVizInfo> steps)
        {
            if (steps == null || _scoringContextExtras == null)
                return;

            try
            {
                if (TryCaptureBicycleFromSteps(steps))
                    return;

                CaptureBicycleFromLivePinFallback();
            }
            catch
            {
                // best-effort only
            }
        }

        private static bool TryCaptureBicycleFromSteps(List<ScoreCalcVizInfo> steps)
        {
            for (var i = 0; i < steps.Count; i++)
            {
                var step = steps[i];
                if (step?.WordBonus == null)
                    continue;

                if (step.WordBonus.IsMultiplicative || step.WordBonus.IsPoison)
                    continue;

                var score = step.WordBonus.Bonus != null ? step.WordBonus.Bonus.Score : 0L;
                if (score <= 0L)
                    continue;

                if (step.RelevantItem != null)
                {
                    if (RunStateExporter.IsBicyclePinItem(step.RelevantItem))
                    {
                        StorePreWordBicycleAccumulator(score);
                        return true;
                    }

                    var itemId = RunStateExporter.Slugify(
                        step.RelevantItem.ArtFileName,
                        step.RelevantItem.Name
                    );
                    if (IsBicycleFamilySlug(itemId))
                    {
                        StorePreWordBicycleAccumulator(score);
                        return true;
                    }
                }

                var suited = GetSuitedCountFromContext();
                var perCard = suited > 0 ? RunStateExporter.TryGetBicyclePerCardRate() : 0;
                if (perCard <= 0)
                    perCard = 1;
                if (suited > 0 && score == perCard * suited)
                {
                    StorePreWordBicycleAccumulator(score);
                    return true;
                }
            }

            return false;
        }

        /// <summary>
        /// Derive pre-word pin acc from live post-score pin when trace steps did not capture.
        /// </summary>
        private static void CaptureBicycleFromLivePinFallback()
        {
            if (_scoringContextExtras == null)
                return;
            if (_scoringContextExtras.ContainsKey("bicycle_word_score_bonus"))
                return;

            var suited = GetSuitedCountFromContext();
            var perCard = RunStateExporter.TryGetBicyclePerCardRate();
            if (perCard <= 0)
                perCard = 1;

            if (suited <= 0)
            {
                var f8Acc = TryGetF8SnapshotBicycleAcc();
                var liveBonus = RunStateExporter.TryGetLiveBicycleWordScoreBonus();
                if (f8Acc >= 0 && liveBonus > f8Acc)
                {
                    var delta = liveBonus - f8Acc;
                    if (delta > 0 && delta % perCard == 0)
                        suited = delta / perCard;
                }
            }

            if (suited <= 0)
                return;

            var pinBonus = RunStateExporter.TryGetLiveBicycleWordScoreBonus();
            if (pinBonus < 0)
                return;

            var pre = pinBonus - perCard * suited;
            if (pre < 0)
                return;

            _scoringContextExtras["bicycle_word_score_bonus"] = pre.ToString();
            _scoringContextExtras["cards_submitted"] = pre.ToString();
        }

        private static void StorePreWordBicycleAccumulator(long score)
        {
            if (_scoringContextExtras == null)
                return;

            var stored = score;
            var suited = 0;
            if (
                _scoringContextExtras.TryGetValue(
                    "bicycle_suited_on_path",
                    out var suitedRaw
                )
            )
                int.TryParse(suitedRaw, out suited);

            var perCard = suited > 0 ? RunStateExporter.TryGetBicyclePerCardRate() : 0;
            if (perCard > 0 && suited > 0)
            {
                var pre = score - perCard * suited;
                if (pre >= 0L)
                    stored = pre;
            }

            var pinBonus = RunStateExporter.TryGetLiveBicycleWordScoreBonus();
            if (pinBonus >= 0 && perCard > 0 && suited > 0)
            {
                var preFromPin = pinBonus - perCard * suited;
                if (preFromPin >= 0L)
                    stored = preFromPin;
            }

            _scoringContextExtras["bicycle_word_score_bonus"] = stored.ToString();
            _scoringContextExtras["cards_submitted"] = stored.ToString();
        }

        /// <summary>
        /// Capture Neapolitan's multiplicative WordBonus percent for the next F8 prediction.
        /// </summary>
        private static void CaptureNeapolitanPercentFromSteps(List<ScoreCalcVizInfo> steps)
        {
            if (steps == null || _scoringContextExtras == null)
                return;

            try
            {
                for (var i = 0; i < steps.Count; i++)
                {
                    var step = steps[i];
                    if (step?.RelevantItem == null || step.WordBonus == null)
                        continue;

                    var itemId = RunStateExporter.Slugify(
                        step.RelevantItem.ArtFileName,
                        step.RelevantItem.Name
                    );
                    if (!string.Equals(itemId, "neapolitan", StringComparison.OrdinalIgnoreCase))
                        continue;

                    if (!step.WordBonus.IsMultiplicative || step.WordBonus.IsPoison)
                        continue;

                    var bonus = step.WordBonus.Bonus != null ? step.WordBonus.Bonus.Score : 0L;
                    if (bonus <= 0L)
                        continue;

                    var percent = bonus.ToString();
                    _scoringContextExtras["neapolitan_percent"] = percent;
                    _scoringContextExtras["neapolitan_percent_last_known"] = percent;
                    break;
                }
            }
            catch
            {
                // best-effort only
            }
        }

        /// <summary>
        /// Persist Snapshot's grid-start copy target for F8 replay (slug + copy level).
        /// </summary>
        private static void CaptureSnapshotCopyFromSteps(List<ScoreCalcVizInfo> steps)
        {
            if (_scoringContextExtras == null)
                return;

            try
            {
                var player = RunStateExporter.GetPlayerForUpdate();
                if (player == null)
                    return;

                var temp = new RunStateSnapshot { extras = _scoringContextExtras };
                RunStateExporter.FillSnapshotCopyExtras(temp, player);

                if (steps == null)
                    return;

                for (var i = 0; i < steps.Count; i++)
                {
                    var step = steps[i];
                    if (step?.RelevantItem == null)
                        continue;

                    var itemId = RunStateExporter.Slugify(
                        step.RelevantItem.ArtFileName,
                        step.RelevantItem.Name
                    );
                    if (!string.Equals(itemId, "snapshot", StringComparison.OrdinalIgnoreCase))
                        continue;

                    var hadSlug =
                        _scoringContextExtras.ContainsKey("snapshot_copy_slug")
                        && !string.IsNullOrEmpty(
                            _scoringContextExtras["snapshot_copy_slug"]
                        );

                    if (hadSlug)
                        return;

                    if (step.WordBonus != null && !step.WordBonus.IsMultiplicative)
                    {
                        var bonus = step.WordBonus.Bonus != null
                            ? step.WordBonus.Bonus.Score
                            : 0L;
                        if (bonus == 120L)
                        {
                            _scoringContextExtras["snapshot_copy_slug"] = "dusty_coffin";
                            _scoringContextExtras["snapshot_copy_level"] = "1";
                            ExportDiagnostics.SetSnapshotCopySource("trace_fallback");
                            CompanionDiagnostics.LogVerboseWarning(
                                "Snapshot copy inferred as dusty_coffin from trace (+120 word bonus)"
                            );
                        }
                    }
                    break;
                }
            }
            catch
            {
                // best-effort only
            }
        }

        /// <summary>
        /// Capture Steak's live WordBonus percent for F8 (wiki: ×1 + 0.25 per rare; game may differ).
        /// </summary>
        private static void CaptureRareItemCountFromSteps(List<ScoreCalcVizInfo> steps)
        {
            if (steps == null || _scoringContextExtras == null)
                return;

            try
            {
                for (var i = 0; i < steps.Count; i++)
                {
                    var step = steps[i];
                    if (step?.RelevantItem == null || step.WordBonus == null)
                        continue;

                    var itemId = RunStateExporter.Slugify(
                        step.RelevantItem.ArtFileName,
                        step.RelevantItem.Name
                    );
                    if (!string.Equals(itemId, "steak", StringComparison.OrdinalIgnoreCase))
                        continue;

                    if (!step.WordBonus.IsMultiplicative || step.WordBonus.IsPoison)
                        continue;

                    var bonus = step.WordBonus.Bonus != null ? step.WordBonus.Bonus.Score : 0L;
                    if (bonus < 100L)
                        continue;

                    _scoringContextExtras["steak_word_bonus_percent"] = bonus.ToString();
                    break;
                }
            }
            catch
            {
                // best-effort only
            }
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
                var actualScore = ComputeActualScore();
                var submitPlayer = RunStateExporter.GetPlayerForUpdate();
                var runState = RunStateExporter.CaptureRunState(submitPlayer);
                var rackAfter = ConsumableRackExporter.Export(submitPlayer);

                var extras = BuildExportExtras();

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

                PersistLastSubmittedWordFirstLetter();

                ConsumablePlacementTracker.ResetAfterSubmit(_boardAtSubmit);
            }
            catch (System.Exception ex)
            {
                MelonLogger.Error("Submit capture failed: " + ex);
            }
            finally
            {
                _active = false;
                _captureCandidate = false;
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
