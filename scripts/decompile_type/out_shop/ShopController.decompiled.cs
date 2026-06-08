using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;
using UnityEngine.UI;

public class ShopController : MonoBehaviour
{
	[SerializeField]
	private TransitionController _transitionController;

	[SerializeField]
	private UnlocksBannerController _unlocksBannerController;

	[SerializeField]
	private EndGameCanvasController _endGameCanvasController;

	[SerializeField]
	private CanvasGroup _shopkeepCanvasCG;

	[SerializeField]
	private GameObject _characterInfoPanelPrefab;

	[SerializeField]
	private DialogueController _dialogueController;

	[SerializeField]
	private RectTransform _shopParentRT;

	[SerializeField]
	private GameObject _rerollParentGO;

	[SerializeField]
	private GameObject _adviceButtonGO;

	[SerializeField]
	private Image _restockButtonTopImage;

	[SerializeField]
	private Image _restockButtonBackgroundImage;

	[SerializeField]
	private GameObject _EAdviceButton;

	[SerializeField]
	private GameObject _MegAdviceButton;

	private ItemInStock[] _itemsInStock = new ItemInStock[6];

	private ItemInStock[] _stickersInStock = new ItemInStock[4];

	private ItemInStock[] _stampsInStock = new ItemInStock[2];

	private TileInStock[] _tilesInStock = new TileInStock[2];

	private ShopVisualController _shopVisualController;

	private TopBarController _topBarController;

	private int _rerollPrice;

	private int _rerollDeduction;

	private bool _hasUsedAngelInvestment;

	private int _foilPercentage = 1;

	private Player _player;

	private bool _freeItemActive;

	private bool _isMegShop;

	private Dictionary<TileType, int> _tileTypeCosts = new Dictionary<TileType, int>
	{
		{
			TileType.Normal,
			2
		},
		{
			TileType.Red,
			3
		},
		{
			TileType.Blue,
			3
		},
		{
			TileType.Void,
			2
		},
		{
			TileType.Shiny,
			4
		},
		{
			TileType.Purple,
			3
		},
		{
			TileType.Gold,
			3
		},
		{
			TileType.White,
			3
		},
		{
			TileType.Green,
			3
		},
		{
			TileType.Cactus,
			3
		},
		{
			TileType.Pink,
			3
		},
		{
			TileType.Glitch,
			3
		}
	};

	private static Dictionary<GlyphType, int> _consumableTileTypeWeightings = new Dictionary<GlyphType, int>
	{
		{
			GlyphType.Letter,
			10
		},
		{
			GlyphType.Blank,
			1
		}
	};

	private static int _consumableTileTypeTotalWeighting;

	private int _rerollCount;

	private int _randomQuipRerollCost = -1;

	public float MostRecentHippoAnimationStartTime = -9999f;

	private Coroutine _speedrunTimeCheckCoroutine;

	private void Start()
	{
		GetTotalFrequency();
		Player player = GameStatics.GetPlayer();
		if (player.ActiveBossModifiers.Exists((BossModifier boss) => boss is CretaceousMegBoss))
		{
			_MegAdviceButton.SetActive(value: true);
			_EAdviceButton.SetActive(value: false);
			_isMegShop = true;
			CretaceousMegBoss cretaceousMegBoss = player.ActiveBossModifiers.First((BossModifier boss) => boss is CretaceousMegBoss) as CretaceousMegBoss;
			Array.Copy(player.FrozenStickers, cretaceousMegBoss.PlayerFrozenStickersAtStart, 4);
			Array.Copy(player.FrozenStamps, cretaceousMegBoss.PlayerFrozenStampsAtStart, 2);
			player.FrozenStickers = new ItemInStock[4];
			player.FrozenStamps = new ItemInStock[2];
		}
		else
		{
			_MegAdviceButton.SetActive(value: false);
			_EAdviceButton.SetActive(value: true);
			_isMegShop = false;
		}
		if (GameStatics.GetPlayer().CurrentRunProgress.Challenge != null || GameStatics.GetPlayer().CurrentRunProgress.Ascension != 0)
		{
			Debug.Log("Hiding advice button due to challenge or being in ascension");
			_adviceButtonGO.SetActive(value: false);
		}
		else
		{
			Debug.Log("Showing advice button");
			_adviceButtonGO.SetActive(value: true);
		}
		if (SaveManager.IsItemUnlocked(typeof(RollerSkate)))
		{
			_randomQuipRerollCost = UnityEngine.Random.Range(6, 11);
		}
		if (CharacterInfoPanel.SingletonObject == null)
		{
			UnityEngine.Object.Instantiate(_characterInfoPanelPrefab).GetComponentInChildren<CameraFinder>().Initialize();
		}
		StartCoroutine(CharacterInfoPanel.SingletonObject.GetComponentInChildren<PlayerCharacterController>().IdleCoroutine());
		if (GameStatics.GetPlayer().CurrentRunProgress.Challenge is DecisionParalysis)
		{
			_rerollParentGO.SetActive(value: false);
		}
		_unlocksBannerController.StartCheckingAchievements();
		ShopItemSlot.ClearDelegates();
		ShopItemSlot.OnBuyButtonClicked += OnItemBuyButtonClicked;
		ShopItemSlot.OnFreezeButtonClicked += OnFreezeButtonClicked;
		ShopItemSlot.OnHippoButtonClicked += OnHippoButtonClicked;
		ShopTile.ClearDelegates();
		ShopTile.OnBuyButtonClicked += OnTileBuyButtonClicked;
		_player = GameStatics.GetPlayer();
		if (_player.GetUnpackedItemsOfType(typeof(FortuneCookie)).Count > 0)
		{
			_foilPercentage = 5;
		}
		_rerollPrice = ((!_player.CurrentRunProgress.IsAscensionModifierActive(AscensionLevel.UnkindShops)) ? 1 : 2);
		if (_isMegShop)
		{
			_rerollPrice = 1;
		}
		if (player.GetUnpackedItemsOfType(typeof(FriedShrimp)).Count > 0)
		{
			_rerollDeduction = 1;
		}
		if (_player.CurrentRunProgress.GetCurrentNodeType() == NodeType.None)
		{
			Debug.LogWarning("No node type set; assuming this is debug launching directly into shop scene. Setting node to shop.");
			_player.CurrentRunProgress.SetNodeType(NodeType.ShopOne);
			_player.CurrentRunProgress.SetStage(1);
			_player.SetCharacter(new WetDennis());
		}
		PersistentSound.SingletonSoundController.EnterShop();
		bool flag = (_freeItemActive = _player.CurrentRunProgress.GetCurrentNodeType() == NodeType.ShopOne && _player.CurrentRunProgress.GetStage() == 1 && !_player.CurrentRunProgress.IsAscensionModifierActive(AscensionLevel.UnkindShops));
		Debug.Log($"{_player.CurrentRunProgress.GetCurrentNodeType()} // {_player.CurrentRunProgress.GetStage()}");
		if (_player.GetUnpackedItemsOfType(typeof(EfficientRecycler)).Count > 0)
		{
			StartCoroutine(PulseEfficientRecycler());
		}
		if (!flag && _player.GetUnpackedItemsOfType(typeof(FutureFunds)).Count > 0)
		{
			StartCoroutine(PulseFutureFunds());
		}
		foreach (RollerSkate item in _player.GetUnpackedItemsOfType(typeof(RollerSkate)))
		{
			item.PreviousShopRestockCount = 0;
		}
		_shopVisualController = UnityEngine.Object.FindFirstObjectByType<ShopVisualController>();
		_shopVisualController.SetShopController(this, _restockButtonTopImage, _restockButtonBackgroundImage);
		StartCoroutine(GenerateGoodsInStock(flag, isCascadingAnimations: false, isReroll: false, IsAngelInvestmentAvailable()));
		_shopVisualController.PopulateRerollCost(GetRerollPrice());
		if (_player.CurrentRunProgress.Challenge is Antiphilatelist || _player.CurrentRunProgress.Challenge is InTheBeginning)
		{
			_shopVisualController.ChangeStampSlotVisibility(0, isVisible: false);
			_shopVisualController.ChangeStampSlotVisibility(1, isVisible: false);
		}
		if (_player.CurrentRunProgress.Challenge is Masochist || _player.CurrentRunProgress.Challenge is InTheBeginning)
		{
			_shopVisualController.ChangeStickerSlotVisibility(0, isVisible: false);
			_shopVisualController.ChangeStickerSlotVisibility(1, isVisible: false);
			_shopVisualController.ChangeStickerSlotVisibility(2, isVisible: false);
			_shopVisualController.ChangeStickerSlotVisibility(3, isVisible: false);
		}
		if (player.GetUnpackedItemsOfType(typeof(NewEruptingVolcano)).Count > 0)
		{
			_shopVisualController.HideFreezeButtons();
		}
		if (SaveManager.IsTutorialComplete())
		{
			if (_player.CurrentRunProgress.CurrentStage == 6 && _player.CurrentRunProgress.CurrentNodeType == NodeType.ShopTwo)
			{
				MusicController.OnEnterShopBeforeMichael();
			}
			else if (!_isMegShop)
			{
				MusicController.OnShopEnter();
			}
			if (flag && !SaveManager.GetIsSilencingShopkeeper() && !(player.CurrentRunProgress.Challenge is InTheBeginning))
			{
				_dialogueController.DialogueEvent(DialogueUtility.GetFirstItemFreeQuip(), fadeOverTime: true);
			}
		}
		_topBarController = CharacterInfoPanel.SingletonObject.transform.parent.GetComponentInChildren<TopBarController>();
		if (player.CurrentRunProgress.Challenge is SpeedrunChallenge || player.CurrentRunProgress.CurrentRunStatistics.IsSpeedrunMode)
		{
			_topBarController.StartTimerAndGetCurrentTime();
			if (player.CurrentRunProgress.Challenge is SpeedrunChallenge)
			{
				_speedrunTimeCheckCoroutine = StartCoroutine(SpeedrunTimeCheck());
			}
		}
		LayoutRebuilder.ForceRebuildLayoutImmediate(_shopParentRT);
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
		yield return StartCoroutine(_dialogueController.DialogueEventCoroutine(SpeedrunChallenge.GameOverQuip, fadeOverTime: true, leftSide: true, isWordSuggestion: false, raycastBlocking: true));
		Player player = GameStatics.GetPlayer();
		RunStatistics currentRunStatistics = player.CurrentRunProgress.CurrentRunStatistics;
		currentRunStatistics.Stickers = player.GetStickers();
		currentRunStatistics.Stamps = player.GetStamps();
		currentRunStatistics.Timer = _topBarController.GetCurrentTime();
		currentRunStatistics.EndCondition = EndGameCondition.LoseChallenge;
		SaveManager.SaveRunHistory(player);
		SaveManager.ClearCurrentRun();
		_endGameCanvasController.ShowEndGameCanvas(currentRunStatistics);
	}

	private int GetRerollPrice()
	{
		return Mathf.Max(_rerollPrice - _rerollDeduction, 0);
	}

	private static void GetTotalFrequency()
	{
		if (SaveManager.IsBulkUnlockUnlocked(typeof(NumbersUnlock)))
		{
			_consumableTileTypeWeightings[GlyphType.Letter] += 3;
			_consumableTileTypeWeightings[GlyphType.Number] = 1;
		}
		if (SaveManager.IsBulkUnlockUnlocked(typeof(CardsUnlock)))
		{
			_consumableTileTypeWeightings[GlyphType.Letter] += 3;
			_consumableTileTypeWeightings[GlyphType.BespokeCard] = 1;
		}
		if (SaveManager.IsBulkUnlockUnlocked(typeof(ChessUnlock)))
		{
			_consumableTileTypeWeightings[GlyphType.Letter] += 3;
			_consumableTileTypeWeightings[GlyphType.Chess] = 1;
		}
		_consumableTileTypeTotalWeighting = 0;
		foreach (KeyValuePair<GlyphType, int> consumableTileTypeWeighting in _consumableTileTypeWeightings)
		{
			_consumableTileTypeTotalWeighting += consumableTileTypeWeighting.Value;
		}
	}

	private IEnumerator GenerateGoodsInStock(bool isFirstShop, bool isCascadingAnimations, bool isReroll, bool freeItem)
	{
		Player player = GameStatics.GetPlayer();
		List<Item> foilStickers = new List<Item>();
		List<Item> legendaryStamps = new List<Item>();
		if (isCascadingAnimations)
		{
			_shopkeepCanvasCG.blocksRaycasts = true;
		}
		int indexForCharacterStarterItem = -1;
		if (isFirstShop && !isReroll && SaveManager.GetHighestCompletedAscension(player.GetCharacter()) == -1)
		{
			indexForCharacterStarterItem = UnityEngine.Random.Range(0, _stickersInStock.Length);
		}
		if (isReroll && player.GetUnpackedItemsOfType(typeof(Eraser)).Count > 0)
		{
			for (int l = 0; l < _stickersInStock.Length; l++)
			{
				if (player.FrozenStickers[l] == null && _shopVisualController.GetShopStickerSlots()[l].IsShown)
				{
					Item myItem = _stickersInStock[l].MyItem;
					if (myItem != null)
					{
						_player.CurrentRunProgress.EmbargoedItemTypes.Add(myItem.GetType());
					}
				}
			}
			for (int m = 0; m < _stampsInStock.Length; m++)
			{
				if (player.FrozenStamps[m] == null && _shopVisualController.GetShopStampSlots()[m].IsShown)
				{
					Item myItem2 = _stampsInStock[m].MyItem;
					if (myItem2 != null)
					{
						_player.CurrentRunProgress.EmbargoedItemTypes.Add(myItem2.GetType());
					}
				}
			}
		}
		for (int k = 0; k < _stickersInStock.Length; k++)
		{
			ItemInStock itemInStock = player.FrozenStickers[k];
			if (itemInStock == null)
			{
				if (k == indexForCharacterStarterItem)
				{
					new List<Type>();
					List<Type> list = new List<Type>(from item in _player.GetStickers(forItemComparison: true)
						where item.TimesUpgraded == GameStatics.GetMaxUpgradeCount(item)
						select item.GetType());
					list.AddRange(from stickerInStock in _stickersInStock
						where stickerInStock != null
						select stickerInStock.MyItem.GetType());
					list.AddRange(from frozenSticker in _player.FrozenStickers
						where frozenSticker != null
						select frozenSticker.MyItem.GetType());
					Item charaterStarterItem = ItemPools.GetCharaterStarterItem(player.GetCharacter(), list);
					if (_player.CurrentRunProgress.Challenge is ColourSwap || player.GetUnpackedItemsOfType(typeof(CanOfBeans)).Count > 0)
					{
						charaterStarterItem.RandomiseRelevantColours();
					}
					if (charaterStarterItem == null)
					{
						GenerateStickerInStock(k, isFirstShop, freeItem);
					}
					else
					{
						Debug.Log("Generating character starter item for shop: " + charaterStarterItem.Name);
						ItemInStock itemInStock2 = new ItemInStock(charaterStarterItem);
						PopulateStickerInStock(itemInStock2, k, isFirstShop: true);
					}
				}
				else
				{
					GenerateStickerInStock(k, isFirstShop, freeItem);
				}
				if (_stickersInStock[k] != null && _stickersInStock[k].MyItem != null && _stickersInStock[k].MyItem.IsFoil)
				{
					foilStickers.Add(_stickersInStock[k].MyItem);
				}
			}
			else
			{
				if (!isReroll && _player.GetUnpackedItemsOfType(typeof(DownwardTrendingChart)).Count > 0)
				{
					itemInStock.MyItem.Discount += 2;
					itemInStock.ResetCost();
				}
				PopulateStickerInStock(itemInStock, k, isFirstShop, freeItem);
			}
			if (isCascadingAnimations && _stickersInStock[k] != null && _stickersInStock[k].MyItem != null)
			{
				yield return new WaitForSeconds(0.05f * GameStatics.GetCurrentAnimationSpeed());
			}
		}
		for (int k = 0; k < _stampsInStock.Length; k++)
		{
			ItemInStock itemInStock3 = player.FrozenStamps[k];
			if (itemInStock3 == null)
			{
				GenerateStampInStock(k, isFirstShop, freeItem);
				if (_stampsInStock[k] != null && _stampsInStock[k].MyItem != null && _stampsInStock[k].MyItem.Rarity == ItemRarity.Legendary)
				{
					legendaryStamps.Add(_stampsInStock[k].MyItem);
				}
			}
			else
			{
				if (!isReroll && _player.GetUnpackedItemsOfType(typeof(DownwardTrendingChart)).Count > 0)
				{
					itemInStock3.MyItem.Discount += 2;
					itemInStock3.ResetCost();
				}
				if (!isReroll && itemInStock3.MyItem is Avocado)
				{
					Avocado obj = (Avocado)itemInStock3.MyItem;
					obj.IsMushy = true;
					obj.Name = "Mushy Avocado";
				}
				PopulateStampInStock(player.FrozenStamps[k], k, isFirstShop, freeItem);
			}
			if (isCascadingAnimations && _stampsInStock[k] != null && _stampsInStock[k].MyItem != null)
			{
				yield return new WaitForSeconds(0.05f * GameStatics.GetCurrentAnimationSpeed());
			}
		}
		for (int k = 0; k < _tilesInStock.Length; k++)
		{
			GenerateTileInStock(k);
			if (isCascadingAnimations)
			{
				yield return new WaitForSeconds(0.05f * GameStatics.GetCurrentAnimationSpeed());
			}
		}
		if (isCascadingAnimations)
		{
			yield return new WaitForSeconds(0.25f * GameStatics.GetCurrentAnimationSpeed());
			_shopkeepCanvasCG.blocksRaycasts = false;
		}
		if (!SaveManager.GetIsSilencingShopkeeper())
		{
			bool secretSanta = GameStatics.GetPlayer().CurrentRunProgress.Challenge is SecretSanta;
			List<Item> list2 = foilStickers.Where((Item item) => !(item is HungryHippo)).ToList();
			if (legendaryStamps.Count > 0)
			{
				_dialogueController.DialogueEvent(DialogueUtility.GetStockLegendaryStampQuip(legendaryStamps[UnityEngine.Random.Range(0, legendaryStamps.Count)], secretSanta), fadeOverTime: true);
			}
			else if (list2.Count > 0)
			{
				_dialogueController.DialogueEvent(DialogueUtility.GetStockFoilStickerQuip(list2[UnityEngine.Random.Range(0, list2.Count)], secretSanta), fadeOverTime: true);
			}
			else if (GetRerollPrice() == _randomQuipRerollCost && isReroll)
			{
				_dialogueController.DialogueEvent(DialogueUtility.GetExpensiveRerollQuip(), fadeOverTime: true);
			}
		}
	}

	private void GenerateStickerInStock(int index, bool isFirstShop, bool freeItem)
	{
		Debug.Log($"Generating sticker at index {index}. Is first shop? {isFirstShop}");
		if (_player.CurrentRunProgress.Challenge is Masochist || _player.CurrentRunProgress.Challenge is InTheBeginning || (_stickersInStock[index] != null && _stickersInStock[index].IsFrozen))
		{
			return;
		}
		bool flag = UnityEngine.Random.Range(0, 100) < _foilPercentage;
		List<Type> list = new List<Type>();
		if (flag && !isFirstShop)
		{
			list.AddRange(from stickerInStock in _stickersInStock
				where stickerInStock != null && stickerInStock.MyItem != null
				select stickerInStock.MyItem.GetType());
			list.AddRange(from frozenSticker in _player.FrozenStickers
				where frozenSticker != null
				select frozenSticker.MyItem.GetType());
			list.AddRange(from sticker in _player.GetStickers(forItemComparison: true)
				where sticker.IsFoil
				select sticker into foilSticker
				select foilSticker.GetType());
		}
		else
		{
			list = new List<Type>(from item in _player.GetStickers(forItemComparison: true)
				where item.TimesUpgraded >= GameStatics.GetMaxUpgradeCount(item)
				select item.GetType());
			list.AddRange(from stickerInStock in _stickersInStock
				where stickerInStock != null && stickerInStock.MyItem != null
				select stickerInStock.MyItem.GetType());
			list.AddRange(from frozenSticker in _player.FrozenStickers
				where frozenSticker != null
				select frozenSticker.MyItem.GetType());
		}
		list.AddRange(_player.CurrentRunProgress.EmbargoedItemTypes);
		list.RemoveAll((Type itemType) => itemType == typeof(Frankenstein));
		if (isFirstShop)
		{
			Item randomBuildBiasedSticker = ItemPools.GetRandomBuildBiasedSticker(ItemRarity.Common, list);
			if (_player.CurrentRunProgress.Challenge is ColourSwap || _player.GetUnpackedItemsOfType(typeof(CanOfBeans)).Count > 0)
			{
				randomBuildBiasedSticker.RandomiseRelevantColours();
			}
			ItemInStock itemInStock = new ItemInStock(randomBuildBiasedSticker);
			PopulateStickerInStock(itemInStock, index, isFirstShop: true);
			return;
		}
		Item randomBuildBiasedSticker2 = ItemPools.GetRandomBuildBiasedSticker(list);
		if (_player.CurrentRunProgress.Challenge is ColourSwap || _player.GetUnpackedItemsOfType(typeof(CanOfBeans)).Count > 0)
		{
			randomBuildBiasedSticker2.RandomiseRelevantColours();
		}
		ItemInStock itemInStock2 = new ItemInStock(randomBuildBiasedSticker2);
		if (itemInStock2.MyItem != null)
		{
			if (freeItem)
			{
				itemInStock2.IsFree = true;
				itemInStock2.IsFirstDiscount = false;
			}
			itemInStock2.MyItem.IsFoil = flag;
		}
		PopulateStickerInStock(itemInStock2, index, isFirstShop: false, freeItem);
	}

	public void PopulateStickerInStock(ItemInStock itemInStock, int index, bool isFirstShop = false, bool freeItem = false)
	{
		itemInStock.IsFirstDiscount = isFirstShop;
		itemInStock.IsFree = freeItem;
		_stickersInStock[index] = itemInStock;
		if (itemInStock.MyItem == null)
		{
			_shopVisualController.ChangeStickerSlotVisibility(index, isVisible: false);
			return;
		}
		_shopVisualController.PopulateStickerInStock(itemInStock, index);
		_shopVisualController.ChangeStickerSlotVisibility(index, isVisible: true);
	}

	private void GenerateStampInStock(int index, bool isFirstShop, bool freeItem)
	{
		Debug.Log($"Generating stamp at index {index}. Is first shop? {isFirstShop}");
		if (_player.CurrentRunProgress.Challenge is Antiphilatelist || _player.CurrentRunProgress.Challenge is InTheBeginning || (_stampsInStock[index] != null && _stampsInStock[index].IsFrozen))
		{
			return;
		}
		List<Type> list = new List<Type>(from item in _player.GetStamps(forItemComparison: true)
			select item.GetType());
		list.AddRange(from stampInStock in _stampsInStock
			where stampInStock != null && stampInStock.MyItem != null
			select stampInStock.MyItem.GetType());
		list.AddRange(from frozenStamp in _player.FrozenStamps
			where frozenStamp != null
			select frozenStamp.MyItem.GetType());
		if (_player.CurrentRunProgress.Challenge != null)
		{
			list.Add(typeof(CoinPurse));
		}
		list.AddRange(_player.CurrentRunProgress.EmbargoedItemTypes);
		if (isFirstShop)
		{
			Item randomBuildBiasedStamp = ItemPools.GetRandomBuildBiasedStamp(list, ItemRarity.Common);
			if (_player.CurrentRunProgress.Challenge is ColourSwap || _player.GetUnpackedItemsOfType(typeof(CanOfBeans)).Count > 0)
			{
				randomBuildBiasedStamp.RandomiseRelevantColours();
			}
			ItemInStock itemInStock = new ItemInStock(randomBuildBiasedStamp);
			PopulateStampInStock(itemInStock, index, isFirstShop: true);
		}
		else
		{
			Item randomBuildBiasedStamp2 = ItemPools.GetRandomBuildBiasedStamp(list);
			if (_player.CurrentRunProgress.Challenge is ColourSwap || _player.GetUnpackedItemsOfType(typeof(CanOfBeans)).Count > 0)
			{
				randomBuildBiasedStamp2.RandomiseRelevantColours();
			}
			ItemInStock itemInStock2 = new ItemInStock(randomBuildBiasedStamp2);
			PopulateStampInStock(itemInStock2, index, isFirstShop: false, freeItem);
		}
	}

	private void PopulateStampInStock(ItemInStock itemInStock, int index, bool isFirstShop = false, bool freeItem = false)
	{
		itemInStock.IsFirstDiscount = isFirstShop;
		itemInStock.IsFree = freeItem;
		_stampsInStock[index] = itemInStock;
		if (itemInStock.MyItem == null)
		{
			_shopVisualController.ChangeStampSlotVisibility(index, isVisible: false);
			return;
		}
		_shopVisualController.PopulateStampInStock(itemInStock, index);
		_shopVisualController.ChangeStampSlotVisibility(index, isVisible: true);
	}

	private void GenerateTileInStock(int index)
	{
		Debug.Log($"Tile at index {index}");
		if (GameStatics.GetPlayer().GetUnpackedItemsOfType(typeof(DeliveryTruck)).Count > 0)
		{
			GenerateScatteredItemTilesInStock(index);
			return;
		}
		Tile tile = new Tile();
		GlyphType glyphType = GlyphType.None;
		int num = UnityEngine.Random.Range(0, _consumableTileTypeTotalWeighting);
		bool flag = false;
		foreach (KeyValuePair<GlyphType, int> consumableTileTypeWeighting in _consumableTileTypeWeightings)
		{
			if (num < consumableTileTypeWeighting.Value)
			{
				glyphType = consumableTileTypeWeighting.Key;
				break;
			}
			num -= consumableTileTypeWeighting.Value;
		}
		switch (glyphType)
		{
		case GlyphType.Letter:
			flag = true;
			tile.SetLetter(Vocabulary.ActiveLanguageVocabulary.LanguageAlphabet.GetRandomLetterWeighted());
			Debug.Log("Letter");
			break;
		case GlyphType.Blank:
			tile.SetGlyphType(GlyphType.Blank);
			Debug.Log("Blank");
			break;
		case GlyphType.Number:
			if (UnityEngine.Random.Range(0, 5) == 0)
			{
				tile.SetFractionNumbers(Alphabet.GetFractionNumbers(Alphabet.GetRandomFraction()));
				Debug.Log("Fraction");
			}
			else
			{
				tile.SetNumber(UnityEngine.Random.Range(1, 10));
				Debug.Log("Number");
			}
			break;
		case GlyphType.BespokeCard:
			tile.SetGlyphType(GlyphType.BespokeCard);
			tile.SetSuit(Suit.Joker);
			Debug.Log("Joker");
			break;
		case GlyphType.Chess:
			tile.SetChessPiece(ChessPieces.GetRandomChessPiece());
			Debug.Log("Chess");
			break;
		}
		if (UnityEngine.Random.Range(0, 10) == 0 && SaveManager.IsBulkUnlockUnlocked(typeof(CardsUnlock)) && tile.GetSuit() != Suit.Joker)
		{
			tile.SetSuit(PlayingCardUtility.GetRandomCardSuit());
			Debug.Log("Suited");
		}
		TileType tileType = (flag ? ItemPools.GetRandomColouredTileTypeWeighted() : ItemPools.GetRandomTileTypeWeighted());
		tile.SetTileType(tileType);
		Debug.Log($"Tile type: {tileType}");
		TileInStock tileInStock = new TileInStock(tile, _tileTypeCosts[tile.GetTileType()]);
		_tilesInStock[index] = tileInStock;
		_shopVisualController.PopulateTileInStock(tileInStock, index);
	}

	private void GenerateScatteredItemTilesInStock(int index)
	{
		Tile tile = new Tile();
		Item randomItem = ScatteredItemPools.GetRandomItem();
		if (GameStatics.GetPlayer().CurrentRunProgress.Challenge is ColourSwap || _player.GetUnpackedItemsOfType(typeof(CanOfBeans)).Count > 0)
		{
			randomItem.RandomiseRelevantColours();
		}
		tile.SetScatteredItem(randomItem);
		tile.SetTileType(ItemPools.GetRandomTileTypeWeighted());
		if (UnityEngine.Random.Range(0, 10) == 0 && SaveManager.IsBulkUnlockUnlocked(typeof(CardsUnlock)))
		{
			tile.SetSuit(PlayingCardUtility.GetRandomCardSuit());
		}
		TileInStock tileInStock = new TileInStock(tile, _tileTypeCosts[tile.GetTileType()]);
		_tilesInStock[index] = tileInStock;
		_shopVisualController.PopulateTileInStock(tileInStock, index);
	}

	public ItemInStock[] GetStickersInStock()
	{
		return _stickersInStock;
	}

	public bool IsAngelInvestmentAvailable()
	{
		if (!_hasUsedAngelInvestment)
		{
			return _player.GetUnpackedItemsOfType(typeof(FutureFunds)).Count > 0;
		}
		return false;
	}

	private void OnItemBuyButtonClicked(int boughtSlotIndex, bool isStamp)
	{
		ShopItemSlot slot = _shopVisualController.GetShopItemSlotFromIndex(boughtSlotIndex, isStamp);
		_freeItemActive = false;
		if ((GameStatics.GetPlayer().Money < slot.MyItemInStock.Cost && !IsAngelInvestmentAvailable() && !slot.MyItemInStock.IsFirstDiscount) || (isStamp && _player.GetStamps(forItemComparison: true).Count >= 5))
		{
			return;
		}
		Player player = GameStatics.GetPlayer();
		Type type = slot.MyItemInStock.MyItem.GetType();
		bool flag = player.GetAllItems(forItemComparison: true).Exists((Item item) => item.GetType() == slot.MyItemInStock.MyItem.GetType());
		foreach (Item item in from sticker in player.GetStickers(forItemComparison: true)
			where sticker is Frankenstein
			select sticker)
		{
			Frankenstein frankenstein = item as Frankenstein;
			if (type == frankenstein.StitchedItems[0].GetType() || type == frankenstein.StitchedItems[1].GetType())
			{
				flag = true;
			}
		}
		if (!isStamp && _player.GetStickers(forItemComparison: true).Count >= 5 && !flag)
		{
			return;
		}
		bool flag2 = false;
		flag2 = ((!isStamp) ? BuySticker(slot, isHippoUpgrade: false) : BuyStamp(slot));
		ResetCosts();
		UpdateCosts();
		if (!(_player.GetUnpackedItemsOfType(typeof(EfficientRecycler)).Count > 0 && flag2))
		{
			return;
		}
		_rerollCount++;
		foreach (Item item2 in _player.GetUnpackedItemsOfType(typeof(RollerSkate)))
		{
			(item2 as RollerSkate).PreviousShopRestockCount = _rerollCount;
		}
		foreach (Item item3 in _player.GetUnpackedItemsOfType(typeof(Rollercoaster)))
		{
			(item3 as Rollercoaster).MakeRollercoasterCheck();
		}
		foreach (Item item4 in _player.GetUnpackedItemsOfType(typeof(Lollipop), forItemComparison: true))
		{
			(item4 as Lollipop).IncrementLollipop();
		}
		foreach (Item item5 in _player.GetUnpackedItemsOfType(typeof(Snail), forItemComparison: true))
		{
			(item5 as Snail).IncrementSnail();
		}
		StartCoroutine(GenerateGoodsInStock(isFirstShop: false, isCascadingAnimations: false, isReroll: true, IsAngelInvestmentAvailable()));
		CharacterInfoPanel.SingletonInventoryVisualController.PopulateCash();
		CharacterInfoPanel.SingletonInventoryVisualController.ClearInspectedItem();
	}

	public void UpdateCosts()
	{
		Debug.Log("Updating costs of items in shop");
		ItemInStock[] stickersInStock = _stickersInStock;
		foreach (ItemInStock itemInStock in stickersInStock)
		{
			if (itemInStock != null)
			{
				bool isFirstDiscount = itemInStock.IsFirstDiscount;
				bool isFree = itemInStock.IsFree;
				int cost = itemInStock.Cost;
				itemInStock.ResetCost();
				itemInStock.IsFirstDiscount = isFirstDiscount;
				itemInStock.IsFree = isFree;
				if (isFree && !IsAngelInvestmentAvailable())
				{
					PopulateStickerInStock(itemInStock, Array.IndexOf(_stickersInStock, itemInStock), isFirstDiscount, IsAngelInvestmentAvailable());
				}
				else if (itemInStock.Cost != cost)
				{
					PopulateStickerInStock(itemInStock, Array.IndexOf(_stickersInStock, itemInStock), isFirstDiscount, IsAngelInvestmentAvailable());
				}
			}
		}
		stickersInStock = _stampsInStock;
		foreach (ItemInStock itemInStock2 in stickersInStock)
		{
			if (itemInStock2 != null)
			{
				bool isFirstDiscount2 = itemInStock2.IsFirstDiscount;
				bool isFree2 = itemInStock2.IsFree;
				int cost2 = itemInStock2.Cost;
				itemInStock2.ResetCost();
				itemInStock2.IsFirstDiscount = isFirstDiscount2;
				itemInStock2.IsFree = isFree2;
				if (isFree2 && !IsAngelInvestmentAvailable())
				{
					PopulateStampInStock(itemInStock2, Array.IndexOf(_stampsInStock, itemInStock2), isFirstDiscount2, IsAngelInvestmentAvailable());
				}
				else if (itemInStock2.Cost != cost2)
				{
					PopulateStampInStock(itemInStock2, Array.IndexOf(_stampsInStock, itemInStock2), isFirstDiscount2, IsAngelInvestmentAvailable());
				}
			}
		}
	}

	public void UpdateHippoButtons()
	{
		foreach (ShopItemSlot shopItemSlot in _shopVisualController.GetShopItemSlots())
		{
			shopItemSlot.TryUpdateHippoButton(IsAngelInvestmentAvailable());
		}
	}

	private void ResetCosts()
	{
		for (int i = 0; i < _stickersInStock.Length; i++)
		{
			ItemInStock itemInStock = _stickersInStock[i];
			if (itemInStock != null && (itemInStock.IsFirstDiscount || itemInStock.IsFree))
			{
				itemInStock.ResetCost();
				PopulateStickerInStock(itemInStock, i);
			}
		}
		for (int j = 0; j < _stampsInStock.Length; j++)
		{
			ItemInStock itemInStock2 = _stampsInStock[j];
			if (itemInStock2 != null && (itemInStock2.IsFirstDiscount || itemInStock2.IsFree))
			{
				itemInStock2.ResetCost();
				PopulateStampInStock(itemInStock2, j);
			}
		}
	}

	private bool BuyStamp(ShopItemSlot itemSlot)
	{
		Player player = GameStatics.GetPlayer();
		Item item = itemSlot.MyItemInStock.MyItem;
		bool flag = IsAngelInvestmentAvailable();
		if (!player.Stamps.Contains(null))
		{
			PersistentSound.SingletonSoundController.FailedPurchase();
			return false;
		}
		if (player.GetStamps(forItemComparison: true).Exists((Item stamp) => stamp.GetType() == item.GetType()))
		{
			PersistentSound.SingletonSoundController.FailedPurchase();
			return false;
		}
		PersistentSound.SingletonSoundController.BuyItem(item, isUpgradingSticker: false);
		player.AddItemToInventory(item);
		if (item is EfficientRecycler)
		{
			StartCoroutine(PulseEfficientRecycler());
		}
		if (flag)
		{
			_hasUsedAngelInvestment = true;
			item.InvestMoneyInItem(0);
		}
		else if (!itemSlot.MyItemInStock.IsFirstDiscount)
		{
			int cost = itemSlot.MyItemInStock.Cost;
			player.ChangeMoney(-cost);
			item.InvestMoneyInItem(cost);
		}
		else
		{
			item.InvestMoneyInItem(0);
		}
		player.FrozenStamps[Array.IndexOf(_stampsInStock, itemSlot.MyItemInStock)] = null;
		_stampsInStock[itemSlot.Index] = null;
		_shopVisualController.ChangeSlotVisibility(itemSlot, isVisible: false);
		CharacterInfoPanel.SingletonInventoryVisualController.PopulateStamps();
		CharacterInfoPanel.SingletonInventoryVisualController.PopulateCash();
		CharacterInfoPanel.SingletonInventoryVisualController.ClearInspectedItem();
		if (player.CurrentRunProgress.Challenge is DecisionParalysis)
		{
			GenerateStampInStock(itemSlot.Index, isFirstShop: false, freeItem: false);
		}
		_shopVisualController.RepopulateShopItems(GetRerollPrice());
		return true;
	}

	private bool BuySticker(ShopItemSlot itemSlot, bool isHippoUpgrade, Item replacementItem = null)
	{
		Player player = GameStatics.GetPlayer();
		Item item2 = ((replacementItem == null) ? itemSlot.MyItemInStock.MyItem : replacementItem);
		if (item2.IsFoil && player.GetStickers(forItemComparison: true).Exists((Item inventoryItem) => inventoryItem.GetType() == item2.GetType()))
		{
			player.GetStickers(forItemComparison: true).Find((Item inventoryItem) => inventoryItem.GetType() == item2.GetType()).IsFoil = true;
		}
		List<Item> list = (from playerItem in player.GetStickers(forItemComparison: true)
			where playerItem.GetType() == item2.GetType()
			select playerItem).ToList();
		foreach (Item item3 in from sticker in player.GetStickers(forItemComparison: true)
			where sticker is Frankenstein
			select sticker)
		{
			Frankenstein frankenstein = item3 as Frankenstein;
			if (item2.GetType() == frankenstein.StitchedItems[0].GetType() || item2.GetType() == frankenstein.StitchedItems[1].GetType())
			{
				list.Add(item3);
			}
		}
		if (list.Exists((Item sticker) => sticker.TimesUpgraded >= GameStatics.GetMaxUpgradeCount(sticker)))
		{
			PersistentSound.SingletonSoundController.FailedPurchase();
			return false;
		}
		List<Item> list2 = list.Where((Item playerItem) => playerItem.TimesUpgraded < GameStatics.GetMaxUpgradeCount(playerItem)).ToList();
		bool flag = list2.Count > 0;
		if (!flag && !player.Stickers.Contains(null))
		{
			PersistentSound.SingletonSoundController.FailedPurchase();
			return false;
		}
		if (isHippoUpgrade)
		{
			PersistentSound.SingletonSoundController.PressHippoButton();
			if (player.GetStickers(forItemComparison: true).Find((Item item) => item is HungryHippo) is HungryHippo hungryHippo)
			{
				Coroutine animationCoroutine = hungryHippo.GetAnimationCoroutine();
				if (animationCoroutine != null)
				{
					StopCoroutine(animationCoroutine);
				}
				MostRecentHippoAnimationStartTime = Time.timeSinceLevelLoad;
				animationCoroutine = StartCoroutine(hungryHippo.DoMunchAnimation());
			}
		}
		if (item2.IsFoil)
		{
			PersistentSound.SingletonSoundController.PurchaseFoilSticker();
		}
		if (flag)
		{
			list2[0].Upgrade(0);
			list2[0].TimesUpgraded++;
			PersistentSound.SingletonSoundController.BuyItem(list2[0], isUpgradingSticker: true);
			if (item2.IsFoil && list2[0] is Frankenstein)
			{
				list2[0].IsFoil = true;
			}
		}
		else
		{
			player.AddItemToInventory(item2);
			PersistentSound.SingletonSoundController.BuyItem(item2, isUpgradingSticker: false);
		}
		if (IsAngelInvestmentAvailable())
		{
			_hasUsedAngelInvestment = true;
			if (flag)
			{
				list2[0].InvestMoneyInItem(0);
			}
			else
			{
				item2.InvestMoneyInItem(0);
			}
		}
		else if (!itemSlot.MyItemInStock.IsFirstDiscount)
		{
			int cost = itemSlot.MyItemInStock.Cost;
			player.ChangeMoney(-cost);
			if (flag)
			{
				list2[0].InvestMoneyInItem(cost);
			}
			else
			{
				item2.InvestMoneyInItem(cost);
			}
		}
		else
		{
			item2.InvestMoneyInItem(0);
		}
		if (_stickersInStock.Contains(itemSlot.MyItemInStock))
		{
			player.FrozenStickers[Array.IndexOf(_stickersInStock, itemSlot.MyItemInStock)] = null;
			_stickersInStock[itemSlot.Index] = null;
			_shopVisualController.ChangeSlotVisibility(itemSlot, isVisible: false);
			CharacterInfoPanel.SingletonInventoryVisualController.PopulateStickers();
		}
		else
		{
			player.FrozenStamps[Array.IndexOf(_stampsInStock, itemSlot.MyItemInStock)] = null;
			_stampsInStock[itemSlot.Index] = null;
			_shopVisualController.ChangeSlotVisibility(itemSlot, isVisible: false);
			CharacterInfoPanel.SingletonInventoryVisualController.PopulateStickers();
		}
		CharacterInfoPanel.SingletonInventoryVisualController.PopulateCash();
		CharacterInfoPanel.SingletonInventoryVisualController.ClearInspectedItem();
		CharacterInfoPanel.SingletonInventoryVisualController.ClearInspectedTile();
		if (player.CurrentRunProgress.Challenge is DecisionParalysis)
		{
			GenerateStickerInStock(itemSlot.Index, isFirstShop: false, freeItem: false);
		}
		if (itemSlot.MyItemInStock.MyItem is HungryHippo)
		{
			UpdateHippoButtons();
		}
		_shopVisualController.RepopulateShopItems(GetRerollPrice());
		if (flag && !SaveManager.HasSeenUpgradeFirstTimeDialogue() && player.GetStickers(forItemComparison: true).Exists((Item sticker) => sticker.TimesUpgraded == 2))
		{
			TutorialController component = GetComponent<TutorialController>();
			StartCoroutine(component.UpgradeFirstTimeTutorial());
		}
		return true;
	}

	private void OnTileBuyButtonClicked(int boughtSlotIndex)
	{
		ShopTile tileSlotFromIndex = _shopVisualController.GetTileSlotFromIndex(boughtSlotIndex);
		Player player = GameStatics.GetPlayer();
		if (GameStatics.GetPlayer().Money < tileSlotFromIndex.MyTileInStock.GetPrice() || player.GetTiles().Count >= 10 || (player.GetUnpackedItemsOfType(typeof(Stadium)).Count == 0 && player.GetTiles().Count >= 5))
		{
			PersistentSound.SingletonSoundController.FailedPurchase();
		}
		else
		{
			BuyTile(tileSlotFromIndex);
		}
	}

	private void BuyTile(ShopTile shopTile)
	{
		Player player = GameStatics.GetPlayer();
		if (!player.ConsumableTiles.Contains(null))
		{
			PersistentSound.SingletonSoundController.FailedPurchase();
			return;
		}
		player.AddTileToInventory(shopTile.MyTile);
		player.ChangeMoney(-shopTile.MyTileInStock.GetPrice());
		if (player.CurrentRunProgress.Challenge is DecisionParalysis)
		{
			GenerateTileInStock(shopTile.Index);
		}
		else
		{
			_shopVisualController.ChangeTileVisibility(shopTile, isVisible: false);
		}
		PersistentSound.SingletonSoundController.BuyTile(shopTile.MyTile);
		_tilesInStock[shopTile.Index].HasBeenBought = true;
		CharacterInfoPanel.SingletonInventoryVisualController.PopulateTiles();
		CharacterInfoPanel.SingletonInventoryVisualController.PopulateCash();
		CharacterInfoPanel.SingletonInventoryVisualController.ClearInspectedItem();
		CharacterInfoPanel.SingletonInventoryVisualController.ClearInspectedTile();
		_shopVisualController.RepopulateShopItems(GetRerollPrice());
	}

	private void OnFreezeButtonClicked(int frozenSlotIndex, bool isStamp)
	{
		Player player = GameStatics.GetPlayer();
		ShopItemSlot shopItemSlotFromIndex = _shopVisualController.GetShopItemSlotFromIndex(frozenSlotIndex, isStamp);
		shopItemSlotFromIndex.MyItemInStock.IsFrozen = !shopItemSlotFromIndex.MyItemInStock.IsFrozen;
		ItemInStock[] array = (isStamp ? player.FrozenStamps : player.FrozenStickers);
		array[frozenSlotIndex] = ((array[frozenSlotIndex] == null) ? shopItemSlotFromIndex.MyItemInStock : null);
		if (shopItemSlotFromIndex.MyItemInStock.IsFrozen)
		{
			PersistentSound.SingletonSoundController.FreezeItem();
		}
		else
		{
			PersistentSound.SingletonSoundController.UnfreezeItem();
		}
		_shopVisualController.ChangeFreezeStatus(shopItemSlotFromIndex, shopItemSlotFromIndex.MyItemInStock.IsFrozen);
	}

	private void OnHippoButtonClicked(int boughtSlotIndex, bool isStamp)
	{
		ShopItemSlot shopItemSlotFromIndex = _shopVisualController.GetShopItemSlotFromIndex(boughtSlotIndex, isStamp);
		if (GameStatics.GetPlayer().Money < shopItemSlotFromIndex.MyItemInStock.Cost && !IsAngelInvestmentAvailable())
		{
			PersistentSound.SingletonSoundController.FailedPurchase();
			return;
		}
		Item item = new HungryHippo();
		if (shopItemSlotFromIndex.MyItemInStock.MyItem.IsFoil)
		{
			item.IsFoil = true;
		}
		bool flag = BuySticker(shopItemSlotFromIndex, isHippoUpgrade: true, item);
		ResetCosts();
		UpdateCosts();
		if (!(_player.GetUnpackedItemsOfType(typeof(EfficientRecycler)).Count > 0 && flag))
		{
			return;
		}
		foreach (Item item2 in _player.GetUnpackedItemsOfType(typeof(Rollercoaster)))
		{
			(item2 as Rollercoaster).MakeRollercoasterCheck();
		}
		foreach (Item item3 in _player.GetUnpackedItemsOfType(typeof(Lollipop)))
		{
			(item3 as Lollipop).IncrementLollipop();
		}
		foreach (Item item4 in _player.GetUnpackedItemsOfType(typeof(Snail)))
		{
			(item4 as Snail).IncrementSnail();
		}
		_rerollCount++;
		foreach (Item item5 in _player.GetUnpackedItemsOfType(typeof(RollerSkate)))
		{
			(item5 as RollerSkate).PreviousShopRestockCount = _rerollCount;
		}
		StartCoroutine(GenerateGoodsInStock(isFirstShop: false, isCascadingAnimations: false, isReroll: true, IsAngelInvestmentAvailable()));
		CharacterInfoPanel.SingletonInventoryVisualController.PopulateCash();
		CharacterInfoPanel.SingletonInventoryVisualController.ClearInspectedItem();
	}

	public void OnRerollButtonClickedCallback()
	{
		Player player = GameStatics.GetPlayer();
		_freeItemActive = false;
		if (player.Money < GetRerollPrice() || player.CurrentRunProgress.Challenge is DecisionParalysis)
		{
			PersistentSound.SingletonSoundController.FailedPurchase();
			return;
		}
		PersistentSound.SingletonSoundController.RerollShop();
		foreach (Item item in player.GetUnpackedItemsOfType(typeof(Rollercoaster)))
		{
			(item as Rollercoaster).MakeRollercoasterCheck();
		}
		foreach (Item item2 in _player.GetUnpackedItemsOfType(typeof(Lollipop)))
		{
			(item2 as Lollipop).IncrementLollipop();
		}
		foreach (Item item3 in _player.GetUnpackedItemsOfType(typeof(Snail)))
		{
			(item3 as Snail).IncrementSnail();
		}
		player.ChangeMoney(-GetRerollPrice());
		_rerollPrice++;
		if (_isMegShop)
		{
			_rerollPrice = 1;
		}
		_rerollCount++;
		foreach (Item item4 in _player.GetUnpackedItemsOfType(typeof(RollerSkate)))
		{
			(item4 as RollerSkate).PreviousShopRestockCount = _rerollCount;
		}
		StartCoroutine(GenerateGoodsInStock(isFirstShop: false, isCascadingAnimations: true, isReroll: true, IsAngelInvestmentAvailable()));
		_shopVisualController.PopulateRerollCost(GetRerollPrice());
		RepopulateShopItems();
		CharacterInfoPanel.SingletonInventoryVisualController.PopulateCash();
		CharacterInfoPanel.SingletonInventoryVisualController.ClearInspectedItem();
		if (GetRerollPrice() >= 6)
		{
			Achievements.UnlockAchievement(typeof(HighRoller));
		}
	}

	public void OnAdviceButtonClickedCallback()
	{
		if (_isMegShop)
		{
			_dialogueController.DialogueEvent(ShopRecommendation.GetMegShopRecommendation(_player.GetAllItems(), GetItemsInShop()), fadeOverTime: true);
			return;
		}
		(string, Emotions) shopRecommendation = ShopRecommendation.GetShopRecommendation(_player.GetAllItems(), GetItemsInShop(), _tilesInStock.Where((TileInStock tile) => !tile.HasBeenBought).ToList(), GetRerollPrice(), _freeItemActive);
		Debug.Log("quip = " + shopRecommendation.Item1);
		_dialogueController.DialogueEvent(shopRecommendation, fadeOverTime: true);
	}

	public void OnLeaveShopButtonClickedCallback()
	{
		Player player = GameStatics.GetPlayer();
		_unlocksBannerController.StopCheckingAchievements();
		foreach (RollerSkate item in player.GetUnpackedItemsOfType(typeof(RollerSkate)))
		{
			item.PreviousShopRestockCount = _rerollCount;
			Debug.Log($"Setting Roller Skate previous shop restock count to {_rerollCount}");
		}
		foreach (SurpriseDelivery item2 in player.GetUnpackedItemsOfType(typeof(SurpriseDelivery)))
		{
			item2.OnLeaveShop();
			CharacterInfoPanel.SingletonInventoryVisualController.PopulateStickers();
		}
		ItemInStock[] frozenStamps = player.FrozenStamps;
		foreach (ItemInStock itemInStock in frozenStamps)
		{
			if (itemInStock != null && itemInStock.MyItem is ShavedIce)
			{
				((ShavedIce)itemInStock.MyItem).Freezes++;
			}
		}
		if (_isMegShop)
		{
			CretaceousMegBoss cretaceousMegBoss = player.ActiveBossModifiers.Find((BossModifier boss) => boss is CretaceousMegBoss) as CretaceousMegBoss;
			player.FrozenStickers = cretaceousMegBoss.PlayerFrozenStickersAtStart;
			player.FrozenStamps = cretaceousMegBoss.PlayerFrozenStampsAtStart;
		}
		if (player.CurrentRunProgress.Challenge is SpeedrunChallenge || player.CurrentRunProgress.CurrentRunStatistics.IsSpeedrunMode)
		{
			float num = _topBarController.StopTimerAndGetCurrentTime();
			Debug.Log($"split / {player.CurrentRunProgress.GetStage()} - {player.CurrentRunProgress.GetCurrentNodeType()} / {num}");
			if (player.CurrentRunProgress.Challenge is SpeedrunChallenge)
			{
				StopCoroutine(_speedrunTimeCheckCoroutine);
			}
		}
		TransitionToNextScene();
	}

	private void TransitionToNextScene()
	{
		string sceneString = GameStatics.GetPlayer().CurrentRunProgress.GoToNextNodeAndGetSceneName();
		_transitionController.TransitionToNewScene(sceneString);
	}

	private IEnumerator PulseEfficientRecycler()
	{
		yield return new WaitForSeconds(0.5f * GameStatics.GetCurrentAnimationSpeed());
		while (true)
		{
			ItemObject itemObject2 = CharacterInfoPanel.SingletonInventoryVisualController.GetItemObjects().Find((ItemObject itemObject) => itemObject.MyItem is EfficientRecycler);
			if (itemObject2 == null)
			{
				break;
			}
			if (!(GameStatics.GetPlayer().CurrentRunProgress.Challenge is PlayingFavourites) || GameStatics.GetPlayer().GetHBFavouriteStamp() is EfficientRecycler)
			{
				itemObject2.ActionPulse(0.5f);
			}
			yield return new WaitForSeconds(0.8f * GameStatics.GetCurrentAnimationSpeed());
		}
		Debug.Log("Stop pulsing Efficient Recycler, it has been destroyed");
	}

	private IEnumerator PulseFutureFunds()
	{
		while (IsAngelInvestmentAvailable())
		{
			ItemObject itemObject2 = CharacterInfoPanel.SingletonInventoryVisualController.GetItemObjects().Find((ItemObject itemObject) => itemObject.MyItem is FutureFunds);
			if (!(itemObject2 == null))
			{
				itemObject2.ActionPulse(0.5f);
				yield return new WaitForSeconds(0.8f * GameStatics.GetCurrentAnimationSpeed());
				continue;
			}
			break;
		}
	}

	private List<Item> GetItemsInShop()
	{
		List<Item> list = new List<Item>();
		list.AddRange(from stockItem in _stampsInStock
			where stockItem != null
			select stockItem.MyItem);
		list.AddRange(from stockItem in _stickersInStock
			where stockItem != null
			select stockItem.MyItem);
		return list;
	}

	public void RepopulateShopItems()
	{
		if (GameStatics.GetPlayer().GetUnpackedItemsOfType(typeof(FriedShrimp)).Count > 0)
		{
			_rerollDeduction = 1;
		}
		else
		{
			_rerollDeduction = 0;
		}
		Debug.Log($"Reroll cost = {GetRerollPrice()}");
		_shopVisualController.PopulateRerollCost(GetRerollPrice());
		_shopVisualController.RepopulateShopItems(GetRerollPrice());
	}

	public List<Item> GetCurrentStock()
	{
		List<Item> list = new List<Item>();
		ItemInStock[] stickersInStock = _stickersInStock;
		foreach (ItemInStock itemInStock in stickersInStock)
		{
			if (itemInStock != null)
			{
				list.Add(itemInStock.MyItem);
			}
		}
		stickersInStock = _stampsInStock;
		foreach (ItemInStock itemInStock2 in stickersInStock)
		{
			if (itemInStock2 != null)
			{
				list.Add(itemInStock2.MyItem);
			}
		}
		return list;
	}

	public void OnAcquireVolcano()
	{
		foreach (ShopItemSlot shopItemSlot in _shopVisualController.GetShopItemSlots())
		{
			if (shopItemSlot.MyItemInStock.IsFrozen)
			{
				shopItemSlot.MyItemInStock.IsFrozen = false;
				_shopVisualController.ChangeFreezeStatus(shopItemSlot, shopItemSlot.MyItemInStock.IsFrozen);
			}
		}
		PersistentSound.SingletonSoundController.UnfreezeItem();
		Player player = GameStatics.GetPlayer();
		for (int i = 0; i < player.FrozenStickers.Length; i++)
		{
			player.FrozenStickers[i] = null;
		}
		for (int j = 0; j < player.FrozenStamps.Length; j++)
		{
			player.FrozenStamps[j] = null;
		}
		_shopVisualController.HideFreezeButtons();
	}

	public void SetFoilPercentage(int percentage = -1)
	{
		if (!SaveManager.HasSeenUpgradeFirstTimeDialogue())
		{
			_foilPercentage = -1;
		}
		else if (percentage == -1)
		{
			_foilPercentage = ((GameStatics.GetPlayer().GetUnpackedItemsOfType(typeof(FortuneCookie)).Count > 0) ? 5 : 0);
		}
		else
		{
			_foilPercentage = percentage;
		}
	}

	public void GoToMainMenu()
	{
		CharacterInfoPanel.SingletonInventoryVisualController.RemovePanel();
		MusicController.OnEndOfEncounter();
		StartCoroutine(_transitionController.AnimateAndTransition(SceneNames.MainMenuSceneName));
	}

	public void GoToQuestSelect()
	{
		CharacterInfoPanel.SingletonInventoryVisualController.RemovePanel();
		MusicController.OnEndOfEncounter();
		StartCoroutine(_transitionController.AnimateAndTransition(SceneNames.ChallengeRunSceneName));
	}

	public void RetryRun()
	{
		CharacterInfoPanel.SingletonInventoryVisualController.RemovePanel();
		MusicController.OnEndOfEncounter();
		TransitionController transitionController = UnityEngine.Object.FindAnyObjectByType<TransitionController>();
		Player player = GameStatics.GetPlayer();
		GameStatics.InitialisePlayerForNewRun(player.MyCharacter.GetType(), (player.CurrentRunProgress.Challenge != null) ? player.CurrentRunProgress.Challenge.GetType() : null, player.CurrentRunProgress.Ascension);
		string sceneString = GameStatics.GetPlayer().CurrentRunProgress.GoToNextNodeAndGetSceneName();
		transitionController.TransitionToNewScene(sceneString);
	}
}
