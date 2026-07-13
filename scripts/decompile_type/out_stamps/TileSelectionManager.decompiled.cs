using System.Collections.Generic;
using System.Linq;
using UnityEngine;
using UnityEngine.SceneManagement;

public class TileSelectionManager : MonoBehaviour
{
	[SerializeField]
	private WordPathLine _wordPathLine;

	private CurrentWordController _currentWordController;

	private EncounterController _encounterController;

	private PuzzleController _puzzleController;

	private GridLayoutController _gridLayoutController;

	private TileAnimationManager _tileAnimationManager;

	private List<TileSelection> _selectedTiles = new List<TileSelection>();

	private bool _isRollingBackSelectedTile = true;

	private bool _isInputBlocked;

	private bool _isFinalPuzzleGrid;

	private MichaelVolumeController _michaelVolumeController;

	private List<Tile> _twinkleToesTilesToSwap = new List<Tile>();

	[SerializeField]
	private GameObject _submitButtonGO;

	[SerializeField]
	private GameObject _submitPopGO;

	[SerializeField]
	private GameObject _rerollButtonObj;

	private void Start()
	{
		_currentWordController = GetComponent<CurrentWordController>();
		_encounterController = GetComponent<EncounterController>();
		_puzzleController = GetComponent<PuzzleController>();
		_tileAnimationManager = GetComponent<TileAnimationManager>();
		_gridLayoutController = Object.FindObjectsByType<GridLayoutController>(FindObjectsSortMode.None)[0];
	}

	public void SetIsInputBlocked(bool isInputBlocked)
	{
		_isInputBlocked = isInputBlocked;
	}

	public void ResetTwinkleToes()
	{
		_twinkleToesTilesToSwap.Clear();
		ShowTwinkleToesTiles();
	}

	private bool IsTileInSelectedTiles(Tile tile)
	{
		return _selectedTiles.Exists((TileSelection selectedTile) => selectedTile.SelectedTile == tile);
	}

	public List<Tile> GetTilesFromSelectedTiles()
	{
		return _selectedTiles.Select((TileSelection selectedTile) => selectedTile.SelectedTile).ToList();
	}

	public void TileClickedCallback(Tile clickedTile, bool isDragging, GridData gridData = null)
	{
		if (_isInputBlocked || clickedTile.IsCrossedOut || clickedTile.IsEmpty() || (_encounterController != null && !_encounterController.IsWaitingForWordSubmission()) || (_puzzleController != null && !_puzzleController.IsWaitingForWordSubmission()))
		{
			return;
		}
		if (_encounterController != null && _encounterController.TwinkleToesSwapAvailable)
		{
			if (!isDragging)
			{
				if (!_twinkleToesTilesToSwap.Contains(clickedTile))
				{
					_twinkleToesTilesToSwap.Add(clickedTile);
					ShowTwinkleToesTiles();
				}
				if (_twinkleToesTilesToSwap.Count == 2)
				{
					_encounterController.SwapTwinkleToesTiles(_twinkleToesTilesToSwap);
				}
			}
		}
		else if (!isDragging || _selectedTiles.Count <= 0 || clickedTile != _selectedTiles[_selectedTiles.Count - 1].SelectedTile)
		{
			if (_encounterController != null)
			{
				gridData = ((gridData == null) ? _encounterController.GetGridData() : gridData);
			}
			else if (_puzzleController != null)
			{
				gridData = ((gridData == null) ? _puzzleController.GetGridData() : gridData);
			}
			TileSelection tileSelection = GridUtility.Singleton.GetValidNextTiles(gridData, GetTilesFromSelectedTiles(), this).Find((TileSelection validSelection) => validSelection.SelectedTile == clickedTile);
			if (IsTileInSelectedTiles(clickedTile))
			{
				RollBackSelectionToClickedTile(clickedTile, isDragging);
			}
			else if (tileSelection != null)
			{
				AppendClickedTileToSelection(tileSelection);
			}
			else if (!isDragging && (!SaveManager.GetIsPreventingClickingInvalidTiles() || _selectedTiles.Count == 0))
			{
				StartNewSelection(clickedTile);
			}
			if (_selectedTiles.Count > 0)
			{
				EditTileLightLayers(gridData);
			}
			Debug.Log($"{_selectedTiles.Count} selected tiles");
			PopulateValidityAndScore(_selectedTiles.Count > 0 && IsTileInSelectedTiles(clickedTile), gridData);
		}
	}

	public void ETileClick(Vector2Int clickedTileCoords)
	{
		Tile clickedTile = _gridLayoutController.GetTileFromCoordinates(clickedTileCoords);
		TileSelection tileSelection = GridUtility.Singleton.GetValidNextTiles(_encounterController.GetGridData(), GetTilesFromSelectedTiles(), this).Find((TileSelection validSelection) => validSelection.SelectedTile == clickedTile);
		if (tileSelection != null)
		{
			AppendClickedTileToSelection(tileSelection);
		}
		if (_selectedTiles.Count == 0)
		{
			List<TileObject> tileObjectsFromTiles = _gridLayoutController.GetTileObjectsFromTiles(GetTilesFromSelectedTiles());
			_selectedTiles.Add(new TileSelection(clickedTile, TileSelectionMethod.Initial, clickedTile.IsDisplayingAsVariableLetter()));
			PersistentSound.SingletonSoundController.TileOnBoardSelected(clickedTile, GetTilesFromSelectedTiles());
			List<TileObject> tileObjectsFromTiles2 = _gridLayoutController.GetTileObjectsFromTiles(new List<Tile> { clickedTile });
			_tileAnimationManager.ChangeSelectedTiles(tileObjectsFromTiles2, tileObjectsFromTiles);
			_wordPathLine.PopulateLine(_gridLayoutController.GetTileObjectsFromTiles(_selectedTiles));
			List<TileObject> tileObjects = _gridLayoutController.GetTileObjects();
			tileObjects.Remove(tileObjectsFromTiles2[0]);
			if (0 == 0)
			{
				_tileAnimationManager.EndAmbientFloating(tileObjects);
				_gridLayoutController.PunchInGrid();
			}
			if (_isFinalPuzzleGrid && _michaelVolumeController != null)
			{
				_michaelVolumeController.ChangeIntensity(_selectedTiles.Count);
			}
		}
		if (_selectedTiles.Count > 0)
		{
			EditTileLightLayers(_encounterController.GetGridData());
		}
		PopulateValidityAndScore(_selectedTiles.Count > 0 && IsTileInSelectedTiles(clickedTile), _encounterController.GetGridData());
	}

	public void ESubmitWord()
	{
		_submitButtonGO.SetActive(value: false);
		_submitPopGO.SetActive(value: false);
		_submitPopGO.SetActive(value: true);
		_rerollButtonObj.SetActive(value: false);
		List<string> list = new List<string>();
		string validWordFromTiles = Vocabulary.GetValidWordFromTiles(GetTilesFromSelectedTiles(), _encounterController.GetBossModifiers());
		if (validWordFromTiles != null)
		{
			list.Add(validWordFromTiles);
			List<Tile> tilesFromSelectedTiles = GetTilesFromSelectedTiles();
			List<TileObject> tileObjectsFromTiles = _gridLayoutController.GetTileObjectsFromTiles(tilesFromSelectedTiles);
			_tileAnimationManager.ChangeSelectedTiles(null, tileObjectsFromTiles);
			_wordPathLine.PopulateLine(new List<TileObject>());
			_encounterController.SubmitWord(new List<TileSelection>(_selectedTiles), list);
			_selectedTiles.Clear();
			_tileAnimationManager.BeginAmbientFloating(_gridLayoutController.GetTileObjects());
			_tileAnimationManager.ResetTileLightLayers(_gridLayoutController.GetTileObjects());
			_gridLayoutController.PunchOutGrid();
		}
	}

	private void EditTileLightLayers(GridData gridData)
	{
		List<TileObject> selectedTiles = _gridLayoutController.GetTileObjectsFromTiles(GetTilesFromSelectedTiles());
		List<TileObject> availableTiles = _gridLayoutController.GetTileObjectsFromTiles(GridUtility.Singleton.GetValidNextTiles(gridData, GetTilesFromSelectedTiles(), this));
		List<TileObject> unavailableTileObjects = (from to in _gridLayoutController.GetTileObjects()
			where !selectedTiles.Contains(to) && !availableTiles.Contains(to)
			select to).ToList();
		_tileAnimationManager.EditTileLightLayers(selectedTiles, availableTiles, unavailableTileObjects);
	}

	private void ShowTwinkleToesTiles()
	{
		List<TileObject> selectedTiles = _gridLayoutController.GetTileObjectsFromTiles(_twinkleToesTilesToSwap);
		List<TileObject> availableTileObjects = (from to in _gridLayoutController.GetTileObjects()
			where !selectedTiles.Contains(to)
			select to).ToList();
		List<TileObject> unavailableTileObjects = new List<TileObject>();
		_tileAnimationManager.EditTileLightLayers(selectedTiles, availableTileObjects, unavailableTileObjects);
	}

	public void ResetGrid()
	{
		_twinkleToesTilesToSwap.Clear();
		CancelSelection();
		GridData gridData = ((_encounterController == null) ? _puzzleController.GetGridData() : _encounterController.GetGridData());
		PopulateValidityAndScore(isPlayingSound: false, gridData);
	}

	public void SelectionCancelledCallback()
	{
		if ((!(_encounterController != null) || _encounterController.IsWaitingForWordSubmission()) && !_isInputBlocked && (!(_puzzleController != null) || _puzzleController.IsWaitingForWordSubmission()))
		{
			Debug.Log("Cancel selection callback hit");
			CancelSelection();
			GridData gridData = ((_encounterController == null) ? _puzzleController.GetGridData() : _encounterController.GetGridData());
			PopulateValidityAndScore(isPlayingSound: false, gridData);
		}
	}

	public void SelectionSubmittedCallback()
	{
		if ((_encounterController != null && !_encounterController.IsWaitingForWordSubmission()) || _isInputBlocked || (_puzzleController != null && !_puzzleController.IsWaitingForWordSubmission()))
		{
			return;
		}
		_submitButtonGO.SetActive(value: false);
		_submitPopGO.SetActive(value: false);
		_submitPopGO.SetActive(value: true);
		if (_rerollButtonObj != null)
		{
			_rerollButtonObj.SetActive(value: false);
		}
		List<string> list = new List<string>();
		Player player = GameStatics.GetPlayer();
		if (_selectedTiles.Count > 0)
		{
			if (_isFinalPuzzleGrid)
			{
				list.Add(Vocabulary.GetRandomTwentyFiveLetterWord());
			}
			else if (player.GetUnpackedItemsOfType(typeof(Honeypot)).Count > 0)
			{
				list = Vocabulary.GetConcatenatedValidWordsFromTiles(GetTilesFromSelectedTiles(), _encounterController.GetBossModifiers());
				if (list == null)
				{
					if (player.CurrentRunProgress.Challenge is Lexographer)
					{
						_encounterController.EndLexographerChallenge(DialogueUtility.FractionFriendlyString(GetTilesFromSelectedTiles()));
					}
					return;
				}
			}
			else
			{
				List<BossModifier> bossModifiers = ((_encounterController == null) ? new List<BossModifier>() : _encounterController.GetBossModifiers());
				string validWordFromTiles = Vocabulary.GetValidWordFromTiles(GetTilesFromSelectedTiles(), bossModifiers);
				if (validWordFromTiles == null)
				{
					if (player.CurrentRunProgress.Challenge is Lexographer)
					{
						_encounterController.EndLexographerChallenge(DialogueUtility.FractionFriendlyString(GetTilesFromSelectedTiles()));
					}
					return;
				}
				list.Add(validWordFromTiles);
			}
			List<Tile> tilesFromSelectedTiles = GetTilesFromSelectedTiles();
			List<TileObject> tileObjectsFromTiles = _gridLayoutController.GetTileObjectsFromTiles(tilesFromSelectedTiles);
			_tileAnimationManager.ChangeSelectedTiles(null, tileObjectsFromTiles);
			_wordPathLine.PopulateLine(new List<TileObject>());
			if (_encounterController != null)
			{
				_encounterController.SubmitWord(new List<TileSelection>(_selectedTiles), list);
			}
			else if (_puzzleController != null)
			{
				_puzzleController.SubmitWord(new List<TileSelection>(_selectedTiles));
			}
			_selectedTiles.Clear();
		}
		else
		{
			_encounterController.SkipWordSubmission();
		}
		_tileAnimationManager.BeginAmbientFloating(_gridLayoutController.GetTileObjects());
		_tileAnimationManager.ResetTileLightLayers(_gridLayoutController.GetTileObjects());
		_gridLayoutController.PunchOutGrid();
	}

	public void RerollButtonCallback()
	{
		if (_encounterController.IsWaitingForWordSubmission() && !_isInputBlocked && _encounterController.TryReroll())
		{
			CancelSelection();
			PopulateValidityAndScore(isPlayingSound: false, _encounterController.GetGridData());
		}
	}

	private void RollBackSelectionToClickedTile(Tile clickedTile, bool isDragging)
	{
		List<TileSelection> list = new List<TileSelection>();
		int num = GetTilesFromSelectedTiles().IndexOf(clickedTile);
		if (_isRollingBackSelectedTile && !isDragging)
		{
			for (int num2 = _selectedTiles.Count - 1; num2 >= num; num2--)
			{
				list.Add(_selectedTiles[num2]);
				_selectedTiles.RemoveAt(num2);
			}
		}
		else
		{
			for (int num3 = _selectedTiles.Count - 1; num3 > num; num3--)
			{
				list.Add(_selectedTiles[num3]);
				_selectedTiles.RemoveAt(num3);
			}
		}
		PersistentSound.SingletonSoundController.RollBackToTileOnBoard(GetTilesFromSelectedTiles());
		_tileAnimationManager.ChangeSelectedTiles(null, _gridLayoutController.GetTileObjectsFromTiles(list.Select((TileSelection removedTile) => removedTile.SelectedTile).ToList()));
		_wordPathLine.PopulateLine(_gridLayoutController.GetTileObjectsFromTiles(GetTilesFromSelectedTiles()));
		if (_selectedTiles.Count == 0)
		{
			_tileAnimationManager.BeginAmbientFloating(_gridLayoutController.GetTileObjects());
			_tileAnimationManager.ResetTileLightLayers(_gridLayoutController.GetTileObjects());
			_gridLayoutController.PunchOutGrid();
		}
		if (_isFinalPuzzleGrid && _michaelVolumeController != null)
		{
			_michaelVolumeController.ChangeIntensity(_selectedTiles.Count);
		}
	}

	public void ResetTileLightLayers()
	{
		_tileAnimationManager.ResetTileLightLayers(_gridLayoutController.GetTileObjects());
	}

	private void AppendClickedTileToSelection(TileSelection selectedTile)
	{
		_selectedTiles.Add(selectedTile);
		PersistentSound.SingletonSoundController.TileOnBoardSelected(selectedTile.SelectedTile, GetTilesFromSelectedTiles());
		_tileAnimationManager.ChangeSelectedTiles(_gridLayoutController.GetTileObjectsFromTiles(new List<Tile> { selectedTile.SelectedTile }), null);
		_wordPathLine.PopulateLine(_gridLayoutController.GetTileObjectsFromTiles(GetTilesFromSelectedTiles()));
		if (_isFinalPuzzleGrid && _michaelVolumeController != null)
		{
			_michaelVolumeController.ChangeIntensity(_selectedTiles.Count);
		}
	}

	private void StartNewSelection(Tile clickedTile)
	{
		bool num = _selectedTiles.Count > 0;
		List<TileObject> tileObjectsFromTiles = _gridLayoutController.GetTileObjectsFromTiles(GetTilesFromSelectedTiles());
		_selectedTiles.Clear();
		_selectedTiles.Add(new TileSelection(clickedTile, TileSelectionMethod.Initial, clickedTile.IsDisplayingAsVariableLetter()));
		PersistentSound.SingletonSoundController.TileOnBoardSelected(clickedTile, GetTilesFromSelectedTiles());
		List<TileObject> tileObjectsFromTiles2 = _gridLayoutController.GetTileObjectsFromTiles(new List<Tile> { clickedTile });
		_tileAnimationManager.ChangeSelectedTiles(tileObjectsFromTiles2, tileObjectsFromTiles);
		_wordPathLine.PopulateLine(_gridLayoutController.GetTileObjectsFromTiles(_selectedTiles));
		List<TileObject> tileObjects = _gridLayoutController.GetTileObjects();
		tileObjects.Remove(tileObjectsFromTiles2[0]);
		if (!num)
		{
			_tileAnimationManager.EndAmbientFloating(tileObjects);
			_gridLayoutController.PunchInGrid();
		}
		if (_isFinalPuzzleGrid && _michaelVolumeController != null)
		{
			_michaelVolumeController.ChangeIntensity(_selectedTiles.Count);
		}
	}

	public void TryStartAmbientFloating()
	{
		if (_encounterController.GetCurrentEncounterThreadStage() == EncounterThreadStage.WaitingForWordSubmission && _selectedTiles.Count == 0)
		{
			_tileAnimationManager.BeginAmbientFloating(_gridLayoutController.GetTileObjects());
		}
	}

	public void TryEndAmbientFloating()
	{
		if (_encounterController.GetCurrentEncounterThreadStage() == EncounterThreadStage.WaitingForWordSubmission && _selectedTiles.Count == 0)
		{
			_tileAnimationManager.EndAmbientFloating(_gridLayoutController.GetTileObjects());
		}
	}

	public void CancelSelection()
	{
		List<TileObject> tileObjectsFromTiles = _gridLayoutController.GetTileObjectsFromTiles(_selectedTiles);
		PersistentSound.SingletonSoundController.RollBackToTileOnBoard(new List<Tile>());
		_selectedTiles.Clear();
		_tileAnimationManager.ChangeSelectedTiles(null, tileObjectsFromTiles);
		_wordPathLine.PopulateLine(_gridLayoutController.GetTileObjectsFromTiles(_selectedTiles));
		_tileAnimationManager.BeginAmbientFloating(_gridLayoutController.GetTileObjects());
		_tileAnimationManager.ResetTileLightLayers(_gridLayoutController.GetTileObjects());
		_gridLayoutController.PunchOutGrid();
		if (_isFinalPuzzleGrid && _michaelVolumeController != null)
		{
			_michaelVolumeController.ChangeIntensity(_selectedTiles.Count);
		}
	}

	public bool ValidateSelection(GridData gridData)
	{
		if (_selectedTiles.Count == 0)
		{
			return true;
		}
		if (_selectedTiles.Count == 1)
		{
			EditTileLightLayers(gridData);
			return true;
		}
		_gridLayoutController.GetTileObjectsFromTiles(_selectedTiles);
		List<TileSelection> list = new List<TileSelection> { _selectedTiles[0] };
		_selectedTiles[0].SelectionMethod = TileSelectionMethod.Initial;
		int i;
		for (i = 1; i < _selectedTiles.Count; i++)
		{
			TileSelection tileSelection = GridUtility.Singleton.GetValidNextTiles(_encounterController.GetGridData(), list.Select((TileSelection validationTile) => validationTile.SelectedTile).ToList(), this).Find((TileSelection validNextTile) => validNextTile.SelectedTile == _selectedTiles[i].SelectedTile);
			if (tileSelection == null)
			{
				return false;
			}
			list.Add(tileSelection);
		}
		_selectedTiles = list;
		EditTileLightLayers(gridData);
		return true;
	}

	public void PopulateValidityAndScore(bool isPlayingSound, GridData gridData)
	{
		Player player = GameStatics.GetPlayer();
		List<Tile> tiles = GetTilesFromSelectedTiles();
		List<BossModifier> list = ((_encounterController == null) ? new List<BossModifier>() : _encounterController.GetBossModifiers());
		ChallengeRun challengeRun = ((player.CurrentRunProgress == null) ? null : player.CurrentRunProgress.Challenge);
		WordValidity wordValidity = ((Vocabulary.GetValidWordFromTiles(tiles, list) == null) ? WordValidity.Invalid : WordValidity.Valid);
		if (player.ActiveBossModifiers.Count > 0 && player.ActiveBossModifiers[0] is MichaelBoss && (player.ActiveBossModifiers[0] as MichaelBoss).SummonedBossesDefeated)
		{
			if (GetTilesFromSelectedTiles().Count < 25)
			{
				wordValidity = WordValidity.BlockedByBoss;
			}
			else
			{
				bool flag = true;
				InventoryCache inventoryCache = new InventoryCache(tiles);
				for (int i = 0; i < tiles.Count; i++)
				{
					if (!tiles[i].IsWildcard(i, tiles, inventoryCache))
					{
						flag = false;
						break;
					}
				}
				wordValidity = ((!flag) ? WordValidity.Invalid : WordValidity.Valid);
			}
		}
		else
		{
			if (wordValidity == WordValidity.Invalid && player.GetUnpackedItemsOfType(typeof(Honeypot)).Count > 0 && Vocabulary.GetConcatenatedValidWordsFromTiles(tiles, list) != null)
			{
				wordValidity = WordValidity.Valid;
			}
			if (wordValidity != WordValidity.Valid)
			{
				wordValidity = Vocabulary.CheckInvalidityReason(tiles, list);
			}
			Vector2Int dimensions = gridData.GetDimensions();
			if (tiles.Count > 0 && challengeRun is UpAndUp && !tiles.Exists((Tile tile) => tile.GetCoordinates() == new Vector2Int(dimensions.x / 2, dimensions.y / 2)))
			{
				wordValidity = WordValidity.BlockedByChallenge;
			}
			else if (tiles.Count > 0 && challengeRun is Chromaphobia && tiles.Exists((Tile tile) => tile.GetTileType() != TileType.Normal))
			{
				wordValidity = WordValidity.BlockedByChallenge;
			}
			else if (tiles.Count > 0 && challengeRun is Cursophobia && tiles.Exists((Tile tile) => tile.IsCursed()))
			{
				wordValidity = WordValidity.BlockedByChallenge;
			}
			else if (tiles.Count > 0 && challengeRun is Chromaphilia && tiles.Exists((Tile tile) => tile.GetTileType() == TileType.Normal))
			{
				wordValidity = WordValidity.BlockedByChallenge;
			}
			else if (tiles.Count > 0 && list.Exists((BossModifier boss) => boss is SandySaguaroBoss) && ((SandySaguaroBoss)_encounterController.GetActiveBossModifierOfType(typeof(SandySaguaroBoss))).CurrentlyActiveConsumableTiles.Exists((Tile tile) => !tiles.Exists((Tile wordTile) => wordTile.IsCopy(tile))))
			{
				wordValidity = WordValidity.BlockedByBoss;
			}
		}
		ScorePacket basicValueScore = ScoreCalculation.GetBasicValueScore(_selectedTiles);
		_gridLayoutController.RefreshWobblyTiles();
		foreach (TileSelection selectedTile in _selectedTiles)
		{
			selectedTile.IsWobbly = selectedTile.SelectedTile.IsDisplayingAsVariableLetter(this);
		}
		_currentWordController.DisplayWordAndScore(tiles, _selectedTiles, wordValidity, basicValueScore);
		if (tiles.Count > 0 && tiles[tiles.Count - 1].GetGlyphType() == GlyphType.ScatteredItem && !SaveManager.GetIsPreventingScatteredItemInspection() && SceneManager.GetActiveScene().name != SceneNames.PuzzleSceneName)
		{
			CharacterInfoPanel.SingletonInventoryVisualController?.ClearInspectedItem();
			CharacterInfoPanel.SingletonInventoryVisualController?.ItemBoardTileInspect(tiles[tiles.Count - 1], tiles[tiles.Count - 1].ScatteredItem);
		}
		if (isPlayingSound)
		{
			PersistentSound.SingletonSoundController.UpdateWordValidity(tiles, wordValidity == WordValidity.Valid);
		}
		MusicController.OnSelectMichaelPuzzleGridWord(tiles.Count, 25);
	}

	public void RepopulateSelectedTile(Tile previousTile, Tile newTile, GridData gridData)
	{
		if (GetTilesFromSelectedTiles().Contains(previousTile))
		{
			int index = GetTilesFromSelectedTiles().IndexOf(previousTile);
			_selectedTiles[index].SelectedTile = newTile;
		}
		if (!ValidateSelection(gridData))
		{
			CancelSelection();
		}
		PopulateValidityAndScore(isPlayingSound: false, gridData);
	}

	public void SetFinalPuzzleGrid(MichaelVolumeController mvc)
	{
		_isFinalPuzzleGrid = true;
		_michaelVolumeController = mvc;
	}
}
