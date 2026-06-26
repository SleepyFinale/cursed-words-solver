using System.Collections.Generic;

public class CelestialBody : Item
{
	public CelestialBody()
	{
		Name = "Celestial Body";
		SpriteData.Add(new ItemSpriteData(ItemSpriteUsage.Default, "CelestialBody"));
		Rarity = ItemRarity.Common;
		Cost = 10;
		UpgradeableComponents = new List<UpgradeableComponent>
		{
			new UpgradeableComponent(1, 10, 10)
		};
		Tags = new List<ItemTag> { ItemTag.CardsBuild };
		DependencyTags = new List<ItemTag> { ItemTag.CardsGenerator };
		ItemFunctionTags = new List<ItemFunctionTag> { ItemFunctionTag.SpecificAdditive };
	}

	public override string GetDescription()
	{
		return $"Cards get {GameStatics.ZeroWidthCharacter}+{UpgradeableComponents[0].VariableValue}{GameStatics.ZeroWidthCharacter} TILE SCORE";
	}

	public override void ApplyTileBonus(ScoreCalcVizInfo step, int index, List<Tile> tiles, List<TileSelection> selections, List<HistoricWord> previousWords, GridData gridData)
	{
		if (tiles.Count != 0 && tiles[index].GetSuit() != 0)
		{
			step.TileScores[index] += (long)UpgradeableComponents[0].VariableValue;
		}
	}
}
