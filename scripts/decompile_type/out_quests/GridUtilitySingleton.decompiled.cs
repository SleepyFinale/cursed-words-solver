using System;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;

public class GridUtilitySingleton
{
	public GridData GenerateGrid(int width, int height, int gridNumber, int numberOfGrids, List<HistoricWord> previousWords, List<BossModifier> bossModifiers, out List<BoardGenVizInfo> vizSteps, bool isReroll, List<Tile> staticTiles = null)
	{
		ChallengeRun challenge = GameStatics.GetPlayer().CurrentRunProgress.Challenge;
		bool num = GameStatics.GetPlayer().GetUnpackedItemsOfType(typeof(Hourglass)).Count % 2 == 1;
		vizSteps = new List<BoardGenVizInfo>();
		GridData gridData = GenerateBasicGridData(width, height, vizSteps, bossModifiers, gridNumber, staticTiles);
		if (num)
		{
			gridData = MakeStartOfGridBossAdjustments(gridData, bossModifiers, challenge, vizSteps, gridNumber, isReroll, goBackwards: true);
			gridData = MakeStartOfGridChallengeAdjustments(gridData, vizSteps, isReroll);
			gridData = MakeStartOfGridItemAdjustments(gridData, gridNumber, numberOfGrids, previousWords, vizSteps, isReroll, goBackwards: true);
		}
		else
		{
			gridData = MakeStartOfGridItemAdjustments(gridData, gridNumber, numberOfGrids, previousWords, vizSteps, isReroll);
			gridData = MakeStartOfGridChallengeAdjustments(gridData, vizSteps, isReroll);
			gridData = MakeStartOfGridBossAdjustments(gridData, bossModifiers, challenge, vizSteps, gridNumber, isReroll);
		}
		while (vizSteps[vizSteps.Count - 1].Grid.GetAvailableTiles().Exists((Tile tile) => tile.GetTileType() != 0 && tile.GetTileType() != TileType.Glitch && !GameStatics.GetPlayer().CurrentRunProgress.AvailableColours.Contains(tile.GetTileType())))
		{
			TileType tileType = vizSteps[vizSteps.Count - 1].Grid.GetAvailableTiles().Find((Tile tile) => tile.GetTileType() != 0 && tile.GetTileType() != TileType.Glitch && !GameStatics.GetPlayer().CurrentRunProgress.AvailableColours.Contains(tile.GetTileType())).GetTileType();
			GameStatics.GetPlayer().CurrentRunProgress.AddAvailableColour(tileType);
		}
		return gridData;
	}

	public GridData GenerateEsPuzzleGrid(GridData puzzleGridData, out List<BoardGenVizInfo> vizSteps)
	{
		vizSteps = new List<BoardGenVizInfo>();
		BoardGenVizInfo item = new BoardGenVizInfo(puzzleGridData, null, null, isPulsingMoney: false, null, isPulsingGridNumber: false, basicGridGen: true, isPulsingPreviousWord: false, new Tile[10]);
		vizSteps.Add(item);
		return puzzleGridData;
	}

	public virtual GridData GenerateBasicGridData(int width, int height, List<BoardGenVizInfo> vizSteps, List<BossModifier> bossModifiers, int gridNumber, List<Tile> staticTiles = null)
	{
		Player player = GameStatics.GetPlayer();
		GridData gridData = new GridData();
		gridData.GridTiles = new Tile[width * height];
		gridData.GridNumber = gridNumber;
		bool flag = GameStatics.GetPlayer().CurrentRunProgress.IsAscensionModifierActive(AscensionLevel.HarderGridGeneration);
		ChallengeRun challenge = GameStatics.GetPlayer().CurrentRunProgress.Challenge;
		List<int> list = new List<int>();
		for (int i = 1; i <= width * height; i++)
		{
			list.Add(i);
		}
		for (int j = 0; j < gridData.GridTiles.Length; j++)
		{
			Vector2Int coords = new Vector2Int(j % width, j / width);
			if (staticTiles != null && staticTiles.Exists((Tile tile) => tile.Coordinates.Equals(coords)))
			{
				gridData.GridTiles[j] = staticTiles.Find((Tile tile) => tile.Coordinates.Equals(coords));
				continue;
			}
			Tile tile2 = new Tile();
			gridData.GridTiles[j] = tile2;
			tile2.SetCoordinates(coords);
			if (challenge is RedLetterDay)
			{
				tile2.SetLetter(Vocabulary.ActiveLanguageVocabulary.LanguageAlphabet.GetRandomConsonantWeighted());
				tile2.SetGlyphType(GlyphType.Letter);
			}
			else if (challenge is RedPepperDay)
			{
				tile2.SetLetter(Vocabulary.ActiveLanguageVocabulary.LanguageAlphabet.GetRandomVowelWeighted());
				tile2.SetGlyphType(GlyphType.Letter);
			}
			else if (challenge is EmptyGrid)
			{
				tile2.SetIsEmpty(isEmpty: true);
			}
			else if (challenge is Sudoku)
			{
				int index = UnityEngine.Random.Range(0, list.Count);
				tile2.SetNumber(list[index]);
				list.RemoveAt(index);
			}
			else
			{
				tile2.SetLetter(flag ? Vocabulary.ActiveLanguageVocabulary.LanguageAlphabet.GetRandomLetterAscensionWeighted() : Vocabulary.ActiveLanguageVocabulary.LanguageAlphabet.GetRandomLetterWeighted());
				tile2.SetGlyphType(GlyphType.Letter);
			}
		}
		gridData.SetDimensions(new Vector2Int(width, height));
		if (challenge is CallOfTheVoid)
		{
			Tile[] gridTiles = gridData.GridTiles;
			foreach (Tile tile3 in gridTiles)
			{
				if (!IsEdgeTile(tile3, gridData))
				{
					tile3.IsInTheVoid = true;
					tile3.Gone = true;
				}
			}
		}
		if (challenge is MunchTime)
		{
			MunchTime munchTime = (MunchTime)challenge;
			if (munchTime.MunchedCoordinates.Count == 0)
			{
				munchTime.PathThroughGrid = GeneratePathThroughGrid(gridData);
			}
			foreach (Vector2Int munchedCoordinate in munchTime.MunchedCoordinates)
			{
				gridData.GetTileAtCoordinates(munchedCoordinate).HasBeenDestroyed = true;
				gridData.GetTileAtCoordinates(munchedCoordinate).Gone = true;
			}
		}
		RunProgress currentRunProgress = GameStatics.GetPlayer().CurrentRunProgress;
		if (challenge is SupplyAndDemand && currentRunProgress.CurrentRunStatistics.WordsSubmittedThisRun.Count > 0)
		{
			Tile[] gridTiles = gridData.GridTiles;
			foreach (Tile gridTile in gridTiles)
			{
				List<Tile> tiles = currentRunProgress.CurrentRunStatistics.WordsSubmittedThisRun[currentRunProgress.CurrentRunStatistics.WordsSubmittedThisRun.Count - 1].Tiles;
				gridTile.IsCrossedOut = tiles.Exists((Tile tile) => tile.GetStringRepresentation() == gridTile.GetStringRepresentation());
			}
		}
		foreach (BossModifier bossModifier in bossModifiers)
		{
			if (!(bossModifier is DestroyGrid))
			{
				continue;
			}
			foreach (Vector2Int destroyedCoordinate in ((DestroyGrid)bossModifier).DestroyedCoordinates)
			{
				gridData.GetTileAtCoordinates(destroyedCoordinate).HasBeenDestroyed = true;
				gridData.GetTileAtCoordinates(destroyedCoordinate).Gone = true;
			}
		}
		Tile[] array = new Tile[10];
		Array.Copy(player.ConsumableTiles, array, 10);
		BoardGenVizInfo item = new BoardGenVizInfo(gridData, null, null, isPulsingMoney: false, null, isPulsingGridNumber: false, basicGridGen: true, isPulsingPreviousWord: false, array);
		vizSteps.Add(item);
		return gridData;
	}

	public GridData MakeStartOfGridItemAdjustments(GridData gridData, int gridNumber, int numberOfGrids, List<HistoricWord> previousWords, List<BoardGenVizInfo> vizSteps, bool isReroll, bool goBackwards = false)
	{
		List<Item> list = new List<Item>();
		if (previousWords.Count > 0)
		{
			foreach (Tile tile in previousWords[previousWords.Count - 1].Tiles)
			{
				if (tile.GetGlyphType() == GlyphType.ScatteredItem)
				{
					list.Add(tile.ScatteredItem);
				}
			}
		}
		Player player = GameStatics.GetPlayer();
		RunProgress currentRunProgress = player.CurrentRunProgress;
		list.AddRange(player.GetAllItems());
		if (goBackwards)
		{
			list.Reverse();
		}
		bool flag = player.GetUnpackedItemsOfType(typeof(SaguaroSeedling)) != null && player.GetUnpackedItemsOfType(typeof(SaguaroSeedling)).Exists((Item item) => item.RelevantColours[0] == TileType.Cactus);
		List<Vector2Int> list2 = (from tile in gridData.GetAvailableTiles()
			where tile.IsTileType(TileType.Cactus)
			select tile.Coordinates).ToList();
		foreach (Item item5 in list)
		{
			if (item5 is RandomAccessMemory)
			{
				RandomAccessMemory randomAccessMemory = item5 as RandomAccessMemory;
				List<Item> list3 = new List<Item>(randomAccessMemory.ItemsInMemory);
				if (goBackwards)
				{
					list3.Reverse();
				}
				foreach (Item item6 in list3)
				{
					gridData = item6.ApplyStartOfGridEffect(gridData, gridNumber, numberOfGrids, previousWords, vizSteps, isReroll);
					foreach (BoardGenVizInfo vizStep in vizSteps)
					{
						if (vizStep.RelevantItem == item6)
						{
							vizStep.RelevantItem = randomAccessMemory;
						}
					}
				}
				continue;
			}
			if (item5 is Frankenstein)
			{
				Frankenstein frankenstein = item5 as Frankenstein;
				foreach (Item stitchedItem in frankenstein.StitchedItems)
				{
					if (stitchedItem == null)
					{
						continue;
					}
					gridData = stitchedItem.ApplyStartOfGridEffect(gridData, gridNumber, numberOfGrids, previousWords, vizSteps, isReroll);
					foreach (BoardGenVizInfo vizStep2 in vizSteps)
					{
						if (vizStep2.RelevantItem == stitchedItem)
						{
							vizStep2.RelevantItem = frankenstein;
						}
					}
				}
				continue;
			}
			gridData = item5.ApplyStartOfGridEffect(gridData, gridNumber, numberOfGrids, previousWords, vizSteps, isReroll);
			if (player.IsHumanBoyFavouriteStamp(item5) && player.GetCharacter().GetCharacterItem().UpgradeableComponents[1].VariableValue > 1)
			{
				for (int i = 0; i < player.GetCharacter().GetCharacterItem().UpgradeableComponents[1].VariableValue - 1; i++)
				{
					gridData = item5.ApplyStartOfGridEffect(gridData, gridNumber, numberOfGrids, previousWords, vizSteps, isReroll);
				}
			}
			Debug.Log($"ITEM {item5.Name}. Is overhand target? {player.IsOverhandTarget(item5)}");
			Item item2 = player.GetStickers().Find((Item item) => item is Overhand);
			if (player.IsOverhandTarget(item5) && item2 != null)
			{
				Debug.Log("Overhand target found");
				for (int j = 0; j < item2.UpgradeableComponents[0].VariableValue; j++)
				{
					gridData = item5.ApplyStartOfGridEffect(gridData, gridNumber, numberOfGrids, previousWords, vizSteps, isReroll);
				}
			}
		}
		List<Item> list4 = new List<Item>(player.GetAllItems());
		if (goBackwards)
		{
			list4.Reverse();
		}
		foreach (Item item7 in list4)
		{
			if (item7 is RandomAccessMemory)
			{
				RandomAccessMemory randomAccessMemory2 = item7 as RandomAccessMemory;
				List<Item> list5 = new List<Item>(randomAccessMemory2.ItemsInMemory);
				if (goBackwards)
				{
					list5.Reverse();
				}
				foreach (Item item8 in list5)
				{
					gridData = item8.FinalStartOfGridEffect(gridData, gridNumber, numberOfGrids, previousWords, vizSteps);
					foreach (BoardGenVizInfo vizStep3 in vizSteps)
					{
						if (vizStep3.RelevantItem == item8)
						{
							vizStep3.RelevantItem = randomAccessMemory2;
						}
					}
				}
				continue;
			}
			if (item7 is Frankenstein)
			{
				Frankenstein frankenstein2 = item7 as Frankenstein;
				foreach (Item stitchedItem2 in frankenstein2.StitchedItems)
				{
					if (stitchedItem2 == null)
					{
						continue;
					}
					gridData = stitchedItem2.FinalStartOfGridEffect(gridData, gridNumber, numberOfGrids, previousWords, vizSteps);
					foreach (BoardGenVizInfo vizStep4 in vizSteps)
					{
						if (vizStep4.RelevantItem == stitchedItem2)
						{
							vizStep4.RelevantItem = frankenstein2;
						}
					}
				}
				continue;
			}
			gridData = item7.FinalStartOfGridEffect(gridData, gridNumber, numberOfGrids, previousWords, vizSteps);
			if (player.IsHumanBoyFavouriteStamp(item7) && player.GetCharacter().GetCharacterItem().UpgradeableComponents[1].VariableValue > 1)
			{
				for (int k = 0; k < player.GetCharacter().GetCharacterItem().UpgradeableComponents[1].VariableValue - 1; k++)
				{
					gridData = item7.FinalStartOfGridEffect(gridData, gridNumber, numberOfGrids, previousWords, vizSteps);
				}
			}
			Item item3 = player.GetStickers().Find((Item item) => item is Overhand);
			if (player.IsOverhandTarget(item7) && item3 != null)
			{
				for (int l = 0; l < item3.UpgradeableComponents[0].VariableValue; l++)
				{
					gridData = item7.FinalStartOfGridEffect(gridData, gridNumber, numberOfGrids, previousWords, vizSteps);
				}
			}
			if (gridData.GetAvailableTiles().Count((Tile tile) => tile.GetTileType() == TileType.Cactus) == list2.Count)
			{
				continue;
			}
			List<Tile> list6 = (from tile in gridData.GetAvailableTiles()
				where tile.GetTileType() == TileType.Cactus
				select tile).ToList();
			List<Tile> list7 = new List<Tile>();
			foreach (Tile cactus in list6)
			{
				if (!list2.Exists((Vector2Int coord) => coord.Equals(cactus.Coordinates)))
				{
					currentRunProgress.CactusGrowthLevel += ((!flag) ? 1 : 2);
					cactus.CactusGrowth += (long)currentRunProgress.CactusGrowthLevel;
					list7.Add(cactus);
				}
			}
			list2 = list6.Select((Tile tile) => tile.Coordinates).ToList();
			if (list7.Count > 0)
			{
				BoardGenVizInfo item4 = new BoardGenVizInfo(gridData, null, list7, isPulsingMoney: false, null, isPulsingGridNumber: false, basicGridGen: false, isPulsingPreviousWord: false, vizSteps[vizSteps.Count - 1].PlayerConsumableTiles);
				vizSteps.Add(item4);
			}
		}
		return gridData;
	}

	public Tile GetTileForBossScatter(GridData gridData, ChallengeRun challenge, List<Tile> blackListedTiles)
	{
		List<Tile> unusableTiles = new List<Tile>(blackListedTiles);
		Vector2Int dimensions = gridData.GetDimensions();
		if (challenge is UpAndUp)
		{
			unusableTiles.Add(gridData.GetTileAtCoordinates(new Vector2Int(dimensions.x / 2, dimensions.y / 2)));
		}
		List<Tile> list = (from tile in gridData.GetAvailableTiles()
			where !unusableTiles.Contains(tile)
			select tile).ToList();
		if (list.Count == 0)
		{
			return null;
		}
		return list[UnityEngine.Random.Range(0, list.Count)];
	}

	public GridData MakeStartOfGridBossAdjustments(GridData gridData, List<BossModifier> bossModifiers, ChallengeRun challenge, List<BoardGenVizInfo> vizSteps, int gridNumber, bool isReroll, bool goBackwards = false)
	{
		List<Vector2Int> list = (from tile in gridData.GetAvailableTiles()
			where tile.IsTileType(TileType.Cactus)
			select tile.Coordinates).ToList();
		Player player = GameStatics.GetPlayer();
		RunProgress currentRunProgress = player.CurrentRunProgress;
		bool flag = player.GetUnpackedItemsOfType(typeof(SaguaroSeedling)) != null && player.GetUnpackedItemsOfType(typeof(SaguaroSeedling)).Exists((Item item) => item.RelevantColours[0] == TileType.Cactus);
		List<BossModifier> list2 = new List<BossModifier>(bossModifiers);
		if (goBackwards)
		{
			list2.Reverse();
		}
		foreach (BossModifier item10 in list2)
		{
			if (item10 is ExtraQs)
			{
				List<Tile> list3 = new List<Tile>();
				for (int i = 0; i < item10.FloorAdjustedModification; i++)
				{
					List<Tile> blackListedTiles = (from tile in gridData.GetAvailableTiles()
						where tile.GetStringRepresentation() == "q"
						select tile).ToList();
					Tile tileForBossScatter = GetTileForBossScatter(gridData, challenge, blackListedTiles);
					if (tileForBossScatter != null)
					{
						tileForBossScatter.SetLetter("q");
						list3.Add(tileForBossScatter);
					}
				}
				if (list3.Count > 0)
				{
					BoardGenVizInfo item2 = new BoardGenVizInfo(gridData, null, list3, isPulsingMoney: false, typeof(ExtraQs), isPulsingGridNumber: false, basicGridGen: false, isPulsingPreviousWord: false, vizSteps[vizSteps.Count - 1].PlayerConsumableTiles);
					vizSteps.Add(item2);
				}
			}
			else if (item10 is ExtraVoids)
			{
				List<Tile> list4 = new List<Tile>();
				ExtraVoids evs = item10 as ExtraVoids;
				for (int j = 0; j < item10.FloorAdjustedModification; j++)
				{
					List<Tile> blackListedTiles2 = (from tile in gridData.GetAvailableTiles()
						where tile.IsTileType(evs.TileTypeToScatter)
						select tile).ToList();
					Tile tileForBossScatter2 = GetTileForBossScatter(gridData, challenge, blackListedTiles2);
					if (tileForBossScatter2 != null)
					{
						tileForBossScatter2.SetTileType(evs.TileTypeToScatter);
						list4.Add(tileForBossScatter2);
					}
				}
				if (list4.Count > 0)
				{
					BoardGenVizInfo item3 = new BoardGenVizInfo(gridData, null, list4, isPulsingMoney: false, typeof(ExtraVoids), isPulsingGridNumber: false, basicGridGen: false, isPulsingPreviousWord: false, vizSteps[vizSteps.Count - 1].PlayerConsumableTiles);
					vizSteps.Add(item3);
				}
			}
			else if (item10 is AddNumbers)
			{
				List<Tile> list5 = new List<Tile>();
				for (int k = 7; k < item10.FloorAdjustedModification + 1; k++)
				{
					Tile tileForBossScatter3 = GetTileForBossScatter(gridData, challenge, list5);
					if (tileForBossScatter3 != null)
					{
						tileForBossScatter3.SetNumber(k);
						list5.Add(tileForBossScatter3);
					}
				}
				if (list5.Count > 0)
				{
					BoardGenVizInfo item4 = new BoardGenVizInfo(gridData, null, list5, isPulsingMoney: false, typeof(AddNumbers), isPulsingGridNumber: false, basicGridGen: false, isPulsingPreviousWord: false, vizSteps[vizSteps.Count - 1].PlayerConsumableTiles);
					vizSteps.Add(item4);
				}
			}
			else if (item10 is DiscolourTiles)
			{
				List<Tile> list6 = new List<Tile>();
				for (int l = 0; l < item10.FloorAdjustedModification; l++)
				{
					List<Tile> blackListedTiles3 = (from tile in gridData.GetAvailableTiles()
						where tile.GetTileType() == TileType.Normal
						select tile).ToList();
					Tile tileForBossScatter4 = GetTileForBossScatter(gridData, challenge, blackListedTiles3);
					if (tileForBossScatter4 != null)
					{
						tileForBossScatter4.SetTileType(TileType.Normal);
						list6.Add(tileForBossScatter4);
					}
				}
				if (list6.Count > 0)
				{
					BoardGenVizInfo item5 = new BoardGenVizInfo(gridData, null, list6, isPulsingMoney: false, typeof(DiscolourTiles), isPulsingGridNumber: false, basicGridGen: false, isPulsingPreviousWord: false, vizSteps[vizSteps.Count - 1].PlayerConsumableTiles);
					vizSteps.Add(item5);
				}
			}
			else if (item10 is DestroyGrid && !isReroll)
			{
				List<Tile> list7 = new List<Tile>();
				List<Vector2Int> list8 = (from tile in gridData.GetAvailableTiles()
					where !tile.HasBeenDestroyed
					select tile.Coordinates).ToList();
				DestroyGrid destroyGrid = (DestroyGrid)item10;
				int num = destroyGrid.FloorAdjustedModification;
				if (destroyGrid.DestroyedCoordinates.Count > 3)
				{
					num--;
				}
				for (int m = 0; m < num; m++)
				{
					if (list8.Count > 1)
					{
						Vector2Int vector2Int = list8[UnityEngine.Random.Range(0, list8.Count)];
						destroyGrid.DestroyedCoordinates.Add(vector2Int);
						list8.Remove(vector2Int);
						Tile tileAtCoordinates = gridData.GetTileAtCoordinates(vector2Int);
						tileAtCoordinates.HasBeenDestroyed = true;
						list7.Add(tileAtCoordinates);
					}
				}
				if (list7.Count > 0)
				{
					BoardGenVizInfo item6 = new BoardGenVizInfo(gridData, null, list7, isPulsingMoney: false, typeof(DestroyGrid), isPulsingGridNumber: false, basicGridGen: false, isPulsingPreviousWord: false, vizSteps[vizSteps.Count - 1].PlayerConsumableTiles);
					vizSteps.Add(item6);
				}
			}
			else if (item10 is SandySaguaroBoss)
			{
				SandySaguaroBoss sandySaguaroBoss = (SandySaguaroBoss)item10;
				BoardGenVizInfo item7 = new BoardGenVizInfo(gridData, null, null, isPulsingMoney: false, typeof(SandySaguaroBoss), isPulsingGridNumber: false, basicGridGen: false, isPulsingPreviousWord: false, sandySaguaroBoss.GenerateConsumableTiles());
				vizSteps.Add(item7);
			}
			else if (item10 is HumanBoyBoss && gridNumber == 1 && !isReroll)
			{
				BoardGenVizInfo boardGenVizInfo = new BoardGenVizInfo(gridData, null, null, isPulsingMoney: false, typeof(HumanBoyBoss), isPulsingGridNumber: false, basicGridGen: false, isPulsingPreviousWord: false, vizSteps[vizSteps.Count - 1].PlayerConsumableTiles);
				HumanBoyBoss humanBoyBoss = (HumanBoyBoss)item10;
				boardGenVizInfo.PlayerItemToRemove = humanBoyBoss.GetItemToSteal();
				humanBoyBoss.StolenItem = boardGenVizInfo.PlayerItemToRemove;
				vizSteps.Add(boardGenVizInfo);
			}
			else if (item10 is PrismaticBeanBoss)
			{
				List<Tile> list9 = new List<Tile>();
				List<TileType> list10 = new List<TileType>
				{
					TileType.Red,
					TileType.Blue,
					TileType.Green,
					TileType.Gold,
					TileType.Purple,
					TileType.White,
					TileType.Void,
					TileType.Shiny,
					TileType.Pink,
					TileType.Cactus
				};
				if (SaveManager.HasSeenGlitchTile())
				{
					list10.Add(TileType.Glitch);
				}
				foreach (Tile availableTile in gridData.GetAvailableTiles())
				{
					availableTile.SetTileType(list10[UnityEngine.Random.Range(0, list10.Count)]);
					list9.Add(availableTile);
				}
				if (list9.Count > 0)
				{
					BoardGenVizInfo item8 = new BoardGenVizInfo(gridData, null, list9, isPulsingMoney: false, typeof(PrismaticBeanBoss), isPulsingGridNumber: false, basicGridGen: false, isPulsingPreviousWord: false, vizSteps[vizSteps.Count - 1].PlayerConsumableTiles);
					vizSteps.Add(item8);
				}
			}
			if (gridData.GetAvailableTiles().Count((Tile tile) => tile.GetTileType() == TileType.Cactus) == list.Count)
			{
				continue;
			}
			List<Tile> list11 = (from tile in gridData.GetAvailableTiles()
				where tile.GetTileType() == TileType.Cactus
				select tile).ToList();
			List<Tile> list12 = new List<Tile>();
			foreach (Tile cactus in list11)
			{
				if (!list.Exists((Vector2Int coord) => coord.Equals(cactus.Coordinates)))
				{
					currentRunProgress.CactusGrowthLevel += ((!flag) ? 1 : 2);
					cactus.CactusGrowth += (long)currentRunProgress.CactusGrowthLevel;
					list12.Add(cactus);
				}
			}
			list = list11.Select((Tile tile) => tile.Coordinates).ToList();
			if (list12.Count > 0)
			{
				BoardGenVizInfo item9 = new BoardGenVizInfo(gridData, null, list12, isPulsingMoney: false, null, isPulsingGridNumber: false, basicGridGen: false, isPulsingPreviousWord: false, vizSteps[vizSteps.Count - 1].PlayerConsumableTiles);
				vizSteps.Add(item9);
			}
		}
		return gridData;
	}

	public GridData MakeStartOfGridChallengeAdjustments(GridData gridData, List<BoardGenVizInfo> vizSteps, bool isReroll)
	{
		ChallengeRun challenge = GameStatics.GetPlayer().CurrentRunProgress.Challenge;
		if (challenge is MunchTime && !isReroll)
		{
			(from tile in gridData.GetAvailableTiles()
				where !tile.HasBeenDestroyed
				select tile.Coordinates).ToList();
			MunchTime munchTime = (MunchTime)challenge;
			Vector2Int vector2Int = munchTime.PathThroughGrid[munchTime.PathThroughGrid.Count - 1];
			munchTime.MunchedCoordinates.Add(vector2Int);
			munchTime.PathThroughGrid.Remove(vector2Int);
			Debug.Log($"Remaining encounters = {GameStatics.GetPlayer().CurrentRunProgress.GetRemainingEncounters()}");
			if (munchTime.PathThroughGrid.Count <= GameStatics.GetPlayer().CurrentRunProgress.GetRemainingEncounters())
			{
				gridData.HasLostChallenge = true;
			}
			Tile tileAtCoordinates = gridData.GetTileAtCoordinates(vector2Int);
			tileAtCoordinates.HasBeenDestroyed = true;
			BoardGenVizInfo item = new BoardGenVizInfo(gridData, null, new List<Tile> { tileAtCoordinates }, isPulsingMoney: false, null, isPulsingGridNumber: false, basicGridGen: false, isPulsingPreviousWord: false, vizSteps[vizSteps.Count - 1].PlayerConsumableTiles);
			vizSteps.Add(item);
		}
		else if (challenge is UpAndUp)
		{
			int number = 15 - GameStatics.GetPlayer().CurrentRunProgress.GetRemainingEncounters();
			Vector2Int dimensions = gridData.GetDimensions();
			Tile tileAtCoordinates2 = gridData.GetTileAtCoordinates(new Vector2Int(dimensions.x / 2, dimensions.y / 2));
			tileAtCoordinates2.SetNumber(number);
			tileAtCoordinates2.IsNumberGoUpMiddleTile = true;
			List<Tile> lettersOnGridToPulse = new List<Tile> { tileAtCoordinates2 };
			BoardGenVizInfo item2 = new BoardGenVizInfo(gridData, null, lettersOnGridToPulse, isPulsingMoney: false, null, isPulsingGridNumber: false, basicGridGen: false, isPulsingPreviousWord: false, vizSteps[vizSteps.Count - 1].PlayerConsumableTiles);
			vizSteps.Add(item2);
		}
		return gridData;
	}

	private List<Tile> GetSicilianDefenseThreatSquares(GridData gridData, TileSelectionManager tileSelectionManager, List<Item> inventory, Tile kingTile, bool hasHungrySnake, bool allowFriendlyCapture)
	{
		List<Tile> list = new List<Tile>();
		foreach (Tile item in from t in gridData.GetTiles()
			where t.GetGlyphType() == GlyphType.Chess && t.IsWhitePiece != kingTile.IsWhitePiece
			select t)
		{
			GridData gridData2 = new GridData();
			gridData2.SetDimensions(gridData.GetDimensions());
			gridData2.GridTiles = (Tile[])gridData.GridTiles.Clone();
			Tile tile = new Tile();
			tile.SetGlyphType(GlyphType.Blank);
			tile.SetCoordinates(kingTile.Coordinates);
			gridData2.GridTiles[Array.IndexOf(gridData2.GridTiles, kingTile)] = tile;
			List<TileSelection> knightMoves = ChessPieces.GetKnightMoves(gridData2, tileSelectionManager, item, isCheckingAgainstKing: false, hasHungrySnake, allowFriendlyCapture);
			list.AddRange(knightMoves.Select((TileSelection move) => move.SelectedTile));
		}
		return list;
	}

	public List<TileSelection> GetValidNextTiles(GridData gridData, List<Tile> currentTiles, TileSelectionManager tileSelectionManager = null, bool noInventory = false)
	{
		if (currentTiles.Count == 0)
		{
			return new List<TileSelection>();
		}
		Player player = GameStatics.GetPlayer();
		List<Item> list = (noInventory ? new List<Item>() : player.GetAllItems());
		Item item2 = list.Find((Item item) => item is RandomAccessMemory);
		Item item3 = list.Find((Item item) => item is Snapshot);
		List<Item> list2 = list.Where((Item item) => item is Frankenstein).ToList();
		if (item2 != null)
		{
			RandomAccessMemory randomAccessMemory = item2 as RandomAccessMemory;
			list.AddRange(randomAccessMemory.ItemsInMemory);
		}
		if (item3 != null)
		{
			Snapshot snapshot = item3 as Snapshot;
			if (snapshot.SnapshottedItem != null)
			{
				list.Add(snapshot.SnapshottedItem);
			}
		}
		foreach (Item item5 in list2)
		{
			Frankenstein frankenstein = item5 as Frankenstein;
			list.AddRange(frankenstein.StitchedItems);
		}
		list.AddRange(from tile in currentTiles
			where tile.GetGlyphType() == GlyphType.ScatteredItem
			select tile.ScatteredItem);
		List<TileSelection> validTileSelections = new List<TileSelection>();
		Tile currentTile = currentTiles[currentTiles.Count - 1];
		if (currentTile.GetTileType() == TileType.White)
		{
			validTileSelections.AddRange(from tile in gridData.GetAvailableTiles()
				select new TileSelection(tile, TileSelectionMethod.Portal, tile.IsDisplayingAsVariableLetter(tileSelectionManager)) into tile
				where !currentTiles.Contains(tile.SelectedTile)
				select tile);
		}
		if (list.Exists((Item item) => item is FullMoon))
		{
			validTileSelections.AddRange(from tile in gridData.GetAvailableTiles()
				where tile.GetStringRepresentation() == currentTile.GetStringRepresentation() && tile.GetGlyphType() == currentTile.GetGlyphType()
				select new TileSelection(tile, TileSelectionMethod.FullMoon, tile.IsDisplayingAsVariableLetter(tileSelectionManager)) into tile
				where !currentTiles.Contains(tile.SelectedTile)
				select tile);
		}
		if (!noInventory && player.CurrentRunProgress.Challenge is SicilianDefense)
		{
			bool hasHungrySnake = list.Exists((Item item) => item is HungrySnake);
			bool allowFriendlyCapture = list.Exists((Item item) => item is KingOfTheBridge);
			List<TileSelection> source = ChessPieces.GetKnightMoves(gridData, tileSelectionManager, currentTile, isCheckingAgainstKing: false, hasHungrySnake, allowFriendlyCapture);
			if (currentTile.PieceType == ChessPiece.King && currentTile.GetGlyphType() == GlyphType.Chess)
			{
				List<Tile> threatSquares = GetSicilianDefenseThreatSquares(gridData, tileSelectionManager, list, currentTile, hasHungrySnake, allowFriendlyCapture: true);
				source = source.Where((TileSelection move) => !threatSquares.Contains(move.SelectedTile)).ToList();
			}
			validTileSelections.AddRange(source.Where((TileSelection move) => !currentTiles.Contains(move.SelectedTile)));
			foreach (TileSelection item6 in validTileSelections)
			{
				if (item6.SelectedTile.GetGlyphType() == GlyphType.Chess && currentTile.GetGlyphType() == GlyphType.Chess && (currentTile.IsWhitePiece != item6.SelectedTile.IsWhitePiece || list.Exists((Item item) => item is KingOfTheBridge)))
				{
					item6.SelectionMethod = TileSelectionMethod.ChessTake;
				}
				else if (item6.SelectionMethod == TileSelectionMethod.ChessTake && currentTile.GetGlyphType() == GlyphType.Chess && currentTile.PieceType == ChessPiece.Knight)
				{
					item6.SelectionMethod = TileSelectionMethod.ChessMove;
				}
				else if (item6.SelectionMethod == TileSelectionMethod.ChessTake || item6.SelectionMethod == TileSelectionMethod.ChessMove)
				{
					item6.SelectionMethod = TileSelectionMethod.KnightTimeMove;
				}
			}
			if (list.Exists((Item item) => item is Television) && currentTile.GetGlyphType() == GlyphType.Chess && (currentTile.PieceType == ChessPiece.King || currentTile.PieceType == ChessPiece.Pawn))
			{
				Debug.Log("Adding television moves");
				foreach (Tile tile2 in from t in gridData.GetAvailableTiles()
					where t.GetGlyphType() == GlyphType.ScatteredItem
					select t)
				{
					if (!validTileSelections.Exists((TileSelection selection) => selection.SelectedTile == tile2))
					{
						TileSelection item4 = new TileSelection(tile2, TileSelectionMethod.Television, tile2.IsDisplayingAsVariableLetter(tileSelectionManager));
						validTileSelections.Add(item4);
					}
				}
			}
			return validTileSelections;
		}
		if (currentTile.GetGlyphType() == GlyphType.Chess)
		{
			validTileSelections.AddRange(from chessTile in ChessPieces.GetValidChessMoves(gridData, list, currentTile)
				where !validTileSelections.Exists((TileSelection tile) => tile.SelectedTile == chessTile.SelectedTile)
				select chessTile into tile
				where !currentTiles.Contains(tile.SelectedTile)
				select tile);
			foreach (TileSelection item7 in validTileSelections)
			{
				if (item7.SelectedTile.GetGlyphType() == GlyphType.Chess && (currentTile.IsWhitePiece != item7.SelectedTile.IsWhitePiece || list.Exists((Item item) => item is KingOfTheBridge)))
				{
					item7.SelectionMethod = TileSelectionMethod.ChessTake;
				}
			}
			return validTileSelections;
		}
		if (currentTile.GetGlyphType() == GlyphType.Arrow)
		{
			validTileSelections.AddRange(from arrowTile in Arrows.GetTilesPointedAt(currentTile.GetStringRepresentation(forWordValidity: true), currentTile.GetCoordinates(), gridData)
				where !validTileSelections.Exists((TileSelection tile) => tile.SelectedTile == arrowTile)
				where !currentTiles.Contains(arrowTile)
				select new TileSelection(arrowTile, TileSelectionMethod.Arrow, arrowTile.IsDisplayingAsVariableLetter(tileSelectionManager)));
			return validTileSelections;
		}
		Vector2Int coordinates = currentTile.GetCoordinates();
		validTileSelections.AddRange(from adjTile in GetTilesAdjacentToCoordinates(gridData, coordinates, list.Exists((Item item) => item is HungrySnake))
			where !validTileSelections.Exists((TileSelection tile) => tile.SelectedTile == adjTile)
			where !currentTiles.Contains(adjTile)
			select new TileSelection(adjTile, TileSelectionMethod.Adjacent, adjTile.IsDisplayingAsVariableLetter(tileSelectionManager)));
		return validTileSelections;
	}

	public bool AreAdjacentTiles(Tile tile1, Tile tile2)
	{
		Vector2Int coordinates = tile1.GetCoordinates();
		Vector2Int coordinates2 = tile2.GetCoordinates();
		if (Math.Abs(coordinates.x - coordinates2.x) <= 1 && Math.Abs(coordinates.y - coordinates2.y) <= 1)
		{
			return !(coordinates == coordinates2);
		}
		return false;
	}

	public List<Tile> GetTilesAdjacentToCoordinates(GridData gridData, Vector2Int coordinates, bool isForcingWrapping)
	{
		bool flag = isForcingWrapping || GameStatics.GetPlayer().GetUnpackedItemsOfType(typeof(HungrySnake)).Count > 0;
		HashSet<Tile> hashSet = new HashSet<Tile>();
		for (int i = -1; i <= 1; i++)
		{
			for (int j = -1; j <= 1; j++)
			{
				if (i == 0 && j == 0)
				{
					continue;
				}
				int x = coordinates.x + i;
				int y = coordinates.y + j;
				if (gridData.IsValidCoordinate(x, y))
				{
					Tile tileAtCoordinates = gridData.GetTileAtCoordinates(x, y);
					if (tileAtCoordinates != null && !tileAtCoordinates.IsInTheVoid && !tileAtCoordinates.HasBeenDestroyed)
					{
						hashSet.Add(tileAtCoordinates);
					}
				}
			}
		}
		if (flag)
		{
			if (coordinates.x == 0)
			{
				int x2 = gridData.GetDimensions().x - 1;
				for (int k = -1; k < 2; k++)
				{
					if (gridData.IsValidCoordinate(x2, coordinates.y + k))
					{
						Tile tileAtCoordinates2 = gridData.GetTileAtCoordinates(x2, coordinates.y + k);
						if (tileAtCoordinates2 != null)
						{
							hashSet.Add(tileAtCoordinates2);
						}
					}
				}
			}
			else if (coordinates.x == gridData.GetDimensions().x - 1)
			{
				int x3 = 0;
				for (int l = -1; l < 2; l++)
				{
					if (gridData.IsValidCoordinate(x3, coordinates.y + l))
					{
						Tile tileAtCoordinates3 = gridData.GetTileAtCoordinates(x3, coordinates.y + l);
						if (tileAtCoordinates3 != null)
						{
							hashSet.Add(tileAtCoordinates3);
						}
					}
				}
			}
		}
		return hashSet.ToList();
	}

	public bool IsCornerTile(Tile tile, GridData gridData)
	{
		Vector2Int coordinates = tile.GetCoordinates();
		Vector2Int dimensions = gridData.GetDimensions();
		int num = dimensions.x - 1;
		int num2 = dimensions.y - 1;
		if (coordinates.x == 0 || coordinates.x == num)
		{
			if (coordinates.y != 0)
			{
				return coordinates.y == num2;
			}
			return true;
		}
		return false;
	}

	public bool IsEdgeTile(Tile tile, GridData gridData)
	{
		Vector2Int coordinates = tile.GetCoordinates();
		Vector2Int dimensions = gridData.GetDimensions();
		int num = dimensions.x - 1;
		int num2 = dimensions.y - 1;
		if (coordinates.x != 0 && coordinates.x != num && coordinates.y != 0)
		{
			return coordinates.y == num2;
		}
		return true;
	}

	public Tile GetTileForItemScatter(GridData gridData, TileType tileType, GlyphType glyphType, List<Tile> whitelistedTiles = null, bool isSuited = false)
	{
		if (whitelistedTiles != null && whitelistedTiles.Count < 1)
		{
			return null;
		}
		List<Tile> list = ((whitelistedTiles == null) ? gridData.GetAvailableTiles() : whitelistedTiles);
		if (GameStatics.GetPlayer().CurrentRunProgress.Challenge is UpAndUp && glyphType != GlyphType.None)
		{
			Vector2Int dimensions = gridData.GetDimensions();
			list = list.Where((Tile tile) => tile.GetCoordinates() != new Vector2Int(dimensions.x / 2, dimensions.y / 2)).ToList();
		}
		if (list.Count == 0)
		{
			return null;
		}
		bool num = GameStatics.GetPlayer().GetUnpackedItemsOfType(typeof(Saxophone)).Count > 0;
		List<TileType> list2 = new List<TileType>();
		if (num)
		{
			foreach (Item item in GameStatics.GetPlayer().GetUnpackedItemsOfType(typeof(Saxophone)))
			{
				list2.AddRange(item.RelevantColours);
			}
		}
		bool flag = list2.Contains(tileType) || (list2.Contains(TileType.Red) && tileType == TileType.Purple) || (list2.Contains(TileType.Blue) && tileType == TileType.Purple);
		TileType relevantColour = TileType.Blue;
		if (flag)
		{
			if (list2.Contains(tileType))
			{
				relevantColour = tileType;
			}
			else if (list2.Contains(TileType.Blue))
			{
				relevantColour = TileType.Blue;
			}
			else
			{
				relevantColour = TileType.Red;
			}
		}
		List<Tile> list3 = (from tile in gridData.GetAvailableTiles()
			where tile.IsTileType(relevantColour)
			select tile).ToList();
		List<Tile> adjacentToBlueTiles = new List<Tile>();
		foreach (Tile item2 in list3)
		{
			List<Tile> collection = (from tile in GetTilesAdjacentToCoordinates(gridData, item2.GetCoordinates(), isForcingWrapping: false)
				where tile.IsTileType(TileType.Normal)
				select tile).ToList();
			adjacentToBlueTiles.AddRange(collection);
		}
		bool flag2 = (glyphType == GlyphType.Number || glyphType == GlyphType.Fraction) && GameStatics.GetPlayer().GetUnpackedItemsOfType(typeof(Magnet)).Count > 0;
		List<Tile> list4 = (from tile in gridData.GetAvailableTiles()
			where tile.GetGlyphType() == GlyphType.Number || tile.GetGlyphType() == GlyphType.Fraction
			select tile).ToList();
		List<Tile> adjacentToNumberTiles = new List<Tile>();
		foreach (Tile item3 in list4)
		{
			List<Tile> collection2 = (from tile in GetTilesAdjacentToCoordinates(gridData, item3.GetCoordinates(), isForcingWrapping: false)
				where tile.GetGlyphType() == GlyphType.Letter
				select tile).ToList();
			adjacentToNumberTiles.AddRange(collection2);
		}
		if (tileType != 0 && glyphType != GlyphType.None && isSuited)
		{
			List<Tile> list5 = list.Where((Tile tile) => tile.GetGlyphType() == GlyphType.Letter && tile.IsTileType(TileType.Normal) && tile.GetSuit() == Suit.None).ToList();
			if (flag && flag2)
			{
				List<Tile> list6 = (from tile in list5
					where adjacentToBlueTiles.Contains(tile)
					where adjacentToNumberTiles.Contains(tile)
					select tile).ToList();
				if (list6.Count > 0)
				{
					return list6[UnityEngine.Random.Range(0, list6.Count)];
				}
			}
			if (flag2)
			{
				List<Tile> list7 = list5.Where((Tile tile) => adjacentToNumberTiles.Contains(tile)).ToList();
				if (list7.Count > 0)
				{
					return list7[UnityEngine.Random.Range(0, list7.Count)];
				}
			}
			if (flag)
			{
				List<Tile> list8 = list5.Where((Tile tile) => adjacentToBlueTiles.Contains(tile)).ToList();
				if (list8.Count > 0)
				{
					return list8[UnityEngine.Random.Range(0, list8.Count)];
				}
			}
			if (list5.Count > 0)
			{
				return list5[UnityEngine.Random.Range(0, list5.Count)];
			}
		}
		if (tileType != 0 && glyphType != GlyphType.None)
		{
			List<Tile> list9 = list.Where((Tile tile) => tile.GetGlyphType() == GlyphType.Letter && tile.IsTileType(TileType.Normal)).ToList();
			if (flag && flag2)
			{
				List<Tile> list10 = (from tile in list9
					where adjacentToBlueTiles.Contains(tile)
					where adjacentToNumberTiles.Contains(tile)
					select tile).ToList();
				if (list10.Count > 0)
				{
					return list10[UnityEngine.Random.Range(0, list10.Count)];
				}
			}
			if (flag2)
			{
				List<Tile> list11 = list9.Where((Tile tile) => adjacentToNumberTiles.Contains(tile)).ToList();
				if (list11.Count > 0)
				{
					return list11[UnityEngine.Random.Range(0, list11.Count)];
				}
			}
			if (flag)
			{
				List<Tile> list12 = list9.Where((Tile tile) => adjacentToBlueTiles.Contains(tile)).ToList();
				if (list12.Count > 0)
				{
					return list12[UnityEngine.Random.Range(0, list12.Count)];
				}
			}
			if (list9.Count > 0)
			{
				return list9[UnityEngine.Random.Range(0, list9.Count)];
			}
		}
		if (glyphType != GlyphType.None && isSuited)
		{
			List<Tile> list13 = list.Where((Tile tile) => tile.GetGlyphType() == GlyphType.Letter && tile.GetSuit() == Suit.None).ToList();
			if (flag2)
			{
				List<Tile> list14 = list13.Where((Tile tile) => adjacentToNumberTiles.Contains(tile)).ToList();
				if (list14.Count > 0)
				{
					return list14[UnityEngine.Random.Range(0, list14.Count)];
				}
			}
			if (list13.Count > 0)
			{
				return list13[UnityEngine.Random.Range(0, list13.Count)];
			}
		}
		if (tileType != TileType.Normal && isSuited)
		{
			List<Tile> list15 = list.Where((Tile tile) => tile.IsTileType(TileType.Normal) && tile.GetSuit() == Suit.None).ToList();
			if (flag)
			{
				List<Tile> list16 = list15.Where((Tile tile) => adjacentToBlueTiles.Contains(tile)).ToList();
				if (list16.Count > 0)
				{
					return list16[UnityEngine.Random.Range(0, list16.Count)];
				}
			}
			if (list15.Count > 0)
			{
				return list15[UnityEngine.Random.Range(0, list15.Count)];
			}
		}
		if (glyphType != GlyphType.None)
		{
			List<Tile> list17 = list.Where((Tile tile) => tile.GetGlyphType() == GlyphType.Letter).ToList();
			if (flag2)
			{
				List<Tile> list18 = list17.Where((Tile tile) => adjacentToNumberTiles.Contains(tile)).ToList();
				if (list18.Count > 0)
				{
					return list18[UnityEngine.Random.Range(0, list18.Count)];
				}
			}
			if (list17.Count > 0)
			{
				return list17[UnityEngine.Random.Range(0, list17.Count)];
			}
		}
		if (tileType != 0)
		{
			List<Tile> list19 = list.Where((Tile tile) => tile.IsTileType(TileType.Normal)).ToList();
			if (flag)
			{
				List<Tile> list20 = list19.Where((Tile tile) => adjacentToBlueTiles.Contains(tile)).ToList();
				if (list20.Count > 0)
				{
					return list20[UnityEngine.Random.Range(0, list20.Count)];
				}
			}
			if (list19.Count > 0)
			{
				return list19[UnityEngine.Random.Range(0, list19.Count)];
			}
		}
		if (isSuited)
		{
			List<Tile> list21 = list.Where((Tile tile) => tile.GetSuit() == Suit.None).ToList();
			if (list21.Count > 0)
			{
				return list21[UnityEngine.Random.Range(0, list21.Count)];
			}
		}
		if (tileType != 0 && glyphType == GlyphType.None)
		{
			List<Tile> list22 = list.Where((Tile tile) => tile.GetTileType() != tileType).ToList();
			if (flag)
			{
				List<Tile> list23 = list22.Where((Tile tile) => adjacentToBlueTiles.Contains(tile)).ToList();
				if (list23.Count > 0)
				{
					return list23[UnityEngine.Random.Range(0, list23.Count)];
				}
			}
			if (list22.Count > 0)
			{
				return list22[UnityEngine.Random.Range(0, list22.Count)];
			}
		}
		return list[UnityEngine.Random.Range(0, list.Count)];
	}

	public bool Contains2x2Grid(GridData gridData, List<Tile> tiles)
	{
		Vector2Int dimensions = gridData.GetDimensions();
		for (int i = 0; i < dimensions.x - 1; i++)
		{
			for (int j = 0; j < dimensions.y - 1; j++)
			{
				Vector2Int coords1 = new Vector2Int(i, j);
				Vector2Int coords2 = new Vector2Int(i + 1, j);
				Vector2Int coords3 = new Vector2Int(i, j + 1);
				Vector2Int coords4 = new Vector2Int(i + 1, j + 1);
				if (tiles.Exists((Tile tiles) => tiles.GetCoordinates() == coords1) && tiles.Exists((Tile tiles) => tiles.GetCoordinates() == coords2) && tiles.Exists((Tile tiles) => tiles.GetCoordinates() == coords3) && tiles.Exists((Tile tiles) => tiles.GetCoordinates() == coords4))
				{
					return true;
				}
			}
		}
		return false;
	}

	public List<Vector2Int> GeneratePathThroughGrid(GridData gridData)
	{
		List<Tile> tilePath = new List<Tile>();
		List<Vector2Int> list = new List<Vector2Int>();
		List<Tile> list2 = gridData.GetTiles().ToList();
		for (int i = 0; i < 25; i++)
		{
			if (i == 0)
			{
				Tile tile = list2[UnityEngine.Random.Range(0, list2.Count)];
				list.Add(tile.GetCoordinates());
				tilePath.Add(tile);
				list2.Remove(tile);
				continue;
			}
			List<Tile> list3 = new List<Tile>();
			foreach (Tile item in new List<Tile>(tilePath))
			{
				list3.AddRange(GetTilesAdjacentToCoordinates(gridData, item.GetCoordinates(), isForcingWrapping: false));
			}
			list3 = list3.Where((Tile adjTile) => !tilePath.Contains(adjTile)).Distinct().ToList();
			Debug.Log($"Adjacent tiles count: {list3.Count}");
			Tile tile2 = list3[UnityEngine.Random.Range(0, list3.Count)];
			list.Add(tile2.GetCoordinates());
			tilePath.Add(tile2);
			list2.Remove(tile2);
		}
		return list;
	}
}
