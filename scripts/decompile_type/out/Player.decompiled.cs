using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using UnityEngine;

public class Player
{
	public Guid GUID;

	public RunProgress CurrentRunProgress;

	public ItemInStock[] FrozenStickers = new ItemInStock[4];

	public ItemInStock[] FrozenStamps = new ItemInStock[2];

	public Item[] Stickers = new Item[5];

	public Item[] Stamps = new Item[5];

	public Tile[] ConsumableTiles = new Tile[10];

	public List<Type> BossesFaced = new List<Type>();

	public Character MyCharacter;

	public int Money;

	public List<BossModifier> ActiveBossModifiers = new List<BossModifier>();

	public bool HasFacedUncursedBoss;

	public bool IsDemo;

	public Player()
	{
		GUID = Guid.NewGuid();
		IsDemo = false;
	}

	public void SetCharacter(Character character)
	{
		MyCharacter = character;
		CurrentRunProgress = new RunProgress();
		CurrentRunProgress.CurrentRunStatistics = new RunStatistics();
		CurrentRunProgress.CurrentRunStatistics.IsSpeedrunMode = SaveManager.GetIsInSpeedrunMode();
		CurrentRunProgress.CurrentRunStatistics.IsFullProfile = SaveManager.GetPercentageCompletion() == "100";
		CurrentRunProgress.CurrentRunStatistics.Language = SaveManager.GetDictionaryLanguage();
		List<Type> earnedAchievementTypes = (from achievement in SaveManager.GetAchievements()
			select achievement.GetType()).ToList();
		List<Type> source = (from t in Assembly.GetAssembly(typeof(Achievement)).GetTypes()
			where t.IsClass && t.IsSubclassOf(typeof(Achievement))
			select t into achievementType
			where !earnedAchievementTypes.Contains(achievementType)
			select (Achievement)Activator.CreateInstance(achievementType) into achievement
			where achievement.IsFullRunAchievement
			select achievement.GetType()).ToList();
		CurrentRunProgress.CurrentRunStatistics.IsFullRunAchievementTypeAvailable = source.ToDictionary((Type type) => type, (Type isAvailable) => true);
		if (character.GetCharacterItem() is HumanHands)
		{
			AddItemToInventory(new LeftHumanHand());
			AddItemToInventory(new RightHumanHand());
		}
	}

	public Character GetCharacter()
	{
		if (MyCharacter == null)
		{
			MyCharacter = new WetDennis();
		}
		return MyCharacter;
	}

	public List<Item> GetAllItems(bool forItemComparison = false)
	{
		List<Item> list = new List<Item>();
		if (CurrentRunProgress != null && CurrentRunProgress.Challenge != null && CurrentRunProgress.Challenge is PlayingFavourites && !forItemComparison)
		{
			list.Add(MyCharacter.GetCharacterItem());
			list.AddRange(from sticker in GetStickers()
				where sticker.IsHumanBoyFavouriteSticker
				select sticker);
			Item item2 = Array.Find(Stickers, (Item item) => item is LeftHumanHand);
			Item item3 = Array.Find(Stamps, (Item item) => item is RightHumanHand);
			list.Add(item2);
			list.Add(item3);
			if (item3 != null)
			{
				int num = Array.IndexOf(Stamps, item3);
				if (num < 4)
				{
					list.Add(Stamps[num + 1]);
				}
			}
			return list.Where((Item item) => item != null).ToList();
		}
		if (MyCharacter != null && MyCharacter.GetCharacterItem() != null)
		{
			list.Add(MyCharacter.GetCharacterItem());
		}
		list.AddRange(Stickers);
		list.AddRange(Stamps);
		return list.Where((Item item) => item != null).ToList();
	}

	public List<Item> GetAllItemsIncludingNestedItems(bool forItemComparison)
	{
		List<Item> allItems = GetAllItems(forItemComparison);
		List<Item> list = new List<Item>();
		foreach (Item item in allItems)
		{
			list.Add(item);
			if (item is RandomAccessMemory)
			{
				RandomAccessMemory randomAccessMemory = item as RandomAccessMemory;
				list.AddRange(randomAccessMemory.ItemsInMemory);
			}
			else if (item is Snapshot)
			{
				Snapshot snapshot = item as Snapshot;
				if (snapshot.SnapshottedItem != null)
				{
					list.Add(snapshot.SnapshottedItem);
				}
			}
			else if (item is Frankenstein)
			{
				Frankenstein frankenstein = item as Frankenstein;
				list.AddRange(frankenstein.StitchedItems);
			}
		}
		return list;
	}

	public List<Item> GetStickers(bool forItemComparison = false)
	{
		if (CurrentRunProgress != null && CurrentRunProgress.Challenge != null && CurrentRunProgress.Challenge is PlayingFavourites && !forItemComparison)
		{
			List<Item> list = new List<Item>();
			list.AddRange(from sticker in Stickers
				where sticker != null
				where sticker.IsHumanBoyFavouriteSticker
				select sticker);
			Item item2 = Array.Find(Stickers, (Item item) => item is LeftHumanHand);
			if (item2 != null)
			{
				list.Add(item2);
			}
			return list;
		}
		return Stickers.Where((Item sticker) => sticker != null).ToList();
	}

	public List<Item> GetStamps(bool forItemComparison = false)
	{
		if (CurrentRunProgress != null && CurrentRunProgress.Challenge != null && CurrentRunProgress.Challenge is PlayingFavourites && !forItemComparison)
		{
			List<Item> list = new List<Item>();
			Item item2 = Array.Find(Stamps, (Item item) => item is RightHumanHand);
			list.Add(item2);
			if (item2 != null)
			{
				int num = Array.IndexOf(Stamps, item2);
				if (num < 4)
				{
					list.Add(Stamps[num + 1]);
				}
			}
			return list;
		}
		return Stamps.Where((Item stamp) => stamp != null).ToList();
	}

	public List<Tile> GetTiles()
	{
		return ConsumableTiles.Where((Tile tile) => tile != null).ToList();
	}

	public List<Item> GetUnpackedItemsOfType(Type itemType, bool forItemComparison = false)
	{
		List<Item> allItems = GetAllItems(forItemComparison);
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
		return allItems.Where((Item item) => item.GetType() == itemType).ToList();
	}

	public void PopulateInventoryFromChallenge()
	{
		List<Type> startingItems = CurrentRunProgress.Challenge.GetStartingItems();
		List<Tile> challengeRunStartingConsumableTiles = CurrentRunProgress.Challenge.GetChallengeRunStartingConsumableTiles();
		List<int> itemUpgrades = CurrentRunProgress.Challenge.GetItemUpgrades();
		foreach (Tile item2 in challengeRunStartingConsumableTiles)
		{
			AddTileToInventory(item2);
		}
		if (startingItems == null)
		{
			return;
		}
		for (int i = 0; i < startingItems.Count; i++)
		{
			Type type = startingItems[i];
			Item item = (Item)Activator.CreateInstance(type);
			item.IsSellingPrevented = type != typeof(NestEgg);
			AddItemToInventory(item);
			if (itemUpgrades != null && itemUpgrades.Count() > i && itemUpgrades[i] > 0)
			{
				for (int j = 0; j < itemUpgrades[i]; j++)
				{
					item.Upgrade(0);
					item.TimesUpgraded++;
				}
			}
		}
	}

	public void RemoveItemFromInventory(Item item)
	{
		if (Array.IndexOf(Stickers, item) != -1)
		{
			Stickers[Array.IndexOf(Stickers, item)] = null;
			if (item is ElectricGuitar)
			{
				MusicController.TryStopGuitar();
			}
			if (item is Maracas)
			{
				MusicController.TryStopMaracas();
			}
		}
		else if (Array.IndexOf(Stamps, item) != -1)
		{
			Stamps[Array.IndexOf(Stamps, item)] = null;
			if (item is Saxophone)
			{
				MusicController.TryStopSaxophone();
			}
		}
		else if (MyCharacter.GetCharacterItem() == item)
		{
			MyCharacter.ClearItem();
		}
		Item item2 = Array.Find(Stamps, (Item stamp) => stamp is SewingNeedle);
		if (item2 != null)
		{
			SetSewingNeedleSellability((SewingNeedle)item2);
		}
	}

	public void ClearStickers()
	{
		Stickers = new Item[5];
		Item item = Array.Find(Stamps, (Item stamp) => stamp is SewingNeedle);
		if (item != null)
		{
			SetSewingNeedleSellability((SewingNeedle)item);
		}
	}

	public void ClearStamps()
	{
		Stamps = new Item[5];
	}

	public void ClearInventory(bool removePin = false)
	{
		Stickers = new Item[5];
		Stamps = new Item[5];
		ConsumableTiles = new Tile[10];
		Money = 0;
		if (removePin)
		{
			MyCharacter.ClearItem();
		}
	}

	public void AddItemToInventory(Item item)
	{
		Debug.Log("Adding item to inventory - " + item.Name);
		if (item.UpgradeableComponents.Count == 0)
		{
			int num = Array.IndexOf(Stamps, null);
			if (num != -1)
			{
				Stamps[num] = item;
				if (item is Saxophone && (ActiveBossModifiers.Count == 0 || !(ActiveBossModifiers[0] is MichaelBoss)))
				{
					MusicController.TryStartSaxophone();
					PersistentSound.SingletonSoundController.AcquireSaxophone();
				}
			}
		}
		else if (item.UpgradeableComponents.Count == 1)
		{
			int num2 = Array.IndexOf(Stickers, null);
			if (num2 != -1)
			{
				Stickers[num2] = item;
				RefreshFavouriteSticker();
				RefreshUnderhandTargetSticker();
				if (item is ElectricGuitar && (ActiveBossModifiers.Count == 0 || !(ActiveBossModifiers[0] is MichaelBoss)))
				{
					MusicController.TryStartGuitar();
					PersistentSound.SingletonSoundController.AcquireGuitar();
				}
				if (item is Maracas && (ActiveBossModifiers.Count == 0 || !(ActiveBossModifiers[0] is MichaelBoss)))
				{
					MusicController.TryStartMaracas();
					PersistentSound.SingletonSoundController.AcquireMaracas();
				}
				Achievements.TryUnlockStacked();
			}
		}
		else if (item.UpgradeableComponents.Count == 2)
		{
			MyCharacter.SetItem(item);
		}
		Item item2 = Array.Find(Stamps, (Item stamp) => stamp is SewingNeedle);
		if (item2 != null)
		{
			SetSewingNeedleSellability((SewingNeedle)item2);
		}
		Achievements.TryUnlockMenagerie();
		Achievements.TryUnlockStuffOfLegend(item);
		item.OnAcquire();
	}

	public void SetSewingNeedleSellability(SewingNeedle sewingNeedle)
	{
		List<Item> stickers = GetStickers(forItemComparison: true);
		stickers.RemoveAll((Item sticker) => sewingNeedle.BlacklistedItems.Exists((Type type) => type == sticker.GetType()));
		sewingNeedle.IsSellingPrevented = stickers.Count < 2;
	}

	public void AddTileToInventory(Tile tile)
	{
		Debug.Log("Adding tile to inventory - " + tile.GetStringRepresentation());
		tile.SetTileToBeConsumable();
		int num = Array.IndexOf(ConsumableTiles, null);
		if ((GetUnpackedItemsOfType(typeof(Stadium)).Count == 0 && GetTiles().Count >= 5) || GetTiles().Count >= 10)
		{
			foreach (Item item4 in GetUnpackedItemsOfType(typeof(Brick)))
			{
				Tile[] consumableTiles = ConsumableTiles;
				foreach (Tile tile2 in consumableTiles)
				{
					if (!tile2.IsSandyBossTile)
					{
						tile2?.ChangeValueModifier(new ScorePacket(item4.UpgradeableComponents[0].VariableValue));
					}
				}
			}
			return;
		}
		List<Item> allItems = GetAllItems();
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
		foreach (Item item5 in list)
		{
			Frankenstein frankenstein = item5 as Frankenstein;
			allItems.AddRange(frankenstein.StitchedItems);
		}
		foreach (Item item6 in allItems.Where((Item item) => item is LuffingJibCrane))
		{
			if (!tile.AlreadyOnTileRack && !tile.IsSandyBossTile)
			{
				LuffingJibCrane luffingJibCrane = item6 as LuffingJibCrane;
				tile.ChangeValueModifier(new ScorePacket(luffingJibCrane.UpgradeableComponents[0].VariableValue));
			}
		}
		if (allItems.Exists((Item item) => item is EruptingVolcano))
		{
			foreach (Item item7 in allItems.Where((Item item) => item is EruptingVolcano))
			{
				if (!tile.IsSandyBossTile)
				{
					tile.SetTileType(item7.RelevantColours[0]);
				}
			}
		}
		if (num != -1)
		{
			ConsumableTiles[num] = tile;
		}
		tile.AlreadyOnTileRack = true;
	}

	public void SetInventoryTiles(List<Tile> tiles)
	{
		Tile[] consumableTiles = ConsumableTiles;
		foreach (Tile tile in consumableTiles)
		{
			if (!tiles.Contains(tile))
			{
				RemoveTileFromInventory(tile, isAppliedToGrid: false);
			}
		}
		foreach (Tile tile2 in tiles)
		{
			if (!ConsumableTiles.Contains(tile2))
			{
				AddTileToInventory(tile2);
			}
		}
	}

	public void RemoveTileFromInventory(Tile tile, bool isAppliedToGrid)
	{
		if (isAppliedToGrid)
		{
			CurrentRunProgress.CurrentRunStatistics.ConsumableTilesUsed.Add(tile);
			foreach (TileNinja item in GetUnpackedItemsOfType(typeof(TileNinja)))
			{
				item.ConsumableTilesUsed++;
			}
		}
		if (isAppliedToGrid && tile != null && tile.SafeFromDestruction)
		{
			CharacterInfoPanel.SingletonInventoryVisualController.RefreshInspect();
			return;
		}
		ConsumableTiles[Array.IndexOf(ConsumableTiles, tile)] = null;
		CharacterInfoPanel.SingletonInventoryVisualController.RefreshInspect();
	}

	public void SetInventoryTilesArray(Tile[] tileArray)
	{
		ConsumableTiles = tileArray;
	}

	public void ChangeMoney(int change)
	{
		Debug.Log($"ChangeMoney called with {change}");
		Money = Mathf.Max(0, Money + change);
		if (change > 0)
		{
			CurrentRunProgress.CurrentRunStatistics.TotalCashEarned += change;
		}
		if (CharacterInfoPanel.SingletonInventoryVisualController != null)
		{
			CharacterInfoPanel.SingletonInventoryVisualController.RefreshInspect();
		}
		if (change < 0)
		{
			foreach (CoinPurse item in GetUnpackedItemsOfType(typeof(CoinPurse)))
			{
				item.Count++;
			}
		}
		if (Money > 100 && !ActiveBossModifiers.Exists((BossModifier boss) => boss is CretaceousMegBoss))
		{
			Achievements.UnlockAchievement(typeof(SuperSaver));
		}
		if (change != 0 && GetTiles().Exists((Tile tile) => tile.GetTileType() == TileType.Gold))
		{
			CharacterInfoPanel.SingletonInventoryVisualController.PopulateTiles();
		}
	}

	public int GetStampIndex(Item item)
	{
		return Array.IndexOf(Stamps, item);
	}

	public Tile GetConsumableTileByIndex(int index)
	{
		return ConsumableTiles[index];
	}

	public bool HasGenerator()
	{
		foreach (Item allItem in GetAllItems())
		{
			foreach (ItemTag tag in allItem.Tags)
			{
				if (Item.GeneratorTags.Contains(tag))
				{
					return true;
				}
			}
		}
		return false;
	}

	public List<ItemTag> GetBuildSynergyTags()
	{
		List<ItemTag> list = new List<ItemTag>
		{
			ItemTag.BlueBuild,
			ItemTag.RedBuild,
			ItemTag.VoidBuild,
			ItemTag.ShinyBuild,
			ItemTag.ChessBuild,
			ItemTag.BlankBuild,
			ItemTag.ColourlessBuild,
			ItemTag.CashBuild,
			ItemTag.RainbowBuild,
			ItemTag.ConsumableBuild,
			ItemTag.CurseBuild,
			ItemTag.NumbersBuild,
			ItemTag.ArrowBuild,
			ItemTag.CardsBuild,
			ItemTag.BigNumbersBuild,
			ItemTag.ScatteredItemsBuild
		};
		List<ItemTag> list2 = new List<ItemTag>();
		foreach (Item allItem in GetAllItems())
		{
			foreach (ItemTag tag in allItem.Tags)
			{
				if (list.Contains(tag) && !list2.Contains(tag))
				{
					list2.Add(tag);
				}
			}
		}
		return list2;
	}

	public List<ItemTag> GetOrderedBuildSynergyTags()
	{
		List<ItemTag> list = new List<ItemTag>
		{
			ItemTag.BlueBuild,
			ItemTag.RedBuild,
			ItemTag.VoidBuild,
			ItemTag.ShinyBuild,
			ItemTag.ChessBuild,
			ItemTag.BlankBuild,
			ItemTag.ColourlessBuild,
			ItemTag.CashBuild,
			ItemTag.RainbowBuild,
			ItemTag.ConsumableBuild,
			ItemTag.CurseBuild,
			ItemTag.NumbersBuild,
			ItemTag.ArrowBuild,
			ItemTag.CardsBuild,
			ItemTag.BigNumbersBuild,
			ItemTag.ScatteredItemsBuild
		};
		Dictionary<ItemTag, int> dictionary = new Dictionary<ItemTag, int>();
		foreach (Item allItem in GetAllItems())
		{
			foreach (ItemTag tag in allItem.Tags)
			{
				if (list.Contains(tag))
				{
					if (dictionary.Keys.Contains(tag))
					{
						dictionary[tag]++;
					}
					else
					{
						dictionary[tag] = 1;
					}
				}
			}
		}
		if (dictionary.Keys.Count == 0)
		{
			return new List<ItemTag>();
		}
		int num = dictionary.Values.Max();
		List<ItemTag> list2 = new List<ItemTag>();
		for (int num2 = num; num2 > 0; num2--)
		{
			foreach (KeyValuePair<ItemTag, int> item in dictionary)
			{
				if (item.Value == num2)
				{
					list2.Add(item.Key);
				}
			}
		}
		return list2;
	}

	public List<ItemTag> GetUnfulfilledDependencyTags()
	{
		List<ItemTag> activeTags = new List<ItemTag>();
		bool flag = true;
		while (flag)
		{
			flag = false;
			foreach (Item allItem in GetAllItems())
			{
				List<ItemTag> list = allItem.Tags.Except(activeTags).ToList();
				if (list.Count != 0)
				{
					if (allItem.DependencyTags.Count == 0)
					{
						activeTags.AddRange(list);
						flag = true;
					}
					else if (activeTags.Intersect(allItem.DependencyTags).Any())
					{
						activeTags.AddRange(list);
						flag = true;
					}
				}
			}
		}
		List<ItemTag> unfulfilledTags = new List<ItemTag>();
		foreach (Item allItem2 in GetAllItems())
		{
			unfulfilledTags.AddRange(allItem2.DependencyTags.Where((ItemTag tag) => !unfulfilledTags.Contains(tag) && !activeTags.Contains(tag)));
		}
		return unfulfilledTags;
	}

	public static T[] Shuffle<T>(List<T> list)
	{
		T[] array = new T[list.Count];
		if (list.Count == 0)
		{
			return new T[0];
		}
		foreach (T item in list)
		{
			List<int> list2 = new List<int>();
			for (int i = 0; i < array.Length; i++)
			{
				if (array[i] == null)
				{
					list2.Add(i);
				}
			}
			int num = list2[UnityEngine.Random.Range(0, list2.Count)];
			array[num] = item;
		}
		return array;
	}

	public void RandomiseItemOrder(bool includingStamps)
	{
		Stickers = Shuffle(Stickers.ToList());
		if (includingStamps)
		{
			Stamps = Shuffle(Stamps.ToList());
		}
		RefreshFavouriteSticker();
		CharacterInfoPanel.SingletonInventoryVisualController.PopulateStamps();
		CharacterInfoPanel.SingletonInventoryVisualController.PopulateStickers();
	}

	public void RefreshFavouriteSticker()
	{
		Item[] stickers = Stickers;
		foreach (Item item2 in stickers)
		{
			if (item2 != null && item2.IsHumanBoyFavouriteSticker)
			{
				item2.IsHumanBoyFavouriteSticker = false;
				item2.LeftHandDowngrade();
			}
		}
		Item item3 = Stickers.ToList().Find((Item item) => item is LeftHumanHand);
		if (item3 != null)
		{
			int num = Array.IndexOf(Stickers, item3);
			if (num > 0 && Stickers[num - 1] != null)
			{
				Stickers[num - 1].IsHumanBoyFavouriteSticker = true;
				Stickers[num - 1].LeftHandUpgrade();
			}
		}
	}

	public void RefreshUnderhandTargetSticker()
	{
		Item[] stickers = Stickers;
		foreach (Item item2 in stickers)
		{
			if (item2 != null && item2.IsUnderhandTarget)
			{
				item2.IsUnderhandTarget = false;
				item2.UnderhandDowngrade();
			}
		}
		Item item3 = Stamps.ToList().Find((Item item) => item is Underhand);
		if (item3 != null)
		{
			int num = Array.IndexOf(Stamps, item3);
			if (Stickers[num] != null)
			{
				Stickers[num].IsUnderhandTarget = true;
				Stickers[num].UnderhandUpgrade();
			}
		}
	}

	public bool IsHumanBoyFavouriteStamp(Item item)
	{
		int num = Array.IndexOf(Stamps, item);
		if (num <= 0)
		{
			return false;
		}
		return Stamps[num - 1] is RightHumanHand;
	}

	public bool IsOverhandTarget(Item item)
	{
		int num = Array.IndexOf(Stamps, item);
		if (num < 0)
		{
			return false;
		}
		return Stickers[num] is Overhand;
	}

	public int GetFrozenItemsCount()
	{
		int num = 0;
		ItemInStock[] frozenStickers = FrozenStickers;
		for (int i = 0; i < frozenStickers.Length; i++)
		{
			if (frozenStickers[i] != null)
			{
				num++;
			}
		}
		frozenStickers = FrozenStamps;
		for (int i = 0; i < frozenStickers.Length; i++)
		{
			if (frozenStickers[i] != null)
			{
				num++;
			}
		}
		return num;
	}

	public Item GetHBFavouriteStamp()
	{
		return GetStamps(forItemComparison: true).Find((Item item) => IsHumanBoyFavouriteStamp(item));
	}

	public Item GetHBFavouriteSticker()
	{
		return GetStickers(forItemComparison: true).Find((Item item) => item.IsHumanBoyFavouriteSticker);
	}
}
