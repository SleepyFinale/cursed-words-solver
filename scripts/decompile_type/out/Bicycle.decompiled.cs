using System.Collections.Generic;
using UnityEngine;

public class Bicycle : Item
{
	public int WordScoreBonus;

	public Bicycle()
	{
		Name = "Bicycle";
		SpriteData.Add(new ItemSpriteData(ItemSpriteUsage.Default, "Bicycle"));
		Rarity = ItemRarity.Unique;
		UpgradeableComponents = new List<UpgradeableComponent>
		{
			new UpgradeableComponent(1, 2, 2),
			new UpgradeableComponent(1, 1, 1)
		};
		Tags = new List<ItemTag>
		{
			ItemTag.CardsBuild,
			ItemTag.CardsGenerator
		};
		PinColors = new List<Color>
		{
			new Color32(233, 56, 47, byte.MaxValue),
			new Color32(110, 119, 173, byte.MaxValue)
		};
		ItemFunctionTags = new List<ItemFunctionTag>
		{
			ItemFunctionTag.Scatterer,
			ItemFunctionTag.SpecificAdditive
		};
	}

	public override string GetDescription()
	{
		return string.Format("START OF GRID: Scatters {0}{1}{2} card{3}. Get +{4} WORD SCORE. Improved by {5}{6}{7} for each submitted card", GameStatics.ZeroWidthCharacter, UpgradeableComponents[0].VariableValue, GameStatics.ZeroWidthCharacter, Item.CheckPlural("s", UpgradeableComponents[0].VariableValue), WordScoreBonus, GameStatics.ZeroWidthCharacter, UpgradeableComponents[1].VariableValue, GameStatics.ZeroWidthCharacter);
	}

	public override GridData ApplyStartOfGridEffect(GridData gridData, int gridNumber, int numberOfGrids, List<HistoricWord> previousWords, List<BoardGenVizInfo> vizSteps, bool isReroll)
	{
		List<Tile> list = new List<Tile>();
		for (int i = 0; i < UpgradeableComponents[0].VariableValue; i++)
		{
			Tile tileForItemScatter = GridUtility.Singleton.GetTileForItemScatter(gridData, TileType.Normal, GlyphType.None, null, isSuited: true);
			if (tileForItemScatter != null)
			{
				tileForItemScatter.SetSuit(PlayingCardUtility.GetRandomCardSuit());
				list.Add(tileForItemScatter);
			}
		}
		if (list.Count > 0)
		{
			vizSteps.Add(new BoardGenVizInfo(gridData, this, list, isPulsingMoney: false, null, isPulsingGridNumber: false, basicGridGen: false, isPulsingPreviousWord: false, vizSteps[vizSteps.Count - 1].PlayerConsumableTiles));
		}
		return gridData;
	}

	public override void ApplyWordBonus(ScoreCalcVizInfo step, int gridNumber, List<Tile> tiles, List<string> words, List<TileSelection> selections, List<HistoricWord> previousWords, GridData gridData)
	{
		if (tiles.Count == 0)
		{
			return;
		}
		int num = 0;
		foreach (Tile tile in tiles)
		{
			if (tile.CardSuit != 0)
			{
				num += UpgradeableComponents[1].VariableValue;
			}
		}
		WordScoreBonus += num;
		if (WordScoreBonus > 0)
		{
			step.WordBonus = new WordBonusToken(WordScoreBonus, isMultiplicative: false);
		}
	}
}
