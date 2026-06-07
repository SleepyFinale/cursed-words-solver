using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

public class EncounterController : MonoBehaviour
{
	[SerializeField]
	private EncounterSummaryDisplayController _encounterSummaryDisplayController;

	[SerializeField]
	private GridLayoutController _gridLayoutController;

	[SerializeField]
	private CurrentWordController _currentWordController;

	[SerializeField]
	private ScoreCalculationVisualController _scoreCalculationVisualController;

	[SerializeField]
	private WordHistoryController _wordHistorycontroller;

	[SerializeField]
	private RewardsController _rewardsController;

	[SerializeField]
	private ParticleSystem _sellIndicatorPS;

	[SerializeField]
	private TransitionController _transitionController;

	[SerializeField]
	private EndGameCanvasController _endGameCanvasController;

	[SerializeField]
	private DialogueController _dialogueController;

	[SerializeField]
	private AreaDisplayController _areaDisplayController;

	[SerializeField]
	private UnlocksBannerController _unlocksBannerController;

	[SerializeField]
	private TileSelectionManager _tileSelectionManager;

	[SerializeField]
	private SpecialEventsCanvasController _specialEventsCanvasController;

	[SerializeField]
	private ChallengeDialogueController _challengeDialogueController;

	[SerializeField]
	private CurseFliesCanvasController _curseFliesCanvasController;

	[SerializeField]
	private MichaelVolumeController _michaelVolumeController;

	[SerializeField]
	private MotionWashColourChanger _motionWashColourChanger;

	private RampingController _ramper;

	[SerializeField]
	private LayoutGroup _leftPanelLayoutGroup;

	[SerializeField]
	private RectTransform _leftPanelRT;

	[SerializeField]
	private UIElementGenericAnimations _gridNumberGenericAnimations;

	[SerializeField]
	private GameObject _characterInfoPanelPrefab;

	[SerializeField]
	private EnemyVisualController _leftPanelBossVisualController;

	private PlayerCharacterController _rightPanelCharacterController;

	private TopBarController _topBarController;

	[SerializeField]
	private GameObject _rerollButtonObject;

	[SerializeField]
	private TextMeshProUGUI _rerollTMP;

	[SerializeField]
	private GameObject _rerollParent;

	[SerializeField]
	private GameObject _rerollLine;

	[SerializeField]
	private GameObject _wordHistorySectionObject;

	[SerializeField]
	private GameObject _gridNumberSectionObject;

	[Header("Michael Fight")]
	[SerializeField]
	private GameObject _michaelDraftVisualControllerGO;

	[SerializeField]
	private MichaelDraftVisualController _michaelDraftVisualController;

	[SerializeField]
	private MichaelSticker[] _michaelStickers;

	[SerializeField]
	private GameObject _ESolveButtonParent;

	[SerializeField]
	private GameObject _creditsGO;

	[SerializeField]
	private CreditsRoll _creditsRoll;

	private List<BossModifier> _bossModifiers = new List<BossModifier>();

	private List<BossModifier> _currentDraftBossModifiers = new List<BossModifier>();

	private BossModifier _draftedBossModifier;

	private GridData _gridData;

	private GridData _puzzleGrid;

	private List<Vector2Int> _pathThroughPuzzleGrid;

	private TileGridTransitions _tileGridTransitions;

	private List<HistoricWord> _previousWords = new List<HistoricWord>();

	private Dictionary<string, int> _earningsBreakdown = new Dictionary<string, int>();

	private EncounterThreadStage _encounterThreadStage;

	private ScorePacket _totalTarget;

	private ScorePacket _remainingTarget;

	private int _remainingGrids;

	private int _totalGridsPerRound;

	private int _rerollsForEncounter;

	private int _rerollReminderDelay = 10;

	private int _rerollTracker;

	public bool TwinkleToesSwapAvailable;

	private bool _awaitingForcedSell;

	private bool _shownChallengeDialogue;

	private bool _enteredWithNoMoney;

	private bool _showLongEnding;

	private int _piggyBankSavings;

	private Coroutine _speedrunTimeCheckCoroutine;

	[Header("Animations")]
	[SerializeField]
	private LensDistortionShake _lensDistortionShake;

	[SerializeField]
	private ScoreAnimations _scoreAnimations;

	[SerializeField]
	private SubmittedScoreAnimations _submittedScoreAnimations;

	[SerializeField]
	private SubmittedScoreAnimations _bossSubmittedScoreAnimations;

	[SerializeField]
	private Animator _submitButtonAnimator;

	[Header("Score Tokens")]
	[SerializeField]
	private Transform _scoreTokenParent;

	[SerializeField]
	private GameObject _scoreTokenPrefab;

	private void Start()
	{
		SettingsMenuController.IsOpen = false;
		_ramper = GetComponent<RampingController>();
		if (GameStatics.Challenge != null && GameStatics.GetPlayer().MyCharacter == null)
		{
			Player player = new Player();
			player.SetCharacter(GameStatics.Challenge.GetCharacter());
			if (GameStatics.Challenge is ColourSwap)
			{
				player.MyCharacter.CharacterItem.RandomiseRelevantColours();
				player.CurrentRunProgress.AvailableColours = new List<TileType>
				{
					TileType.Red,
					TileType.Blue,
					TileType.Void,
					TileType.Shiny,
					TileType.Purple,
					TileType.Gold,
					TileType.White,
					TileType.Green,
					TileType.Cactus,
					TileType.Pink
				};
			}
			player.CurrentRunProgress.Challenge = GameStatics.Challenge;
			player.CurrentRunProgress.SetNodeType(NodeType.EncounterFirst);
			player.CurrentRunProgress.SetStage(1);
			player.CurrentRunProgress.GetRandomBossDrafts();
			player.PopulateInventoryFromChallenge();
			GameStatics.SetPlayer(player);
			if (GameStatics.Challenge is ColourSwap)
			{
				_motionWashColourChanger.StartColourCoroutine();
			}
			GameStatics.Challenge = null;
		}
		if (GameStatics.GetPlayer().CurrentRunProgress.Challenge is ColourSwap || GameStatics.GetPlayer().GetUnpackedItemsOfType(typeof(CanOfBeans)).Count > 0)
		{
			_motionWashColourChanger.StartColourCoroutine();
		}
		Player player2 = GameStatics.GetPlayer();
		if (CharacterInfoPanel.SingletonObject == null)
		{
			UnityEngine.Object.Instantiate(_characterInfoPanelPrefab).GetComponentInChildren<CameraFinder>().Initialize();
		}
		_topBarController = CharacterInfoPanel.SingletonObject.transform.parent.GetComponentInChildren<TopBarController>();
		_rightPanelCharacterController = CharacterInfoPanel.SingletonObject.GetComponentInChildren<PlayerCharacterController>();
		if (player2.CurrentRunProgress.Challenge is SpeedrunChallenge || player2.CurrentRunProgress.CurrentRunStatistics.IsSpeedrunMode)
		{
			_topBarController.SetTimerColor(GameStatics.GetSpeedrunTimerColor());
			bool flag = player2.CurrentRunProgress.Challenge is SpeedrunChallenge;
			if (player2.CurrentRunProgress.CurrentRunStatistics.Timer > 0.1f && _topBarController.GetCurrentTime() < 0.1f)
			{
				float newTime = (flag ? ((float)SpeedrunChallenge.TimeLimitInSeconds - player2.CurrentRunProgress.CurrentRunStatistics.Timer) : player2.CurrentRunProgress.CurrentRunStatistics.Timer);
				_topBarController.ShowTime(newTime, flag);
				_topBarController.SetCurrentTime(player2.CurrentRunProgress.CurrentRunStatistics.Timer);
			}
			else if (_topBarController.GetCurrentTime() > 0.1f)
			{
				player2.CurrentRunProgress.CurrentRunStatistics.Timer = _topBarController.GetCurrentTime();
			}
			else
			{
				float newTime2 = (flag ? SpeedrunChallenge.TimeLimitInSeconds : 0);
				_topBarController.ShowTime(newTime2, flag);
			}
		}
		if (player2.CurrentRunProgress.GetCurrentNodeType() != NodeType.EncounterFirst || player2.CurrentRunProgress.CurrentStage != 1)
		{
			Player currentRun = SaveManager.GetCurrentRun();
			if (currentRun != null && player2.GUID != currentRun.GUID)
			{
				SaveManager.SaveRunHistory(currentRun);
			}
			SaveManager.SaveCurrentRun();
		}
		if (player2.CurrentRunProgress.GetCurrentNodeType() == NodeType.EncounterFirst)
		{
			if (player2.CurrentRunProgress.GetStage() == 1)
			{
				SaveManager.SetPiggyBankMoneyToZero();
			}
			else
			{
				_piggyBankSavings = 2 * SaveManager.GetMoneyFromPiggyBank();
				player2.ChangeMoney(_piggyBankSavings);
			}
		}
		Debug.Log($"Current node type = {player2.CurrentRunProgress.GetCurrentNodeType()}");
		_enteredWithNoMoney = player2.Money == 0;
		_tileGridTransitions = base.gameObject.AddComponent<TileGridTransitions>();
		_tileGridTransitions.MakeAssignments(_gridLayoutController);
		_areaDisplayController.Populate(player2.CurrentRunProgress.GetCurrentNodeType(), player2.CurrentRunProgress.GetStage());
		Debug.Log($"Current node type = {player2.CurrentRunProgress.GetCurrentNodeType()}");
		StartCoroutine(GameSetup());
	}

	public IEnumerator GameSetup()
	{
		Player player = GameStatics.GetPlayer();
		Vocabulary.SetActiveLanguageVocabulary(player.CurrentRunProgress.CurrentRunStatistics.Language);
		if (player.CurrentRunProgress.CurrentStage == 6 && player.CurrentRunProgress.GetCurrentNodeType() == NodeType.Boss)
		{
			_showLongEnding = !SaveManager.HasBeatenFinalBoss() || SaveManager.GetIsShowingLongEnding();
			MichaelBoss michael = player.ActiveBossModifiers[0] as MichaelBoss;
			_totalTarget = player.CurrentRunProgress.GetCurrentEncounterTarget();
			_remainingTarget = _totalTarget;
			_rerollsForEncounter = 1;
			_rerollTracker = 0;
			if (michael.ModifierDrafts.Count == 0)
			{
				_encounterSummaryDisplayController.ShowMichael(michael);
				michael.PopulateModifierDrafts();
				_encounterSummaryDisplayController.SetInitialDisplayedTargetValue(_totalTarget);
			}
			if (michael.DraftedModifiers.Exists((BossModifier boss) => boss is DestroyGrid))
			{
				Debug.Log("Clearing destroyed coordinates");
				(michael.DraftedModifiers.Find((BossModifier boss) => boss.GetType() == typeof(DestroyGrid)) as DestroyGrid).DestroyedCoordinates.Clear();
			}
			int draftedCount = michael.DraftedModifiers.Count;
			if (draftedCount < michael.FloorAdjustedModification)
			{
				yield return StartCoroutine(WaitForMichaelFightBossDecision());
				michael.DraftedModifiers.Add(_draftedBossModifier);
				_draftedBossModifier = null;
				_bossModifiers = new List<BossModifier>(michael.DraftedModifiers);
				_submittedScoreAnimations = _bossSubmittedScoreAnimations;
				_encounterSummaryDisplayController.ShowMichael(michael);
				if (draftedCount == 0)
				{
					player.CurrentRunProgress.CurrentRunStatistics.Bosses.AddRange(new List<BossModifier> { michael });
				}
			}
		}
		if (player.CurrentRunProgress.GetCurrentNodeType() == NodeType.None)
		{
			Debug.LogWarning("No node type set; assuming this is debug launching directly into encounter scene. Setting node to encounter.");
			player.CurrentRunProgress.SetNodeType(NodeType.EncounterFirst);
			player.CurrentRunProgress.SetStage(1);
			player.SetCharacter(new WetDennis());
			CharacterInfoPanel.SingletonInventoryVisualController.PopulateAll();
		}
		else if (player.CurrentRunProgress.GetCurrentNodeType() == NodeType.Boss)
		{
			if (!(player.ActiveBossModifiers[0] is MichaelBoss))
			{
				Debug.Log($"Current node type = {player.CurrentRunProgress.GetCurrentNodeType()}");
				_bossModifiers = new List<BossModifier>(player.ActiveBossModifiers);
				if (GameStatics.DevQueueBoss != null)
				{
					GameStatics.DevQueueBoss.SetFloorAdjustedModification(player.CurrentRunProgress.GetStage() - 1, isAscensionModifierActive: false);
					_bossModifiers = new List<BossModifier> { GameStatics.DevQueueBoss };
				}
				player.BossesFaced.AddRange(_bossModifiers.Select((BossModifier boss) => boss.GetType()));
				player.CurrentRunProgress.CurrentRunStatistics.Bosses.AddRange(_bossModifiers);
				_encounterSummaryDisplayController.ShowBoss(_bossModifiers[0]);
				_submittedScoreAnimations = _bossSubmittedScoreAnimations;
				player.ActiveBossModifiers.Clear();
				Debug.Log("The selected boss is... " + _bossModifiers[0].Name + "!");
			}
			if (IsBossModifierActive(typeof(RandomiseItemOrder)))
			{
				ItemObject[] array = UnityEngine.Object.FindObjectsByType<ItemObject>(FindObjectsSortMode.None);
				Debug.Log($"Found {array.Length} itemObjects");
				RandomiseItemOrder obj = (RandomiseItemOrder)GetActiveBossModifierOfType(typeof(RandomiseItemOrder));
				obj.StickersAtStart = player.Stickers;
				obj.StampsAtStart = player.Stamps;
			}
			else if (IsBossModifierActive(typeof(ForcedSell)))
			{
				ForcedSell forcedSell = (ForcedSell)GetActiveBossModifierOfType(typeof(ForcedSell));
				Debug.Log($"Forced sell f a m = {forcedSell.FloorAdjustedModification}");
				if (forcedSell.FloorAdjustedModification == 1 && player.GetAllItems(forItemComparison: true).Exists((Item item) => item.Rarity != ItemRarity.Unique && !item.IsSellingPrevented))
				{
					_awaitingForcedSell = true;
				}
				else if (forcedSell.FloorAdjustedModification == 2 && player.GetStickers(forItemComparison: true).Exists((Item item) => item.Rarity != ItemRarity.Unique && !item.IsSellingPrevented))
				{
					_awaitingForcedSell = true;
				}
			}
		}
		foreach (Item allItemsIncludingNestedItem in player.GetAllItemsIncludingNestedItems(forItemComparison: false))
		{
			allItemsIncludingNestedItem.StartOfEncounterSetUp();
		}
		_totalTarget = player.CurrentRunProgress.GetCurrentEncounterTarget();
		_remainingTarget = _totalTarget;
		_rerollsForEncounter = 1;
		if (player.CurrentRunProgress.Challenge is TwoWrongs)
		{
			_encounterSummaryDisplayController.SetInitialDisplayedTargetValue(_totalTarget * -1L);
		}
		else
		{
			_encounterSummaryDisplayController.SetInitialDisplayedTargetValue(_totalTarget);
		}
		_totalGridsPerRound = (IsBossModifierActive(typeof(FewerGrids)) ? (GameStatics.GridsPerRound - GetActiveBossModifierOfType(typeof(FewerGrids)).FloorAdjustedModification) : GameStatics.GridsPerRound);
		foreach (Item item3 in player.GetUnpackedItemsOfType(typeof(Diya)))
		{
			_totalGridsPerRound++;
			if (player.IsHumanBoyFavouriteStamp(item3) && player.GetCharacter().GetCharacterItem().UpgradeableComponents[1].VariableValue > 1)
			{
				for (int i = 0; i < player.GetCharacter().GetCharacterItem().UpgradeableComponents[1].VariableValue - 1; i++)
				{
					_totalGridsPerRound++;
				}
			}
			Item item2 = player.Stickers.ToList().Find((Item item) => item is Overhand);
			if (player.IsOverhandTarget(item3) && item2 != null)
			{
				for (int j = 0; j < item2.UpgradeableComponents[0].VariableValue; j++)
				{
					_totalGridsPerRound++;
				}
			}
		}
		_totalGridsPerRound -= (player.CurrentRunProgress.IsAscensionModifierActive(AscensionLevel.OneFewerGrid) ? 1 : 0);
		_remainingGrids = _totalGridsPerRound;
		_rerollParent.SetActive(value: true);
		_currentWordController.ResetWordAndScoreDisplay();
		ForceRebuildLeftPanelLayout();
		if (!GameStatics.InGameTutorial)
		{
			BuildGrid();
		}
		else
		{
			MusicController.OnGameplayTutorialStart();
		}
		yield return null;
	}

	public IEnumerator WaitForMichaelFightBossDecision()
	{
		MichaelBoss michael = GameStatics.GetPlayer().ActiveBossModifiers[0] as MichaelBoss;
		_encounterSummaryDisplayController.ShowMichael(michael);
		_currentWordController.ResetWordAndScoreDisplay();
		_rerollParent.SetActive(value: false);
		TutorialController component = GetComponent<TutorialController>();
		int draftedCount = michael.DraftedModifiers.Count;
		if (draftedCount == 0)
		{
			michael.PopulateModifierDrafts();
			GeneratePuzzleGrid(5);
			MusicController.OnMichaelIntroducesFinalEncounter();
			if (_showLongEnding)
			{
				yield return StartCoroutine(component.IntroToMichaelFight(michael));
			}
			else
			{
				yield return StartCoroutine(component.MichaelFightReturningQuip(michael));
			}
		}
		else if (_showLongEnding)
		{
			yield return StartCoroutine(component.MichaelFightDraftQuip(michael));
		}
		else
		{
			yield return StartCoroutine(component.MichaelFightReturningQuip(michael));
		}
		_currentDraftBossModifiers.Clear();
		_currentDraftBossModifiers.Add(michael.ModifierDrafts[draftedCount][0]);
		_currentDraftBossModifiers.Add(michael.ModifierDrafts[draftedCount][1]);
		Debug.Log($"Draft {draftedCount + 1} choice between {michael.ModifierDrafts[draftedCount][0].Name} and {michael.ModifierDrafts[draftedCount][1].Name}");
		_michaelDraftVisualControllerGO.SetActive(value: true);
		_michaelDraftVisualController.AssignBossModifiers(_currentDraftBossModifiers);
		while (_draftedBossModifier == null)
		{
			yield return null;
		}
		MusicController.OnBeginMichaelPhase(draftedCount + 1);
		_encounterSummaryDisplayController.SetInitialDisplayedTargetValue(_totalTarget);
		StartCoroutine(_rightPanelCharacterController.IdleCoroutine());
		_encounterSummaryDisplayController.EnemyIdle();
		_michaelStickers[draftedCount].Populate(_draftedBossModifier);
	}

	public void DraftBossModifier(int i)
	{
		_draftedBossModifier = _currentDraftBossModifiers[i];
		Debug.Log("Drafting " + _draftedBossModifier.Name + ".");
	}

	public bool IsBossModifierActive(Type bossModifierType)
	{
		return _bossModifiers.Exists((BossModifier boss) => boss.GetType() == bossModifierType);
	}

	public BossModifier GetActiveBossModifierOfType(Type bossModifierType)
	{
		return _bossModifiers.Find((BossModifier boss) => boss.GetType() == bossModifierType);
	}

	public void SetTotalTarget(int i)
	{
		_totalTarget = new ScorePacket(i);
		_remainingTarget = _totalTarget;
		_encounterSummaryDisplayController.SetInitialDisplayedTargetValue(_totalTarget);
		_currentWordController.ResetWordAndScoreDisplay();
		ForceRebuildLeftPanelLayout();
	}

	public void BuildGrid()
	{
		Debug.Log("Building grid...");
		List<BoardGenVizInfo> list = GenerateGrid(isReroll: false);
		if (list[list.Count - 1].Grid.HasLostChallenge)
		{
			if (GameStatics.GetPlayer().CurrentRunProgress.Challenge is MunchTime)
			{
				StartCoroutine(MunchTimeIsOver());
			}
			else
			{
				StartCoroutine(ShowEndGame(isWin: false, isChallengeLoss: true));
			}
			return;
		}
		_gridLayoutController.GenerateGrid(GetGridDimensions());
		StartCoroutine(TransitionGridIn(list));
		if (!GameStatics.InGameTutorial)
		{
			MusicController.OnNewEncounterGrid(_remainingGrids, _totalGridsPerRound);
		}
	}

	public IEnumerator MunchTimeIsOver()
	{
		ChallengeRun challenge = GameStatics.GetPlayer().CurrentRunProgress.Challenge;
		SetEncounterThreadStage(EncounterThreadStage.ShowingChallengeDialogue);
		if (challenge is MunchTime)
		{
			Debug.Log("Munch Time is over!");
			SetEncounterThreadStage(EncounterThreadStage.ExecutingWordConsequences);
			yield return StartCoroutine(_dialogueController.DialogueEventCoroutine(MunchTime.GameOverQuip, fadeOverTime: true));
		}
		MusicController.OnWinOrLoseEncounter(isWin: false);
		StartCoroutine(ShowEndGame(isWin: false, isChallengeLoss: true));
	}

	public void EndLexographerChallenge(string submittedWord)
	{
		StartCoroutine(LexographerFail(submittedWord));
	}

	public IEnumerator LexographerFail(string submittedWord)
	{
		ChallengeRun challenge = GameStatics.GetPlayer().CurrentRunProgress.Challenge;
		SetEncounterThreadStage(EncounterThreadStage.ShowingChallengeDialogue);
		if (challenge is Lexographer)
		{
			Debug.Log("Lexographed too close to the sun!");
			Lexographer lexographer = (Lexographer)challenge;
			lexographer.GameOverQuip.text = lexographer.GameOverQuip.text.Replace("[SUBMITTED WORD]", submittedWord);
			yield return StartCoroutine(_dialogueController.DialogueEventCoroutine(lexographer.GameOverQuip, fadeOverTime: true));
		}
		MusicController.OnWinOrLoseEncounter(isWin: false);
		StartCoroutine(ShowEndGame(isWin: false, isChallengeLoss: true));
	}

	public IEnumerator SpeedrunTimeCheck()
	{
		while (!(_topBarController.GetCurrentTime() >= (float)SpeedrunChallenge.TimeLimitInSeconds))
		{
			yield return null;
		}
		StopCoroutine(_speedrunTimeCheckCoroutine);
		_topBarController.StopTimerAndGetCurrentTime();
		StartCoroutine(SpeedrunOutOfTime());
	}

	public IEnumerator SpeedrunOutOfTime()
	{
		SetEncounterThreadStage(EncounterThreadStage.ExecutingWordConsequences);
		yield return StartCoroutine(_dialogueController.DialogueEventCoroutine(SpeedrunChallenge.GameOverQuip, fadeOverTime: true));
		StartCoroutine(ShowEndGame(isWin: false, isChallengeLoss: true));
	}

	private void ForceRebuildLeftPanelLayout()
	{
		LayoutRebuilder.ForceRebuildLayoutImmediate(_leftPanelRT);
		foreach (Transform item in _leftPanelRT)
		{
			if (item.GetComponent<RectTransform>() != null)
			{
				LayoutRebuilder.ForceRebuildLayoutImmediate(item.GetComponent<RectTransform>());
			}
		}
		LayoutRebuilder.ForceRebuildLayoutImmediate(_leftPanelRT);
	}

	public void RemoveUIForFinalMichaelGrid()
	{
		_gridNumberSectionObject.SetActive(value: false);
		_rerollParent.SetActive(value: false);
		_currentWordController.SetSkipButtonToBeHidden();
		_rerollsForEncounter = 0;
	}

	public IEnumerator TransitionMichaelGridIn()
	{
		List<BoardGenVizInfo> vizSteps = new List<BoardGenVizInfo>();
		GridData gridData = GridUtility.Singleton.GenerateBasicGridData(GameStatics.GridDimension, GameStatics.GridDimension, vizSteps, new List<BossModifier>(), 1);
		_gridLayoutController.GenerateGrid(new Vector2Int(GameStatics.GridDimension, GameStatics.GridDimension));
		yield return StartCoroutine(_tileGridTransitions.RandomTransitionGridIn(gridData));
		yield return StartCoroutine(ShowGridGenerationViz(vizSteps));
	}

	public IEnumerator TransitionEGridIn()
	{
		List<BoardGenVizInfo> vizSteps = new List<BoardGenVizInfo>();
		while (_puzzleGrid == null)
		{
			yield return null;
		}
		if (SaveManager.HasBeatenFinalBoss())
		{
			_currentWordController.ShowESolveButton();
		}
		GridData gridData = (_gridData = GridUtility.Singleton.GenerateEsPuzzleGrid(_puzzleGrid, out vizSteps));
		yield return StartCoroutine(_tileGridTransitions.RandomTransitionGridOutAndIn(gridData, isReroll: false));
		yield return StartCoroutine(ShowGridGenerationViz(vizSteps));
		_tileSelectionManager.ResetTileLightLayers();
		if (SaveManager.HasBeatenFinalBoss())
		{
			_ESolveButtonParent.SetActive(value: true);
		}
		_michaelVolumeController.gameObject.SetActive(value: true);
		_tileSelectionManager.SetFinalPuzzleGrid(_michaelVolumeController);
	}

	public void GeneratePuzzleGrid(int size)
	{
		GeneratedGridResult puzzleGrid = GridGenerator.GetPuzzleGrid();
		_puzzleGrid = puzzleGrid.Grid;
		_pathThroughPuzzleGrid = puzzleGrid.Path;
	}

	public void OnSolveButtonClicked()
	{
		if (_encounterThreadStage == EncounterThreadStage.WaitingForWordSubmission)
		{
			StartCoroutine(SolvePuzzleGrid());
		}
	}

	public IEnumerator SolvePuzzleGrid()
	{
		SetEncounterThreadStage(EncounterThreadStage.PuzzleGridAutosolve);
		_tileSelectionManager.ResetGrid();
		yield return new WaitForSeconds(0.3f);
		for (int i = 0; i < _pathThroughPuzzleGrid.Count; i++)
		{
			_tileSelectionManager.ETileClick(_pathThroughPuzzleGrid[i]);
			yield return new WaitForSeconds(0.08f);
		}
		SetEncounterThreadStage(EncounterThreadStage.WaitingForWordSubmission);
	}

	private IEnumerator TransitionGridIn(List<BoardGenVizInfo> gridSteps)
	{
		Debug.Log("Transitioning grid in");
		yield return StartCoroutine(_tileGridTransitions.RandomTransitionGridIn(gridSteps[0].Grid));
		yield return StartCoroutine(ShowGridGenerationViz(gridSteps));
		Player player = GameStatics.GetPlayer();
		if (player.GetUnpackedItemsOfType(typeof(TwinkleToes)).Count > 0)
		{
			TwinkleToes twinkleToes = (TwinkleToes)player.GetUnpackedItemsOfType(typeof(TwinkleToes))[0];
			if (twinkleToes.TileSwapAvailable)
			{
				TwinkleToesSwapAvailable = true;
				twinkleToes.TileSwapAvailable = false;
				StartCoroutine(PulseTwinkleToes());
			}
		}
		TryUnlockFountainPen();
		TryUnlockNewspaper();
		TryUnlockStethoscope();
		TryUnlockFrog();
		yield return StartCoroutine(_unlocksBannerController.CheckAchievementsCoroutine());
		if (player.GetCharacter() is HayleyBayles && player.CurrentRunProgress.IsFirstStage() && !SaveManager.HasSeenNumbersUnlockDialogue())
		{
			TutorialController component = GetComponent<TutorialController>();
			yield return StartCoroutine(component.NumbersIntroTutorial());
		}
		else if (player.GetCharacter() is SamGambit && player.CurrentRunProgress.IsFirstStage() && !SaveManager.HasSeenChessUnlockDialogue())
		{
			TutorialController component2 = GetComponent<TutorialController>();
			yield return StartCoroutine(component2.ChessIntroTutorial());
		}
		else if (player.GetCharacter() is NinaNix && player.CurrentRunProgress.IsFirstStage() && !SaveManager.HasSeenNinaIntroDialogue())
		{
			TutorialController component3 = GetComponent<TutorialController>();
			yield return StartCoroutine(component3.NinaIntroDialogue());
		}
		else if (player.GetCharacter() is BonesTheDog && player.CurrentRunProgress.IsFirstStage() && !SaveManager.HasSeenBonesIntroDialogue())
		{
			TutorialController component4 = GetComponent<TutorialController>();
			yield return StartCoroutine(component4.BonesIntroDialogue());
		}
		else if (player.GetCharacter() is Octacles && player.CurrentRunProgress.IsFirstStage() && !SaveManager.HasSeenOctaclesIntroDialogue())
		{
			TutorialController component5 = GetComponent<TutorialController>();
			yield return StartCoroutine(component5.OctaclesIntroTutorial());
		}
		else if (player.GetCharacter() is NathaServo && player.CurrentRunProgress.IsFirstStage() && !SaveManager.HasSeenNatIntroDialogue())
		{
			TutorialController component6 = GetComponent<TutorialController>();
			yield return StartCoroutine(component6.NatIntroTutorial());
		}
		if (!SaveManager.HasSeenFractionUnlockDialogue() && (_gridData.GetAvailableTiles().Exists((Tile tile) => tile.GetGlyphType() == GlyphType.Fraction) || player.GetTiles().Exists((Tile tile) => tile.GetGlyphType() == GlyphType.Fraction)))
		{
			TutorialController component7 = GetComponent<TutorialController>();
			yield return StartCoroutine(component7.FractionIntroTutorial());
		}
		if (!SaveManager.HasSeenCurrencyFirstTimeDialogue() && (_gridData.GetAvailableTiles().Exists((Tile tile) => tile.GetGlyphType() == GlyphType.Currency) || player.GetTiles().Exists((Tile tile) => tile.GetGlyphType() == GlyphType.Currency)))
		{
			TutorialController component8 = GetComponent<TutorialController>();
			yield return StartCoroutine(component8.CurrencyFirstTimeTutorial());
		}
		if (!SaveManager.HasSeenScatteredItemDialogue() && (_gridData.GetAvailableTiles().Exists((Tile tile) => tile.GetGlyphType() == GlyphType.ScatteredItem) || player.GetTiles().Exists((Tile tile) => tile.GetGlyphType() == GlyphType.ScatteredItem)))
		{
			Item item = ((!_gridData.GetAvailableTiles().Exists((Tile tile) => tile.GetGlyphType() == GlyphType.ScatteredItem)) ? player.GetTiles().Find((Tile tile) => tile.GetGlyphType() == GlyphType.ScatteredItem).ScatteredItem : _gridData.GetAvailableTiles().Find((Tile tile) => tile.GetGlyphType() == GlyphType.ScatteredItem).ScatteredItem);
			TutorialController component9 = GetComponent<TutorialController>();
			yield return StartCoroutine(component9.ScatteredItemFirstTimeTutorial(item));
		}
		List<TileType> unusualTileTypes = new List<TileType>
		{
			TileType.Gold,
			TileType.Pink,
			TileType.Purple,
			TileType.Green,
			TileType.White
		};
		if (!SaveManager.HasSeenWeirdColourDialogue() && (_gridData.GetAvailableTiles().Exists((Tile tile) => unusualTileTypes.Contains(tile.GetTileType())) || player.GetTiles().Exists((Tile tile) => unusualTileTypes.Contains(tile.GetTileType()))))
		{
			TileType tileType = ((!_gridData.GetAvailableTiles().Exists((Tile tile) => unusualTileTypes.Contains(tile.GetTileType()))) ? player.GetTiles().Find((Tile tile) => unusualTileTypes.Contains(tile.GetTileType())).GetTileType() : _gridData.GetAvailableTiles().Find((Tile tile) => unusualTileTypes.Contains(tile.GetTileType())).GetTileType());
			TutorialController component10 = GetComponent<TutorialController>();
			yield return StartCoroutine(component10.WeirdColourFirstTimeTutorial(tileType));
		}
		if (!SaveManager.HasSeenGlitchTileDialogue() && (_gridData.GetAvailableTiles().Exists((Tile tile) => tile.GetTileType() == TileType.Glitch) || player.GetTiles().Exists((Tile tile) => tile.GetTileType() == TileType.Glitch)))
		{
			TutorialController component11 = GetComponent<TutorialController>();
			yield return StartCoroutine(component11.GlitchTileFirstTimeTutorial());
		}
		if (!SaveManager.HasSeenWobblyFirstTimeDialogue() && _gridData.GetAvailableTiles().Exists((Tile tile) => tile.IsDisplayingAsVariableLetter()))
		{
			TutorialController component12 = GetComponent<TutorialController>();
			yield return StartCoroutine(component12.WobblyFirstTimeTutorial());
		}
		WaitForWordSubmission();
	}

	private IEnumerator TransitionGridOutAndIn(bool isReroll)
	{
		List<BoardGenVizInfo> boardGenSteps = GenerateGrid(isReroll);
		if (boardGenSteps[boardGenSteps.Count - 1].Grid.HasLostChallenge)
		{
			if (GameStatics.GetPlayer().CurrentRunProgress.Challenge is MunchTime)
			{
				StartCoroutine(MunchTimeIsOver());
			}
			else
			{
				StartCoroutine(ShowEndGame(isWin: false, isChallengeLoss: true));
			}
			yield break;
		}
		if (SaveManager.IsTutorialComplete())
		{
			MusicController.OnNewEncounterGrid(_remainingGrids, _totalGridsPerRound);
		}
		else
		{
			MusicController.OnGameplayTutorialNewGrid(_remainingGrids);
		}
		_currentWordController.ResetWordAndScoreDisplay();
		_tileSelectionManager.ResetTileLightLayers();
		yield return StartCoroutine(_tileGridTransitions.RandomTransitionGridOutAndIn(boardGenSteps[0].Grid, isReroll));
		yield return StartCoroutine(ShowGridGenerationViz(boardGenSteps));
		Player player = GameStatics.GetPlayer();
		if (player.GetUnpackedItemsOfType(typeof(TwinkleToes)).Count > 0)
		{
			TwinkleToes twinkleToes = (TwinkleToes)player.GetUnpackedItemsOfType(typeof(TwinkleToes))[0];
			if (twinkleToes.TileSwapAvailable)
			{
				TwinkleToesSwapAvailable = true;
				twinkleToes.TileSwapAvailable = false;
				StartCoroutine(PulseTwinkleToes());
			}
		}
		TryUnlockFountainPen();
		TryUnlockNewspaper();
		TryUnlockStethoscope();
		TryUnlockFrog();
		yield return StartCoroutine(_unlocksBannerController.CheckAchievementsCoroutine());
		if (!SaveManager.HasSeenFractionUnlockDialogue() && (_gridData.GetAvailableTiles().Exists((Tile tile) => tile.GetGlyphType() == GlyphType.Fraction) || player.GetTiles().Exists((Tile tile) => tile.GetGlyphType() == GlyphType.Fraction)))
		{
			TutorialController component = GetComponent<TutorialController>();
			yield return StartCoroutine(component.FractionIntroTutorial());
		}
		if (!SaveManager.HasSeenCurrencyFirstTimeDialogue() && (_gridData.GetAvailableTiles().Exists((Tile tile) => tile.GetGlyphType() == GlyphType.Currency) || player.GetTiles().Exists((Tile tile) => tile.GetGlyphType() == GlyphType.Currency)))
		{
			TutorialController component2 = GetComponent<TutorialController>();
			yield return StartCoroutine(component2.CurrencyFirstTimeTutorial());
		}
		if (!SaveManager.HasSeenScatteredItemDialogue() && (_gridData.GetAvailableTiles().Exists((Tile tile) => tile.GetGlyphType() == GlyphType.ScatteredItem) || player.GetTiles().Exists((Tile tile) => tile.GetGlyphType() == GlyphType.ScatteredItem)))
		{
			Item item = ((!_gridData.GetAvailableTiles().Exists((Tile tile) => tile.GetGlyphType() == GlyphType.ScatteredItem)) ? player.GetTiles().Find((Tile tile) => tile.GetGlyphType() == GlyphType.ScatteredItem).ScatteredItem : _gridData.GetAvailableTiles().Find((Tile tile) => tile.GetGlyphType() == GlyphType.ScatteredItem).ScatteredItem);
			TutorialController component3 = GetComponent<TutorialController>();
			yield return StartCoroutine(component3.ScatteredItemFirstTimeTutorial(item));
		}
		List<TileType> unusualTileTypes = new List<TileType>
		{
			TileType.Gold,
			TileType.Pink,
			TileType.Purple,
			TileType.Green,
			TileType.White
		};
		if (!SaveManager.HasSeenWeirdColourDialogue() && (_gridData.GetAvailableTiles().Exists((Tile tile) => unusualTileTypes.Contains(tile.GetTileType())) || player.GetTiles().Exists((Tile tile) => unusualTileTypes.Contains(tile.GetTileType()))))
		{
			TileType tileType = ((!_gridData.GetAvailableTiles().Exists((Tile tile) => unusualTileTypes.Contains(tile.GetTileType()))) ? player.GetTiles().Find((Tile tile) => unusualTileTypes.Contains(tile.GetTileType())).GetTileType() : _gridData.GetAvailableTiles().Find((Tile tile) => unusualTileTypes.Contains(tile.GetTileType())).GetTileType());
			TutorialController component4 = GetComponent<TutorialController>();
			yield return StartCoroutine(component4.WeirdColourFirstTimeTutorial(tileType));
		}
		if (!SaveManager.HasSeenGlitchTileDialogue() && (_gridData.GetAvailableTiles().Exists((Tile tile) => tile.GetTileType() == TileType.Glitch) || player.GetTiles().Exists((Tile tile) => tile.GetTileType() == TileType.Glitch)))
		{
			TutorialController component5 = GetComponent<TutorialController>();
			yield return StartCoroutine(component5.GlitchTileFirstTimeTutorial());
		}
		if (!SaveManager.HasSeenWobblyFirstTimeDialogue() && _gridData.GetAvailableTiles().Exists((Tile tile) => tile.IsDisplayingAsVariableLetter()))
		{
			TutorialController component6 = GetComponent<TutorialController>();
			yield return StartCoroutine(component6.WobblyFirstTimeTutorial());
		}
		WaitForWordSubmission();
	}

	private IEnumerator TransitionGridOut()
	{
		yield return StartCoroutine(_tileGridTransitions.RandomTransitionGridOut(_gridData));
	}

	private IEnumerator PulseTwinkleToes()
	{
		int gridsRemainingAtStart = _remainingGrids;
		int rerollsRemainingAtStart = _rerollsForEncounter;
		while (TwinkleToesSwapAvailable && gridsRemainingAtStart == _remainingGrids && rerollsRemainingAtStart == _rerollsForEncounter)
		{
			ItemObject itemObject2 = CharacterInfoPanel.SingletonInventoryVisualController.GetItemObjects().Find((ItemObject itemObject) => itemObject.MyItem is TwinkleToes);
			if (!(itemObject2 == null))
			{
				itemObject2.ActionPulse(0.5f);
				yield return new WaitForSeconds(0.8f * GameStatics.GetCurrentAnimationSpeed());
				continue;
			}
			break;
		}
	}

	private IEnumerator ShowGridGenerationViz(List<BoardGenVizInfo> gridSteps)
	{
		Player player = GameStatics.GetPlayer();
		if (player.CurrentRunProgress.Challenge is SpeedrunChallenge || player.CurrentRunProgress.CurrentRunStatistics.IsSpeedrunMode)
		{
			float num = _topBarController.StartTimerAndGetCurrentTime();
			if (player.CurrentRunProgress.GetCurrentNodeType() != NodeType.EncounterFirst || player.CurrentRunProgress.CurrentStage == 1)
			{
				Debug.Log($"split / run start / {num}");
			}
		}
		IEnumerator bossAnim = null;
		if (IsBossModifierActive(typeof(SmallGrid)))
		{
			bossAnim = PulseBossModifier(typeof(SmallGrid));
			StartCoroutine(bossAnim);
		}
		if (bossAnim != null)
		{
			while (bossAnim.Current as bool? != true)
			{
				yield return null;
			}
		}
		if (IsBossModifierActive(typeof(FewerGrids)) && _totalGridsPerRound - 1 == _remainingGrids && _rerollTracker == 0)
		{
			bossAnim = PulseBossModifier(typeof(FewerGrids));
			StartCoroutine(bossAnim);
		}
		if (bossAnim != null)
		{
			while (bossAnim.Current as bool? != true)
			{
				yield return null;
			}
		}
		if (IsBossModifierActive(typeof(BigBoss)) && _totalGridsPerRound - 1 == _remainingGrids && _rerollTracker == 0)
		{
			bossAnim = PulseBossModifier(typeof(BigBoss));
			StartCoroutine(bossAnim);
			_totalTarget = _totalTarget.Scale((float)GetActiveBossModifierOfType(typeof(BigBoss)).FloorAdjustedModification / 100f);
			_remainingTarget = _totalTarget;
			_encounterSummaryDisplayController.UpdateDisplayedTargetValue(_totalTarget, _totalTarget, GameStatics.GetPlayer().CurrentRunProgress.Challenge is TwoWrongs);
			_encounterSummaryDisplayController.PulseTargetValue();
			yield return new WaitForSeconds(0.75f * GameStatics.GetCurrentAnimationSpeed());
		}
		if (_rerollsForEncounter > 0 && _rerollTracker == 0)
		{
			string arg = ((GameStatics.GetPlayer().GetUnpackedItemsOfType(typeof(Wheel)).Count > 0) ? "<br> $1 EACH" : "");
			_rerollTMP.SetText($"<b>{_rerollsForEncounter}</b> PER <br><size=18>ENCOUNTER{arg}");
			_rerollButtonObject.GetComponentInChildren<Button>().interactable = true;
			_rerollLine.SetActive(value: true);
		}
		Tile[] tiles;
		if (gridSteps.Count < 2)
		{
			_gridData = gridSteps[0].Grid;
			tiles = _gridData.GetTiles();
			foreach (Tile newTile in tiles)
			{
				_gridLayoutController.PopulateTileDetails(newTile, isRecoloring: true);
			}
			yield break;
		}
		List<TileObject> tileObjectsOnGrid = _gridLayoutController.GetTileObjects();
		if (bossAnim != null)
		{
			while (bossAnim.Current as bool? != true)
			{
				yield return null;
			}
		}
		for (int i = 1; i < gridSteps.Count; i++)
		{
			BoardGenVizInfo currentStep = gridSteps[i];
			Dictionary<TileObject, Tile> tilesToAnimate = new Dictionary<TileObject, Tile>();
			bool isAnimating = false;
			Debug.Log($"Relevant item = {currentStep.RelevantItem}");
			if (currentStep.RelevantItem is LuckyDice || currentStep.RelevantItem is Snapshot || currentStep.RelevantItem is CrystalBall || currentStep.RelevantItem is EightBall)
			{
				yield return StartCoroutine(currentStep.RelevantItem.DoStartOfGridAnimation());
				if (currentStep.RelevantItem is Snapshot)
				{
					Snapshot snapshot = currentStep.RelevantItem as Snapshot;
					ItemObject itemObjectFromItem = CharacterInfoPanel.SingletonInventoryVisualController.GetItemObjectFromItem(currentStep.RelevantItem);
					yield return StartCoroutine(itemObjectFromItem.DoSnapshotAnimation(snapshot.SnapshottedItem, isAnimating: true));
				}
			}
			player.ChangeMoney(currentStep.MoneyChange);
			CharacterInfoPanel.SingletonInventoryVisualController.PopulateCash();
			if (currentStep.IsPulsingMoney)
			{
				isAnimating = true;
				CharacterInfoPanel.SingletonInventoryVisualController.CashGenericAnimations.ActionPulse(1f);
			}
			foreach (KeyValuePair<string, int> item in currentStep.EarningsBreakdown)
			{
				if (item.Value != 0)
				{
					if (!_earningsBreakdown.ContainsKey(item.Key))
					{
						_earningsBreakdown[item.Key] = item.Value;
					}
					else
					{
						_earningsBreakdown[item.Key] += item.Value;
					}
				}
			}
			if (currentStep.RerollsChange != 0)
			{
				_rerollsForEncounter += currentStep.RerollsChange;
				if (_rerollsForEncounter > 0)
				{
					string arg2 = ((GameStatics.GetPlayer().GetUnpackedItemsOfType(typeof(Wheel)).Count > 0) ? "<br> $1 EACH" : "");
					_rerollTMP.SetText(string.Format("<b>{0}</b> <size=18>REROLL{1} <br>REMAINING{2}", _rerollsForEncounter, Item.CheckPlural("S", _rerollsForEncounter), arg2));
					_rerollButtonObject.GetComponentInChildren<Button>().interactable = true;
					_rerollLine.SetActive(value: true);
				}
				else
				{
					_rerollTMP.SetText("NO REROLLS<br>LEFT");
					_rerollButtonObject.GetComponentInChildren<Button>().interactable = false;
					_rerollLine.SetActive(value: false);
				}
			}
			if (currentStep.IsPulsingRerolls)
			{
				_rerollParent.GetComponent<UIElementGenericAnimations>().ActionPulse(1f);
			}
			if (currentStep.PlayerItemToRemove != null)
			{
				player.RemoveItemFromInventory(currentStep.PlayerItemToRemove);
				yield return new WaitForSeconds(0.45f * GameStatics.GetCurrentAnimationSpeed());
				CharacterInfoPanel.SingletonInventoryVisualController.PopulateAll();
				CharacterInfoPanel.SingletonInventoryVisualController.RefreshInspect();
				bossAnim = PulseBossModifier(typeof(HumanBoyBoss));
				StartCoroutine(bossAnim);
				yield return new WaitForSeconds(0.45f * GameStatics.GetCurrentAnimationSpeed());
			}
			if (StringSerializer.Serialize(typeof(Tile[]), currentStep.PlayerConsumableTiles) != StringSerializer.Serialize(typeof(Tile[]), player.ConsumableTiles))
			{
				Debug.Log("Tile array change found");
				player.SetInventoryTilesArray(currentStep.PlayerConsumableTiles);
				isAnimating = true;
				CharacterInfoPanel.SingletonInventoryVisualController.PopulateTiles();
				CharacterInfoPanel.SingletonInventoryVisualController.RefreshInspect();
			}
			else
			{
				Debug.Log("Tile array change not found");
				Debug.Log("Current step array = " + StringSerializer.Serialize(typeof(Tile[]), currentStep.PlayerConsumableTiles));
			}
			foreach (TileObject tileObject2 in _gridLayoutController.GetTileObjects())
			{
				Tile currentTile = gridSteps[i].Grid.GetTileAtCoordinates(tileObject2.GridCoordinate);
				Tile tileAtCoordinates = gridSteps[i - 1].Grid.GetTileAtCoordinates(tileObject2.GridCoordinate);
				if (currentTile.GetTileType() != tileAtCoordinates.GetTileType() || currentTile.GetStringRepresentation() != tileAtCoordinates.GetStringRepresentation() || currentTile.GetValueForDisplay() != tileAtCoordinates.GetValueForDisplay() || currentTile.GetSuitForDisplay() != tileAtCoordinates.GetSuitForDisplay())
				{
					RunProgress currentRunProgress = player.CurrentRunProgress;
					if (currentRunProgress.Challenge is SupplyAndDemand && currentRunProgress.CurrentRunStatistics.WordsSubmittedThisRun.Count > 0)
					{
						List<Tile> tiles2 = currentRunProgress.CurrentRunStatistics.WordsSubmittedThisRun[currentRunProgress.CurrentRunStatistics.WordsSubmittedThisRun.Count - 1].Tiles;
						currentTile.IsCrossedOut = tiles2.Exists((Tile tile) => tile.GetStringRepresentation() == currentTile.GetStringRepresentation());
					}
					tilesToAnimate[tileObject2] = currentTile;
					isAnimating = true;
				}
				if (currentTile.HasBeenDestroyed != tileAtCoordinates.HasBeenDestroyed)
				{
					isAnimating = true;
					tilesToAnimate[tileObject2] = currentTile;
				}
			}
			if (isAnimating)
			{
				if (currentStep.RelevantItem != null)
				{
					ItemObject itemObject2 = CharacterInfoPanel.SingletonInventoryVisualController.GetItemObjects().Find((ItemObject itemObject) => itemObject.MyItem == currentStep.RelevantItem);
					if (itemObject2 != null)
					{
						itemObject2.ActionPulse(1f);
						PersistentSound.SingletonSoundController.PulseItem();
					}
					else
					{
						TileObject tileObject = tileObjectsOnGrid.Find((TileObject to) => to.MyTile.ScatteredItem == currentStep.RelevantItem);
						if (tileObject != null)
						{
							tileObject.ActionPulse();
							PersistentSound.SingletonSoundController.PulseItem();
						}
					}
				}
				if (currentStep.BossModifierToPulse != null)
				{
					bossAnim = PulseBossModifier(currentStep.BossModifierToPulse);
					StartCoroutine(bossAnim);
				}
				yield return new WaitForSeconds(0.15f * GameStatics.GetCurrentAnimationSpeed());
				foreach (KeyValuePair<TileObject, Tile> kvp in tilesToAnimate)
				{
					StartCoroutine(kvp.Key.TransformTile(kvp.Value));
					yield return new WaitForSeconds(0.05f * GameStatics.GetCurrentAnimationSpeed());
					if (kvp.Value.HasBeenDestroyed)
					{
						yield return new WaitForSeconds(0.3f * GameStatics.GetCurrentAnimationSpeed());
					}
				}
				yield return new WaitForSeconds(0.75f * GameStatics.GetCurrentAnimationSpeed());
			}
			if (currentStep.MoneyChange != 0 && currentStep.Grid.GetAvailableTiles().Exists((Tile tile) => tile.IsTileType(TileType.Gold)))
			{
				yield return StartCoroutine(WaitForTileUpdate((from tile in currentStep.Grid.GetAvailableTiles()
					where tile.IsTileType(TileType.Gold)
					select tile).ToList()));
			}
			if (bossAnim != null)
			{
				while (bossAnim.Current as bool? != true)
				{
					yield return null;
				}
			}
			yield return null;
		}
		_gridData = gridSteps[gridSteps.Count - 1].Grid;
		tiles = _gridData.GetTiles();
		foreach (Tile newTile2 in tiles)
		{
			_gridLayoutController.PopulateTileDetails(newTile2, isRecoloring: true);
		}
	}

	public void SwapTwinkleToesTiles(List<Tile> tilesToSwap)
	{
		TwinkleToesSwapAvailable = false;
		SetEncounterThreadStage(EncounterThreadStage.SwappingTiles);
		Dictionary<TileObject, Tile> dictionary = new Dictionary<TileObject, Tile>();
		List<Tile> list = new List<Tile>();
		foreach (TileObject tileObject in _gridLayoutController.GetTileObjects())
		{
			if (tilesToSwap.Exists((Tile tile) => tile.Coordinates == tileObject.GridCoordinate))
			{
				Tile tileToCopy = tilesToSwap.Find((Tile tile) => tile.Coordinates != tileObject.GridCoordinate);
				Tile tile2 = new Tile();
				tile2.SetAsCopy(tileToCopy, changeCoords: false);
				tile2.Coordinates = tileObject.GridCoordinate;
				dictionary[tileObject] = tile2;
				list.Add(tile2);
			}
		}
		List<Tile> list2 = _gridData.GetTiles().ToList();
		list2.Remove(tilesToSwap[0]);
		list2.Remove(tilesToSwap[1]);
		list2.AddRange(list);
		_gridData.GridTiles = list2.ToArray();
		StartCoroutine(DisplayTwinkleToesSwap(dictionary));
	}

	private IEnumerator DisplayTwinkleToesSwap(Dictionary<TileObject, Tile> tilesToAnimate)
	{
		yield return new WaitForSeconds(0.5f * GameStatics.GetCurrentAnimationSpeed());
		_tileSelectionManager.ResetGrid();
		ItemObject itemObject2 = CharacterInfoPanel.SingletonInventoryVisualController.GetItemObjects().Find((ItemObject itemObject) => itemObject.MyItem is TwinkleToes);
		if (itemObject2 != null)
		{
			itemObject2.ActionPulse(1f);
		}
		yield return new WaitForSeconds(0.15f * GameStatics.GetCurrentAnimationSpeed());
		foreach (KeyValuePair<TileObject, Tile> item in tilesToAnimate)
		{
			StartCoroutine(item.Key.TransformTile(item.Value));
			yield return new WaitForSeconds(0.05f * GameStatics.GetCurrentAnimationSpeed());
		}
		yield return new WaitForSeconds(0.75f * GameStatics.GetCurrentAnimationSpeed());
		Tile[] tiles = _gridData.GetTiles();
		foreach (Tile newTile in tiles)
		{
			_gridLayoutController.PopulateTileDetails(newTile, isRecoloring: true);
		}
		WaitForWordSubmission();
	}

	public void DevSubmitWord(ScorePacket score)
	{
		Player player = GameStatics.GetPlayer();
		SetEncounterThreadStage(EncounterThreadStage.ExecutingWordConsequences);
		HistoricWord historicWord = new HistoricWord(new List<TileSelection>(), new List<string> { "!!!" }, isWordSkipped: false, score, _remainingTarget - score, CurrentGridsGenerated(), GetGridDimensions());
		_previousWords.Add(historicWord);
		player.CurrentRunProgress.CurrentRunStatistics.UpdateWordRecords(historicWord);
		Achievements.TryUnlockRunStatisticsAchievements();
		Achievements.TryUnlockWordSubmissionAchievements(_gridData, historicWord);
		Achievements.TryUnlockRoundScoringAchievements(historicWord, _totalTarget, score, CurrentGridsGenerated(), _bossModifiers);
		_remainingTarget -= score;
		_currentWordController.DisplayScores();
		_encounterSummaryDisplayController.UpdateDisplayedTargetValue(_remainingTarget, _totalTarget, player.CurrentRunProgress.Challenge is TwoWrongs);
		StartCoroutine(TryGoToNextGrid());
	}

	public void DevCompleteEncounter()
	{
		if (_encounterThreadStage == EncounterThreadStage.WaitingForWordSubmission)
		{
			_remainingTarget = new ScorePacket(-999L);
			SubmitWord(new List<TileSelection>(), new List<string> { "" });
		}
	}

	public void DevWinGame()
	{
		if (_encounterThreadStage == EncounterThreadStage.WaitingForWordSubmission)
		{
			Player player = GameStatics.GetPlayer();
			player.HasFacedUncursedBoss = true;
			player.CurrentRunProgress.DevSetFinalStage();
			_remainingTarget = new ScorePacket(-999L);
			SubmitWord(new List<TileSelection>(), new List<string> { "" });
		}
	}

	public void WinTutorial()
	{
		SetEncounterThreadStage(EncounterThreadStage.WaitingForWordSubmission);
		_remainingTarget = new ScorePacket(0L);
		SubmitWord(new List<TileSelection>(), new List<string> { "" });
	}

	public void DevFailEncounter()
	{
		if (_encounterThreadStage == EncounterThreadStage.WaitingForWordSubmission)
		{
			_remainingTarget = new ScorePacket(9999L);
			_remainingGrids = 0;
			SubmitWord(new List<TileSelection>(), new List<string> { "" });
		}
	}

	private Vector2Int GetGridDimensions()
	{
		Vector2Int vector2Int = new Vector2Int(GameStatics.GridDimension, GameStatics.GridDimension);
		if (GameStatics.GetPlayer().CurrentRunProgress.Challenge is CallOfTheVoid)
		{
			vector2Int.x++;
			vector2Int.y++;
		}
		if (IsBossModifierActive(typeof(SmallGrid)))
		{
			int num = GetActiveBossModifierOfType(typeof(SmallGrid)).FloorAdjustedModification + 1;
			Debug.Log($"gridReductions: {num}");
			for (int i = 0; i < num; i++)
			{
				if (i % 2 == 0)
				{
					vector2Int.y--;
				}
				else
				{
					vector2Int.x--;
				}
				Debug.Log($"i = {i}, current dimensions = {vector2Int}");
			}
		}
		return vector2Int;
	}

	public List<HistoricWord> GetPreviousWords()
	{
		return _previousWords;
	}

	public EncounterThreadStage GetCurrentEncounterThreadStage()
	{
		return _encounterThreadStage;
	}

	public bool IsWaitingForWordSubmission()
	{
		if (_encounterThreadStage == EncounterThreadStage.WaitingForWordSubmission)
		{
			return !SettingsMenuController.IsOpen;
		}
		return false;
	}

	public int CurrentGridsGenerated()
	{
		return _totalGridsPerRound - _remainingGrids;
	}

	public GridData GetGridData()
	{
		return _gridData;
	}

	public List<BossModifier> GetBossModifiers()
	{
		return _bossModifiers;
	}

	private List<BoardGenVizInfo> GenerateGrid(bool isReroll)
	{
		List<Tile> list = new List<Tile>();
		if (!isReroll)
		{
			_remainingGrids--;
			_encounterSummaryDisplayController.UpdateRoundSummary(CurrentGridsGenerated(), _totalGridsPerRound);
		}
		if (isReroll && GameStatics.GetPlayer().GetUnpackedItemsOfType(typeof(Fan)).Count > 0)
		{
			foreach (Item fan in GameStatics.GetPlayer().GetUnpackedItemsOfType(typeof(Fan)))
			{
				list.AddRange(from tile in _gridData.GetAvailableTiles()
					where tile.IsTileType(fan.RelevantColours[0])
					select tile);
			}
		}
		Vector2Int gridDimensions = GetGridDimensions();
		_gridData = GridUtility.Singleton.GenerateGrid(gridDimensions.x, gridDimensions.y, CurrentGridsGenerated(), _totalGridsPerRound, _previousWords, _bossModifiers, out var vizSteps, isReroll, (list.Count > 0) ? list : null);
		return vizSteps;
	}

	public bool TryReroll()
	{
		if (_rerollsForEncounter <= 0)
		{
			return false;
		}
		Player player = GameStatics.GetPlayer();
		if (player.GetUnpackedItemsOfType(typeof(Wheel)).Count > 0)
		{
			if (player.Money < 1)
			{
				return false;
			}
			player.ChangeMoney(-1);
			CharacterInfoPanel.SingletonInventoryVisualController.PopulateCash();
		}
		PersistentSound.SingletonSoundController.RerollBoard();
		foreach (Item item in player.GetUnpackedItemsOfType(typeof(Rollercoaster)))
		{
			(item as Rollercoaster).MakeRollercoasterCheck();
		}
		_rerollsForEncounter--;
		_rerollTracker++;
		if (player.GetStamps().Exists((Item item) => item is TwinkleToes))
		{
			_tileSelectionManager.ResetTwinkleToes();
		}
		if (_rerollsForEncounter <= 0)
		{
			_rerollButtonObject.GetComponentInChildren<Button>().interactable = false;
			_rerollLine.SetActive(value: false);
		}
		else
		{
			string arg = ((GameStatics.GetPlayer().GetUnpackedItemsOfType(typeof(Wheel)).Count > 0) ? "<br> $1 EACH" : "");
			_rerollTMP.SetText(string.Format("<b>{0}</b> <size=18>REROLL{1} <br>REMAINING{2}", _rerollsForEncounter, Item.CheckPlural("S", _rerollsForEncounter), arg));
			_rerollButtonObject.GetComponentInChildren<Button>().interactable = true;
			_rerollLine.SetActive(value: true);
		}
		SetEncounterThreadStage(EncounterThreadStage.Initializing);
		StartCoroutine(TransitionGridOutAndIn(isReroll: true));
		return true;
	}

	public void SetRerolls(int rerollCount)
	{
		_rerollsForEncounter -= rerollCount;
	}

	public EncounterThreadStage GetEncounterThreadStage()
	{
		return _encounterThreadStage;
	}

	public void SetChallengeDialogueStage()
	{
		SetEncounterThreadStage(EncounterThreadStage.ShowingChallengeDialogue);
	}

	public void SetEncounterThreadStage(EncounterThreadStage newThreadStage)
	{
		if (newThreadStage == EncounterThreadStage.WaitingForWordSubmission || newThreadStage == EncounterThreadStage.SwappingTiles || newThreadStage == EncounterThreadStage.WaitingForForcedSell)
		{
			_unlocksBannerController.StartCheckingAchievements();
			if (GameStatics.GetPlayer().CurrentRunProgress.Challenge is SpeedrunChallenge)
			{
				_speedrunTimeCheckCoroutine = StartCoroutine(SpeedrunTimeCheck());
			}
		}
		else
		{
			_unlocksBannerController.StopCheckingAchievements();
			if (GameStatics.GetPlayer().CurrentRunProgress.Challenge is SpeedrunChallenge)
			{
				StopCoroutine(_speedrunTimeCheckCoroutine);
			}
		}
		Debug.Log($"Encounter thread stage being set to: {newThreadStage}");
		_encounterThreadStage = newThreadStage;
	}

	public void SubmitWord(List<TileSelection> tiles, List<string> words)
	{
		Player player = GameStatics.GetPlayer();
		SetEncounterThreadStage(EncounterThreadStage.ExecutingWordConsequences);
		_unlocksBannerController.StopCheckingAchievements();
		IEnumerator enumerator = null;
		if (player.ActiveBossModifiers.Exists((BossModifier bossMod) => bossMod is MichaelBoss) && ((MichaelBoss)player.ActiveBossModifiers[0]).SummonedBossesDefeated)
		{
			_michaelVolumeController.gameObject.SetActive(value: false);
			MusicController.OnSubmitMichaelPuzzleGridWord();
		}
		if (IsBossModifierActive(typeof(RandomiseItemOrder)))
		{
			enumerator = PulseBossModifier(typeof(RandomiseItemOrder));
			StartCoroutine(enumerator);
			player.RandomiseItemOrder(GetActiveBossModifierOfType(typeof(RandomiseItemOrder)).FloorAdjustedModification == 2);
		}
		List<Item> itemsForWordSubmission = GetItemsForWordSubmission(tiles, isIncludingInventory: true);
		int count = GameStatics.GetPlayer().GetUnpackedItemsOfType(typeof(CableCar)).Count;
		if (count > 0)
		{
			List<Item> list = (from item in GetItemsForWordSubmission(tiles, isIncludingInventory: false)
				where item.IsSticker()
				select item).ToList();
			for (int i = 0; i < count; i++)
			{
				foreach (Item item in list)
				{
					item.Upgrade(0);
				}
			}
		}
		List<ScoreCalcVizInfo> steps = ScoreCalculation.CalculateOverallScore(tiles, words, itemsForWordSubmission, _previousWords, _bossModifiers, _gridData, CurrentGridsGenerated());
		ScorePacket scoreFromScoreCalcInfo = ScoreCalculation.GetScoreFromScoreCalcInfo(steps);
		if (player.CurrentRunProgress.Challenge is TwoWrongs)
		{
			scoreFromScoreCalcInfo *= -1L;
		}
		ScorePacket scorePacket = _remainingTarget - scoreFromScoreCalcInfo;
		if (scoreFromScoreCalcInfo >= new ScorePacket(1000000L))
		{
			SteamAchievementHandler.AddAchievementToQueue(SteamAchievementHandler.STEAM_ACHIEVEMENT_ONE_MILLION_POINTS);
		}
		if (scoreFromScoreCalcInfo >= new ScorePacket(1000000000L))
		{
			SteamAchievementHandler.AddAchievementToQueue(SteamAchievementHandler.STEAM_ACHIEVEMENT_ONE_BILLION_POINTS);
		}
		if (scoreFromScoreCalcInfo.IsInfinite && !scoreFromScoreCalcInfo.IsNegative)
		{
			SteamAchievementHandler.AddAchievementToQueue(SteamAchievementHandler.STEAM_ACHIEVEMENT_INFINITE_POINTS);
		}
		if (player.CurrentRunProgress.Challenge is Bullseye)
		{
			scorePacket = scorePacket.GetAbsoluteValue();
		}
		HistoricWord historicWord = new HistoricWord(tiles, words, isWordSkipped: false, scoreFromScoreCalcInfo, scorePacket, CurrentGridsGenerated(), GetGridDimensions());
		Debug.Log("Submitted word(s): " + string.Join("; ", historicWord.Words));
		_previousWords.Add(historicWord);
		if (player.ActiveBossModifiers.Count <= 0 || !(player.ActiveBossModifiers[0] is MichaelBoss) || !((MichaelBoss)player.ActiveBossModifiers[0]).SummonedBossesDefeated)
		{
			player.CurrentRunProgress.CurrentRunStatistics.UpdateWordRecords(historicWord);
		}
		_currentWordController.DisplayScores();
		PersistentSound.SingletonSoundController.SubmitWord();
		StartCoroutine(ShowScoreCalculation(steps, historicWord, ScoreCalculation.GetBasicValueScore(tiles), scoreFromScoreCalcInfo, tiles.Select((TileSelection tiles) => tiles.SelectedTile).ToList(), enumerator));
	}

	public void SkipWordSubmission()
	{
		if (GameStatics.GetPlayer().GetStamps().Exists((Item item) => item is TwinkleToes))
		{
			_tileSelectionManager.ResetTwinkleToes();
		}
		SetEncounterThreadStage(EncounterThreadStage.ExecutingWordConsequences);
		_previousWords.Add(new HistoricWord(new List<TileSelection>(), new List<string> { "" }, isWordSkipped: true, new ScorePacket(0L), _remainingTarget, CurrentGridsGenerated(), GetGridDimensions()));
		PersistentSound.SingletonSoundController.SkipButton();
		if (_remainingGrids <= 0)
		{
			MusicController.OnWinOrLoseEncounter(isWin: false);
		}
		if (!SaveManager.IsTutorialComplete() && _remainingGrids <= 0 && _remainingTarget > new ScorePacket(0L))
		{
			TutorialController component = GetComponent<TutorialController>();
			StartCoroutine(component.LostTutorialDialogue());
		}
		else
		{
			StartCoroutine(TryGoToNextGrid());
		}
	}

	private List<Item> GetItemsForWordSubmission(List<TileSelection> tileSelections, bool isIncludingInventory)
	{
		List<Item> list = new List<Item>();
		foreach (TileSelection tileSelection in tileSelections)
		{
			Tile selectedTile = tileSelection.SelectedTile;
			if (selectedTile.GetGlyphType() == GlyphType.ScatteredItem)
			{
				list.Add(selectedTile.ScatteredItem);
			}
		}
		if (isIncludingInventory)
		{
			list.AddRange(GameStatics.GetPlayer().GetAllItems());
		}
		return list;
	}

	private IEnumerator TryGoToNextGrid()
	{
		Player player = GameStatics.GetPlayer();
		_currentWordController.HideWordAndScoreDisplay();
		if (_remainingTarget <= new ScorePacket(0L))
		{
			if (IsBossModifierActive(typeof(RandomiseItemOrder)))
			{
				ItemObject[] array = UnityEngine.Object.FindObjectsByType<ItemObject>(FindObjectsSortMode.None);
				for (int i = 0; i < array.Length; i++)
				{
					array[i].DraggingDisabled = false;
				}
			}
			if (_enteredWithNoMoney && (IsBossModifierActive(typeof(StealsMoney)) || IsBossModifierActive(typeof(NegativeMoney))))
			{
				Achievements.UnlockAchievement(typeof(DeclareBankcrupcy));
			}
			if (_bossModifiers.Exists((BossModifier boss) => boss.IsSecretCharacter))
			{
				foreach (BossModifier bossModifier in _bossModifiers)
				{
					if (bossModifier.IsSecretCharacter)
					{
						TutorialController component = GetComponent<TutorialController>();
						yield return StartCoroutine(component.SecretCharacterUnlockDialogue(bossModifier));
					}
				}
			}
			yield return StartCoroutine(_unlocksBannerController.CheckAchievementsCoroutine());
			int gridsUnused = _remainingGrids;
			_rightPanelCharacterController = CharacterInfoPanel.SingletonObject.GetComponentInChildren<PlayerCharacterController>();
			if (player.ActiveBossModifiers.Count > 0 && player.ActiveBossModifiers[0] is MichaelBoss && ((MichaelBoss)player.ActiveBossModifiers[0]).DraftedModifiers.Count < ((MichaelBoss)player.ActiveBossModifiers[0]).FloorAdjustedModification)
			{
				Debug.Log("Modifier beaten!");
				if (player.CurrentRunProgress.Challenge is SpeedrunChallenge || player.CurrentRunProgress.CurrentRunStatistics.IsSpeedrunMode)
				{
					float num = _topBarController.StopTimerAndGetCurrentTime();
					Debug.Log($"split / finale - {((MichaelBoss)player.ActiveBossModifiers[0]).DraftedModifiers.Count} / {num}");
				}
				yield return StartCoroutine(TransitionGridOut());
				StartCoroutine(GameSetup());
			}
			else if (player.ActiveBossModifiers.Count > 0 && player.ActiveBossModifiers[0] is MichaelBoss)
			{
				MichaelBoss michael = player.ActiveBossModifiers[0] as MichaelBoss;
				TutorialController tc = GetComponent<TutorialController>();
				if (michael.SummonedBossesDefeated)
				{
					SaveManager.SetCharacterHasBeatenFinalBoss(player.MyCharacter);
					if (player.CurrentRunProgress.Ascension == (AscensionLevel)GameStatics.HighestCrownAvailable)
					{
						SteamAchievementHandler.AddAchievementToQueue(SteamAchievementHandler.STEAM_ACHIEVEMENT_FINAL_CROWN_MICHAEL);
					}
					foreach (Item item in player.CurrentRunProgress.PlayerSavedFinalInventory)
					{
						player.AddItemToInventory(item);
					}
					if (_showLongEnding)
					{
						yield return StartCoroutine(tc.MichaelFightEndDialogue(michael));
					}
					Debug.Log("Roll credits");
					StartCoroutine(_rightPanelCharacterController.VictoryCoroutine());
					StartCoroutine(ShowEndGame(isWin: true, isChallengeLoss: false, _showLongEnding));
				}
				else
				{
					Debug.Log("MICHAEL SUMMONS DEFEATED!!!");
					michael.SummonedBossesDefeated = true;
					michael.SummonedBossesDefeated = true;
					yield return StartCoroutine(TransitionGridOut());
					StartCoroutine(_rightPanelCharacterController.IdleCoroutine());
					_encounterSummaryDisplayController.EnemyIdle();
					if (_showLongEnding)
					{
						yield return StartCoroutine(tc.MichaelPuzzleGrid(michael));
					}
					else
					{
						yield return StartCoroutine(tc.MichaelPuzzleGridLessDialogue(michael));
					}
				}
			}
			else if (player.CurrentRunProgress.IsFinalStage() && (player.CurrentRunProgress.Ascension < AscensionLevel.CursedBosses || player.HasFacedUncursedBoss))
			{
				StartCoroutine(_rightPanelCharacterController.VictoryCoroutine());
				StartCoroutine(ShowEndGame(isWin: true));
			}
			else if (player.CurrentRunProgress.Challenge is SpeedrunChallenge && _topBarController.GetCurrentTime() >= (float)SpeedrunChallenge.TimeLimitInSeconds)
			{
				StartCoroutine(SpeedrunOutOfTime());
			}
			else
			{
				StartCoroutine(_rightPanelCharacterController.VictoryCoroutine());
				Reward fairyReward = null;
				if (_bossModifiers.Exists((BossModifier boss) => boss.IsCursed) && player.CurrentRunProgress.Ascension > AscensionLevel.None)
				{
					player.CurrentRunProgress.CursedBossesDefeated.Add(player.CurrentRunProgress.GetStage() - 1);
					yield return CharacterInfoPanel.SingletonInventoryVisualController.PopulateNewCurseFly(player.CurrentRunProgress.GetStage() - 1);
					fairyReward = new Reward("A fairy follows you...", 0, isFairy: true);
				}
				ChallengeRun currentChallenge = player.CurrentRunProgress.Challenge;
				Reward embargoRefund = null;
				if (currentChallenge is Embargo && !player.CurrentRunProgress.IsFinalStage() && player.CurrentRunProgress.GetCurrentNodeType() == NodeType.Boss)
				{
					_ = currentChallenge;
					int num2 = 0;
					foreach (Item allItem in player.GetAllItems(forItemComparison: true))
					{
						num2 += allItem.MoneyInvested.Sum();
						player.CurrentRunProgress.EmbargoedItemTypes.Add(allItem.GetType());
					}
					player.ClearStickers();
					player.ClearStamps();
					player.ChangeMoney(num2);
					CharacterInfoPanel.SingletonInventoryVisualController.PopulateStickers();
					CharacterInfoPanel.SingletonInventoryVisualController.PopulateStamps();
					embargoRefund = new Reward("Embargo refund", num2);
				}
				yield return new WaitForSeconds(0.5f);
				bool flag = currentChallenge is DoNotPassGo;
				List<Reward> list = new List<Reward>
				{
					new Reward("Encounter clear!", (!flag) ? 10 : 0),
					new Reward(string.Format("{0} grid{1} unused", gridsUnused, (gridsUnused != 1) ? "s" : ""), (!flag) ? (gridsUnused * 2) : 0)
				};
				if (player.CurrentRunProgress.GetCurrentNodeType() == NodeType.Boss)
				{
					list.Add(new Reward("Boss defeated!", (!flag) ? 5 : 0));
					List<Item> unpackedItemsOfType = player.GetUnpackedItemsOfType(typeof(Ogre));
					if (unpackedItemsOfType.Count > 0)
					{
						int num3 = 0;
						foreach (Item item2 in unpackedItemsOfType)
						{
							_ = item2;
							num3 += 5;
						}
						list.Add(new Reward("Ogre bonus", num3));
					}
				}
				if (fairyReward != null)
				{
					list.Add(fairyReward);
				}
				List<Reward> list2 = new List<Reward>();
				if (embargoRefund != null)
				{
					list2.Add(embargoRefund);
				}
				if (player.CurrentRunProgress.CurrentNodeType == NodeType.EncounterFirst && _piggyBankSavings > 0)
				{
					list2.Add(new Reward("Piggy Bank savings", _piggyBankSavings, isFairy: false, isPig: true));
				}
				foreach (KeyValuePair<string, int> item3 in _earningsBreakdown)
				{
					list2.Add(new Reward(item3.Key, item3.Value, isFairy: false, item3.Key == "Saved in Piggy Bank"));
				}
				if (player.CurrentRunProgress.GetCurrentNodeType() == NodeType.Boss && IsBossModifierActive(typeof(CretaceousMegBoss)))
				{
					list2.Clear();
					CretaceousMegBoss cretaceousMegBoss = GetActiveBossModifierOfType(typeof(CretaceousMegBoss)) as CretaceousMegBoss;
					if (cretaceousMegBoss.PlayerMoneyAtStart > 0)
					{
						list2.Add(new Reward("Recovered money", cretaceousMegBoss.PlayerMoneyAtStart));
					}
				}
				int num4 = 0;
				if (player.GetUnpackedItemsOfType(typeof(Dragon)).Count != 0)
				{
					int num5 = 0;
					int num6 = player.Money;
					if (!flag)
					{
						num6 += 10 + gridsUnused * 2;
						if (player.CurrentRunProgress.GetCurrentNodeType() == NodeType.Boss)
						{
							num6 += 5;
						}
					}
					foreach (Item item4 in player.GetUnpackedItemsOfType(typeof(Dragon)))
					{
						_ = item4;
						Debug.Log("player total for dragon earnings: " + num6);
						num5 += (int)Mathf.Floor((float)num6 * 0.1f);
						Debug.Log("dragon earnings from this item: " + (int)Mathf.Floor((float)num6 * 0.1f));
					}
					if (num5 > 0)
					{
						list2.Add(new Reward("Interest", num5));
						num4 = num5;
					}
				}
				_rewardsController.ShowRewards(list, list2);
				if (!flag)
				{
					player.ChangeMoney(10 + gridsUnused * 2);
					if (player.CurrentRunProgress.GetCurrentNodeType() == NodeType.Boss)
					{
						player.ChangeMoney(5);
					}
					if (num4 > 0)
					{
						player.ChangeMoney(num4);
					}
					int num7 = 0;
					foreach (Reward item5 in list)
					{
						num7 += item5.RewardCashAmount;
					}
					foreach (Reward item6 in list2)
					{
						num7 += item6.RewardCashAmount;
					}
					if (num7 >= 30)
					{
						Achievements.UnlockAchievement(typeof(Kaching));
					}
				}
				CharacterInfoPanel.SingletonInventoryVisualController.PopulateCash();
			}
		}
		else if (_remainingGrids <= 0)
		{
			if (_rightPanelCharacterController != null)
			{
				StartCoroutine(_rightPanelCharacterController.DefeatCoroutine());
			}
			if (_leftPanelBossVisualController.gameObject.activeInHierarchy)
			{
				StartCoroutine(_leftPanelBossVisualController.SelectCoroutine());
			}
			StartCoroutine(ShowEndGame(isWin: false));
		}
		else
		{
			if (GameStatics.GetPlayer().CurrentRunProgress.Challenge is SpeedrunChallenge)
			{
				if (_topBarController.GetCurrentTime() >= (float)SpeedrunChallenge.TimeLimitInSeconds)
				{
					StartCoroutine(SpeedrunOutOfTime());
					yield break;
				}
				_topBarController.StopTimerAndGetCurrentTime();
			}
			StartCoroutine(TransitionGridOutAndIn(isReroll: false));
		}
		yield return null;
	}

	public void GoToNextScene()
	{
		Player player = GameStatics.GetPlayer();
		if (player.CurrentRunProgress.Challenge is SpeedrunChallenge || GameStatics.GetPlayer().CurrentRunProgress.CurrentRunStatistics.IsSpeedrunMode)
		{
			float num = _topBarController.StopTimerAndGetCurrentTime();
			Debug.Log($"split / {player.CurrentRunProgress.GetStage()} - {player.CurrentRunProgress.GetCurrentNodeType()} / {num}");
		}
		StartCoroutine(GoToNextSceneCoroutine());
	}

	private IEnumerator GoToNextSceneCoroutine()
	{
		Player player = GameStatics.GetPlayer();
		if (player.CurrentRunProgress.IsFinalStage() && player.CurrentRunProgress.Ascension >= AscensionLevel.CursedBosses && !player.HasFacedUncursedBoss)
		{
			Achievements.TryUnlockEndOfRunStatisticsAchievements(isWin: true);
			Achievements.TryUnlockCrownRewardAchievements();
			SaveManager.UpdateHighestAscensionBeaten(player.MyCharacter, player.CurrentRunProgress.Ascension);
			yield return StartCoroutine(_unlocksBannerController.CheckAchievementsCoroutine());
			if ((player.CurrentRunProgress.Ascension == AscensionLevel.UnkindShops || player.CurrentRunProgress.Ascension == AscensionLevel.CursedBosses) && SaveManager.GetHighestCompletedAscensions().Values.ToList().Count((int i) => i >= 1) >= 3)
			{
				BulkUnlock bulkUnlock = new ScatteredItemsUnlock();
				if (!SaveManager.IsBulkUnlockUnlocked(bulkUnlock))
				{
					Debug.Log("Unlocking Bulk Unlock: " + bulkUnlock.Name);
					bulkUnlock.Unlock();
					player.CurrentRunProgress.CurrentRunStatistics.CharactersUnlocked.Add(new NathaServo());
					player.CurrentRunProgress.CurrentRunStatistics.BulkUnlocksUnlocked.Add(bulkUnlock);
					yield return StartCoroutine(ShowMidRunCharacterUnlock(new List<Character>
					{
						new NathaServo()
					}, new List<BulkUnlock>
					{
						new ScatteredItemsUnlock()
					}));
				}
			}
			Debug.Log("Flies time");
			_curseFliesCanvasController.gameObject.SetActive(value: true);
			yield return _curseFliesCanvasController.FliesSpin();
		}
		else
		{
			Debug.Log("No flies :(");
		}
		yield return StartCoroutine(_unlocksBannerController.CheckAchievementsCoroutine());
		StartCoroutine(TransitionToNextScene());
	}

	private IEnumerator TransitionToNextScene()
	{
		Player player = GameStatics.GetPlayer();
		if (!SaveManager.IsTutorialComplete())
		{
			TutorialController component = GetComponent<TutorialController>();
			yield return component.TransitionToShopTutorial();
		}
		else if (player.CurrentRunProgress.GetCurrentNodeType() != NodeType.Boss)
		{
			MusicController.OnEndOfEncounter();
		}
		string sceneString = player.CurrentRunProgress.GoToNextNodeAndGetSceneName();
		_transitionController.TransitionToNewScene(sceneString);
	}

	public void GoToMainMenu()
	{
		StartCoroutine(ShowAchievementSummaryAndChangeScene(isGoingToCharacterSelect: false));
	}

	public void GoToCharacterSelect()
	{
		StartCoroutine(ShowAchievementSummaryAndChangeScene(isGoingToCharacterSelect: true));
	}

	public void RetryRun()
	{
		CharacterInfoPanel.SingletonInventoryVisualController.RemovePanel();
		Player player = GameStatics.GetPlayer();
		GameStatics.InitialisePlayerForNewRun(player.MyCharacter.GetType(), (player.CurrentRunProgress.Challenge != null) ? player.CurrentRunProgress.Challenge.GetType() : null, player.CurrentRunProgress.Ascension);
		string sceneString = GameStatics.GetPlayer().CurrentRunProgress.GoToNextNodeAndGetSceneName();
		_transitionController.TransitionToNewScene(sceneString);
	}

	private IEnumerator ShowMidRunCharacterUnlock(List<Character> unlockedCharacters, List<BulkUnlock> unlockedBulkUnlocks)
	{
		yield return StartCoroutine(_unlocksBannerController.Populate(new List<Item>(), unlockedCharacters, null, unlockedBulkUnlocks));
	}

	private IEnumerator ShowAchievementSummaryAndChangeScene(bool isGoingToCharacterSelect)
	{
		Player player = GameStatics.GetPlayer();
		if (player.CurrentRunProgress.Challenge == null)
		{
			List<Item> list = (from achievement in player.CurrentRunProgress.CurrentRunStatistics.AchievementsEarned
				select achievement.TypeOfItemUnlocked into itemType
				select (Item)Activator.CreateInstance(itemType) into item
				where item.Rarity != ItemRarity.Unique
				select item).ToList();
			List<Character> charactersUnlocked = player.CurrentRunProgress.CurrentRunStatistics.CharactersUnlocked;
			List<BulkUnlock> bulkUnlocksUnlocked = player.CurrentRunProgress.CurrentRunStatistics.BulkUnlocksUnlocked;
			if (list.Count > 0 || charactersUnlocked.Count > 0 || bulkUnlocksUnlocked.Count > 0)
			{
				yield return StartCoroutine(_unlocksBannerController.Populate(list, charactersUnlocked, null, bulkUnlocksUnlocked));
			}
		}
		else if (player.CurrentRunProgress.IsFirstTimeBeatingChallenge)
		{
			if (player.CurrentRunProgress.Challenge is SpeedrunChallenge)
			{
				yield return StartCoroutine(_unlocksBannerController.Populate(new List<Item>(), new List<Character>(), null, null, isUnlockingSpeedrunMode: true));
			}
			else
			{
				Item item2 = (Item)Activator.CreateInstance(ChallengeRuns.ItemUnlocks[player.CurrentRunProgress.Challenge.GetType()]);
				yield return StartCoroutine(_unlocksBannerController.Populate(new List<Item> { item2 }, new List<Character>()));
			}
		}
		CharacterInfoPanel.SingletonInventoryVisualController.RemovePanel();
		if (isGoingToCharacterSelect)
		{
			MusicController.OnEndOfEncounter();
			StartCoroutine(_transitionController.AnimateAndTransition((player.CurrentRunProgress.Challenge == null) ? SceneNames.CharacterSelectSceneName : SceneNames.ChallengeRunSceneName));
		}
		else
		{
			MusicController.OnEndOfEncounter();
			StartCoroutine(_transitionController.AnimateAndTransition(SceneNames.MainMenuSceneName));
		}
	}

	public void WaitForWordSubmission()
	{
		_rerollButtonObject.SetActive(value: true);
		_currentWordController.ResetWordAndScoreDisplay();
		if (_awaitingForcedSell)
		{
			SetEncounterThreadStage(EncounterThreadStage.WaitingForForcedSell);
			_currentWordController.DisplayBlockedByBoss();
			StartCoroutine(PulseForcedSell());
			return;
		}
		Player player = GameStatics.GetPlayer();
		ChallengeRun challenge = player.CurrentRunProgress.Challenge;
		bool flag = player.CurrentRunProgress.IsFirstStage();
		if (challenge != null && flag && !_shownChallengeDialogue)
		{
			_challengeDialogueController.ShowStartOfChallengeDialogue();
			_shownChallengeDialogue = true;
		}
		else if (_encounterThreadStage != EncounterThreadStage.ShowingTutorial)
		{
			SetEncounterThreadStage(EncounterThreadStage.WaitingForWordSubmission);
		}
		if (_rerollsForEncounter > 0 && !SaveManager.GetIsPreventingRerollPulse())
		{
			StartCoroutine(RerollReminder(_rerollReminderDelay));
		}
		_unlocksBannerController.StartCheckingAchievements();
	}

	public void WaitForFinalPuzzleSubmission()
	{
		_rerollParent.SetActive(value: false);
		_currentWordController.ResetWordAndScoreDisplay();
		SetEncounterThreadStage(EncounterThreadStage.WaitingForWordSubmission);
	}

	public IEnumerator PulseForcedSell()
	{
		while (_awaitingForcedSell)
		{
			StartCoroutine(PulseBossModifier(typeof(ForcedSell)));
			yield return new WaitForSeconds(2f * GameStatics.GetCurrentAnimationSpeed());
		}
	}

	public void UnfavouriteItemInPlayingFavouritesChallenge(List<Item> items)
	{
		_gridLayoutController.RefreshWobblyTiles();
		GameStatics.GetPlayer();
		if (!_tileSelectionManager.ValidateSelection(_gridData))
		{
			_tileSelectionManager.CancelSelection();
		}
		_tileSelectionManager.PopulateValidityAndScore(isPlayingSound: false, _gridData);
		if (items.Exists((Item item) => item is TwinkleToes) && TwinkleToesSwapAvailable)
		{
			_tileSelectionManager.ResetTwinkleToes();
			TwinkleToesSwapAvailable = false;
		}
		if (items.Exists((Item item) => item is Wheel))
		{
			if (_rerollsForEncounter <= 0)
			{
				_rerollButtonObject.GetComponentInChildren<Button>().interactable = false;
				_rerollLine.SetActive(value: false);
				return;
			}
			string arg = ((GameStatics.GetPlayer().GetUnpackedItemsOfType(typeof(Wheel)).Count > 0) ? "<br> $1 EACH" : "");
			_rerollTMP.SetText(string.Format("<b>{0}</b> <size=18>REROLL{1} <br>REMAINING{2}", _rerollsForEncounter, Item.CheckPlural("S", _rerollsForEncounter), arg));
			_rerollButtonObject.GetComponentInChildren<Button>().interactable = true;
			_rerollLine.SetActive(value: true);
		}
	}

	public IEnumerator SellItem(Item item)
	{
		_gridLayoutController.RefreshWobblyTiles();
		GameStatics.GetPlayer();
		if (!_tileSelectionManager.ValidateSelection(_gridData))
		{
			_tileSelectionManager.CancelSelection();
		}
		_tileSelectionManager.PopulateValidityAndScore(isPlayingSound: false, _gridData);
		if (item is TwinkleToes && TwinkleToesSwapAvailable)
		{
			_tileSelectionManager.ResetTwinkleToes();
			TwinkleToesSwapAvailable = false;
		}
		if (item is Wheel)
		{
			if (_rerollsForEncounter <= 0)
			{
				_rerollButtonObject.GetComponentInChildren<Button>().interactable = false;
				_rerollLine.SetActive(value: false);
			}
			else
			{
				string arg = ((GameStatics.GetPlayer().GetUnpackedItemsOfType(typeof(Wheel)).Count > 0) ? "<br> $1 EACH" : "");
				_rerollTMP.SetText(string.Format("<b>{0}</b> <size=18>REROLL{1} <br>REMAINING{2}", _rerollsForEncounter, Item.CheckPlural("S", _rerollsForEncounter), arg));
				_rerollButtonObject.GetComponentInChildren<Button>().interactable = true;
				_rerollLine.SetActive(value: true);
			}
		}
		if (_awaitingForcedSell && item != null)
		{
			if (IsBossModifierActive(typeof(ForcedSell)) && GetActiveBossModifierOfType(typeof(ForcedSell)).FloorAdjustedModification == 1)
			{
				_awaitingForcedSell = false;
				_encounterSummaryDisplayController.StopHoldingAttackAnimation();
				_currentWordController.ResetWordAndScoreDisplay();
				WaitForWordSubmission();
			}
			else if (item.UpgradeableComponents.Count > 0)
			{
				_awaitingForcedSell = false;
				_encounterSummaryDisplayController.StopHoldingAttackAnimation();
				_currentWordController.ResetWordAndScoreDisplay();
				WaitForWordSubmission();
			}
		}
		if (item.GetSellValue() > 0)
		{
			List<Tile> goldTiles = (from tile in _gridData.GetAvailableTiles()
				where tile.GetTileType() == TileType.Gold
				select tile).ToList();
			yield return StartCoroutine(WaitForTileUpdate(goldTiles));
		}
	}

	private IEnumerator WaitForTileUpdate(List<Tile> goldTiles)
	{
		if (goldTiles.Count < 1)
		{
			yield break;
		}
		EncounterThreadStage previousStage = _encounterThreadStage;
		Debug.Log($"Thread stage before pulsing gold tiles: {previousStage}");
		SetEncounterThreadStage(EncounterThreadStage.WaitingForTileUpdate);
		if (goldTiles != null)
		{
			for (int i = 0; i < goldTiles.Count; i++)
			{
				_gridLayoutController.PopulateTileDetails(goldTiles[i]);
				if (i < goldTiles.Count - 1)
				{
					Debug.Log($"pulsing gold tile {i}");
					StartCoroutine(_gridLayoutController.GetTileObjectFromTile(goldTiles[i]).ActionPulseCoroutine());
				}
				else
				{
					Debug.Log($"waiting for gold tile {i} pulse");
					yield return StartCoroutine(_gridLayoutController.GetTileObjectFromTile(goldTiles[i]).ActionPulseCoroutine());
				}
			}
		}
		Debug.Log($"Gold tiles done, setting thread stage back to: {previousStage}");
		SetEncounterThreadStage(previousStage);
	}

	private IEnumerator RerollReminder(int delay)
	{
		int currentGrid = CurrentGridsGenerated();
		int rerolls = _rerollsForEncounter;
		int tracker = _rerollTracker;
		yield return new WaitForSeconds(delay);
		while (_encounterThreadStage == EncounterThreadStage.WaitingForWordSubmission && currentGrid == CurrentGridsGenerated() && _rerollsForEncounter == rerolls && tracker == _rerollTracker)
		{
			_rerollButtonObject.GetComponent<UIElementGenericAnimations>().ActionPulse(0.2f);
			yield return new WaitForSeconds(delay);
		}
	}

	private IEnumerator ShowScoreCalculation(List<ScoreCalcVizInfo> steps, HistoricWord word, ScorePacket basicScore, ScorePacket finalScore, List<Tile> tiles, IEnumerator bossAnim)
	{
		yield return null;
		Player player = GameStatics.GetPlayer();
		if (tiles.Count >= 25 && player.CurrentRunProgress.Challenge == null)
		{
			bool flag = false;
			if (player.ActiveBossModifiers.Count > 0 && player.ActiveBossModifiers[0] is MichaelBoss && (player.ActiveBossModifiers[0] as MichaelBoss).SummonedBossesDefeated)
			{
				flag = true;
			}
			if (!flag)
			{
				SteamAchievementHandler.AddAchievementToQueue(SteamAchievementHandler.STEAM_ACHIEVEMENT_TWENTY_FIVE_TILES);
			}
		}
		if (!SaveManager.GetIsSilencingMichael())
		{
			(string, Emotions) wordSubmissionQuip = DialogueUtility.GetWordSubmissionQuip(word);
			if (wordSubmissionQuip.Item1 != null)
			{
				yield return StartCoroutine(_dialogueController.DialogueEventCoroutine(wordSubmissionQuip, fadeOverTime: true, leftSide: true, isWordSuggestion: true));
			}
		}
		if (bossAnim != null)
		{
			while (bossAnim.Current as bool? != true)
			{
				yield return null;
			}
		}
		yield return StartCoroutine(DisplayScoreSteps(steps, word, tiles));
		_wordHistorycontroller.AddEntry(_previousWords[_previousWords.Count - 1]);
		_submittedScoreAnimations.SubmitBounce(finalScore);
		_scoreAnimations.SubmitBounce();
		StartCoroutine(_lensDistortionShake.Shake(0.15f, 0.75f));
		ScorePacket newRemainingTarget = _remainingTarget - finalScore;
		if (player.CurrentRunProgress.Challenge is Bullseye)
		{
			newRemainingTarget = newRemainingTarget.GetAbsoluteValue();
		}
		if (player.ActiveBossModifiers.Count > 0 && player.ActiveBossModifiers[0] is MichaelBoss && ((MichaelBoss)player.ActiveBossModifiers[0]).SummonedBossesDefeated)
		{
			newRemainingTarget = new ScorePacket(-1L);
		}
		PersistentSound.SingletonSoundController.ChunkDownScore(newRemainingTarget <= new ScorePacket(0L));
		_rightPanelCharacterController = CharacterInfoPanel.SingletonObject.GetComponentInChildren<PlayerCharacterController>();
		Debug.Log("DISPLAYING SCORE CALCULATION");
		if (newRemainingTarget <= new ScorePacket(0L))
		{
			Debug.Log("WIN");
			if (player.CurrentRunProgress.IsFinalStage() && (player.CurrentRunProgress.Ascension < AscensionLevel.CursedBosses || player.HasFacedUncursedBoss))
			{
				Debug.Log($"Is final stage? {player.CurrentRunProgress.IsFinalStage()}. Ascension? {player.CurrentRunProgress.Ascension}. Has faced uncursed boss? {player.HasFacedUncursedBoss}");
				Debug.Log("WIN WHOLE GAME");
				MusicController.OnWinRun();
			}
			else if (player.ActiveBossModifiers.Count > 0 && player.ActiveBossModifiers[0] is MichaelBoss)
			{
				MichaelBoss michaelBoss = player.ActiveBossModifiers[0] as MichaelBoss;
				if (michaelBoss.SummonedBossesDefeated)
				{
					Debug.Log("DEFEAT MICHAEL");
					MusicController.OnWinMichaelEncounter();
				}
				else
				{
					MusicController.OnWinMichaelPhase(michaelBoss.DraftedModifiers.Count);
				}
			}
			else
			{
				Debug.Log("WIN JUST THIS ENCOUNTER");
				MusicController.OnWinOrLoseEncounter(isWin: true);
			}
			StartCoroutine(_rightPanelCharacterController.AttackCoroutine(finalAttack: true));
		}
		else if (_remainingGrids <= 0)
		{
			MusicController.OnWinOrLoseEncounter(isWin: false);
			StartCoroutine(_rightPanelCharacterController.AttackCoroutine(finalAttack: true));
		}
		else
		{
			StartCoroutine(_rightPanelCharacterController.AttackCoroutine());
		}
		yield return new WaitForSeconds(0.05f * GameStatics.GetCurrentAnimationSpeed());
		_remainingTarget = newRemainingTarget;
		_encounterSummaryDisplayController.UpdateDisplayedTargetValue(_remainingTarget, _totalTarget, player.CurrentRunProgress.Challenge is TwoWrongs);
		yield return new WaitForSeconds(0.8f * GameStatics.GetCurrentAnimationSpeed());
		Achievements.TryUnlockRunStatisticsAchievements();
		Achievements.TryUnlockWordSubmissionAchievements(_gridData, word);
		Achievements.TryUnlockRoundScoringAchievements(word, _totalTarget, finalScore, CurrentGridsGenerated(), _bossModifiers);
		yield return null;
		yield return StartCoroutine(_unlocksBannerController.CheckAchievementsCoroutine());
		if (!SaveManager.IsTutorialComplete() && _remainingGrids <= 0 && _remainingTarget > new ScorePacket(0L))
		{
			TutorialController component = GetComponent<TutorialController>();
			yield return StartCoroutine(component.LostTutorialDialogue());
		}
		else
		{
			StartCoroutine(TryGoToNextGrid());
		}
	}

	private IEnumerator DisplayRealWord(HistoricWord word)
	{
		for (int i = 0; i < word.Tiles.Count; i++)
		{
			StartCoroutine(_currentWordController.WordLetters[i].RevealLetter(word.Words[0][i].ToString().ToUpper()));
			yield return new WaitForSeconds(0.1f);
		}
		yield return new WaitForSeconds(0.8f);
	}

	private IEnumerator DisplayScoreSteps(List<ScoreCalcVizInfo> steps, HistoricWord word, List<Tile> tiles)
	{
		List<ModifierToken> tokens = new List<ModifierToken>();
		Player player = GameStatics.GetPlayer();
		List<Type> inventoryitemTypes = (from item in player.GetAllItems()
			select item.GetType()).ToList();
		Debug.Log(StringSerializer.Serialize(typeof(List<ScoreCalcVizInfo>), steps));
		if (steps.Exists((ScoreCalcVizInfo step) => step.IsShowingTakes))
		{
			foreach (TileSelection item4 in word.TileSelections.Where((TileSelection tileSelection) => tileSelection.SelectionMethod == TileSelectionMethod.ChessTake || tileSelection.SelectionMethod == TileSelectionMethod.EnPassant))
			{
				Tile takenPiece = ((item4.SelectionMethod == TileSelectionMethod.EnPassant) ? item4.EnPassantedTile : item4.SelectedTile);
				Tile selectedTile = word.TileSelections[word.TileSelections.IndexOf(item4) - 1].SelectedTile;
				yield return StartCoroutine(_specialEventsCanvasController.ShowChessTake(selectedTile, takenPiece, item4.SelectionMethod == TileSelectionMethod.EnPassant));
			}
		}
		List<TileObject> tileObjectsOnGrid = _gridLayoutController.GetTileObjects();
		if (GameStatics.GetPlayer().GetUnpackedItemsOfType(typeof(CableCar)).Count > 0)
		{
			List<Item> list = (from item in GetItemsForWordSubmission(word.TileSelections, isIncludingInventory: false)
				where item.IsSticker()
				select item).ToList();
			foreach (Item item2 in list)
			{
				TileObject tileObject = tileObjectsOnGrid.Find((TileObject to) => to.MyTile.ScatteredItem == item2);
				tileObject.Populate();
				if (tileObject != null)
				{
					tileObject.ActionPulse();
				}
			}
			if (list.Count > 0)
			{
				PersistentSound.SingletonSoundController.PulseItem();
				yield return new WaitForSeconds(1f * GameStatics.GetCurrentAnimationSpeed());
			}
		}
		for (int i = 1; i < steps.Count; i++)
		{
			ScoreCalcVizInfo currentStep = steps[i];
			ScoreCalcVizInfo previousStep = steps[i - 1];
			IEnumerator michaelBossAnim = null;
			if (previousStep.IsSettlingGlitchTiles)
			{
				Dictionary<TileObject, Tile> tilesToAnimate = new Dictionary<TileObject, Tile>();
				foreach (Tile item5 in previousStep.TilesToRepopulate)
				{
					TileObject tileObjectFromCoordinates = _gridLayoutController.GetTileObjectFromCoordinates(item5.Coordinates);
					tileObjectFromCoordinates.MyTile = item5;
					tilesToAnimate[tileObjectFromCoordinates] = item5;
				}
				yield return new WaitForSeconds(0.15f * GameStatics.GetCurrentAnimationSpeed());
				foreach (KeyValuePair<TileObject, Tile> kvp in tilesToAnimate)
				{
					StartCoroutine(kvp.Key.TransformTile(kvp.Value));
					yield return new WaitForSeconds(0.05f * GameStatics.GetCurrentAnimationSpeed());
					if (kvp.Value.HasBeenDestroyed)
					{
						yield return new WaitForSeconds(0.3f * GameStatics.GetCurrentAnimationSpeed());
					}
				}
				ScorePacket basicValueScore = ScoreCalculation.GetBasicValueScore(previousStep.WordTileSelections);
				_currentWordController.DisplayWordAndScore(previousStep.WordTileSelections.Select((TileSelection tile) => tile.SelectedTile).ToList(), previousStep.WordTileSelections, WordValidity.Submitted, basicValueScore);
				_currentWordController.DisplayScores();
				yield return new WaitForSeconds(0.75f * GameStatics.GetCurrentAnimationSpeed());
				continue;
			}
			if (currentStep.RelevantItem != null)
			{
				ItemObject itemObject2 = CharacterInfoPanel.SingletonInventoryVisualController.GetItemObjects().Find((ItemObject itemObject) => itemObject.MyItem == currentStep.RelevantItem);
				if (itemObject2 != null)
				{
					itemObject2.ActionPulse(1f);
					CharacterInfoPanel.SingletonInventoryVisualController.RefreshInspect();
					PersistentSound.SingletonSoundController.PulseItem();
				}
				else
				{
					TileObject tileObject2 = tileObjectsOnGrid.Find((TileObject to) => to.MyTile.ScatteredItem == currentStep.RelevantItem);
					if (tileObject2 != null)
					{
						tileObject2.ActionPulse();
						PersistentSound.SingletonSoundController.PulseItem();
					}
				}
				yield return new WaitForSeconds(0.3f * GameStatics.GetCurrentAnimationSpeed());
			}
			int change = currentStep.Money - player.Money;
			player.ChangeMoney(change);
			CharacterInfoPanel.SingletonInventoryVisualController.PopulateCash();
			foreach (KeyValuePair<string, int> item6 in currentStep.EarningsBreakdown)
			{
				if (item6.Value != 0)
				{
					if (!_earningsBreakdown.ContainsKey(item6.Key))
					{
						_earningsBreakdown[item6.Key] = item6.Value;
					}
					else
					{
						_earningsBreakdown[item6.Key] += item6.Value;
					}
				}
			}
			if (currentStep.IsPulsingMoney)
			{
				CharacterInfoPanel.SingletonInventoryVisualController.CashGenericAnimations.ActionPulse(1f);
				yield return new WaitForSeconds(0.15f * GameStatics.GetCurrentAnimationSpeed());
			}
			if (currentStep.BossModifierToPulse != null)
			{
				michaelBossAnim = PulseBossModifier(currentStep.BossModifierToPulse);
				StartCoroutine(michaelBossAnim);
			}
			if (currentStep.IsPulsingGridNumber)
			{
				if (currentStep.GridNumberChange != 0)
				{
					_totalGridsPerRound += currentStep.GridNumberChange;
					_remainingGrids += currentStep.GridNumberChange;
					_encounterSummaryDisplayController.UpdateRoundSummary(CurrentGridsGenerated(), _totalGridsPerRound);
				}
				_gridNumberGenericAnimations.ActionPulse(1f);
				yield return new WaitForSeconds(0.15f * GameStatics.GetCurrentAnimationSpeed());
			}
			if (currentStep.PokerHand != 0)
			{
				Debug.Log($"POKER HAND : {currentStep.PokerHand}");
				Debug.Log("POKER HAND TILES : " + StringSerializer.Serialize(typeof(List<Tile>), currentStep.PokerHandTiles));
				yield return StartCoroutine(_specialEventsCanvasController.ShowPokerHandSubmission(currentStep.PokerHandTiles, currentStep.PokerHand));
			}
			if (currentStep.ItemTypeToAddToInventory != null && !inventoryitemTypes.Contains(currentStep.ItemTypeToAddToInventory))
			{
				player.AddItemToInventory(Activator.CreateInstance(currentStep.ItemTypeToAddToInventory) as Item);
				inventoryitemTypes.Add(currentStep.ItemTypeToAddToInventory);
				CharacterInfoPanel.SingletonInventoryVisualController.PopulateStamps();
				CharacterInfoPanel.SingletonInventoryVisualController.PopulateStickers();
				yield return new WaitForSeconds(0.3f * GameStatics.GetCurrentAnimationSpeed());
			}
			if (currentStep.IsPulsingWholeWord)
			{
				foreach (WordLetterController wordLetter in _currentWordController.WordLetters)
				{
					wordLetter.ActionPulse(1f, -1);
				}
				yield return new WaitForSeconds(0.4f * GameStatics.GetCurrentAnimationSpeed());
			}
			else if (currentStep.LettersInWordToPulse.Count > 0 || currentStep.LettersOnGridToPulse.Count > 0)
			{
				List<Tile> uniqueLettersInWordToPulse = new List<Tile>();
				List<Tile> uniqueLettersOnGridToPulse = new List<Tile>();
				foreach (Tile item7 in currentStep.LettersInWordToPulse)
				{
					if (!uniqueLettersInWordToPulse.Contains(item7))
					{
						uniqueLettersInWordToPulse.Add(item7);
					}
				}
				foreach (Tile item8 in currentStep.LettersOnGridToPulse)
				{
					if (!uniqueLettersOnGridToPulse.Contains(item8))
					{
						uniqueLettersOnGridToPulse.Add(item8);
					}
				}
				int wordPulseCount = uniqueLettersInWordToPulse.Count;
				int gridPulseCount2 = uniqueLettersOnGridToPulse.Count;
				int j;
				for (j = 0; j < Mathf.Max(wordPulseCount, gridPulseCount2); j++)
				{
					if (wordPulseCount > j)
					{
						_currentWordController.WordLetters.Where((WordLetterController letter) => letter != null).ToList().Find((WordLetterController letter) => letter.GetTile() == uniqueLettersInWordToPulse[j])?.ActionPulse(1f, -1);
					}
					if (gridPulseCount2 > j)
					{
						_gridLayoutController.GetTileObjectFromTile(uniqueLettersOnGridToPulse[j]).ActionPulse();
					}
					yield return new WaitForSeconds(0.05f * GameStatics.GetCurrentAnimationSpeed());
				}
				yield return new WaitForSeconds(0.4f * GameStatics.GetCurrentAnimationSpeed());
			}
			if (currentStep.WordBonus != null)
			{
				WordBonusToken wordBonus = currentStep.WordBonus;
				ModifierTokenType modifierTokenType = (wordBonus.IsPoison ? ModifierTokenType.Poison : ((!wordBonus.IsMultiplicative) ? ModifierTokenType.Additive : ModifierTokenType.Multiplicative));
				modifierTokenType = ((wordBonus is ConditionalWordBonusToken) ? ModifierTokenType.Conditional : modifierTokenType);
				Item item3 = ((modifierTokenType == ModifierTokenType.Conditional) ? currentStep.RelevantItem : null);
				string arg = "+";
				if (wordBonus.Bonus.IsInfinite)
				{
					if (wordBonus.Bonus.IsNegative)
					{
						arg = "";
					}
				}
				else
				{
					arg = ((wordBonus.Bonus.Score >= 0) ? "+" : "");
				}
				string text = (wordBonus.Bonus.IsInfinite ? wordBonus.Bonus.ToString() : ((float)wordBonus.Bonus.Score / 100f).ToString());
				string text2 = (wordBonus.IsMultiplicative ? ("×" + text) : $"{arg}{wordBonus.Bonus}");
				text2 = ((modifierTokenType == ModifierTokenType.Conditional) ? null : text2);
				ModifierToken component = UnityEngine.Object.Instantiate(_scoreTokenPrefab, _scoreTokenParent).GetComponent<ModifierToken>();
				component.Populate(wordBonus, modifierTokenType, item3, text2);
				tokens.Add(component);
				PersistentSound.SingletonSoundController.WordTokenPopup();
				yield return new WaitForSeconds(0.2f * GameStatics.GetCurrentAnimationSpeed());
				TryUnlockDango(currentStep);
				yield return null;
				yield return StartCoroutine(_unlocksBannerController.CheckAchievementsCoroutine());
				yield return new WaitForSeconds(0.2f * GameStatics.GetCurrentAnimationSpeed());
			}
			bool isAnimatingTileScoreChanges = false;
			for (int gridPulseCount2 = 0; gridPulseCount2 < currentStep.TileScores.Count; gridPulseCount2++)
			{
				ScorePacket scorePacket = currentStep.TileScores[gridPulseCount2] - previousStep.TileScores[gridPulseCount2];
				if (scorePacket != new ScorePacket(0L))
				{
					WordLetterController wordLetterController = _currentWordController.WordLetters[gridPulseCount2];
					wordLetterController.UpdateScoreViz(currentStep.TileScores[gridPulseCount2], gridPulseCount2);
					wordLetterController.LetterScoreToken.gameObject.SetActive(value: true);
					if (currentStep.IsUsingFloatMultipliers)
					{
						wordLetterController.LetterScoreToken.Populate(scorePacket, currentStep.TileScoreMultiplierFloats[gridPulseCount2]);
					}
					else
					{
						wordLetterController.LetterScoreToken.Populate(scorePacket, currentStep.TileScoreMultipliers[gridPulseCount2]);
					}
					wordLetterController.LetterScoreToken.Splash();
					isAnimatingTileScoreChanges = true;
					PersistentSound.SingletonSoundController.LetterTokenPopup();
					yield return new WaitForSeconds(0.15f * GameStatics.GetCurrentAnimationSpeed());
				}
			}
			if (isAnimatingTileScoreChanges)
			{
				yield return new WaitForSeconds(0.3f * GameStatics.GetCurrentAnimationSpeed());
			}
			ScorePacket scorePacket2 = currentStep.TileScores.Sum();
			ScorePacket scorePacket3 = previousStep.TileScores.Sum();
			if (scorePacket2 != scorePacket3)
			{
				_currentWordController.DisplayScore(scorePacket2);
				_currentWordController.CurrentScoreActionPulse(1f);
				StartCoroutine(_ramper.RampToNewAmount(0.15f));
				PersistentSound.SingletonSoundController.PulseScoreChange();
				yield return new WaitForSeconds(0.75f * GameStatics.GetCurrentAnimationSpeed());
			}
			if (StringSerializer.Serialize(typeof(Tile[]), currentStep.PlayerConsumableTiles) != StringSerializer.Serialize(typeof(Tile[]), previousStep.PlayerConsumableTiles))
			{
				player.SetInventoryTilesArray(currentStep.PlayerConsumableTiles);
				CharacterInfoPanel.SingletonInventoryVisualController.PopulateTiles();
				CharacterInfoPanel.SingletonInventoryVisualController.RefreshInspect();
				yield return new WaitForSeconds(0.45f * GameStatics.GetCurrentAnimationSpeed());
			}
			if (michaelBossAnim != null)
			{
				while (michaelBossAnim.Current as bool? != true)
				{
					yield return null;
				}
			}
		}
		ScorePacket score = steps[steps.Count - 1].TileScores.Sum();
		foreach (ModifierToken modifierToken in tokens)
		{
			yield return new WaitForSeconds(0.4f * GameStatics.GetCurrentAnimationSpeed());
			WordBonusToken myWordBonusToken = modifierToken.MyWordBonusToken;
			if (myWordBonusToken is ConditionalWordBonusToken)
			{
				ConditionalWordBonusToken conditionalWordBonusToken = myWordBonusToken as ConditionalWordBonusToken;
				if (conditionalWordBonusToken.Condition == WordBonusCondition.WordScoreZero && score != new ScorePacket(0L))
				{
					PersistentSound.SingletonSoundController.ConditionalWordToken(isSuccess: false);
					yield return StartCoroutine(modifierToken.Fail());
					continue;
				}
				if (conditionalWordBonusToken.Condition == WordBonusCondition.WordScoreNegative && score >= new ScorePacket(0L))
				{
					PersistentSound.SingletonSoundController.ConditionalWordToken(isSuccess: false);
					yield return StartCoroutine(modifierToken.Fail());
					continue;
				}
			}
			if (myWordBonusToken.IsMultiplicative)
			{
				if (myWordBonusToken.Bonus.Score == 100 && !myWordBonusToken.Bonus.IsInfinite)
				{
					PersistentSound.SingletonSoundController.ConditionalWordToken(isSuccess: false);
					yield return StartCoroutine(modifierToken.Fail());
					continue;
				}
				score *= myWordBonusToken.Bonus;
				score /= 100L;
			}
			else
			{
				if (myWordBonusToken.Bonus.Score == 0L && !myWordBonusToken.Bonus.IsInfinite)
				{
					PersistentSound.SingletonSoundController.ConditionalWordToken(isSuccess: false);
					yield return StartCoroutine(modifierToken.Fail());
					continue;
				}
				score += myWordBonusToken.Bonus;
			}
			_currentWordController.DisplayScore(score);
			_currentWordController.CurrentScoreActionPulse(1f);
			PersistentSound.SingletonSoundController.ConditionalWordToken(isSuccess: true);
			PersistentSound.SingletonSoundController.PulseScoreChange();
			StartCoroutine(_ramper.RampToNewAmount(0.15f));
			yield return StartCoroutine(modifierToken.Succeed());
		}
		StartCoroutine(_ramper.RampToZero());
		CharacterInfoPanel.SingletonInventoryVisualController.RefreshInspect();
		yield return new WaitForSeconds(0.75f * GameStatics.GetCurrentAnimationSpeed());
	}

	private IEnumerator ShowEndGame(bool isWin, bool isChallengeLoss = false, bool endCredits = false)
	{
		Player player = GameStatics.GetPlayer();
		RunStatistics stats = player.CurrentRunProgress.CurrentRunStatistics;
		stats.Stickers = player.GetStickers(forItemComparison: true);
		stats.Stamps = player.GetStamps(forItemComparison: true);
		if (isWin && player.ActiveBossModifiers.Count > 0 && player.ActiveBossModifiers[0] is MichaelBoss)
		{
			(player.ActiveBossModifiers[0] as MichaelBoss).AllFriendsAgain = true;
		}
		if (player.CurrentRunProgress.Challenge is SpeedrunChallenge || player.CurrentRunProgress.CurrentRunStatistics.IsSpeedrunMode)
		{
			stats.Timer = _topBarController.StopTimerAndGetCurrentTime();
			Debug.Log($"split / run complete / {stats.Timer}");
			if (isWin && player.CurrentRunProgress.Challenge == null)
			{
				SteamAchievementHandler.TryUnlockSpeedrunAchievements(stats.Timer);
			}
		}
		if (isWin)
		{
			stats.EndCondition = EndGameCondition.Win;
			if (SaveManager.AreAscensionsUnlocked() && player.CurrentRunProgress.Challenge == null)
			{
				SaveManager.UpdateHighestAscensionBeaten(player.GetCharacter(), player.CurrentRunProgress.Ascension);
				int num = 3;
				int num2 = 5;
				if (!SaveManager.IsItemUnlocked(typeof(StampPadlock)) && (int)player.CurrentRunProgress.Ascension >= num)
				{
					ItemPools.AddNewlyUnlockedItem(typeof(StampPadlock));
				}
				if (!SaveManager.IsItemUnlocked(typeof(StickerPadlock)) && (int)player.CurrentRunProgress.Ascension >= num2)
				{
					ItemPools.AddNewlyUnlockedItem(typeof(StickerPadlock));
				}
			}
			else if (player.CurrentRunProgress.Challenge == null)
			{
				SaveManager.UpdateHighestAscensionBeaten(player.GetCharacter(), AscensionLevel.None);
			}
		}
		else
		{
			stats.EndCondition = ((player.CurrentRunProgress.GetCurrentNodeType() != NodeType.Boss) ? EndGameCondition.LoseEncounter : EndGameCondition.LoseBoss);
			if (isChallengeLoss)
			{
				stats.EndCondition = EndGameCondition.LoseChallenge;
			}
		}
		Debug.Log($"END GAME CONDITION: {stats.EndCondition}");
		SaveManager.SaveRunHistory(player);
		SaveManager.ClearCurrentRun();
		Achievements.TryUnlockEndOfRunStatisticsAchievements(isWin);
		if (isWin)
		{
			if (GameStatics.GetNumberOfStages() < 5)
			{
				Debug.Log("Not checking end of run achievements as not full run");
			}
			else
			{
				foreach (KeyValuePair<Type, bool> item in GameStatics.GetPlayer().CurrentRunProgress.CurrentRunStatistics.IsFullRunAchievementTypeAvailable)
				{
					if (item.Value)
					{
						Achievements.UnlockAchievement(item.Key);
					}
				}
			}
			Achievements.TryUnlockCrownRewardAchievements();
		}
		yield return null;
		yield return StartCoroutine(_unlocksBannerController.CheckAchievementsCoroutine());
		if (!endCredits)
		{
			_endGameCanvasController.ShowEndGameCanvas(stats);
			yield break;
		}
		_creditsGO.SetActive(value: true);
		SaveManager.AddAchievement(new BlessingOfTheFairiesUnlock());
		ItemPools.AddItemsToPools(new List<Type> { typeof(BlessingOfTheFairies) });
		StartCoroutine(_creditsRoll.RollCredits(stats));
	}

	private void TryUnlockNewspaper()
	{
		if (!Array.Exists(_gridData.GetTiles(), (Tile tile) => !tile.IsTileType(TileType.Red)))
		{
			Achievements.UnlockAchievement(typeof(RedAllOver));
		}
	}

	private void TryUnlockStethoscope()
	{
		if (Array.Exists(_gridData.GetTiles(), (Tile tile) => tile.GetGlyphType() == GlyphType.ScatteredItem && tile.ScatteredItem.UpgradeableComponents.Count > 0 && tile.ScatteredItem.UpgradeableComponents[0].Level >= 4))
		{
			Achievements.UnlockAchievement(typeof(WellEquipped));
		}
	}

	private void TryUnlockFountainPen()
	{
		List<Tile> availableTiles = _gridData.GetAvailableTiles();
		if (availableTiles.Count((Tile tile) => tile.GetTileType() == TileType.Red) >= 3 && availableTiles.Count((Tile tile) => tile.GetTileType() == TileType.Blue) >= 3 && availableTiles.Count((Tile tile) => tile.GetTileType() == TileType.Shiny) >= 3 && availableTiles.Count((Tile tile) => tile.GetTileType() == TileType.Void) >= 3)
		{
			Achievements.UnlockAchievement(typeof(TechnicolourTriumph));
		}
	}

	private void TryUnlockDango(ScoreCalcVizInfo step)
	{
		if (step.WordBonus != null && step.WordBonus.IsMultiplicative && step.WordBonus.Bonus.Score == 0L && !step.WordBonus.Bonus.IsInfinite)
		{
			Achievements.UnlockAchievement(typeof(OhDang));
		}
	}

	private void TryUnlockFrog()
	{
		int i;
		for (i = 1; i <= 9; i++)
		{
			if (!_gridData.GetTiles().ToList().Exists((Tile tile) => tile.GetGlyphType() == GlyphType.Number && tile.GetNumber() == i))
			{
				return;
			}
		}
		Achievements.UnlockAchievement(typeof(Numberphile));
	}

	public void ClearBossModifiers()
	{
		_bossModifiers.Clear();
	}

	private int GetStickerIndexFromBossModifier(Type bossModifierType)
	{
		for (int i = 0; i < _bossModifiers.Count; i++)
		{
			if (_bossModifiers[i].GetType() == bossModifierType)
			{
				return i;
			}
		}
		return -1;
	}

	public IEnumerator PulseBossModifier(Type bossModifierType)
	{
		Player player = GameStatics.GetPlayer();
		if (player.ActiveBossModifiers.Count > 0 && player.ActiveBossModifiers[0] is MichaelBoss)
		{
			int stickerIndexFromBossModifier = GetStickerIndexFromBossModifier(bossModifierType);
			_michaelStickers[stickerIndexFromBossModifier].Pulse();
			yield return StartCoroutine(_encounterSummaryDisplayController.PulseMichael(Activator.CreateInstance(bossModifierType) as BossModifier));
			yield return true;
		}
		else
		{
			_encounterSummaryDisplayController.PulseBossModifier();
			yield return true;
		}
	}
}
