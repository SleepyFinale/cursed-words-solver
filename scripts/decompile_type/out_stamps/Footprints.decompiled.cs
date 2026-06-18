using System;
using System.Collections.Generic;
using System.Linq;

public class Footprints : Item
{
	public Footprints()
	{
		Name = "Footprints";
		SpriteData.Add(new ItemSpriteData(ItemSpriteUsage.Default, "Footprints"));
		Rarity = ItemRarity.Common;
		Cost = 11;
		UpgradeableComponents = new List<UpgradeableComponent>
		{
			new UpgradeableComponent(1, 1, 2)
		};
		Tags = new List<ItemTag> { ItemTag.ChessBuild };
		DependencyTags = new List<ItemTag> { ItemTag.ChessGenerator };
		ItemFunctionTags = new List<ItemFunctionTag> { ItemFunctionTag.SpecificMultiplier };
		EnablerItems = new List<Type>
		{
			typeof(FullMoon),
			typeof(HungrySnake)
		};
	}

	public override string GetDescription()
	{
		return $"If you make 3 or more non-adjacent moves in a word get {GameStatics.ZeroWidthCharacter}×{(float)(UpgradeableComponents[0].VariableValue * 100) / 100f}{GameStatics.ZeroWidthCharacter} WORD SCORE";
	}

	public override void ApplyWordBonus(ScoreCalcVizInfo step, int gridNumber, List<Tile> tiles, List<string> words, List<TileSelection> selections, List<HistoricWord> previousWords, GridData gridData)
	{
		if (tiles.Count == 0)
		{
			return;
		}
		int num = 0;
		List<Tile> list = new List<Tile>();
		for (int i = 1; i < tiles.Count; i++)
		{
			if (!GridUtility.Singleton.AreAdjacentTiles(tiles[i - 1], tiles[i]))
			{
				num++;
				list.Add(tiles[i]);
				list.Add(tiles[i - 1]);
			}
		}
		if (num >= 3)
		{
			step.WordBonus = new WordBonusToken(UpgradeableComponents[0].VariableValue * 100, isMultiplicative: true);
			step.LettersInWordToPulse.AddRange(list.Distinct().ToList());
			step.LettersOnGridToPulse.AddRange(list.Distinct().ToList());
		}
	}
}
