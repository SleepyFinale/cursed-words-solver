using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;
using UnityEngine.UI;

public class PuzzleController : MonoBehaviour
{
	[SerializeField]
	private EncounterSummaryDisplayController _encounterSummaryDisplayController;

	[SerializeField]
	private GridLayoutController _gridLayoutController;

	[SerializeField]
	private CurrentWordController _currentWordController;

	[SerializeField]
	private WordHistoryController _wordHistorycontroller;

	[SerializeField]
	private TileSelectionManager _tileSelectionManager;

	[SerializeField]
	private TransitionController _transitionController;

	[SerializeField]
	private EndPuzzleCanvasController _endPuzzleCanvasController;

	[SerializeField]
	private RectTransform _leftPanelRT;

	[SerializeField]
	private TopBarController _topBarController;

	private TileGridTransitions _tileGridTransitions;

	private GridData _gridData;

	private EncounterThreadStage _encounterThreadStage;

	private FairyGrid _fairyGrid;

	private int _gridDimension = 6;

	private int _totalGridsPerRound = 5;

	private int _remainingGrids;

	private DateTime _today;

	private bool _isTransitioning;

	private void Start()
	{
		GameStatics.SetPlayer(new Player
		{
			CurrentRunProgress = new RunProgress()
		});
		_today = DateTime.Today;
		SettingsMenuController.IsOpen = false;
		AtmosController.OnPuzzleEnter();
		_tileGridTransitions = base.gameObject.AddComponent<TileGridTransitions>();
		_tileGridTransitions.MakeAssignments(_gridLayoutController);
		Vocabulary.SetActiveLanguageVocabulary(SaveManager.GetDictionaryLanguage());
		_remainingGrids = _totalGridsPerRound - 1;
		_currentWordController.SetSkipButtonToBeHidden();
		_currentWordController.ResetWordAndScoreDisplay();
		ForceRebuildLeftPanelLayout();
		BuildGrid();
	}

	public void BuildGrid()
	{
		List<BoardGenVizInfo> gridSteps = GenerateGrid();
		_gridLayoutController.GenerateGrid(new Vector2Int(_gridDimension, _gridDimension));
		StartCoroutine(TransitionGridIn(gridSteps));
	}

	private List<BoardGenVizInfo> GenerateGrid()
	{
		_encounterSummaryDisplayController.UpdateRoundSummary(CurrentGridsGenerated(), _totalGridsPerRound);
		DateTime date = _today.Date;
		System.Random seed = new System.Random(date.Year * 10000 + date.Month * 100 + date.Day);
		_fairyGrid = FairyGridGeneration.GenerateRandomFairyGrid(seed);
		return new List<BoardGenVizInfo>
		{
			new BoardGenVizInfo(_fairyGrid.Grid, null, null, isPulsingMoney: false, null, isPulsingGridNumber: false, basicGridGen: true, isPulsingPreviousWord: false, new Tile[10])
		};
	}

	public int CurrentGridsGenerated()
	{
		return _totalGridsPerRound - _remainingGrids;
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

	private IEnumerator TransitionGridIn(List<BoardGenVizInfo> gridSteps)
	{
		yield return StartCoroutine(_tileGridTransitions.RandomTransitionGridIn(gridSteps[0].Grid, isPuzzleMode: true));
		yield return StartCoroutine(ShowGridGenerationViz(gridSteps));
		WaitForWordSubmission();
	}

	public void WaitForWordSubmission()
	{
		_currentWordController.ResetWordAndScoreDisplay();
		SetEncounterThreadStage(EncounterThreadStage.WaitingForWordSubmission);
	}

	public void SetEncounterThreadStage(EncounterThreadStage newThreadStage)
	{
		_encounterThreadStage = newThreadStage;
	}

	private IEnumerator ShowGridGenerationViz(List<BoardGenVizInfo> gridSteps)
	{
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
		for (int i = 1; i < gridSteps.Count; i++)
		{
			Dictionary<TileObject, Tile> tilesToAnimate = new Dictionary<TileObject, Tile>();
			bool flag = false;
			foreach (TileObject tileObject in _gridLayoutController.GetTileObjects())
			{
				Tile tileAtCoordinates = gridSteps[i].Grid.GetTileAtCoordinates(tileObject.GridCoordinate);
				Tile tileAtCoordinates2 = gridSteps[i - 1].Grid.GetTileAtCoordinates(tileObject.GridCoordinate);
				if (tileAtCoordinates.GetTileType() != tileAtCoordinates2.GetTileType() || tileAtCoordinates.GetStringRepresentation() != tileAtCoordinates2.GetStringRepresentation() || tileAtCoordinates.GetValueForDisplay() != tileAtCoordinates2.GetValueForDisplay() || tileAtCoordinates.GetSuitForDisplay() != tileAtCoordinates2.GetSuitForDisplay())
				{
					tilesToAnimate[tileObject] = tileAtCoordinates;
					flag = true;
				}
			}
			if (flag)
			{
				yield return new WaitForSeconds(0.15f * GameStatics.GetCurrentAnimationSpeed());
				foreach (KeyValuePair<TileObject, Tile> item in tilesToAnimate)
				{
					StartCoroutine(item.Key.TransformTile(item.Value));
					yield return new WaitForSeconds(0.05f * GameStatics.GetCurrentAnimationSpeed());
				}
				yield return new WaitForSeconds(0.75f * GameStatics.GetCurrentAnimationSpeed());
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

	public GridData GetGridData()
	{
		return _gridData;
	}

	public bool IsWaitingForWordSubmission()
	{
		if (_encounterThreadStage == EncounterThreadStage.WaitingForWordSubmission)
		{
			return !SettingsMenuController.IsOpen;
		}
		return false;
	}

	public void SubmitWord(List<TileSelection> tiles)
	{
		_tileSelectionManager.SelectionCancelledCallback();
		SetEncounterThreadStage(EncounterThreadStage.ExecutingWordConsequences);
		PersistentSound.SingletonSoundController.SubmitWord();
		StartCoroutine(CheckAnswer(tiles));
	}

	public IEnumerator CheckAnswer(List<TileSelection> tiles)
	{
		List<Vector2Int> solutionCoordinates = _fairyGrid.Solution.Select((Tile solutionTile) => solutionTile.Coordinates).ToList();
		List<TileSolutionState> solutionStates = new List<TileSolutionState>();
		bool isCorrectSolution = tiles.Count == solutionCoordinates.Count;
		for (int i = 0; i < tiles.Count; i++)
		{
			Tile tile2 = tiles[i].SelectedTile;
			TileObject tileObjectFromTile = _gridLayoutController.GetTileObjectFromTile(tile2);
			bool num = solutionCoordinates.Exists((Vector2Int solnCoord) => solnCoord.Equals(tile2.Coordinates));
			Vector2Int vector2Int = solutionCoordinates.Find((Vector2Int solnCoord) => solnCoord.Equals(tile2.Coordinates));
			Debug.Log(vector2Int);
			TileSolutionState tileSolutionState;
			if (num)
			{
				tileSolutionState = ((solutionCoordinates.IndexOf(vector2Int) == i) ? TileSolutionState.CorrectPosition : TileSolutionState.IncorrectPosition);
				if (tileSolutionState == TileSolutionState.IncorrectPosition)
				{
					isCorrectSolution = false;
				}
			}
			else
			{
				tileSolutionState = (_fairyGrid.Solution.Exists((Tile fairyTile) => GridUtility.Singleton.AreAdjacentTiles(fairyTile, tile2)) ? TileSolutionState.AdjacentToPosition : TileSolutionState.Incorrect);
				isCorrectSolution = false;
			}
			solutionStates.Add(tileSolutionState);
			if (i == tiles.Count - 1)
			{
				yield return StartCoroutine(SpinAndRepopulateTile(tileObjectFromTile, tileSolutionState));
			}
			else
			{
				StartCoroutine(SpinAndRepopulateTile(tileObjectFromTile, tileSolutionState));
			}
		}
		_wordHistorycontroller.AddPuzzleEntry(tiles.Select((TileSelection tile) => tile.SelectedTile).ToList(), solutionStates);
		if (isCorrectSolution)
		{
			SaveManager.SetMostRecentPuzzleDate(_today.Date);
			HistoricWord solutionWord = new HistoricWord(_fairyGrid.Solution, new List<string> { _fairyGrid.SolutionWord }, isWordSkipped: false);
			SteamAchievementHandler.AddAchievementToQueue("ACH_CURSEDLE");
			yield return new WaitForSeconds(1f);
			StartCoroutine(_endPuzzleCanvasController.Populate(isWin: true, solutionWord, _totalGridsPerRound - _remainingGrids));
		}
		else if (_remainingGrids == 0)
		{
			SaveManager.SetMostRecentPuzzleDate(_today.Date);
			HistoricWord solutionWord = new HistoricWord(_fairyGrid.Solution, new List<string> { _fairyGrid.SolutionWord }, isWordSkipped: false);
			yield return new WaitForSeconds(1f);
			StartCoroutine(_endPuzzleCanvasController.Populate(isWin: false, solutionWord, 0));
			yield return new WaitForSeconds(0.25f);
			PersistentSound.SingletonSoundController.MichaelFightDramaticBeat(1);
		}
		else
		{
			_remainingGrids--;
			_encounterSummaryDisplayController.UpdateRoundSummary(CurrentGridsGenerated(), _totalGridsPerRound);
			SetEncounterThreadStage(EncounterThreadStage.WaitingForWordSubmission);
		}
	}

	private IEnumerator SpinAndRepopulateTile(TileObject gridTileObject, TileSolutionState solutionState)
	{
		yield return gridTileObject.SpinToSide();
		gridTileObject.PopulatePuzzleColour(solutionState);
		yield return gridTileObject.SpinFromSide(isAmbientFloating: false);
	}

	public void MainMenuButtonCallback()
	{
		if (!_isTransitioning)
		{
			_isTransitioning = true;
			_topBarController.UnsubscribeFromEvents();
			AtmosController.OnPuzzleExit();
			_transitionController.TransitionToNewScene(SceneNames.MainMenuSceneName);
		}
	}
}
