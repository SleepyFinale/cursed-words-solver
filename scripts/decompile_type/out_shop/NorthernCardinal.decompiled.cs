using System.Collections.Generic;
using UnityEngine;

public class NorthernCardinal : Item
{
	public NorthernCardinal()
	{
		Name = "Young Cardinal";
		SpriteData.Add(new ItemSpriteData(ItemSpriteUsage.Default, "NorthernCardinal"));
		Rarity = ItemRarity.Common;
		Cost = 8;
		Tags = new List<ItemTag> { ItemTag.RedBuild };
		IsAnimal = true;
		ItemFunctionTags = new List<ItemFunctionTag> { ItemFunctionTag.Tech };
	}

	public override string GetDescription()
	{
		return "Items with 'red' in their description cost $4 less";
	}

	public override void OnAcquire()
	{
		ShopController shopController = Object.FindFirstObjectByType<ShopController>();
		if (shopController != null)
		{
			shopController.RepopulateShopItems();
		}
	}

	public override AdviceData GetHighPriorityShopReccomendationAdvice(List<Item> playerItems, List<BuildData> builds)
	{
		Player player = GameStatics.GetPlayer();
		if (builds.Exists((BuildData build) => build.BuildTag == ItemTag.RedBuild))
		{
			AdviceData adviceData = new AdviceData(ItemTag.RedBuild, new List<Item> { this }, isGeneric: false, isUpgrade: false);
			if (player.Money >= GetCost())
			{
				adviceData.ShouldBuy = true;
				adviceData.SpecificUtilityRecommendationDialogue = "I'd suggest " + Name + " - it can be very helpful on a RED run!";
				adviceData.SpecificUtilityRecommendationEmotion = Emotions.ShopkeeperIdea;
				return adviceData;
			}
			adviceData.ShouldFreeze = true;
			adviceData.SpecificUtilityRecommendationDialogue = Name + " could be worth freezing if you're leaning RED?";
			adviceData.SpecificUtilityRecommendationEmotion = Emotions.ShopkeeperExplaining;
			return adviceData;
		}
		return null;
	}
}
