using System.Collections.Generic;
using System.Linq;
using UnityEngine;

public class AdviceData
{
	public ItemTag Build;

	public List<Item> RecommendedItems = new List<Item>();

	public List<Tile> RecommendedTiles = new List<Tile>();

	public ItemFunction FunctionFulfilled;

	public bool ShouldFreeze;

	public bool ShouldBuy;

	public bool ShouldUpgrade;

	public bool ShouldRestock;

	public bool ShouldLeave;

	public bool IsFreeItem;

	public bool ShouldSell;

	public bool IsGeneric;

	public string SpecificUtilityRecommendationDialogue;

	public Emotions SpecificUtilityRecommendationEmotion;

	private int StringIndex;

	private int ItemIndex;

	public AdviceData(ItemTag build, List<Item> recommendedItems, bool isGeneric, bool isUpgrade, ItemFunction functionFulfilled = ItemFunction.Other)
	{
		Build = build;
		RecommendedItems = recommendedItems;
		IsGeneric = isGeneric;
		FunctionFulfilled = functionFulfilled;
	}

	public (string dialogue, Emotions emotion) GetQuip(int restockPrice, bool isFreeItem, int stringIndex, int itemIndex)
	{
		StringIndex = stringIndex;
		ItemIndex = itemIndex;
		Debug.Log(StringSerializer.Serialize(typeof(AdviceData), this));
		if (!string.IsNullOrEmpty(SpecificUtilityRecommendationDialogue))
		{
			return (dialogue: SpecificUtilityRecommendationDialogue, emotion: SpecificUtilityRecommendationEmotion);
		}
		if (RecommendedTiles.Count > 0)
		{
			(string, Emotions) result = ShopRecStrings.BuyTile[StringIndex % ShopRecStrings.BuyTile.Count];
			result.Item1 = result.Item1.Replace("[TILE DESCRIPTION]", GetTileString());
			return result;
		}
		Player player = GameStatics.GetPlayer();
		IsFreeItem = isFreeItem;
		if (RecommendedItems.Count > 0)
		{
			if (RecommendedItems.Exists((Item item) => item.GetCost() <= player.Money))
			{
				RecommendedItems = RecommendedItems.Where((Item item) => item.GetCost() <= player.Money).ToList();
				ShouldBuy = true;
			}
			else
			{
				ShouldFreeze = true;
			}
			if (player.GetStickers(forItemComparison: true).Count >= 5 && player.GetStamps(forItemComparison: true).Count >= 5)
			{
				ShouldSell = true;
			}
			else if (player.GetStickers(forItemComparison: true).Count >= 5)
			{
				if (RecommendedItems.Exists((Item item) => !item.IsSticker()))
				{
					RecommendedItems = RecommendedItems.Where((Item item) => !item.IsSticker()).ToList();
				}
				else
				{
					ShouldSell = true;
				}
			}
			else if (player.GetStamps(forItemComparison: true).Count >= 5)
			{
				if (RecommendedItems.Exists((Item item) => !item.IsStamp()))
				{
					RecommendedItems = RecommendedItems.Where((Item item) => !item.IsStamp()).ToList();
				}
				else
				{
					ShouldSell = true;
				}
			}
			if (RecommendedItems.Exists((Item item) => player.GetAllItems(forItemComparison: true).Exists((Item invItem) => invItem.GetType() == item.GetType())))
			{
				RecommendedItems = RecommendedItems.Where((Item item) => player.GetAllItems(forItemComparison: true).Exists((Item invItem) => invItem.GetType() == item.GetType())).ToList();
				ShouldUpgrade = true;
				ShouldSell = false;
			}
			(string, Emotions) result2 = ("", Emotions.MichaelConfused);
			if (ShouldUpgrade)
			{
				if (ShouldBuy)
				{
					result2 = ShopRecStrings.UpgradeAvailable[StringIndex % ShopRecStrings.UpgradeAvailable.Count];
				}
				if (ShouldFreeze)
				{
					result2 = ShopRecStrings.UpgradeAvailableFreeze[StringIndex % ShopRecStrings.UpgradeAvailableFreeze.Count];
				}
			}
			else if (ShouldSell)
			{
				result2 = ((!ShouldFreeze) ? ShopRecStrings.SellItem[StringIndex % ShopRecStrings.SellItem.Count] : ShopRecStrings.SellItemFreeze[StringIndex % ShopRecStrings.SellItemFreeze.Count]);
			}
			else if (IsFreeItem)
			{
				result2 = (IsGeneric ? ShopRecStrings.GenericFreeItem[StringIndex % ShopRecStrings.GenericFreeItem.Count] : ((RecommendedItems.Count > 1 && Build != 0) ? ShopRecStrings.FreeItem2BuildSpecific[StringIndex % ShopRecStrings.FreeItem2BuildSpecific.Count] : ((RecommendedItems.Count != 1 || Build == ItemTag.NoBuild) ? ShopRecStrings.FreeItemNoBuild[StringIndex % ShopRecStrings.FreeItemNoBuild.Count] : ShopRecStrings.FreeItemBuildSpecific[StringIndex % ShopRecStrings.FreeItemBuildSpecific.Count])));
			}
			else if (FunctionFulfilled == ItemFunction.Build)
			{
				result2 = (ShouldBuy ? ((RecommendedItems.Count <= 1) ? ShopRecStrings.AnyBuildItemDialogue1Available[StringIndex % ShopRecStrings.AnyBuildItemDialogue1Available.Count] : ShopRecStrings.AnyBuildItemDialogue2Available[StringIndex % ShopRecStrings.AnyBuildItemDialogue2Available.Count]) : ((RecommendedItems.Count <= 1) ? ShopRecStrings.AnyBuildItemDialogue1AvailableFreeze[StringIndex % ShopRecStrings.AnyBuildItemDialogue1AvailableFreeze.Count] : ShopRecStrings.AnyBuildItemDialogue2AvailableFreeze[StringIndex % ShopRecStrings.AnyBuildItemDialogue2AvailableFreeze.Count]));
			}
			else if (FunctionFulfilled == ItemFunction.Scoring)
			{
				result2 = ((!IsGeneric && Build != 0) ? (ShouldBuy ? ((RecommendedItems.Count <= 1) ? ShopRecStrings.AnyBuildScoringItemDialogue1Available[StringIndex % ShopRecStrings.AnyBuildScoringItemDialogue1Available.Count] : ShopRecStrings.AnyBuildScoringItemDialogue2Available[StringIndex % ShopRecStrings.AnyBuildScoringItemDialogue2Available.Count]) : ((RecommendedItems.Count <= 1) ? ShopRecStrings.AnyBuildScoringItemDialogue1AvailableFreeze[StringIndex % ShopRecStrings.AnyBuildScoringItemDialogue1AvailableFreeze.Count] : ShopRecStrings.AnyBuildScoringItemDialogue2AvailableFreeze[StringIndex % ShopRecStrings.AnyBuildScoringItemDialogue2AvailableFreeze.Count])) : (ShouldBuy ? ((RecommendedItems.Count <= 1) ? ShopRecStrings.AnyBuildScoringItemDialogue1Generic[StringIndex % ShopRecStrings.AnyBuildScoringItemDialogue1Generic.Count] : ShopRecStrings.AnyBuildScoringItemDialogue2Generic[StringIndex % ShopRecStrings.AnyBuildScoringItemDialogue2Generic.Count]) : ((RecommendedItems.Count <= 1) ? ShopRecStrings.AnyBuildScoringItemDialogue1GenericFreeze[StringIndex % ShopRecStrings.AnyBuildScoringItemDialogue1GenericFreeze.Count] : ShopRecStrings.AnyBuildScoringItemDialogue2GenericFreeze[StringIndex % ShopRecStrings.AnyBuildScoringItemDialogue2GenericFreeze.Count])));
			}
			else if (FunctionFulfilled == ItemFunction.Multiplier)
			{
				result2 = ((!IsGeneric && Build != 0) ? (ShouldBuy ? ((RecommendedItems.Count <= 1) ? ShopRecStrings.AnyBuildMultiplierItemDialogue1Available[StringIndex % ShopRecStrings.AnyBuildMultiplierItemDialogue1Available.Count] : ShopRecStrings.AnyBuildMultiplierItemDialogue2Available[StringIndex % ShopRecStrings.AnyBuildMultiplierItemDialogue2Available.Count]) : ((RecommendedItems.Count <= 1) ? ShopRecStrings.AnyBuildMultiplierItemDialogue1AvailableFreeze[StringIndex % ShopRecStrings.AnyBuildMultiplierItemDialogue1AvailableFreeze.Count] : ShopRecStrings.AnyBuildMultiplierItemDialogue2AvailableFreeze[StringIndex % ShopRecStrings.AnyBuildMultiplierItemDialogue2AvailableFreeze.Count])) : (ShouldBuy ? ((RecommendedItems.Count <= 1) ? ShopRecStrings.AnyBuildMultiplierItemDialogue1Generic[StringIndex % ShopRecStrings.AnyBuildMultiplierItemDialogue1Generic.Count] : ShopRecStrings.AnyBuildMultiplierItemDialogue2Generic[StringIndex % ShopRecStrings.AnyBuildMultiplierItemDialogue2Generic.Count]) : ((RecommendedItems.Count <= 1) ? ShopRecStrings.AnyBuildMultiplierItemDialogue1GenericFreeze[StringIndex % ShopRecStrings.AnyBuildMultiplierItemDialogue1GenericFreeze.Count] : ShopRecStrings.AnyBuildMultiplierItemDialogue2GenericFreeze[StringIndex % ShopRecStrings.AnyBuildMultiplierItemDialogue2GenericFreeze.Count])));
			}
			else if (FunctionFulfilled == ItemFunction.Additive)
			{
				result2 = ((!IsGeneric && Build != 0) ? (ShouldBuy ? ((RecommendedItems.Count <= 1) ? ShopRecStrings.AnyBuildAdditiveItemDialogue1Available[StringIndex % ShopRecStrings.AnyBuildAdditiveItemDialogue1Available.Count] : ShopRecStrings.AnyBuildAdditiveItemDialogue2Available[StringIndex % ShopRecStrings.AnyBuildAdditiveItemDialogue2Available.Count]) : ((RecommendedItems.Count <= 1) ? ShopRecStrings.AnyBuildAdditiveItemDialogue1AvailableFreeze[StringIndex % ShopRecStrings.AnyBuildAdditiveItemDialogue1AvailableFreeze.Count] : ShopRecStrings.AnyBuildAdditiveItemDialogue2AvailableFreeze[StringIndex % ShopRecStrings.AnyBuildAdditiveItemDialogue2AvailableFreeze.Count])) : (ShouldBuy ? ((RecommendedItems.Count <= 1) ? ShopRecStrings.AnyBuildAdditiveItemDialogue1Generic[StringIndex % ShopRecStrings.AnyBuildAdditiveItemDialogue1Generic.Count] : ShopRecStrings.AnyBuildAdditiveItemDialogue2Generic[StringIndex % ShopRecStrings.AnyBuildAdditiveItemDialogue2Generic.Count]) : ((RecommendedItems.Count <= 1) ? ShopRecStrings.AnyBuildAdditiveItemDialogue1GenericFreeze[StringIndex % ShopRecStrings.AnyBuildAdditiveItemDialogue1GenericFreeze.Count] : ShopRecStrings.AnyBuildAdditiveItemDialogue2GenericFreeze[StringIndex % ShopRecStrings.AnyBuildAdditiveItemDialogue2GenericFreeze.Count])));
			}
			else if (FunctionFulfilled == ItemFunction.Scatterer)
			{
				result2 = (ShouldBuy ? ((RecommendedItems.Count <= 1) ? ShopRecStrings.AnyBuildScatterItemDialogue1Available[StringIndex % ShopRecStrings.AnyBuildScatterItemDialogue1Available.Count] : ShopRecStrings.AnyBuildScatterItemDialogue2Available[StringIndex % ShopRecStrings.AnyBuildScatterItemDialogue2Available.Count]) : ((RecommendedItems.Count <= 1) ? ShopRecStrings.AnyBuildScatterItemDialogue1AvailableFreeze[StringIndex % ShopRecStrings.AnyBuildScatterItemDialogue1AvailableFreeze.Count] : ShopRecStrings.AnyBuildScatterItemDialogue2AvailableFreeze[StringIndex % ShopRecStrings.AnyBuildScatterItemDialogue2AvailableFreeze.Count]));
			}
			result2.Item1 = result2.Item1.Replace("[ITEM]", RecommendedItems[ItemIndex % RecommendedItems.Count].Name);
			result2.Item1 = result2.Item1.Replace("[ITEM1]", RecommendedItems[ItemIndex % RecommendedItems.Count].Name);
			result2.Item1 = result2.Item1.Replace("[ITEM2]", RecommendedItems[(ItemIndex + 1) % RecommendedItems.Count].Name);
			result2.Item1 = result2.Item1.Replace("[BUILD]", ShopRecommendation.BuildTagStrings[Build]);
			result2.Item1 = result2.Item1.Replace("[ITEM TYPE TO SELL]", RecommendedItems[ItemIndex % RecommendedItems.Count].IsSticker() ? "Sticker" : "Stamp");
			return result2;
		}
		if (ShopRecommendation.PlayerShouldRestock(player.Money, restockPrice) && !isFreeItem)
		{
			ShouldRestock = true;
			ShouldLeave = false;
		}
		else if (!isFreeItem)
		{
			ShouldRestock = false;
			ShouldLeave = true;
		}
		(string, Emotions) result3 = ("", Emotions.MichaelConfused);
		if (IsFreeItem)
		{
			result3 = ((Build != 0) ? ShopRecStrings.FreeItemNoBuildItems[StringIndex % ShopRecStrings.FreeItemNoBuildItems.Count] : ShopRecStrings.FreeItemNoBuild[StringIndex % ShopRecStrings.FreeItemNoBuild.Count]);
		}
		else if (Build == ItemTag.NoBuild)
		{
			result3 = ShopRecStrings.NoBuildTags[StringIndex % ShopRecStrings.NoBuildTags.Count];
		}
		else if (FunctionFulfilled == ItemFunction.Build)
		{
			result3 = ((!ShouldRestock) ? ShopRecStrings.AnySingleBuildItemNoneAvailableLeave[StringIndex % ShopRecStrings.AnySingleBuildItemNoneAvailableLeave.Count] : ShopRecStrings.AnySingleBuildItemNoneAvailableRestock[StringIndex % ShopRecStrings.AnySingleBuildItemNoneAvailableRestock.Count]);
		}
		else if (FunctionFulfilled == ItemFunction.Scoring)
		{
			result3 = ((!ShouldRestock) ? ShopRecStrings.AnyBuildScoringItemDialogueNoneLeave[StringIndex % ShopRecStrings.AnyBuildScoringItemDialogueNoneLeave.Count] : ShopRecStrings.AnyBuildScoringItemDialogueNoneRestock[StringIndex % ShopRecStrings.AnyBuildScoringItemDialogueNoneRestock.Count]);
		}
		else if (FunctionFulfilled == ItemFunction.Additive)
		{
			result3 = ((!ShouldRestock) ? ShopRecStrings.AnyBuildAdditiveItemDialogueNoneLeave[StringIndex % ShopRecStrings.AnyBuildAdditiveItemDialogueNoneLeave.Count] : ShopRecStrings.AnyBuildAdditiveItemDialogueNoneRestock[StringIndex % ShopRecStrings.AnyBuildAdditiveItemDialogueNoneRestock.Count]);
		}
		else if (FunctionFulfilled == ItemFunction.Multiplier)
		{
			result3 = ((!ShouldRestock) ? ShopRecStrings.AnyBuildMultiplierItemDialogueNoneLeave[StringIndex % ShopRecStrings.AnyBuildMultiplierItemDialogueNoneLeave.Count] : ShopRecStrings.AnyBuildMultiplierItemDialogueNoneRestock[StringIndex % ShopRecStrings.AnyBuildMultiplierItemDialogueNoneRestock.Count]);
		}
		else if (FunctionFulfilled == ItemFunction.Scatterer)
		{
			result3 = ((!ShouldRestock) ? ShopRecStrings.AnyBuildScatterItemDialogueNoneLeave[StringIndex % ShopRecStrings.AnyBuildScatterItemDialogueNoneLeave.Count] : ShopRecStrings.AnyBuildScatterItemDialogueNoneRestock[StringIndex % ShopRecStrings.AnyBuildScatterItemDialogueNoneRestock.Count]);
		}
		result3.Item1 = result3.Item1.Replace("[BUILD]", ShopRecommendation.BuildTagStrings[Build]);
		return result3;
	}

	public string GetTileString()
	{
		Tile tile = RecommendedTiles[Random.Range(0, RecommendedTiles.Count)];
		string text = ((tile.GetGlyphType() == GlyphType.Letter) ? tile.GetStringRepresentation().ToUpper() : tile.GetStringRepresentation());
		if (tile.GetTileType() != 0)
		{
			return ShopRecommendation.TileColourStrings[tile.GetTileType()] + " " + text;
		}
		return text;
	}
}
