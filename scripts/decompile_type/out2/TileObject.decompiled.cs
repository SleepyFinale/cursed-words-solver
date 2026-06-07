using System.Collections;
using OutlineFx;
using TMPro;
using UnityEngine;

public class TileObject : MonoBehaviour
{
	public Tile MyTile;

	public Vector2Int GridCoordinate;

	[SerializeField]
	private GameObject _tileGO;

	[SerializeField]
	private GameObject _eatenParticlesGO;

	[Header("Text")]
	[SerializeField]
	private GameObject[] _textParentGOs;

	[SerializeField]
	private TextMeshPro[] _letterTMPs;

	private TextMeshPro _letterTMP;

	[SerializeField]
	private TextMeshPro _suitTMP;

	[SerializeField]
	private TextMeshPro[] _scoreTMPs;

	private TextMeshPro _scoreTMP;

	private Color _textColor;

	private Color _scoreColor;

	[SerializeField]
	private Color[] _suitColors;

	private TMP_FontAsset _defaultFont;

	[SerializeField]
	private TMP_FontAsset _fractionFont;

	[SerializeField]
	private CharacterWobble _characterWobble;

	[SerializeField]
	private GameObject _crossOutGO;

	private string _displayedTileValue;

	[SerializeField]
	private ParticleSystemRenderer _greenTileParticleSystem;

	[Header("Scattered Item")]
	[SerializeField]
	private GameObject _scatteredItemParentGO;

	[SerializeField]
	private ItemObject _scatteredItemObject;

	[Header("Mesh")]
	[SerializeField]
	private GameObject[] _tileMeshGOs;

	[SerializeField]
	private Renderer[] _tileRenderers;

	private Renderer _tileRenderer;

	private bool _rotated;

	[SerializeField]
	private global::OutlineFx.OutlineFx[] _outlines;

	[HideInInspector]
	public global::OutlineFx.OutlineFx Outline;

	[SerializeField]
	private GameObject[] _darkenerSelectableGOs;

	[SerializeField]
	private GameObject[] _darkenerUnselectableGOs;

	[SerializeField]
	private Color _normalTileVarianceColor;

	[Header("Colliders")]
	[SerializeField]
	private GameObject _boxColliderGO;

	[SerializeField]
	private GameObject _draggingColliderGO;

	[Header("Animation")]
	[SerializeField]
	private AnimationCurve _scaleUpAnimationCurve;

	[SerializeField]
	private AnimationCurve _actionPulseCurve;

	[SerializeField]
	private AnimationCurve _spinCurve;

	private Vector3 _startPos;

	[SerializeField]
	private AnimationCurve _transformRotCurve;

	[SerializeField]
	private AnimationCurve _transformScaleCurve;

	private Coroutine _ambientFloatingCoroutine;

	[SerializeField]
	private float _maxAmbientFloatOffset = 0.1f;

	[SerializeField]
	private float _maxAmbientFloatFrequency = 1f;

	public bool IsRecoloring;

	private bool _isBlueAffected;

	private int _currentLightLayer = 2;

	public void SetStartPosition()
	{
		_startPos = base.transform.localPosition;
	}

	public void SetActiveCollider(bool isDragging)
	{
		_draggingColliderGO.SetActive(isDragging);
		_boxColliderGO.SetActive(!isDragging);
	}

	public void Populate(Tile tile = null, bool preserveLightLayer = false)
	{
		if (tile != null)
		{
			MyTile = tile;
		}
		if (MyTile.HasBeenDestroyed || MyTile.IsInTheVoid)
		{
			if (!MyTile.Gone)
			{
				Object.Instantiate(_eatenParticlesGO, base.transform).transform.SetParent(null);
				MyTile.Gone = true;
			}
			_tileGO.SetActive(value: false);
			return;
		}
		GameObject[] tileMeshGOs = _tileMeshGOs;
		for (int i = 0; i < tileMeshGOs.Length; i++)
		{
			tileMeshGOs[i].SetActive(value: false);
		}
		TileType tileType = MyTile.GetTileType();
		int num = -1;
		if (tileType == TileType.Normal)
		{
			num = 0;
			RotateNormalTile();
		}
		if (tileType == TileType.Red)
		{
			num = 1;
		}
		if (tileType == TileType.Blue)
		{
			num = 2;
		}
		if (tileType == TileType.Void)
		{
			num = 3;
		}
		if (tileType == TileType.Shiny)
		{
			num = 4;
		}
		if (tileType == TileType.Cactus)
		{
			num = 5;
		}
		if (tileType == TileType.Pink)
		{
			num = 6;
		}
		if (tileType == TileType.Gold)
		{
			num = 7;
		}
		if (tileType == TileType.Green)
		{
			num = 8;
		}
		if (tileType == TileType.Purple)
		{
			num = 9;
		}
		if (tileType == TileType.White)
		{
			num = 10;
		}
		if (tileType == TileType.Glitch)
		{
			num = 11;
		}
		_tileMeshGOs[num].SetActive(value: true);
		_tileRenderer = _tileRenderers[num];
		if (num == 0 && !IsRecoloring)
		{
			Color value = Color.Lerp(Color.white, _normalTileVarianceColor, Random.Range(0.35f, 1f));
			value.a = 1f;
			_tileRenderer.material.SetColor("_BaseColor", value);
			IsRecoloring = true;
		}
		if (num == 2 || num == 9)
		{
			GetComponentInChildren<BlueTileWaterEffect>().Wobble();
		}
		Outline = _outlines[num];
		tileMeshGOs = _textParentGOs;
		for (int i = 0; i < tileMeshGOs.Length; i++)
		{
			tileMeshGOs[i].SetActive(value: false);
		}
		_crossOutGO.SetActive(MyTile.IsCrossedOut);
		if (MyTile != null && MyTile.GetGlyphType() == GlyphType.ScatteredItem && !MyTile.IsEmpty())
		{
			_scatteredItemObject.Populate(MyTile.ScatteredItem);
			_scatteredItemParentGO.SetActive(value: true);
		}
		else
		{
			_textParentGOs[num].SetActive(value: true);
			_scatteredItemParentGO.SetActive(value: false);
		}
		_letterTMP = _letterTMPs[num];
		_scoreTMP = _scoreTMPs[num];
		string stringRepresentation = MyTile.GetStringRepresentation();
		_letterTMP.SetText((MyTile.GetGlyphType() == GlyphType.Letter) ? stringRepresentation.ToUpper() : stringRepresentation);
		_scoreTMP.SetText(MyTile.GetValueForDisplay());
		_displayedTileValue = MyTile.GetValueForDisplay();
		_textColor = _letterTMP.color;
		_scoreColor = _letterTMP.color;
		if (MyTile.CardSuit != 0 && MyTile.CardSuit != Suit.Joker && !MyTile.IsEmpty())
		{
			_suitTMP.gameObject.SetActive(value: true);
			_suitTMP.SetText(MyTile.GetSuitForDisplay());
			if (MyTile.CardSuit == Suit.Hearts || MyTile.CardSuit == Suit.Diamonds)
			{
				_suitTMP.color = _suitColors[0];
			}
			else
			{
				_suitTMP.color = _suitColors[1];
			}
		}
		else
		{
			_suitTMP.gameObject.SetActive(value: false);
		}
		if (_defaultFont == null)
		{
			_defaultFont = _letterTMP.font;
		}
		_scoreTMP.color = _scoreColor;
		_characterWobble.TextMesh = _letterTMP;
		_characterWobble.SetIsWobbling(MyTile.IsDisplayingAsVariableLetter());
		_letterTMP.enabled = !MyTile.IsEmpty();
		_scoreTMP.enabled = !MyTile.IsEmpty();
		if (!preserveLightLayer)
		{
			ChangeLightLayer(2);
		}
		else
		{
			ChangeLightLayer(_currentLightLayer);
		}
	}

	public void PopulatePuzzleColour(TileSolutionState solutionState)
	{
		GameObject[] tileMeshGOs = _tileMeshGOs;
		for (int i = 0; i < tileMeshGOs.Length; i++)
		{
			tileMeshGOs[i].SetActive(value: false);
		}
		int num = -1;
		if (solutionState == TileSolutionState.CorrectPosition)
		{
			num = 12;
		}
		if (solutionState == TileSolutionState.IncorrectPosition)
		{
			num = 13;
		}
		if (solutionState == TileSolutionState.AdjacentToPosition)
		{
			num = 14;
		}
		if (solutionState == TileSolutionState.Incorrect)
		{
			num = 15;
		}
		_tileMeshGOs[num].SetActive(value: true);
		_tileRenderer = _tileRenderers[num];
		Outline = _outlines[num];
	}

	public void RefreshIsWobbling(TileSelectionManager tileSelectionManager)
	{
		_characterWobble.SetIsWobbling(MyTile.IsDisplayingAsVariableLetter(tileSelectionManager));
	}

	private void RotateNormalTile()
	{
		if (!_rotated)
		{
			int num = Random.Range(0, 4) * 90;
			if (_tileMeshGOs[0].transform.childCount > 0)
			{
				_tileMeshGOs[0].transform.GetChild(0).localRotation *= Quaternion.Euler(Vector3.forward * num);
			}
			_rotated = true;
		}
	}

	public void SetCrossOut(bool isCrossedOut)
	{
		_crossOutGO.SetActive(isCrossedOut);
	}

	public void AddToSelection()
	{
		StopAllCoroutines();
		StartCoroutine(RaiseUp());
	}

	public void RemoveFromSelection()
	{
		StopAllCoroutines();
		StartCoroutine(SettleDown());
	}

	public void Destroy()
	{
		Object.Destroy(_tileGO);
	}

	public void ChangeLightLayer(int lightLayerInt)
	{
		if (_tileRenderer == null)
		{
			return;
		}
		_currentLightLayer = lightLayerInt;
		GameObject[] darkenerSelectableGOs = _darkenerSelectableGOs;
		for (int i = 0; i < darkenerSelectableGOs.Length; i++)
		{
			darkenerSelectableGOs[i].SetActive(value: false);
			_scatteredItemObject.Lighten();
		}
		darkenerSelectableGOs = _darkenerUnselectableGOs;
		for (int i = 0; i < darkenerSelectableGOs.Length; i++)
		{
			darkenerSelectableGOs[i].SetActive(value: false);
			_scatteredItemObject.Lighten();
		}
		switch (lightLayerInt)
		{
		case 2:
		{
			darkenerSelectableGOs = _darkenerSelectableGOs;
			for (int i = 0; i < darkenerSelectableGOs.Length; i++)
			{
				darkenerSelectableGOs[i].SetActive(value: true);
				_scatteredItemObject.Lighten();
			}
			break;
		}
		case 1:
		{
			darkenerSelectableGOs = _darkenerUnselectableGOs;
			for (int i = 0; i < darkenerSelectableGOs.Length; i++)
			{
				darkenerSelectableGOs[i].SetActive(value: true);
				_scatteredItemObject.Darken();
			}
			break;
		}
		}
		_tileRenderer.renderingLayerMask = (uint)(1 << RenderingLayerMask.NameToRenderingLayer($"Light Layer {lightLayerInt}"));
		_greenTileParticleSystem.renderingLayerMask = (uint)(1 << RenderingLayerMask.NameToRenderingLayer($"Light Layer {lightLayerInt}"));
		switch (lightLayerInt)
		{
		case 1:
			_letterTMP.color = _textColor - new Color(1f, 1f, 1f, 0f);
			_scoreTMP.color = _scoreColor - new Color(1f, 1f, 1f, 0f);
			break;
		case 2:
			_letterTMP.color = _textColor;
			_scoreTMP.color = _scoreColor;
			break;
		default:
			_letterTMP.color = _textColor;
			_scoreTMP.color = _scoreColor;
			break;
		}
	}

	public Vector3 GetDoubleBackSafeOffset()
	{
		return Vector3.one * Random.Range(-0.01f, 0.01f);
	}

	private IEnumerator RaiseUp()
	{
		Vector3 endPos = GetRaisedLocalPosition();
		float t = 0f;
		float animationTime = 0.04f;
		while (t < 1f)
		{
			t += Time.deltaTime / (animationTime * GameStatics.GetCurrentAnimationSpeed());
			base.transform.localPosition = Vector3.Lerp(_startPos, endPos, t);
			yield return null;
		}
		base.transform.localPosition = endPos;
	}

	public Vector3 GetRaisedLocalPosition()
	{
		return _startPos - Vector3.forward * 0.5f;
	}

	private IEnumerator SettleDown()
	{
		Vector3 currentPos = base.transform.localPosition;
		float t = 0f;
		float animationTime = 0.04f;
		while (t < 1f)
		{
			t += Time.deltaTime / (animationTime * GameStatics.GetCurrentAnimationSpeed());
			base.transform.localPosition = Vector3.Lerp(currentPos, _startPos, t);
			yield return null;
		}
		base.transform.localPosition = _startPos;
	}

	public IEnumerator ScaleDownToZero()
	{
		base.transform.localScale = Vector3.one;
		float t = 0f;
		float animationTime = 0.2f;
		while (t < 1f)
		{
			t += Time.deltaTime / (animationTime * GameStatics.GetCurrentAnimationSpeed());
			float t2 = _scaleUpAnimationCurve.Evaluate(1f - Mathf.Clamp01(t));
			base.transform.localScale = Vector3.LerpUnclamped(Vector3.zero, Vector3.one, t2);
			yield return null;
		}
		base.transform.localScale = Vector3.zero;
	}

	public IEnumerator ScaleUpFromZero()
	{
		base.transform.localScale = Vector3.zero;
		float t = 0f;
		float animationTime = 0.2f;
		base.transform.position += new Vector3(0f, 0f, Random.Range(0f - _maxAmbientFloatOffset, _maxAmbientFloatOffset));
		while (t < 1f)
		{
			t += Time.deltaTime / (animationTime * GameStatics.GetCurrentAnimationSpeed());
			float t2 = _scaleUpAnimationCurve.Evaluate(Mathf.Clamp01(t));
			base.transform.localScale = Vector3.LerpUnclamped(Vector3.zero, Vector3.one, t2);
			yield return null;
		}
		base.transform.localScale = Vector3.one;
		BeginAmbientFloating();
	}

	public IEnumerator SpinToSide()
	{
		float t = 0f;
		float animationTime = 0.2f;
		Vector3 targetRotation = new Vector3(0f, -179.99f, 0f);
		while (t < 1f)
		{
			t += Time.deltaTime / (animationTime * GameStatics.GetCurrentAnimationSpeed());
			float t2 = _spinCurve.Evaluate(Mathf.Clamp01(t / 2f));
			base.transform.localRotation = Quaternion.Euler(Vector3.Lerp(Vector3.zero, targetRotation, t2));
			yield return null;
		}
		base.transform.localRotation = Quaternion.Euler(targetRotation / 2f);
	}

	public IEnumerator SpinFromSide(bool isAmbientFloating = true)
	{
		float t = 0f;
		float animationTime = 0.2f;
		Vector3 startRotation = new Vector3(0f, 180.01f, 0f);
		while (t < 1f)
		{
			t += Time.deltaTime / (animationTime * GameStatics.GetCurrentAnimationSpeed());
			float t2 = _spinCurve.Evaluate(Mathf.Clamp01(t / 2f + 0.5f));
			base.transform.localRotation = Quaternion.Euler(Vector3.Lerp(startRotation, Vector3.zero, t2));
			yield return null;
		}
		base.transform.localRotation = Quaternion.Euler(Vector3.zero);
		if (isAmbientFloating)
		{
			BeginAmbientFloating();
		}
	}

	public IEnumerator TransformTile(Tile tile)
	{
		Quaternion startRot = base.transform.localRotation;
		_ = base.transform.localRotation * Quaternion.Euler(0f, 0f, -15f);
		Vector3 startScale = base.transform.localScale;
		float t2 = 0f;
		PersistentSound.SingletonSoundController.GridGenerationPlaceTile(tile);
		while (t2 < 1f)
		{
			t2 += Time.deltaTime / (0.1f * GameStatics.GetCurrentAnimationSpeed());
			base.transform.localScale = Vector3.Lerp(startScale, Vector3.zero, t2);
			yield return null;
		}
		Populate(tile);
		_ = startRot;
		_ = base.transform.localRotation;
		t2 = 0f;
		while (t2 < 1f)
		{
			t2 += Time.deltaTime / (0.35f * GameStatics.GetCurrentAnimationSpeed());
			base.transform.localScale = Vector3.LerpUnclamped(Vector3.zero, startScale, _transformRotCurve.Evaluate(t2));
			yield return null;
		}
		base.transform.localScale = startScale;
	}

	public void BeginAmbientFloating()
	{
		if (_ambientFloatingCoroutine == null && base.gameObject.activeInHierarchy && !SaveManager.GetIsDisablingTileFloat())
		{
			_ambientFloatingCoroutine = StartCoroutine(AmbientFloating());
		}
	}

	public void EndAmbientFloating()
	{
		if (_ambientFloatingCoroutine != null)
		{
			StopCoroutine(_ambientFloatingCoroutine);
			_ambientFloatingCoroutine = null;
			base.transform.localRotation = Quaternion.identity;
		}
		if (!MyTile.HasBeenDestroyed && !MyTile.IsInTheVoid)
		{
			StartCoroutine(SettleDown());
		}
	}

	private IEnumerator AmbientFloating()
	{
		int num = ((Random.Range(0, 2) == 0) ? 1 : (-1));
		Vector3 endPos = _startPos + new Vector3(_maxAmbientFloatOffset * (float)num / 6f, _maxAmbientFloatOffset * (float)num / 6f, _maxAmbientFloatOffset * (float)num);
		float frequency = Random.Range(1.2f, 3.5f) * _maxAmbientFloatFrequency;
		float xOffset = Random.Range(0f, 0.99f);
		float yOffset = Random.Range(0f, 0.99f);
		float t = 0f;
		float perlinMult = Random.Range(1.5f, 1.75f);
		while (true)
		{
			t += Time.deltaTime / perlinMult / GameStatics.GetCurrentAnimationSpeed();
			base.transform.localPosition = Vector3.LerpUnclamped(_startPos, endPos, Mathf.Sin(t * frequency));
			float x = (Mathf.PerlinNoise(xOffset + t, 0.5f) - 0.5f) * 16f;
			float y = (Mathf.PerlinNoise(yOffset + t, 0.5f) - 0.5f) * 16f;
			base.transform.localRotation = Quaternion.Lerp(base.transform.localRotation, Quaternion.Euler(x, y, 0f), 0.4f);
			yield return null;
		}
	}

	private IEnumerator ToneDownFloating()
	{
		float newOffset = _maxAmbientFloatOffset / 15f;
		float t = 0f;
		while (t < 1f)
		{
			t += Time.deltaTime / (2f * GameStatics.GetCurrentAnimationSpeed());
			_maxAmbientFloatOffset = Mathf.Lerp(_maxAmbientFloatOffset, newOffset, t);
			yield return null;
		}
		_maxAmbientFloatOffset = newOffset;
	}

	public void ActionPulse()
	{
		StartCoroutine(ActionPulseCoroutine());
	}

	public IEnumerator ActionPulseCoroutine(float intensity = float.PositiveInfinity)
	{
		if (intensity == float.PositiveInfinity)
		{
			intensity = Random.Range(0.2f, 1f);
		}
		float t = 0f;
		while (t < 1f)
		{
			t += Time.deltaTime / GameStatics.GetCurrentAnimationSpeed();
			base.transform.localScale = Vector3.one + Vector3.one * _actionPulseCurve.Evaluate(t) * intensity;
			yield return null;
		}
		base.transform.localScale = Vector3.one;
	}
}
