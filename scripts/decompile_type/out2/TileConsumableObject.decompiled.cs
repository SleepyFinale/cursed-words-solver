using System;
using UnityEngine;
using UnityEngine.UI;

public class TileConsumableObject : IDraggableInventoryObject
{
	[SerializeField]
	private UIElementGenericAnimations _UIElementGenericAnimations;

	[SerializeField]
	private GameObject _tileAndCamPrefab;

	[SerializeField]
	private GameObject _highlightGO;

	private GameObject _tileAndCamGO;

	[SerializeField]
	private RectTransform _myRT;

	[SerializeField]
	private CanvasGroup _myCG;

	public RenderTexture MyRenderTexture;

	[SerializeField]
	private RawImage _myRawImage;

	public Tile MyTile;

	private bool _dragBegun;

	public static event Action<TileConsumableObject> OnTileClicked;

	public static event Action<TileConsumableObject> OnTileBeginDrag;

	public static event Action<TileConsumableObject> OnTileDrop;

	private void Start()
	{
		_UIElementGenericAnimations.StartCoroutine(_UIElementGenericAnimations.StampIn());
	}

	public void Populate(Tile tile, int offsetNumber = 0)
	{
		MyTile = tile;
		_tileAndCamGO = UnityEngine.Object.Instantiate(_tileAndCamPrefab);
		TileObject componentInChildren = _tileAndCamGO.GetComponentInChildren<TileObject>();
		componentInChildren.MyTile = tile;
		componentInChildren.Populate();
		_tileAndCamGO.transform.position += Vector3.right * offsetNumber * 20f;
		MyRenderTexture = GetPhotoOfTile(_tileAndCamGO.GetComponentInChildren<Camera>());
		_myRawImage.texture = MyRenderTexture;
		UnityEngine.Object.Destroy(_tileAndCamGO);
	}

	public void BeginDrag()
	{
		_dragBegun = false;
		EncounterController encounterController = UnityEngine.Object.FindFirstObjectByType<EncounterController>();
		if (!(encounterController != null) || encounterController.GetEncounterThreadStage() == EncounterThreadStage.WaitingForWordSubmission)
		{
			TileConsumableObject.OnTileBeginDrag?.Invoke(this);
			_myCG.blocksRaycasts = false;
			_dragBegun = true;
		}
	}

	public void Drag()
	{
		if (_dragBegun)
		{
			EncounterController encounterController = UnityEngine.Object.FindFirstObjectByType<EncounterController>();
			if (encounterController != null && encounterController.GetEncounterThreadStage() != EncounterThreadStage.WaitingForWordSubmission)
			{
				Debug.Log("not dragging, stuff is happening");
				return;
			}
			RectTransformUtility.ScreenPointToLocalPointInRectangle(_myRT.parent as RectTransform, Input.mousePosition, Camera.main, out var localPoint);
			_myRT.anchoredPosition = localPoint;
		}
	}

	public void Release()
	{
		if (_dragBegun)
		{
			EncounterController encounterController = UnityEngine.Object.FindFirstObjectByType<EncounterController>();
			if (encounterController != null && encounterController.GetEncounterThreadStage() != EncounterThreadStage.WaitingForWordSubmission)
			{
				Debug.Log("not dragging, stuff is happening");
				return;
			}
			_dragBegun = false;
			TileConsumableObject.OnTileDrop?.Invoke(this);
			_myCG.blocksRaycasts = true;
		}
	}

	public void OnClickedCallback()
	{
		TileConsumableObject.OnTileClicked?.Invoke(this);
	}

	public void Highlight()
	{
		_highlightGO?.SetActive(value: true);
	}

	public void Unhighlight()
	{
		_highlightGO?.SetActive(value: false);
	}

	public RenderTexture GetPhotoOfTile(Camera cam)
	{
		RenderTexture renderTexture = new RenderTexture(512, 512, 16);
		renderTexture.filterMode = FilterMode.Trilinear;
		renderTexture.anisoLevel = 16;
		renderTexture.useDynamicScale = true;
		renderTexture.antiAliasing = 1;
		renderTexture.wrapMode = TextureWrapMode.Clamp;
		renderTexture.Create();
		cam.targetTexture = renderTexture;
		cam.Render();
		cam.targetTexture = null;
		return renderTexture;
	}
}
