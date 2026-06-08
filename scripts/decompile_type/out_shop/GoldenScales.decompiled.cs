using System.Collections.Generic;

public class GoldenScales : Item
{
	public GoldenScales()
	{
		Name = "Golden Scales";
		SpriteData.Add(new ItemSpriteData(ItemSpriteUsage.Default, "GoldenScales"));
		Rarity = ItemRarity.Common;
		Cost = 10;
		Tags = new List<ItemTag>
		{
			ItemTag.CashBuild,
			ItemTag.CashGenerator
		};
		ItemFunctionTags = new List<ItemFunctionTag> { ItemFunctionTag.Tech };
	}

	public override string GetDescription()
	{
		return "START OF ENCOUNTER: Each empty Sticker slot gives $1";
	}

	public override GridData ApplyStartOfGridEffect(GridData gridData, int gridNumber, int numberOfGrids, List<HistoricWord> previousWords, List<BoardGenVizInfo> vizSteps, bool isReroll)
	{
		if (gridNumber != 1)
		{
			return gridData;
		}
		Player player = GameStatics.GetPlayer();
		int num = 5 - player.GetStickers(forItemComparison: true).Count;
		if (num > 0)
		{
			BoardGenVizInfo boardGenVizInfo = new BoardGenVizInfo(gridData, this, new List<Tile>(), isPulsingMoney: true, null, isPulsingGridNumber: false, basicGridGen: false, isPulsingPreviousWord: false, vizSteps[vizSteps.Count - 1].PlayerConsumableTiles);
			boardGenVizInfo.MoneyChange = num;
			boardGenVizInfo.EarningsBreakdown[Name] = num;
			vizSteps.Add(boardGenVizInfo);
		}
		return gridData;
	}

	public override AdviceData GetHighPriorityShopReccomendationAdvice(List<Item> playerItems, List<BuildData> builds)
	{
		Player player = GameStatics.GetPlayer();
		AdviceData adviceData = new AdviceData(ItemTag.NoBuild, new List<Item> { this }, isGeneric: true, isUpgrade: false);
		if (player.GetStickers(forItemComparison: true).Count <= 2)
		{
			if (player.Money >= GetCost())
			{
				adviceData.ShouldBuy = true;
				adviceData.SpecificUtilityRecommendationDialogue = "You could grab " + Name + " to make some cash off your empty Sticker slots!";
				adviceData.SpecificUtilityRecommendationEmotion = Emotions.ShopkeeperIdea;
				return adviceData;
			}
			adviceData.ShouldFreeze = true;
			adviceData.SpecificUtilityRecommendationDialogue = Name + " could be worth freezing? It can make you lots of money in the early game!";
			adviceData.SpecificUtilityRecommendationEmotion = Emotions.ShopkeeperExplaining;
			return adviceData;
		}
		return null;
	}
}
