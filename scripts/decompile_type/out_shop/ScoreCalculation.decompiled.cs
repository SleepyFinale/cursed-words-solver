using System;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;

public static class ScoreCalculation
{
	public static int ShinyBonus = 50;

	public static ScorePacket GetBasicValueScore(List<TileSelection> tiles)
	{
		ScorePacket result = new ScorePacket(0L);
		foreach (TileSelection tile in tiles)
		{
			result += tile.SelectedTile.GetValue();
		}
		return result;
	}

	public static ScoreCalcVizInfo GetInitialScoreInfo(List<TileSelection> tiles)
	{
		ScoreCalcVizInfo scoreCalcVizInfo = new ScoreCalcVizInfo();
		scoreCalcVizInfo.PlayerConsumableTiles = new Tile[10];
		Array.Copy(GameStatics.GetPlayer().ConsumableTiles, scoreCalcVizInfo.PlayerConsumableTiles, 10);
		scoreCalcVizInfo.Money = GameStatics.GetPlayer().Money;
		foreach (TileSelection tile in tiles)
		{
			scoreCalcVizInfo.TileScores.Add(tile.SelectedTile.GetValue());
			scoreCalcVizInfo.TileScoreMultipliers.Add(null);
			scoreCalcVizInfo.TileScoreMultiplierFloats.Add(null);
		}
		return scoreCalcVizInfo;
	}

	public static List<ScoreCalcVizInfo> CalculateOverallScore(List<TileSelection> tileSelections, List<string> words, List<Item> items, List<HistoricWord> previousWords, List<BossModifier> bossModifiers, GridData grid, int GridNumber)
	{
		List<ScoreCalcVizInfo> list = new List<ScoreCalcVizInfo>();
		Player player = GameStatics.GetPlayer();
		bool flag = GameStatics.GetPlayer().GetUnpackedItemsOfType(typeof(Hourglass)).Count % 2 == 1;
		if (tileSelections.Exists((TileSelection selection) => selection.SelectedTile.IsTileType(TileType.Glitch)))
		{
			list.Add(SettleGlitchTiles(tileSelections));
		}
		list.Add(GetInitialScoreInfo(tileSelections));
		if (!flag)
		{
			foreach (BossModifier bossModifier in bossModifiers)
			{
				list.Add(ApplyBossModifier(tileSelections, list, bossModifier));
			}
		}
		if (player.CurrentRunProgress.Challenge is TheBonesRound && tileSelections.Exists((TileSelection tile) => tile.SelectedTile.GetSuit() != Suit.None))
		{
			list.Add(CalculatePokerHand(tileSelections, list, inWord: true));
		}
		if (tileSelections.Exists((TileSelection tile) => tile.SelectedTile.GetGlyphType() == GlyphType.Currency))
		{
			list.Add(GetMoneyFromCurrencyTiles(tileSelections, list));
		}
		if (tileSelections.Exists((TileSelection tile) => tile.SelectedTile.GetTileType() == TileType.Pink))
		{
			list.Add(StoreMoneyInPinkTiles(tileSelections, list));
		}
		List<Item> list2 = new List<Item>(items);
		if (flag)
		{
			list2.Reverse();
		}
		foreach (Item item3 in list2)
		{
			if (item3 is RandomAccessMemory)
			{
				RandomAccessMemory randomAccessMemory = item3 as RandomAccessMemory;
				foreach (Item item4 in randomAccessMemory.ItemsInMemory)
				{
					ScoreCalcVizInfo scoreCalcVizInfo = item4.ApplyItemToScore(list, words, GridNumber, tileSelections, previousWords, grid);
					if (scoreCalcVizInfo.RelevantItem != null)
					{
						scoreCalcVizInfo.RelevantItem = randomAccessMemory;
					}
					list.Add(scoreCalcVizInfo);
				}
				continue;
			}
			if (item3 is Frankenstein)
			{
				Frankenstein frankenstein = item3 as Frankenstein;
				foreach (Item stitchedItem in frankenstein.StitchedItems)
				{
					ScoreCalcVizInfo scoreCalcVizInfo2 = stitchedItem.ApplyItemToScore(list, words, GridNumber, tileSelections, previousWords, grid);
					if (scoreCalcVizInfo2.RelevantItem != null)
					{
						scoreCalcVizInfo2.RelevantItem = frankenstein;
					}
					list.Add(scoreCalcVizInfo2);
				}
				continue;
			}
			list.Add(item3.ApplyItemToScore(list, words, GridNumber, tileSelections, previousWords, grid));
			if (player.IsHumanBoyFavouriteStamp(item3) && player.GetCharacter().GetCharacterItem().UpgradeableComponents[1].VariableValue > 1)
			{
				for (int i = 0; i < player.GetCharacter().GetCharacterItem().UpgradeableComponents[1].VariableValue - 1; i++)
				{
					list.Add(item3.ApplyItemToScore(list, words, GridNumber, tileSelections, previousWords, grid));
				}
			}
			Item item2 = player.GetStickers().Find((Item item) => item is Overhand);
			if (player.IsOverhandTarget(item3) && item2 != null)
			{
				for (int j = 0; j < item2.UpgradeableComponents[0].VariableValue; j++)
				{
					list.Add(item3.ApplyItemToScore(list, words, GridNumber, tileSelections, previousWords, grid));
				}
			}
		}
		if (flag)
		{
			List<BossModifier> list3 = new List<BossModifier>(bossModifiers);
			list3.Reverse();
			foreach (BossModifier item5 in list3)
			{
				list.Add(ApplyBossModifier(tileSelections, list, item5));
			}
		}
		if (player.CurrentRunProgress.Challenge is Lexographer)
		{
			list.Add(ApplyLexographer(tileSelections, list));
		}
		return ApplyPoisonEffect(previousWords, list);
	}

	public static ScoreCalcVizInfo ApplyBossModifier(List<TileSelection> tiles, List<ScoreCalcVizInfo> infoSteps, BossModifier bossModifier)
	{
		ScoreCalcVizInfo nextStep = GetNextStep(infoSteps);
		Player player = GameStatics.GetPlayer();
		if (bossModifier is ReducedLetterValue)
		{
			for (int i = 0; i < tiles.Count; i++)
			{
				nextStep.TileScores[i] -= (long)bossModifier.FloorAdjustedModification;
			}
			nextStep.IsPulsingWholeWord = true;
			nextStep.BossModifierToPulse = typeof(ReducedLetterValue);
		}
		if (bossModifier is StealsMoney && nextStep.Money > 0)
		{
			int num = ((nextStep.Money >= bossModifier.FloorAdjustedModification) ? bossModifier.FloorAdjustedModification : nextStep.Money);
			nextStep.Money -= bossModifier.FloorAdjustedModification;
			nextStep.Money = Mathf.Max(nextStep.Money, 0);
			nextStep.IsPulsingMoney = true;
			nextStep.IsPulsingWholeWord = true;
			nextStep.BossModifierToPulse = typeof(StealsMoney);
			if (nextStep.EarningsBreakdown.ContainsKey("Stolen by Boss"))
			{
				nextStep.EarningsBreakdown["Stolen by Boss"] -= num;
			}
			else
			{
				nextStep.EarningsBreakdown["Stolen by Boss"] = -num;
			}
		}
		if (bossModifier is NegativeMoney && player.Money > 0)
		{
			nextStep.IsPulsingWholeWord = true;
			nextStep.BossModifierToPulse = typeof(NegativeMoney);
			nextStep.IsPulsingMoney = true;
			nextStep.WordBonus = new WordBonusToken(-bossModifier.FloorAdjustedModification * nextStep.Money, isMultiplicative: false);
		}
		return nextStep;
	}

	public static ScoreCalcVizInfo ApplyLexographer(List<TileSelection> tiles, List<ScoreCalcVizInfo> infoSteps)
	{
		ScoreCalcVizInfo nextStep = GetNextStep(infoSteps);
		for (int i = 0; i < tiles.Count; i++)
		{
			if (tiles[i].IsCursed())
			{
				nextStep.TileScores[i] = new ScorePacket(0L);
				nextStep.TileScoreMultipliers[i] = 0;
			}
		}
		return nextStep;
	}

	public static ScoreCalcVizInfo CalculatePokerHand(List<TileSelection> tiles, List<ScoreCalcVizInfo> infoSteps, bool inWord)
	{
		ScoreCalcVizInfo nextStep = GetNextStep(infoSteps);
		List<Tile> list = (from tile in tiles
			select tile.SelectedTile into tile
			where tile.GetSuit() != Suit.None
			select tile).ToList();
		if (list.Count == 0)
		{
			return nextStep;
		}
		PokerHand pokerHand;
		List<Tile> pokerHandFromTiles = PokerHands.GetPokerHandFromTiles(list, out pokerHand);
		if (inWord)
		{
			nextStep.LettersInWordToPulse.AddRange(pokerHandFromTiles);
		}
		nextStep.LettersOnGridToPulse.AddRange(pokerHandFromTiles);
		nextStep.PokerHand = pokerHand;
		nextStep.PokerHandTiles = pokerHandFromTiles;
		nextStep.WordBonus = new WordBonusToken(PokerHands.PokerHandPointValues[pokerHand], isMultiplicative: false);
		return nextStep;
	}

	public static ScoreCalcVizInfo GetMoneyFromCurrencyTiles(List<TileSelection> tiles, List<ScoreCalcVizInfo> infoSteps)
	{
		ScoreCalcVizInfo nextStep = GetNextStep(infoSteps);
		List<Tile> list = (from tile in tiles
			select tile.SelectedTile into tile
			where tile.GetGlyphType() == GlyphType.Currency
			select tile).ToList();
		if (list.Count == 0)
		{
			return nextStep;
		}
		bool flag = GameStatics.GetPlayer().GetUnpackedItemsOfType(typeof(KokeshiDolls)).Count > 0;
		nextStep.LettersInWordToPulse.AddRange(list);
		nextStep.IsPulsingMoney = true;
		foreach (Tile item in list)
		{
			int num = 1;
			if (flag)
			{
				num = Vocabulary.ActiveLanguageVocabulary.LanguageAlphabet.GetUnchangedLetterValue(Currency.GetLetterFromCurrency(item.GetStringRepresentation(forWordValidity: true)));
			}
			nextStep.Money += num;
			if (!nextStep.EarningsBreakdown.ContainsKey("Currency tiles"))
			{
				nextStep.EarningsBreakdown["Currency tiles"] = num;
			}
			else
			{
				nextStep.EarningsBreakdown["Currency tiles"] += num;
			}
		}
		return nextStep;
	}

	public static ScoreCalcVizInfo SettleGlitchTiles(List<TileSelection> tiles)
	{
		ScoreCalcVizInfo scoreCalcVizInfo = new ScoreCalcVizInfo();
		List<Tile> list = (from tile in tiles
			select tile.SelectedTile into tile
			where tile.IsTileType(TileType.Glitch)
			select tile).ToList();
		foreach (Tile item in list)
		{
			List<TileType> list2 = new List<TileType>
			{
				TileType.Normal,
				TileType.Blue,
				TileType.Cactus,
				TileType.Gold,
				TileType.Green,
				TileType.Purple,
				TileType.Pink,
				TileType.White,
				TileType.Red,
				TileType.Void,
				TileType.Shiny
			};
			TileType tileType = list2[UnityEngine.Random.Range(0, list2.Count)];
			bool num = UnityEngine.Random.Range(0, 4) < 1;
			int num2 = UnityEngine.Random.Range(0, 8);
			item.SetTileType(tileType);
			if (num)
			{
				item.SetSuit(PlayingCardUtility.GetRandomCardSuit());
			}
			switch (num2)
			{
			case 0:
				item.SetToRandomLetter();
				break;
			case 1:
				item.SetToRandomCurrency();
				break;
			case 2:
				item.SetToRandomFraction();
				break;
			case 3:
				item.SetToRandomNumber();
				break;
			case 4:
				item.SetGlyphType(GlyphType.Blank);
				break;
			case 5:
				item.SetToRandomItem();
				break;
			case 6:
				item.SetToRandomChessPiece();
				break;
			case 7:
				item.SetGlyphType(GlyphType.BespokeCard);
				item.SetSuit(Suit.Joker);
				break;
			}
			item.WasGlitchTile = true;
		}
		scoreCalcVizInfo.IsSettlingGlitchTiles = true;
		scoreCalcVizInfo.TilesToRepopulate = list;
		scoreCalcVizInfo.WordTileSelections = tiles;
		return scoreCalcVizInfo;
	}

	public static ScoreCalcVizInfo StoreMoneyInPinkTiles(List<TileSelection> tiles, List<ScoreCalcVizInfo> infoSteps)
	{
		ScoreCalcVizInfo nextStep = GetNextStep(infoSteps);
		List<Tile> list = (from tile in tiles
			select tile.SelectedTile into tile
			where tile.GetTileType() == TileType.Pink
			select tile).ToList();
		if (list.Count == 0)
		{
			return nextStep;
		}
		nextStep.LettersInWordToPulse.AddRange(list);
		nextStep.LettersOnGridToPulse.AddRange(list);
		nextStep.IsPulsingMoney = true;
		int num = 0;
		foreach (Tile item in list)
		{
			_ = item;
			if (nextStep.Money > 0)
			{
				nextStep.Money--;
				num++;
			}
		}
		nextStep.EarningsBreakdown["Saved in Piggy Bank"] = -num;
		SaveManager.SaveMoneyInPiggyBank(num);
		return nextStep;
	}

	public static List<ScoreCalcVizInfo> ApplyPoisonEffect(List<HistoricWord> previousWords, List<ScoreCalcVizInfo> infoSteps)
	{
		foreach (HistoricWord previousWord in previousWords)
		{
			int num = previousWord.Tiles.Count((Tile tile) => tile.IsTileType(TileType.Green));
			if (num > 0)
			{
				ScoreCalcVizInfo nextStep = GetNextStep(infoSteps);
				Debug.Log("Calculating poison damage");
				Debug.Log("Historic word score packet: " + StringSerializer.Serialize(typeof(ScorePacket), previousWord.Score));
				ScorePacket scorePacket = num * previousWord.Score.Scale(0.1f);
				Debug.Log("Poison damage: " + StringSerializer.Serialize(typeof(ScorePacket), scorePacket));
				nextStep.WordBonus = new WordBonusToken(scorePacket, isMultiplicative: false, isPoison: true);
				infoSteps.Add(nextStep);
			}
		}
		return infoSteps;
	}

	public static ScorePacket GetScoreFromScoreCalcInfo(List<ScoreCalcVizInfo> steps)
	{
		if (steps.Count == 0)
		{
			return new ScorePacket(0L);
		}
		ScorePacket scorePacket = steps[steps.Count - 1].TileScores.Sum();
		foreach (ScoreCalcVizInfo step in steps)
		{
			if (step.WordBonus == null)
			{
				continue;
			}
			if (step.WordBonus is ConditionalWordBonusToken)
			{
				ConditionalWordBonusToken conditionalWordBonusToken = step.WordBonus as ConditionalWordBonusToken;
				if ((conditionalWordBonusToken.Condition == WordBonusCondition.WordScoreZero && scorePacket != new ScorePacket(0L)) || (conditionalWordBonusToken.Condition == WordBonusCondition.WordScoreNegative && scorePacket >= new ScorePacket(0L)))
				{
					continue;
				}
			}
			if (step.WordBonus.IsMultiplicative)
			{
				scorePacket *= step.WordBonus.Bonus;
				scorePacket /= 100L;
			}
			else
			{
				scorePacket += step.WordBonus.Bonus;
			}
		}
		return scorePacket;
	}

	public static ScoreCalcVizInfo GetNextStep(List<ScoreCalcVizInfo> currentSteps)
	{
		return currentSteps[currentSteps.Count - 1].GetMatchingStep();
	}
}
