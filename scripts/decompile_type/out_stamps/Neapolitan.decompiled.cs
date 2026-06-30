using System.Collections.Generic;

public class Neapolitan : Item
{
	public int MulticolouredWordsSubmitted;

	public Neapolitan()
	{
		Name = "Neapolitan";
		SpriteData.Add(new ItemSpriteData(ItemSpriteUsage.Default, "Neapolitan"));
		Rarity = ItemRarity.Rare;
		Cost = 13;
		Tags = new List<ItemTag> { ItemTag.RainbowBuild };
		IsFood = true;
		ItemFunctionTags = new List<ItemFunctionTag> { ItemFunctionTag.SpecificMultiplier };
	}

	public override string GetDescription()
	{
		return $"Get ×{(float)(100 + MulticolouredWordsSubmitted * 5) / 100f} WORD SCORE (Improved by 0.05 by words with 3 or more different colours)";
	}

	public override void ApplyWordBonus(ScoreCalcVizInfo step, int gridNumber, List<Tile> tiles, List<string> words, List<TileSelection> selections, List<HistoricWord> previousWords, GridData gridData)
	{
		List<Tile> list = new List<Tile>();
		List<TileType> list2 = new List<TileType>();
		foreach (Tile tile in tiles)
		{
			TileType tileType = tile.GetTileType();
			if (!list2.Contains(tileType) && tileType != 0)
			{
				list.Add(tile);
				list2.Add(tileType);
			}
		}
		if (list2.Count >= 3)
		{
			MulticolouredWordsSubmitted++;
		}
		if (MulticolouredWordsSubmitted != 0)
		{
			step.WordBonus = new WordBonusToken(100 + MulticolouredWordsSubmitted * 5, isMultiplicative: true);
		}
	}
}
