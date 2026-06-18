using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;

public class GridLayoutController : MonoBehaviour
{
	[SerializeField]
	private EncounterController _encounterController;

	[SerializeField]
	private TileSelectionManager _tileSelectionManager;

	[SerializeField]
	private Transform _gridTransform;

	[SerializeField]
	private GameObject _tilePrefab;

	[SerializeField]
	private List<TileObject> _tileObjects = new List<TileObject>();

	[SerializeField]
	private float _tileGap;

	private Vector3 _gridTransformStartPos;

	private bool _encounterStartPosSet;

	private Vector3 _gridTransformPunchInOffset = new Vector3(0f, 0f, -0.6f);

	private float _cursorFollowMaxTilt = 6f;

	private float _gridScreenspaceOffset = -120f;

	private float _rotateToCursorSpeed = 5f;

	private bool _isRotatingToCursor;

	private void Update()
	{
		if (_isRotatingToCursor && !SaveManager.GetIsDisablingGridTilt())
		{
			float num = Mathf.Clamp01(Input.mousePosition.x / (float)Screen.width);
			float num2 = Mathf.Clamp01((Input.mousePosition.y + _gridScreenspaceOffset) / (float)Screen.height);
			float num3 = (num - 0.5f) * -2f;
			float num4 = (num2 - 0.5f) * 2f;
			RotateTowardsTargetRotation(Quaternion.Euler(new Vector3(num4 * _cursorFollowMaxTilt, num3 * _cursorFollowMaxTilt, 0f)));
		}
		else
		{
			RotateTowardsTargetRotation(Quaternion.identity);
		}
	}

	private void RotateTowardsTargetRotation(Quaternion target)
	{
		_gridTransform.rotation = Quaternion.Slerp(_gridTransform.rotation, target, _rotateToCursorSpeed * (Time.deltaTime / GameStatics.GetCurrentAnimationSpeed()));
	}

	public void GenerateGrid(Vector2Int gridDimensions)
	{
		Vector3 vector = new Vector3((float)(gridDimensions.x - 1) + (float)(gridDimensions.x - 1) * _tileGap, (float)(gridDimensions.y - 1) + (float)(gridDimensions.y - 1) * _tileGap, 0f) / 2f;
		for (int i = 0; i < gridDimensions.x; i++)
		{
			for (int j = 0; j < gridDimensions.y; j++)
			{
				TileObject component = UnityEngine.Object.Instantiate(_tilePrefab, _gridTransform).GetComponent<TileObject>();
				Vector3 vector2 = new Vector3((float)i + (float)i * _tileGap, (float)j + (float)j * _tileGap, 0f);
				component.transform.localPosition = vector2 - vector;
				component.SetStartPosition();
				component.GridCoordinate = new Vector2Int(i, j);
				_tileObjects.Add(component);
			}
		}
		int num = Mathf.Max(gridDimensions.x, gridDimensions.y);
		if (!_encounterStartPosSet && num > GameStatics.GridDimension)
		{
			_gridTransformStartPos = _gridTransform.localPosition + new Vector3(0f, (float)(num - GameStatics.GridDimension) * 0.1f, (float)(num - GameStatics.GridDimension) * 2.3f);
			_encounterStartPosSet = true;
		}
		if (num > GameStatics.GridDimension)
		{
			_gridTransform.localPosition = _gridTransformStartPos;
		}
	}

	public void PopulateTileDetails(Tile newTile, bool isRecoloring = false)
	{
		TileObject tileObject = _tileObjects.Find((TileObject t) => object.Equals(t.GridCoordinate, newTile.GetCoordinates()));
		tileObject.IsRecoloring = isRecoloring;
		if (tileObject == null)
		{
			throw new Exception("Never expecting a mismatch of coordinates between real and virtual grid tiles");
		}
		RunProgress currentRunProgress = GameStatics.GetPlayer().CurrentRunProgress;
		if (currentRunProgress?.Challenge is SupplyAndDemand && currentRunProgress.CurrentRunStatistics.WordsSubmittedThisRun.Count > 0)
		{
			List<Tile> tiles = currentRunProgress.CurrentRunStatistics.WordsSubmittedThisRun[currentRunProgress.CurrentRunStatistics.WordsSubmittedThisRun.Count - 1].Tiles;
			newTile.IsCrossedOut = tiles.Exists((Tile tile) => tile.GetStringRepresentation() == newTile.GetStringRepresentation());
		}
		tileObject.MyTile = newTile;
		tileObject.Populate();
	}

	public void PopulateTileKeepLightLayer(Tile newTile, bool isRecolouring = false)
	{
		TileObject tileObject = _tileObjects.Find((TileObject t) => object.Equals(t.GridCoordinate, newTile.GetCoordinates()));
		tileObject.IsRecoloring = isRecolouring;
		if (tileObject == null)
		{
			throw new Exception("Never expecting a mismatch of coordinates between real and virtual grid tiles");
		}
		RunProgress currentRunProgress = GameStatics.GetPlayer().CurrentRunProgress;
		if (currentRunProgress?.Challenge is SupplyAndDemand && currentRunProgress.CurrentRunStatistics.WordsSubmittedThisRun.Count > 0)
		{
			List<Tile> tiles = currentRunProgress.CurrentRunStatistics.WordsSubmittedThisRun[currentRunProgress.CurrentRunStatistics.WordsSubmittedThisRun.Count - 1].Tiles;
			newTile.IsCrossedOut = tiles.Exists((Tile tile) => tile.GetStringRepresentation() == newTile.GetStringRepresentation());
		}
		tileObject.MyTile = newTile;
		tileObject.Populate(null, preserveLightLayer: true);
	}

	public void RefreshWobblyTiles()
	{
		foreach (TileObject tileObject in _tileObjects)
		{
			tileObject.RefreshIsWobbling(_tileSelectionManager);
		}
	}

	public List<TileObject> GetTileObjects()
	{
		return new List<TileObject>(_tileObjects);
	}

	public void ClearTileObjects()
	{
		_tileObjects.Clear();
	}

	public TileObject GetTileObjectFromTile(Tile tile)
	{
		return _tileObjects.Find((TileObject tileObject) => tileObject.MyTile == tile);
	}

	public Tile GetTileFromCoordinates(Vector2Int coords)
	{
		return _tileObjects.Find((TileObject tileObject) => tileObject.MyTile.Coordinates.Equals(coords)).MyTile;
	}

	public TileObject GetTileObjectFromCoordinates(Vector2Int coords)
	{
		return _tileObjects.Find((TileObject tileObject) => tileObject.MyTile.Coordinates.Equals(coords));
	}

	public List<TileObject> GetTileObjectsFromTiles(List<TileSelection> tiles)
	{
		return tiles.Select((TileSelection tile) => _tileObjects.Find((TileObject to) => to.MyTile == tile.SelectedTile)).ToList();
	}

	public List<TileObject> GetTileObjectsFromTiles(List<Tile> tiles)
	{
		return tiles.Select((Tile tile) => _tileObjects.Find((TileObject to) => to.MyTile == tile)).ToList();
	}

	public void PunchInGrid()
	{
		_isRotatingToCursor = true;
		StartCoroutine(BringToPunchInOffset());
	}

	public void PunchOutGrid()
	{
		_isRotatingToCursor = false;
		StartCoroutine(BringToStartPosition());
	}

	private IEnumerator BringToPunchInOffset()
	{
		_gridTransform.localPosition = _gridTransformStartPos;
		float t = 0f;
		float animationTime = 0.04f;
		while (t < 1f)
		{
			t += Time.deltaTime / (animationTime * GameStatics.GetCurrentAnimationSpeed());
			_gridTransform.localPosition = Vector3.Lerp(_gridTransformStartPos, _gridTransformStartPos + _gridTransformPunchInOffset, t);
			yield return null;
		}
		_gridTransform.localPosition = _gridTransformStartPos + _gridTransformPunchInOffset;
	}

	private IEnumerator BringToStartPosition()
	{
		_gridTransform.localPosition = _gridTransformStartPos + _gridTransformPunchInOffset;
		float t = 0f;
		float animationTime = 0.04f;
		while (t < 1f)
		{
			t += Time.deltaTime / (animationTime * GameStatics.GetCurrentAnimationSpeed());
			_gridTransform.localPosition = Vector3.Lerp(_gridTransformStartPos + _gridTransformPunchInOffset, _gridTransformStartPos, t);
			yield return null;
		}
		_gridTransform.localPosition = _gridTransformStartPos;
	}

	public void ApplyConsumableTile(TileObject gridTileObject, TileConsumableObject consumableTileObject)
	{
		PersistentSound.SingletonSoundController.PlaceConsumableTileOnBoard(consumableTileObject.MyTile);
		Tile myTile = gridTileObject.MyTile;
		Tile myTile2 = consumableTileObject.MyTile;
		Tile tileToApply = myTile2.GetCopy(isConsumable: true);
		tileToApply.SetCoordinates(myTile.GetCoordinates());
		RunProgress currentRunProgress = GameStatics.GetPlayer().CurrentRunProgress;
		if (currentRunProgress.Challenge is SupplyAndDemand && currentRunProgress.CurrentRunStatistics.WordsSubmittedThisRun.Count > 0)
		{
			List<Tile> tiles = currentRunProgress.CurrentRunStatistics.WordsSubmittedThisRun[currentRunProgress.CurrentRunStatistics.WordsSubmittedThisRun.Count - 1].Tiles;
			tileToApply.IsCrossedOut = tiles.Exists((Tile tile) => tile.GetStringRepresentation() == tileToApply.GetStringRepresentation());
		}
		GridData gridData = _encounterController.GetGridData();
		gridData.GridTiles[Array.IndexOf(gridData.GridTiles, myTile)] = tileToApply;
		gridTileObject.MyTile = tileToApply;
		GameStatics.GetPlayer().RemoveTileFromInventory(consumableTileObject.MyTile, isAppliedToGrid: true);
		_tileSelectionManager.RepopulateSelectedTile(myTile, tileToApply, _encounterController.GetGridData());
		CharacterInfoPanel.SingletonInventoryVisualController.RefreshInspect();
		StartCoroutine(SpinAndRepopulateTile(gridTileObject));
	}

	private IEnumerator SpinAndRepopulateTile(TileObject gridTileObject)
	{
		yield return gridTileObject.SpinToSide();
		gridTileObject.Populate(null, preserveLightLayer: true);
		yield return gridTileObject.SpinFromSide(isAmbientFloating: false);
		_tileSelectionManager.SetIsInputBlocked(isInputBlocked: false);
	}
}
