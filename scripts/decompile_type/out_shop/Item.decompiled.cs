using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using nickeltin.SDF.Runtime;
using UnityEngine;

public abstract class Item
{
	public string Name;

	public List<ItemSpriteData> SpriteData = new List<ItemSpriteData>();

	public string ArtFileName;

	public List<UpgradeableComponent> UpgradeableComponents = new List<UpgradeableComponent>();

	public int TimesUpgraded;

	public ItemRarity Rarity;

	public int Cost;

	public int SellCost;

	public int Discount;

	public List<ItemTag> Tags = new List<ItemTag>();

	public List<ItemTag> DependencyTags = new List<ItemTag>();

	public List<ItemTag> ShopAdviceAdditionalTags = new List<ItemTag>();

	public List<ItemFunctionTag> ItemFunctionTags = new List<ItemFunctionTag>();

	public List<Type> EnablerItems = new List<Type>();

	public bool IsFoil;

	public bool IsSellingPrevented;

	public bool CostsMoneyToSell;

	public List<int> MoneyInvested = new List<int>();

	public bool IsFood;

	public bool IsAnimal;

	public int WrappedPresentIndex;

	public bool IsHumanBoyFavouriteSticker;

	public bool IsUnderhandTarget;

	public bool IsOverhandTarget;

	public List<Color> PinColors = new List<Color>
	{
		new Color32(246, 72, 83, byte.MaxValue),
		new Color32(82, 152, 243, byte.MaxValue)
	};

	public List<(string Text, Emotions Emotion)> BuyItemQuips = new List<(string, Emotions)>();

	public List<(string Text, Emotions Emotion)> UpgradeItemQuips = new List<(string, Emotions)>();

	public bool IsBlacklistedFromShopRecommendations;

	public List<TileType> RelevantColours = new List<TileType>();

	public static List<ItemTag> GeneratorTags = new List<ItemTag>
	{
		ItemTag.BlankGenerator,
		ItemTag.BlueGenerator,
		ItemTag.RedGenerator,
		ItemTag.CashGenerator,
		ItemTag.VoidGenerator,
		ItemTag.ShinyGenerator,
		ItemTag.ArrowGenerator,
		ItemTag.CurrencyGenerator,
		ItemTag.ChessGenerator,
		ItemTag.CardsGenerator,
		ItemTag.NumbersGenerator,
		ItemTag.ItemScatterer
	};

	public virtual string GetDescription()
	{
		return "";
	}

	public virtual string GetDescription(bool forPinDraft = false)
	{
		return GetDescription();
	}

	public virtual Sprite GetCurrentSprite()
	{
		return SpriteData.Find((ItemSpriteData data) => data.Usage == ItemSpriteUsage.Default).GetSprite();
	}

	public int GetWrappedPresentIndex()
	{
		if (WrappedPresentIndex == 0)
		{
			WrappedPresentIndex = UnityEngine.Random.Range(1, 10);
		}
		return WrappedPresentIndex;
	}

	public virtual List<string> GetAccumulatorWords()
	{
		return new List<string>();
	}

	public virtual List<List<string>> GetAccumulatorPairs()
	{
		return new List<List<string>>();
	}

	public virtual Sprite GetWrappedSprite()
	{
		return Resources.Load<Sprite>($"Items/Gifts/Gift{GetWrappedPresentIndex()}");
	}

	public virtual SDFSpriteMetadataAsset GetCurrentSDFSprite()
	{
		return SpriteData.Find((ItemSpriteData data) => data.Usage == ItemSpriteUsage.Default).GetSDFSprite();
	}

	public virtual SDFSpriteMetadataAsset GetWrappedSDF()
	{
		Resources.Load<Sprite>($"Items/Gifts/Gift{GetWrappedPresentIndex()}").TryGetSpriteMetadataAsset(out var metadataAsset);
		return metadataAsset;
	}

	public string GetUpgradedDescription(int upgradeableComponentIndex = 0)
	{
		Player player = GameStatics.GetPlayer();
		Item item2 = Activator.CreateInstance(GetType()) as Item;
		if (item2 is MichaelsBook && player.GetAllItems().Exists((Item item) => GetType() == item.GetType()))
		{
			Item item3 = player.GetAllItems().Find((Item item) => item.GetType() == GetType());
			if (item3 != null)
			{
				(item2 as MichaelsBook).StarterWords = (item3 as MichaelsBook).StarterWords;
				(item2 as MichaelsBook).WordsAtEachLevel = (item3 as MichaelsBook).WordsAtEachLevel;
				(item2 as MichaelsBook).StarterWordsInitialised = (item3 as MichaelsBook).StarterWordsInitialised;
			}
		}
		if (player.CurrentRunProgress.Challenge is ColourSwap || player.GetUnpackedItemsOfType(typeof(CanOfBeans)).Count > 0)
		{
			item2.RandomiseRelevantColours();
		}
		int level = player.GetAllItems(forItemComparison: true).Find((Item item) => item.GetType() == GetType()).UpgradeableComponents[0].Level;
		while (item2.UpgradeableComponents[upgradeableComponentIndex].Level < level + 1)
		{
			item2.Upgrade(upgradeableComponentIndex);
		}
		return FormatUpgradedDescription(item2.GetDescription());
	}

	public string FormatUpgradedDescription(string description)
	{
		string[] array = description.Split(GameStatics.ZeroWidthCharacter);
		string[] array2 = new string[8] { "<b><color=#f7cf02>", "</b></color=#f7cf02>", "<b><color=#f7cf02>", "</b></color=#f7cf02>", "<b><color=#f7cf02>", "</b></color=#f7cf02>", "<b><color=#f7cf02>", "</b></color=#f7cf02>" };
		string text = "";
		for (int i = 0; i < array.Length; i++)
		{
			text += array[i];
			if (i < 8)
			{
				text += array2[i];
			}
		}
		return text;
	}

	public bool CanBeUpgraded()
	{
		if (!(this is LeftHumanHand) && UpgradeableComponents.Count == 1)
		{
			return TimesUpgraded < GameStatics.GetMaxUpgradeCount(this);
		}
		return false;
	}

	public virtual void Upgrade(int componentIndex, bool isUpgradingBoth = false)
	{
		Debug.Log($"UPGRADING PIN COMPONENT {componentIndex} with isUpgradingBoth = {isUpgradingBoth}");
		if (!isUpgradingBoth)
		{
			UpgradeableComponents[componentIndex].Upgrade();
		}
		else
		{
			UpgradeableComponents[0].Upgrade();
			UpgradeableComponents[1].Upgrade();
		}
		Achievements.TryUnlockStacked();
	}

	public virtual void Downgrade(int componentIndex)
	{
		UpgradeableComponents[componentIndex].Downgrade();
	}

	public void LeftHandUpgrade()
	{
		for (int i = 0; i < GameStatics.GetPlayer().GetCharacter().GetCharacterItem()
			.UpgradeableComponents[0].VariableValue; i++)
		{
			Upgrade(0);
		}
	}

	public void UnderhandUpgrade()
	{
		Upgrade(0);
		Upgrade(0);
		Upgrade(0);
	}

	public void LeftHandDowngrade()
	{
		for (int i = 0; i < GameStatics.GetPlayer().GetCharacter().GetCharacterItem()
			.UpgradeableComponents[0].VariableValue; i++)
		{
			Downgrade(0);
		}
	}

	public void UnderhandDowngrade()
	{
		Downgrade(0);
		Downgrade(0);
		Downgrade(0);
	}

	public void InvestMoneyInItem(int money)
	{
		MoneyInvested.Add(money);
	}

	public virtual int GetSellValue()
	{
		int num = 0;
		if (GameStatics.GetPlayer().GetUnpackedItemsOfType(typeof(Receipt)).Count > 0 && !(this is Receipt))
		{
			for (int i = 0; i < MoneyInvested.Count; i++)
			{
				num += MoneyInvested[i];
			}
			return Mathf.Max(0, num);
		}
		for (int j = 0; j < MoneyInvested.Count; j++)
		{
			num = ((j != 0) ? (num + MoneyInvested[j] / 4) : (num + MoneyInvested[j] / 2));
		}
		return Mathf.Max(0, num);
	}

	public int GetCost()
	{
		Player player = GameStatics.GetPlayer();
		bool flag = GetDescription().Contains("red", StringComparison.OrdinalIgnoreCase);
		int num = Mathf.Max(Cost - Discount, 0);
		List<Item> allItems = player.GetAllItems();
		Item item2 = allItems.Find((Item item) => item is RandomAccessMemory);
		Item item3 = allItems.Find((Item item) => item is Snapshot);
		List<Item> list = allItems.Where((Item item) => item is Frankenstein).ToList();
		if (item2 != null)
		{
			RandomAccessMemory randomAccessMemory = item2 as RandomAccessMemory;
			allItems.AddRange(randomAccessMemory.ItemsInMemory);
		}
		if (item3 != null)
		{
			Snapshot snapshot = item3 as Snapshot;
			if (snapshot.SnapshottedItem != null)
			{
				allItems.Add(snapshot.SnapshottedItem);
			}
		}
		foreach (Item item4 in list)
		{
			Frankenstein frankenstein = item4 as Frankenstein;
			allItems.AddRange(frankenstein.StitchedItems);
		}
		foreach (Item item5 in allItems)
		{
			if (item5 is Avocado)
			{
				num *= 2;
			}
			if (item5 is NorthernCardinal && flag)
			{
				num = Mathf.Max(0, num - 4);
			}
			if (item5 is BlessingOfTheShopkeeper)
			{
				num = 10;
			}
		}
		return Mathf.Max(0, num);
	}

	public static string CheckPlural(string pluralString, int pluralAmount)
	{
		if (pluralAmount != 1)
		{
			return pluralString;
		}
		return "";
	}

	public static string CheckPlural(string singularString, string pluralString, int pluralAmount)
	{
		if (pluralAmount != 1)
		{
			return pluralString;
		}
		return singularString;
	}

	public string CheckSingular(string singularString, int singularAmount)
	{
		if (singularAmount != 1)
		{
			return "";
		}
		return singularString;
	}

	public virtual AdviceData GetHighPriorityShopReccomendationAdvice(List<Item> playerItems, List<BuildData> builds)
	{
		return null;
	}

	public virtual AdviceData GetLowPriorityShopReccomendationAdvice(List<Item> playerItems, List<BuildData> builds)
	{
		return null;
	}

	public virtual void ApplyTileBonus(ScoreCalcVizInfo step, int index, List<Tile> tiles, List<TileSelection> selections, List<HistoricWord> previousWords, GridData gridData)
	{
	}

	public virtual void ApplyWordBonus(ScoreCalcVizInfo step, int gridNumber, List<Tile> tiles, List<string> words, List<TileSelection> selections, List<HistoricWord> previousWords, GridData gridData)
	{
	}

	public virtual ScoreCalcVizInfo ApplyItemToScore(List<ScoreCalcVizInfo> scoreCalcSteps, List<string> words, int gridNumber, List<TileSelection> tileSelections, List<HistoricWord> previousWords, GridData gridData)
	{
		List<Tile> list = tileSelections.Select((TileSelection tileSelection) => tileSelection.SelectedTile).ToList();
		ScoreCalcVizInfo nextStep = ScoreCalculation.GetNextStep(scoreCalcSteps);
		List<ScorePacket> list2 = new List<ScorePacket>(nextStep.TileScores);
		GetDescription();
		for (int i = 0; i < list.Count; i++)
		{
			ApplyTileBonus(nextStep, i, list, tileSelections, previousWords, gridData);
		}
		ApplyWordBonus(nextStep, gridNumber, list, words, tileSelections, previousWords, gridData);
		for (int j = 0; j < list2.Count; j++)
		{
			if (list2[j] != nextStep.TileScores[j])
			{
				nextStep.RelevantItem = this;
				break;
			}
		}
		if (nextStep.WordBonus != null)
		{
			nextStep.RelevantItem = this;
		}
		return nextStep;
	}

	public virtual void RandomiseRelevantColours()
	{
		Player player = GameStatics.GetPlayer();
		if (player.GetUnpackedItemsOfType(GetType()).Count > 0)
		{
			Item item = player.GetUnpackedItemsOfType(GetType(), forItemComparison: true)[0];
			if (item != null)
			{
				RelevantColours = new List<TileType>(item.RelevantColours);
			}
			return;
		}
		int count = RelevantColours.Count;
		RelevantColours.Clear();
		List<TileType> list = new List<TileType>
		{
			TileType.Red,
			TileType.Blue,
			TileType.Shiny,
			TileType.Void,
			TileType.Cactus,
			TileType.Pink,
			TileType.Gold,
			TileType.Green,
			TileType.Purple,
			TileType.White
		};
		for (int i = 0; i < count; i++)
		{
			int index = UnityEngine.Random.Range(0, list.Count);
			RelevantColours.Add(list[index]);
			list.RemoveAt(index);
		}
	}

	public virtual GridData ApplyStartOfGridEffect(GridData gridData, int gridNumber, int numberOfGrids, List<HistoricWord> previousWords, List<BoardGenVizInfo> vizSteps, bool isReroll)
	{
		return gridData;
	}

	public virtual GridData FinalStartOfGridEffect(GridData gridData, int gridNumber, int numberOfGrids, List<HistoricWord> previousWords, List<BoardGenVizInfo> vizSteps)
	{
		return gridData;
	}

	public virtual IEnumerator DoStartOfGridAnimation()
	{
		yield break;
	}

	public virtual void StartOfEncounterSetUp()
	{
	}

	public virtual void OnAcquire()
	{
	}

	public bool IsSticker()
	{
		return UpgradeableComponents.Count == 1;
	}

	public bool IsStamp()
	{
		return UpgradeableComponents.Count == 0;
	}

	public List<HistoricWord> GetSkipFilteredHistoricWords(List<HistoricWord> previousWords)
	{
		return previousWords.Where((HistoricWord prevWord) => !prevWord.IsWordSkipped).ToList();
	}

	public List<ItemTag> GetAllShopAdviceTags()
	{
		List<ItemTag> list = new List<ItemTag>(Tags);
		list.AddRange(ShopAdviceAdditionalTags);
		return list.ToList();
	}
}
