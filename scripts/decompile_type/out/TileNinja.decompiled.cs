// Decompiled from Assembly-CSharp.dll (Cursed Words 0.2.0)
// Source of truth for Tile Ninja cumulative word bonus.
using System.Collections.Generic;

public class TileNinja : Item
{
	public int ConsumableTilesUsed;

	public TileNinja()
	{
		Name = "Tile Ninja";
		SpriteData.Add(new ItemSpriteData(ItemSpriteUsage.Default, "TileNinja"));
		Rarity = ItemRarity.Rare;
		Cost = 18;
		Tags = new List<ItemTag> { ItemTag.ConsumableBuild };
		ItemFunctionTags = new List<ItemFunctionTag> { ItemFunctionTag.GenericMultiplier };
	}

	public override string GetDescription()
	{
		return $"Get x{(float)(120 + ConsumableTilesUsed * 2) / 100f} WORD SCORE (Place a consumable tile to improve by 0.02)";
	}

	public override void ApplyWordBonus(ScoreCalcVizInfo step, int gridNumber, List<Tile> tiles, List<string> words, List<TileSelection> selections, List<HistoricWord> previousWords, GridData gridData)
	{
		step.WordBonus = new WordBonusToken(120 + ConsumableTilesUsed * 2, isMultiplicative: true);
	}
}
