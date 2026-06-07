using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;
using UnityEngine.UI;

public class InventoryVisualController : MonoBehaviour
{
	[SerializeField]
	private GameObject _itemObjectPrefab;

	[SerializeField]
	private GameObject _consumableTileObjectPrefab;

	[SerializeField]
	private GameObject _topLevelCanvasGO;

	[SerializeField]
	private GameObject _stickersParentGo;

	[SerializeField]
	private GameObject _stampsParentGo;

	[SerializeField]
	private Transform[] _stickerSlotTransforms;

	[SerializeField]
	private Transform[] _stampSlotTransforms;

	[SerializeField]
	private Transform[] _tileSlotTransforms;

	[SerializeField]
	private GameObject _secondRowTileParentGO;

	[SerializeField]
	private LayoutElement _inventoryLayoutElement;

	[SerializeField]
	private Image _inventoryPanelBG;

	[SerializeField]
	private Image _inspectorPanelBG;

	[SerializeField]
	private Image _tabBG;

	[SerializeField]
	private Transform _giftStickerLayoutParent;

	[SerializeField]
	private Image _sellButtonFill;

	[SerializeField]
	private Image _tileDestroyButtonFill;

	[SerializeField]
	private Image _scatteredItemTileDestroyButtonFill;

	[SerializeField]
	private ItemInspectorController _itemInspectorController;

	[SerializeField]
	private ItemReorderController _itemReorderController;

	[SerializeField]
	private CameraFinder _cameraFinder;

	[SerializeField]
	private PlayerCharacterController _playerCharacterController;

	[SerializeField]
	private TopBarController _topBarController;

	private CashDisplayController _cashDisplayController;

	[Header("Curse Flies")]
	[SerializeField]
	private GameObject _dragToRearrangeGO;

	[SerializeField]
	private GameObject _curseFliesParentGO;

	[SerializeField]
	private GameObject[] _curseFlyGOs;

	public UIElementGenericAnimations CashGenericAnimations;

	private List<ItemObject> _stickerObjects = new List<ItemObject>();

	private List<ItemObject> _stampObjects = new List<ItemObject>();

	private List<TileConsumableObject> _consumableTileObjects = new List<TileConsumableObject>();

	private ItemObject _giftItemObject;

	private Item _inspectedItem;

	private Tile _inspectedTile;

	private bool _isSpritePopulated;

	private float _sellButtonMostRecentClickTime = -9999f;

	private float _tileDestroyMostRecentClickTime = -9999f;

	public int TimeEval;

	private Coroutine _sellButtonFillCoroutine;

	private Coroutine _tileDestroyButtonFillCoroutine;

	private Coroutine _scatteredItemTileDestroyButtonFillCoroutine;

	private void Awake()
	{
		ItemObject.OnItemClicked += OnItemClicked;
		TileConsumableObject.OnTileClicked += OnTileClicked;
		RunProgress.AdvancingScene += OnSceneChanged;
		_cashDisplayController = GetComponent<CashDisplayController>();
		_cashDisplayController.DisplayInitialCashValue(GameStatics.GetPlayer().Money);
		TimeEval = Mathf.RoundToInt(Time.realtimeSinceStartup * 1000f);
		InputManager inputManager = UnityEngine.Object.FindFirstObjectByType<InputManager>();
		if (inputManager != null)
		{
			inputManager.Initialize();
		}
		PopulateAll();
	}

	private void OnSceneChanged()
	{
		ClearInspectedItem();
	}

	public void PopulateAll()
	{
		PopulateStickers();
		PopulateStamps();
		PopulateGift();
		PopulateTiles();
		PopulateCash();
		PopulateSprite();
		ColourPanels();
		PopulateCurseFlies();
	}

	public void PopulateStickers()
	{
		Transform[] stickerSlotTransforms = _stickerSlotTransforms;
		foreach (Transform transform in stickerSlotTransforms)
		{
			if (transform.childCount > 0)
			{
				UnityEngine.Object.Destroy(transform.GetChild(0).gameObject);
			}
		}
		_stickerObjects.Clear();
		Item[] stickers = GameStatics.GetPlayer().Stickers;
		GameStatics.GetPlayer().RefreshUnderhandTargetSticker();
		for (int j = 0; j < _stickerSlotTransforms.Length; j++)
		{
			Item item = stickers[j];
			if (item != null)
			{
				ItemObject component = UnityEngine.Object.Instantiate(_itemObjectPrefab, _stickerSlotTransforms[j]).GetComponent<ItemObject>();
				component.Populate(item);
				_stickerObjects.Add(component);
			}
		}
	}

	public void PopulateStamps()
	{
		Transform[] stampSlotTransforms = _stampSlotTransforms;
		foreach (Transform transform in stampSlotTransforms)
		{
			if (transform.childCount > 0)
			{
				UnityEngine.Object.Destroy(transform.GetChild(0).gameObject);
			}
		}
		_stampObjects.Clear();
		Item[] stamps = GameStatics.GetPlayer().Stamps;
		for (int j = 0; j < _stampSlotTransforms.Length; j++)
		{
			Item item2 = stamps[j];
			if (item2 != null)
			{
				ItemObject component = UnityEngine.Object.Instantiate(_itemObjectPrefab, _stampSlotTransforms[j]).GetComponent<ItemObject>();
				component.Populate(item2);
				_stampObjects.Add(component);
			}
		}
		if (GameStatics.GetPlayer().Stamps.ToList().Find((Item item) => item is Underhand) != null)
		{
			StartCoroutine(UnderhandRefresh());
		}
	}

	private IEnumerator UnderhandRefresh()
	{
		yield return null;
		PopulateStickers();
	}

	public void PopulateTiles()
	{
		if (GameStatics.GetPlayer().GetUnpackedItemsOfType(typeof(Stadium)).Count > 0)
		{
			_secondRowTileParentGO.SetActive(value: true);
			_inventoryLayoutElement.minHeight = 738f;
			_inventoryLayoutElement.preferredHeight = 738f;
		}
		else
		{
			_secondRowTileParentGO.SetActive(value: false);
			_inventoryLayoutElement.minHeight = 660f;
			_inventoryLayoutElement.preferredHeight = 660f;
		}
		Transform[] tileSlotTransforms = _tileSlotTransforms;
		foreach (Transform transform in tileSlotTransforms)
		{
			for (int num = transform.childCount - 1; num >= 0; num--)
			{
				UnityEngine.Object.Destroy(transform.GetChild(num).gameObject);
			}
		}
		_consumableTileObjects.Clear();
		Tile[] consumableTiles = GameStatics.GetPlayer().ConsumableTiles;
		for (int j = 0; j < _tileSlotTransforms.Length; j++)
		{
			Tile tile = consumableTiles[j];
			if (tile != null)
			{
				TileConsumableObject component = UnityEngine.Object.Instantiate(_consumableTileObjectPrefab, _tileSlotTransforms[j]).GetComponent<TileConsumableObject>();
				component.Populate(tile, j);
				_consumableTileObjects.Add(component);
			}
		}
		RefreshInspect();
	}

	public void PopulateGift()
	{
		Player player = GameStatics.GetPlayer();
		if (player.GetCharacter() == null)
		{
			return;
		}
		foreach (Transform item in _giftStickerLayoutParent)
		{
			UnityEngine.Object.Destroy(item.gameObject);
		}
		ItemObject component = UnityEngine.Object.Instantiate(_itemObjectPrefab, _giftStickerLayoutParent).GetComponent<ItemObject>();
		component.Populate(player.GetCharacter().GetCharacterItem());
		_giftItemObject = component;
	}

	public void PopulateCash()
	{
		_cashDisplayController.DisplayCashValue(GameStatics.GetPlayer().Money);
		RefreshInspect();
	}

	private void PopulateSprite()
	{
		if (!_isSpritePopulated)
		{
			_playerCharacterController.PopulateCharacterAnimator();
			_isSpritePopulated = true;
		}
	}

	public void HidePin()
	{
		_giftStickerLayoutParent.gameObject.SetActive(value: false);
	}

	public void PopulateCurseFlies()
	{
		Player player = GameStatics.GetPlayer();
		if (player.CurrentRunProgress.Ascension >= AscensionLevel.CursedBosses)
		{
			_dragToRearrangeGO.SetActive(value: false);
			_curseFliesParentGO.SetActive(value: true);
			for (int i = 0; i < 5; i++)
			{
				if (player.CurrentRunProgress.CursedBossesDefeated.Contains(i))
				{
					Debug.Log("Turning on cursed fly");
					_curseFlyGOs[i].SetActive(value: true);
				}
				else
				{
					Debug.Log("Turning off cursed fly");
					_curseFlyGOs[i].SetActive(value: false);
				}
			}
		}
		else
		{
			_dragToRearrangeGO.SetActive(value: true);
			_curseFliesParentGO.SetActive(value: false);
		}
	}

	public IEnumerator PopulateNewCurseFly(int flyNumber)
	{
		if (GameStatics.GetPlayer().CurrentRunProgress.Ascension >= AscensionLevel.CursedBosses)
		{
			PersistentSound.SingletonSoundController.FairyGet();
			_curseFlyGOs[flyNumber].SetActive(value: true);
			_curseFlyGOs[flyNumber].GetComponent<UIElementGenericAnimations>().ActionPulse(1f);
			yield return new WaitForSeconds(0.5f);
		}
	}

	private void ColourPanels()
	{
		Character character = GameStatics.GetPlayer().GetCharacter();
		_inventoryPanelBG.color = character.GetUIColorA();
		_inspectorPanelBG.color = character.GetUIColorA();
		_tabBG.color = character.GetUIColorA();
		Color uIColorB = character.GetUIColorB();
		Transform[] stickerSlotTransforms = _stickerSlotTransforms;
		for (int i = 0; i < stickerSlotTransforms.Length; i++)
		{
			stickerSlotTransforms[i].GetComponent<Image>().color = uIColorB;
		}
		stickerSlotTransforms = _stampSlotTransforms;
		for (int i = 0; i < stickerSlotTransforms.Length; i++)
		{
			stickerSlotTransforms[i].GetComponent<Image>().color = uIColorB;
		}
		stickerSlotTransforms = _tileSlotTransforms;
		for (int i = 0; i < stickerSlotTransforms.Length; i++)
		{
			stickerSlotTransforms[i].GetComponent<Image>().color = uIColorB;
		}
	}

	public Item GetInspectedItem()
	{
		return _inspectedItem;
	}

	public List<ItemObject> GetItemObjects()
	{
		List<ItemObject> list = new List<ItemObject>();
		list.AddRange(_stickerObjects);
		list.AddRange(_stampObjects);
		list.Add(_giftItemObject);
		ShopVisualController shopVisualController = UnityEngine.Object.FindFirstObjectByType<ShopVisualController>();
		if (shopVisualController != null)
		{
			list.AddRange(shopVisualController.GetItemObjects());
		}
		return list;
	}

	public List<TileConsumableObject> GetTileConsumableObjects()
	{
		List<TileConsumableObject> list = new List<TileConsumableObject>();
		list.AddRange(_consumableTileObjects);
		ShopVisualController shopVisualController = UnityEngine.Object.FindFirstObjectByType<ShopVisualController>();
		if (shopVisualController != null)
		{
			list.AddRange(shopVisualController.GetTileConsumableObjects());
		}
		return list;
	}

	public ItemObject GetItemObjectFromItem(Item item)
	{
		foreach (ItemObject itemObject in GetItemObjects())
		{
			if (itemObject.MyItem == item)
			{
				return itemObject;
			}
		}
		return null;
	}

	public TileConsumableObject GetTileConsumableObjectFromTile(Tile tile)
	{
		foreach (TileConsumableObject tileConsumableObject in GetTileConsumableObjects())
		{
			if (tile == tileConsumableObject.MyTile)
			{
				return tileConsumableObject;
			}
		}
		return null;
	}

	public void ClearInspectedItem()
	{
		if (_inspectedItem != null)
		{
			UnInspect();
			UnhighlightItem(_inspectedItem);
			_inspectedItem = null;
		}
	}

	public void ClearInspectedTile()
	{
		if (_inspectedTile != null)
		{
			UnInspect();
			UnhighlightTile(_inspectedTile);
			_inspectedTile = null;
		}
	}

	public void RefreshInspect()
	{
		if (_inspectedItem != null)
		{
			_itemInspectorController.Inspect(_inspectedItem);
		}
	}

	public void Inspect(Item item)
	{
		_itemInspectorController.Inspect(item);
		PersistentSound.SingletonSoundController.InspectItem();
	}

	public void ItemBoardTileInspect(Tile tile, Item item)
	{
		Debug.Log("via ItemBoardTileInspect()...");
		_itemInspectorController.Inspect(tile.ScatteredItem, isShowingUpgradeableText: false, wrapped: false, tile);
		PersistentSound.SingletonSoundController.InspectItem();
	}

	public void ItemTileInspect(Tile tile, TileConsumableObject tileConsumableObject)
	{
		Debug.Log("via ItemTileInspect()...");
		_itemInspectorController.Inspect(tile.ScatteredItem, isShowingUpgradeableText: false, wrapped: false, tile, tileConsumableObject);
		PersistentSound.SingletonSoundController.InspectItem();
	}

	public void TileInspect(TileConsumableObject tileConsumableObject)
	{
		_itemInspectorController.TileInspect(tileConsumableObject);
		PersistentSound.SingletonSoundController.InspectItem();
	}

	public void UnInspect(bool toEmpty = true)
	{
		_itemInspectorController.UnInspect();
		if (toEmpty)
		{
			PersistentSound.SingletonSoundController.UninspectItem();
		}
	}

	public void HighlightItem(Item item)
	{
		if (item != null)
		{
			ItemObject itemObjectFromItem = GetItemObjectFromItem(item);
			if (itemObjectFromItem != null)
			{
				itemObjectFromItem.Highlight();
			}
		}
	}

	public void HighlightTile(Tile tile)
	{
		if (tile != null)
		{
			TileConsumableObject tileConsumableObjectFromTile = GetTileConsumableObjectFromTile(tile);
			if (tileConsumableObjectFromTile != null)
			{
				tileConsumableObjectFromTile.Highlight();
			}
		}
	}

	public void UnhighlightItem(Item item)
	{
		GetItemObjectFromItem(item)?.Unhighlight();
	}

	public void UnhighlightTile(Tile tile)
	{
		GetTileConsumableObjectFromTile(tile)?.Unhighlight();
	}

	private void OnItemClicked(ItemObject clickedItemObject)
	{
		Item myItem = clickedItemObject.MyItem;
		if (_inspectedTile != null)
		{
			UnhighlightTile(_inspectedTile);
			UnInspect(toEmpty: false);
			_inspectedTile = null;
		}
		if (_inspectedItem == myItem)
		{
			UnhighlightItem(_inspectedItem);
			UnInspect();
			_inspectedItem = null;
		}
		else
		{
			if (_inspectedItem != null)
			{
				UnhighlightItem(_inspectedItem);
			}
			_inspectedItem = myItem;
			HighlightItem(myItem);
			Inspect(myItem);
		}
		_ = UnityEngine.Object.FindFirstObjectByType<ShopController>() == null;
	}

	private void OnTileClicked(TileConsumableObject clickedTileConsumableObject)
	{
		Tile myTile = clickedTileConsumableObject.MyTile;
		if (_inspectedItem != null)
		{
			UnhighlightItem(_inspectedItem);
			UnInspect(toEmpty: false);
			_inspectedItem = null;
		}
		if (_inspectedTile == myTile)
		{
			UnhighlightTile(_inspectedTile);
			UnInspect();
			_inspectedTile = null;
		}
		else
		{
			if (_inspectedTile != null)
			{
				UnhighlightTile(_inspectedTile);
			}
			_inspectedTile = myTile;
			HighlightTile(myTile);
			if (myTile.GetGlyphType() == GlyphType.ScatteredItem)
			{
				ClearInspectedItem();
				ItemTileInspect(_inspectedTile, clickedTileConsumableObject);
			}
			else
			{
				TileInspect(clickedTileConsumableObject);
			}
		}
		_ = UnityEngine.Object.FindFirstObjectByType<ShopController>() == null;
	}

	public void OnItemSellButtonMouseDown()
	{
		EncounterController encounterController = UnityEngine.Object.FindFirstObjectByType<EncounterController>();
		ShopController shopController = UnityEngine.Object.FindFirstObjectByType<ShopController>();
		if (encounterController != null && encounterController.GetEncounterThreadStage() != EncounterThreadStage.WaitingForWordSubmission && encounterController.GetEncounterThreadStage() != EncounterThreadStage.WaitingForForcedSell)
		{
			Debug.Log("not selling, stuff is happening");
			return;
		}
		if (shopController != null && Time.timeSinceLevelLoad - shopController.MostRecentHippoAnimationStartTime < HungryHippo.AnimationTimeWait)
		{
			Debug.Log("not selling, hippo is animating");
			return;
		}
		_sellButtonMostRecentClickTime = Time.timeSinceLevelLoad;
		_sellButtonFillCoroutine = StartCoroutine(FillSellButton());
	}

	public void OnTileDestroyButtonMouseDown()
	{
		EncounterController encounterController = UnityEngine.Object.FindFirstObjectByType<EncounterController>();
		ShopController shopController = UnityEngine.Object.FindFirstObjectByType<ShopController>();
		if (encounterController != null && encounterController.GetEncounterThreadStage() != EncounterThreadStage.WaitingForWordSubmission)
		{
			Debug.Log("not destroying, stuff is happening");
			return;
		}
		if (shopController != null && Time.timeSinceLevelLoad - shopController.MostRecentHippoAnimationStartTime < HungryHippo.AnimationTimeWait)
		{
			Debug.Log("not destroying, hippo is animating");
			return;
		}
		_tileDestroyMostRecentClickTime = Time.timeSinceLevelLoad;
		_tileDestroyButtonFillCoroutine = StartCoroutine(FillTileDestroyButton());
	}

	public void OnScatteredItemTileDestroyButtonMouseDown()
	{
		EncounterController encounterController = UnityEngine.Object.FindFirstObjectByType<EncounterController>();
		ShopController shopController = UnityEngine.Object.FindFirstObjectByType<ShopController>();
		if (encounterController != null && encounterController.GetEncounterThreadStage() != EncounterThreadStage.WaitingForWordSubmission)
		{
			Debug.Log("not destroying, stuff is happening");
			return;
		}
		if (shopController != null && Time.timeSinceLevelLoad - shopController.MostRecentHippoAnimationStartTime < HungryHippo.AnimationTimeWait)
		{
			Debug.Log("not destroying, hippo is animating");
			return;
		}
		_tileDestroyMostRecentClickTime = Time.timeSinceLevelLoad;
		_scatteredItemTileDestroyButtonFillCoroutine = StartCoroutine(FillScatteredItemTileDestroyButton());
	}

	public void OnItemSellButtonMouseUp()
	{
	}

	private IEnumerator FillSellButton()
	{
		float t = 0f;
		float totalTime = 0.5f;
		while (t < 1f)
		{
			t += Time.deltaTime / totalTime;
			_sellButtonFill.fillAmount = t;
			yield return null;
		}
	}

	private IEnumerator FillTileDestroyButton()
	{
		float t = 0f;
		float totalTime = 0.5f;
		while (t < 1f)
		{
			t += Time.deltaTime / totalTime;
			_tileDestroyButtonFill.fillAmount = t;
			yield return null;
		}
	}

	private IEnumerator FillScatteredItemTileDestroyButton()
	{
		float t = 0f;
		float totalTime = 0.5f;
		while (t < 1f)
		{
			t += Time.deltaTime / totalTime;
			_scatteredItemTileDestroyButtonFill.fillAmount = t;
			yield return null;
		}
	}

	public void OnItemSellButtonClicked()
	{
		if (_sellButtonFillCoroutine == null)
		{
			return;
		}
		StopCoroutine(_sellButtonFillCoroutine);
		_sellButtonFillCoroutine = null;
		_sellButtonFill.fillAmount = 0f;
		if (_inspectedItem == null || Time.timeSinceLevelLoad - _sellButtonMostRecentClickTime < 0.5f)
		{
			return;
		}
		EncounterController encounterController = UnityEngine.Object.FindFirstObjectByType<EncounterController>();
		ShopController shopController = UnityEngine.Object.FindFirstObjectByType<ShopController>();
		PinDraftVisualController pinDraftVisualController = UnityEngine.Object.FindFirstObjectByType<PinDraftVisualController>();
		if (encounterController != null && encounterController.GetEncounterThreadStage() != EncounterThreadStage.WaitingForWordSubmission && encounterController.GetEncounterThreadStage() != EncounterThreadStage.WaitingForForcedSell)
		{
			Debug.Log("not selling, stuff is happening");
			return;
		}
		if (shopController != null && Time.timeSinceLevelLoad - shopController.MostRecentHippoAnimationStartTime < HungryHippo.AnimationTimeWait)
		{
			Debug.Log("not selling, hippo is animating");
			return;
		}
		Player player = GameStatics.GetPlayer();
		bool num = !(player.CurrentRunProgress.Challenge is PlayingFavourites) || player.GetHBFavouriteStamp() == _inspectedItem || player.GetHBFavouriteSticker() == _inspectedItem;
		player.RemoveItemFromInventory(_inspectedItem);
		if (num)
		{
			if (_inspectedItem is MysteryGift)
			{
				Item randomSticker = ItemPools.GetRandomSticker((from sticker in player.GetStickers(forItemComparison: true)
					select sticker.GetType()).ToList(), ItemRarity.Rare);
				for (int i = 1; i < _inspectedItem.UpgradeableComponents[0].Level; i++)
				{
					randomSticker.Upgrade(0);
				}
				randomSticker.IsFoil = _inspectedItem.IsFoil;
				randomSticker.TimesUpgraded = _inspectedItem.TimesUpgraded;
				player.AddItemToInventory(randomSticker);
			}
			else if (_inspectedItem is SewingNeedle)
			{
				SewingNeedle sewingNeedle = (SewingNeedle)_inspectedItem;
				List<Item> stickers = player.GetStickers(forItemComparison: true);
				stickers.RemoveAll((Item sticker) => sewingNeedle.BlacklistedItems.Exists((Type type) => type == sticker.GetType()));
				if (stickers.Count >= 2)
				{
					List<Item> list = new List<Item>();
					int index = UnityEngine.Random.Range(0, stickers.Count);
					list.Add(stickers[index]);
					stickers.RemoveAt(index);
					int index2 = UnityEngine.Random.Range(0, stickers.Count);
					list.Add(stickers[index2]);
					stickers.RemoveAt(index2);
					bool isFoil = list[0].IsFoil || list[1].IsFoil;
					int num2 = Mathf.Max(list[0].UpgradeableComponents[0].Level, list[1].UpgradeableComponents[0].Level);
					Debug.Log($"levels: {list[0].UpgradeableComponents[0].Level} and {list[1].UpgradeableComponents[0].Level}, max = {num2}");
					Frankenstein frankenstein = new Frankenstein();
					frankenstein.StitchedItems.Add(StringSerializer.GetSanitizedData(list[0]));
					frankenstein.StitchedItems.Add(StringSerializer.GetSanitizedData(list[1]));
					foreach (Item stitchedItem in frankenstein.StitchedItems)
					{
						stitchedItem.IsFoil = false;
					}
					while (frankenstein.StitchedItems[0].UpgradeableComponents[0].Level > 1)
					{
						frankenstein.StitchedItems[0].Downgrade(0);
					}
					while (frankenstein.StitchedItems[1].UpgradeableComponents[0].Level > 1)
					{
						frankenstein.StitchedItems[1].Downgrade(0);
					}
					Debug.Log($"Downgraded levels: {frankenstein.StitchedItems[0].UpgradeableComponents[0].Level} and {frankenstein.StitchedItems[1].UpgradeableComponents[0].Level}");
					if (num2 > 1)
					{
						for (int j = 1; j < num2; j++)
						{
							frankenstein.Upgrade(0);
						}
					}
					Debug.Log($"Upgraded levels: {frankenstein.StitchedItems[0].UpgradeableComponents[0].Level} and {frankenstein.StitchedItems[1].UpgradeableComponents[0].Level}");
					frankenstein.IsFoil = isFoil;
					frankenstein.TimesUpgraded = num2 - 1;
					frankenstein.MoneyInvested.AddRange(list[0].MoneyInvested);
					frankenstein.MoneyInvested.AddRange(list[1].MoneyInvested);
					player.RemoveItemFromInventory(list[0]);
					player.RemoveItemFromInventory(list[1]);
					player.AddItemToInventory(frankenstein);
				}
			}
			else if (_inspectedItem is SignalReceiver && encounterController != null)
			{
				List<Type> itemTypesInInventory = (from item in player.GetAllItems(forItemComparison: true)
					select item.GetType()).ToList();
				if (itemTypesInInventory.Contains(typeof(Frankenstein)))
				{
					foreach (Item item3 in player.GetUnpackedItemsOfType(typeof(Frankenstein), forItemComparison: true))
					{
						Frankenstein frankenstein2 = item3 as Frankenstein;
						itemTypesInInventory.AddRange(frankenstein2.StitchedItems.Select((Item item) => item.GetType()));
					}
				}
				List<Tile> list2 = (from tile in (from tile in encounterController.GetGridData().GetAvailableTiles()
						where tile.GetGlyphType() == GlyphType.ScatteredItem
						select tile).ToList()
					where tile.ScatteredItem.UpgradeableComponents.Count == 1 && !itemTypesInInventory.Contains(tile.ScatteredItem.GetType())
					select tile).ToList();
				if (list2.Count > 0)
				{
					Item item2 = Activator.CreateInstance(list2[UnityEngine.Random.Range(0, list2.Count)].ScatteredItem.GetType()) as Item;
					for (int k = 1; k < _inspectedItem.UpgradeableComponents[0].Level; k++)
					{
						item2.Upgrade(0);
					}
					item2.IsFoil = _inspectedItem.IsFoil;
					item2.TimesUpgraded = _inspectedItem.TimesUpgraded;
					player.AddItemToInventory(item2);
				}
			}
			else if (_inspectedItem is Stadium)
			{
				for (int l = 5; l < 10; l++)
				{
					Tile consumableTileByIndex = player.GetConsumableTileByIndex(l);
					if (consumableTileByIndex != null)
					{
						player.RemoveTileFromInventory(consumableTileByIndex, isAppliedToGrid: false);
					}
				}
				CharacterInfoPanel.SingletonInventoryVisualController.PopulateTiles();
			}
			else if (_inspectedItem is Unicorn)
			{
				List<Item> list3 = (from sticker in player.GetStickers(forItemComparison: true)
					where !sticker.IsFoil
					select sticker).ToList();
				if (list3.Count > 0)
				{
					list3[UnityEngine.Random.Range(0, list3.Count)].IsFoil = true;
				}
			}
		}
		PopulateStickers();
		PopulateStamps();
		if (_inspectedItem.CostsMoneyToSell)
		{
			player.ChangeMoney(-_inspectedItem.SellCost);
		}
		else
		{
			player.ChangeMoney(_inspectedItem.GetSellValue());
		}
		PopulateCash();
		PersistentSound.SingletonSoundController.GainMoney();
		if (encounterController != null)
		{
			StartCoroutine(encounterController.SellItem(_inspectedItem));
		}
		if (shopController != null)
		{
			shopController.SetFoilPercentage();
			shopController.UpdateCosts();
			shopController.UpdateHippoButtons();
			shopController.RepopulateShopItems();
		}
		if (pinDraftVisualController != null && _inspectedItem is IDCard)
		{
			pinDraftVisualController.OnSellIDCard();
		}
		_itemInspectorController.UnInspect();
		_inspectedItem = null;
	}

	public void OnTileDestroyButtonClicked()
	{
		if (_tileDestroyButtonFillCoroutine == null)
		{
			return;
		}
		StopCoroutine(_tileDestroyButtonFillCoroutine);
		_tileDestroyButtonFillCoroutine = null;
		_tileDestroyButtonFill.fillAmount = 0f;
		if (_inspectedTile == null || Time.timeSinceLevelLoad - _tileDestroyMostRecentClickTime < 0.5f)
		{
			return;
		}
		EncounterController encounterController = UnityEngine.Object.FindFirstObjectByType<EncounterController>();
		ShopController shopController = UnityEngine.Object.FindFirstObjectByType<ShopController>();
		if (encounterController != null && encounterController.GetEncounterThreadStage() != EncounterThreadStage.WaitingForWordSubmission)
		{
			Debug.Log("not destroying, stuff is happening");
			return;
		}
		if (shopController != null && Time.timeSinceLevelLoad - shopController.MostRecentHippoAnimationStartTime < HungryHippo.AnimationTimeWait)
		{
			Debug.Log("not destroying, hippo is animating");
			return;
		}
		GameStatics.GetPlayer().RemoveTileFromInventory(_inspectedTile, isAppliedToGrid: false);
		PopulateTiles();
		if (shopController != null)
		{
			shopController.UpdateCosts();
			shopController.RepopulateShopItems();
		}
		_itemInspectorController.UnInspect();
		_inspectedItem = null;
	}

	public void OnScatteredItemTileDestroyButtonClicked()
	{
		if (_scatteredItemTileDestroyButtonFillCoroutine == null)
		{
			return;
		}
		StopCoroutine(_scatteredItemTileDestroyButtonFillCoroutine);
		_scatteredItemTileDestroyButtonFillCoroutine = null;
		_scatteredItemTileDestroyButtonFill.fillAmount = 0f;
		if (_inspectedTile == null || Time.timeSinceLevelLoad - _tileDestroyMostRecentClickTime < 0.5f)
		{
			return;
		}
		EncounterController encounterController = UnityEngine.Object.FindFirstObjectByType<EncounterController>();
		ShopController shopController = UnityEngine.Object.FindFirstObjectByType<ShopController>();
		if (encounterController != null && encounterController.GetEncounterThreadStage() != EncounterThreadStage.WaitingForWordSubmission)
		{
			Debug.Log("not destroying, stuff is happening");
			return;
		}
		if (shopController != null && Time.timeSinceLevelLoad - shopController.MostRecentHippoAnimationStartTime < HungryHippo.AnimationTimeWait)
		{
			Debug.Log("not destroying, hippo is animating");
			return;
		}
		GameStatics.GetPlayer().RemoveTileFromInventory(_inspectedTile, isAppliedToGrid: false);
		PopulateTiles();
		if (shopController != null)
		{
			shopController.UpdateCosts();
			shopController.RepopulateShopItems();
		}
		_itemInspectorController.UnInspect();
		_inspectedItem = null;
	}

	public void RemovePanel()
	{
		ItemObject.OnItemClicked -= OnItemClicked;
		TileConsumableObject.OnTileClicked -= OnTileClicked;
		RunProgress.AdvancingScene -= OnSceneChanged;
		_cameraFinder.UnsubscribeFromEvents();
		_topBarController.UnsubscribeFromEvents();
		_itemReorderController.UnsubscribeFromEvents();
		UnityEngine.Object.Destroy(_topLevelCanvasGO);
	}

	public void PulseInventory()
	{
		_stickersParentGo.GetComponent<UIElementGenericAnimations>().ActionPulse(1f);
		_stampsParentGo.GetComponent<UIElementGenericAnimations>().ActionPulse(1f);
	}
}
