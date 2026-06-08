using System.Collections.Generic;
using System.Linq;
using UnityEngine;

public static class ShopRecommendation
{
	public static int StringIndex = 0;

	public static int ItemIndex = 0;

	public static int AdviceIndex = 0;

	public static Dictionary<ItemTag, string> BuildTagStrings = new Dictionary<ItemTag, string>
	{
		{
			ItemTag.BlueBuild,
			"BLUE"
		},
		{
			ItemTag.RedBuild,
			"RED"
		},
		{
			ItemTag.VoidBuild,
			"VOID"
		},
		{
			ItemTag.ShinyBuild,
			"SHINY"
		},
		{
			ItemTag.ChessBuild,
			"CHESS"
		},
		{
			ItemTag.BlankBuild,
			"?"
		},
		{
			ItemTag.ColourlessBuild,
			"COLOURLESS"
		},
		{
			ItemTag.CashBuild,
			"MONEY"
		},
		{
			ItemTag.RainbowBuild,
			"RAINBOW"
		},
		{
			ItemTag.ConsumableBuild,
			"CONSUMABLE"
		},
		{
			ItemTag.CurseBuild,
			"CURSE"
		},
		{
			ItemTag.NumbersBuild,
			"NUMBERS"
		},
		{
			ItemTag.ArrowBuild,
			"ARROWS"
		},
		{
			ItemTag.CardsBuild,
			"CARDS"
		},
		{
			ItemTag.BigNumbersBuild,
			"BIG NUMBERS"
		},
		{
			ItemTag.ScatteredItemsBuild,
			"ITEMS"
		},
		{
			ItemTag.NoBuild,
			"NO BUILD!!!"
		}
	};

	public static Dictionary<ItemFunction, List<ItemFunctionTag>> MapFunctionsToFunctionTags = new Dictionary<ItemFunction, List<ItemFunctionTag>>
	{
		{
			ItemFunction.Scoring,
			new List<ItemFunctionTag>
			{
				ItemFunctionTag.GenericAdditive,
				ItemFunctionTag.SpecificAdditive,
				ItemFunctionTag.GenericMultiplier,
				ItemFunctionTag.SpecificMultiplier
			}
		},
		{
			ItemFunction.Additive,
			new List<ItemFunctionTag>
			{
				ItemFunctionTag.GenericAdditive,
				ItemFunctionTag.SpecificAdditive
			}
		},
		{
			ItemFunction.Multiplier,
			new List<ItemFunctionTag>
			{
				ItemFunctionTag.GenericMultiplier,
				ItemFunctionTag.SpecificMultiplier
			}
		},
		{
			ItemFunction.Scatterer,
			new List<ItemFunctionTag> { ItemFunctionTag.Scatterer }
		},
		{
			ItemFunction.Other,
			new List<ItemFunctionTag> { ItemFunctionTag.Tech }
		},
		{
			ItemFunction.Build,
			new List<ItemFunctionTag>
			{
				ItemFunctionTag.GenericAdditive,
				ItemFunctionTag.SpecificAdditive,
				ItemFunctionTag.GenericMultiplier,
				ItemFunctionTag.SpecificMultiplier,
				ItemFunctionTag.Tech,
				ItemFunctionTag.Scatterer
			}
		}
	};

	public static List<string> NeedFulfilledStrings = new List<string> { "Looks like you could do with a[BUILD][FUNCTION]...", "Hmmm... if I were you I'd be looking for a [BUILD][FUNCTION].", "I think a [BUILD][FUNCTION] would help you out!", "A [BUILD][FUNCTION] would take your build to the next level!", "Looking for a [BUILD][FUNCTION]?" };

	public static List<string> AvailableActionStrings = new List<string> { "What about [BUYING/FREEZING/UPGRADING] [ITEM OR ITEM]?", "Have you considered [BUYING/FREEZING/UPGRADING] [ITEM OR ITEM][FREEZE?]?", "[ITEM OR ITEM] would hit the spot - you should [BUY/FREEZE/UPGRADE] it!", "[ITEM OR ITEM] could help you out!" };

	public static string NeedFulfilledString = "You could do with a[BUILD][FUNCTION]/[IF WILLING TO SELL] ";

	public static string AvailableActionString = "You should [BUY/FREEZE/UPGRADE] [ITEM AND ITEM]";

	public static string GenericActionString = "You could [BUY/FREEZE/UPGRADE] [ITEM OR ITEM] if they will work in your build";

	public static string NeedUnfulfilledString = "Shame there aren't any [BUILD] [FUNCTION]s";

	public static string NotAvailableActionString = "You should [RESTOCK/LEAVE/TAKE]";

	public static Dictionary<ItemFunction, List<string>> ItemFunctionStrings = new Dictionary<ItemFunction, List<string>>
	{
		{
			ItemFunction.Build,
			new List<string> { "item" }
		},
		{
			ItemFunction.Scoring,
			new List<string> { "scoring item", "score booster", "scorer" }
		},
		{
			ItemFunction.Additive,
			new List<string> { "additive item", "additive scorer" }
		},
		{
			ItemFunction.Multiplier,
			new List<string> { "multiplier", "score multiplier" }
		},
		{
			ItemFunction.Scatterer,
			new List<string> { "tile scatterer", "scattering item" }
		},
		{
			ItemFunction.Other,
			new List<string> { "item" }
		},
		{
			ItemFunction.Tile,
			new List<string> { "tile", "consumable tile" }
		}
	};

	public static Dictionary<TileType, string> TileColourStrings = new Dictionary<TileType, string>
	{
		{
			TileType.Red,
			"red"
		},
		{
			TileType.Blue,
			"blue"
		},
		{
			TileType.Void,
			"void"
		},
		{
			TileType.Shiny,
			"shiny"
		},
		{
			TileType.Normal,
			"colourless"
		},
		{
			TileType.Cactus,
			"cactus"
		},
		{
			TileType.Purple,
			"purple"
		},
		{
			TileType.Gold,
			"gold"
		},
		{
			TileType.White,
			"white"
		},
		{
			TileType.Pink,
			"pink"
		},
		{
			TileType.Green,
			"green"
		},
		{
			TileType.Glitch,
			"glitch"
		}
	};

	public static List<ItemTag> GetBuildSynergyTags()
	{
		List<ItemTag> list = new List<ItemTag>
		{
			ItemTag.BlueBuild,
			ItemTag.RedBuild,
			ItemTag.VoidBuild,
			ItemTag.ShinyBuild,
			ItemTag.BlankBuild,
			ItemTag.ColourlessBuild,
			ItemTag.RainbowBuild,
			ItemTag.ConsumableBuild,
			ItemTag.NoBuild,
			ItemTag.CashBuild,
			ItemTag.ScatteredItemsBuild
		};
		if (SaveManager.IsBulkUnlockUnlocked(typeof(NumbersUnlock)))
		{
			list.Add(ItemTag.NumbersBuild);
			list.Add(ItemTag.BigNumbersBuild);
		}
		if (SaveManager.IsBulkUnlockUnlocked(typeof(ChessUnlock)))
		{
			list.Add(ItemTag.ChessBuild);
		}
		if (SaveManager.IsBulkUnlockUnlocked(typeof(CardsUnlock)))
		{
			list.Add(ItemTag.CardsBuild);
		}
		if (SaveManager.IsBulkUnlockUnlocked(typeof(CursedUnlock)))
		{
			list.Add(ItemTag.CurseBuild);
		}
		return list;
	}

	public static (string Text, Emotions Emotion) GetShopRecommendation(List<Item> playerInventory, List<Item> itemsAvailableInStock, List<TileInStock> tilesInStock, int restockPrice, bool freeItemAvailable)
	{
		Debug.Log("Current Pin Tags:");
		Debug.Log(StringSerializer.Serialize(tilesInStock.GetType(), tilesInStock));
		foreach (ItemTag tag in GameStatics.GetPlayer().MyCharacter.GetCharacterItem().Tags)
		{
			Debug.Log(tag);
		}
		foreach (ItemFunctionTag itemFunctionTag in GameStatics.GetPlayer().MyCharacter.GetCharacterItem().ItemFunctionTags)
		{
			Debug.Log(itemFunctionTag);
		}
		(string, Emotions) result = ("", Emotions.MichaelThinking);
		if (StringIndex == 0)
		{
			StringIndex = Random.Range(0, 6);
		}
		if (ItemIndex == 0)
		{
			ItemIndex = Random.Range(0, 2);
		}
		if (AdviceIndex == 0)
		{
			AdviceIndex = Random.Range(0, 3);
		}
		itemsAvailableInStock = itemsAvailableInStock.Where((Item item) => !item.IsBlacklistedFromShopRecommendations).ToList();
		StringIndex++;
		ItemIndex++;
		AdviceIndex++;
		List<BuildData> builds = (from tag in GetMostCommonBuilds(playerInventory)
			select GetBuildDataForBuild(tag)).ToList();
		List<AdviceData> list = BaselineBuildFunctionsAdviceData(builds, itemsAvailableInStock, freeItemAvailable);
		List<AdviceData> list2 = BuildUpgradesAdviceData(builds, itemsAvailableInStock);
		List<AdviceData> list3 = HighPriorityUtilityAdviceData(builds, itemsAvailableInStock, playerInventory);
		if (!list.Exists((AdviceData ad) => ad.RecommendedItems.Count > 0) && (list2.Exists((AdviceData ad) => ad.RecommendedItems.Count > 0) || list3.Exists((AdviceData ad) => ad.RecommendedItems.Count > 0)))
		{
			Debug.Log("Clearing baseline advice as higher priority advice exists");
			list.Clear();
		}
		List<AdviceData> item2 = BuildFunctionsAdviceToLevel(builds, itemsAvailableInStock, 2, isForcingRecommendation: false);
		List<AdviceData> item3 = LowPriorityUtilityAdviceData(builds, itemsAvailableInStock, playerInventory).Concat(GetTileAdviceData(builds, tilesInStock)).ToList();
		List<AdviceData> item4 = BuildFunctionsAdviceToLevel(builds, itemsAvailableInStock, 10, isForcingRecommendation: true);
		List<AdviceData> item5 = new List<AdviceData>
		{
			new AdviceData(ItemTag.NoBuild, new List<Item>(), isGeneric: false, isUpgrade: false)
		};
		foreach (List<AdviceData> item6 in new List<List<AdviceData>> { list, list2, list3, item2, item3, item4, item5 })
		{
			if (item6.Count > 0)
			{
				return item6[AdviceIndex % item6.Count].GetQuip(restockPrice, freeItemAvailable, StringIndex, ItemIndex);
			}
		}
		return result;
	}

	public static (string Text, Emotions Emotion) GetMegShopRecommendation(List<Item> playerInventory, List<Item> itemsAvailableInStock)
	{
		AdviceIndex++;
		List<(string, Emotions)> list = new List<(string, Emotions)>
		{
			("A classic nouveau riche upstart - all the cash, none of the class.", Emotions.DinosaurAngry),
			("You're asking for advice from the person you're gearing up to fight? Honestly... am I surrounded by idiots?", Emotions.DinosaurPowerful),
			("Free advice? I don't think so! People would pay a lot of money to hear my investment strategies.", Emotions.DinosaurCharacter)
		};
		return list[AdviceIndex % list.Count];
	}

	public static bool ItemFulfillsFunction(Item item, ItemFunction function)
	{
		return MapFunctionsToFunctionTags[function].Exists((ItemFunctionTag functionTag) => item.ItemFunctionTags.Contains(functionTag));
	}

	public static List<Item> GetItemsFulfillingFunctionForBuild(List<Item> shopItems, ItemTag build, ItemFunction function)
	{
		List<Item> list = new List<Item>();
		foreach (Item shopItem in shopItems)
		{
			if (shopItem.GetAllShopAdviceTags().Contains(build) && ItemFulfillsFunction(shopItem, function))
			{
				list.Add(shopItem);
			}
		}
		return list;
	}

	public static Dictionary<ItemFunction, List<Item>> GetItemsFulfillingFunctionsForBuild(List<Item> shopItems, ItemTag build, List<ItemFunction> functions)
	{
		Dictionary<ItemFunction, List<Item>> dictionary = new Dictionary<ItemFunction, List<Item>>();
		foreach (ItemFunction function in functions)
		{
			dictionary[function] = GetItemsFulfillingFunctionForBuild(shopItems, build, function);
		}
		return dictionary;
	}

	public static List<Item> GetNonScatterItemsForBuild(List<Item> shopItems, ItemTag build)
	{
		List<Item> list = new List<Item>();
		foreach (Item shopItem in shopItems)
		{
			if (shopItem.GetAllShopAdviceTags().Contains(build) && ItemFulfillsFunction(shopItem, ItemFunction.Build) && !shopItem.ItemFunctionTags.Exists((ItemFunctionTag ft) => ft == ItemFunctionTag.Scatterer))
			{
				list.Add(shopItem);
			}
		}
		return list;
	}

	public static List<Item> GetGenericItemsFulfillingFunction(List<Item> shopItems, ItemFunction function)
	{
		List<Item> list = new List<Item>();
		if (function == ItemFunction.Additive || function == ItemFunction.Scoring)
		{
			list.AddRange(shopItems.Where((Item item) => item.ItemFunctionTags.Contains(ItemFunctionTag.GenericAdditive)));
		}
		if (function == ItemFunction.Multiplier || function == ItemFunction.Scoring)
		{
			list.AddRange(shopItems.Where((Item item) => item.ItemFunctionTags.Contains(ItemFunctionTag.GenericMultiplier)));
		}
		return list;
	}

	public static List<AdviceData> BaselineBuildFunctionsAdviceData(List<BuildData> builds, List<Item> shopItems, bool isFreeItem)
	{
		List<ItemFunction> list = new List<ItemFunction>
		{
			ItemFunction.Scatterer,
			ItemFunction.Scoring,
			ItemFunction.Additive,
			ItemFunction.Multiplier
		};
		List<AdviceData> list2 = new List<AdviceData>();
		foreach (BuildData build in builds)
		{
			foreach (ItemFunction item in list)
			{
				if (build.FunctionTagCounts[item] != 0)
				{
					continue;
				}
				Debug.Log($"Looking for baseline {item} for {build.BuildTag}");
				List<Item> itemsFulfillingFunctionForBuild = GetItemsFulfillingFunctionForBuild(shopItems, build.BuildTag, item);
				if (itemsFulfillingFunctionForBuild.Count > 0)
				{
					Debug.Log($"Found {itemsFulfillingFunctionForBuild.Count} items for {item} in {build.BuildTag}. First item is {itemsFulfillingFunctionForBuild[0].Name}");
					list2.Add(new AdviceData(build.BuildTag, itemsFulfillingFunctionForBuild, isGeneric: false, isUpgrade: false, item));
					break;
				}
				itemsFulfillingFunctionForBuild.AddRange(GetGenericItemsFulfillingFunction(shopItems, item));
				if (itemsFulfillingFunctionForBuild.Count > 0)
				{
					list2.Add(new AdviceData((!isFreeItem) ? build.BuildTag : ItemTag.NoBuild, itemsFulfillingFunctionForBuild, itemsFulfillingFunctionForBuild.Count > 0, isUpgrade: false, item));
				}
				else if (isFreeItem)
				{
					Debug.Log("IS FREE ITEM: looking for any build item");
					itemsFulfillingFunctionForBuild.AddRange(GetItemsFulfillingFunctionForBuild(shopItems, build.BuildTag, ItemFunction.Build));
					list2.Add(new AdviceData((itemsFulfillingFunctionForBuild.Count != 0) ? build.BuildTag : ItemTag.NoBuild, itemsFulfillingFunctionForBuild, isGeneric: false, isUpgrade: false, ItemFunction.Build));
				}
				else
				{
					list2.Add(new AdviceData(build.BuildTag, new List<Item>(), isGeneric: false, isUpgrade: false, item));
				}
				break;
			}
		}
		if (list2.Exists((AdviceData advice) => advice.RecommendedItems.Count > 0))
		{
			list2 = list2.Where((AdviceData advice) => advice.RecommendedItems.Count > 0).ToList();
		}
		if (list2.Exists((AdviceData advice) => !advice.IsGeneric))
		{
			list2 = list2.Where((AdviceData advice) => !advice.IsGeneric).ToList();
		}
		if (list2.Exists((AdviceData advice) => advice.RecommendedItems.Exists((Item item) => GameStatics.GetPlayer().GetAllItems(forItemComparison: true).Exists((Item invItem) => invItem.GetType() == item.GetType()))))
		{
			list2 = list2.Where((AdviceData advice) => advice.RecommendedItems.Exists((Item item) => GameStatics.GetPlayer().GetAllItems(forItemComparison: true).Exists((Item invItem) => invItem.GetType() == item.GetType()))).ToList();
			foreach (AdviceData item2 in list2)
			{
				item2.RecommendedItems = item2.RecommendedItems.Where((Item item) => GameStatics.GetPlayer().GetAllItems(forItemComparison: true).Exists((Item invItem) => invItem.GetType() == item.GetType())).ToList();
				item2.ShouldUpgrade = true;
			}
		}
		return list2;
	}

	public static List<AdviceData> BuildFunctionsAdviceToLevel(List<BuildData> builds, List<Item> shopItems, int level, bool isForcingRecommendation)
	{
		List<ItemFunction> list = new List<ItemFunction>
		{
			ItemFunction.Additive,
			ItemFunction.Multiplier,
			ItemFunction.Scatterer
		};
		List<AdviceData> list2 = new List<AdviceData>();
		foreach (BuildData build in builds)
		{
			for (int i = 1; i <= level; i++)
			{
				Debug.Log($"Checking Build Functions at i = {i}");
				int num = Mathf.Min(i, 2);
				if (build.FunctionTagCounts[ItemFunction.Scatterer] <= num && build.FunctionTagCounts[ItemFunction.Scatterer] == build.FunctionTagCounts[ItemFunction.Additive] && build.FunctionTagCounts[ItemFunction.Multiplier] == build.FunctionTagCounts[ItemFunction.Additive])
				{
					List<Item> itemsFulfillingFunctionForBuild = GetItemsFulfillingFunctionForBuild(shopItems, build.BuildTag, ItemFunction.Build);
					Debug.Log("All functions equal and less than max scatter count, recommending: " + string.Join(", ", itemsFulfillingFunctionForBuild.Select((Item item) => item.Name)));
					if (itemsFulfillingFunctionForBuild.Count > 0)
					{
						list2.Add(new AdviceData(build.BuildTag, itemsFulfillingFunctionForBuild, isGeneric: false, isUpgrade: false, ItemFunction.Build));
						break;
					}
				}
				if (build.FunctionTagCounts[ItemFunction.Scatterer] > num && build.FunctionTagCounts[ItemFunction.Additive] >= 2 && build.FunctionTagCounts[ItemFunction.Multiplier] >= 2 && i > 2)
				{
					List<Item> nonScatterItemsForBuild = GetNonScatterItemsForBuild(shopItems, build.BuildTag);
					Debug.Log("Max scatter items owned, lots of scorers owned and i > 2. Recommeding: " + string.Join(", ", nonScatterItemsForBuild.Select((Item item) => item.Name)));
					if (nonScatterItemsForBuild.Count > 0)
					{
						list2.Add(new AdviceData(build.BuildTag, nonScatterItemsForBuild, isGeneric: false, isUpgrade: false, ItemFunction.Build));
						break;
					}
				}
				List<ItemFunction> list3 = new List<ItemFunction>();
				Debug.Log("Getting unfulfilled functions");
				foreach (ItemFunction item in list)
				{
					if (build.FunctionTagCounts[item] < i && (item != ItemFunction.Scatterer || i <= 2))
					{
						list3.Add(item);
						Debug.Log($"{item} is unfulfilled");
					}
				}
				Dictionary<ItemFunction, List<Item>> itemsFulfillingFunctionsForBuild = GetItemsFulfillingFunctionsForBuild(shopItems, build.BuildTag, list3);
				if (itemsFulfillingFunctionsForBuild.Count > 0)
				{
					bool flag = false;
					foreach (KeyValuePair<ItemFunction, List<Item>> item2 in itemsFulfillingFunctionsForBuild)
					{
						if (item2.Value.Count > 0)
						{
							Debug.Log(string.Format("Found items for {0}, recommending: {1}", item2.Key, string.Join(", ", item2.Value.Select((Item item) => item.Name))));
							list2.Add(new AdviceData(build.BuildTag, item2.Value, isGeneric: false, isUpgrade: false, item2.Key));
							flag = true;
						}
					}
					if (flag)
					{
						break;
					}
				}
				foreach (ItemFunction item3 in list3)
				{
					List<Item> genericItemsFulfillingFunction = GetGenericItemsFulfillingFunction(shopItems, item3);
					Debug.Log(string.Format("Finding generic items for {0}: {1}", item3, string.Join(", ", genericItemsFulfillingFunction.Select((Item item) => item.Name))));
					if (genericItemsFulfillingFunction.Count > 0)
					{
						list2.Add(new AdviceData(build.BuildTag, genericItemsFulfillingFunction, isGeneric: true, isUpgrade: false, item3));
						break;
					}
					if (build.FunctionTagCounts[ItemFunction.Other] <= 2)
					{
						List<Item> itemsFulfillingFunctionForBuild2 = GetItemsFulfillingFunctionForBuild(shopItems, build.BuildTag, ItemFunction.Other);
						Debug.Log("Trying to recommend utility: " + string.Join(", ", itemsFulfillingFunctionForBuild2.Select((Item item) => item.Name)));
						if (itemsFulfillingFunctionForBuild2.Count > 0)
						{
							list2.Add(new AdviceData(build.BuildTag, itemsFulfillingFunctionForBuild2, isGeneric: false, isUpgrade: false, ItemFunction.Build));
							break;
						}
					}
				}
			}
			if (!isForcingRecommendation)
			{
				continue;
			}
			List<ItemFunction> list4 = new List<ItemFunction>();
			int num2 = 9999;
			foreach (KeyValuePair<ItemFunction, int> functionTagCount in build.FunctionTagCounts)
			{
				if ((functionTagCount.Key != ItemFunction.Scatterer || functionTagCount.Value < 3) && list.Contains(functionTagCount.Key))
				{
					if (functionTagCount.Value < num2)
					{
						list4.Clear();
						list4.Add(functionTagCount.Key);
						num2 = functionTagCount.Value;
					}
					else if (functionTagCount.Value == num2)
					{
						list4.Add(functionTagCount.Key);
					}
				}
			}
			foreach (ItemFunction item4 in list4)
			{
				Debug.Log($"{item4} is a least common function");
			}
			if (list4.Count == 1)
			{
				list2.Add(new AdviceData(build.BuildTag, new List<Item>(), isGeneric: false, isUpgrade: false, list4[0]));
			}
			else if (list4.Count == 3)
			{
				list2.Add(new AdviceData(build.BuildTag, new List<Item>(), isGeneric: false, isUpgrade: false, ItemFunction.Build));
			}
			else if (list4.Contains(ItemFunction.Additive) && list4.Contains(ItemFunction.Multiplier))
			{
				list2.Add(new AdviceData(build.BuildTag, new List<Item>(), isGeneric: false, isUpgrade: false, ItemFunction.Scoring));
			}
			else
			{
				list2.Add(new AdviceData(build.BuildTag, new List<Item>(), isGeneric: false, isUpgrade: false, list4[Random.Range(0, 2)]));
			}
		}
		if (list2.Exists((AdviceData advice) => advice.RecommendedItems.Count > 0))
		{
			list2 = list2.Where((AdviceData advice) => advice.RecommendedItems.Count > 0).ToList();
		}
		if (list2.Exists((AdviceData advice) => !advice.IsGeneric))
		{
			list2 = list2.Where((AdviceData advice) => !advice.IsGeneric).ToList();
		}
		if (list2.Exists((AdviceData advice) => advice.RecommendedItems.Exists((Item item) => GameStatics.GetPlayer().GetAllItems(forItemComparison: true).Exists((Item invItem) => invItem.GetType() == item.GetType()))))
		{
			list2 = list2.Where((AdviceData advice) => advice.RecommendedItems.Exists((Item item) => GameStatics.GetPlayer().GetAllItems(forItemComparison: true).Exists((Item invItem) => invItem.GetType() == item.GetType()))).ToList();
			foreach (AdviceData item5 in list2)
			{
				item5.RecommendedItems = item5.RecommendedItems.Where((Item item) => GameStatics.GetPlayer().GetAllItems(forItemComparison: true).Exists((Item invItem) => invItem.GetType() == item.GetType())).ToList();
				item5.ShouldUpgrade = true;
			}
		}
		return list2;
	}

	public static List<AdviceData> BuildUpgradesAdviceData(List<BuildData> builds, List<Item> shopItems)
	{
		List<AdviceData> list = new List<AdviceData>();
		foreach (BuildData build in builds)
		{
			List<Item> list2 = new List<Item>();
			foreach (Item shopItem in shopItems)
			{
				if (build.RelevantItems.Exists((Item buildItem) => buildItem.GetType() == shopItem.GetType()))
				{
					list2.Add(shopItem);
				}
			}
			if (list2.Count > 0)
			{
				list.Add(new AdviceData(build.BuildTag, list2, isGeneric: false, isUpgrade: true));
			}
		}
		return list;
	}

	public static List<AdviceData> HighPriorityUtilityAdviceData(List<BuildData> builds, List<Item> shopItems, List<Item> playerInventory)
	{
		List<AdviceData> list = new List<AdviceData>();
		foreach (Item shopItem in shopItems)
		{
			AdviceData highPriorityShopReccomendationAdvice = shopItem.GetHighPriorityShopReccomendationAdvice(playerInventory, builds);
			if (highPriorityShopReccomendationAdvice != null)
			{
				list.Add(highPriorityShopReccomendationAdvice);
			}
		}
		return list;
	}

	public static List<AdviceData> LowPriorityUtilityAdviceData(List<BuildData> builds, List<Item> shopItems, List<Item> playerInventory)
	{
		List<AdviceData> list = new List<AdviceData>();
		foreach (Item shopItem in shopItems)
		{
			AdviceData lowPriorityShopReccomendationAdvice = shopItem.GetLowPriorityShopReccomendationAdvice(playerInventory, builds);
			if (lowPriorityShopReccomendationAdvice != null)
			{
				list.Add(lowPriorityShopReccomendationAdvice);
			}
		}
		return list;
	}

	public static List<Tile> AffordableBuildRelevantTiles(BuildData build, List<TileInStock> shopTiles)
	{
		List<Tile> list = new List<Tile>();
		Player player = GameStatics.GetPlayer();
		if (player.GetTiles().Count >= 5)
		{
			return list;
		}
		foreach (TileInStock shopTile in shopTiles)
		{
			if (shopTile.GetPrice() <= player.Money && ((build.BuildTag == ItemTag.BlueBuild && shopTile.MyTile.IsTileType(TileType.Blue)) || (build.BuildTag == ItemTag.RedBuild && shopTile.MyTile.IsTileType(TileType.Red)) || (build.BuildTag == ItemTag.VoidBuild && shopTile.MyTile.IsTileType(TileType.Void)) || (build.BuildTag == ItemTag.ShinyBuild && shopTile.MyTile.IsTileType(TileType.Shiny)) || (build.BuildTag == ItemTag.RainbowBuild && shopTile.MyTile.IsTileType(TileType.Shiny)) || (build.BuildTag == ItemTag.RainbowBuild && shopTile.MyTile.IsTileType(TileType.Normal)) || (build.BuildTag == ItemTag.ChessBuild && shopTile.MyTile.GetGlyphType() == GlyphType.Chess) || (build.BuildTag == ItemTag.BlankBuild && shopTile.MyTile.GetGlyphType() == GlyphType.Blank) || (build.BuildTag == ItemTag.CashBuild && shopTile.MyTile.GetGlyphType() == GlyphType.Currency) || (build.BuildTag == ItemTag.NumbersBuild && (shopTile.MyTile.GetGlyphType() == GlyphType.Number || shopTile.MyTile.GetGlyphType() == GlyphType.Fraction)) || (build.BuildTag == ItemTag.ArrowBuild && shopTile.MyTile.GetGlyphType() == GlyphType.Arrow) || (build.BuildTag == ItemTag.ScatteredItemsBuild && shopTile.MyTile.GetGlyphType() == GlyphType.ScatteredItem) || (build.BuildTag == ItemTag.CurseBuild && shopTile.MyTile.IsCursed()) || (build.BuildTag == ItemTag.CardsBuild && (shopTile.MyTile.CardSuit != 0 || shopTile.MyTile.GetGlyphType() == GlyphType.BespokeCard)) || build.BuildTag == ItemTag.ConsumableBuild))
			{
				list.Add(shopTile.MyTile);
			}
		}
		return list;
	}

	public static List<AdviceData> GetTileAdviceData(List<BuildData> builds, List<TileInStock> shopTiles)
	{
		List<AdviceData> list = new List<AdviceData>();
		foreach (BuildData build in builds)
		{
			List<Tile> list2 = AffordableBuildRelevantTiles(build, shopTiles);
			if (list2.Count > 0)
			{
				AdviceData adviceData = new AdviceData(build.BuildTag, new List<Item>(), isGeneric: false, isUpgrade: false, ItemFunction.Tile);
				adviceData.RecommendedTiles = list2;
				adviceData.ShouldBuy = true;
				list.Add(adviceData);
			}
		}
		return list;
	}

	public static bool PlayerShouldRestock(int playerMoney, int restockPrice)
	{
		if (playerMoney < restockPrice)
		{
			return false;
		}
		if (restockPrice <= 2)
		{
			return true;
		}
		if (restockPrice >= 6)
		{
			return false;
		}
		if (playerMoney / 2 > restockPrice)
		{
			return true;
		}
		return false;
	}

	public static Dictionary<ItemFunction, int> GetFunctionTagCounts(List<Item> inventory)
	{
		Dictionary<ItemFunction, int> dictionary = new Dictionary<ItemFunction, int>
		{
			{
				ItemFunction.Multiplier,
				0
			},
			{
				ItemFunction.Additive,
				0
			},
			{
				ItemFunction.Scatterer,
				0
			},
			{
				ItemFunction.Other,
				0
			},
			{
				ItemFunction.Scoring,
				0
			}
		};
		List<ItemFunction> list = new List<ItemFunction>
		{
			ItemFunction.Multiplier,
			ItemFunction.Additive,
			ItemFunction.Scatterer,
			ItemFunction.Other,
			ItemFunction.Scoring
		};
		foreach (Item item in inventory)
		{
			foreach (ItemFunction item2 in list)
			{
				if (ItemFulfillsFunction(item, item2))
				{
					dictionary[item2]++;
				}
			}
		}
		return dictionary;
	}

	public static void DebugDictionary<T, S>(Dictionary<T, S> dictionary)
	{
		foreach (KeyValuePair<T, S> item in dictionary)
		{
			Debug.Log($"--- {item.Key}: {item.Value}");
		}
	}

	public static BuildData GetBuildDataForBuild(ItemTag buildTag)
	{
		List<Item> list = new List<Item>();
		foreach (Item allItem in GameStatics.GetPlayer().GetAllItems(forItemComparison: true))
		{
			if (allItem.GetAllShopAdviceTags().Contains(buildTag) || allItem.ItemFunctionTags.Contains(ItemFunctionTag.GenericAdditive) || allItem.ItemFunctionTags.Contains(ItemFunctionTag.GenericMultiplier))
			{
				list.Add(allItem);
			}
		}
		Dictionary<ItemFunction, int> functionTagCounts = GetFunctionTagCounts(list);
		return new BuildData(buildTag, list, functionTagCounts);
	}

	public static List<ItemTag> GetMostCommonBuilds(List<Item> inventory)
	{
		Dictionary<ItemTag, int> dictionary = new Dictionary<ItemTag, int>();
		foreach (Item item in inventory)
		{
			foreach (ItemTag allShopAdviceTag in item.GetAllShopAdviceTags())
			{
				if (GetBuildSynergyTags().Contains(allShopAdviceTag))
				{
					if (dictionary.ContainsKey(allShopAdviceTag))
					{
						dictionary[allShopAdviceTag]++;
					}
					else
					{
						dictionary[allShopAdviceTag] = 1;
					}
				}
			}
		}
		int num = 0;
		List<ItemTag> list = new List<ItemTag>();
		foreach (KeyValuePair<ItemTag, int> item2 in dictionary)
		{
			if (item2.Value > num)
			{
				num = item2.Value;
				list.Clear();
				list.Add(item2.Key);
			}
			else if (item2.Value == num)
			{
				list.Add(item2.Key);
			}
		}
		return list;
	}
}
