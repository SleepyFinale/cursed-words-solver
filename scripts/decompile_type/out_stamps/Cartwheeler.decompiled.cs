using System.Collections.Generic;
using UnityEngine;

public class Cartwheeler : Item
{
	public Cartwheeler()
	{
		Name = "Cartwheeler";
		SpriteData.Add(new ItemSpriteData(ItemSpriteUsage.Default, "Cartwheeler"));
		Rarity = ItemRarity.Rare;
		Cost = 18;
		Tags = new List<ItemTag>
		{
			ItemTag.BlankBuild,
			ItemTag.VoidBuild
		};
		ItemFunctionTags = new List<ItemFunctionTag> { ItemFunctionTag.GenericMultiplier };
	}

	public override string GetDescription()
	{
		return "For each tile in your word get ×-1.1 WORD SCORE";
	}

	public override void ApplyWordBonus(ScoreCalcVizInfo step, int gridNumber, List<Tile> tiles, List<string> words, List<TileSelection> selections, List<HistoricWord> previousWords, GridData gridData)
	{
		float num = 1f;
		foreach (Tile tile in tiles)
		{
			_ = tile;
			num *= -1.1f;
		}
		step.WordBonus = new WordBonusToken(Mathf.RoundToInt(num * 100f), isMultiplicative: true);
		step.LettersInWordToPulse.AddRange(tiles);
	}
}
